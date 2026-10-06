#!/usr/bin/env python3
"""Metadata-only audit for the Root951 fresh116 registration.

This validator deliberately never opens a path referenced by a request unless
that path itself is a permitted metadata/source file.  In particular, manifest
JSON paths are recorded and checked as strings but are not opened: the manifest
may point into a scientific product tree.  No runner, runtime validator, or
renderer is imported or executed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parents[1]
INTEGRATION = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics"
)
CAMPAIGN = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02"
HANDOFF = CAMPAIGN / "handoff_20261003"
ROOT951 = HANDOFF / (
    "root_stage1_grounded116_manifest_path_repair1_full37_first_then_shared2_951"
)
ROOT950 = HANDOFF / (
    "root_stage1_grounded116_manifest_CLI_repair1_and_delegated_failure129_adoption_950"
)
ROOT946 = HANDOFF / (
    "root_stage1_actual945_manifest_dictrepr_CLI_failure_classification_grounded_repair1_946"
)
CHECKPOINT123 = HANDOFF / "ROOT_LIVE_RESUMPTION_CHECKPOINT_123.json"
WORKER116 = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/"
    "root_followup_116_f3_manifest_cli_binding_repair_v1/workers/"
    "nvme_render_successor.py"
)
ALLOWED_METADATA_SUFFIXES = {".json", ".py", ".txt", ".log"}
FORBIDDEN_SUFFIXES = {
    ".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu",
    ".npy", ".npz", ".raw", ".bin",
}
GI = 1024 ** 3


class AuditError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() not in ALLOWED_METADATA_SUFFIXES:
        raise AuditError(f"refusing non-metadata JSON path: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AuditError(f"expected JSON object: {path}")
    return value


def read_metadata_text(path: Path) -> str:
    if path.suffix.lower() not in ALLOWED_METADATA_SUFFIXES:
        raise AuditError(f"refusing non-source metadata path: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def metadata_sha256(path: Path) -> str:
    if path.suffix.lower() not in ALLOWED_METADATA_SUFFIXES:
        raise AuditError(f"refusing to hash non-metadata path: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def hex64(value: Any, label: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdefABCDEF" for c in value
    )


def extract_ids(value: Any, result: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"physical_case_id", "case_id", "id"} and isinstance(item, str):
                result.add(item)
            extract_ids(item, result)
    elif isinstance(value, list):
        for item in value:
            extract_ids(item, result)


def _proc_node(pid: str) -> dict[str, Any]:
    """Read one exact process and its direct children, never scan /proc."""
    proc = Path("/proc") / pid
    stat = (proc / "stat").read_text(encoding="utf-8")
    fields = stat.split()
    cmdline = (proc / "cmdline").read_text(encoding="utf-8").replace("\0", " ").strip()
    status = (proc / "status").read_text(encoding="utf-8", errors="replace")
    selected_status = {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in status.splitlines()
        if line.startswith(("Name:", "State:", "Pid:", "PPid:", "NSpid:"))
    }
    child_text = (proc / "task" / pid / "children").read_text(encoding="utf-8").strip()
    children = child_text.split() if child_text else []
    return {
        "pid": int(pid),
        "start_ticks": fields[21],
        "cmdline": cmdline,
        "status": selected_status,
        "children": [int(child) for child in children],
    }


def _proc_tree(root_pid: str, max_depth: int = 3) -> list[dict[str, Any]]:
    """Follow only descendants of the recorded Root951 controller PID."""
    nodes: list[dict[str, Any]] = []
    frontier = [(str(root_pid), 0)]
    seen: set[str] = set()
    while frontier:
        pid, depth = frontier.pop(0)
        if pid in seen or depth > max_depth:
            continue
        seen.add(pid)
        node = _proc_node(pid)
        node["depth"] = depth
        nodes.append(node)
        frontier.extend((str(child), depth + 1) for child in node["children"])
    return nodes


def proc_observation(launch: dict[str, Any], controller_path: Path) -> dict[str, Any]:
    """Read the exact Root951 controller tree and record live argv evidence."""
    pid = str(launch.get("pid"))
    out: dict[str, Any] = {
        "pid": launch.get("pid"),
        "expected_start_ticks": str(launch.get("proc_start_ticks")),
        "controller_path": str(controller_path),
        "observed": False,
        "start_ticks_match": False,
        "cmdline_matches_controller": False,
        "children": None,
        "receipt_observation": "none_found_at_audit_snapshot",
        "live_manifest_argv_observations": [],
    }
    try:
        nodes = _proc_tree(pid)
        controller = next(node for node in nodes if node["pid"] == int(pid))
        out.update(
            {
                "observed": True,
                "observed_start_ticks": controller["start_ticks"],
                "start_ticks_match": controller["start_ticks"] == str(launch.get("proc_start_ticks")),
                "cmdline": controller["cmdline"],
                "cmdline_matches_controller": str(controller_path) in controller["cmdline"],
                "children": controller["children"],
                "children_observed_empty": not bool(controller["children"]),
                "descendant_processes": nodes,
            }
        )
        for node in nodes:
            argv = node["cmdline"].split()
            if "--manifest" not in argv:
                continue
            index = argv.index("--manifest")
            value = argv[index + 1] if index + 1 < len(argv) else None
            out["live_manifest_argv_observations"].append(
                {
                    "pid": node["pid"],
                    "start_ticks": node["start_ticks"],
                    "manifest_arg": value,
                    "manifest_arg_is_absolute_json": isinstance(value, str) and Path(value).is_absolute() and value.endswith("/manifest.json"),
                    "argv_has_dict_repr": isinstance(value, str) and value.startswith("{") and "'" in value[:2],
                }
            )
    except (FileNotFoundError, PermissionError, IndexError, OSError, StopIteration) as exc:
        out["observation_error"] = type(exc).__name__
    return out


def audit() -> dict[str, Any]:
    cfg = load_json(ROOT951 / "controller-config.json")
    preflight = load_json(ROOT951 / "enabled37-metadata-preflight.json")
    launch = load_json(ROOT951 / "controller-launch-process.json")
    adoption = load_json(ROOT950 / "actual116-grounded-path-repair-adoption.json")
    tests = load_json(ROOT950 / "main-independent-tests.json")
    failure = load_json(ROOT946 / "actual-cli-manifest-failure-classification.json")
    checkpoint = load_json(CHECKPOINT123)

    request_paths = sorted((ROOT951 / "requests").glob("*.json"))
    wrapper_paths = sorted((ROOT951 / "wrapper-requests").glob("*.json"))
    require(len(request_paths) == 37, f"Root951 request count is {len(request_paths)}")
    require(len(wrapper_paths) == 37, f"Root951 wrapper count is {len(wrapper_paths)}")
    require(cfg.get("requested") == 37 and preflight.get("requested") == 37, "Root951 requested count mismatch")
    require(preflight.get("accepted199_excluded") is True, "accepted199 exclusion flag missing")
    require(preflight.get("case_credit") == 0 and cfg.get("case_credit") == 0, "Root951 case credit is not zero")
    require(preflight.get("main_science_payload_IO") is False, "Root951 source preparation claims payload IO")

    expected_worker = cfg.get("worker", {})
    require(expected_worker.get("path") == str(WORKER116), "Root951 worker path is not fresh116")
    worker_text = read_metadata_text(WORKER116)
    worker_sha = metadata_sha256(WORKER116)
    require(worker_sha == expected_worker.get("sha256"), "fresh116 worker digest differs from Root951 config")
    require("manifest_path = _absolute(request[\"manifest\"], \"manifest\")" in worker_text, "fresh116 manifest_path separation missing")
    require('"manifest": str(manifest_path)' in worker_text, "fresh116 absolute manifest return missing")
    require(adoption.get("worker116_schema") == "ds02.stage1.f3.fresh114.nvme-render-successor.v1", "Root950 worker schema mismatch")
    require(adoption.get("worker116_sha256") == worker_sha, "Root950 worker digest mismatch")
    require(adoption.get("source_adopted_byte_exact") is True, "Root950 adoption is not byte exact")
    require(adoption.get("original023_scientific_renderer_unchanged") is True, "Root950 does not preserve Root023")
    require(adoption.get("main_scientific_payload_IO") is False, "Root950 main payload IO flag is not closed")
    require(adoption.get("grounded_repair_number") == 1, "Root950 repair number mismatch")
    require(adoption.get("max_grounded_repairs_for_class") == 2, "Root950 repair limit mismatch")
    require(adoption.get("fresh129_delegated_actual945_failed1_noPNG_casecredit0_retained") is True, "Root950 failed-945 evidence retention missing")
    require(tests.get("actual_unittest_exit_code") == 0 and tests.get("actual_tests_run") == 10, "fresh116 independent tests not recorded as 10/0")
    require(failure.get("failure_class") == "manifest_JSON_object_string_passed_as_CLI_path", "Root946 failure class mismatch")
    require(failure.get("actual_manifest_argv_length") == 49002, "Root946 dict-repr argv length mismatch")
    require(failure.get("grounded_repair_number") == 1 and failure.get("max_grounded_repairs_per_class", failure.get("max_grounded_repairs_for_class")) == 2, "Root946 repair bound mismatch")
    require(failure.get("future36_held") == 36, "Root946 held count mismatch")
    require(failure.get("science_payload_IO_by_main") is False, "Root946 main payload IO flag is not closed")

    wrappers_by_pid: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in wrapper_paths:
        wrapper = load_json(path)
        pid = wrapper.get("physical_case_id")
        require(isinstance(pid, str) and pid not in wrappers_by_pid, f"duplicate/missing wrapper ID: {path}")
        wrappers_by_pid[pid] = (path, wrapper)

    pre_by_pid = {item.get("physical_case_id"): item for item in preflight.get("cases", [])}
    require(len(pre_by_pid) == 37, "preflight physical-case count mismatch")
    problems: list[dict[str, str]] = []
    cases: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    for request_path in request_paths:
        request = load_json(request_path)
        pid = request.get("physical_case_id")
        require(pid in wrappers_by_pid, f"request has no wrapper: {pid}")
        wrapper_path, wrapper = wrappers_by_pid[pid]
        family_counts[request.get("family_id")] += 1
        checks = {
            "identity": all(request.get(k) == wrapper.get(k) for k in ("family_id", "case_id", "physical_case_id", "attempt_id")),
            "manifest_absolute": isinstance(wrapper.get("manifest"), str) and Path(wrapper["manifest"]).is_absolute() and wrapper["manifest"].endswith("/manifest.json"),
            "renderer_template_path": (
                isinstance(wrapper.get("renderer_argv_template"), list)
                and "--manifest" in wrapper["renderer_argv_template"]
                and wrapper["renderer_argv_template"][wrapper["renderer_argv_template"].index("--manifest") + 1] == "{manifest}"
            ),
            "worker116_input": str(WORKER116) in wrapper.get("input_files", []) and wrapper.get("input_sha256", {}).get(str(WORKER116)) == worker_sha,
            "outer_worker116": "--worker" in request.get("command", []) and request["command"][request["command"].index("--worker") + 1] == str(WORKER116),
            "outer_wrapper": "--request" in request.get("command", []) and request["command"][request["command"].index("--request") + 1] == str(wrapper_path),
            "enabled": wrapper.get("disabled") is False and wrapper.get("source_only") is False and wrapper.get("launch") is True and wrapper.get("launch_allowed") is True and wrapper.get("execution_allowed") is True,
            "repair_class_bound": request.get("root_grounded_failure_class") == "manifest_dict_repr_used_as_cli_filename" and request.get("root_grounded_repair_number") == 1 and request.get("root_repair_limit_per_class") == 2,
            "failed945_reference": isinstance(request.get("root_failed945_request_preserved"), dict) and set(request["root_failed945_request_preserved"]) >= {"path", "sha256"},
            "case_credit_zero": request.get("independent_case_count_increment") == 0 and wrapper.get("no_science_payload_IO_by_source_preparation") is True,
            "input_map_closed": set(request.get("input_files", [])) == set(request.get("input_sha256", {})) and set(wrapper.get("input_files", [])) == set(wrapper.get("input_sha256", {})),
            "manifest_input_attested": wrapper.get("manifest") in wrapper.get("input_files", []),
            "wrapper_input_attested": str(wrapper_path) in request.get("input_files", []) and str(wrapper_path) in request.get("input_sha256", {}),
            "budget": all(
                (
                    wrapper.get("home_free_floor_bytes") == 500 * GI,
                    wrapper.get("home_publish_cap_bytes") == 3 * GI,
                    wrapper.get("nvme_free_floor_bytes") == 100 * GI,
                    wrapper.get("nvme_stage_cap_bytes") == 24 * GI,
                    wrapper.get("cpu_threads") == 24,
                    wrapper.get("declared_cpu_cores") == 24,
                    wrapper.get("environment_threads") == 2,
                    wrapper.get("max_wall_seconds") == 14400,
                    wrapper.get("global_renderer_cap") == 2,
                    wrapper.get("resource_ledger_lock") == "/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.lock",
                )
            ),
            "reservation_binding": wrapper.get("reservation_id") == wrapper.get("current_attempt_id") and str(wrapper.get("reservation_id", "")).endswith(str(wrapper.get("attempt_id", ""))),
            "digest_shapes": all(hex64(request.get(k), k) for k in ("physical_condition_sha256", "actual_converter_scope_sha256", "source_h5_producer_sha256")) and all(hex64(wrapper.get(k), k) for k in ("actual_converter_scope_sha256", "canonical_source_scope_sha256")),
        }
        for key, ok in checks.items():
            if not ok:
                problems.append({"physical_case_id": pid, "check": key})
        pre = pre_by_pid.get(pid)
        if not pre or pre.get("request", {}).get("path") != str(request_path) or pre.get("manifest_cli_is_exact_absolute_source_path") is not True or pre.get("case_credit") != 0:
            problems.append({"physical_case_id": pid, "check": "preflight_alignment"})
        cases.append(
            {
                "family_id": request.get("family_id"),
                "case_id": request.get("case_id"),
                "physical_case_id": pid,
                "request_path": str(request_path),
                "request_json_sha256": metadata_sha256(request_path),
                "wrapper_path": str(wrapper_path),
                "wrapper_json_sha256": metadata_sha256(wrapper_path),
                "attempt_id": request.get("attempt_id"),
                "manifest_path": wrapper.get("manifest"),
                "manifest_opened": False,
                "manifest_cli_binding_static_pass": all(checks.values()),
                "worker_schema": wrapper.get("schema"),
                "expected_frames": request.get("expected_frames"),
                "expected_particles": request.get("expected_particles"),
                "request_input_count": len(request.get("input_files", [])),
                "wrapper_input_count": len(wrapper.get("input_files", [])),
                "scientific_payload_refs_present_but_unopened": any(Path(str(x)).suffix.lower() in FORBIDDEN_SUFFIXES for x in set(request.get("input_files", [])) | set(wrapper.get("input_files", []))),
                "future_input_hashes_null": wrapper.get("future_input_hashes_null"),
                "case_credit": 0,
                "checks": checks,
            }
        )

    require(not problems, "Root951 static audit failures: " + json.dumps(problems[:5], sort_keys=True))
    require(dict(family_counts) == {"F2": 3, "F4": 10, "F5": 1, "F6": 23}, f"family counts mismatch: {family_counts}")

    # Check accepted checkpoint metadata without opening any decision's product files.
    accepted_paths = checkpoint.get("accepted_decisions", [])
    require(checkpoint.get("checkpoint") == 123 and len(accepted_paths) == 199, "accepted199 checkpoint is not 123/199")
    accepted_ids: set[str] = set()
    accepted_missing: list[str] = []
    for raw in accepted_paths:
        p = Path(raw)
        if p.suffix.lower() != ".json":
            raise AuditError(f"accepted decision is not JSON metadata: {p}")
        if not p.exists():
            accepted_missing.append(str(p))
            continue
        extract_ids(load_json(p), accepted_ids)
    current_ids = {case["physical_case_id"] for case in cases}
    overlap = sorted(current_ids & accepted_ids)
    require(not accepted_missing, f"accepted decision metadata missing: {accepted_missing[:3]}")
    require(not overlap, f"Root951 overlaps accepted199 physical IDs: {overlap}")

    process = proc_observation(launch, Path(launch["controller"]))
    receipt_count = 0
    receipt_metadata: list[dict[str, Any]] = []
    for case in cases:
        receipt = Path(case["attempt_id"])  # only to prevent accidental reuse below
        del receipt
        # attempt_root is metadata only; existence checks do not read payloads.
        q = load_json(Path(case["request_path"]))
        rp = Path(q["attempt_root"]) / "execution-receipt.json"
        if rp.exists():
            receipt_count += 1
            receipt = load_json(rp)
            receipt_metadata.append(
                {
                    "physical_case_id": case["physical_case_id"],
                    "path": str(rp),
                    "metadata_observation": "execution receipt JSON read; no product payload opened",
                    "status": receipt.get("status"),
                    "returncode": receipt.get("returncode"),
                    "pid": receipt.get("pid"),
                    "started_at_utc": receipt.get("started_at_utc"),
                    "command": receipt.get("command"),
                    "output_root": receipt.get("output_root"),
                    "production_product_acceptance": receipt.get("production_product_acceptance"),
                }
            )
    process["execution_receipts_found_at_audit"] = receipt_count
    process["receipt_observation"] = (
        "execution receipt metadata read; status remains running and no completed result inferred"
        if receipt_count
        else "none_found_at_audit_snapshot"
    )
    observed_args = process.get("live_manifest_argv_observations", [])
    known_manifests = {case["manifest_path"] for case in cases}
    for observation in observed_args:
        value = observation.get("manifest_arg")
        require(
            observation.get("manifest_arg_is_absolute_json") is True
            and observation.get("argv_has_dict_repr") is False
            and value in known_manifests,
            "live Root951 --manifest argv is not one of the registered absolute source paths",
        )
    process["actual_manifest_argv_observed"] = bool(observed_args)
    process["manifest_argv_note"] = (
        "Live descendant argv matched a registered absolute manifest path; no dict representation was observed."
        if observed_args
        else "No child existed at the exact PID observation; static wrapper template is the only path proof in this snapshot."
    )

    return {
        "schema": "ds02.stage1.f3.fresh117.root951-manifest-audit.v1",
        "package_id": "F3_fresh117_root951_manifest_cli_binding_audit",
        "source_only": True,
        "no_jobs_started_or_stopped_by_audit": True,
        "no_science_payload_opened_or_hashed_by_audit": True,
        "at_audit_process": "metadata-only",
        "root951": {
            "handoff": str(ROOT951),
            "requested": 37,
            "request_count": len(request_paths),
            "wrapper_count": len(wrapper_paths),
            "family_counts": dict(family_counts),
            "case_credit": 0,
            "accepted199_excluded": True,
            "accepted_checkpoint_path": str(CHECKPOINT123),
            "accepted_checkpoint": 123,
            "accepted_decision_count": 199,
            "accepted_id_overlap": overlap,
            "worker116_path": str(WORKER116),
            "worker116_sha256": worker_sha,
            "worker116_schema": adoption.get("worker116_schema"),
            "root951_grounded_repair_number": cfg.get("grounded_repair_number"),
            "root951_repair_limit_per_class": 2,
            "first_full_success_before_parallel2": launch.get("first_full_success_before_parallel2"),
            "science_only_via142_928": launch.get("science_only_via142_928"),
            "metadata_preflight_flags": {
                "manifest_cli_exact_absolute_source_path_all37": all(c["manifest_cli_binding_static_pass"] for c in cases),
                "main_science_payload_IO": preflight.get("main_science_payload_IO"),
                "home_floor_GiB": preflight.get("Home_floor_GiB"),
                "home_publication_hard_cap_GiB": preflight.get("Home_publication_hard_cap_GiB"),
            },
        },
        "root950_adoption": {
            "path": str(ROOT950 / "actual116-grounded-path-repair-adoption.json"),
            "source_adopted_byte_exact": adoption.get("source_adopted_byte_exact"),
            "worker116_schema": adoption.get("worker116_schema"),
            "worker116_sha256": adoption.get("worker116_sha256"),
            "independent_actual_manifest_metadata_path_equality_pass": adoption.get("independent_actual_manifest_metadata_path_equality_pass"),
            "original023_scientific_renderer_unchanged": adoption.get("original023_scientific_renderer_unchanged"),
            "fresh115_disabled_successor_superseded_by_registered948_remaining9": adoption.get("fresh115_disabled_successor_superseded_by_registered948_remaining9"),
            "fresh129_failed1_noPNG_casecredit0_retained": adoption.get("fresh129_delegated_actual945_failed1_noPNG_casecredit0_retained"),
            "main_scientific_payload_IO": adoption.get("main_scientific_payload_IO"),
            "independent_tests": {
                "path": str(ROOT950 / "main-independent-tests.json"),
                "actual_tests_run": tests.get("actual_tests_run"),
                "actual_unittest_exit_code": tests.get("actual_unittest_exit_code"),
                "science_payload_IO": tests.get("science_payload_IO"),
            },
        },
        "root946_failure_preservation": {
            "path": str(ROOT946 / "actual-cli-manifest-failure-classification.json"),
            "failure_class": failure.get("failure_class"),
            "actual_manifest_argv_length": failure.get("actual_manifest_argv_length"),
            "grounded_repair_number": failure.get("grounded_repair_number"),
            "max_grounded_repairs_per_class": failure.get("max_grounded_repairs_per_class", failure.get("max_grounded_repairs_for_class")),
            "future36_held": failure.get("future36_held"),
            "actual945_receipt": failure.get("actual945_first_receipt"),
            "actual945_request": failure.get("actual945_request"),
            "actual945_stdout": failure.get("actual945_stdout"),
            "main_science_payload_IO": failure.get("science_payload_IO_by_main"),
            "registered943_child_science_IO": failure.get("registered943_ParaView_child_scientific_XMF_H5_reads"),
            "preservation_note": "945 failure and 112/114/934 evidence remain historical; fresh117 does not reclassify them or grant credit.",
        },
        "controller_observation": process,
        "receipt_metadata_observation": receipt_metadata,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    try:
        report = audit()
    except (AuditError, OSError, json.JSONDecodeError) as exc:
        print(f"fresh117 validation failed: {exc}")
        return 1
    print(json.dumps({
        "schema": report["schema"],
        "requested": report["root951"]["requested"],
        "family_counts": report["root951"]["family_counts"],
        "static_manifest_bindings": report["root951"]["metadata_preflight_flags"]["manifest_cli_exact_absolute_source_path_all37"],
        "accepted199_overlap": report["root951"]["accepted_id_overlap"],
        "controller_observed": report["controller_observation"].get("observed"),
        "actual_manifest_argv_observed": report["controller_observation"].get("actual_manifest_argv_observed"),
        "execution_receipts_found": report["controller_observation"].get("execution_receipts_found_at_audit"),
        "no_science_payload_opened_or_hashed": report["no_science_payload_opened_or_hashed_by_audit"],
    }, indent=2))
    if args.write_report:
        out=PACKAGE/"metadata/fresh117-validator-report.json"
        out.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
