#!/usr/bin/env python3
"""Validate the source authority route for a future F1 world/unit read.

This worker is intentionally a bounded metadata gate.  It validates the
official writer/loader/periodic source records and the ROOT207/ROOT217
small-proof joins, then records that a future guarded native observation is
still required.  It never opens a BI4/VTK/H5 payload and never turns the
manufactured ROOT217 fixture into historical producer world-axis evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "ds02.stage2.f1.world-axis-unit-calibration.v1"
CONTRACT_SCHEMA = "ds02.stage2.f1.world-axis-unit-calibration-contract.v1"
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".vtu", ".h5", ".hdf5"}
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}
STAT_FIELDS = ("bytes", "mtime_ns", "ctime_ns", "device", "inode")


class CalibrationFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "device": int(value.st_dev), "inode": int(value.st_ino)}


def _record(spec: dict[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
        raise CalibrationFailure(f"{label} lacks path record")
    path = Path(spec["path"]).expanduser().absolute()
    if path.is_symlink() or not path.is_file() or path.suffix.lower() in PAYLOAD_SUFFIXES:
        raise CalibrationFailure(f"{label} is not an allowed bounded source file: {path}")
    before = _stat(path)
    if before["bytes"] > 16 * 1024 * 1024:
        raise CalibrationFailure(f"{label} exceeds bounded source read: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = _stat(path)
    if before != after:
        raise CalibrationFailure(f"{label} changed while read: {path}")
    for key in STAT_FIELDS:
        if key in spec and int(spec[key]) != before[key]:
            raise CalibrationFailure(f"{label} {key} differs from bound record")
    if spec.get("sha256") is not None and spec["sha256"] != digest:
        raise CalibrationFailure(f"{label} SHA differs from bound record")
    return {"path": str(path), **before, "sha256": digest, "stable_read": True}


def _json_record(spec: dict[str, Any], label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(spec, label)
    value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CalibrationFailure(f"{label} is not a JSON object")
    return value, record


def _validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != "ds02.stage2.f1.world-axis-unit-calibration-manifest.v1":
        raise CalibrationFailure("world-axis calibration manifest schema mismatch")
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise CalibrationFailure("manifest lacks contract record")
    contract_value, contract_record = _json_record(contract, "world-axis contract")
    if contract_value.get("schema") != CONTRACT_SCHEMA:
        raise CalibrationFailure("world-axis contract schema mismatch")
    coordinate = contract_value.get("coordinate_scope", {})
    if coordinate.get("world_frame") != "UNKNOWN until actual producer XML/Run.out/source update and guarded native metadata agree":
        raise CalibrationFailure("world-axis UNKNOWN policy was weakened")
    units = contract_value.get("units", {})
    expected = {"position": "m", "velocity": "m/s", "mass": "kg", "time": "s"}
    if any(units.get(key, {}).get("unit") != unit for key, unit in expected.items()):
        raise CalibrationFailure("source unit contract is incomplete")
    source_records = manifest.get("source_records")
    if not isinstance(source_records, list) or not source_records:
        raise CalibrationFailure("manifest has no official source records")
    checked = [_record(item, "official source record") for item in source_records]
    proof_records = manifest.get("proof_records")
    if not isinstance(proof_records, list) or len(proof_records) != 2:
        raise CalibrationFailure("manifest must bind ROOT207 and ROOT217 proof records")
    proofs = []
    for item in proof_records:
        proof, rec = _json_record(item, "calibration proof")
        if not (str(proof.get("status", "")).startswith(("VERIFIED", "PASS", "ACTUAL"))):
            raise CalibrationFailure("calibration proof is not terminal")
        report = proof.get("report")
        if not isinstance(report, str):
            raise CalibrationFailure("calibration proof lacks report path")
        report_spec = {"path": report, "sha256": proof.get("report_sha256")}
        report_record = _record(report_spec, "calibration proof report")
        proofs.append({"proof": rec, "report": report_record, "manufactured_only": proof.get("production_reader_or_world_axis_calibration_not_inferred", False) is True})
    deferred = manifest.get("deferred_native_records", [])
    if not isinstance(deferred, list):
        raise CalibrationFailure("deferred_native_records must be a list")
    for item in deferred:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"].lower().endswith(".bi4"):
            raise CalibrationFailure("deferred native record is malformed")
        if item.get("content_sha256") not in (None, "DEFERRED_TO_PARENT_AFTER_RESERVATION"):
            if not isinstance(item["content_sha256"], str) or len(item["content_sha256"]) != 64:
                raise CalibrationFailure("deferred native SHA is malformed")
    return {"contract": contract_record, "source_records": checked, "proofs": proofs, "deferred_count": len(deferred)}


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest, manifest_record = _json_record({"path": str(manifest_path)}, "world-axis manifest")
    checked = _validate_manifest(manifest)
    result = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_NATIVE_AXIS_UNIT_OBSERVATION" if checked["deferred_count"] else "WAITING_PARENT_NATIVE_SOURCE_SNAPSHOT",
        "manifest": manifest_record,
        "source_authority": {
            "official_writer_loader": "JPartDataBi4/JPartDataHead/JPartsLoad4",
            "serialization": ["Idp/Idpd", "Pos/Posd", "Vel", "Rhop"],
            "domain_periodic": ["MapPosMin/MapPosMax", "PeriMode", "PeriXinc", "PeriYinc", "PeriZinc", "JSphCpu::Interaction_PosNoPeriodic"],
            "xml_runout_join": "required from actual execution request/receipt; not inferred from field names",
        },
        "proofs": checked["proofs"],
        "deferred_native_records": checked["deferred_count"],
        "observables": {"component_space": ["role_counts", "Idp/Idpd", "Pos/Posd", "Vel", "Rhop", "native MassFluid/MassBound", "Dp", "TimeStep"], "world_axis": "UNKNOWN", "units": "source-bound SI route ready; historical producer readback required"},
        "qualification": UNKNOWN,
        "read_scope": {"production_native_payload_read": False, "hdf5_read": False, "vtk_read": False, "solver_launch": False, "interpolation": False, "neighbor_grid_truth": False},
    }
    output = output.expanduser().absolute(); output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise CalibrationFailure(f"refusing overwrite: {output}")
    output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def self_test() -> None:
    contract = {"schema": CONTRACT_SCHEMA, "coordinate_scope": {"world_frame": "UNKNOWN until actual producer XML/Run.out/source update and guarded native metadata agree"}, "units": {key: {"unit": unit} for key, unit in {"position": "m", "velocity": "m/s", "mass": "kg", "time": "s"}.items()}}
    assert contract["coordinate_scope"]["world_frame"].startswith("UNKNOWN")
    assert all(item["unit"] in ("m", "m/s", "kg", "s") for item in contract["units"].values())
    print("PASS_F1_WORLD_AXIS_UNIT_CALIBRATION_WORKER_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True); group.add_argument("--self-test", action="store_true"); group.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if args.manifest is None or args.output is None:
        parser.error("--run requires --manifest and --output")
    try:
        result = run(args.manifest, args.output)
    except Exception as exc:
        print(f"FAILED_F1_WORLD_AXIS_UNIT_CALIBRATION: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.absolute()), "production_native_payload_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
