#!/usr/bin/env python3
"""Prepare one fresh F2 dynamic duration anchor without launching a solver.

This adapter is intentionally independent from the older F2 duration and H2
records.  It reuses the frozen full-cup DBC GenCase recipe as a CPU-only
helper, changes only the prescribed rotation duration to the previously
unexecuted q=.75 anchor, and writes a new hash-bound prepared manifest.  The
adapter never calls the solver, submits a job, or writes a ledger, registry,
or queue entry.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_qualification as f2q
from scripts import f2_full_cup_closed_catchment_dbc as base


SCHEMA = "core.f2.dynamic_third_family_dbc_duration.preflight.v1"
FAMILY = "F2"
SCOPE_ID = "F2_dynamic_third_family_dbc_duration_x_v1"
REVISION_ID = "F2_dynamic_third_family_dbc_duration_q0p75_anchor_v1"
RECIPE_ID = "F2_dynamic_third_family_native_dbc_duration_v1"
CASE_ID = "CORE_F2_DYNAMIC_THIRD_DBC_DURATION_q0p75000000_dp0p007500000000_anchor"
JOB_ID = "f2-dynamic-third-family-dbc-duration-q0p75-anchor-v1-001"
Q = 0.75
DP_M = 0.0075
ROTATION_DURATION_S = 1.025
BASELINE_DURATION_S = 0.85
ANGLE_DEGREES = -105.0
MOTION_START_S = 0.50
TIME_MAX_S = 5.0
OUTPUT_INTERVAL_S = 0.01
PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-q0p75-preflight-v1"
)
LINEAGE_CLARIFICATION_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dynamic-third-family-dbc-duration-lineage-clarification-v1.json"
)
STATIC_SOURCE_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/F2_resting_fill_side_wet_full_cup_canary_v3/prepared.json"
)
STATIC_SOURCE_SHA256 = "2bb1dac4bef30bea2926184641c9d4f3a18895b5b9468ac86b14cbbe28f256c7"
DYNAMIC_Q05_PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2_extension5s_v2/prepared.json"
)
DYNAMIC_Q05_PREPARED_SHA256 = "b63377edf7c3ac3758da06a3e8065feab36fa793cf4ba718c1f8f0b1ef6a067d"
DYNAMIC_Q10_PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_q1p0_v1/prepared.json"
)
DYNAMIC_Q10_PREPARED_SHA256 = "c1200c143b93d0ff4c142d74d6196dc1a4894e61b1194f1501e5bd82f3bd7091"


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _configure_base() -> None:
    """Pin the base CPU recipe to this adapter's independent names."""
    base.SCOPE_ID = SCOPE_ID
    base.REVISION_ID = REVISION_ID
    base.CASE_ID = CASE_ID
    base.JOB_ID = JOB_ID
    base.Q = Q
    base.DP_M = DP_M
    base.ROTATION_DURATION_S = ROTATION_DURATION_S
    base.TIME_MAX_S = TIME_MAX_S
    base.MAXIMUM_EXTENDED_TIME_S = TIME_MAX_S
    base.OUTPUT_INTERVAL_S = OUTPUT_INTERVAL_S


