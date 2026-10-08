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


SCHEMA = "ds02.stage2.event-registration.v3"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
INPUT = REFERENCE / "stage2_f2_f3_f6_owner_scale_closure_v2.json"
SOURCE_SUPPORT = REFERENCE / "stage2_f2_f3_f6_source_support_audit_v2.json"
OUTPUT = REFERENCE / "stage2_f2_f3_f6_event_registration_v3.json"
F2_OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/"
    "root_followup_140_f2_actual_native_typed157_home4gib_v1/owners/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010-actual-native-typed157-owner.json"
)
F2_GENERATED_XML = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/"
    "root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-"
    "actual-gencase-source801-root804/prepared/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010.xml"
)


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


def parse_f2_mk_mapping(path: Path) -> dict[str, Any]:
    """Bind relative fluid labels to absolute/native MK labels from XML."""

    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    particles = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "particles"), None)
    if particles is None:
        raise ValueError("F2 generated XML has no particles node")
    mkfluidfirst = particles.get("mkfluidfirst")
    mapping: dict[str, int] = {}
    counts: dict[str, int] = {}
    ranges: list[dict[str, Any]] = []
    for node in particles:
        if node.tag.rsplit("}", 1)[-1] != "fluid" or node.get("mkfluid") is None:
            continue
        relative = node.get("mkfluid")
        absolute = node.get("mk")
        if absolute is None or node.get("begin") is None or node.get("count") is None:
            raise ValueError("F2 fluid block lacks mkfluid/mk/begin/count")
        if relative in mapping and mapping[relative] != int(absolute):
            raise ValueError(f"F2 duplicate relative MK with conflicting absolute MK: {relative}")
        mapping[relative] = int(absolute)
        counts[relative] = int(node.get("count"))
        ranges.append({
            "mkfluid_relative": int(relative),
            "mk_absolute": int(absolute),
            "begin": int(node.get("begin")),
            "count": int(node.get("count")),
        })
    expected = {"0": 1, "1": 2, "2": 3}
    status = "PASS_EXACT_GENERATED_XML_RELATIVE_TO_ABSOLUTE_MK"
    if mapping != expected:
        status = "UNKNOWN_MAPPING_DIFFERS_FROM_EXPECTED_F2_NATIVE_LAYOUT"
    return {
        "source_xml": record(path),
        "mkfluidfirst": int(mkfluidfirst) if mkfluidfirst is not None else None,
        "mapping_relative_to_absolute": mapping,
        "counts_by_mkfluid_relative": counts,
        "ranges": ranges,
        "expected_for_this_source": expected,
        "status": status,
        "typed_observer_contract": "retain both mkfluid_relative and mk_absolute; never rename relative 0 as absolute 0",
    }


def interval(low: float, size: float, label: str) -> dict[str, Any]:
    low = float(low)
    size = finite(size, label + ".size")
    if not math.isfinite(low):
        raise ValueError(f"{label}.low must be finite")
    return {"low_m": low, "high_m": low + size, "size_m": size}


def crossing_qualifies(previous: dict[str, float], current: dict[str, float], *, axis: str, threshold: float, aperture: dict[str, dict[str, Any]]) -> bool:
    """Pure saved-row crossing predicate used by the manufactured tests."""

    if not (math.isfinite(float(previous[axis])) and math.isfinite(float(current[axis]))):
        return False
    if not (float(previous[axis]) < threshold <= float(current[axis])):
        return False
    for coordinate, bounds in aperture.items():
        value = float(current[coordinate])
        if not math.isfinite(value) or value < bounds["low_m"] or value > bounds["high_m"]:
            return False
    return True


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
        "crossing_contract": {
            "requires_previous_saved_sample_on_same_side": True,
            "requires_current_saved_sample_on_direction_side": True,
            "requires_current_sample_inside_finite_region": True,
            "first_observed_time_is_a_RunPARTs_bracket": True,
            "hidden_between_saved_frames": "UNKNOWN",
        },
    }


