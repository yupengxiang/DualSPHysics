#!/usr/bin/env python3
"""Guard probe for v8 full-axis adapter and strict reference compare."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_observer_v6 import observe_scientific_scan  # noqa: E402
from ds_data02_stage2_reference_probe_v7 import _bundle  # noqa: E402
from ds_data02_stage2_reference_v7 import load_frozen_observer_config, sha256  # noqa: E402
from ds_data02_stage2_reference_v8 import (  # noqa: E402
    adapt_v4_label_event_axis,
    evaluate_manual_predictions_v8,
)


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
    evaluation = evaluate_manual_predictions_v8(reference, prediction, args.config)
    adapter_payload = {
        "schema": "ds02.stage2.observation-labels.v2",
        "first_passage_censor": [[1, 0], [1, 1]],
        "first_passage_interval": [[[0.0, 1.0], [1.0, 2.0]], [[0.0, 1.0], [1.0, 2.0]]],
        "first_passage_chord_time": [[float("nan"), 1.5], [float("nan"), float("nan")]],
        "crossing_count": [[0, 1], [0, 0]],
    }
    adapter = adapt_v4_label_event_axis(adapter_payload, event_index=1,
                                        initial_inside=[False, True],
                                        failed_before_observation=[False, False])
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "strict-manual-evaluation-v8.json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (output_root / "v4-event-axis-adapter-v8.json").write_text(
        json.dumps(adapter, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    report = {
        "schema": "ds02.stage2.reference-probe-report.v2",
        "strict_evaluation_schema": evaluation["schema"],
        "strict_evaluation_status": evaluation["status"],
        "strict_evaluation_failures": evaluation["failures"],
        "v4_event_axis_adapter_schema": adapter["schema"],
        "v4_event_axis_adapter_status": adapter["adapter_status"],
        "query_times_s": evaluation["query_times_s"],
        "scan_sha256": sha256(args.scan),
        "config_sha256": config_hash,
        "trajectory_hdf5_read": False,
        "model_invoked": False,
        "quality": evaluation["quality"],
        "qualification_status": evaluation["qualification_status"],
    }
    (output_root / "reference-probe-report-v8.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

