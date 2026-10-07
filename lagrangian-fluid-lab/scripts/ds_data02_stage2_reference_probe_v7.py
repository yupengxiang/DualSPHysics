#!/usr/bin/env python3
"""Run strict source-bound manual comparison and relocation checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_observer_v6 import observe_scientific_scan  # noqa: E402
from ds_data02_stage2_reference_v7 import (  # noqa: E402
    STRICT_EVALUATION_SCHEMA,
    evaluate_manual_predictions_v7,
    load_frozen_observer_config,
    sha256,
    verify_portable_source,
)


def _bundle(config: dict, config_path: Path, config_hash: str, observations: list[dict]) -> tuple[dict, dict]:
    audit = config["source_audit"]
    bindings = {
        "catalog_sha256": audit["current_catalog_sha256"],
        "case_row_sha256": audit["case_row_sha256"],
        "source_hdf5_sha256": audit["source_hdf5_producer_sha256"],
        "operator_config_sha256": audit["operator_generated_xml_sha256"],
    }
    values = {
        "com_x": {"kind": "position", "reference_scale": 1.0,
                  "values": [row["active_fluid_com_m"][0] for row in observations]},
        "mean_velocity_x": {"kind": "velocity", "reference_scale": 1.0,
                             "values": [row["active_fluid_mean_velocity_m_s"][0] for row in observations]},
        "kinetic_energy": {"kind": "kinetic_energy", "reference_scale": 1.0,
                            "values": [row["active_fluid_kinetic_energy_J"] for row in observations]},
        "active_mass_fraction": {"kind": "mass_fraction", "reference_scale": 1.0,
                                  "values": [row["active_fluid_mass_fraction"] for row in observations]},
    }
    config_binding = {"path": str(config_path.resolve()), "sha256": config_hash}
    common = {
        "config_binding": config_binding,
        "bindings": bindings,
        "query_times_s": list(config["query_times_s"]),
        "budgets": {"time_fraction_used": 0.20, "output_fraction_used": 0.10},
        "events": [{"event_id": "first_passage", "source_region_id": "fluid_to_open_rim",
                    "zone": 0, "idp": 100, "status": "observed", "event_time_s": 0.5,
                    "feature_time_s": config["fixed_physical_scales"]["feature_time_s"],
                    "saved_brackets": [[0.0, 1.0]]}],
    }
    reference = dict(common, schema="ds02.stage2.manual-observation-reference.v1", macros=values)
    prediction_values = {name: list(spec["values"]) for name, spec in values.items()}
    prediction = dict(common, schema="ds02.stage2.manual-observation-predictions.v1", macros=prediction_values,
                      events=[dict(common["events"][0], zone=7, idp=999)])
    return reference, prediction


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    config_hash = sha256(args.config)
    config = load_frozen_observer_config(args.config, config_hash)
    observation = observe_scientific_scan(args.scan, config)
    reference, prediction = _bundle(config, args.config, config_hash, observation["observations"])
    evaluation = evaluate_manual_predictions_v7(reference, prediction, args.config)

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    evaluation_path = output_root / "strict-manual-evaluation-v7.json"
    evaluation_path.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2,
                                           sort_keys=True, allow_nan=False) + "\n")

    source = output_root / "migration-source.json"
    relocated = output_root / "migration-relocated.json"
    source.write_bytes(b'{"migration_fixture":true}\n')
    relocated.write_bytes(source.read_bytes())
    source_stat = source.stat()
    os.utime(relocated, ns=(source_stat.st_atime_ns + 1000, source_stat.st_mtime_ns + 1000))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    migration = {
        "schema": "ds02.stage2.portable-source-migration.v1", "allow_mtime_change": True,
        "source_path": str(source), "relocated_path": str(relocated), "source_sha256": source_hash,
        "relocated_bytes": relocated.stat().st_size, "relocated_mtime_ns": relocated.stat().st_mtime_ns,
        "path_map": {str(source): str(relocated)},
    }
    relocation = verify_portable_source(
        relocated, {"bytes": source_stat.st_size, "mtime_ns": source_stat.st_mtime_ns,
                    "sha256": source_hash}, verify_source_hash=True, migration=migration)
    relocation_path = output_root / "portable-migration-check.json"
    relocation_path.write_text(json.dumps(relocation, ensure_ascii=False, indent=2,
                                           sort_keys=True, allow_nan=False) + "\n")
    report = {
        "schema": "ds02.stage2.reference-probe-report.v1",
        "strict_evaluation_schema": STRICT_EVALUATION_SCHEMA,
        "strict_evaluation_status": evaluation["status"],
        "strict_evaluation_failures": evaluation["failures"],
        "config_sha256": config_hash,
        "scan_sha256": sha256(args.scan),
        "query_times_s": evaluation["query_times_s"],
        "macro_checks": len(evaluation["macro_checks"]),
        "event_checks": len(evaluation["event_checks"]),
        "portable_migration_status": "PASS_MTIME_CHANGE_AFTER_FULL_HASH",
        "portable_migration_used": relocation["migration_used"],
        "trajectory_hdf5_read": False,
        "model_invoked": False,
        "quality": evaluation["quality"],
        "qualification_status": evaluation["qualification_status"],
    }
    (output_root / "reference-probe-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
