#!/usr/bin/env python3
"""Produce a compact evidence-limited matrix for all fourteen sentinels.

The v2 status and v5 source-control audit are historical preparation inputs.
This forward matrix keeps their actual source, mass, control, and window
evidence separate from later bounded observations.  It adds only explicitly
known root proofs (F1 owner QA/support, F2 continuum closure, and F7
same/half observers/output calibration).  Missing evidence remains UNKNOWN;
no family or neighboring-grid result is propagated to another sentinel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.fourteen-terminal-next-matrix.v3"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STATUS = REFERENCE / "stage2_fourteen_reference_status_v2.json"
CONTROL = REFERENCE / "stage2_fourteen_source_control_audit_v5.json"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
F2_CLOSURE = REFERENCE / "stage2_f2_s1_continuum_owner_closure_v1.json"
F1_SOLVER_REPORT = REFERENCE / "stage2_f1_s1_owner_matched_solver_requests_v2.json"
F7_NEIGHBOR_REPORT = REFERENCE / "stage2_f7_s2_output_neighbor_snapshot_request_v1.json"
OUTPUT = REFERENCE / "stage2_fourteen_terminal_next_matrix_v3.json"

F1_QA_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_TWO_OWNER_RUNGS_INITIAL_NATIVE_QA_V2_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
F1_SUPPORT_DP005 = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP005_V2_SUPPORT_CONTROL_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
F1_SUPPORT_DP0025 = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP0025_SUPPORT_V5_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
F7_OUTPUT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_S2_OUTPUT_CALIBRATION_V2/") / "f7-s2-output-calibration-v2-root-001-root-forward-030-001/report/f7_s2_output_calibration_v2.json"
F7_SAME_OBSERVER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_S2_SAME_CFL_TIME_OUTPUT_OBSERVER_V1/") / "f7-s2-same_cfl-time-output-observer-v1-root-001-root-forward-029-001/observer/f7_s2_same_cfl_time_output_observer_v1.json"
F7_HALF_OBSERVER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/F7_S2_HALF_CFL_TIME_OUTPUT_OBSERVER_V1/") / "f7-s2-half_cfl-time-output-observer-v1-root-001-root-forward-029-001/observer/f7_s2_half_cfl_time_output_observer_v1.json"


NEXT: dict[str, dict[str, Any]] = {
    "F1-S1": {
        "actual_override": "owner dp=.005 and .0025 native QA PASS; dp005 support PASS; dp0025 stable VTK support PASS; no dynamics credit",
        "next_request": "stage2-f1-s1-owner-matched-solver-v2: four launch-disabled full-window SaveDt requests, parent fresh UUID/ledger and serial raw-tree materialisation",
        "next_status": "READY_PARENT_GPU_DISPATCH_AFTER_SOURCE_PREFLIGHTS",
        "evidence": [str(F1_QA_PROOF), str(F1_SUPPORT_DP005), str(F1_SUPPORT_DP0025), str(F1_SOLVER_REPORT)],
    },
    "F1-S2": {
        "actual_override": "dp=.0225 and .017 full-window source-bound runs completed by root; .0225 sample mass -0.4995%, .017 +0.6009%; no QI/QN/QE",
        "next_request": "selected native observers for coarse/.017/original plus same/half output calibration; retain actual RunPARTs brackets",
        "next_status": "OBSERVATION_READY_SOURCE_BOUND",
        "evidence": ["F1-S2 root full-window receipts and canonical observer requests in stage2-f1-s2-reference-v6/native-observer-canonical-v5-final"],
    },
    "F2-S1": {
        "actual_override": "CURRENT full401 native source exists; exact Def/metadata drawboxes close continuum volume 18.876 kg while generated sample is 21.114 kg (+11.8563%); continuum equivalence finite-blocked",
        "next_request": "new separately registered owner-consistent geometry recipe/GenCase QA; current source remains discrete-sample diagnostic only",
        "next_status": "FINITE_CONTINUUM_MATCH_FAILURE_NO_MATCHED_CFD_UNDER_CURRENT_SOURCE",
        "evidence": [str(F2_CLOSURE)],
    },
    "F2-S2": {
        "actual_override": "CURRENT source full401/control evidence; coarse mass hard fail (+4.3998%) and fine sample diagnostic pass (+0.4213%); continuum owner equivalence unresolved",
        "next_request": "source-bound continuum/fill closure and actual initial QA for any new lattice, then same/half full-window pair",
        "next_status": "SOURCE_CLOSURE_REQUIRED",
        "evidence": ["stage2_fourteen_reference_status_v2 F2-S2 evidence matrix", "CURRENT source XML/receipt/control audit v5"],
    },
    "F3-S1": {
        "actual_override": "CURRENT source/control window bound; original/coarse sample gates source-relative, fine +2.9583% hard fail; forcing/hdp dependency remains source-bound",
        "next_request": "exact source-bound GenCase/initial QA for a meaningful spacing branch, then serial same/half full-window SaveDt",
        "next_status": "GENCASE_AND_SOURCE_DEPENDENCY_QA_REQUIRED",
        "evidence": ["stage2_fourteen_source_control_audit_v5 F3-S1", "stage2_fourteen_reference_status_v2 F3-S1"],
    },
    "F3-S2": {
        "actual_override": "CURRENT source/control window bound; original/coarse sample gates source-relative, fine +2.9583% hard fail; pitch/ay variant remains distinct",
        "next_request": "exact F3-S2 source/forcing closure and initial QA before same/half pair; do not reuse F3-S1 GenCase bytes as solver equivalence",
        "next_status": "GENCASE_AND_SOURCE_DEPENDENCY_QA_REQUIRED",
        "evidence": ["stage2_fourteen_source_control_audit_v5 F3-S2", "stage2_fourteen_reference_status_v2 F3-S2"],
    },
    "F4-S1": {
        "actual_override": "coarse/same/half/fine full-window native runs and selected physical observers exist; F4 SaveDt dt rows/clamps are local evidence; field/time qualification UNKNOWN",
        "next_request": "bounded full-window macro-observer streaming at common actual query brackets plus late-event observer; no endpoint extrapolation",
        "next_status": "OBSERVATION_AND_CALIBRATION_PENDING",
        "evidence": ["F4 same/half/fine/coarse receipts", "F4 selected physical observer reports", "stage2_f4 physical observer binding"],
    },
    "F4-S2": {
        "actual_override": "source/control and mass-preflight evidence only; coarse hard fail (+4.7054%), fine sample diagnostic -0.4290%; no matched dynamics credit",
        "next_request": "source-bound mass-compatible spatial branch with physical drop/control closure, then one full-window same/half pair",
        "next_status": "SPATIAL_SOURCE_MATCH_REQUIRED",
        "evidence": ["stage2_fourteen_reference_status_v2 F4-S2", "stage2_fourteen_source_control_audit_v5 F4-S2"],
    },
    "F5-S1": {
        "actual_override": "CURRENT CLI/XML/motion semantics independently source-verified; full801 native reconstruction completed; coarse/fine sample gates are >2% hard fail",
        "next_request": "selected physical observer/typed QA on actual full801 source; retain CLI tmax16 versus XML TimeMax26 distinction",
        "next_status": "OBSERVATION_READY_BUT_SPATIAL_MATCH_UNKNOWN",
        "evidence": ["F5 root full801 verification", "stage2_fourteen_source_control_audit_v5 F5-S1"],
    },
    "F5-S2": {
        "actual_override": "distinct motion/control source row; no qualified three-grid or field observer result",
        "next_request": "source-bound initial QA and mass-compatible grid before any full-window pair; do not borrow F5-S1 trajectory",
        "next_status": "SOURCE_BOUND_INITIAL_QA_REQUIRED",
        "evidence": ["stage2_fourteen_source_control_audit_v5 F5-S2", "stage2_fourteen_reference_status_v2 F5-S2"],
    },
    "F6-S1": {
        "actual_override": "source floating sample mass and physical rigid body mass/inertia/COM are separate; coarse sample diagnostic -0.8179%, fine -4.2002% hard fail",
        "next_request": "actual generated floating cloud COM/inertia/center audit for a mass-compatible branch, then selected observer; no sum(sample mass) as rigid mass",
        "next_status": "RIGID_PHYSICAL_STATE_AUDIT_REQUIRED",
        "evidence": ["F6 geometry/control v3 actual audit", "stage2_fourteen_reference_status_v2 F6-S1"],
    },
    "F6-S2": {
        "actual_override": "distinct omega/control source; same rigid massbody/inertia contract must be independently checked; coarse sample diagnostic -0.8179%, fine -4.2002% hard fail",
        "next_request": "source-bound floating COM/inertia/center audit and initial QA, then same/half pair only after spatial closure",
        "next_status": "RIGID_PHYSICAL_STATE_AUDIT_REQUIRED",
        "evidence": ["F6 geometry/control v3 actual audit", "stage2_fourteen_reference_status_v2 F6-S2"],
    },
    "F7-S1": {
        "actual_override": "CURRENT identity/control dependencies source-bound; coarse +9.4422% hard fail and fine identity/mass branch is not inherited from F7-S2",
        "next_request": "exact F7-S1 mass-compatible three-grid GenCase/initial QA and full-window pair; motion/control file SHA must be independently bound",
        "next_status": "SOURCE_MATCH_AND_INITIAL_QA_REQUIRED",
        "evidence": ["stage2_fourteen_reference_status_v2 F7-S1", "stage2_fourteen_source_control_audit_v5 F7-S1"],
    },
    "F7-S2": {
        "actual_override": "same/half full12s native runs, 17-frame observers, bounded output calibration and same-half field diagnostics completed; 4x neighbor/endpoints and pure integration/output decomposition remain UNKNOWN",
        "next_request": "stage2_f7-s2-output-neighbor-snapshot-v1 for frames 302/602/902, followed by source-enforced observer and 4x same-run diagnostics",
        "next_status": "READY_BOUNDED_NEIGHBOR_SNAPSHOT_NO_QUALIFICATION",
        "evidence": [str(F7_SAME_OBSERVER), str(F7_HALF_OBSERVER), str(F7_OUTPUT), str(F7_NEIGHBOR_REPORT)],
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file() or path.is_symlink():
        return {"path": str(path), "accessible": False}
    stat = path.stat()
    return {"path": str(path), "accessible": True, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def candidate_summary(row: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for candidate in row.get("initial_state", {}).get("spatial_candidates", []):
        result.append({
            "grid": candidate.get("grid"),
            "requested_dp_m": candidate.get("requested_dp_m"),
            "whole_initial_mass_error_pct": candidate.get("whole_initial_mass_error_pct"),
            "mass_gate": candidate.get("whole_initial_mass_gate"),
            "planning_status": candidate.get("planning_status"),
            "solver_started": candidate.get("solver_started"),
            "scientific_qualification": candidate.get("scientific_qualification"),
        })
    return result


def build() -> dict[str, Any]:
    for path in (STATUS, CONTROL, QUALITY):
        if not path.is_file():
            raise FileNotFoundError(path)
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    control = json.loads(CONTROL.read_text(encoding="utf-8"))
    quality = json.loads(QUALITY.read_text(encoding="utf-8"))
    rows = status.get("sentinels")
    quality_rows = quality.get("sources")
    control_rows = control.get("sources")
    if not isinstance(rows, list) or len(rows) != 14 or not isinstance(quality_rows, list) or len(quality_rows) != 14 or not isinstance(control_rows, list) or len(control_rows) != 14:
        raise ValueError("expected exact 14-row status/quality/control inputs")
    q_by_id = {row["sentinel_id"]: row for row in quality_rows}
    c_by_id = {row["sentinel_id"]: row for row in control_rows}
    matrix = []
    for row in rows:
        sid = row["sentinel_id"]
        if sid not in NEXT or sid not in q_by_id or sid not in c_by_id:
            raise ValueError(f"missing explicit next row for {sid}")
        q = q_by_id[sid]
        c = c_by_id[sid]
        source_controls = q.get("source_solver_controls", {})
        matrix.append({
            "sentinel_id": sid,
            "family_id": row.get("family_id"),
            "physical_case_id": row.get("physical_case_id"),
            "identity_status": row.get("identity", {}).get("current_identity_status"),
            "source": {
                "xml": record(Path(q["source_xml"]["path"])),
                "window_s": [0.0, q.get("window_end_s")],
                "source_dp_m": q.get("source_dp_m"),
                "source_fluid_particles": q.get("source_fluid_particles"),
                "source_sample_mass_kg": q.get("source_sample_mass_kg"),
                "solver_receipt_status": source_controls.get("status"),
                "solver_terminal_time_s": q.get("window_end_s"),
                "motion_refs": q.get("source_xml", {}).get("motion_refs", []),
            },
            "initial_spatial_candidates": candidate_summary(row),
            "control_and_integration": {
                "source_cfl": row.get("control_window", {}).get("source_cfl"),
                "half_cfl": row.get("control_window", {}).get("source_half_cfl"),
                "savedt_same_state": row.get("integration", {}).get("savedt_same_cfl", {}).get("execution_state"),
                "savedt_half_state": row.get("integration", {}).get("savedt_half_cfl", {}).get("execution_state"),
                "actual_dt_sequence": row.get("integration", {}).get("actual_dt_sequence", "UNKNOWN"),
                "clamp_status": row.get("integration", {}).get("half_cfl_clamp_or_endpoint_caveat", "UNKNOWN"),
            },
            "forward_actual_scope": NEXT[sid]["actual_override"],
            "next": {k: NEXT[sid][k] for k in ("next_request", "next_status", "evidence")},
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        })
    return {
        "schema": SCHEMA,
        "status": "ACTUAL_14_SENTINEL_TERMINAL_NEXT_MATRIX_WITH_LIMITED_OVERRIDES",
        "generated_at_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip(),
        "scope": {
            "sentinel_count": 14,
            "source_status_input": record(STATUS),
            "source_control_input": record(CONTROL),
            "source_quality_input": record(QUALITY),
            "native_or_h5_read_by_builder": False,
            "family_extrapolation": False,
            "qualification_policy": "each row keeps QI/QN/QE UNKNOWN until its own actual source-bound spatial, integration, output and observer evidence closes",
        },
        "frozen_error_budget": {
            "position_fraction_of_L": 0.02,
            "event_neighborhood_fraction_of_L": 0.05,
            "velocity_and_ke_fraction_of_nonzero_scale": 0.05,
            "whole_initial_mass_fraction": 0.03,
            "event_time_fraction_of_characteristic_T": 0.01,
            "time_and_output_each_fraction_of_task_budget": 0.25,
            "event_T": "UNKNOWN where source has no registered event definition",
        },
        "sentinels": matrix,
        "global_unknowns": [
            "native sample mass is not continuum mass or rigid-body mass",
            "RunPARTs summaries are not full per-step dt traces",
            "actual saved-time brackets and output sampling remain distinct from integration and spatial error",
            "no neighboring-grid result is used as truth for another sentinel",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    value = build()
    output = args.output.expanduser().resolve()
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if output.exists():
        if output.read_bytes() != encoded:
            raise FileExistsError(f"refuse to overwrite immutable matrix: {output}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(encoded)
    print(json.dumps({"status": value["status"], "output": str(output), "sha256": sha256(output), "sentinel_count": len(value["sentinels"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
