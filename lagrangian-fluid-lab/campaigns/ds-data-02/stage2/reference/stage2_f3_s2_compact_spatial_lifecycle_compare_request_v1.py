#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the source-bound ROOT240 F3 compact diagnostic request.

The builder joins each observer proof to its observer request/receipt and to
the underlying solver proof/request/receipt.  ROOT150's legacy full report
is deliberately stat-only and is never hashed or opened here; ROOT177 and
ROOT178 compact summaries are bounded JSON inputs.  This is a diagnostic
request, not a solver or native-payload request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = HERE / "stage2_f3_s2_compact_spatial_lifecycle_compare_v1.py"
CONTRACT = HERE / "stage2_f3_s2_compact_spatial_lifecycle_compare_contract_v1.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.compact-spatial-lifecycle-compare-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f3-s2.compact-spatial-lifecycle-manifest.v1"
FAMILY_ID = "F3"
SENTINEL_ID = "F3-S2"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise FileNotFoundError(f"{label} is not a regular file: {raw}")
    path = raw.resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} resolved target is not regular: {path}")
    return path


def _stat(path: Path) -> dict[str, int]:
    value = _regular(path, "source").stat()
    return {"bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino), "mode": int(value.st_mode)}


def _record(path: Path, label: str, *, read_json: bool = True, max_bytes: int = 4 * 1024 * 1024) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > max_bytes:
        raise ValueError(f"{label} exceeds bounded input limit: {before['bytes']}")
    digest = hashlib.sha256(); chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk); chunks.append(chunk)
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed while being read")
    rec = {"path": str(path), "bytes": before["bytes"], "sha256": digest.hexdigest(), "stat": before, "stable_read": True, "label": label, "content_scope": "bounded_json_metadata_only"}
    if not read_json:
        return None, rec
    value = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, rec


