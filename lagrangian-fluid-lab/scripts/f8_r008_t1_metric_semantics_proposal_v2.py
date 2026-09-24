#!/usr/bin/env python3
"""Build a read-only v2 proposal closing Terra High findings for F8 R008 metrics.

This is an additive design revision to proposal v1. It does not implement the
F8 worker or authorize any solver, worker, queue, or qualification activity.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

from scripts import f8_r008_t1_metric_semantics_proposal_v1 as v1

ROOT = v1.ROOT
SCRIPT = Path(__file__).resolve().relative_to(LAB)
TEST = Path("tests/test_f8_r008_t1_metric_semantics_proposal_v2.py")
V1_RECEIPT = ROOT / "t1-metric-semantics-proposal-v1/receipt.json"
V1_SCRIPT = Path("scripts/f8_r008_t1_metric_semantics_proposal_v1.py")
V1_TEST = Path("tests/test_f8_r008_t1_metric_semantics_proposal_v1.py")
NATIVE_SCHEMA = ROOT / "t1-metric-semantics-proposal-v2/native-fluid-table-schema-v1.json"
CORE_CFD = Path("scripts/core_cfd.py")
CORE_CFD_TEST = Path("tests/test_core_cfd.py")
OUTPUT = LAB / ROOT / "t1-metric-semantics-proposal-v2/receipt.json"
SCHEMA = "core.cfd.f8.r008_t1_metric_semantics_proposal.v2"


def _evidence(base: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = list(base)
    known = {item["path"] for item in evidence}
    additions = [
        (V1_RECEIPT, "immutable predecessor proposal reviewed by Terra High; v2 is additive supersession"),
        (V1_SCRIPT, "v1 proposal builder whose frozen semantics are retained"),
        (V1_TEST, "v1 proposal regression tests retained by v2"),
        (NATIVE_SCHEMA, "proposed strict F8 native fluid-frame table schema"),
        (CORE_CFD, "existing generic Core native conversion implementation; bound to distinguish current behavior from proposed strict validation"),
        (CORE_CFD_TEST, "generic Core native conversion regression tests"),
        (SCRIPT, "v2 Terra High finding-closure proposal builder"),
        (TEST, "v2 metric-semantics proposal regression tests"),
    ]
    for path, role in additions:
        item = v1.binding(path, role)
        if item["path"] not in known:
            evidence.append(item)
            known.add(item["path"])
    return evidence


def build_proposal() -> dict[str, Any]:
    # Re-verify the predecessor receipt before carrying forward its frozen design.
    v1.verify_proposal(LAB / V1_RECEIPT)
    value = copy.deepcopy(v1.build_proposal())
    value["schema"] = SCHEMA
    value["record_id"] = "f8-r008-t1-metric-semantics-proposal-v2"
    value["status"] = "awaiting_independent_terra_high_review"
    value["supersedes"] = {
        "record_id": "f8-r008-t1-metric-semantics-proposal-v1",
        "receipt": V1_RECEIPT.as_posix(),
        "change_kind": "additive_closure_of_three_independent_review_findings",
        "scope_or_gate_change": False,
    }
    value["prior_independent_review"] = {
        "reviewer_model": "gpt-5.6-terra",
        "reasoning_effort": "high",
        "verdict": "REVISE",
        "disposition": "three requested operational definitions are added below; no scope, threshold, execution, or qualification boundary changes",
        "findings": [
            {
                "severity": "high",
                "topic": "cross-resolution harmonic coefficients",
                "closure": "define a fixed-frequency fit returning finite mean, sine coefficient a, and cosine coefficient b; interpolate a and b only, then derive amplitude and phase",
            },
            {
                "severity": "high",
                "topic": "native fluid frame identity and values",
                "closure": "bind a fluid-only frame-table schema and require strict exact raw-ID membership, complete finite velocity/position, and finite positive invariant mass before reduction",
            },
            {
                "severity": "medium",
                "topic": "cycle-mean seam partition",
                "closure": "for 3N+1 rows, integrate each cycle over its own inclusive N+1 rows; neighboring cycles share only the seam endpoint",
            },
        ],
        "source_note": "This is a parent-authored disposition summary of the independent review received in the task thread; it is not represented as a reviewer-authored report.",
    }

    value["observation_semantics"]["fixed_frequency_coefficient_fit"] = {
        "model": "u(t) = mean + a*sin(omega*t) + b*cos(omega*t)",
        "design_matrix_columns": ["1", "sin(omega*t)", "cos(omega*t)"],
        "fit_rows": "all exact native rows returned by the frozen inclusive three-cycle selector",
        "frequency_and_time_origin": "use the row's frozen omega_rad_s and absolute native time; no frequency or time-shift fitting",
        "returned_values": ["mean", "sine_coefficient_a_m_s", "cosine_coefficient_b_m_s"],
        "returned_value_validation": "require all three coefficients finite and the least-squares design rank to equal 3",
        "derived_amplitude_m_s": "hypot(a, b)",
        "derived_phase_rad": "atan2(b, a), in [-pi, pi] for the equivalent mean + A*sin(omega*t + phase) representation",
        "compatibility_boundary": "the existing f8_observation_parser_v1.fit_harmonic returns amplitude and phase but not a and b; the F8 T1 metric adapter must expose this coefficient contract without silently changing the existing parser contract",
    }
    value["observation_semantics"]["cycle_partition"] = {
        "samples_per_period": "N = native_output_samples_per_period from the frozen case row",
        "selected_row_count": "exactly 3*N+1 rows, indexed 0 through 3*N inclusive",
        "cycle_row_ranges_inclusive": [
            {"cycle": 0, "first_row": 0, "last_row": "N"},
            {"cycle": 1, "first_row": "N", "last_row": "2*N"},
            {"cycle": 2, "first_row": "2*N", "last_row": "3*N"},
        ],
        "integration": "for each cycle independently, trapezoid-integrate its N+1 instantaneous per-unit-span flux samples over exactly one period and divide by that period",
        "seam_rule": "the shared seam sample is the final endpoint of the preceding cycle and the initial endpoint of the following cycle; it appears once within each adjacent cycle integration and no cycle contains a duplicate row",
        "reduction": "retain the three separate cycle means and report their maximum absolute value; never merge signed cycle means before the maximum",
    }
    value["native_fluid_frame_contract"] = {
        "schema_path": NATIVE_SCHEMA.as_posix(),
        "schema_id": "core.cfd.f8.r008_native_fluid_frame_table.v1",
        "input_boundary": "strictly validate each decoded raw frame before projecting its fluid-only rows into the proposed Core schema_version=3 table",
        "raw_id_set": "the exact expected native ID universe is hash-bound from the generated XML; each decoded frame must contain each expected ID exactly once and no other ID",
        "cohort_partition": "generated XML declarations must uniquely partition registered fluid IDs and registered boundary/nonfluid IDs; only the registered fluid cohort enters the table",
        "initial_reference": "row 0 is exactly t=0; bind the immutable sorted fluid ID axis, initial z coordinate, and positive finite mass by particle_id",
        "selected_frame_gates": [
            "every expected fluid ID occurs exactly once in every selected native frame and maps to the same immutable ID axis",
            "all position and velocity components are finite for every selected fluid row",
            "mass is finite, strictly positive, and invariant by particle_id relative to row 0",
            "all valid entries are true; missing, duplicate, unknown, changed, or unbound IDs fail the case before any metric reduction",
        ],
        "current_implementation_disclaimer": "scripts/core_cfd.py::convert_native currently maps and filters decoded IDs against the fluid axis and rejects duplicate mapped fluid identities, but it does not reject every unknown raw ID; this proposal therefore requires a strict F8 pre-projection validator and does not claim the generic converter already satisfies it",
        "execution_authority": {"solver": False, "gpu": False, "worker": False, "queue": False, "qualification_credit": 0},
    }

    profile_alignment = value["metric_definitions"]["cross_resolution_profile_alignment"]
    profile_alignment["coefficient_fit_contract"] = "use observation_semantics.fixed_frequency_coefficient_fit; retain and spatially interpolate only coefficients a and b, never wrapped phase or amplitude"
    profile_alignment["post_interpolation_derived_values"] = {
        "amplitude": "hypot(interpolated_a, interpolated_b)",
        "phase_rad": "atan2(interpolated_b, interpolated_a)",
    }
    flux = value["metric_definitions"]["cycle_mean_flux"]
    flux["cycle_partition"] = "use observation_semantics.cycle_partition; for N samples per period the selected rows are 0..3N and the three inclusive cycle slices are 0..N, N..2N, and 2N..3N"

    value["review_request"] = {
        "requested_model": "gpt-5.6-terra",
        "requested_reasoning_effort": "high",
        "questions": [
            "Does the coefficient-returning fixed-frequency fit define the sine/cosine convention consistently with amplitude, phase, and all eight cross-resolution comparisons?",
            "Does the bound fluid-only table plus exact pre-projection raw-ID audit define a fail-closed native input contract without overclaiming current converter behavior?",
            "Does the 3N+1 row partition integrate exactly three adjacent full periods with only shared seam endpoints and no duplicate within-cycle samples?",
            "Does v2 preserve every v1 scope row, native window, threshold, denominator, failure policy, and zero-authority boundary?",
            "Identify any remaining formula, sign, unit, edge-case, or provenance defect that should block adoption.",
        ],
    }
    value["evidence"] = _evidence(value["evidence"])
    return value


def verify_proposal(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value != build_proposal():
        raise ValueError("R008 v2 metric-semantics proposal no longer matches frozen evidence")
    return value


def write_proposal(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 v2 metric-semantics proposal: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(build_proposal(), indent=2, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable review proposal once")
    args = parser.parse_args()
    if args.write:
        print(write_proposal().relative_to(LAB))
    else:
        print(json.dumps(build_proposal(), indent=2, sort_keys=True))