def build() -> dict[str, Any]:
    input_record = record(INPUT)
    support_record = record(SOURCE_SUPPORT)
    support = json.loads(SOURCE_SUPPORT.read_text(encoding="utf-8"))
    closure = json.loads(INPUT.read_text(encoding="utf-8"))
    if closure.get("schema") != "ds02.stage2.owner-scale-closure.v2":
        raise ValueError("event registration requires owner-scale closure v2")
    sentinels = closure["sentinels"]
    f2 = sentinels["F2-S1"]
    f3 = sentinels["F3-S2"]
    f6 = sentinels["F6-S2"]
    f2_owner_record = record(F2_OWNER)
    f2_owner = json.loads(F2_OWNER.read_text(encoding="utf-8"))
    if f2_owner.get("physical_case_id") != f2["physical_case_id"]:
        raise ValueError("F2 owner physical identity does not match the scale closure")
    receiver_low = f2_owner["geometry"]["receiver_low_m"]
    receiver_size = f2_owner["geometry"]["receiver_size_m"]
    f2_gap = float(receiver_low[0]) - f2["continuous_owner"]["extent_m"][0] - f2["continuous_owner"]["low_m"][0]
    if abs(f2_gap - 0.185) > 1e-12:
        raise ValueError(f"unexpected F2 receiver gap: {f2_gap}")
    f2_mapping = parse_f2_mk_mapping(F2_GENERATED_XML)
    f2_low = [float(value) for value in f2["continuous_owner"]["low_m"]]
    f2_extent = [float(value) for value in f2["continuous_owner"]["extent_m"]]
    f2_source_y = interval(f2_low[1], f2_extent[1], "F2 source y")
    f2_source_z = interval(f2_low[2], f2_extent[2], "F2 source z")
    f2_aperture_y = interval(receiver_low[1], receiver_size[1], "F2 receiver aperture y")
    f2_aperture_z = interval(receiver_low[2], receiver_size[2], "F2 receiver aperture z")
    f2_aperture_overlap = (
        max(f2_source_y["low_m"], f2_aperture_y["low_m"]) < min(f2_source_y["high_m"], f2_aperture_y["high_m"])
        and max(f2_source_z["low_m"], f2_aperture_z["low_m"]) < min(f2_source_z["high_m"], f2_aperture_z["high_m"])
    )
    f2_speed = f2["registered_scales"]["velocity"]["value_m_per_s"]
    f3_depth = f3["continuous_owner"]["extent_m"][2]
    f3_top = f3["continuous_owner"]["low_m"][2] + f3_depth
    f3_threshold = f3_top + 0.5 * f3_depth
    f3_low = [float(value) for value in f3["continuous_owner"]["low_m"]]
    f3_extent = [float(value) for value in f3["continuous_owner"]["extent_m"]]
    f3_aperture_x = interval(f3_low[0], f3_extent[0], "F3 owner x aperture")
    f3_aperture_y = interval(f3_low[1], f3_extent[1], "F3 owner y aperture")
    f3_speed = f3["registered_scales"]["velocity"]["value_m_per_s"]
    f6_speed = f6["rigid_body_binding"]["initial_angular_velocity_rad_per_s"]
    f6_omega = math.sqrt(sum(float(value) ** 2 for value in f6_speed))
    events = {
        "F2-S1": [
            event(
                event_id="F2-S1-fluid-crosses-receiver-aperture-v3",
                cohort="initial fluid cohort mkfluid_relative in {0,1,2}; preserve the exact relative-to-absolute mapping below",
                region={
                    "source_geometry": "receiver plane plus finite y/z aperture from owner geometry",
                    "crossing_axis": "x",
                    "plane_x_m": receiver_low[0],
                    "entry_side": "x increases from below plane to at-or-above plane",
                    "receiver_low_m": receiver_low,
                    "receiver_size_m": receiver_size,
                    "aperture_y": f2_aperture_y,
                    "aperture_z": f2_aperture_z,
                    "initial_source_y": f2_source_y,
                    "initial_source_z": f2_source_z,
                    "initial_source_all_x_below_plane": f2_low[0] + f2_extent[0] < receiver_low[0],
                    "initial_source_aperture_overlap": f2_aperture_overlap,
                    "gap_m": f2_gap,
                    "empty_initial_aperture_overlap_is_not_silent_pass": True,
                    "first_saved_time_bracket": "lower RunPARTs row has prior x<plane; upper row has x>=plane and current y/z inside aperture",
                },
                direction="+x",
                condition=(
                    "first saved transition for one tracked initial-fluid particle with prior x < plane and "
                    "current x >= plane, current y in aperture_y, and current z in aperture_z; "
                    "otherwise UNKNOWN (including particles already on the positive side)"
                ),
                length=f2_gap,
                speed=f2_speed,
                source="owner receiver_low_m.x - owner fluid_low_m.x - owner fluid_source_size_m.x; frozen F2 registered moving-body velocity scale",
                observable="typed particle position, mkfluid_relative, mk_absolute, and actual RunPARTs time bracket",
            )
        ],
        "F3-S2": [
            event(
                event_id="F3-S2-fluid-enters-half-depth-top-band-v3",
                cohort="initial owner fluid cohort mkfluid_relative=0 with native mk_absolute retained separately",
                region={
                    "source_geometry": "owner initial fluid volume with finite x/y aperture and open top",
                    "aperture_x": f3_aperture_x,
                    "aperture_y": f3_aperture_y,
                    "initial_top_z_m": f3_top,
                    "threshold_z_m": f3_threshold,
                    "threshold_increment_m": 0.5 * f3_depth,
                    "open_top_face": True,
                    "first_saved_time_bracket": "lower RunPARTs row has prior z<threshold; upper row has z>=threshold and current x/y inside owner aperture",
                },
                direction="+z",
                condition=(
                    "first saved transition for one tracked initial-fluid particle with prior z < threshold and "
                    "current z >= threshold, current x in aperture_x, and current y in aperture_y; "
                    "same-side particles and out-of-aperture particles are not event positives"
                ),
                length=0.5 * f3_depth,
                speed=f3_speed,
                source="0.5 * owner continuous fluid depth; frozen F3 source/cell-centre transport velocity registration (owner .09 depth is retained as a separate diagnostic)",
                observable="typed particle position, explicit cohort labels, and actual RunPARTs time bracket",
            )
        ],
        "F6-S2": [
            event(
                event_id="F6-S2-rigid-orientation-half-radian-v3",
                cohort="physical floating rigid body defined by massbody, COM and inertia",
                region={
                    "source_geometry": "physical rigid-body state, not floating SPH sample mass",
                    "orientation_angle_threshold_rad": 0.5,
                    "physical_center_m": f6["rigid_body_binding"]["physical_center_m"],
                    "state_cohort_required": "one rigid-body state identity, no substitution of floating particle sample mass",
                    "first_saved_time_bracket": "lower RunPARTs row has prior geodesic delta <0.5; upper row has delta>=0.5",
                },
                direction="increasing rotation angle from initial orientation",
                condition=(
                    "first saved transition for the same rigid-body state with prior geodesic orientation delta < 0.5 rad "
                    "and current delta >= 0.5 rad; if rigid state or initial orientation is unavailable, UNKNOWN"
                ),
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
        "input_owner_files": {"F2-S1": f2_owner_record},
        "input_source_support_audit": support_record,
        "f2_native_mk_mapping": f2_mapping,
        "f2_aperture_diagnostic": {
            "source_support_audit": support.get("sentinels", {}).get("F2-S1", support.get("F2-S1", {})),
            "initial_source_y": f2_source_y,
            "initial_source_z": f2_source_z,
            "receiver_aperture_y": f2_aperture_y,
            "receiver_aperture_z": f2_aperture_z,
            "overlap": f2_aperture_overlap,
            "interpretation": "No initial overlap is retained as a geometry diagnostic; later event positives still require current y/z inside the finite aperture.",
        },
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
        "manufactured_transition_contract_self_test": self_test(),
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


def self_test() -> dict[str, Any]:
    closure = {"schema": "ds02.stage2.owner-scale-closure.v2", "sentinels": {}}
    assert not closure["sentinels"]
    try:
        finite(0.0, "zero")
    except ValueError:
        pass
    else:
        raise AssertionError("zero characteristic scale accepted")
    aperture = {"y": interval(-1.0, 2.0, "test y"), "z": interval(0.0, 1.0, "test z")}
    if not crossing_qualifies(
        {"x": 0.4, "y": 0.0, "z": 0.5},
        {"x": 0.6, "y": 0.0, "z": 0.5},
        axis="x", threshold=0.5, aperture=aperture,
    ):
        raise AssertionError("valid negative-to-positive crossing was rejected")
    if crossing_qualifies(
        {"x": 0.6, "y": 0.0, "z": 0.5},
        {"x": 0.7, "y": 0.0, "z": 0.5},
        axis="x", threshold=0.5, aperture=aperture,
    ):
        raise AssertionError("already-positive sample was accepted as first crossing")
    if crossing_qualifies(
        {"x": 0.4, "y": 2.0, "z": 0.5},
        {"x": 0.6, "y": 2.0, "z": 0.5},
        axis="x", threshold=0.5, aperture=aperture,
    ):
        raise AssertionError("out-of-aperture sample was accepted")
    result = {
        "status": "PASS",
        "zero_scale_rejected": True,
        "negative_to_positive_crossing_accepted": True,
        "already_positive_rejected": True,
        "out_of_aperture_rejected": True,
        "same_side_between_saved_rows": "UNKNOWN",
    }
    print("stage2 F2/F3/F6 event registration v3 self-test: PASS")
    return result


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
