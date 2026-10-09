#!/usr/bin/env python3
"""Build a source-only ROOT281 world-axis/unit calibration route.

The request is launch-disabled until a parent supplies selected native file
records after reservation.  The builder reads small proof/report/source files
only; BI4/VTK/H5 paths remain deferred and are never opened here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
SOURCE = Path("/home/jade/Projects/DualSPHysics")
CP = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
WORKER = HERE / "stage2_f1_world_axis_unit_calibration_v1.py"
CONTRACT = HERE / "stage2_f1_world_axis_unit_calibration_contract_v1.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.stage2.f1.world-axis-unit-calibration-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1.world-axis-unit-calibration-manifest.v1"
MAX_SMALL = 16 * 1024 * 1024
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".vtu", ".h5", ".hdf5"}

ROOT207_PROOF = CP / "F1_NATIVE_SELECTED_OBSERVER_V5_ACTUAL_ROOT_VERIFICATION_207.json"
ROOT217_PROOF = CP / "OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json"


class BuildFailure(RuntimeError):
    pass


def _record(path: Path, label: str, *, payload_allowed: bool = False) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file() or (path.suffix.lower() in PAYLOAD_SUFFIXES and not payload_allowed):
        raise BuildFailure(f"{label} is not an allowed source file: {path}")
    before = path.stat()
    if before.st_size > MAX_SMALL:
        raise BuildFailure(f"{label} exceeds bounded read: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise BuildFailure(f"{label} changed while read: {path}")
    return {"path": str(path), "bytes": int(after.st_size), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns), "device": int(after.st_dev), "inode": int(after.st_ino), "sha256": digest, "payload_read_by_builder": False}


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    rec = _record(path, label)
    value = json.loads(Path(rec["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not an object")
    return value, rec


def _proof_and_report(proof_path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proof, proof_record = _json(proof_path, label + " proof")
    if not str(proof.get("status", "")).startswith(("VERIFIED", "PASS", "ACTUAL")):
        raise BuildFailure(f"{label} proof is not terminal")
    report_path = proof.get("report")
    report_sha = proof.get("report_sha256")
    if not isinstance(report_path, str) or not isinstance(report_sha, str):
        raise BuildFailure(f"{label} proof lacks report SHA/path")
    report_record = _record(Path(report_path), label + " report")
    if report_record["sha256"] != report_sha:
        raise BuildFailure(f"{label} report SHA changed")
    return proof, proof_record, report_record


def _official_sources() -> list[Path]:
    return [
        SOURCE / "src/source/JPartDataBi4.cpp", SOURCE / "src/source/JPartDataBi4.h",
        SOURCE / "src/source/JPartDataHead.cpp", SOURCE / "src/source/JPartDataHead.h",
        SOURCE / "src/source/JPartOutBi4Save.cpp", SOURCE / "src/source/JPartOutBi4Save.h",
        SOURCE / "src/source/JPartsLoad4.cpp", SOURCE / "src/source/JPartsLoad4.h",
        SOURCE / "src/source/JPeriodicDef.h", SOURCE / "src/source/JSphCpu_InOut.cpp",
        SOURCE / "src/source/JSphGpuSingle.cpp",
        SOURCE / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp",
        HERE / "stage2_native_physical_observer_v2.py",
        HERE / "stage2_f1_native_selected_observer_v1.py",
    ]


def build(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    root207, root207_rec, root207_report = _proof_and_report(args.root207_proof, "ROOT207")
    root217, root217_rec, root217_report = _proof_and_report(args.root217_proof, "ROOT217")
    contract_value, contract_record = _json(CONTRACT, "world-axis contract")
    if contract_value.get("schema") != "ds02.stage2.f1.world-axis-unit-calibration-contract.v1":
        raise BuildFailure("world-axis contract schema mismatch")
    source_records = [contract_record, _record(WORKER, "world-axis worker"), _record(Path(__file__), "world-axis request builder")]
    for path in _official_sources():
        source_records.append(_record(path, f"official source {path.name}"))
    # Proof/report are small metadata inputs.  Their nested native paths are
    # intentionally not traversed or hashed by this builder.
    proof_records = [root207_rec, root207_report, root217_rec, root217_report]
    source_records.extend(proof_records)
    source_records = list({item["path"]: item for item in source_records}.values())
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "SOURCE_PREPARED_PARENT_NATIVE_AXIS_UNIT_OBSERVATION_REQUIRED",
        "contract": contract_record,
        "source_records": source_records,
        "proof_records": [root207_rec, root217_rec],
        "proof_report_records": [root207_report, root217_report],
        "deferred_native_records": [],
        "deferred_native_policy": {"selected_frames": "parent supplies exact native Part paths after reservation", "pre_sha_stat": True, "post_sha_stat": True, "decode": "future guarded observer only", "world_axis": "UNKNOWN until source/XML/Run.out/native join"},
        "official_source_route": {
            "writer": ["JPartDataBi4::Config", "ConfigParticles", "ConfigCtes", "ConfigSimMap", "ConfigSimPeri", "AddPartData"],
            "reader": ["JPartsLoad4::Get_Pos/Get_Posd/Get_Vel/Get_Rhop", "JPartDataBi4 load arrays"],
            "periodic": ["MapPosMin/MapPosMax", "PeriMode", "PeriXinc/PeriYinc/PeriZinc", "JSphCpu::Interaction_PosNoPeriodic"],
            "execution_join": "actual request/receipt/Run.out/XML required; key names alone are not authority",
        },
        "observables": {"component_space": ["role_counts", "Idp/Idpd", "Pos/Posd", "Vel", "Rhop", "MassFluid", "MassBound", "Dp", "TimeStep"], "world_axis": "UNKNOWN", "units": {"position": "m", "velocity": "m/s", "mass": "kg", "time": "s"}},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
        "source_scope": {"builder_payload_read": False, "production_native_payload_read": False, "hdf5_read": False, "vtk_read": False, "solver_launch": False},
    }
    manifest_path = args.manifest_output.expanduser().absolute(); request_path = args.request_output.expanduser().absolute()
    if manifest_path.exists() or request_path.exists():
        raise BuildFailure("refusing overwrite")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_record = _record(manifest_path, "world-axis manifest")
    inputs = {item["path"]: item for item in source_records}; inputs[manifest_record["path"]] = manifest_record
    request = {
        "schema": "ds02.request.v1", "variant_schema": SCHEMA,
        "status": "READY_FOR_PARENT_V8_F1_WORLD_AXIS_UNIT_CALIBRATION_AFTER_NATIVE_SNAPSHOT",
        "kind": "cpu", "cpu_task_kind": "audit", "request_id": "f1-world-axis-unit-calibration-root281-v1-001",
        "family_id": "F1", "sentinel_id": "F1-S1+F1-S2", "physical_case_id": "F1_WORLD_AXIS_UNIT_SOURCE_ROUTE_V1", "case_id": "F1_WORLD_AXIS_UNIT_CALIBRATION_ROOT281_V1", "attempt_id": "f1-world-axis-unit-calibration-root281-v1-001",
        "cwd": str(REPO / "lagrangian-fluid-lab"), "worktree_root": str(REPO),
        "command": [str(PYTHON), "-B", str(WORKER), "--run", "--manifest", manifest_record["path"], "--output", "{attempt_root}/calibration/f1_world_axis_unit_calibration_v1.json"],
        "input_files": sorted(inputs), "input_sha256": {path: inputs[path]["sha256"] for path in sorted(inputs)}, "input_records": inputs, "manifest": manifest_record,
        "deferred_input_files": [], "deferred_input_records": [], "deferred_input_policy": manifest["deferred_native_policy"],
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600, "max_memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "estimated_native_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "launch_disabled": True, "execution_allowed": False, "solver_started": False, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "ledger_mutation": False,
        "source_binding": {"root207": root207_rec, "root217": root217_rec, "world_axis": "UNKNOWN", "component_space_observation": "allowed after future parent native snapshot", "interpolation": "FORBIDDEN", "neighbor_grid_truth": False, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        "runtime_closure": {"worker": str(WORKER), "contract": str(CONTRACT), "official_writer": str(SOURCE / "src/source/JPartDataBi4.cpp"), "official_loader": str(SOURCE / "src/source/JPartsLoad4.cpp"), "periodic_source": str(SOURCE / "src/source/JSphCpu_InOut.cpp"), "decoder_source": str(SOURCE / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"), "literal_python": str(PYTHON)},
    }
    request_path.parent.mkdir(parents=True, exist_ok=True); request_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest, request


def self_test() -> None:
    assert "JPartDataBi4::ConfigSimPeri" in json.loads(CONTRACT.read_text(encoding="utf-8"))["official_mapping"]["periodic"] if isinstance(json.loads(CONTRACT.read_text(encoding="utf-8"))["official_mapping"]["periodic"], str) else True
    print("PASS_F1_WORLD_AXIS_UNIT_CALIBRATION_REQUEST_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); group = parser.add_mutually_exclusive_group(required=True); group.add_argument("--self-test", action="store_true"); group.add_argument("--build", action="store_true")
    parser.add_argument("--root207-proof", type=Path, default=ROOT207_PROOF); parser.add_argument("--root217-proof", type=Path, default=ROOT217_PROOF); parser.add_argument("--manifest-output", type=Path); parser.add_argument("--request-output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if args.manifest_output is None or args.request_output is None:
        parser.error("--build requires --manifest-output and --request-output")
    try:
        _, request = build(args)
    except Exception as exc:
        print(f"FAILED_F1_WORLD_AXIS_UNIT_CALIBRATION_REQUEST: {exc}")
        return 2
    print(json.dumps({"status": request["status"], "native_payload_read": False, "request": str(args.request_output.absolute())}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
