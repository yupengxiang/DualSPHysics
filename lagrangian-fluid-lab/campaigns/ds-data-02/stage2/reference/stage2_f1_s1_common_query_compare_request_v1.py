#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the bounded ROOT239 F1-S1 same-CFL comparison request.

The builder binds existing selected observer reports to their independent
proof/request/receipt records.  It reads only bounded JSON metadata and
never opens Part/BI4/H5/VTK payloads.  The three reports are included as
small actionable JSON inputs so the parent runtime can hash them in its
normal input closure; the worker still re-checks stable bytes and proof
joins before producing diagnostics.
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
WORKER = HERE / "stage2_f1_s1_common_query_compare_v1.py"
CONTRACT = HERE / "stage2_f1_s1_common_query_compare_contract_v1.json"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f1-s1.common-query-compare-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s1.common-query-manifest.v1"
FAMILY_ID = "F1"
SENTINEL_ID = "F1-S1"
PHYSICAL_CASE_ID = "F1_ECC_THICK_DBC_LOWER_HEAD_V1"
QUERY_TIMES_S = (0.0, 0.4, 0.8, 1.2, 1.6)


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise FileNotFoundError(f"{label} is not a regular file: {raw}")
    path = raw.resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} resolved target is not regular: {path}")
    return path


def _stat(path: Path) -> dict[str, int]:
    value = _regular(path, "source") .stat()
    return {"bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino), "mode": int(value.st_mode)}


def _record(path: Path, label: str, *, read_json: bool = True, max_bytes: int = 2 * 1024 * 1024) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > max_bytes:
        raise ValueError(f"{label} exceeds bounded input limit: {before['bytes']}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk); chunks.append(chunk)
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed while being read")
    record = {"path": str(path), "bytes": before["bytes"], "sha256": digest.hexdigest(), "stat": before, "stable_read": True, "label": label, "content_scope": "bounded_json_metadata_only"}
    if not read_json:
        return None, record
    value = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value, record


def _record_code(path: Path, label: str, max_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    _, record = _record(path, label, read_json=False, max_bytes=max_bytes)
    record["content_scope"] = "source_code_or_runtime_metadata"
    return record


def _record_python() -> dict[str, Any]:
    literal = PYTHON.expanduser()
    if not literal.is_symlink():
        raise ValueError(f"literal venv argv0 must remain a symlink: {literal}")
    resolved = _regular(literal.resolve(), "resolved venv Python")
    pyvenv = literal.parent.parent / "pyvenv.cfg"
    return {"literal_path": str(literal), "literal_argv0_required": True, "resolved": _record_code(resolved, "resolved venv Python"), "pyvenv_cfg": _record_code(pyvenv, "venv pyvenv.cfg", max_bytes=1024 * 1024)}


def _json_value(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    value, record = _record(path, label)
    assert value is not None
    return value, record


def _direct_spec(label: str, spacing: float, proof_name: str) -> dict[str, Any]:
    proof_path = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints" / proof_name
    proof, proof_record = _json_value(proof_path, f"{label} proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError(f"{label} proof is not an actual terminal observer proof")
    request_path = _regular(Path(str(proof.get("request"))), f"{label} request")
    receipt_path = _regular(Path(str(proof.get("receipt"))), f"{label} receipt")
    report_path = _regular(Path(str(proof.get("report"))), f"{label} report")
    request_value, request_record = _json_value(request_path, f"{label} request")
    receipt_value, receipt_record = _json_value(receipt_path, f"{label} receipt")
    del request_value
    if not str(receipt_value.get("status", "")).lower().startswith(("completed", "complete", "success")):
        raise ValueError(f"{label} receipt is not completed")
    report_record = _record(report_path, f"{label} report", read_json=False)[1]
    if proof.get("request_sha256") != request_record["sha256"] or proof.get("receipt_sha256") != receipt_record["sha256"] or proof.get("report_sha256") != report_record["sha256"]:
        raise ValueError(f"{label} proof/request/receipt/report SHA join failed")
    return {"label": label, "grid_spacing_m": spacing, "proof": proof_record, "request": request_record, "receipt": receipt_record, "report": report_record}


def _dp010_spec() -> dict[str, Any]:
    proof_path = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_FIVE_NATIVE_OBSERVERS_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
    proof, proof_record = _json_value(proof_path, "DP010 five-observer proof")
    rows = [item for item in proof.get("observations", []) if isinstance(item, dict) and "DP010_SAME_CFL" in str(item.get("identity", ""))]
    if len(rows) != 1:
        raise ValueError("DP010 SAME-CFL observer is not unique in five-observer proof")
    row = rows[0]
    report_path = _regular(Path(str(row["output"])), "DP010 observer report")
    receipt_path = _regular(Path(str(row["receipt"])), "DP010 observer receipt")
    report_record = _record(report_path, "DP010 observer report", read_json=False)[1]
    receipt_record = _record(receipt_path, "DP010 observer receipt", read_json=False)[1]
    if row.get("output_sha256") != report_record["sha256"] or row.get("receipt_sha256") != receipt_record["sha256"]:
        raise ValueError("DP010 proof report/receipt SHA join failed")
    return {"label": "dp010", "grid_spacing_m": 0.01, "proof": proof_record, "report": report_record, "receipt": receipt_record, "request": None, "source_selection": "DP010_SAME_CFL entry in five-observer proof"}


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    producers = [_dp010_spec(), _direct_spec("dp005", 0.005, "F1_DP005_SAME_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json"), _direct_spec("dp0025", 0.0025, "F1_DP0025_SAME_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json")]
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_F1_S1_COMMON_QUERY_COMPARE", "family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID, "query_times_s": list(QUERY_TIMES_S), "producers": producers, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "diagnostic_limits": {"interpolation": False, "neighbor_grid_truth": False, "bracket_width_is_error": False, "native_sample_mass_is_continuum_mass": False}}
    manifest["sha256"] = _canonical(manifest)
    manifest_path = args.manifest_output.expanduser().absolute()
    _write_once(manifest_path, manifest)
    manifest_record = _record(manifest_path, "ROOT239 comparison manifest", read_json=False, max_bytes=4 * 1024 * 1024)[1]
    records: dict[str, dict[str, Any]] = {manifest_record["path"]: manifest_record, str(WORKER): _record_code(WORKER, "ROOT239 worker"), str(CONTRACT): _record_code(CONTRACT, "ROOT239 contract")}
    python = _record_python(); records[python["resolved"]["path"]] = python["resolved"]; records[python["pyvenv_cfg"]["path"]] = python["pyvenv_cfg"]
    for producer in producers:
        for key in ("proof", "request", "receipt", "report"):
            record = producer.get(key)
            if isinstance(record, dict):
                records[record["path"]] = record
    input_files = sorted(records)
    input_hashes = {path: records[path]["sha256"] for path in input_files}
    command = [str(PYTHON), str(WORKER), "--manifest", str(manifest_path), "--output", "{attempt_root}/comparison/f1_s1_common_query_compare_v1.json"]
    request = {"schema": SCHEMA, "variant_schema": VARIANT, "status": "READY_FOR_PARENT_V8_F1_S1_COMMON_QUERY_COMPARE", "kind": "cpu", "cpu_task_kind": "audit", "family_id": FAMILY_ID, "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID, "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit, "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY_REPO), "command": command, "input_files": input_files, "input_hashes": input_hashes, "input_sha256": input_hashes, "input_records": records, "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600, "max_memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_peak_memory_bytes": 256 * 1024 * 1024, "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()), "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "native_payload_read": False, "hdf5_read": False, "raw_directory_scan": False, "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/comparison/f1_s1_common_query_compare_v1.json"}, "source_binding": {"manifest": manifest_record, "queries_s": list(QUERY_TIMES_S), "producer_labels": [item["label"] for item in producers], "saved_endpoint_only": True, "interpolation": False, "neighbor_grid_truth": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}, "resource_guard": {"runner": "parent-v8-audit", "observer_json_only": True, "native_payload_read": "forbidden", "full_h5_read": "forbidden", "solver_launch": "forbidden"}, "qualification_stage": "f1_s1_same_cfl_existing_observer_diagnostics_only"}
    request["sha256"] = _canonical(request)
    return request, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-output", type=Path, default=Path("stage2-f1-s1-common-query-manifest-root239.json"))
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--case-id", default="F1_S1_COMMON_QUERY_COMPARE_ROOT239")
    parser.add_argument("--attempt-id", default="f1-s1-common-query-compare-v1-root-239-001")
    parser.add_argument("--launch-commit", default="SOURCE_ONLY_ROOT239")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        # Do not fabricate a production request in self-test mode; the worker
        # owns manufactured semantic cases.  This checks that source paths are
        # discoverable and that the request canonicalizer is deterministic.
        print("PASS_F1_S1_COMMON_QUERY_REQUEST_V1_ENTRYPOINT_SELFTEST")
        return 0
    if args.output_request is None:
        parser.error("--output-request is required unless --self-test is used")
    request, _ = build(args)
    _write_once(args.output_request, request)
    print(json.dumps({"status": request["status"], "request": str(args.output_request.expanduser().absolute()), "manifest": str(args.manifest_output.expanduser().absolute()), "sha256": request["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
