#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the bounded source/receipt/XML CFL-entrypoint audit request."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = HERE / "stage2_f1_s2_cfl_entrypoint_audit_v1.py"
CONTRACT = HERE / "stage2_f1_s2_cfl_entrypoint_audit_contract_v1.json"
SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.cfl-entrypoint-manifest.v1"
MAX_JSON = 8 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024


class BuildFailure(RuntimeError):
    pass


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    return path.absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat(); return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size), "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _record(path: Path, label: str, limit: int) -> dict[str, Any]:
    path = _regular(path, label); before = _stat(path)
    if before["bytes"] > limit: raise BuildFailure(f"{label} exceeds bounded limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
    after = _stat(path)
    if before != after: raise BuildFailure(f"{label} changed while being read")
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": after["bytes"], "stat": after, "stable_read": True, "label": label, "content_scope": "bounded_metadata_or_official_source"}


def _path(value: Any, label: str) -> Path:
    if isinstance(value, str): return Path(value)
    if isinstance(value, dict) and isinstance(value.get("path"), str): return Path(value["path"])
    raise BuildFailure(f"{label} missing path")


def _python_binding() -> dict[str, Any]:
    literal = PYTHON.expanduser()
    if not literal.is_symlink(): raise BuildFailure("literal venv Python must remain a symlink")
    resolved = _regular(literal.resolve(), "resolved venv Python")
    cfg = literal.parent.parent / "pyvenv.cfg"
    return {"literal_argv0": str(literal), "literal_argv0_required": True, "resolved": _record(resolved, "resolved venv Python", 8 * 1024 * 1024), "pyvenv_cfg": _record(cfg, "pyvenv.cfg", MAX_SOURCE)}


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink(): raise BuildFailure(f"refusing overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"); os.replace(temporary, path)
    finally: temporary.unlink(missing_ok=True)


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = _regular(args.manifest, "F1 CFL manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F1_CFL_ENTRYPOINT_AUDIT": raise BuildFailure("manifest schema/status mismatch")
    entries = manifest.get("entries"); sources = manifest.get("official_sources")
    if not isinstance(entries, list) or not entries or not isinstance(sources, list) or not sources: raise BuildFailure("manifest entries/sources missing")
    records: dict[str, dict[str, Any]] = {}
    manifest_record = _record(manifest_path, "F1 CFL manifest", MAX_JSON); records[manifest_record["path"]] = manifest_record
    for i, source in enumerate(sources):
        record = _record(_path(source, f"official source {i}"), f"official source {i}", MAX_SOURCE); records[record["path"]] = record
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict): raise BuildFailure(f"entry {index} is not an object")
        for key, limit in (("request", MAX_JSON), ("receipt", MAX_JSON), ("xml", MAX_XML)):
            path = _path(entry.get(key), f"entry {index} {key}")
            if path.suffix.lower() in {".bi4", ".h5", ".vtk", ".part", ".csv"}: raise BuildFailure(f"payload path in entry {index} {key}")
            record = _record(path, f"entry {index} {key}", limit); records[record["path"]] = record
    worker_record = _record(WORKER, "F1 CFL worker", MAX_SOURCE); records[worker_record["path"]] = worker_record
    contract_record = _record(CONTRACT, "F1 CFL contract", MAX_JSON); records[contract_record["path"]] = contract_record
    py = _python_binding(); records[py["resolved"]["path"]] = py["resolved"]; records[py["pyvenv_cfg"]["path"]] = py["pyvenv_cfg"]
    files = sorted(records); hashes = {path: records[path]["sha256"] for path in files}
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": "ds02.stage2.f1-s2.cfl-entrypoint-audit-request.v1",
        "status": "READY_FOR_PARENT_V8_F1_CFL_ENTRYPOINT_AUDIT_ROOT248",
        "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F1", "sentinel_id": "F1-S2",
        "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "command": [str(PYTHON), str(WORKER), "--manifest", str(manifest_path), "--output", "{attempt_root}/control/f1_s2_cfl_entrypoint_audit_v1.json"],
        "input_files": files, "input_hashes": hashes, "input_sha256": hashes, "input_records": records, "deferred_input_files": [],
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600, "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "estimated_input_read_bytes": sum(int(record["bytes"]) for record in records.values()), "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "solver_launch": False, "gencase_launch": False,
        "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "runparts_read": False, "raw_directory_scan": False,
        "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/control/f1_s2_cfl_entrypoint_audit_v1.json"},
        "source_binding": {"receipt_launch_argv_authority": True, "xml_cflnumber_authority_when_no_-cfl": True, "labels_not_evidence": True, "half_cfl_overlay_status": "SOURCE_ONLY_PREPARED_NOT_RUN", "interpolation": False, "neighbor_grid_truth": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        "resource_guard": {"runner": "parent-v8-audit", "native_payload": "forbidden", "solver_launch": "forbidden", "large_report": "forbidden"},
    }
    request["sha256"] = _canonical(request); _write_once(args.output_request, request); return request


def _self_test() -> None:
    assert _canonical({"x": 1}) == _canonical({"x": 1})
    try: _path({"path": "bad.bi4"}, "payload")
    except BuildFailure: pass
    print("PASS_F1_CFL_ENTRYPOINT_REQUEST_V1_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--manifest", type=Path); parser.add_argument("--output-request", type=Path); parser.add_argument("--case-id", default="F1_S2_CFL_ENTRYPOINT_AUDIT_ROOT248"); parser.add_argument("--attempt-id", default="f1-s2-cfl-entrypoint-audit-v1-root-248-001"); parser.add_argument("--launch-commit", default="SOURCE_ONLY_ROOT248"); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test: _self_test(); return 0
    if args.manifest is None or args.output_request is None: parser.error("--manifest and --output-request are required unless --self-test")
    try: request = build(args)
    except Exception as exc: print(f"FAILED_F1_CFL_ENTRYPOINT_REQUEST: {exc}"); return 2
    print(json.dumps({"status": request["status"], "request": str(args.output_request.absolute()), "sha256": request["sha256"]}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
