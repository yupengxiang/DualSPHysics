#!/usr/bin/env python3
"""Guard-safe v10 request validator and manufactured calibration probe."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ds_data02_stage2_f2_replay_v10 import (  # noqa: E402
    manufactured_replay_calibration,
    validate_replay_request,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    bound = validate_replay_request(request)
    calibration = manufactured_replay_calibration()
    result = {
        "schema": "ds02.stage2.f2-s1-replay-probe-report.v10",
        "status": "PASS",
        "request_id": request.get("request_id"),
        "request_schema": request.get("schema"),
        "request_binding_status": "EXACT_CURRENT_SOURCE_BOUND_PENDING_IO",
        "hdf5_content_sha256": bound["_verified_hdf5"].get("content_sha256"),
        "trajectory_read": False,
        "model_invoked": False,
        "manufactured_calibration": calibration,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