def _record_code(path: Path, label: str, max_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    _, rec = _record(path, label, read_json=False, max_bytes=max_bytes); rec["content_scope"] = "source_code_or_runtime_metadata"; return rec


def _python_record() -> dict[str, Any]:
    literal = PYTHON.expanduser()
    if not literal.is_symlink():
        raise ValueError(f"literal venv argv0 must remain a symlink: {literal}")
    resolved = _regular(literal.resolve(), "resolved venv Python")
    pyvenv = literal.parent.parent / "pyvenv.cfg"
    return {"literal_path": str(literal), "literal_argv0_required": True, "resolved": _record_code(resolved, "resolved venv Python"), "pyvenv_cfg": _record_code(pyvenv, "venv pyvenv.cfg", max_bytes=1024 * 1024)}


def _proof_edges(label: str, observer_proof_name: str, solver_proof_name: str, summary_path: Path | None) -> dict[str, Any]:
    proof_path = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints" / observer_proof_name
    proof, proof_rec = _record(proof_path, f"{label} observer proof")
    assert proof is not None
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError(f"{label} observer proof is not actual")
    observer_request = _regular(Path(str(proof.get("request"))), f"{label} observer request")
    observer_receipt = _regular(Path(str(proof.get("receipt"))), f"{label} observer receipt")
    _, observer_request_rec = _record(observer_request, f"{label} observer request")
    receipt_value, observer_receipt_rec = _record(observer_receipt, f"{label} observer receipt")
    if proof.get("request_sha256") != observer_request_rec["sha256"] or proof.get("receipt_sha256") != observer_receipt_rec["sha256"]:
        raise ValueError(f"{label} observer proof/request/receipt SHA join failed")
    if not str(receipt_value.get("status", "")).lower().startswith(("completed", "complete", "success")):
        raise ValueError(f"{label} observer receipt is not completed")
    solver_proof_path = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints" / solver_proof_name
    solver_proof, solver_proof_rec = _record(solver_proof_path, f"{label} solver proof")
    assert solver_proof is not None
    if solver_proof.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"} or "ACTUAL" not in str(solver_proof.get("status", "")):
        raise ValueError(f"{label} solver proof is not actual")
    solver_request = _regular(Path(str(solver_proof.get("request"))), f"{label} solver request")
    solver_receipt = _regular(Path(str(solver_proof.get("receipt"))), f"{label} solver receipt")
    _, solver_request_rec = _record(solver_request, f"{label} solver request", max_bytes=8 * 1024 * 1024)
    solver_receipt_value, solver_receipt_rec = _record(solver_receipt, f"{label} solver receipt", max_bytes=32 * 1024 * 1024)
    if solver_proof.get("request_sha256") != solver_request_rec["sha256"] or solver_proof.get("receipt_sha256") != solver_receipt_rec["sha256"]:
        raise ValueError(f"{label} solver proof/request/receipt SHA join failed")
    if not str(solver_receipt_value.get("status", "")).lower().startswith(("completed", "complete", "success")):
        raise ValueError(f"{label} solver receipt is not completed")
    summary_rec = None
    if summary_path is not None:
        summary_value, summary_rec = _record(summary_path, f"{label} compact summary", max_bytes=4 * 1024 * 1024)
        assert summary_value is not None
        if summary_value.get("schema") != "ds02.stage2.f3-s2.full-native-stream-observer.v5" or not str(summary_value.get("status", "")).startswith("PASS"):
            raise ValueError(f"{label} compact summary schema/status is not successful")
        if summary_value.get("case_binding", {}).get("physical_case_id") not in {None, PHYSICAL_CASE_ID}:
            raise ValueError(f"{label} compact summary physical case differs")
        if int(summary_value.get("frame_count", -1)) != 836:
            raise ValueError(f"{label} compact summary frame count differs")
        if proof.get("summary") != summary_rec["path"] or proof.get("summary_sha256") != summary_rec["sha256"]:
            raise ValueError(f"{label} proof/summary SHA join failed")
    return {"label": label, "observer_proof": proof_rec, "observer_request": observer_request_rec, "observer_receipt": observer_receipt_rec, "solver_proof": solver_proof_rec, "solver_request": solver_request_rec, "solver_receipt": solver_receipt_rec, "summary": summary_rec, "legacy_full_report": {"path": str(proof.get("report") or proof.get("full_report_stat_only", {}).get("path", "")), "bytes": proof.get("report_bytes") or proof.get("full_report_stat_only", {}).get("bytes"), "sha256": proof.get("report_sha256") or proof.get("full_report_stat_only", {}).get("sha256"), "content_read": False}}


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"); os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def build(args: argparse.Namespace) -> dict[str, Any]:
    data = DATA_ROOT / "families/F3"
    producers = [
        {"label": "coarse", "solver_spacing_m": 0.015, "observer_proof": None, **_proof_edges("coarse", "F3_FULL836_NATIVE_STREAM_ACTUAL_LIMITED_ROOT_VERIFICATION_150.json", "F3_DP015_COARSE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_133.json", None)},
        {"label": "middle", "solver_spacing_m": 0.006, **_proof_edges("middle", "F3_MIDDLE_FULL836_NATIVE_COMPACT_ACTUAL_ROOT_VERIFICATION_177.json", "F3_DP006_MIDDLE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_162.json", data / "F3_S2_MIDDLE_FULL_NATIVE_STREAM_V6_ROOT_177/f3-s2-middle-full-native-stream-v6-root-177-001-root-forward-030-001/observer/f3_s2_full_native_stream_observer_v5.summary.json")},
        {"label": "fine", "solver_spacing_m": 0.003, **_proof_edges("fine", "F3_FINE_FULL836_NATIVE_COMPACT_ACTUAL_ROOT_VERIFICATION_178.json", "F3_DP003_FINE_EXTERNAL_ACTUAL_NATIVE_ROOT_VERIFICATION_170.json", data / "F3_S2_FULL_NATIVE_STREAM_ROOT178_V6/f3-s2-full-native-stream-root178-v6-001-root-forward-030-001/observer/f3_s2_full_native_stream_observer_v5.summary.json")},
    ]
    # The coarse proof already contains the source report SHA/stat.  Keep it
    # as a deferred stat-only edge; no builder content read of that 14.8 MB
    # legacy report is permitted.
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE", "family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID, "query_times_s": list(QUERY_TIMES_S), "producers": producers, "scope": {"coarse_fields": "UNKNOWN_LEGACY_FULL_REPORT_NOT_READ", "middle_fine": "compact_summary_only", "native_payload_read": False, "full_report_read": False, "interpolation": False, "neighbor_grid_truth": False}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    manifest["sha256"] = _canonical(manifest)
    manifest_path = args.manifest_output.expanduser().absolute(); _write_once(manifest_path, manifest)
    _, manifest_rec = _record(manifest_path, "ROOT240 manifest", read_json=False)
    records: dict[str, dict[str, Any]] = {manifest_rec["path"]: manifest_rec, str(WORKER): _record_code(WORKER, "ROOT240 worker"), str(CONTRACT): _record_code(CONTRACT, "ROOT240 contract")}
    py = _python_record(); records[py["resolved"]["path"]] = py["resolved"]; records[py["pyvenv_cfg"]["path"]] = py["pyvenv_cfg"]
    for producer in producers:
        for key in ("observer_proof", "observer_request", "observer_receipt", "solver_proof", "solver_request", "solver_receipt", "summary"):
            item = producer.get(key)
            if isinstance(item, dict): records[item["path"]] = item
    input_files = sorted(records); input_hashes = {path: records[path]["sha256"] for path in input_files}
    command = [str(PYTHON), str(WORKER), "--manifest", str(manifest_path), "--output", "{attempt_root}/comparison/f3_s2_compact_spatial_lifecycle_compare_v1.json"]
    request = {"schema": SCHEMA, "variant_schema": VARIANT, "status": "READY_FOR_PARENT_V8_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE", "kind": "cpu", "cpu_task_kind": "audit", "family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID, "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit, "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY_REPO), "command": command, "input_files": input_files, "input_hashes": input_hashes, "input_sha256": input_hashes, "input_records": records, "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900, "max_memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_peak_memory_bytes": 512 * 1024 * 1024, "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()), "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "raw_directory_scan": False, "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/comparison/f3_s2_compact_spatial_lifecycle_compare_v1.json"}, "source_binding": {"producers": {item["label"]: {"observer_proof": item["observer_proof"]["path"], "solver_proof": item["solver_proof"]["path"], "summary": item.get("summary", {}).get("path") if isinstance(item.get("summary"), dict) else None} for item in producers}, "queries_s": list(QUERY_TIMES_S), "coarse_full_report_read": False, "compact_summary_only": True, "interpolation": False, "neighbor_grid_truth": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}, "resource_guard": {"runner": "parent-v8-audit", "legacy_coarse_full_report": "forbidden", "native_payload": "forbidden", "solver_launch": "forbidden"}, "qualification_stage": "f3_s2_compact_fields_lifecycle_diagnostics_only"}
    request["sha256"] = _canonical(request)
    request_path = args.output_request.expanduser().absolute(); _write_once(request_path, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--manifest-output", type=Path, default=Path("stage2-f3-s2-compact-spatial-lifecycle-manifest-root240.json")); parser.add_argument("--output-request", type=Path); parser.add_argument("--case-id", default="F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_ROOT240"); parser.add_argument("--attempt-id", default="f3-s2-compact-spatial-lifecycle-compare-v1-root-240-001"); parser.add_argument("--launch-commit", default="SOURCE_ONLY_ROOT240"); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test:
        print("PASS_F3_S2_COMPACT_SPATIAL_LIFECYCLE_REQUEST_V1_ENTRYPOINT_SELFTEST"); return 0
    if args.output_request is None: parser.error("--output-request is required unless --self-test is used")
    request = build(args); print(json.dumps({"status": request["status"], "request": str(args.output_request.expanduser().absolute()), "manifest": str(args.manifest_output.expanduser().absolute()), "sha256": request["sha256"]}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
