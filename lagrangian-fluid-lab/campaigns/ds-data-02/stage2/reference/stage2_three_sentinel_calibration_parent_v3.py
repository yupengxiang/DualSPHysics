#!/usr/bin/env python3
"""Runtime-V10 source adapter for the ROOT345 calibration parent.

This additive wrapper consumes the V3 nested-runtime-receipt handoff and
reuses the calibration V2 request construction.  It adds the actual runtime
V10/V9/V8/V6/V2/Git-helper source closure and keeps the three requests
execution-disabled until native-header and initial-support parents have
completed.  It does not read deferred GenCase products.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_three_sentinel_calibration_parent_v2.py"
HANDOFF_V3_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-native-initial-support-handoff.v3"
SCHEMA = "ds02.stage2.three-sentinel.calibration-parent-handoff.v3"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class CalibrationV3Failure(RuntimeError):
    pass


def _load_v2() -> Any:
    spec = importlib.util.spec_from_file_location("three_sentinel_calibration_parent_v2_for_v3", V2_PATH)
    if spec is None or spec.loader is None:
        raise CalibrationV3Failure(f"cannot import calibration V2: {V2_PATH}")
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


V2 = _load_v2()
SCRIPT_DIR = HERE.parents[4] / "lagrangian-fluid-lab" / "scripts"
if not (SCRIPT_DIR / "ds_data02_runtime_v10_git_bound.py").is_file():
    SCRIPT_DIR = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts")
V10_FILES = (
    "ds_data02_runtime_v10_git_bound.py", "ds_data02_runtime_v9_git_bound.py",
    "ds_data02_runtime_v8.py", "ds_data02_runtime_v6.py", "ds_data02_runtime_v2.py",
    "ds_data02_git_launch_state_v1.py", "ds_data02_git_launch_state_v2.py",
    "ds_data02_git_launch_state_v3.py",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationV3Failure(f"cannot read generated JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CalibrationV3Failure(f"generated JSON is not an object: {path}")
    return value


def _record(path: Path, label: str) -> dict[str, Any]:
    try:
        return V2._record(path, label)
    except Exception as exc:
        raise CalibrationV3Failure(f"cannot record {path}: {exc}") from exc


def build(handoff: Path, output_dir: Path) -> dict[str, Any]:
    V2.HANDOFF_SCHEMA = HANDOFF_V3_SCHEMA
    V2.SCHEMA = SCHEMA
    V2.MANIFEST_SCHEMA = "ds02.stage2.three-sentinel.calibration-parent-manifest.v3"
    result = V2.build(handoff, output_dir)
    output_dir = Path(output_dir).absolute()
    package_path = Path(result["package_path"]).absolute()
    package = _load_json(package_path)
    package["schema"] = SCHEMA
    package["handoff_schema"] = HANDOFF_V3_SCHEMA
    package["runtime_v10_source_closure"] = {
        "schema": "ds02.stage2.runtime-v10-git-bound.v1", "files": [], "closure_complete": True,
    }
    # Add runtime source records to every target manifest/request.  These are
    # bounded code/config files, not GenCase/native payloads.
    runtime_records: list[dict[str, Any]] = []
    for name in V10_FILES:
        path = SCRIPT_DIR / name
        value = _record(path, f"calibration V3 runtime closure: {name}")
        runtime_records.append(value)
    package["runtime_v10_source_closure"]["files"] = [item["path"] for item in runtime_records]
    package["runtime_v10_source_closure"]["closure_complete"] = True
    for item in package.get("packages", []):
        manifest_path = Path(item["manifest"]).absolute()
        request_path = Path(item["request"]).absolute()
        manifest = _load_json(manifest_path); request = _load_json(request_path)
        manifest["schema"] = V2.MANIFEST_SCHEMA
        records = manifest.get("source_records", [])
        by_path = {entry.get("path"): entry for entry in records if isinstance(entry, dict) and isinstance(entry.get("path"), str)}
        for record in runtime_records:
            by_path[record["path"]] = record
        manifest["source_records"] = [by_path[key] for key in sorted(by_path)]
        manifest["runtime_v10_source_closure"] = package["runtime_v10_source_closure"]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_record = _record(manifest_path, f"{item['sentinel_id']} calibration V3 manifest")
        request["schema"] = V2.REQUEST_SCHEMA; request["variant_schema"] = SCHEMA
        request["manifest"] = manifest_record
        request["runtime_v10_source_closure"] = package["runtime_v10_source_closure"]
        input_records = {entry.get("path"): entry for entry in request.get("input_records", {}).values()
                         if isinstance(entry, dict) and isinstance(entry.get("path"), str)}
        for record in runtime_records:
            input_records[record["path"]] = record
        input_records[manifest_record["path"]] = manifest_record
        request["input_records"] = {key: input_records[key] for key in sorted(input_records)}
        request["input_files"] = sorted(input_records)
        request["input_sha256"] = {key: input_records[key]["sha256"] for key in sorted(input_records)}
        request["execution_allowed"] = False; request["launch_disabled"] = True
        request["status"] = manifest.get("status", "WAITING_ROOT345_NATIVE_HEADER_AND_INITIAL_SUPPORT")
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        request_record = _record(request_path, f"{item['sentinel_id']} calibration V3 request")
        item.update({"manifest": manifest_record["path"], "request": request_record["path"],
                     "manifest_sha256": manifest_record["sha256"], "request_sha256": request_record["sha256"]})
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result["package_path"] = str(package_path); result["package"] = package
    return result


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="three-sentinel-calibration-parent-v3-") as td:
        root = Path(td)
        rows = [{"sentinel_id": sid, "grid_label": grid, "edge_status": "WAITING_OR_REJECTED",
                 "product_records": {}} for sid in V2.TARGETS for grid in V2.GRIDS]
        handoff = root / "handoff.json"
        V2._write(handoff, {"schema": HANDOFF_V3_SCHEMA,
                            "status": "WAITING_ROOT345_PRODUCER_EDGES_OR_WHOLE_PARENT_SOURCE_CLOSURE",
                            "rows": rows, "scientific_qualification": dict(UNKNOWN)})
        result = build(handoff, root / "out")
        assert result["package"]["schema"] == SCHEMA
        assert result["package"]["status"].startswith("WAITING_")
        assert len(result["package"]["runtime_v10_source_closure"]["files"]) == len(V10_FILES)
    print("PASS_THREE_SENTINEL_CALIBRATION_PARENT_V3_RUNTIME_V10_WAITING_CHAIN")


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
        print(json.dumps({"status": result["package"]["status"], "package": result["package_path"],
                          "scientific_credit": 0}, sort_keys=True))
        return 0
    except (CalibrationV3Failure, V2.CalibrationHandoffFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_CALIBRATION_PARENT_V3: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
