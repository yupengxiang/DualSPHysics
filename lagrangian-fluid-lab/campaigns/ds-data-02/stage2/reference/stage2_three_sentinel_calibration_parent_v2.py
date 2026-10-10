#!/usr/bin/env python3
"""Prepare the post-ROOT345 three-sentinel calibration handoff (V2).

This adapter consumes the strict ROOT345 V2 handoff manifest and emits three
execution-disabled calibration source packages.  It does not turn a deferred
GenCase path into a ready product: the frozen calibration worker additionally
needs source XML/Def, the exact GenCase receipt, owner predicate, and all four
product records.  Those records are materialized from the producer request and
proof only after ROOT345 and the initial-support parent close.  Missing fields
remain explicit WAITING reasons; QI/QN/QE and scientific credit stay unknown.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
HANDOFF_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-native-initial-support-handoff.v2"
REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.three-sentinel.calibration-parent-handoff.v2"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel.calibration-parent-manifest.v2"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
JSON_CAP = 10 * 1024 * 1024
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
WORKER = HERE / "stage2_three_sentinel_calibration_worker_v1.py"
VERIFY = HERE / "stage2_three_sentinel_calibration_verify_v1.py"
CONTRACT = HERE / "stage2_three_sentinel_calibration_worker_contract_v1.json"
SCALES = HERE / "stage2_three_sentinel_calibration_scales_v2.json"
RUNTIME = HERE.parents[4] / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"


class CalibrationHandoffFailure(RuntimeError):
    pass


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _record(path: Path, label: str, *, json_only: bool = False) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise CalibrationHandoffFailure(f"{label} is not a regular source file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise CalibrationHandoffFailure(f"{label} exceeds the 10 MiB source cap: {path}")
    if json_only and path.suffix.lower() != ".json":
        raise CalibrationHandoffFailure(f"{label} is not JSON metadata: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after:
        raise CalibrationHandoffFailure(f"{label} changed during bounded read: {path}")
    return {"path": str(path), "label": label, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "stat": after,
            "payload_read_by_builder": False, "scope": "bounded_source_metadata"}


def _read(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label, json_only=True)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationHandoffFailure(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CalibrationHandoffFailure(f"{label} is not a JSON object")
    return value, record


def _row_key(row: dict[str, Any]) -> str:
    return f"{row.get('sentinel_id')}:{row.get('grid_label')}"


def _case_requirements(row: dict[str, Any]) -> list[str]:
    required = ["source_xml", "source_def", "candidate_def", "gencase_receipt", "owner_predicate"]
    products = row.get("product_records")
    if not isinstance(products, dict):
        required.append("product_records.generated_xml/fluid_vtk/bound_vtk/native_bi4")
    else:
        for name in ("generated_xml", "fluid_vtk", "bound_vtk", "native_bi4"):
            value = products.get(name)
            if not isinstance(value, dict) or not isinstance(value.get("path"), str):
                required.append(f"product_records.{name}")
    return required


def build(handoff_path: Path, output_dir: Path) -> dict[str, Any]:
    handoff, handoff_record = _read(_abs(handoff_path), "ROOT345 V2 handoff")
    if handoff.get("schema") != HANDOFF_SCHEMA:
        raise CalibrationHandoffFailure("handoff schema is not ROOT345 V2")
    rows = handoff.get("rows")
    if not isinstance(rows, list) or len(rows) != 9:
        raise CalibrationHandoffFailure("handoff must contain exactly nine rows")
    by_target: dict[str, list[dict[str, Any]]] = {sid: [] for sid in TARGETS}
    for row in rows:
        if not isinstance(row, dict) or row.get("sentinel_id") not in by_target or row.get("grid_label") not in GRIDS:
            raise CalibrationHandoffFailure("handoff row has invalid target/grid")
        by_target[str(row["sentinel_id"])].append(row)
    for sid, values in by_target.items():
        if {str(row.get("grid_label")) for row in values} != set(GRIDS):
            raise CalibrationHandoffFailure(f"handoff does not contain exactly three rows for {sid}")
    static: dict[str, dict[str, Any]] = {handoff_record["path"]: handoff_record}
    for path, label in ((WORKER, "calibration worker V1"), (VERIFY, "calibration verifier V1"),
                        (CONTRACT, "calibration contract"), (SCALES, "calibration scales"),
                        (RUNTIME, "shared runtime V2"), (PYVENV, "pyvenv.cfg"),
                        (PYTHON.resolve(), "resolved project interpreter"), (Path(__file__), "calibration handoff V2")):
        static[str(_abs(path))] = _record(path, label)

    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise CalibrationHandoffFailure(f"refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    packages: list[dict[str, Any]] = []
    all_ready = handoff.get("status") == "READY_FOR_PARENT_NATIVE_HEADER_V3_AND_INITIAL_SUPPORT"
    for sid in TARGETS:
        target_rows = by_target[sid]
        missing = {row_key: _case_requirements(row) for row in target_rows
                   if (row_key := _row_key(row)) and _case_requirements(row)}
        ready = all_ready and not missing and all(row.get("edge_status") == "VERIFIED_COMPLETED_PRODUCER_EDGE" for row in target_rows)
        target_dir = output_dir / sid.replace("-", "_"); target_dir.mkdir()
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "status": "READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION" if ready else "WAITING_ROOT345_NATIVE_HEADER_AND_INITIAL_SUPPORT",
            "sentinel_id": sid, "handoff": handoff_record, "cases": target_rows,
            "missing_case_fields": missing, "calibration_worker": {"path": str(WORKER), "sha256": static[str(WORKER)]["sha256"]},
            "scientific_scope": {"neighbor_grid_truth": False, "interpolation": False,
                                  "xml_mass_is_not_native_mass": True, "mass_rescale": False, **UNKNOWN},
            "native_header_scope": "MassFluid/MassBound per-particle; typed role counts or per-ID weights required",
        }
        manifest_path = target_dir / f"{sid.replace('-', '_')}-calibration-parent-manifest-v2.json"
        _write(manifest_path, manifest)
        manifest_record = _record(manifest_path, f"{sid} calibration parent manifest", json_only=True)
        request = {
            "schema": REQUEST_SCHEMA, "variant_schema": SCHEMA,
            "status": manifest["status"], "request_variant": "three-sentinel-calibration-parent-v2",
            "family_id": sid[:2], "sentinel_id": sid,
            "case_id": f"{sid.replace('-', '_')}_INITIAL_SUPPORT_CALIBRATION_PARENT_V2",
            "attempt_id": "PARENT_ASSIGNED_AFTER_RESERVATION", "cpu_task_kind": "audit", "cpu_threads": 1,
            "execution_allowed": False, "launch_disabled": True,
            "command": [str(PYTHON), str(WORKER), "--run", "--manifest", str(manifest_path),
                        "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/report/calibration-v2.json"],
            "manifest": manifest_record, "input_files": sorted(static), "input_records": static,
            "input_sha256": {path: item["sha256"] for path, item in static.items()},
            "deferred_input_records": [{"row_key": _row_key(row), "role": "producer_products_and_support",
                                        "scope": "parent_after_reservation", "path": item.get("path")}
                                       for row in target_rows for item in (row.get("product_records") or {}).values()
                                       if isinstance(item, dict) and isinstance(item.get("path"), str)],
            "materialization_requirements": {"producer_request_proof_receipt_exact_join": True,
                                             "source_xml_def_candidate_def_owner_predicate": "from actual producer request/receipt closure",
                                             "native_mass_xml_fallback": False, "initial_support_before_solver": True},
            "scientific_qualification": dict(UNKNOWN), "solver_launch": False, "gencase_launch": False,
            "source_only": True, "native_payload_read": False, "ledger_mutation": False,
        }
        request_path = target_dir / f"{sid.replace('-', '_')}-calibration-parent-request-v2.json"
        _write(request_path, request)
        packages.append({"sentinel_id": sid, "ready": ready, "manifest": str(manifest_path),
                         "request": str(request_path), "missing_case_fields": missing, "scientific_qualification": dict(UNKNOWN)})
    package = {"schema": SCHEMA, "status": "READY_FOR_PARENT" if all(item["ready"] for item in packages) else "WAITING_ROOT345_NATIVE_HEADER_AND_INITIAL_SUPPORT",
               "handoff": handoff_record, "packages": packages, "source_records": list(static.values()),
               "scientific_qualification": dict(UNKNOWN), "production_payload_read_by_builder": False}
    package_path = output_dir / "three-sentinel-calibration-parent-package-v2.json"; _write(package_path, package)
    return {"status": package["status"], "package_path": str(package_path), "packages": packages, "scientific_credit": 0}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="three-sentinel-calibration-parent-v2-") as td:
        root = Path(td)
        rows = [{"sentinel_id": sid, "grid_label": grid, "edge_status": "WAITING_OR_REJECTED",
                 "product_records": {}} for sid in TARGETS for grid in GRIDS]
        handoff = root / "handoff.json"
        _write(handoff, {"schema": HANDOFF_SCHEMA, "status": "WAITING_ROOT345_PRODUCER_EDGES_OR_WHOLE_PARENT_SOURCE_CLOSURE",
                         "rows": rows, "scientific_qualification": dict(UNKNOWN)})
        result = build(handoff, root / "out")
        assert result["status"].startswith("WAITING_")
        assert len(result["packages"]) == 3
        assert all(item["scientific_qualification"] == UNKNOWN for item in result["packages"])
    print("PASS_THREE_SENTINEL_CALIBRATION_PARENT_V2_WAITING_HANDOFF_NO_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.handoff is None or args.output_dir is None:
            parser.error("--build requires --handoff and --output-dir")
        result = build(args.handoff, args.output_dir)
        print(json.dumps({"status": result["status"], "package": result["package_path"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (CalibrationHandoffFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_CALIBRATION_PARENT_V2: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
