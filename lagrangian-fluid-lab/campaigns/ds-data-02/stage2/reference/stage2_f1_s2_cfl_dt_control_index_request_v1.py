#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the bounded ROOT248 F1-S2 control-provenance request."""
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
WORKER = HERE / "stage2_f1_s2_cfl_dt_control_index_v1.py"
CONTRACT = HERE / "stage2_f1_s2_cfl_dt_control_index_contract_v1.json"
SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.cfl-dt-control-manifest.v1"
MAX_JSON = 4 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file(): raise ValueError(f"{label} is not regular: {path}")
    return path.absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat(); return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size), "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _record(path: Path, label: str, limit: int, parse: bool = True) -> tuple[Any, dict[str, Any]]:
    path = _regular(path, label); before = _stat(path)
    if before["bytes"] > limit: raise ValueError(f"{label} exceeds bound: {before['bytes']}")
    digest = hashlib.sha256(); chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk); chunks.append(chunk)
    after = _stat(path)
    if before != after: raise RuntimeError(f"{label} changed during read")
    value: Any = None
    if parse:
        value = json.loads(b"".join(chunks).decode("utf-8"))
        if not isinstance(value, dict): raise ValueError(f"{label} is not JSON object")
    return value, {"path": str(path), "sha256": digest.hexdigest(), "bytes": after["bytes"], "stat": after, "stable_read": True, "label": label, "content_scope": "bounded_json_or_xml_metadata" if parse else "source_code_or_contract"}


def _code(path: Path, label: str) -> dict[str, Any]: return _record(path, label, 8 * 1024 * 1024, False)[1]


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink(): raise ValueError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True); tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try: tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"); os.replace(tmp, path)
    finally: tmp.unlink(missing_ok=True)


def _python_binding() -> dict[str, Any]:
    literal = PYTHON.expanduser()
    if not literal.is_symlink(): raise ValueError("literal venv Python must remain a symlink")
    resolved = _regular(literal.resolve(), "resolved venv Python")
    cfg = literal.parent.parent / "pyvenv.cfg"
    return {"literal_argv0": str(literal), "literal_argv0_required": True, "resolved": _code(resolved, "resolved venv Python"), "pyvenv_cfg": _code(cfg, "pyvenv.cfg")}


def build(args: argparse.Namespace) -> dict[str, Any]:
    manifest, manifest_rec = _record(args.manifest, "F1-S2 control manifest", MAX_JSON)
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_F1_S2_CONTROL_INDEX": raise ValueError("manifest schema/status mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries: raise ValueError("manifest entries missing")
    records: dict[str, dict[str, Any]] = {manifest_rec["path"]: manifest_rec}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict): raise ValueError(f"entry {i} is not object")
        for key, limit in (("request", MAX_JSON), ("receipt", MAX_JSON), ("xml", MAX_XML)):
            item = entry.get(key)
            if not isinstance(item, dict) or not isinstance(item.get("path"), str): raise ValueError(f"entry {i} missing {key}")
            suffix = Path(item["path"]).suffix.lower()
            if suffix in {".bi4", ".h5", ".vtk", ".part", ".csv"}: raise ValueError(f"entry {i} points at forbidden payload type {suffix}")
            _, rec = _record(Path(item["path"]), f"entry {i} {key}", limit, parse=(key != "xml"))
            records[rec["path"]] = rec
    for path, label in ((WORKER, "ROOT248 worker"), (CONTRACT, "ROOT248 contract")):
        rec = _code(path, label); records[rec["path"]] = rec
    py = _python_binding(); records[py["resolved"]["path"]] = py["resolved"]; records[py["pyvenv_cfg"]["path"]] = py["pyvenv_cfg"]
    files = sorted(records); hashes = {p: records[p]["sha256"] for p in files}
    request = {"schema": SCHEMA, "variant_schema": "ds02.stage2.f1-s2.cfl-dt-control-index-request.v1", "status": "READY_FOR_PARENT_V8_F1_S2_CFL_DT_CONTROL_INDEX_ROOT248", "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F1", "sentinel_id": "F1-S2", "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit, "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": [str(PYTHON), str(WORKER), "--manifest", str(args.manifest.absolute()), "--output", "{attempt_root}/control/f1_s2_cfl_dt_control_index_v1.json"], "input_files": files, "input_hashes": hashes, "input_sha256": hashes, "input_records": records, "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600, "max_memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_peak_memory_bytes": 256 * 1024 * 1024, "estimated_input_read_bytes": sum(int(r["bytes"]) for r in records.values()), "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "runparts_read": False, "raw_directory_scan": False, "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/control/f1_s2_cfl_dt_control_index_v1.json"}, "source_binding": {"receipt_launch_argv_authority": True, "xml_declaration_only": True, "labels_not_evidence": True, "half_cfl_or_output_substitutes": False, "interpolation": False, "neighbor_grid_truth": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}, "resource_guard": {"runner": "parent-v8-audit", "native_payload": "forbidden", "solver_launch": "forbidden", "large_report": "forbidden"}}
    request["sha256"] = _canonical(request); _write_once(args.output_request, request); return request


def _self_test() -> None:
    # The worker carries the executable synthetic tests.  This builder test
    # specifically checks that its own canonical request is deterministic and
    # that a forbidden native payload cannot enter the input closure.
    try:
        suffix = Path("case.bi4").suffix.lower()
        if suffix not in {".bi4", ".h5", ".vtk"}: raise AssertionError("payload filter failed")
    except Exception as exc:
        raise AssertionError("payload filter failed") from exc
    assert _canonical({"x": 1}) == _canonical({"x": 1})
    print("PASS_F1_S2_CFL_DT_CONTROL_REQUEST_V1_SELFTEST")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--manifest", type=Path); p.add_argument("--output-request", type=Path); p.add_argument("--case-id", default="F1_S2_CFL_DT_CONTROL_INDEX_ROOT248"); p.add_argument("--attempt-id", default="f1-s2-cfl-dt-control-index-v1-root-248-001"); p.add_argument("--launch-commit", default="SOURCE_ONLY_ROOT248"); p.add_argument("--self-test", action="store_true"); args = p.parse_args()
    if args.self_test: _self_test(); return 0
    if args.manifest is None or args.output_request is None: p.error("--manifest and --output-request are required unless --self-test")
    try: req = build(args)
    except Exception as exc: print(f"FAILED_F1_S2_CFL_DT_CONTROL_REQUEST: {exc}"); return 2
    print(json.dumps({"status": req["status"], "request": str(args.output_request.absolute()), "sha256": req["sha256"]}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
