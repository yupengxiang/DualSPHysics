#!/usr/bin/env python3
"""Build the source-only ROOT231 query-2/3/4 endpoint request.

This is an additive successor to the consumed ROOT225 request.  It binds
the ROOT223/ROOT207 component-space producer chain and ROOT217 decoder
calibration, but leaves all native Part files deferred to the parent guard.
The request is V8-shaped (``kind=cpu`` and explicit input/runtime records),
while the scientific scope remains diagnostics-only: world-axis calibration,
interpolation, output error, spatial truth, and QI/QN/QE remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import stage2_f1_s2_query_endpoint_observer_v1 as legacy


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f1_s2_query_endpoint_observer_v2.py"
LEGACY_WORKER = HERE / "stage2_f1_s2_query_endpoint_observer_v1.py"
CONTRACT = HERE / "stage2_f1_s2_query_endpoint_followup_plan_v1.json"
CALIBRATED = HERE / "stage2_f1_native_selected_observer_v1.py"
BASE_OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYTHON_TARGET = Path("/usr/bin/python3.10")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")
ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ROOT223_PROOF = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_S2_COMPONENT_COMPARE_V1_ACTUAL_ROOT_VERIFICATION_223.json"
ROOT223_SHA = "23f79366541c609e3cfb42c99ec0419ddf4fecca63aaf9d5c12c9ecbc22a9b84"
ROOT207_SHA = "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab"
ROOT207_CHILD_SHA = "d588f17021c3b1418ac73e343d6c323f2d8850d2be1148d39bba7243ce101fb2"
ROOT217_PROOF = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json"
ROOT217_SHA = "7df9b02c339e3b3eb8bae8f108c16d5db0fd2b6cb3f03d192c4edc827ae1bdf0"
ROOT217_REPORT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/STAGE2_F1_BI4_OFFICIAL_WRITER_CALIBRATION_ROOT217_V4/f1-bi4-official-writer-calibration-v4-root-217-001-root-forward-030-001/observer/official-writer-calibration-v4.json")
ROOT217_REPORT_SHA = "2a8cb45871d6604c49e01c1577c5cb66ea73f3e3da22f9d3f043bf2a719b8356"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.query-endpoint-request.v2"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.query-endpoint-manifest.v2"
QUERY_TIMES_S = (2.0, 3.0, 4.0)
MAX_SMALL_BYTES = 16 * 1024 * 1024
MAX_NATIVE_BYTES = 512 * 1024 * 1024
NATIVE_READ_PASSES = 4


class BuildError(RuntimeError):
    pass


def stable_hash(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise BuildError(f"{label} exceeds bounded preparation read: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    sig_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    sig_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if sig_before != sig_after:
        raise BuildError(f"{label} changed while being read: {path}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(after.st_size),
        "sha256": digest.hexdigest(),
        "stat": {"dev": int(after.st_dev), "ino": int(after.st_ino), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns)},
    }


def read_json(path: Path, label: str, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    record = stable_hash(path, label)
    if expected_sha is not None and record["sha256"] != expected_sha:
        raise BuildError(f"{label} SHA mismatch: {record['sha256']} != {expected_sha}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"{label} root is not an object")
    return value, record


def write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _receipt_for_runparts(runparts: Path) -> Path:
    return runparts.parents[1] / "execution-receipt.json"


def _query_records(rows: list[dict[str, Any]], query: float) -> tuple[dict[str, Any], dict[str, Any]]:
    lower = [row for row in rows if row["time_s"] <= query]
    upper = [row for row in rows if row["time_s"] >= query]
    if not lower or not upper:
        raise BuildError(f"query {query} is outside actual saved window")
    return max(lower, key=lambda row: row["time_s"]), min(upper, key=lambda row: row["time_s"])


def _case_grid(case: dict[str, Any], label: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = case.get("source")
    identity = case.get("identity")
    if not isinstance(source, dict) or not isinstance(identity, dict):
        raise BuildError(f"{label} ROOT207 child case lacks source/identity")
    runparts = Path(source["runparts"]["path"])
    generated_xml = Path(source["generated_xml"]["path"])
    raw_root = Path(source["raw_root"])
    decoder = Path(source["decoder"]["path"])
    decoder_source = Path(source["decoder_source"]["path"])
    receipt, receipt_rec = read_json(_receipt_for_runparts(runparts), f"{label} solver receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (0, "0"):
        raise BuildError(f"{label} solver receipt is not completed/0")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise BuildError(f"{label} receipt has no request")
    physical = identity.get("physical_case_id")
    if label in {"coarse", "fine"}:
        if request.get("family_id") != "F1" or request.get("sentinel_id") != "F1-S2" or request.get("physical_case_id") != physical:
            raise BuildError(f"{label} physical request identity mismatch")
        identity_status = "REQUEST_V1_F1_S2_PHYSICAL_IDENTITY"
    else:
        if request.get("family_id") != "F1" or request.get("case_id") != "F1_STAGE1_DUAL_H340_DP020" or request.get("sentinel_id") is not None or request.get("physical_case_id") != physical:
            raise BuildError(f"{label} historical request identity mismatch")
        identity_status = "HISTORICAL_RUNNER_V2_EXACT_F1_CASE_ID_PHYSICAL_IDENTITY_ABSENT"
    runparts_rec = stable_hash(runparts, f"{label} RunPARTs")
    xml_rec = stable_hash(generated_xml, f"{label} generated XML")
    decoder_rec = stable_hash(decoder, f"{label} official decoder")
    decoder_source_rec = stable_hash(decoder_source, f"{label} decoder source")
    rows = legacy._parse_runparts(runparts.read_bytes(), f"{label} RunPARTs")
    queries: list[dict[str, Any]] = []
    selected: dict[int, dict[str, Any]] = {}
    for query in QUERY_TIMES_S:
        lower, upper = _query_records(rows, query)
        queries.append({"query_time_s": query, "lower": lower, "upper": upper, "interpolation": "NOT_PERFORMED", "extrapolation": "FORBIDDEN", "selected_row_index_is_not_native_frame_id": True})
        selected[int(lower["frame"])] = lower
        selected[int(upper["frame"])] = upper
    command = request.get("command")
    tout = legacy._command_tout(command)
    xml_tout = legacy._xml_timeout(generated_xml.read_bytes(), f"{label} generated XML")
    receipt_tout = legacy._command_tout(receipt.get("command"))
    if tout is None or xml_tout is None or receipt_tout is None or tout != receipt_tout:
        raise BuildError(f"{label} lacks consistent XML/request/receipt tout metadata")
    grid = {
        "label": label,
        "case_label": case.get("label"),
        "identity": identity,
        "raw_root": str(raw_root),
        "runparts": runparts_rec,
        "generated_xml": xml_rec,
        "solver_receipt": receipt_rec,
        "decoder": decoder_rec,
        "decoder_source": decoder_source_rec,
        "expected_frame_count": len(rows),
        "first_frame": rows[0],
        "last_frame": rows[-1],
        "queries": queries,
        "selected_frames": sorted(selected),
        "xml_TimeOut_s": float(xml_tout),
        "actual_request_tout_s": float(tout),
        "actual_request_command": command,
        "actual_request_sha256": receipt.get("request_sha256"),
        "receipt_identity_status": identity_status,
        "run_txt_present": (runparts.parents[1] / "Run.txt").is_file(),
        "run_out_present": (runparts.parents[1] / "Run.out").is_file(),
        "control_status": "RUNTIME_RECEIPT_OVERRIDE_VERIFIED" if float(tout) != float(xml_tout) else "RECEIPT_TIME_OUT_MATCHES_GENERATED_XML",
    }
    deferred = []
    for frame in sorted(selected):
        endpoint_labels = [
            f"q{int(query['query_time_s'])}_{side}"
            for query in queries
            for side in ("lower", "upper")
            if int(query[side]["frame"]) == frame
        ]
        deferred.append({
            "path": str(raw_root / f"Part_{frame:04d}.bi4"),
            "grid": label,
            "frame": frame,
            "endpoint_labels": endpoint_labels,
            "expected_time_s": selected[frame]["time_s"],
            "sha256": "PARENT_AFTER_RESERVATION",
            "stat_at_prepare": "UNKNOWN_UNTIL_PARENT_RESERVATION",
            "worker_owned_after_reservation": True,
        })
    return grid, [receipt_rec, runparts_rec, xml_rec, decoder_rec, decoder_source_rec], deferred


def build(output_manifest: Path, output_request: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan, plan_rec = read_json(CONTRACT, "ROOT231 follow-up plan")
    if plan.get("schema") != "ds02.stage2.f1-s2.query-endpoint-followup-plan.v1" or plan.get("status") != "PRE_REGISTERED_LAUNCH_DISABLED":
        raise BuildError("ROOT231 follow-up plan schema/status mismatch")
    if plan.get("queries", {}).get("times_s") != list(QUERY_TIMES_S):
        raise BuildError("ROOT231 query times are not the frozen 2/3/4 set")
    proof, proof_rec = read_json(ROOT223_PROOF, "ROOT223 proof", ROOT223_SHA)
    if proof.get("status") != "VERIFIED_ACTUAL_F1_S2_THREE_GRID_SELECTED_COMPONENT_DIAGNOSTICS_ONLY":
        raise BuildError("ROOT223 proof status mismatch")
    report, report_rec = read_json(Path(proof["report"]), "ROOT223 report", proof.get("report_sha256"))
    if report.get("schema") != "ds02.stage2.f1-s2.component-space-compare.v1":
        raise BuildError("ROOT223 report schema mismatch")
    producer = proof.get("source_producer_proof", {})
    if producer.get("sha256") != ROOT207_SHA:
        raise BuildError("ROOT223 source producer is not ROOT207")
    child_binding = proof.get("actual_native_child_report", {})
    child, child_rec = read_json(Path(child_binding["path"]), "ROOT207 child report", ROOT207_CHILD_SHA)
    if child.get("schema") != "ds02.stage2.f1.native-selected-observer.v1" or child.get("status") != "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES":
        raise BuildError("ROOT207 child report schema/status mismatch")
    calibration, calibration_proof_rec = read_json(ROOT217_PROOF, "ROOT217 calibration proof", ROOT217_SHA)
    if calibration.get("scientific_qualification", {}).get("QI") not in (None, "UNKNOWN"):
        raise BuildError("ROOT217 manufactured calibration was promoted to QI")
    calibration_report, calibration_report_rec = read_json(ROOT217_REPORT, "ROOT217 calibration report", ROOT217_REPORT_SHA)
    if calibration_report.get("schema") != "ds02.stage2.f1.bi4-official-writer-calibration.v4":
        raise BuildError("ROOT217 calibration report schema mismatch")
    cases = {item.get("label"): item for item in child.get("cases", []) if isinstance(item, dict)}
    selected = {"coarse": "F1_S2_DP0225_COARSE", "medium": "F1_S2_DP020_MEDIUM", "fine": "F1_S2_DP017_FINE"}
    grids: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    static: list[dict[str, Any]] = [
        plan_rec,
        stable_hash(WORKER, "ROOT231 endpoint worker"),
        stable_hash(LEGACY_WORKER, "ROOT225 endpoint worker compatibility module"),
        stable_hash(CALIBRATED, "calibrated V1 native observer worker"),
        stable_hash(BASE_OBSERVER, "calibrated native physical observer"),
        proof_rec,
        report_rec,
        child_rec,
        calibration_proof_rec,
        calibration_report_rec,
    ]
    for label, case_label in selected.items():
        case = cases.get(case_label)
        if case is None:
            raise BuildError(f"ROOT207 child lacks {case_label}")
        grid, grid_static, grid_deferred = _case_grid(case, label)
        grids.append(grid)
        deferred.extend(grid_deferred)
        static.extend(grid_static)
    unique = {record["path"]: record for record in static}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_NOT_RUN_ROOT231_QUERY234_SOURCE_ENDPOINT_AUDIT",
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "query": {"times_s": list(QUERY_TIMES_S), "selection": plan["queries"]["selection"], "interpolation": "FORBIDDEN", "extrapolation": "FORBIDDEN"},
        "contract": {"path": str(CONTRACT), "sha256": plan_rec["sha256"]},
        "root223": {"path": str(ROOT223_PROOF), "sha256": ROOT223_SHA, "report": report_rec, "root207_child": child_rec},
        "root217": {"path": str(ROOT217_PROOF), "sha256": ROOT217_SHA, "report": calibration_report_rec},
        "grids": grids,
        "deferred_native_records": deferred,
        "static_source_records": list(unique.values()),
        "read_scope": plan["resource_guard"],
        "qualification": plan["qualification"],
        "axis_scope": "component-space source convention only; producer world-axis orientation remains UNKNOWN",
    }
    manifest_path = output_manifest.expanduser().absolute()
    request_path = output_request.expanduser().absolute()
    write_once(manifest_path, manifest)
    manifest_rec = stable_hash(manifest_path, "ROOT231 manifest")
    source_records = list(unique.values()) + [manifest_rec]
    records = {item["path"]: item for item in source_records}
    static_bytes = sum(int(item["bytes"]) for item in source_records)
    max_deferred = int(plan["queries"]["maximum_deferred_part_records"])
    native_read_bytes = max_deferred * MAX_NATIVE_BYTES * NATIVE_READ_PASSES
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V8_F1_S2_QUERY234_ENDPOINT_AUDIT",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-query234-endpoint-audit-root231-001",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_QUERY234_ENDPOINT_AUDIT_ROOT231",
        "attempt_id": "f1-s2-query234-endpoint-audit-root231-001",
        "cwd": str(ROOT),
        "worktree_root": str(ROOT),
        "command": [str(PYTHON), "-B", str(WORKER), "--manifest", "{attempt_root}/inputs/f1_s2_query234_endpoint_manifest_v2.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_query234_endpoint_observer_v2.json"],
        "literal_venv_invocation": {"path": str(PYTHON), "argv0_literal": True, "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)},
        "input_files": sorted(records),
        "input_sha256": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "manifest": manifest_rec,
        "deferred_input_files": sorted(item["path"] for item in deferred),
        "deferred_input_records": deferred,
        "deferred_input_policy": {
            "parent_after_reservation_first_sha_and_stat": True,
            "parent_after_child_post_sha_and_stat": True,
            "required_stat_fields": ["bytes", "mtime_ns", "ctime_ns", "dev", "ino"],
            "producer_known_sha_is_not_builder_computed": True,
            "source_replace_or_stat_change": "FAIL",
            "selected_frame_count_upper_bound": max_deferred,
        },
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 2 * 1024**3,
        "max_storage_bytes": 512 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_scratch_bytes": 512 * 1024**2,
        "estimated_storage_bytes": 512 * 1024**2,
        "estimated_native_read_passes": NATIVE_READ_PASSES,
        "estimated_native_read_bytes": native_read_bytes,
        "estimated_native_read_bytes_is_conservative_upper_bound": True,
        "estimated_input_read_bytes": static_bytes + native_read_bytes,
        "estimated_input_read_bytes_scope": "static metadata plus up to 18 deferred native files at 512 MiB each and four worker/decoder passes; actual bytes remain parent-measured",
        "estimated_hdf5_read_bytes": 0,
        "resources": {"gpu": False, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 2 * 1024**3, "external_storage_max_bytes": 512 * 1024**2, "home_storage_max_bytes": 128 * 1024**2, "log_max_bytes": 512 * 1024, "parent_guard_required": True},
        "runtime_closure": {
            "literal_python": {"path": str(PYTHON), "resolved_target": str(PYTHON_TARGET), "pyvenv_cfg": str(PYVENV_CFG)},
            "worker": str(WORKER),
            "legacy_manifest_helper": str(LEGACY_WORKER),
            "calibrated_observer": str(CALIBRATED),
            "base_observer": str(BASE_OBSERVER),
            "parent_v8_deferred_sha_stat_gate": True,
        },
        "storage_scope": {"output_root": "{attempt_root}", "native_payload_read": "nearest lower/upper Part files for queries 2, 3, and 4 seconds only", "h5_vtk_allowed": False, "full_native_tree_scan": False, "solver_launch": False},
        "source_binding": {"manifest": str(manifest_path), "root223_proof": {"path": str(ROOT223_PROOF), "sha256": ROOT223_SHA}, "root207_child_report": {"path": str(child_binding["path"]), "sha256": ROOT207_CHILD_SHA}, "root217_calibration_proof": {"path": str(ROOT217_PROOF), "sha256": ROOT217_SHA}, "axis_scope": "component-space only; world-axis UNKNOWN", "query_times_s": list(QUERY_TIMES_S), "interpolation": "FORBIDDEN", "neighbor_grid_truth": False},
        "scope": {"queries_s": list(QUERY_TIMES_S), "nearest_lower_upper_native_frames": True, "native_mass_from_decoder": True, "science_Q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}},
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "ledger_mutation": False,
        "qualification_credit": 0,
    }
    write_once(request_path, request)
    return manifest, request


def self_test() -> None:
    rows = [{"frame": 0, "time_s": 0.0}, {"frame": 199, "time_s": 1.995}, {"frame": 200, "time_s": 2.0001}]
    assert _query_records(rows, 2.0) == (rows[1], rows[2])
    assert legacy._command_tout(["solver", "-tout:0.005"]) == "0.005"
    assert MAX_NATIVE_BYTES * NATIVE_READ_PASSES * 18 > 0
    print("PASS_F1_S2_QUERY_ENDPOINT_REQUEST_V2_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--output-request", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output_manifest is None or args.output_request is None:
        parser.error("--output-manifest and --output-request are required with --build")
    try:
        build(args.output_manifest, args.output_request)
    except (BuildError, OSError, ValueError, KeyError) as exc:
        print(f"FAIL_F1_S2_QUERY_ENDPOINT_REQUEST_V2: {exc}")
        return 2
    print(f"PASS_PREPARED_F1_S2_QUERY234_ENDPOINT {args.output_manifest} {args.output_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
