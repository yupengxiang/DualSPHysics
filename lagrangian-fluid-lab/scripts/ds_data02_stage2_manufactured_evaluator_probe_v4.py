#!/usr/bin/env python3
"""Run the v4 manufactured analytic operator replay and a real F6 XML audit.

The generated bundle contains one deterministic synthetic HDF5 trajectory and
its independently authored expectation JSON.  The optional F6 metadata read is
limited to CURRENT plus one bound generated XML; it does not open scientific
HDF5 data or infer rigid-body mass from particle weights.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_consumers_v4 import (  # noqa: E402
    BindingError,
    evaluate_observation_labels,
    load_current_catalog,
    materialize_labels,
    read_json,
    read_rigid_body_semantics,
)
from ds_data02_stage2_manufactured_fixture_v4 import CASE_ID, build_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-source", type=Path, required=True)
    parser.add_argument("--f6-catalog", type=Path, required=True)
    parser.add_argument("--f6-case-id", required=True)
    args = parser.parse_args()

    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise FileExistsError(f"preserve existing evaluator bundle: {output_root}")
    bundle_paths = build_bundle(output_root / "manufactured", args.expected_source)
    catalog = load_current_catalog(bundle_paths["catalog"], expected_case_count=1)
    config = read_json(bundle_paths["config"])
    label_path = output_root / "manufactured" / "labels.h5"
    materialize_labels(catalog, CASE_ID, label_path, config, particle_chunk=2)
    evaluation = evaluate_observation_labels(label_path, bundle_paths["expected"])
    if evaluation["status"] != "PASS_MANUFACTURED_OPERATOR":
        raise BindingError(f"manufactured operator replay failed: {evaluation['failures']}")

    f6_catalog = load_current_catalog(args.f6_catalog)
    f6_case = f6_catalog.case(args.f6_case_id)
    rigid_body_semantics = read_rigid_body_semantics(f6_case)
    report = {
        "schema": "ds02.stage2.manufactured-single-case-bundle.v1",
        "bundle_root": str(output_root / "manufactured"),
        "evaluation": evaluation,
        "rigid_body_semantics": rigid_body_semantics,
        "model_invoked": False,
        "hidden_test": False,
        "scientific_calibration_status": "UNKNOWN",
        "qualification_status": "UNKNOWN",
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "scope": "manufactured operator replay plus one bound F6 XML metadata audit; no scientific HDF5 read",
    }
    report_path = output_root / "manufactured-evaluator-report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
