#!/usr/bin/env python3
"""Strict source-bound v12 metadata probe; it never opens HDF5 datasets."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ds_data02_stage2_f2_replay_v12 import (  # noqa: E402
    ReplayV12BindingError,
    manufactured_replay_calibration,
    validate_replay_request,
)


def _expect_rejection(label: str, request: dict) -> dict[str, str]:
    try:
        validate_replay_request(request, verify_sources=True, verify_hdf5_stat=True)
    except ReplayV12BindingError as error:
        return {"status": "PASS", "reason": str(error)}
    raise RuntimeError(f"negative binding case was accepted: {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    bound = validate_replay_request(request, verify_sources=True, verify_hdf5_stat=True)
    calibration = manufactured_replay_calibration()

    wrong_case = copy.deepcopy(request)
    wrong_case["case_identity"]["physical_case_id"] = "F2_WRONG_CASE"
    wrong_denominator = copy.deepcopy(request)
    wrong_denominator["initial_mass_denominator"]["initial_missing_mass_kg"] = 0.003000000142492354
    wrong_denominator["initial_mass_denominator"]["denominator_kg"] = 21.11700100300368
    wrong_sha = copy.deepcopy(request)
    wrong_sha["source_files"][0]["sha256"] = "0" * 64
    wrong_case_name = copy.deepcopy(request)
    original = Path(wrong_case_name["source_files"][0]["path"])
    wrong_case_name["source_files"][0]["path"] = str(original.with_name(original.name.upper()))
    wrong_receiver = copy.deepcopy(request)
    wrong_receiver["receiver_geometry"]["volume_size_m"][0] = 1.11

    # A same-size mutation is checked against the declared content hash in a
    # temporary file.  The source tree itself is never modified.
    source_mutation = copy.deepcopy(request)
    with tempfile.TemporaryDirectory(prefix="ds02-v12-probe-") as directory:
        mutated = Path(directory) / "mutated-source.json"
        source_bytes = Path(source_mutation["source_files"][0]["path"]).read_bytes()
        altered = bytearray(source_bytes)
        altered[0] = altered[0] ^ 1
        mutated.write_bytes(altered)
        source_mutation["source_files"][0]["path"] = str(mutated)
        negative = {
            "wrong_case_identity": _expect_rejection("wrong_case_identity", wrong_case),
            "wrong_initial_denominator": _expect_rejection("wrong_initial_denominator", wrong_denominator),
            "wrong_declared_source_sha": _expect_rejection("wrong_declared_source_sha", wrong_sha),
            "wrong_case_path": _expect_rejection("wrong_case_path", wrong_case_name),
            "wrong_receiver_geometry": _expect_rejection("wrong_receiver_geometry", wrong_receiver),
            "same_size_wrong_content": _expect_rejection("same_size_wrong_content", source_mutation),
        }

    result = {
        "schema": "ds02.stage2.f2-s1-replay-probe-report.v12",
        "status": "PASS",
        "request_id": request.get("request_id"),
        "request_schema": request.get("schema"),
        "request_binding_status": "EXACT_CURRENT_SOURCE_BOUND_PENDING_IO",
        "source_validation": "verify_sources=true; verify_hdf5_stat=true; HDF5 content not opened",
        "verified_source_count": len(bound["_verified_sources"]),
        "verified_source_roles": [item.get("role") for item in bound["_verified_sources"]],
        "hdf5_content_sha256": bound["_verified_hdf5"].get("content_sha256"),
        "trajectory_read": False,
        "negative_binding_checks": negative,
        "manufactured_calibration": calibration,
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
