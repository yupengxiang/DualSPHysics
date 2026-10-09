#!/usr/bin/env python3
"""Small source-contract helpers for the F5-S1 Y-zero forward audit.

This file deliberately contains no payload reader.  It validates only the
terminal GenCase envelope and the static Def phase relationship.  The V8
geometry parser remains the implementation used for Fluid/Bound payloads;
the forward worker patches its old Y-half identity check with this narrower
Y-zero contract so consumed V8 bytes remain untouched.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_SAMPLE_MASS_KG = 254.4779834119572
EXPECTED = {"dp005": {"dp_m": 0.005, "pointref_m": (0.0125, 0.0, 0.0125)}}


def close(a: Any, b: Any, tol: float = 1e-12) -> bool:
    return abs(float(a) - float(b)) <= tol


def _normalise(data: bytes) -> bytes:
    data, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+(")', rb"\1<DP>\2", data, count=1)
    if count != 1:
        raise ValueError("Def must contain exactly one definition@dp")
    data, count = re.subn(rb'<pointref\s+x="[^"]+"\s+y="[^"]+"\s+z="[^"]+"\s*/>', b'<pointref x="<X>" y="<Y>" z="<Z>" />', data, count=1)
    if count != 1:
        raise ValueError("Def must contain exactly one pointref")
    return data


def _facts(data: bytes) -> tuple[float, tuple[float, float, float]]:
    dp = re.search(rb'<definition\b[^>]*\bdp="([^"]+)"', data)
    point = re.search(rb'<pointref\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"\s*/>', data)
    if not dp or not point:
        raise ValueError("cannot parse Def dp/pointref")
    return float(dp.group(1)), tuple(float(point.group(i)) for i in range(1, 4))


def validate_gencase_request(request: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate a Y-zero q/receipt without accepting the old Y-half rung."""
    if request.get("schema") != "ds02.request.v1":
        raise ValueError("GenCase request must use ds02.request.v1")
    if request.get("family_id") != "F5" or request.get("sentinel_id") != "F5-S1":
        raise ValueError("F5-S1 identity mismatch")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("F5 physical case identity mismatch")
    if request.get("cpu_task_kind") != "gencase" or request.get("gencase_launch") is not True:
        raise ValueError("support request is not a GenCase request")
    if request.get("solver_launch") is not False or request.get("hdf5_read") is not False or request.get("bi4_read") is not False:
        raise ValueError("GenCase request permits a forbidden solver/native read")
    binding = request.get("source_binding")
    if not isinstance(binding, dict) or binding.get("grid") not in EXPECTED:
        raise ValueError("Y-zero source binding/grid is missing")
    expected = EXPECTED[binding["grid"]]
    if not close(binding.get("dp_m", -1.0), expected["dp_m"]):
        raise ValueError("Y-zero dp does not match dp005")
    point = tuple(float(value) for value in binding.get("pointref_m", ()))
    if point != expected["pointref_m"]:
        raise ValueError(f"Y-zero pointref mismatch: {point!r}")
    if not close(binding.get("continuous_region_mass_kg", -1.0), CONTINUOUS_MASS_KG, 1e-9):
        raise ValueError("continuous-owner mass changed")
    if not close(binding.get("old_sample_mass_kg", OLD_SAMPLE_MASS_KG), OLD_SAMPLE_MASS_KG, 1e-12):
        raise ValueError("diagnostic old sample mass changed")
    for key in ("continuous_box_and_clip_unchanged", "controls_and_motion_unchanged"):
        if binding.get(key) is not True:
            raise ValueError(f"source binding does not preserve {key}")
    if binding.get("mass_rescale") is not False:
        raise ValueError("mass rescaling is forbidden")
    planned = Path(str(request.get("output_root", ""))).expanduser().resolve()
    actual = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not str(request.get("output_root", "")).strip() or not str(receipt.get("output_root", "")).strip():
        raise ValueError("request/receipt output roots are required")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("GenCase receipt is not completed zero-return")
    return {
        "grid": binding["grid"], "expected_dp_m": expected["dp_m"], "expected_pointref_m": list(expected["pointref_m"]),
        "continuous_region_mass_kg": CONTINUOUS_MASS_KG, "old_discrete_sample_mass_kg": OLD_SAMPLE_MASS_KG,
        "planned_output_root": str(planned), "actual_receipt_output_root": str(actual),
        "planned_root_matches_receipt": planned == actual, "materialized_output_root_override": planned != actual,
    }


def validate_def_phase(candidate_def: Path, source_def: Path, *, expected_pointref: tuple[float, float, float]) -> dict[str, Any]:
    candidate = candidate_def.expanduser().resolve().read_bytes()
    source = source_def.expanduser().resolve().read_bytes()
    candidate_dp, candidate_point = _facts(candidate)
    if not close(candidate_dp, EXPECTED["dp005"]["dp_m"]):
        raise ValueError("candidate Def dp is not .005")
    if candidate_point != expected_pointref:
        raise ValueError(f"candidate Def pointref differs from Y-zero contract: {candidate_point!r}")
    if _normalise(candidate) != _normalise(source):
        raise ValueError("candidate Def changes source semantics beyond dp/pointref")
    return {
        "candidate_dp_m": candidate_dp, "candidate_pointref_m": list(candidate_point),
        "normalized_candidate_source_equal": True,
        "normalized_sha256": hashlib.sha256(_normalise(candidate)).hexdigest(),
        "global_lattice_phase_change": True,
        "all_shapes_scope": ["fluid", "boundary", "forcing", "shape_operations"],
    }


def self_test() -> dict[str, Any]:
    good = {
        "schema": "ds02.request.v1", "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "cpu_task_kind": "gencase", "gencase_launch": True, "solver_launch": False, "hdf5_read": False, "bi4_read": False,
        "output_root": "/tmp/yzero", "source_binding": {"grid": "dp005", "dp_m": .005, "pointref_m": [.0125, 0., .0125], "continuous_region_mass_kg": CONTINUOUS_MASS_KG, "old_sample_mass_kg": OLD_SAMPLE_MASS_KG, "continuous_box_and_clip_unchanged": True, "controls_and_motion_unchanged": True, "mass_rescale": False},
    }
    receipt = {"status": "completed", "returncode": 0, "output_root": "/tmp/yzero"}
    assert validate_gencase_request(good, receipt)["expected_pointref_m"] == [.0125, 0., .0125]
    bad = {**good, "source_binding": {**good["source_binding"], "pointref_m": [.0125, .0025, .0125]}}
    try:
        validate_gencase_request(bad, receipt)
    except ValueError:
        pass
    else:
        raise AssertionError("Y-half pointref was accepted by Y-zero contract")
    return {"status": "PASS", "schema": "ds02.stage2.f5-s1.clipplane-yzero-contract.v1", "wrong_yhalf_rejected": True, "payload_read": False}


if __name__ == "__main__":
    import json
    print(json.dumps(self_test(), indent=2))
