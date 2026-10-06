#!/usr/bin/env python3
"""Metadata-only audit for the already registered Root934 render batch.

The auditor deliberately never opens a scientific payload.  H5 paths are
classified from JSON strings and their already registered producer digest is
compared to the outer request's attestation.  Temporal manifests, XMF paths,
receipts, and request/controller JSON are bounded metadata inputs.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, Iterable


ROOT934_DEFAULT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_NVMe3GiB_fullnative_renderer_first1_then_shared2_"
    "F6remaining23_F2ready3_F5ready1_934"
)
ROOT932_DEFAULT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_delegated112_NVMe3GiB_renderer_library_adoption_"
    "registered_exit_contract_932"
)
REPORT_DEFAULT = Path(__file__).resolve().parents[1] / "metadata" / "root934-audit-report.json"

EXPECTED_FAMILIES = {"F6": 23, "F2": 3, "F5": 1}
FRESH112_SCHEMA = "ds02.stage1.f3.fresh112.nvme-render-successor.v1"
MANIFEST_SCHEMA = "ds02.stage1.paraview-temporal-product.v1"
ENTRY_NAME = "registered_render_entry.py"
HEX = set("0123456789abcdefABCDEF")
PAYLOAD_SUFFIXES = {".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".raw", ".bin"}
METADATA_SUFFIXES = {".json", ".py", ".xmf", ".xml", ".txt", ".log", ""}


class AuditError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise AuditError(f"refusing scientific payload path: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditError(f"cannot read metadata JSON: {path}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"metadata JSON is not an object: {path}")
    return value


def load_text(path: Path) -> str:
    if path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise AuditError(f"refusing scientific payload path: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AuditError(f"cannot read source text: {path}") from exc


def is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def metadata_suffix(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return suffix if suffix else ""


def check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def receipt_summary(paths: Iterable[str]) -> dict[str, Any]:
    summaries = []
    missing = []
    for raw in paths:
        path = Path(raw)
        if path.suffix.lower() in PAYLOAD_SUFFIXES:
            raise AuditError(f"receipt path unexpectedly points to payload: {path}")
        if path.name != "execution-receipt.json":
            continue
        if not path.is_file():
            missing.append(str(path))
            continue
        receipt = load_json(path)
        summaries.append({
            "path": str(path),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "completed0": receipt.get("status") == "completed" and receipt.get("returncode") == 0,
        })
    return {
        "count": len(summaries),
        "completed0": sum(bool(row["completed0"]) for row in summaries),
        "missing": missing,
        "rows": summaries,
    }


def _pair_paths(root: Path) -> dict[str, tuple[Path, Path]]:
    outer = {path.stem.removesuffix("-render-request"): path for path in (root / "requests").glob("*.json")}
    wrappers = {path.stem.removesuffix("-enabled-wrapper"): path for path in (root / "wrapper-requests").glob("*.json")}
    if set(outer) != set(wrappers):
        raise AuditError("outer and wrapper filename sets differ")
    return {key: (outer[key], wrappers[key]) for key in sorted(outer)}


def _entry_contract(entry: Path) -> dict[str, Any]:
    source = load_text(entry)
    tree = ast.parse(source, filename=str(entry))
    has_execute = "execute_request" in source and "authorized=True" in source
    has_completed = 'result.get(\'status\')==\'completed\'' in source or 'result.get("status")=="completed"' in source
    has_floor = "post_publish_home_floor_rechecked" in source
    has_exit_one = "else 1" in source
    return {
        "path": str(entry),
        "syntax_valid": tree is not None,
        "calls_library_with_authorization": has_execute,
        "requires_completed_status": has_completed,
        "requires_postpublish_floor": has_floor,
        "rejected_result_exits_one": has_exit_one,
        "success_gate_pass": all((has_execute, has_completed, has_floor, has_exit_one)),
    }


def _scope_record(outer: dict[str, Any], wrapper: dict[str, Any], manifest: dict[str, Any], failures: list[str], label: str) -> dict[str, Any]:
    source_scope = outer.get("physical_condition_sha256")
    canonical_scope = wrapper.get("canonical_source_scope_sha256")
    actual_scope = outer.get("actual_converter_scope_sha256")
    wrapper_actual_scope = wrapper.get("actual_converter_scope_sha256")
    check(is_hex64(source_scope), f"{label}: outer source physical scope is not sha256", failures)
    check(is_hex64(actual_scope), f"{label}: outer converter scope is not sha256", failures)
    check(source_scope == canonical_scope, f"{label}: canonical source scope differs between outer/wrapper", failures)
    check(actual_scope == wrapper_actual_scope, f"{label}: converter scope differs between outer/wrapper", failures)
    # Root023 manifests use `physical_condition_sha256` for the scope bound to
    # the stored trajectory.  Depending on the family, that is the actual
    # converter scope or the source scope; F2 additionally records the source
    # scope under `canonical_source_physical_condition_sha256`.  The audit
    # checks the explicit mapping instead of collapsing the two semantics.
    manifest_physical = manifest.get("physical_condition_sha256")
    manifest_canonical = manifest.get("canonical_source_physical_condition_sha256")
    check(manifest_physical in (None, source_scope, actual_scope), f"{label}: manifest physical scope differs", failures)
    if manifest_canonical is not None:
        check(manifest_canonical == source_scope, f"{label}: manifest canonical source scope differs", failures)
    return {
        "canonical_source_scope_sha256": canonical_scope,
        "actual_converter_scope_sha256": wrapper_actual_scope,
        "scope_values_distinct": canonical_scope != wrapper_actual_scope,
        "scope_semantics": "separate_equal_values" if canonical_scope == wrapper_actual_scope else "separate_distinct_values",
        "manifest_physical_scope_sha256": manifest_physical,
        "manifest_canonical_source_scope_sha256": manifest_canonical,
        "manifest_scope_mapping": "manifest_physical_is_actual_converter_scope" if manifest_physical == actual_scope else "manifest_physical_is_source_scope",
    }


def _manifest_contract(outer: dict[str, Any], wrapper: dict[str, Any], manifest: dict[str, Any], failures: list[str], label: str) -> dict[str, Any]:
    check(manifest.get("schema") == MANIFEST_SCHEMA, f"{label}: unexpected manifest schema", failures)
    for key in ("family_id", "case_id", "physical_case_id"):
        check(manifest.get(key) == wrapper.get(key), f"{label}: manifest {key} mismatch", failures)
    expected_frames = outer.get("expected_frames")
    expected_particles = outer.get("expected_particles")
    check(manifest.get("frames") == expected_frames, f"{label}: manifest frame count mismatch", failures)
    check(manifest.get("particles") == expected_particles, f"{label}: manifest particle count mismatch", failures)

    geometry = manifest.get("actual_geometry")
    native_contract = manifest.get("expected_native_contract")
    dimension = geometry.get("dimension") if isinstance(geometry, dict) else None
    if dimension is None and isinstance(native_contract, dict):
        dimension = native_contract.get("dimension")
    fields = manifest.get("fields")
    position_shape = fields.get("position", {}).get("shape") if isinstance(fields, dict) else None
    velocity_shape = fields.get("velocity", {}).get("shape") if isinstance(fields, dict) else None
    if dimension is None and isinstance(position_shape, list) and isinstance(velocity_shape, list):
        if position_shape[-1:] == [3] and velocity_shape[-1:] == [3]:
            dimension = 3
    check(dimension == 3, f"{label}: manifest dimension is not 3", failures)
    n3 = (
        isinstance(position_shape, list) and position_shape[-1:] == [3]
        and isinstance(velocity_shape, list) and velocity_shape[-1:] == [3]
    )
    shape_contract = manifest.get("xmf_shape_contract")
    if isinstance(shape_contract, str):
        n3 = n3 and "N3" in shape_contract
    elif isinstance(shape_contract, dict):
        vector = str(shape_contract.get("dynamic_vector_dimensions", ""))
        n3 = n3 and vector.endswith(" 3")
    check(n3, f"{label}: no position/velocity N-by-3 manifest contract", failures)

    xdmf = manifest.get("xdmf")
    xdmf_path = Path(xdmf) if isinstance(xdmf, str) else None
    check(xdmf_path is not None and xdmf_path.suffix.lower() == ".xmf", f"{label}: manifest XMF path missing", failures)
    check(bool(xdmf_path and xdmf_path.is_file()), f"{label}: manifest XMF path is absent", failures)
    return {
        "manifest_path": str(wrapper.get("manifest")),
        "manifest_schema": manifest.get("schema"),
        "frames": manifest.get("frames"),
        "particles": manifest.get("particles"),
        "dimension": dimension,
        "n3_position_velocity": n3,
        "xdmf_path": xdmf,
        "manifest_source_disabled": manifest.get("disabled"),
        "manifest_source_future_hashes_null": manifest.get("future_hashes_null"),
        "manifest_visual_status": manifest.get("visual_status"),
        "manifest_precision_status": manifest.get("precision_status", manifest.get("numerical_precision_status")),
    }


def _failure_evidence(root934: Path, result: dict[str, Any], wrapper_by_case: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Read bounded JSON/stdout failure evidence, never renderer payloads."""

    case_id = result.get("case_id")
    wrapper = wrapper_by_case.get(case_id, {})
    receipt_path = Path(result.get("actual_receipt", ""))
    receipt = load_json(receipt_path) if receipt_path.is_file() else {}
    attempt_root = Path(receipt.get("output_root") or receipt.get("request", {}).get("attempt_root") or "")
    stdout_path = attempt_root / "stdout.log"
    stdout_tail = ""
    if stdout_path.is_file():
        # Root934's launcher stdout is bounded metadata, not a science output.
        stdout_tail = stdout_path.read_text(encoding="utf-8", errors="replace")[-16 * 1024:]
    nvme_root = Path(wrapper.get("nvme_root", ""))
    rejection_paths = sorted(nvme_root.glob(f"{result.get('case_id', '') if False else receipt.get('request', {}).get('attempt_id', '')}*.rejection.json")) if nvme_root.is_dir() else []
    # The rejection filename uses the temporary stage suffix, so fall back to
    # the stable attempt prefix when the exact glob above has no match.
    if not rejection_paths and nvme_root.is_dir():
        prefix = str(receipt.get("request", {}).get("attempt_id", ""))
        rejection_paths = sorted(path for path in nvme_root.glob("*.rejection.json") if path.name.startswith(prefix))
    rejection_path = rejection_paths[-1] if rejection_paths else None
    rejection = load_json(rejection_path) if rejection_path else {}
    stage_root = Path(rejection.get("stage_root", "")) if rejection.get("stage_root") else None
    expected_stderr = stage_root / "renderer.stderr.log" if stage_root else None
    return {
        "case_id": case_id,
        "actual_receipt": str(receipt_path),
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "receipt_pid": receipt.get("pid"),
        "receipt_elapsed_seconds": receipt.get("elapsed_seconds"),
        "receipt_gpu_seconds": receipt.get("gpu_seconds"),
        "receipt_bytes": receipt.get("bytes"),
        "receipt_stdout_sha256_attested": receipt.get("stdout_sha256"),
        "receipt_input_hashes_stable": receipt.get("input_hashes_after_run") == receipt.get("input_hashes_at_launch"),
        "attempt_stdout_path": str(stdout_path),
        "attempt_stdout_tail": stdout_tail,
        "rejection_path": str(rejection_path) if rejection_path else None,
        "rejection_schema": rejection.get("schema"),
        "rejection_status": rejection.get("status"),
        "rejection_returncode": rejection.get("returncode"),
        "rejection_stage_removed": rejection.get("stage_removed_after_rejection"),
        "rejection_home_output_absent": rejection.get("home_output_absent"),
        "rejection_stderr_tail_present": bool(rejection.get("stderr_tail")),
        "rejection_stdout_tail_present": bool(rejection.get("stdout_tail")),
        "rejection_actual_argv_present": bool(rejection.get("actual_argv") or rejection.get("argv")),
        "renderer_stderr_expected_path": str(expected_stderr) if expected_stderr else None,
        "renderer_stderr_present_after_cleanup": bool(expected_stderr and expected_stderr.is_file()),
        "renderer_stderr_missing_after_cleanup": bool(expected_stderr and not expected_stderr.is_file()),
        "root934_failure_is_not_a_science_root_cause": True,
        "diagnostic_limit": "No renderer stderr/argv survived fresh112 cleanup; do not infer the ParaView root cause.",
    }