def _rewrite_manifest(lab: Path, output: Path, prepared: dict) -> dict:
    config = prepared["config"]
    definition_audit = config["definition_audit"]
    motion_path = Path(definition_audit["motion_file"])
    definition_path = Path(definition_audit["definition"])
    if not definition_path.is_file() or not motion_path.is_file():
        raise FileNotFoundError("CPU-generated definition or motion file is missing")

    # The base helper writes the correct native geometry and initial arrays.
    # Replace only provenance/parameter labels and the duration-specific
    # hypothesis; no generated geometry or solver control is changed here.
    static_source = (lab / STATIC_SOURCE_RELATIVE).resolve()
    dynamic_q05 = (lab / DYNAMIC_Q05_PREPARED_RELATIVE).resolve()
    dynamic_q10 = (lab / DYNAMIC_Q10_PREPARED_RELATIVE).resolve()
    lineage_clarification = (lab / LINEAGE_CLARIFICATION_RELATIVE).resolve()
    expected_lineage = {
        static_source: STATIC_SOURCE_SHA256,
        dynamic_q05: DYNAMIC_Q05_PREPARED_SHA256,
        dynamic_q10: DYNAMIC_Q10_PREPARED_SHA256,
        lineage_clarification: _sha256(lineage_clarification),
    }
    for path, expected in expected_lineage.items():
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"lineage input changed or is missing: {path}")

    config.update(
        {
            "scope_id": SCOPE_ID,
            "revision_id": REVISION_ID,
            "case_id": CASE_ID,
            "recipe_id": RECIPE_ID,
            "stage": "qualification_anchor_preflight",
            "split": "qualification_only",
            "qualification_only": True,
            "qualified": False,
            "parameter": {
                "name": "rotation_duration_s",
                "q": Q,
                "value": ROTATION_DURATION_S,
                "candidate_range": [0.50, 1.20],
                "held_out": False,
            },
            "dp_m": DP_M,
            "time_max_s": TIME_MAX_S,
            "maximum_extended_time_s": TIME_MAX_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "angle_degrees": ANGLE_DEGREES,
            "motion_start_s": MOTION_START_S,
            "lineage_group_id": SCOPE_ID,
            "physical_case_id": "F2_dynamic_third_family_dbc_duration_v1",
            "control_semantics": (
                "prescribed centered rotation starts at 0.50 s; q=.75 maps to "
                "1.025 s and reaches -105 degrees at 1.525 s; native DBC mvrotfile"
            ),
            "repair_candidate_id": "duration_axis_anchor_q0p75",
            # This flag is relative to the dynamic DBC baseline.  The nested
            # catchment contract remains explicitly changed relative to the
            # static v3 source; see geometry_lineage below.
            "physical_geometry_changed": False,
            "initial_condition_changed": False,
            "mass_rescaling": False,
            "qualification_inheritance": "none; independent dynamic scope",
            "qualification_claim": "none; CPU/native preflight only",
            "observer_revision": "F2_geometry_aware_observer_v1",
            "geometry_comparison_basis": (
                "existing q=.5 and q=1.0 native-DBC full-cup closed-catchment "
                "dynamic baselines; static v3 is source provenance only"
            ),
            "geometry_lineage": {
                "static_source": {
                    "path": str(static_source),
                    "sha256": STATIC_SOURCE_SHA256,
                    "physical_geometry_changed_relative_to_source": True,
                    "change": "fixed mkbound=3 catchment side walls are added over the retained tray footprint",
                },
                "dynamic_baseline": {
                    "paths": [str(dynamic_q05), str(dynamic_q10)],
                    "sha256": [DYNAMIC_Q05_PREPARED_SHA256, DYNAMIC_Q10_PREPARED_SHA256],
                    "physical_geometry_changed_relative_to_dynamic_baseline": False,
                    "shared_geometry": "cup, receiver, tray floor and four catchment side walls are frozen",
                },
            },
            "repair_hypothesis": {
                "id": "duration_axis_anchor_q0p75",
                "mechanism_class": "prescribed_continuous_motion_protocol",
                "single_variable_change": (
                    "relative to the q=.5/q=1.0 native-DBC dynamic baselines, "
                    "rotation_duration_s 0.85/1.20 -> 1.025 at q=.75; all "
                    "boundary, geometry, initial state, horizon and gates fixed"
                ),
                "boundary_unchanged": "native DBC Boundary=1",
                "cfl_unchanged": 0.2,
                "dp_unchanged_m": DP_M,
                "rationale": (
                    "the 5 s DBC canary passed hard identity/geometry integrity; "
                    "q=.75 is a new interior duration anchor between the recorded "
                    "q=.5 and q=1.0 dynamic baselines and is not a same-input retry; "
                    "static v3 remains only the native source"
                ),
                "negative_evidence_preserved": (
                    "q=.5 and q=1.0 right-censored canaries remain separate failed "
                    "development evidence; no settling threshold or horizon is changed"
                ),
            },
        }
    )
    config["source_geometry_contract"]["motion"] = (
        "prescribed centered rotation, y axis through z=0.65, q=.75 duration "
        "1.025 s, same fixed closed-catchment geometry as q=.5/q=1.0 native-DBC "
        "dynamic baselines"
    )
    definition_audit.update(
        {
            "definition_sha256": _sha256(definition_path),
            "motion_sha256": _sha256(motion_path),
            "changed_fields": [
                "case/scope/revision provenance names",
                "rotation duration 0.85 -> 1.025 s and q=.5 -> q=.75",
                "motion target completion 1.35 -> 1.525 s with -105 degree hold through 5 s",
            ],
            "unchanged_fields": [
                "native DBC Boundary=1, CFL=.20, dp=.0075, Dt controls",
                "full-cup/catchment geometry and native initial lattice relative to the dynamic baseline",
                "5 s window, output cadence, observer thresholds and no-rescaling policy",
                "gravity, EOS and viscosity",
            ],
            "qualification_claim": "none",
        }
    )
    config["definition_audit"] = definition_audit
    prepared["config"] = config
    prepared["schema"] = "core.cfd.v1"
    prepared["qualification_only"] = True
    prepared["qualification_claim"] = "none; independent q=.75 dynamic DBC CPU/native preflight only"
    prepared["created_at"] = _stamp()
    prepared["third_family_preflight"] = {
        "schema": SCHEMA,
        "anchor_q": Q,
        "anchor_duration_s": ROTATION_DURATION_S,
        "motion_complete_s": MOTION_START_S + ROTATION_DURATION_S,
        "baseline_duration_s": BASELINE_DURATION_S,
        "geometry_comparison_basis": "q=.5/q=1.0 native-DBC closed-catchment dynamic baselines",
        "geometry_changed_relative_to_static_source": True,
        "geometry_changed_relative_to_dynamic_baseline": False,
        "lineage_clarification": {
            "path": str(lineage_clarification),
            "sha256": _sha256(lineage_clarification),
        },
        "native_geometry_reused_only_after_decode_equality": True,
        "preflight_checks": [
            "GenCase generated exactly the declared runtime domain",
            "fluid count and native IDs are finite and unique",
            "initial fluid velocity is zero",
            "native initial fluid arrays match the passed full-cup source lattice",
            "source mass gate passes with native rho*dp^3 and no rescaling",
            "motion target is reached at 1.525 s and held through 5.0 s",
        ],
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "solver_product_present": False,
    }
    prepared["execution_controls"] = {
        "read_only_scientific_scope": True,
        "cpu_gencase_allowed": True,
        "native_decode_allowed": True,
        "solver_allowed": False,
        "gpu_allowed": False,
        "queue_allowed": False,
        "ledger_allowed": False,
        "registry_allowed": False,
    }
    prepared["execution_status"] = (
        "CPU GenCase/native decode preflight complete; solver not invoked; GPU/queue/"
        "ledger/registry untouched"
    )
    prepared["lineage_clarification"] = {
        "path": str(lineage_clarification),
        "sha256": _sha256(lineage_clarification),
        "static_source": {
            "path": str(static_source),
            "sha256": STATIC_SOURCE_SHA256,
        },
        "dynamic_baselines": [
            {"path": str(dynamic_q05), "sha256": DYNAMIC_Q05_PREPARED_SHA256, "q": 0.5},
            {"path": str(dynamic_q10), "sha256": DYNAMIC_Q10_PREPARED_SHA256, "q": 1.0},
        ],
        "physical_geometry_changed_relative_to_static_source": True,
        "physical_geometry_changed_relative_to_dynamic_baseline": False,
        "single_variable_change_relative_to_dynamic_baseline": "rotation_duration_s",
    }
    # Rebind all generated files after the metadata rewrite.  The prepared
    # manifest is itself intentionally excluded from this input closure.
    prepared["inputs"] = {
        str(path.resolve()): _sha256(path)
        for path in output.rglob("*")
        if path.is_file() and path.name != "prepared.json"
    }
    _write_json(output / "prepared.json", prepared)
    return prepared


