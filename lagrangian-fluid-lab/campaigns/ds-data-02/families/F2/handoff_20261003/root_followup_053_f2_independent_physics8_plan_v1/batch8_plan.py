"""Define the F2 stage1 independent-physics batch of eight cases.

This module creates a reviewable plan and request skeleton only.  It does not
write XML, copy motion files, read H5/BI4/CSV arrays, run GenCase, run a
solver, or allocate a production case.  Root must approve the geometry
preflight and bind exact source bytes before any materialization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.f2.stage1.independent-physics8-plan.v1"
FAMILY_ID = "F2"
EVENT_WINDOW_S = 4.0
SAVE_INTERVAL_S = 0.01
DP_M = 0.01
SOLVER_DIMENSION = 3
XML_DATA2D = False

ROOT = Path(__file__).resolve().parents[6]
FAMILY_ROOT = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2"

SOURCE_TEMPLATES: dict[str, dict[str, str]] = {
    "center_catch": {
        "definition": "campaigns/ds-data-02/families/F2/definitions/F2_REF_CENTER_NOMINAL_MEDIUM_Def.xml",
        "definition_sha256": "fe8fe641461402170f6dc112fef0d960138a39cbfc0ab1354aba47f3b42a594a",
        "motion": "campaigns/ds-data-02/families/F2/definitions/F2_REF_CENTER_NOMINAL_MEDIUM_motion.dat",
        "motion_sha256": "547a941301b2a3d2fcce8633e4ff43b86fe08c4633c41e8fa9a0e85567f45c4b",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_CENTER_V1",
    },
    "offset_spill": {
        "definition": "campaigns/ds-data-02/families/F2/definitions/F2_REF_OFFSET_NOMINAL_MEDIUM_Def.xml",
        "definition_sha256": "2ec50a458648fe63dc1b0c706ded645af2a589e5d8e21613dfb5ba369f749a1a",
        "motion": "campaigns/ds-data-02/families/F2/definitions/F2_REF_OFFSET_NOMINAL_MEDIUM_motion.dat",
        "motion_sha256": "547a941301b2a3d2fcce8633e4ff43b86fe08c4633c41e8fa9a0e85567f45c4b",
        "geometry_family_id": "F2_GEOM_CUP_RECEIVER_OFFSET_V1",
    },
}

ALLOWED_MOTHERS = tuple(SOURCE_TEMPLATES)
ALLOWED_TILT_DEG = (-4.0, 0.0, 4.0)
ALLOWED_ROTATION_DURATION_S = (0.65, 1.2)
ALLOWED_FILL_RATIO = (0.8, 1.0)
ALLOWED_MOUTH_GEOMETRY = ("open_rim", "short_spout")
ALLOWED_RECEIVER_X_M = (0.45, 0.65)
ALLOWED_RECEIVER_Y_M = (0.0, 0.14, 0.22)

# These are physical tuples, not three-resolution views.  The initial tilt is
# a bounded candidate parameter and must be checked for non-overlap before a
# definition is materialized.  The existing smooth +Y rotation driver and
# endpoint -105 degrees remain the source control semantics.
CASE_TUPLES: tuple[dict[str, Any], ...] = (
    {
        "case_index": 1, "mother": "center_catch", "tilt_deg": 0.0,
        "rotation_duration_s": 1.2, "fill_ratio": 1.0, "mouth_geometry": "open_rim",
        "receiver_x_m": 0.45, "receiver_y_m": 0.0,
    },
    {
        "case_index": 2, "mother": "offset_spill", "tilt_deg": 0.0,
        "rotation_duration_s": 1.2, "fill_ratio": 1.0, "mouth_geometry": "open_rim",
        "receiver_x_m": 0.45, "receiver_y_m": 0.22,
    },
    {
        "case_index": 3, "mother": "center_catch", "tilt_deg": -4.0,
        "rotation_duration_s": 0.65, "fill_ratio": 0.8, "mouth_geometry": "open_rim",
        "receiver_x_m": 0.65, "receiver_y_m": 0.0,
    },
    {
        "case_index": 4, "mother": "offset_spill", "tilt_deg": 4.0,
        "rotation_duration_s": 0.65, "fill_ratio": 0.8, "mouth_geometry": "open_rim",
        "receiver_x_m": 0.65, "receiver_y_m": 0.14,
    },
    {
        "case_index": 5, "mother": "center_catch", "tilt_deg": 4.0,
        "rotation_duration_s": 0.65, "fill_ratio": 1.0, "mouth_geometry": "short_spout",
        "receiver_x_m": 0.45, "receiver_y_m": 0.0,
    },
    {
        "case_index": 6, "mother": "offset_spill", "tilt_deg": -4.0,
        "rotation_duration_s": 0.65, "fill_ratio": 1.0, "mouth_geometry": "short_spout",
        "receiver_x_m": 0.45, "receiver_y_m": 0.22,
    },
    {
        "case_index": 7, "mother": "center_catch", "tilt_deg": -4.0,
        "rotation_duration_s": 1.2, "fill_ratio": 0.8, "mouth_geometry": "short_spout",
        "receiver_x_m": 0.65, "receiver_y_m": 0.0,
    },
    {
        "case_index": 8, "mother": "offset_spill", "tilt_deg": 4.0,
        "rotation_duration_s": 1.2, "fill_ratio": 0.8, "mouth_geometry": "short_spout",
        "receiver_x_m": 0.65, "receiver_y_m": 0.14,
    },
)


def _physical_key(case: Mapping[str, Any]) -> str:
    values = {
        key: case[key]
        for key in (
            "mother", "tilt_deg", "rotation_duration_s", "fill_ratio",
            "mouth_geometry", "receiver_x_m", "receiver_y_m",
        )
    }
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_choice(name: str, value: Any, allowed: Sequence[Any]) -> None:
    if value not in allowed:
        raise ValueError(f"{name}={value!r} is outside the frozen F2 stage1 plan allowlist {tuple(allowed)!r}")


def validate_case_tuple(case: Mapping[str, Any]) -> None:
    _check_choice("mother", case["mother"], ALLOWED_MOTHERS)
    _check_choice("tilt_deg", float(case["tilt_deg"]), ALLOWED_TILT_DEG)
    _check_choice("rotation_duration_s", float(case["rotation_duration_s"]), ALLOWED_ROTATION_DURATION_S)
    _check_choice("fill_ratio", float(case["fill_ratio"]), ALLOWED_FILL_RATIO)
    _check_choice("mouth_geometry", case["mouth_geometry"], ALLOWED_MOUTH_GEOMETRY)
    _check_choice("receiver_x_m", float(case["receiver_x_m"]), ALLOWED_RECEIVER_X_M)
    _check_choice("receiver_y_m", float(case["receiver_y_m"]), ALLOWED_RECEIVER_Y_M)


def build_plan() -> dict[str, Any]:
    if len(CASE_TUPLES) != 8:
        raise ValueError("stage1 batch8 must contain exactly eight physical tuples")
    rows: list[dict[str, Any]] = []
    physical_keys: set[str] = set()
    for case in CASE_TUPLES:
        validate_case_tuple(case)
        index = int(case["case_index"])
        case_id = f"F2_STAGE1_B08_C{index:02d}"
        physical_key = _physical_key(case)
        if physical_key in physical_keys:
            raise ValueError(f"duplicate physical tuple at {case_id}")
        physical_keys.add(physical_key)
        source = SOURCE_TEMPLATES[case["mother"]]
        rows.append({
            "case_id": case_id,
            "physical_case_id": case_id,
            "independent_case_count_increment": 1,
            "status": "planned_not_materialized",
            "physical_condition_sha256": physical_key,
            "mother": {
                "mechanism_id": case["mother"],
                "definition_template": source["definition"],
                "definition_template_sha256": source["definition_sha256"],
                "motion_template": source["motion"],
                "motion_template_sha256": source["motion_sha256"],
                "geometry_family_id": source["geometry_family_id"],
                "control_family_id": "F2_CTRL_SMOOTH_ROTATE_Y_V1",
            },
            "geometry_and_endpoints": {
                "mouth_geometry": case["mouth_geometry"],
                "receiver_x_m": float(case["receiver_x_m"]),
                "receiver_y_m": float(case["receiver_y_m"]),
                "interior_regions": ["cup_interior", "receiver_interior", "spill_tray_interior", "inflight", "unknown"],
                "finite_boundary_policy": "preserve cup, receiver and tray finite walls; world top remains the only open face",
            },
            "physics_tuple": {
                "initial_cup_tilt_deg": float(case["tilt_deg"]),
                "tilt_axis": "world_x_candidate_requires_geometry_preflight",
                "rotation_duration_s": float(case["rotation_duration_s"]),
                "rotation_endpoint_deg": -105.0,
                "native_rotation_axis_endpoints": {
                    "axis_p1": [0.0, -1.0, 0.65],
                    "axis_p2": [0.0, 1.0, 0.65],
                },
                "fluid_fill_ratio": float(case["fill_ratio"]),
                "gravity_m_s2": [0.0, 0.0, -9.81],
            },
            "single_resolution_policy": {
                "dp_m": DP_M,
                "resolution_views_per_physical_case": 1,
                "three_dimensional": True,
                "solver_dimension": SOLVER_DIMENSION,
                "xml_data2d": XML_DATA2D,
                "event_window_s": EVENT_WINDOW_S,
                "save_interval_s": SAVE_INTERVAL_S,
            },
            "provenance_policy": {
                "unknown_excluded_uid_retained": True,
                "excluded_uid_count_source": "actual native receipt after root launch",
                "physical_spill_inference": False,
                "native_mass_rescaling": False,
                "source_mutation_allowed": False,
                "materialize_only_after_root_visual_scope_review": True,
                "numerical_precision_status": "not accepted",
            },
        })
    return {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "scope_id": "root_followup_053_f2_independent_physics8_plan_v1",
        "status": "planned_not_materialized",
        "launch_allowed": False,
        "root_only": True,
        "physical_case_count": len(rows),
        "resolution_counting_rule": "one true3D dp010 view per physical tuple; no coarse/medium/fine aliases and no repeated windows count",
        "allowlist": {
            "initial_cup_tilt_deg": list(ALLOWED_TILT_DEG),
            "rotation_duration_s": list(ALLOWED_ROTATION_DURATION_S),
            "fluid_fill_ratio": list(ALLOWED_FILL_RATIO),
            "mouth_geometry": list(ALLOWED_MOUTH_GEOMETRY),
            "receiver_x_m": list(ALLOWED_RECEIVER_X_M),
            "receiver_y_m": list(ALLOWED_RECEIVER_Y_M),
        },
        "common_physical_contract": {
            "event_window_s": EVENT_WINDOW_S,
            "save_interval_s": SAVE_INTERVAL_S,
            "dp_m": DP_M,
            "solver_dimension": SOLVER_DIMENSION,
            "xml_data2d": XML_DATA2D,
            "full_native_fields_required": ["valid", "particle_id", "particle_zone", "initial_mk", "mass", "velocity", "density", "pressure", "type"],
            "visual_acceptance": "root reviews every full temporal animation; visual pass and numerical precision remain separate",
        },
        "source_bindings": {
            "family_card": "campaigns/ds-data-02/families/F2/family_card.json",
            "split_range_design": "campaigns/ds-data-02/families/F2/split_range_design.json",
            "event_definitions": "campaigns/ds-data-02/families/F2/event_definitions.json",
        },
        "cases": rows,
        "unknowns_and_gates": [
            "tilt candidate must pass source geometry non-overlap and finite-boundary preflight before materialization",
            "actual native excluded UID/loss remains unknown until a root-authorized fulltyped trajectory exists",
            "no H5/CSV/BI4/solver reads or numerical generation are performed by this plan",
            "a visual renderer output never grants Q-N or production approval",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new plan JSON path")
    args = parser.parse_args(argv)
    plan = build_plan()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schema": SCHEMA, "physical_case_count": len(plan["cases"]), "status": plan["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
