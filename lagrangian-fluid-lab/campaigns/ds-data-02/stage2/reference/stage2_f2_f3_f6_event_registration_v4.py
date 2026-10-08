#!/usr/bin/env python3
"""Forward correction for the frozen F2/F3/F6 event registration.

The consumed v3 event artifact already has the finite apertures, crossing
directions, F2 relative/native MK mapping, and F3 top-band threshold.  This
additive sidecar makes the F3 velocity denominator explicit: the registered
value uses the frozen dp=.006 source/cell-centre depth 0.084 m, while the
owner continuous depth 0.09 m remains a separate diagnostic.  It does not
recompute the frozen scale from the owner depth and does not inspect solver
fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.event-registration.v4"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
INPUT = REFERENCE / "stage2_f2_f3_f6_event_registration_v3.json"
OUTPUT = REFERENCE / "stage2_f2_f3_f6_event_registration_v4.json"
F3_GRAVITY_M_PER_S2 = 9.81
F3_SOURCE_CELL_CENTRE_DEPTH_M = 0.084
F3_OWNER_CONTINUOUS_DEPTH_M = 0.09
F3_EXPECTED_SPEED_M_PER_S = math.sqrt(F3_GRAVITY_M_PER_S2 * F3_SOURCE_CELL_CENTRE_DEPTH_M)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def validate_v3(base: dict[str, Any]) -> dict[str, Any]:
    if base.get("schema") != "ds02.stage2.event-registration.v3":
        raise ValueError(f"unexpected input schema: {base.get('schema')!r}")
    mapping = base.get("f2_native_mk_mapping", {}).get("mapping_relative_to_absolute")
    if mapping != {"0": 1, "1": 2, "2": 3}:
        raise ValueError(f"F2 native MK mapping is not the exact frozen mapping: {mapping!r}")
    f2 = base["events"]["F2-S1"][0]
    f2_region = f2["finite_region"]
    if f2.get("direction") != "+x" or f2_region.get("crossing_axis") != "x":
        raise ValueError("F2 crossing direction/axis is not the frozen +x contract")
    for key in ("aperture_y", "aperture_z"):
        bounds = f2_region.get(key)
        if not bounds or not math.isfinite(float(bounds["low_m"])) or not math.isfinite(float(bounds["high_m"])):
            raise ValueError(f"F2 finite aperture missing: {key}")
    f3 = base["events"]["F3-S2"][0]
    f3_region = f3["finite_region"]
    if f3.get("direction") != "+z" or f3_region.get("initial_top_z_m") != F3_OWNER_CONTINUOUS_DEPTH_M:
        raise ValueError("F3 top/direction contract is not the corrected owner contract")
    if f3_region.get("threshold_z_m") != F3_OWNER_CONTINUOUS_DEPTH_M * 1.5:
        raise ValueError("F3 threshold is not top plus half the owner depth")
    for key in ("aperture_x", "aperture_y"):
        bounds = f3_region.get(key)
        if not bounds or not math.isfinite(float(bounds["low_m"])) or not math.isfinite(float(bounds["high_m"])):
            raise ValueError(f"F3 finite aperture missing: {key}")
    f6 = base["events"]["F6-S2"][0]
    if f6.get("direction") != "increasing rotation angle from initial orientation":
        raise ValueError("F6 orientation direction is not explicit")
    if "state_cohort_required" not in f6.get("finite_region", {}):
        raise ValueError("F6 rigid state cohort requirement is missing")
    registered = finite(f3["characteristic_speed_m_per_s"], "frozen F3 speed")
    if abs(registered - F3_EXPECTED_SPEED_M_PER_S) > 1e-15:
        raise ValueError(f"F3 frozen speed changed: {registered!r}")
    return {
        "f2_finite_aperture_and_direction": "PASS_FROZEN_V3_VERIFIED",
        "f2_relative_to_native_mk_mapping": "PASS_0_TO_1_1_TO_2_2_TO_3",
        "f3_finite_aperture_and_direction": "PASS_FROZEN_V3_VERIFIED",
        "f3_initial_top_z_m": F3_OWNER_CONTINUOUS_DEPTH_M,
        "f3_threshold_z_m": F3_OWNER_CONTINUOUS_DEPTH_M * 1.5,
        "f3_velocity_scale": {
            "registered_value_m_per_s": registered,
            "formula": "sqrt(abs(source_gravity_z_m_per_s2) * frozen_source_cell_centre_depth_m)",
            "source_gravity_z_m_per_s2": F3_GRAVITY_M_PER_S2,
            "frozen_source_cell_centre_depth_m": F3_SOURCE_CELL_CENTRE_DEPTH_M,
            "owner_continuous_depth_m_diagnostic_only": F3_OWNER_CONTINUOUS_DEPTH_M,
            "owner_depth_recompute_forbidden": True,
            "owner_depth_recomputed_speed_m_per_s_diagnostic": math.sqrt(F3_GRAVITY_M_PER_S2 * F3_OWNER_CONTINUOUS_DEPTH_M),
            "interpretation": "The frozen observer scale remains sqrt(9.81*0.084)=0.9077664897978995 m/s; owner depth 0.09 m is recorded separately and cannot replace it after seeing results.",
        },
        "f6_rigid_state_cohort_and_direction": "PASS_FROZEN_V3_VERIFIED",
    }


def build() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(f"refuse overwrite immutable artifact: {OUTPUT}")
    base = json.loads(INPUT.read_text(encoding="utf-8"))
    corrections = validate_v3(base)
    result = {
        "schema": SCHEMA,
        "status": "FORWARD_CORRECTION_FROZEN_EVENT_V3_VERIFIED_SCIENTIFIC_QUALIFICATION_UNKNOWN",
        "source_v3": record(INPUT),
        "preservation": {
            "v3_bytes_unchanged": True,
            "field_observations_read": False,
            "bi4_read": False,
            "hdf5_read": False,
            "solver_started": False,
        },
        "corrections": corrections,
        "events": base["events"],
        "f2_native_mk_mapping": base["f2_native_mk_mapping"],
        "frozen_error_budget": base["field_error_budget"],
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "consumer_rule": "Use this sidecar for the F3 scale explanation and retain the v3 event predicates; no field comparison or event credit is implied.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    return result


def self_test() -> dict[str, Any]:
    base = json.loads(INPUT.read_text(encoding="utf-8"))
    corrections = validate_v3(base)
    if corrections["f3_velocity_scale"]["registered_value_m_per_s"] != base["events"]["F3-S2"][0]["characteristic_speed_m_per_s"]:
        raise AssertionError("v4 changed frozen F3 scale")
    return {
        "status": "PASS",
        "f2_aperture_direction_mapping": True,
        "f3_top_threshold_aperture_direction": True,
        "f3_frozen_scale_preserved": True,
        "f6_rigid_cohort_direction": True,
        "field_observations_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.self_test == args.build:
        parser.error("choose exactly one of --self-test or --build")
    print(json.dumps(self_test() if args.self_test else {"status": "WRITTEN", "path": str(OUTPUT), **build()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