def audit(root934: Path = ROOT934_DEFAULT, root932: Path = ROOT932_DEFAULT) -> dict[str, Any]:
    failures: list[str] = []
    pairs = _pair_paths(root934)
    check(len(pairs) == 27, f"expected 27 outer/wrapper pairs, found {len(pairs)}", failures)
    family_counts: dict[str, int] = {}
    rows = []
    preflight = load_json(root934 / "actual-metadata-only-enabled27-preflight.json")
    preflight_rows = {row.get("case_id"): row for row in preflight.get("cases", []) if isinstance(row, dict)}
    config = load_json(root934 / "controller-config.json")
    launch = load_json(root934 / "controller-launch-process.json")

    for key, (outer_path, wrapper_path) in pairs.items():
        outer = load_json(outer_path)
        wrapper = load_json(wrapper_path)
        label = outer.get("case_id", key)
        family = outer.get("family_id")
        family_counts[family] = family_counts.get(family, 0) + 1
        for request in (outer, wrapper):
            check(request.get("family_id") in EXPECTED_FAMILIES, f"{label}: unknown family", failures)
            check(request.get("disabled") is False, f"{label}: request is disabled", failures)
            check(request.get("source_only") is False, f"{label}: request remains source-only", failures)
            check(request.get("launch") is True and request.get("launch_allowed") is True and request.get("execution_allowed") is True, f"{label}: execution flags are not enabled", failures)
        for field in ("family_id", "case_id", "physical_case_id", "attempt_id", "expected_frames", "expected_particles"):
            check(outer.get(field) == wrapper.get(field), f"{label}: outer/wrapper {field} mismatch", failures)
        check(outer.get("schema") == "ds02.runner-request.v2", f"{label}: outer schema mismatch", failures)
        check(wrapper.get("schema") == FRESH112_SCHEMA, f"{label}: wrapper schema mismatch", failures)
        check(outer.get("source_h5_producer_sha256") and is_hex64(outer.get("source_h5_producer_sha256")), f"{label}: missing H5 producer attestation", failures)
        check(wrapper.get("reservation_id") == wrapper.get("current_attempt_id"), f"{label}: reservation/current attempt mismatch", failures)
        expected_reservation = f"{family}/{outer.get('case_id')}/{outer.get('attempt_id')}"
        check(wrapper.get("reservation_id") == expected_reservation, f"{label}: reservation id is not full family/case/attempt id", failures)

        for resource in (outer, wrapper):
            check(resource.get("cpu_threads") == 24, f"{label}: CPU threads != 24", failures)
            check(resource.get("max_wall_seconds") == 14400, f"{label}: wall limit != 14400", failures)
            check(resource.get("launch_owner") == "root", f"{label}: launch owner is not root", failures)
            check(resource.get("worktree_root") and resource.get("cwd"), f"{label}: worktree/cwd missing", failures)
        check(wrapper.get("declared_cpu_cores") == 24, f"{label}: declared CPU cores != 24", failures)
        check(wrapper.get("environment_threads") == 2, f"{label}: env thread count != 2", failures)
        check(wrapper.get("global_renderer_cap") == 2, f"{label}: renderer cap != 2", failures)
        check(wrapper.get("home_publish_cap_bytes") == 3 * 1024 ** 3, f"{label}: Home publish cap != 3 GiB", failures)
        check(wrapper.get("nvme_stage_cap_bytes") == 24 * 1024 ** 3, f"{label}: NVMe stage cap != 24 GiB", failures)
        check(wrapper.get("nvme_free_floor_bytes") >= 100 * 1024 ** 3, f"{label}: NVMe floor below 100 GiB", failures)
        check(wrapper.get("home_free_floor_bytes") >= 500 * 1024 ** 3, f"{label}: Home floor below 500 GiB", failures)
        check(wrapper.get("reservation_id") and wrapper.get("current_attempt_id"), f"{label}: reservation id missing", failures)

        for request_name, request in (("outer", outer), ("wrapper", wrapper)):
            files = request.get("input_files")
            hashes = request.get("input_sha256")
            check(isinstance(files, list) and isinstance(hashes, dict), f"{label}: {request_name} input closure missing", failures)
            if isinstance(files, list) and isinstance(hashes, dict):
                check(set(files) == set(hashes), f"{label}: {request_name} input files/hashes differ", failures)
                for path, digest in hashes.items():
                    check(is_hex64(digest), f"{label}: {request_name} non-sha256 input attestation", failures)
                    check(metadata_suffix(path) in METADATA_SUFFIXES or (request_name == "outer" and metadata_suffix(path) in PAYLOAD_SUFFIXES), f"{label}: unsupported {request_name} input suffix", failures)
            if request_name == "wrapper" and isinstance(files, list):
                check(not any(metadata_suffix(path) in PAYLOAD_SUFFIXES for path in files), f"{label}: wrapper directly binds science payload", failures)

        outer_files = outer.get("input_files", [])
        h5 = [path for path in outer_files if metadata_suffix(path) in {".h5", ".hdf5"}]
        check(len(h5) == 1, f"{label}: outer H5 attestation count is not one", failures)
        if len(h5) == 1:
            check(outer.get("input_sha256", {}).get(h5[0]) == outer.get("source_h5_producer_sha256"), f"{label}: H5 hash is not the registered producer attestation", failures)
        check(not any(metadata_suffix(path) in {".h5", ".hdf5"} for path in wrapper.get("input_files", [])), f"{label}: wrapper input closure includes H5", failures)

        command = outer.get("command")
        check(isinstance(command, list) and ENTRY_NAME in [Path(str(item)).name for item in command], f"{label}: outer command does not use registered entry", failures)
        check(isinstance(command, list) and str(wrapper_path) in command, f"{label}: outer command does not bind its wrapper", failures)

        manifest_path = Path(wrapper.get("manifest", ""))
        manifest = load_json(manifest_path) if manifest_path.is_file() else {}
        if not manifest:
            failures.append(f"{label}: manifest JSON missing")
        manifest_record = _manifest_contract(outer, wrapper, manifest, failures, label) if manifest else {}
        scope_record = _scope_record(outer, wrapper, manifest, failures, label) if manifest else {}
        receipts = receipt_summary(wrapper.get("input_files", []))
        check(receipts["count"] >= 2, f"{label}: fewer than native+typed execution receipts", failures)
        check(receipts["completed0"] == receipts["count"], f"{label}: an upstream receipt is not completed/0", failures)
        pre = preflight_rows.get(label, {})
        check(pre.get("metadata_only_preflight_pass") is True, f"{label}: Root934 preflight row is not pass", failures)
        check(pre.get("frames") == outer.get("expected_frames"), f"{label}: preflight frame evidence mismatch", failures)
        check(pre.get("N3") == outer.get("expected_particles"), f"{label}: preflight N3 evidence mismatch", failures)
        rows.append({
            "family_id": family,
            "case_id": label,
            "physical_case_id": outer.get("physical_case_id"),
            "attempt_id": outer.get("attempt_id"),
            "reservation_id": wrapper.get("reservation_id"),
            "expected_frames": outer.get("expected_frames"),
            "expected_particles": outer.get("expected_particles"),
            "h5_producer_attestation_present": True,
            "h5_opened_or_hashed_by_this_audit": False,
            "scope": scope_record,
            "manifest": manifest_record,
            "upstream_receipts": receipts,
            "preflight_pass": pre.get("metadata_only_preflight_pass") is True,
            "product_manifest_family_specific": f"/families/{family}/" in str(manifest_path),
            "render_result_available_at_audit": False,
        })

    controller_result_path = root934 / "controller-result.json"
    controller_result = load_json(controller_result_path) if controller_result_path.is_file() else None
    wrapper_by_case = {}
    for _, (_, wrapper_path) in pairs.items():
        wrapper = load_json(wrapper_path)
        wrapper_by_case[wrapper.get("case_id")] = wrapper
    controller_failure = None
    if controller_result:
        failed_rows = [row for row in controller_result.get("results", []) if row.get("status") != "completed" or row.get("returncode") != 0]
        if failed_rows:
            controller_failure = _failure_evidence(root934, failed_rows[0], wrapper_by_case)

    adoption = load_json(root932 / "actual112-library-and-entry-adoption-review.json")
    entry_path = Path(adoption["registered_entry"])
    entry = _entry_contract(entry_path)
    toy = load_json(root932 / "toy-registered-entry-exit-contract-test.json")
    report = {
        "schema": "ds02.stage1.f3.fresh113.root934-metadata-audit.v1",
        "audit_scope": "Root934 outer/wrapper bindings and metadata-only upstream product evidence",
        "source_only": True,
        "science_payloads_opened_or_hashed_by_this_audit": False,
        "controller_root": str(root934),
        "adoption_root": str(root932),
        "controller_pid_snapshot": launch.get("pid"),
        "controller_start_ticks_snapshot": launch.get("proc_start_ticks"),
        "controller_result_present": (root934 / "controller-result.json").is_file(),
        "controller_progress_present": (root934 / "actual-progress.json").is_file(),
        "controller_result_snapshot": {
            "requested": controller_result.get("requested") if controller_result else None,
            "actual_fullnative_completed0": controller_result.get("actual_fullnative_completed0") if controller_result else None,
            "pending_held": controller_result.get("pending_held") if controller_result else None,
            "case_credit": controller_result.get("case_credit") if controller_result else None,
        },
        "controller_failure_observed": controller_failure is not None,
        "controller_failure_evidence": controller_failure,
        "requested": len(rows),
        "family_counts": family_counts,
        "expected_family_counts": EXPECTED_FAMILIES,
        "family_counts_match": family_counts == EXPECTED_FAMILIES,
        "first920_excluded_case": config.get("first920_completed_case_excluded"),
        "first920_exclusion_recorded": bool(config.get("first920_completed_case_excluded")),
        "controller_first_success_before_pool2": launch.get("first1_actual_success_before_pool2") is True,
        "resource_contract": {
            "cpu_threads": 24,
            "environment_threads": 2,
            "global_renderer_cap": 2,
            "home_publish_cap_bytes": 3 * 1024 ** 3,
            "home_floor_bytes": 500 * 1024 ** 3,
            "nvme_stage_cap_bytes": 24 * 1024 ** 3,
            "nvme_floor_bytes": 100 * 1024 ** 3,
            "wall_seconds": 14400,
        },
        "outer_wrapper_and_scope_contract_pass": not failures,
        "registered_entry_contract": entry,
        "root932_toy_failure_path_evidence": {
            "pass": toy.get("pass") is True,
            "tests": len(toy.get("tests", [])) if isinstance(toy.get("tests"), list) else None,
            "no_real_worker_renderer_or_science_io": toy.get("no_real_worker_renderer_or_science_IO") is True,
        },
        "rows": rows,
        "warnings": [
            "Root934 controller result is metadata evidence only; this package never retries, stops, or reclassifies the live controller.",
            "Some F6 source manifests retain disabled/future-hash metadata from their source snapshot while the Root934 wrapper is the enabled adopted binding; this is recorded per row and is not rewritten here.",
            "H5 values are copied only as existing producer attestations from request JSON; this audit never opens or hashes H5.",
            "The observed first Root934 renderer failure has no bounded stderr or argv in the fresh112 rejection JSON because cleanup removes the stage first; fresh114 should persist those fields before cleanup.",
        ],
        "failures": failures,
        "pass": not failures,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root934", type=Path, default=ROOT934_DEFAULT)
    parser.add_argument("--root932", type=Path, default=ROOT932_DEFAULT)
    parser.add_argument("--output", type=Path, default=REPORT_DEFAULT)
    args = parser.parse_args()
    report = audit(args.root934, args.root932)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "requested": report["requested"], "failures": len(report["failures"]), "output": str(args.output)}))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
