#!/usr/bin/env python3
"""Build source-prepared requests for the reserved F3 staged GenCase worker.

This builder consumes the additive exact-source rebind package and creates one
request per F3 grid.  The original owner forcing is explicitly in the future
parent runtime ``input_files`` with its known SHA/stat; the attempt-contained
copy is intentionally absent until the worker runs after reservation.  No
GenCase, solver, native payload, or forcing bytes are read by this builder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_three_sentinel_owner_grid_f3_staged_gencase_worker_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.three-sentinel.f3-staged-gencase-request-manifest.v2"
VARIANT = "three-sentinel-owner-grid-gencase-producer-f3force-staged-v2"
SMALL_CAP = 10 * 1024 * 1024
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class BuildFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file(): raise BuildFailure(f"{label} is not regular: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP: raise BuildFailure(f"{label} exceeds metadata cap")
    raw = path.read_bytes(); after = _stat(path)
    if before != after: raise BuildFailure(f"{label} changed during read")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict): raise BuildFailure(f"{label} must be object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                   "bytes": before["bytes"], "stat_before": before, "stat_after": after}


def _record(path: Path, label: str, *, read: bool = True) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file(): raise BuildFailure(f"{label} is not regular: {path}")
    before = _stat(path)
    if read:
        if before["bytes"] > SMALL_CAP: raise BuildFailure(f"{label} exceeds metadata cap")
        raw = path.read_bytes(); after = _stat(path)
        if before != after: raise BuildFailure(f"{label} changed during read")
        digest = hashlib.sha256(raw).hexdigest(); mode = "small_read"; read_flag = True
    else:
        after = before; digest = None; mode = "deferred_parent_after_reservation"; read_flag = False
    return {"path": str(path), "sha256": digest, "bytes": before["bytes"],
            "stat_before": before, "stat_after": after, "read_mode": mode,
            "payload_read_by_builder": read_flag}


def _record_declared(value: Any, label: str, *, read: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str): raise BuildFailure(f"{label} lacks path")
    path = Path(str(value["path"])).expanduser().absolute()
    if not path.is_file() or path.is_symlink(): raise BuildFailure(f"{label} is not regular: {path}")
    if not _valid_sha(value.get("sha256")):
        raise BuildFailure(f"{label} lacks concrete SHA")
    if read: return _record(path, label, read=True)
    current = _stat(path)
    expected = value.get("stat_after", value.get("stat_before", value.get("stat")))
    if isinstance(expected, dict):
        for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
            if key in expected and int(expected[key]) != current[key]:
                raise BuildFailure(f"{label} {key} differs from declared stat")
    return {**dict(value), "path": str(path), "sha256": str(value["sha256"]).lower(),
            "stat_before": current, "stat_after": current, "bytes": current["bytes"],
            "read_mode": "parent_after_reservation_runtime_input", "payload_read_by_builder": False}


def _write(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink(): raise BuildFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def build(rebind_manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest, manifest_record = _read_json(rebind_manifest_path, "F3 rebind manifest")
    if manifest.get("schema") != "ds02.stage2.three-sentinel.f3-forcing-rebind.v1":
        raise BuildFailure("unexpected F3 rebind schema")
    rows = manifest.get("rows")
    if not isinstance(rows, list) or {r.get("grid_label") for r in rows if isinstance(r, dict)} != {"original", "coarse", "fine"}:
        raise BuildFailure("F3 rebind manifest must contain original/coarse/fine")
    owner = manifest.get("owner_forcing")
    owner_record = _record_declared(owner, "owner forcing", read=False)
    worker_record = _record(WORKER, "staged GenCase worker", read=True)
    python_record = _record(PYTHON.resolve(), "resolved venv Python", read=True)
    pyvenv = PYTHON.parent.parent / "pyvenv.cfg"
    pyvenv_record = _record(pyvenv, "pyvenv.cfg", read=True)
    out = output_dir.expanduser().absolute()
    if out.exists() and any(out.iterdir()): raise BuildFailure(f"refusing non-empty output: {out}")
    out.mkdir(parents=True, exist_ok=True); request_dir = out / "requests"; request_dir.mkdir()
    prepared: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda x: str(x.get("grid_label"))):
        grid = str(row.get("grid_label")); old_path = Path(str(row.get("request_path"))).expanduser().absolute()
        old, old_record = _read_json(old_path, f"F3 {grid} rebind request")
        if old.get("sentinel_id") != "F3-S1": raise BuildFailure(f"{grid} request sentinel mismatch")
        candidate = row.get("candidate_def") or (old.get("source_binding") or {}).get("candidate_def")
        candidate_record = _record_declared(candidate, f"{grid} prepared candidate Def", read=True)
        command = old.get("command")
        if not isinstance(command, list) or not command or not isinstance(command[0], str): raise BuildFailure(f"{grid} old command missing binary")
        binary_path = Path(command[0]).expanduser().absolute(); binary_record = _record(binary_path, f"{grid} GenCase binary", read=True)
        records = {str(k): dict(v) for k, v in (old.get("input_records") or {}).items() if isinstance(v, dict)}
        for key in list(records):
            if Path(key).name == "CaseSloshingAccData.csv": records.pop(key, None)
        records[str(candidate_record["path"])] = candidate_record
        records[str(WORKER)] = worker_record; records[str(binary_path)] = binary_record
        records[str(PYTHON.resolve())] = python_record; records[str(pyvenv)] = pyvenv_record
        records[str(owner_record["path"])] = owner_record
        case = f"F3_S1_{grid.upper()}_OWNER_GRID_GENCASE_F3FORCE_STAGED_V1"
        attempt = f"f3-s1-{grid}-owner-grid-gencase-f3force-staged-v2-parent-pending-001"
        planned = f"/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/{case}/{attempt}"
        req_path = request_dir / f"f3-s1-{grid}-owner-grid-gencase-f3force-staged-v2-request.json"
        request = {
            "schema": REQUEST_SCHEMA, "status": "READY_FOR_PARENT_RESERVED_F3_STAGED_GENCASE_WORKER",
            "request_variant": VARIANT, "kind": "cpu", "cpu_task_kind": "gencase",
            "family_id": "F3", "sentinel_id": "F3-S1", "grid_label": grid,
            "case_id": case, "attempt_id": attempt,
            "command": [str(PYTHON), str(WORKER), "--run", "--request", "{request_path}",
                         "--attempt-root", "{attempt_root}", "--report", "{attempt_root}/report/f3-staged-gencase-worker-v1.json"],
            "input_files": sorted(records), "input_records": records,
            "input_sha256": {p: r["sha256"] for p, r in records.items() if _valid_sha(r.get("sha256"))},
            "deferred_input_records": [], "output_root": "{attempt_root}", "planned_output_root": planned,
            "execution_allowed": False, "launch_disabled": True, "source_only": True,
            "gencase_launch": True, "solver_launch": False, "solver_started": False,
            "bi4_read": False, "hdf5_read": False, "production_eligible": False,
            "max_wall_seconds": 1800, "max_memory_bytes": 4 * 1024**3, "max_storage_bytes": 64 * 1024**3,
            "estimated_cpu_seconds": 1800, "estimated_storage_bytes": 8 * 1024**3,
            "resource_scope": {"cpu_threads": 1, "memory_max_bytes": 4 * 1024**3,
                               "max_wall_seconds": 1800, "scratch_max_bytes": 8 * 1024**3, "gpu": "none"},
            "staged_gencase_worker": {"worker_path": worker_record, "owner_forcing": owner_record,
                                       "candidate_def": candidate_record,
                                       "copy_contract": {"destination": "{attempt_root}/inputs/F3_S1/" + grid + "/CaseSloshingAccData.csv",
                                                          "source_must_be_parent_runtime_input": True,
                                                          "source_pre_post_sha_stat_required": True,
                                                          "destination_new_inode_required": True,
                                                          "destination_does_not_exist_before_worker": True,
                                                          "candidate_copy_must_not_be_used": True},
                                       "report_products_stat_only": True,
                                       "native_product_hash_owner": "parent_after_worker_policy"},
            "gencase": {"binary": binary_record, "binary_sha256": binary_record["sha256"],
                        "extra_args": ["-save:all", "-threads:1"],
                        "official_stem_rule": "*_Def.xml -> argv stem without .xml, retain _Def",
                        "cwd": "{attempt_root}/inputs/F3_S1/" + grid,
                        "output_prefix": "{attempt_root}/generated"},
            "source_binding": {"rebind_manifest": manifest_record, "rebind_request": old_record,
                                "owner_forcing": owner_record, "candidate_def": candidate_record,
                                "source_edit_contract": {"allowed": ["definition@dp", "auxiliary_path_rebinding"],
                                                          "candidate_copy_rejected": True,
                                                          "path_only_auxiliary_rebinding_plus_dp": True}},
            "parent_runtime_contract": {"original_forcing_is_in_input_files": True,
                                        "runtime_v8_must_hash_original_before_and_after": True,
                                        "staged_destination_not_preexisting_input": True,
                                        "worker_copies_after_reservation": True,
                                        "actual_runtime_request_must_rebind_placeholders": True},
            "scientific_qualification": QUALIFICATION,
        }
        _write(req_path, request)
        prepared.append({"grid_label": grid, "request_path": str(req_path),
                         "request_sha256": hashlib.sha256(req_path.read_bytes()).hexdigest(),
                         "owner_sha256": owner_record["sha256"], "production_eligible": False})
    result = {"schema": SCHEMA, "status": "READY_FOR_PARENT_RESERVED_STAGED_GENCASE_REVIEW",
              "owner_forcing": owner_record, "worker": worker_record, "rows": prepared,
              "read_scope": {"owner_forcing_bytes_read_by_builder": False,
                             "candidate_def_bytes_read_by_builder": True,
                             "production_gencase_started": False, "solver_started": False,
                             "scientific_credit": 0}}
    manifest_out = out / "f3-staged-gencase-request-manifest-v2.json"; _write(manifest_out, result)
    return {"manifest_path": str(manifest_out), "request_paths": [x["request_path"] for x in prepared], "manifest": result}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f3-staged-request-") as td:
        root = Path(td); source = root / "owner.csv"; source.write_bytes(b"owner-control")
        cand = root / "cand_Def.xml"; cand.write_text('<case><acctimesfile value="CaseSloshingAccData.csv"/></case>')
        binary = root / "GenCase_linux64"; binary.write_text("#!/bin/sh\nexit 0\n"); binary.chmod(0o755)
        old = root / "old-request.json"; owner = _record(source, "tiny owner", read=True); cr = _record(cand, "tiny candidate", read=True)
        req = {"sentinel_id": "F3-S1", "grid_label": "coarse", "command": [str(binary)], "input_records": {str(cand): cr}, "source_binding": {"candidate_def": cr}}
        old.write_text(json.dumps(req)); rbind = root / "rebind.json"
        rbind.write_text(json.dumps({"schema": "ds02.stage2.three-sentinel.f3-forcing-rebind.v1", "owner_forcing": owner,
                                     "rows": [{"grid_label": "coarse", "request_path": str(old), "candidate_def": cr},
                                              {"grid_label": "original", "request_path": str(old), "candidate_def": cr},
                                              {"grid_label": "fine", "request_path": str(old), "candidate_def": cr}]}))
        out = root / "out"; result = build(rbind, out); assert len(result["request_paths"]) == 3
        q = json.loads(Path(result["request_paths"][0]).read_text()); assert str(source) in q["input_files"]
        assert q["cpu_task_kind"] == "gencase"
        assert not any(Path(p).name == "CaseSloshingAccData.csv" and p != str(source) for p in q["input_files"])
        assert q["staged_gencase_worker"]["copy_contract"]["source_must_be_parent_runtime_input"]
    print("PASS_THREE_SENTINEL_OWNER_GRID_F3_STAGED_GENCASE_REQUEST_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__); g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--self-test", action="store_true"); g.add_argument("--build", action="store_true")
    p.add_argument("--rebind-manifest", type=Path); p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    try:
        if args.self_test: _self_test(); return 0
        if args.rebind_manifest is None or args.output_dir is None: p.error("--build requires rebind manifest/output")
        result = build(args.rebind_manifest, args.output_dir)
        print(json.dumps({"status": result["manifest"]["status"], "manifest": result["manifest_path"],
                          "requests": result["request_paths"], "scientific_credit": 0}, sort_keys=True)); return 0
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_OWNER_GRID_F3_STAGED_GENCASE_REQUEST_V2: {exc}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
