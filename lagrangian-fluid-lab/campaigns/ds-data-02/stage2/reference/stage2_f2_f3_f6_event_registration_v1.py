#!/usr/bin/env python3
"""Pre-register finite events and source-derived characteristic times.

The v1 observer contracts correctly left event time UNKNOWN because the
source files did not carry event labels.  This forward sidecar supplies
explicit task definitions from the already closed owner geometry and source
scales.  It does not inspect solver results, choose a denominator after the
fact, or infer an event from output/control duration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.event-registration.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
INPUT = REFERENCE / "stage2_f2_f3_f6_owner_scale_closure_v2.json"
OUTPUT = REFERENCE / "stage2_f2_f3_f6_event_registration_v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def finite(value: float, label: str) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive: {value!r}")
    return value


def event(*, event_id: str, cohort: str, region: dict[str, Any], direction: str, condition: str, length: float, speed: float, source: str, observable: str) -> dict[str, Any]:
    length = finite(length, f"{event_id} characteristic length")
    speed = finite(speed, f"{event_id} characteristic speed")
    characteristic = length / speed
    return {
        "event_id": event_id,
        "cohort": cohort,
        "finite_region": region,
        "direction": direction,
        "condition": condition,
        "observable": observable,
        "characteristic_length_m": length,
        "characteristic_speed_m_per_s": speed,
        "characteristic_time_s": characteristic,
        "time_error_tolerance_s": 0.01 * characteristic,
        "scale_source": source,
        "output_or_control_duration_used_as_T": False,
        "actual_event_status": "UNKNOWN_UNTIL_FIELD_OBSERVATION",
        "field_availability_status": "UNKNOWN_UNTIL_TYPED_OBSERVER_SCHEMA_CHECK",
    }


def build() -> dict[str, Any]:
    input_record = record(INPUT)
    closure = json.loads(INPUT.read_text(encoding="utf-8"))
    if closure.get("schema") != "ds02.stage2.owner-scale-closure.v2":
        raise ValueError("event registration requires owner-scale closure v2")
    sentinels = closure["sentinels"]
    f2 = sentinels["F2-S1"]
    f3 = sentinels["F3-S2"]
    f6 = sentinels["F6-S2"]
    f2_gap = 0.56 - f2["continuous_owner"]["extent_m"][0] - f2["continuous_owner"]["low_m"][0]
    if abs(f2_gap - 0.185) > 1e-12:
        raise ValueError(f"unexpected F2 receiver gap: {f2_gap}")
    f2_speed = f2["registered_scales"]["velocity"]["value_m_per_s"]
    f3_depth = f3["continuous_owner"]["extent_m"][2]
    f3_top = f3["continuous_owner"]["low_m"][2] + f3_depth
    f3_threshold = f3_top + 0.5 * f3_depth
    f3_speed = f3["registered_scales"]["velocity"]["value_m_per_s"]
    f6_speed = f6["rigid_body_binding"]["initial_angular_velocity_rad_per_s"]
    f6_omega = math.sqrt(sum(float(value) ** 2 for value in f6_speed))
    events = {
        "F2-S1": [
            event(
                event_id="F2-S1-fluid-crosses-receiver-plane-v1",
                cohort="all initial fluid particles, retaining mkfluid identity 0/1/2",
                region={
                    "source_geometry": "receiver x boundary from owner geometry",
                    "plane_x_m": 0.56,
                    "initial_fluid_max_x_m": 0.375,
                    "gap_m": f2_gap,
                },
                direction="+x",
                condition="first tracked initial-fluid sample with x >= receiver_plane_x_m",
                length=f2_gap,
                speed=f2_speed,
                source="owner receiver_low_m.x - owner fluid_low_m.x - owner fluid_source_size_m.x; frozen F2 registered moving-body velocity scale",
                observable="typed particle position with mkfluid cohort and actual RunPARTs time",
            )
        ],
        "F3-S2": [
            event(
                event_id="F3-S2-fluid-enters-half-depth-top-band-v1",
                cohort="initial owner fluid cohort mkfluid=0",
                region={
                    "source_geometry": "owner initial fluid volume, top band above its initial free-surface level",
                    "initial_top_z_m": f3_top - f3_depth,
                    "threshold_z_m": f3_threshold,
                    "threshold_increment_m": 0.5 * f3_depth,
                    "open_top_face": True,
                },
                direction="+z",
                condition="first tracked initial-fluid sample with z >= threshold_z_m",
                length=0.5 * f3_depth,
                speed=f3_speed,
                source="0.5 * owner continuous fluid depth; frozen F3 gravity transport velocity scale",
                observable="typed particle position with initial-fluid cohort and actual RunPARTs time",
            )
        ],
        "F6-S2": [
            event(
                event_id="F6-S2-rigid-orientation-half-radian-v1",
                cohort="physical floating rigid body defined by massbody, COM and inertia",
                region={
                    "source_geometry": "physical rigid-body state, not floating SPH sample mass",
                    "orientation_angle_threshold_rad": 0.5,
                    "physical_center_m": f6["rigid_body_binding"]["physical_center_m"],
                },
                direction="increasing rotation angle from initial orientation",
                condition="first rigid-body orientation angle with geodesic delta >= 0.5 rad",
                length=0.5,
                speed=f6_omega,
                source="pre-registered orientation threshold divided by physical initial angular-speed scale",
                observable="typed rigid-body orientation/state; if unavailable, retain UNKNOWN",
            )
        ],
    }
    return {
        "schema": SCHEMA,
        "status": "EVENTS_PRE_REGISTERED_ACTUAL_EVENTS_UNKNOWN",
        "purpose": "define finite event regions and characteristic T before any field differences",
        "input_owner_scale_closure": input_record,
        "event_time_policy": {
            "output_duration_is_not_event_T": True,
            "control_table_duration_is_not_event_T": True,
            "event_error_fraction_of_registered_T": 0.01,
            "event_observation_requires_actual_time_bracket": True,
            "event_time_unknown_if_event_not_observed_or_field_unavailable": True,
        },
        "field_error_budget": {
            "position_fraction_of_registered_L": 0.02,
            "velocity_and_ke_fraction_of_registered_nonzero_scale": 0.05,
            "time_and_output_each_max_fraction_of_task_budget": 0.25,
            "all_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "events": events,
        "consumer_gate": {
            "allowed_next_step": "bind actual typed observer fields and RunPARTs brackets to these pre-registered definitions",
            "forbidden": ["choose a different threshold after seeing results", "use output/control duration as T", "treat event occurrence as grid truth"],
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse overwrite of immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def self_test() -> None:
    closure = {"schema": "ds02.stage2.owner-scale-closure.v2", "sentinels": {}}
    assert not closure["sentinels"]
    try:
        finite(0.0, "zero")
    except ValueError:
        pass
    else:
        raise AssertionError("zero characteristic scale accepted")
    print("stage2 F2/F3/F6 event registration v1 self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    atomic_json(args.output, build())
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
