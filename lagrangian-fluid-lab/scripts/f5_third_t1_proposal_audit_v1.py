#!/usr/bin/env python3
"""Build a read-only, proposal-only audit for an F5 third-T1 candidate.

This entry point reads the already materialized R3 WaveRunup reports and the
immutable official WaveRunup inputs.  It computes hashes and records a small
root-review contract; it never calls GenCase, the solver, a decoder, a queue,
or a GPU worker.  The generated JSON is a design/provenance artifact and has
zero qualification, matrix, registry, or ledger credit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OFFICIAL_WAVE = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/17_WaveRunup"
R3_RUN_REPORT = LAB / "campaigns/v0.1-candidate/r3-f5-wave-runup.json"
R3_ALIGNMENT_REPORT = LAB / "campaigns/v0.1-candidate/r3-f5-reference-alignment.json"
DEFAULT_OUTPUT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1-proposal-audit-v1.json"


SOURCE_FILES: tuple[tuple[str, str], ...] = (
    ("CaseWaveRunup_Def.xml", "official WaveRunup case definition"),
    ("Mov_piston.dat", "official piston time/displacement source"),
    ("Slope.stl", "official run-up slope geometry"),
    ("Blocks_3D_scaled.stl", "official slope/block geometry"),
    ("wg1234.txt", "official external gauge locations"),
    ("EXP_CaseWaveRunup_CIEMito.txt", "official CIEMito reference table"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact(path: Path, role: str, *, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise FileNotFoundError(path)
        return {"path": str(path.relative_to(LAB)), "present": False, "role": role}
    return {
        "path": str(path.relative_to(LAB)),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected an object in {path}")
    return value


def summarize_r3(run_report: dict[str, Any], alignment: dict[str, Any]) -> dict[str, Any]:
    if run_report.get("status") != "candidate_only":
        raise ValueError("R3 WaveRunup report is not candidate_only")
    if run_report.get("formal_release_authorized") is not False:
        raise ValueError("R3 WaveRunup report must not authorize formal release")
    runs: list[dict[str, Any]] = []
    for run in run_report.get("runs", []):
        if not isinstance(run, dict):
            continue
        gauges = run.get("external_gauge_summary", {}).get("gauges", {})
        runs.append(
            {
                "label": run.get("label"),
                "dp_m": run.get("dp_m"),
                "status": run.get("status"),
                "frames": run.get("frames"),
                "excluded_particles": run.get("excluded_particles"),
                "time_end_s": max(
                    (item.get("time_end_s") for item in gauges.values() if isinstance(item, dict)),
                    default=None,
                ),
                "external_gauge_count": len(gauges),
            }
        )
    alignment_rows: list[dict[str, Any]] = []
    for run in alignment.get("runs", []):
        if not isinstance(run, dict):
            continue
        alignment_rows.append(
            {
                "label": run.get("label"),
                "dp_m": run.get("dp_m"),
                "fixed_zero_offset_mean_rmse_m": run.get("fixed_zero_offset", {}).get("mean_rmse_m"),
                "local_shift_best_mean_rmse_m": run.get("local_shift_diagnostic", {}).get("best_mean_rmse_m"),
                "local_shift_best_offset_s": run.get("local_shift_diagnostic", {}).get("best_offset_s"),
            }
        )
    return {
        "source_scope": run_report.get("scope"),
        "execution_status": run_report.get("status"),
        "formal_release_authorized": run_report.get("formal_release_authorized"),
        "runs": runs,
        "alignment_status": alignment.get("status"),
        "alignment_rows": alignment_rows,
        "interpretation": (
            "Engineering and external-observation evidence only.  These runs "
            "are not imported into the Core T1 denominator."
        ),
    }


def build_proposal() -> dict[str, Any]:
    run_report = load_json(R3_RUN_REPORT)
    alignment_report = load_json(R3_ALIGNMENT_REPORT)

    sources = [artifact(OFFICIAL_WAVE / name, role) for name, role in SOURCE_FILES]
    evidence = [
        artifact(R3_RUN_REPORT, "R3 WaveRunup candidate-only execution report"),
        artifact(R3_ALIGNMENT_REPORT, "R3 WaveRunup candidate-only gauge alignment report"),
        artifact(LAB / "reports/findings.md", "exploration resolution failure/repair finding"),
        artifact(LAB / "scripts/r3_f5_wave_runup.py", "existing observation-path implementation"),
        artifact(LAB / "scripts/r3_f5_reference_alignment.py", "existing external-alignment implementation"),
    ]
    return {
        "schema": "core.f5.third_t1.proposal_audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "proposal_only_root_review_required",
        "qualification_claim": "none",
        "candidate": {
            "family": "F5",
            "scope_id": "F5_prescribed_wave_runup_x_v1",
            "revision_id": "F5_piston_amplitude_runup_v1",
            "candidate_id": "F5_wave_runup_piston_scale_anchor",
            "mechanism_class": "prescribed_piston_wave_runup_return",
            "hypothesis": (
                "A prescribed piston wave crossing a fixed slope and block field "
                "creates a reproducible incident-wave, run-up, and return-flow "
                "response whose amplitude dependence can be evaluated with SWL "
                "gauges and run-up lines."
            ),
            "scientific_difference": [
                "The source is a time-dependent moving piston and a sloped run-up surface, not a gravity-release dam break.",
                "The response is wave propagation, slope run-up and return flow, not pouring into a receiver or underflow through an aperture.",
                "The registered control is piston displacement amplitude at fixed time history and fixed slope/block geometry.",
                "The external contract has four fixed Eulerian wave gauges plus run-up-line observations and an independent CIEMito table.",
            ],
            "disallowed_shortcuts": [
                "no F1 obstacle, dam-break, or suspended-gap geometry/input reuse",
                "no F2 cup, reservoir, receiver, weir, or submerged-orifice input reuse",
                "no reuse of R3 generated XML, BI4, HDF5, or trajectory as Core qualification data",
                "no fitted time shift, external-reference label leakage, threshold relaxation, or survivor renormalization",
                "no solver, GPU, queue, ledger, registry, or matrix submission from this proposal",
            ],
        },
        "core_gate": {
            "current_registered_t1_families": ["F3", "F4"],
            "required_t1_family_count": 3,
            "candidate_family": "F5",
            "candidate_can_satisfy_third_family_conditionally": True,
            "qualification_credit_added": 0,
            "core_gate_changed": False,
        },
        "evidence": {
            "official_inputs": sources,
            "existing_candidate_only": evidence,
            "r3_summary": summarize_r3(run_report, alignment_report),
            "observed_support": [
                "Three fresh R3 resolution probes at dp=0.030/0.025/0.020 m completed about 16 s with 801 frames.",
                "R3 excluded-particle counts were 1, 1, and 0 respectively; the old 0.040 m stress case is excluded from the ladder.",
                "R3 emitted four external SWL gauge series at 0.02 s cadence and aligned them to the official CIEMito table as a diagnostic.",
                "The refined external-gauge diagnostic decreased fixed-zero-offset mean RMSE from 15.52 mm at 0.030 m to 8.87 mm at 0.020 m.",
            ],
            "limitations": [
                "The R3 reports are candidate-only and carry no Core T1 credit.",
                "The official table is Eulerian gauge/reference data, not particle-corresponded truth.",
                "A fresh Core matrix at dp=0.010/0.0075/0.005 m and a preregistered event observer are still required.",
                "Reference time origin, uncertainty envelope, and run-up event thresholds require root review.",
            ],
        },
        "fresh_input_contract": {
            "source_identity_changed": True,
            "qualification_inheritance": False,
            "old_generated_input_reused": False,
            "old_trajectory_reused": False,
            "new_definition_required": True,
            "new_motion_file_required": True,
            "construction": (
                "Copy the pinned official source assets into a new Core case directory; "
                "emit a literal Definition and a literal motion file for every q/dp cell. "
                "For piston scale s, preserve the time column and write "
                "x_new(t)=x_initial+s*(x_old(t)-x_initial)."
            ),
            "forbidden_sources": [
                "campaigns/v0.1-candidate/cases/r3-f5-wave-runup/*/generated",
                "campaigns/v0.1-candidate/runs/r3-f5-wave-runup",
                "data-official/O5_wave_runup.h5",
                "data-official/O5_wave_runup_refined.h5",
            ],
            "allowed_reference_role": (
                "Pinned official XML/STL/motion/reference files may be read as source "
                "provenance and copied into a fresh output identity; prior generated "
                "products remain diagnostics only."
            ),
        },
        "fixed_scope_design": {
            "cell_count": 15,
            "spatial_cell_count": 13,
            "temporal_cell_count": 2,
            "parameter": "piston_displacement_scale",
            "mapping": "s(q)=0.80+0.40*q",
            "qualification_q": [0.0, 0.5, 1.0],
            "qualification_scale": [0.8, 1.0, 1.2],
            "held_out_q": [0.25, 0.75],
            "held_out_scale": [0.9, 1.1],
            "resolutions_m": [0.01, 0.0075, 0.005],
            "temporal_controls": ["internal_time", "native_output"],
            "registered_window": {
                "time_max_s": 16.0,
                "output_interval_s": 0.02,
                "gauge_interval_s": 0.02,
                "extension_before_anchor": False,
                "event_completion_required": True,
            },
            "fixed_physics": [
                "gravity=(0,0,-9.81) m/s^2",
                "official slope and block geometry copied by hash",
                "official piston time samples retained; only displacement scale varies",
                "particle shifting disabled unless a separately reviewed contract changes it",
            ],
            "denominator_policy": [
                "all 15 rows remain in the denominator",
                "solver failure, hard-integrity failure, and event censoring receive zero credit",
                "CPU/native preflight and anchor canary receive zero T1 credit",
            ],
        },
        "observer_contract_draft": {
            "hard_integrity": [
                "requested 16 s horizon reached",
                "native fluid IDs are unique and no active ID is missing",
                "all active position, velocity, density, mass, and gauge values are finite",
                "zero piston/slope/block closed-face endpoint violations",
                "zero saved-frame chord crossings through piston, slope, or block geometry",
                "zero unintended particles outside the explicit simulation domain",
                "native source mass and full-window mass change remain within root-approved fixed gates",
            ],
            "event": {
                "incident": "wave signal reaches WG1 and then WG2/WG3 in chronological order",
                "runup": "run-up-line signal exceeds a preregistered q-independent threshold and has a finite first/peak time",
                "return": "run-up returns below its event threshold before the 16 s horizon",
                "external": "q=0.5 scale=1.0 compares four model SWL gauges with the pinned CIEMito table using fixed time origin",
                "completion": "hard integrity, incident/run-up/return events, and complete horizon are all required",
            },
            "external_reference_policy": [
                "retain duplicate reference timestamps in provenance",
                "aggregate duplicates only for interpolation, never as extra observations",
                "do not optimize a local time shift as a physical calibration",
                "do not use the reference table as particle labels or training targets before independent review",
            ],
        },
        "root_review_only_contract": {
            "step_0": "Review this candidate, F5 family distinction, source hashes, and no-reuse boundary.",
            "step_1": "If accepted, write a fresh q=0.5, dp=0.0075 literal Definition and scaled motion file; do not run solver.",
            "step_2": "Run only CPU GenCase/native decode under a new output stem and audit normals, IDs, finite arrays, mass, domain and geometry endpoints; credit remains zero.",
            "step_3": "Root may then authorize exactly one protected solver anchor; this proposal itself submits nothing.",
            "step_4": "Only after a complete hard-pass anchor may the 15-row matrix be materialized; all rows and failures stay fixed in the denominator.",
            "step_5": "T1 promotion requires the complete fixed matrix, the separate 32-case production denominator, external/event review, and Core evaluator acceptance.",
        },
        "execution_controls": {
            "read_only_audit": True,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_launched": False,
            "queue_mutation": 0,
            "central_ledger_mutation": 0,
            "central_registry_mutation": 0,
            "matrix_materialized": False,
            "matrix_submitted": False,
        },
        "implementation": {
            "path": str(Path(__file__).resolve().relative_to(LAB)),
            "sha256": sha256(Path(__file__).resolve()),
            "role": "read-only proposal audit; no scientific execution",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_proposal()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "candidate": report["candidate"]["scope_id"],
                "output": str(args.output),
                "output_sha256": sha256(args.output),
                "registry_mutation": report["execution_controls"]["central_registry_mutation"],
                "ledger_mutation": report["execution_controls"]["central_ledger_mutation"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
