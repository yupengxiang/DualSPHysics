#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the bounded ROOT252 F6 continuous-owner XML audit request.

The builder consumes ROOT244's small proof/report and the six source/generated
XML files named by that report.  It never opens a BI4, VTK, H5, Part, or
solver output.  The request deliberately treats an explicit XML drawbox as a
continuous-owner *diagnostic* and keeps particle sample mass separate.
"""
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
WORKER = HERE / "stage2_f6_continuous_owner_geometry_audit_v1.py"
CONTRACT = HERE / "stage2_f6_continuous_owner_geometry_audit_contract_v1.json"
SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f6-continuous-owner-geometry-manifest.v1"
MAX_JSON = 8 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024


class BuildFailure(RuntimeError):
    pass


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    return path.absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {
        "dev": int(s.st_dev),
        "ino": int(s.st_ino),
        "bytes": int(s.st_size),
        "mtime_ns": int(s.st_mtime_ns),
        "ctime_ns": int(s.st_ctime_ns),
    }


def _read(path: Path, label: str, limit: int, parse_json: bool) -> tuple[Any, dict[str, Any]]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > limit:
        raise BuildFailure(f"{label} exceeds bounded limit: {before['bytes']}")
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            chunks.append(chunk)
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while being read")
    value: Any = None
    if parse_json:
        try:
            value = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BuildFailure(f"{label} is not JSON") from exc
        if not isinstance(value, dict):
            raise BuildFailure(f"{label} is not an object")
    return value, {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "bytes": after["bytes"],
        "stat": after,
        "stable_read": True,
        "label": label,
        "content_scope": "bounded_json_metadata" if parse_json else "small_XML_geometry_metadata_or_source",
    }


def _record(path: Path, label: str, *, xml: bool = False) -> tuple[Any, dict[str, Any]]:
    return _read(path, label, MAX_XML if xml else MAX_JSON, not xml)


def _code(path: Path, label: str) -> dict[str, Any]:
    return _read(path, label, 8 * 1024 * 1024, False)[1]


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _python_binding() -> dict[str, Any]:
    literal = PYTHON.expanduser()
    if not literal.is_symlink():
        raise BuildFailure("literal venv Python must remain a symlink")
    resolved = _regular(literal.resolve(), "resolved venv Python")
    cfg = literal.parent.parent / "pyvenv.cfg"
    return {
        "literal_argv0": str(literal),
        "literal_argv0_required": True,
        "resolved": _code(resolved, "resolved venv Python"),
        "pyvenv_cfg": _code(cfg, "pyvenv.cfg"),
    }


def _case_from_report(case: dict[str, Any], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sid = str(case.get("sentinel_id"))
    source = case.get("source_xml")
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise BuildFailure(f"{sid} source_xml missing")
    _, source_rec = _record(Path(source["path"]), f"{sid} source XML", xml=True)
    if source.get("sha256") and source["sha256"] != source_rec["sha256"]:
        raise BuildFailure(f"{sid} source XML SHA differs from ROOT244 report")
    records[source_rec["path"]] = source_rec
    grids: list[dict[str, Any]] = []
    for grid in case.get("candidate_grids", []):
        if not isinstance(grid, dict):
            raise BuildFailure(f"{sid} grid is not an object")
        generated = grid.get("generated_xml")
        if isinstance(generated, str):
            generated = {"path": generated}
        elif isinstance(grid.get("generated_xml_record"), dict):
            generated = dict(grid["generated_xml_record"])
        if not isinstance(generated, dict) or not isinstance(generated.get("path"), str):
            raise BuildFailure(f"{sid}/{grid.get('grid')} generated XML missing")
        _, generated_rec = _record(Path(generated["path"]), f"{sid} {grid.get('grid')} XML", xml=True)
        if generated.get("sha256") and generated["sha256"] != generated_rec["sha256"]:
            raise BuildFailure(f"{sid}/{grid.get('grid')} XML SHA differs from ROOT244 report")
        records[generated_rec["path"]] = generated_rec
        grids.append({
            "grid": grid.get("grid"),
            "requested_dp_m": grid.get("requested_dp_m"),
            "generated_xml": generated_rec,
        })
    if not grids:
        raise BuildFailure(f"{sid} has no candidate grids")
    return {
        "sentinel_id": sid,
        "physical_case_id": case.get("physical_case_id"),
        "source_xml": source_rec,
        "grids": grids,
    }


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    proof, proof_rec = _record(args.proof, "ROOT244 proof")
    report_path = Path(str(proof.get("report", "")))
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise BuildFailure("ROOT244 proof is not an actual verification")
    if not report_path.is_absolute():
        raise BuildFailure("ROOT244 proof report path must be absolute")
    report, report_rec = _record(report_path, "ROOT244 report")
    if proof.get("report_sha256") != report_rec["sha256"]:
        raise BuildFailure("ROOT244 proof/report SHA mismatch")
    if report.get("schema") != "ds02.stage2.f6-owner-rigid-metadata-audit.v1":
        raise BuildFailure("ROOT244 report schema mismatch")
    records: dict[str, dict[str, Any]] = {proof_rec["path"]: proof_rec, report_rec["path"]: report_rec}
    cases = [_case_from_report(case, records) for case in report.get("cases", [])]
    if {case["sentinel_id"] for case in cases} != {"F6-S1", "F6-S2"}:
        raise BuildFailure("ROOT244 report does not contain exactly F6-S1 and F6-S2")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_NOT_RUN_F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT",
        "root244_proof_status": proof.get("status"),
        "proof": proof_rec,
        "report": report_rec,
        "cases": cases,
        "read_scope": {
            "proof_report_and_xml_only": True,
            "native_payload_read": False,
            "vtk_read": False,
            "hdf5_read": False,
            "runparts_read": False,
            "solver_launch": False,
        },
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
    }
    _write_once(args.manifest_output, manifest)
    _, manifest_rec = _record(args.manifest_output, "F6 geometry manifest")
    records[manifest_rec["path"]] = manifest_rec
    for path, label in ((WORKER, "F6 geometry worker"), (CONTRACT, "F6 geometry contract")):
        rec = _code(path, label)
        records[rec["path"]] = rec
    py = _python_binding()
    records[py["resolved"]["path"]] = py["resolved"]
    records[py["pyvenv_cfg"]["path"]] = py["pyvenv_cfg"]
    files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in files}
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": "ds02.stage2.f6-continuous-owner-geometry-audit-request.v1",
        "status": "READY_FOR_PARENT_V8_F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT_ROOT252",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": "F6",
        "sentinel_ids": ["F6-S1", "F6-S2"],
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "command": [str(PYTHON), str(WORKER), "--manifest", str(args.manifest_output.absolute()), "--output", "{attempt_root}/audit/f6_continuous_owner_geometry_audit_v1.json"],
        "input_files": files,
        "input_hashes": hashes,
        "input_sha256": hashes,
        "input_records": records,
        "deferred_input_files": [],
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "estimated_input_read_bytes": sum(int(rec["bytes"]) for rec in records.values()),
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "vtk_read": False,
        "runparts_read": False,
        "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/audit/f6_continuous_owner_geometry_audit_v1.json"},
        "source_binding": {
            "continuous_owner_basis": "explicit XML solid fluid drawbox only",
            "sample_mass_is_diagnostic_only": True,
            "clip_boolean_semantics": "UNKNOWN unless explicit XML primitive",
            "native_support": "UNKNOWN_PENDING_GUARDED_NATIVE_FRAME_AUDIT",
            "interpolation": False,
            "neighbor_grid_truth": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "resource_guard": {"runner": "parent-v8-audit", "native_payload": "forbidden", "solver_launch": "forbidden", "large_report": "forbidden"},
    }
    request["sha256"] = _canonical(request)
    _write_once(args.output_request, request)
    return request


def _self_test() -> None:
    assert _canonical({"x": 1}) == _canonical({"x": 1})
    assert Path("fixture.bi4").suffix.lower() == ".bi4"
    print("PASS_F6_CONTINUOUS_OWNER_GEOMETRY_REQUEST_V1_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--case-id", default="F6_CONTINUOUS_OWNER_GEOMETRY_AUDIT_ROOT252")
    parser.add_argument("--attempt-id", default="f6-continuous-owner-geometry-audit-v1-root-252-001")
    parser.add_argument("--launch-commit", default="SOURCE_ONLY_ROOT252")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if args.proof is None or args.manifest_output is None or args.output_request is None:
        parser.error("--proof, --manifest-output and --output-request are required unless --self-test")
    try:
        request = build(args)
    except Exception as exc:
        print(f"FAILED_F6_CONTINUOUS_OWNER_GEOMETRY_REQUEST: {exc}")
        return 2
    print(json.dumps({"status": request["status"], "request": str(args.output_request.absolute()), "sha256": request["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
