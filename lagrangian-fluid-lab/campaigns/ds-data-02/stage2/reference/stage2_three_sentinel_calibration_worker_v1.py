#!/usr/bin/env python3
"""Run one bounded initial-support calibration parent for F2-S2, F3-S1, or F5-S1.

This is an additive CLI over the frozen owner-grid payload parser.  The
parent supplies exactly one sentinel's original/coarse/fine GenCase products
in a manifest.  The worker reads generated XML, Fluid/Bound VTK, and the
generated BI4 bytes only after the parent has reserved the request; it records
stable pre/decode/post SHA/stat guards and never starts GenCase or a solver.

The report separates the four scientific dimensions explicitly.  Initial
support and native-header fields are reported when the guarded product
contains them.  Spatial rows are diagnostic support evidence only; integration
and output-cadence error are ``NOT_IN_THIS_PARENT`` unless a later source-bound
pair is registered.  XML mass is never used as native MassFluid/MassBound and
all QI/QN/QE values remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
FROZEN_WORKER = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
FROZEN_SPEC = importlib.util.spec_from_file_location(
    "stage2_owner_grid_initial_support_worker_frozen_v1", FROZEN_WORKER
)
if FROZEN_SPEC is None or FROZEN_SPEC.loader is None:
    raise RuntimeError(f"cannot import frozen owner-grid worker: {FROZEN_WORKER}")
FROZEN = importlib.util.module_from_spec(FROZEN_SPEC)
FROZEN_SPEC.loader.exec_module(FROZEN)

SCHEMA = "ds02.stage2.three-sentinel-calibration-worker.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-calibration-manifest.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
ROW_KEYS = tuple(f"{sid}:{grid}" for sid in TARGETS for grid in GRIDS)
JSON_CAP = 10 * 1024 * 1024
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class CalibrationFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise CalibrationFailure(f"manifest is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise CalibrationFailure(f"manifest exceeds 10 MiB cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise CalibrationFailure(f"manifest changed during read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationFailure(f"manifest is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CalibrationFailure("manifest must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after, "bytes": len(raw)}


def _dimension_status(sentinel_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    native = [row.get("native_header", {}).get("status", "UNKNOWN") for row in rows]
    return {
        "spatial": {
            "status": "SUPPORT_ONLY_NO_CROSS_GRID_TRUTH",
            "observed": "original/coarse/fine support rows are retained separately",
            "truth_credit": False,
        },
        "integration": {
            "status": "NOT_IN_THIS_PARENT",
            "required_pair": "same grid/source/output cadence with CFL-only change and actual dt/clamp trace",
            "truth_credit": False,
        },
        "output_sampling": {
            "status": "NOT_IN_THIS_PARENT",
            "required_pair": "same grid/source/CFL with output cadence-only change and exact saved rows",
            "truth_credit": False,
        },
        "native_header": {
            "status": "PASS_IF_ALL_BOUND" if native and all(str(item).startswith("PASS") for item in native) else "PARTIAL_OR_UNKNOWN",
            "row_statuses": native,
            "xml_mass_fallback": False,
            "truth_credit": False,
        },
    }


def _decorate(sentinel_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sentinel_id": sentinel_id,
        "grid_rows": rows,
        "dimension_status": _dimension_status(sentinel_id, rows),
        "frozen_gates": {
            "position": "2% registered L; 5% near event",
            "velocity_ke": "5% of registered nonzero scale",
            "regional_mass": "3 percentage points of whole initial fluid mass",
            "time_output": "each <= one quarter of its registered task gate",
        },
        "scientific_qualification": dict(UNKNOWN_QUALIFICATION),
        "admission": {
            "initial_support_only": True,
            "solver_launch": False,
            "gencase_launch": False,
            "neighbor_grid_truth": False,
            "interpolation": False,
            "mass_rescale": False,
            "xml_mass_is_not_native_mass": True,
        },
    }


def _read_scale_registry(record: dict[str, Any], sentinel_id: str) -> dict[str, Any]:
    """Read only the small frozen scale registry and bind its exact bytes.

    Numerical denominators are part of the preregistration contract.  A
    worker must never silently replace them with a value from XML, a native
    sample count, or another sentinel.  The registry is intentionally a
    small static input; all generated/native products remain deferred.
    """
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise CalibrationFailure("manifest has no calibration_scales path")
    path = _absolute(Path(record["path"]))
    value, guard = _read_manifest(path)
    expected = record.get("sha256")
    if not isinstance(expected, str) or guard["sha256"] != expected:
        raise CalibrationFailure("calibration scale registry SHA does not match manifest")
    if value.get("schema") != "ds02.stage2.three-sentinel-calibration-scales.v2":
        raise CalibrationFailure("calibration scale registry schema mismatch")
    rows = value.get("sentinels")
    row = next((item for item in rows if isinstance(item, dict) and item.get("sentinel_id") == sentinel_id), None) \
        if isinstance(rows, list) else None
    if row is None:
        raise CalibrationFailure(f"calibration scale registry has no {sentinel_id} row")
    if value.get("scientific_credit") != 0 or value.get("status") != "SOURCE_BOUND_NUMERICAL_SCALES_WITH_EXPLICIT_BLOCKERS_NO_Q":
        raise CalibrationFailure("calibration scale registry grants scientific credit")
    return {"record": guard, "registry": value, "sentinel": row}


def _validate_manifest(manifest: dict[str, Any]) -> tuple[str, dict[str, dict[str, Any]], dict[str, Any]]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise CalibrationFailure(f"manifest schema mismatch: {manifest.get('schema')!r}")
    if manifest.get("status") != "READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION":
        raise CalibrationFailure("manifest is not a guarded calibration manifest")
    sentinel_id = manifest.get("sentinel_id")
    if sentinel_id not in TARGETS:
        raise CalibrationFailure("manifest must contain exactly one eligible sentinel")
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != len(GRIDS):
        raise CalibrationFailure("manifest must contain exactly original/coarse/fine rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("sentinel_id") != sentinel_id or row.get("grid_label") not in GRIDS:
            raise CalibrationFailure("manifest row sentinel/grid is invalid")
        key = f"{sentinel_id}:{row['grid_label']}"
        if key in result:
            raise CalibrationFailure(f"duplicate manifest row: {key}")
        result[key] = row
    expected = {f"{sentinel_id}:{grid}" for grid in GRIDS}
    if set(result) != expected:
        raise CalibrationFailure("manifest does not contain exactly three grid rows")
    scope = manifest.get("scientific_scope")
    if not isinstance(scope, dict) or scope.get("scientific_credit") != 0:
        raise CalibrationFailure("manifest scientific scope grants credit")
    if scope.get("neighbor_grid_truth") is not False or scope.get("interpolation") is not False:
        raise CalibrationFailure("manifest permits neighboring-grid truth or interpolation")
    scale_record = manifest.get("calibration_scales")
    if not isinstance(scale_record, dict):
        raise CalibrationFailure("manifest must bind the frozen calibration scale registry")
    return str(sentinel_id), result, scale_record


def run(manifest_path: Path, attempt_root: Path, output_path: Path) -> dict[str, Any]:
    manifest, manifest_guard = _read_manifest(manifest_path)
    sentinel_id, rows, scale_record = _validate_manifest(manifest)
    scale_guard = _read_scale_registry(scale_record, sentinel_id)
    audited: list[dict[str, Any]] = []
    for grid in GRIDS:
        key = f"{sentinel_id}:{grid}"
        case = rows[key]
        try:
            result = FROZEN._audit_case(case, _absolute(attempt_root))
            # A missing optional probe is an explicit UNKNOWN, never an XML
            # mass fallback.  Keep this semantic marker on every successful
            # row so an independent verifier can reject accidental fallback.
            native_header = result.setdefault("native_header", {})
            native_header.setdefault("status", "UNKNOWN_NATIVE_HEADER_PROBE_NOT_BOUND")
            native_header["xml_mass_is_not_native"] = True
            result.setdefault("admission", {})["mass_rescale"] = False
            result["scientific_qualification"] = dict(UNKNOWN_QUALIFICATION)
            audited.append(result)
        except Exception as exc:  # retain per-grid failure as diagnostic evidence
            audited.append({
                "row_key": key,
                "sentinel_id": sentinel_id,
                "grid_label": grid,
                "status": "FAILED_INITIAL_SUPPORT_DIAGNOSTIC",
                "reason": repr(exc),
                "scientific_qualification": dict(UNKNOWN_QUALIFICATION),
                "admission": {"solver_launch": False, "gencase_launch": False, "scientific_credit": 0},
            })
    result = _decorate(sentinel_id, audited)
    result.update({
        "schema": SCHEMA,
        "status": "COMPLETE_PARTIAL_THREE_SENTINEL_CALIBRATION_DIAGNOSTIC",
        "manifest": manifest_guard,
        "calibration_scales": scale_guard,
        "read_scope": {
            "generated_xml": True,
            "fluid_vtk": True,
            "bound_vtk": True,
            "native_bi4_bytes": True,
            "native_header_probe_optional": True,
            "production_hdf5": False,
            "solver_launch": False,
            "gencase_launch": False,
        },
    })
    output_path = _absolute(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise CalibrationFailure(f"refusing to overwrite report: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def _fixture_manifest(root: Path, sentinel_id: str) -> Path:
    """Use the frozen tiny product generator; no production payload is read."""
    source = FROZEN._fixture_manifest(root / "frozen")
    full = json.loads(source.read_text(encoding="utf-8"))
    cases = [row for row in full["cases"] if row.get("sentinel_id") == sentinel_id]
    scale_source = HERE / "stage2_three_sentinel_calibration_scales_v2.json"
    scale_path = root / "calibration-scales-v2.json"
    scale_path.parent.mkdir(parents=True, exist_ok=True)
    scale_path.write_bytes(scale_source.read_bytes())
    scale_raw = scale_path.read_bytes()
    scale_guard = {"path": str(scale_path), "sha256": _sha(scale_raw),
                   "stat": _stat(scale_path), "payload_read_by_builder": False,
                   "scope": "bounded_static_calibration_registry"}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION",
        "sentinel_id": sentinel_id,
        "cases": cases,
        "calibration_scales": scale_guard,
        "scientific_scope": {"neighbor_grid_truth": False, "interpolation": False, "scientific_credit": 0},
    }
    path = root / f"{sentinel_id.replace('-', '_')}-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="three-sentinel-calibration-worker-") as directory:
        root = Path(directory)
        for sentinel_id in TARGETS:
            manifest = _fixture_manifest(root / sentinel_id.replace("-", "_"), sentinel_id)
            output = root / f"{sentinel_id.replace('-', '_')}-report.json"
            value = run(manifest, root / "attempt", output)
            assert value["status"].startswith("COMPLETE_PARTIAL")
            assert len(value["grid_rows"]) == 3
            assert all(row["scientific_qualification"] == UNKNOWN_QUALIFICATION for row in value["grid_rows"])
            assert value["dimension_status"]["integration"]["status"] == "NOT_IN_THIS_PARENT"
            assert value["dimension_status"]["output_sampling"]["status"] == "NOT_IN_THIS_PARENT"
    print("PASS_THREE_SENTINEL_CALIBRATION_WORKER_V1_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.manifest is None or args.attempt_root is None or args.output is None:
            parser.error("--run requires --manifest, --attempt-root and --output")
        value = run(args.manifest, args.attempt_root, args.output)
    except (CalibrationFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_CALIBRATION_WORKER_V1: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value["status"], "output": str(_absolute(args.output)),
                      "sentinel_id": value["sentinel_id"], "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