def prepare(lab_root: Path, output: Path) -> dict:
    lab_root = Path(lab_root).resolve()
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"preflight output must be fresh: {output}")
    _configure_base()
    prepared = base.prepare_canary(lab_root, output)
    result = _rewrite_manifest(lab_root, output, copy.deepcopy(prepared))
    forbidden = {
        "result.json",
        "trajectory.h5",
        "audit.json",
        "observations.json",
        "worker-status.json",
    }
    found = [str(path.relative_to(output)) for path in output.rglob("*") if path.name in forbidden]
    if found:
        raise RuntimeError(f"preflight unexpectedly created solver products: {found}")
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output", type=Path, default=PREPARED_RELATIVE)
    args = parser.parse_args()
    lab = args.lab_root.resolve()
    output = (lab / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    result = prepare(lab, output)
    print(
        json.dumps(
            {
                "schema": result["third_family_preflight"]["schema"],
                "scope_id": result["config"]["scope_id"],
                "case_id": result["config"]["case_id"],
                "q": result["config"]["parameter"]["q"],
                "rotation_duration_s": result["config"]["parameter"]["value"],
                "preflight_pass": result["preflight_pass"],
                "solver_product_present": result["third_family_preflight"]["solver_product_present"],
                "execution_status": result["execution_status"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
