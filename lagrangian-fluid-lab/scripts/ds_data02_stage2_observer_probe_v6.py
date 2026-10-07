#!/usr/bin/env python3
"""Run the source-bound v6 observer without opening scientific HDF5."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_observer_v6 import (  # noqa: E402
    CALIBRATION_SCHEMA,
    OBSERVER_RESULT_SCHEMA,
    manufactured_observer_calibration,
    observe_scientific_scan,
    sha256,
    validate_observer_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    validated = validate_observer_config(config)
    calibration = manufactured_observer_calibration(validated)
    observation = observe_scientific_scan(args.scan, validated)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    calibration_path = output_root / "manufactured-observer-calibration.json"
    observation_path = output_root / "f2-s1-observer-observation.json"
    calibration_path.write_text(json.dumps(calibration, ensure_ascii=False, indent=2,
                                            sort_keys=True, allow_nan=False) + "\n")
    observation_path.write_text(json.dumps(observation, ensure_ascii=False, indent=2,
                                           sort_keys=True, allow_nan=False) + "\n")
    report = {
        "schema": "ds02.stage2.reference-observer-probe-report.v1",
        "config_path": str(args.config.resolve()),
        "config_sha256": sha256(args.config),
        "scan_path": str(args.scan.resolve()),
        "scan_sha256": sha256(args.scan),
        "calibration_schema": CALIBRATION_SCHEMA,
        "calibration_status": calibration["status"],
        "observation_schema": OBSERVER_RESULT_SCHEMA,
        "observation_path": str(observation_path),
        "query_times_s": [row["time_s"] for row in observation["observations"]],
        "observation_count": len(observation["observations"]),
        "missing_mass_bucket_status": observation["observations"][-1]["missing_mass_bucket"],
        "mass_quantile_front_status": observation["mass_quantile_front"]["status"],
        "mass_distribution_status": observation["fixed_scale_mass_distribution"]["status"],
        "trajectory_hdf5_read": False,
        "model_invoked": False,
        "quality": observation["quality"],
        "qualification_status": observation["qualification_status"],
    }
    report_path = output_root / "reference-observer-probe-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                      sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

