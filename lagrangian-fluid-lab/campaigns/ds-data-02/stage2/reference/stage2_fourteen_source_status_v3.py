#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a source-only current status index for the fourteen sentinels.

Only small JSON proof/source records named in ``SENTINELS`` are read.  This
builder never opens BI4, VTK, HDF5, native Part payloads, or solver output
arrays; it does not launch any process.  A record's qualification fields stay
UNKNOWN even when its bounded source, GenCase, observer, or solver diagnostic
passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.fourteen-source-status.v3"
REPO = Path(__file__).resolve().parents[5]
DEFAULT_CHECKPOINT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints"
REFERENCE_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")


def proof(name: str, claim_scope: str) -> dict[str, str]:
    return {"kind": "proof_json", "name": name, "claim_scope": claim_scope}


def source_file(path: str, claim_scope: str) -> dict[str, str]:
    return {"kind": "small_source_record", "path": path, "claim_scope": claim_scope}


SENTINELS: list[dict[str, Any]] = [
    {
        "sentinel_id": "F1-S1", "family_id": "F1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "terminal_category": "ACTUAL_SOLVER_AND_SELECTED_OBSERVER_DIAGNOSTIC",
        "terminal_status": "ACTUAL_DP010_DP005_DP0025_RUNS; CROSS_GRID_SPATIAL_CREDIT_UNRESOLVED",
        "hard_fail_or_blocker": ["Cross-grid diagnostic exceeds the frozen position tolerance in selected comparisons; neighbor-grid difference is not a truth/error bound."],
        "evidence": [
            proof("F1_S1_CROSS_GRID_SPATIAL_DIAGNOSTIC_INDEPENDENT_ROOT_VERIFICATION_068.json", "cross-grid arithmetic and lattice-resolution diagnostic; no truth credit"),
            proof("F1_DP005_SAME_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json", "actual same-CFL selected fields and source closure"),
            proof("F1_DP005_HALF_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json", "actual half-CFL selected fields and source closure"),
            proof("F1_DP0025_SAME_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json", "actual fine same-CFL selected fields and source closure"),
            proof("F1_DP0025_HALF_CFL_NINE_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_054.json", "actual fine half-CFL selected fields and source closure"),
        ],
        "next_guarded_task": {
            "kind": "JSON_ONLY_EXISTING_OBSERVER_COMPARISON",
            "action": "Compare already-produced selected observers at registered common queries using actual RunPARTs brackets; separate asynchronous time/output diagnostics from spatial or integration error.",
            "source_prerequisite": "F1 four observer proofs above plus existing DP010 observer proof",
            "payload_read": "none beyond already selected observer JSON",
            "solver_launch": False,
            "success_condition": "bounded comparisons report exact/bracketed/UNKNOWN per query and retain all tolerance gates",
        },
    },
    {
        "sentinel_id": "F1-S2", "family_id": "F1", "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "terminal_category": "ACTUAL_FULL_WINDOW_RUNS_DIAGNOSTIC",
        "terminal_status": "ACTUAL_DP0225_AND_DP017_801_FRAME_WINDOWS; OBSERVER_AND_INTEGRATION_QUALIFICATION_UNKNOWN",
        "hard_fail_or_blocker": ["Terminal saved times and counter conventions are bounded actual evidence; they do not establish a full per-step integration error bound."],
        "evidence": [
            proof("F1_COARSE_DP0225_FULL4S_INDEPENDENT_VERIFICATION_001.json", "actual 801-frame full-window coarse run"),
            proof("F1_FINE_DP017_FULL4S_INDEPENDENT_VERIFICATION_001.json", "actual 801-frame full-window fine run with endpoint caveat"),
            proof("F1_THREE_INTERVAL_GENCASE_INDEPENDENT_VERIFICATION_001.json", "source-bound three-rung GenCase diagnostics"),
        ],
        "next_guarded_task": {
            "kind": "SELECTED_NATIVE_OBSERVER_AND_RUNPART_BRACKET_AUDIT",
            "action": "Decode only registered selected frames from the existing coarse/medium/fine trees and join actual saved-time brackets; do not add a finer solver.",
            "source_prerequisite": "F1 coarse/fine proof receipts and exact source controls",
            "payload_read": "bounded selected native frames only, after parent reservation",
            "solver_launch": False,
            "success_condition": "common-time coverage and output sampling are reported independently; missing brackets remain UNKNOWN",
        },
    },
    {
        "sentinel_id": "F2-S1", "family_id": "F2", "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "terminal_category": "ACTUAL_COARSE_FINE_RUNS_CONTINUUM_MASS_HARDFAIL",
        "terminal_status": "ACTUAL_DP01258_AND_DP00855_FULL_WINDOWS; DISCRETE_SOURCE_MASS_CLOSE; CONTINUUM_OWNER_EQUIVALENCE_HARDFAIL",
        "hard_fail_or_blocker": ["The finite continuous owner mass is 18.876 kg while the native discrete source target is 21.114 kg; source-relative agreement cannot be promoted to continuous initial-state qualification."],
        "evidence": [
            proof("F2_S1_COARSE_FULL_CFD_VERIFICATION_001.json", "actual coarse 401-frame full-window development run"),
            proof("F2_FINE_FULL4S_NATIVE_INDEPENDENT_VERIFICATION_001.json", "actual fine 801-frame full-window run and per-MK diagnostic"),
            proof("F2_S1_CONTINUUM_SOURCE_MASS_MISMATCH_ROOT_VERIFICATION_001.json", "finite owner mass closure and hard mismatch"),
        ],
        "next_guarded_task": {
            "kind": "SOURCE_OWNER_SUPPORT_AND_PER_MATERIAL_AUDIT",
            "action": "Close fill/continuous-owner support and per-MK mass semantics on existing source products before any further CFD; keep old runs immutable.",
            "source_prerequisite": "F2 continuum mismatch proof and existing coarse/fine source/control receipts",
            "payload_read": "small XML/report or bounded selected observer only",
            "solver_launch": False,
            "success_condition": "either an exact source-supported owner contract is proven or the matched branch is terminally limited with explicit UNKNOWN",
        },
    },
    {
        "sentinel_id": "F2-S2", "family_id": "F2", "physical_case_id": "F2_STAGE1_OFFSET_P03_OPEN_RIM_RX065_RY014_FILL080",
        "terminal_category": "SOURCE_CONTROL_ONLY_NO_PRIMARY_RUN",
        "terminal_status": "SOURCE_CONTROL_CLOSED; GENERATED_INITIAL_SUPPORT_AND_MASS_UNKNOWN",
        "hard_fail_or_blocker": ["No primary F2-S2 generated initial-state/support proof or solver run is bound; do not reuse F2-S1 mass or field output."],
        "evidence": [source_file("stage2_f2_s2_source_control_ladder_audit_v4.json", "exact source/control/motion closure only; no generated support or mass credit")],
        "next_guarded_task": {
            "kind": "CPU_GENCASE_INITIAL_SUPPORT_QA",
            "action": "Run one parent-guarded GenCase source/control ladder preflight, then audit generated XML/Fluid/Bound support, mass, overlap, and motion assets for this exact CURRENT case.",
            "source_prerequisite": "stage2_f2_s2_source_control_ladder_audit_v4.json",
            "payload_read": "generated outputs only after parent reservation",
            "solver_launch": False,
            "success_condition": "all three spatial rungs have actual XML/support/mass evidence before any solver request",
        },
    },
    {
        "sentinel_id": "F3-S1", "family_id": "F3", "physical_case_id": "F3_TWOAXIS_AY0P50_PITCH_NOMINAL",
        "terminal_category": "ACTUAL_ANCHOR_AND_NATIVE_COST_DIAGNOSTIC",
        "terminal_status": "ACTUAL_LABEL/COST ANCHOR; GRID_OBSERVER_AND_DYNAMICS_QUALIFICATION_UNKNOWN",
        "hard_fail_or_blocker": ["Existing labels and full-window reconstruction are scoped to source-region/accounting diagnostics; no continuous no-flux or numerical qualification is established."],
        "evidence": [
            proof("F3_ANCHOR_FAMILY_LABELS_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "actual saved-frame spatial/region/event labels with moving/hidden-crossing limits"),
            proof("F3_FULL836_PHASE_RECOVERY_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "actual full836 source reconstruction and phase recovery"),
            proof("F3_MATCHED_THREE_GRID_PLAN_AND_NATIVE_COST_METADATA_ROOT_VERIFICATION_119.json", "actual same-forcing cost anchor; no scientific qualification"),
        ],
        "next_guarded_task": {
            "kind": "BOUNDED_SELECTED_NATIVE_OBSERVER_AUDIT",
            "action": "Use the existing source-bound full836/cost anchor for a selected observer and RunPART bracket audit; keep no-flux/contact and cross-grid truth UNKNOWN until directly observed.",
            "source_prerequisite": "F3 anchor label proof and exact CURRENT source-control receipt",
            "payload_read": "bounded selected native frames after parent reservation",
            "solver_launch": False,
            "success_condition": "actual query brackets and material/region definitions are closed without inferring hidden crossings",
        },
    },
    {
        "sentinel_id": "F3-S2", "family_id": "F3", "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "terminal_category": "ACTUAL_INITIAL_SUPPORT_PASS_DISCRETE_MASS_BI4_HASH_PENDING",
        "terminal_status": "ROOT128_SUPPORT_V6_BOUNDED_PASS; NO_SOLVER_CREDIT; GENERATED_BI4_SOURCE_SNAPSHOT_PENDING",
        "hard_fail_or_blocker": ["The support report proves only initial discrete sample mass/axis/support; contact, flux, dynamics, dt, output, and QI/QN/QE remain UNKNOWN until the BI4 snapshot and later canary close."],
        "evidence": [
            proof("F3_DP015_SUPPORT_V6_ACTUAL_ROOT_VERIFICATION_128.json", "actual 4320-fluid/19944-bound support and 14.58 kg discrete diagnostic"),
            proof("F3_DP003_ACTUAL_SOURCE_MASS_OWNER_SUPPORT_ROOT_VERIFICATION_104.json", "actual DP003 source/support diagnostic, no dynamics credit"),
            proof("F3_MATCHED_THREE_GRID_PLAN_AND_NATIVE_COST_METADATA_ROOT_VERIFICATION_119.json", "actual same-forcing native cost anchor and source control"),
        ],
        "next_guarded_task": {
            "kind": "BI4_SOURCE_SNAPSHOT_THEN_EXTERNAL_V5_REQUEST",
            "action": "Parent-guard one complete generated.bi4 stream for ROOT120 (snapshot ROOT132); after the terminal SHA is returned, build the additive v7 external request for ROOT133. Do not hand-enter or locally hash the BI4.",
            "source_prerequisite": "ROOT120 q/receipt/generated.bi4 plus ROOT128 support proof; code commits fcf90594d and 4875bbd7b",
            "payload_read": "one complete BI4 stream for snapshot, then solver only if parent independently approves",
            "solver_launch": False,
            "success_condition": "snapshot full SHA/stat stable, exact q/receipt join, support/mass gate closed; otherwise stop with UNKNOWN",
        },
    },
    {
        "sentinel_id": "F4-S1", "family_id": "F4", "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "terminal_category": "ACTUAL_THREE_GRID_RUNS_AND_LOCAL_OBSERVERS",
        "terminal_status": "ACTUAL_COARSE/SAME/HALF/FINE_WINDOWS; BRACKET_AND_INTEGRATION_ERROR_SCOPE_UNKNOWN",
        "hard_fail_or_blocker": ["Exact native-time comparisons exist only at available saved times; bracket-only queries and interpolation error remain UNKNOWN, and SaveDt row-count convention is not a full-step trace proof."],
        "evidence": [
            proof("F4_S1_SAVEDT_SAME_CFL_INDEPENDENT_VERIFICATION_001.json", "actual same-CFL saved-time trace"),
            proof("F4_S1_SAVEDT_HALF_CFL_INDEPENDENT_VERIFICATION_001.json", "actual half-CFL trace with endpoint/clamp caveat"),
            proof("F4_FINE_FULL_WINDOW_INDEPENDENT_VERIFICATION_001.json", "actual fine full window"),
            proof("F4_OBSERVER_COMPARISON_INDEPENDENT_VERIFICATION_001.json", "actual observer comparison with UNKNOWN bracketed queries"),
            proof("F4_FULL_WINDOW_LOSSLESS_INDEPENDENT_VERIFICATION_001.json", "actual lossless native roundtrip"),
        ],
        "next_guarded_task": {
            "kind": "BOUNDED_COMMON_TIME_OBSERVER_COMPARISON",
            "action": "Use existing coarse/same/half/fine observers at real RunPART times, with explicit brackets and no interpolation credit until empirical output calibration closes.",
            "source_prerequisite": "F4 actual observer and SaveDt proofs",
            "payload_read": "selected native fields or existing observer JSON only",
            "solver_launch": False,
            "success_condition": "position/velocity/KE/region results are separated from time/output sampling and all missing brackets remain UNKNOWN",
        },
    },
    {
        "sentinel_id": "F4-S2", "family_id": "F4", "physical_case_id": "F4_DROP_gap0p18000_xoffm0p08000_yoff0p04000_uz0p60000",
        "terminal_category": "SOURCE_PLAN_ONLY_NO_PRIMARY_RUN",
        "terminal_status": "SOURCE_BOUND_SAVEDT_PLAN; SUPPORT/OBSERVABLES UNKNOWN",
        "hard_fail_or_blocker": ["F4-S1 actual observers cannot be transferred to F4-S2; no F4-S2 generated support or solver receipt is claimed."],
        "evidence": [source_file("stage2_savedt_cfl_pair_binding_v1.json", "exact F4-S2 source/control SaveDt pair bindings; launch state only")],
        "next_guarded_task": {
            "kind": "CPU_INITIAL_SUPPORT_QA_THEN_ONE_CANARY",
            "action": "Guard a small F4-S2 generated XML/VTK support and mass audit against exact gap/offset/velocity controls before selecting one full-window canary.",
            "source_prerequisite": "exact F4-S2 CURRENT XML/motion/BI4 and source-bound SaveDt pair",
            "payload_read": "generated support payload only after parent reservation",
            "solver_launch": False,
            "success_condition": "initial geometry/mass/control/support closes; otherwise preserve hard failure and do not schedule CFD",
        },
    },
    {
        "sentinel_id": "F5-S1", "family_id": "F5", "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        "terminal_category": "ACTUAL_INITIAL_SUPPORT_AND_CONTINUOUS_MASS_HARDFAIL",
        "terminal_status": "OFFICIAL_CLIP_SOURCE CLOSED; YHALF DP010 HARDFAIL, DP005 MARGINAL; NO_SOLVER_QUALIFICATION",
        "hard_fail_or_blocker": ["Official clip audit gives 287.736 kg continuous owner versus the old source sample 254.477983 kg (−11.5585%); Y-half DP010 is −2.2444% and DP005 −1.1420%, so no solver request is yet source-matched."],
        "evidence": [
            proof("F5_SOURCE_CLIP_CONTINUOUS_MASS_ACTUAL_HARDFAIL_ROOT_VERIFICATION_091.json", "official clip/continuous mass hard failure"),
            proof("F5_YHALF_DP010_V7_ACTUAL_INITIAL_SUPPORT_ROOT_VERIFICATION_109.json", "actual DP010 support/mass diagnostic"),
            proof("F5_YHALF_DP005_V7_ACTUAL_INITIAL_SUPPORT_ROOT_VERIFICATION_110.json", "actual DP005 support/mass diagnostic"),
            proof("F5_PROJECTION_V2_AND_STORAGE_PROXY_ACTUAL_METADATA_ROOT_VERIFICATION_114.json", "actual q/receipt/frame-size joins and cost proxy, not solver cost"),
        ],
        "next_guarded_task": {
            "kind": "SOURCE_BOUND_GEOMETRY_DIAGNOSTIC",
            "action": "Run the additive V10 q123 geometry/shape diagnostic against actual receipt/output paths and compare all-shape support semantics; retain the continuous owner and mass gates.",
            "source_prerequisite": "ROOT091/109/110 source proofs and q123 producer receipt",
            "payload_read": "bounded generated XML/VTK support after parent reservation",
            "solver_launch": False,
            "success_condition": "outside/overlap/shape assignment is resolved or the F5-S1 branch remains terminally hard-failed; no mass rescale",
        },
    },
    {
        "sentinel_id": "F5-S2", "family_id": "F5", "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T080",
        "terminal_category": "SOURCE_CONTROL_ONLY_NO_PRIMARY_RUN",
        "terminal_status": "SOURCE_CONTROL_CLOSED; INITIAL_SUPPORT/MASS/OBSERVERS UNKNOWN",
        "hard_fail_or_blocker": ["F5-S1 clip and Y-half diagnostics do not establish F5-S2; its transformed motion/bed and continuous owner require an independent source-bound initial QA."],
        "evidence": [source_file("stage2_f5_effective_condition_audit_v2.json", "exact F5-S1/F5-S2 controls and numerical recipe separation; no solver")],
        "next_guarded_task": {
            "kind": "CPU_GENCASE_INITIAL_SUPPORT_QA",
            "action": "Prepare one exact F5-S2 GenCase source/control output and guarded support/mass audit; keep source physical window 16 s distinct from XML 26 s and do not reuse F5-S1 sample mass.",
            "source_prerequisite": "F5-S2 exact CURRENT XML, transformed motion, bed/clip source and effective-condition audit",
            "payload_read": "generated XML/Fluid/Bound support only after parent reservation",
            "solver_launch": False,
            "success_condition": "continuous owner, support, count/mass and motion assets close before any full-window solver plan",
        },
    },
    {
        "sentinel_id": "F6-S1", "family_id": "F6", "physical_case_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
        "terminal_category": "ACTUAL_SOURCE_AND_RIGID_DIAGNOSTIC_OWNER_UNKNOWN",
        "terminal_status": "ACTUAL SOURCE/RIGID CLOUD/OBSERVATION DIAGNOSTICS; CONTINUOUS FLUID OWNER UNKNOWN",
        "hard_fail_or_blocker": ["SPH sample mass (256 kg) and physical rigid body mass (128 kg) are distinct; no linked continuous-fluid owner contract is authoritative."],
        "evidence": [
            proof("F6_ACTUAL_SOURCE_OWNER_AUTHORITY_UNKNOWN_ROOT_VERIFICATION_103.json", "actual source grids and explicit owner-authority UNKNOWN"),
            proof("F6_RIGID_CLOUD_V4_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "actual rigid cloud geometry diagnostics"),
            proof("F6_RIGID_OBSERVATION_INDEPENDENT_VERIFICATION_001.json", "actual rigid observation source/time/state identity"),
        ],
        "next_guarded_task": {
            "kind": "EXPLICIT_CONTINUOUS_OWNER_AND_RIGID_STATE_AUDIT",
            "action": "Bind a new explicit continuous-owner recipe and independently compare body mass/inertia/COM and fluid support; keep rigid physical mass separate from SPH sample mass.",
            "source_prerequisite": "F6 source-owner proof, rigid-cloud proof, exact motion/body metadata",
            "payload_read": "small XML/CSV or guarded selected fields; no new CFD",
            "solver_launch": False,
            "success_condition": "owner authority and rigid initial state are source-supported; otherwise retain UNKNOWN and do not call a matched grid",
        },
    },
    {
        "sentinel_id": "F6-S2", "family_id": "F6", "physical_case_id": "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
        "terminal_category": "ACTUAL_SOURCE_AND_RIGID_DIAGNOSTIC_OWNER_UNKNOWN",
        "terminal_status": "ACTUAL SHARED RIGID/SOURCE DIAGNOSTICS; CONTINUOUS FLUID OWNER UNKNOWN",
        "hard_fail_or_blocker": ["F6-S1 owner ambiguity and sample/body mass separation cannot be inherited as a matched F6-S2 reference."],
        "evidence": [
            proof("F6_ACTUAL_SOURCE_OWNER_AUTHORITY_UNKNOWN_ROOT_VERIFICATION_103.json", "actual S2 grid diagnostics with continuous owner UNKNOWN"),
            proof("F6_RIGID_CLOUD_V4_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "actual rigid cloud source comparison"),
            proof("F6_RIGID_OBSERVATION_INDEPENDENT_VERIFICATION_001.json", "actual rigid observation source/time/state identity"),
        ],
        "next_guarded_task": {
            "kind": "F6_S2_OWNER_AND_RIGID_INITIAL_QA",
            "action": "Use exact S2 angular control and physical COM/inertia to close continuous-owner/support and rigid-state identity in a bounded source audit before any solver.",
            "source_prerequisite": "F6-S2 CURRENT source/body/motion binding; shared F6 diagnostics are evidence only",
            "payload_read": "small source/selected-state fields after parent reservation",
            "solver_launch": False,
            "success_condition": "S2-specific owner/control/rigid identity is proven; no promotion from S1 or sample-mass agreement",
        },
    },
    {
        "sentinel_id": "F7-S1", "family_id": "F7", "physical_case_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1",
        "terminal_category": "ACTUAL_LABEL_AND_GENCASE_DIAGNOSTIC_NO_PRIMARY_REFERENCE",
        "terminal_status": "ACTUAL LABEL/MASS PROBES; FULL SOURCE-MATCHED RUN UNKNOWN",
        "hard_fail_or_blocker": ["Existing F7-S2 same/half runs do not cover F7-S1; no F7-S1 full-window source-matched solver or three-grid observer proof is bound."],
        "evidence": [
            proof("F7_ANCHOR_FAMILY_LABELS_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "actual F7-S1 label/region/source cohort diagnostics"),
            proof("MASS_FIT_INDEPENDENT_VERIFICATION_003.json", "actual bounded GenCase mass probes across families; not solver qualification"),
        ],
        "next_guarded_task": {
            "kind": "CPU_INITIAL_SUPPORT_QA_THEN_SINGLE_SOURCE_MATCHED_CANARY",
            "action": "Close F7-S1 exact current source/control/motion and initial support/mass in one guarded GenCase audit, then propose only one full-window canary with actual storage estimate.",
            "source_prerequisite": "F7-S1 CURRENT XML/motion and source-bound mass probe evidence",
            "payload_read": "generated support/selected observer only after parent reservation",
            "solver_launch": False,
            "success_condition": "initial support/mass/control and parent storage lease close before any solver; no F7-S2 inheritance",
        },
    },
    {
        "sentinel_id": "F7-S2", "family_id": "F7", "physical_case_id": "F7_OBSTACLE_QUINTIC_B08_A065",
        "terminal_category": "ACTUAL_FULL_WINDOW_AND_OUTPUT_DIAGNOSTIC",
        "terminal_status": "ACTUAL SAME_CFL/HALF_CFL FULL WINDOWS; LOCAL OUTPUT DIAGNOSTICS PASS; PHYSICAL/INTEGRATION Q UNKNOWN",
        "hard_fail_or_blocker": ["The joined same20/half17 calibration is local output sampling evidence; half radius-two frames/endpoints remain UNKNOWN and asynchronous differences are not pure integration error."],
        "evidence": [
            proof("F7_V5_FULL_NATIVE_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "actual same-CFL 1201-frame full native window"),
            proof("F7_HALF_CFL_SEVENTEEN_NATIVE_OBSERVER_ACTUAL_INDEPENDENT_VERIFICATION_001.json", "actual half-CFL selected fields"),
            proof("F7_V3_JOIN20_HALF17_CALIBRATION_ACTUAL_INDEPENDENT_VERIFICATION_051.json", "actual bounded 2x/4x output diagnostics with missing half neighbors explicit"),
            proof("F7_SAME_HALF_ACTUAL_FIELD_COMPARISON_INDEPENDENT_VERIFICATION_001.json", "actual same/half field differences, not truth error"),
        ],
        "next_guarded_task": {
            "kind": "KEEP_LOCAL_OUTPUT_CALIBRATION_SCOPE_OR_SNAPSHOT_MISSING_HALF_NEIGHBORS",
            "action": "Use the completed join20/half17 report as the terminal local output diagnostic; only schedule a unique bounded half-CFL 302/602/902 neighbor snapshot if that specific missing bracket is needed. Do not re-decode existing frames or claim integration truth.",
            "source_prerequisite": "F7 same20/half17 producer proofs and registered quarter-task tolerances",
            "payload_read": "only missing half neighbor frames after parent reservation",
            "solver_launch": False,
            "success_condition": "missing brackets become exact/bracketed or remain explicit UNKNOWN; no neighboring-grid truth credit",
        },
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    stat = path.stat()
    return {"path": str(path), "label": label, "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(path)}


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True, timeout=5).strip()
    except Exception:
        return "UNKNOWN"


def resolve_evidence(item: dict[str, str], checkpoint_root: Path) -> Path:
    if item["kind"] == "proof_json":
        return checkpoint_root / item["name"]
    if item["kind"] == "small_source_record":
        return REFERENCE_ROOT / item["path"]
    raise ValueError(item["kind"])


def build(checkpoint_root: Path) -> dict[str, Any]:
    checkpoint_root = checkpoint_root.expanduser().resolve()
    sentinels: list[dict[str, Any]] = []
    source_inputs: list[dict[str, Any]] = []
    for item in SENTINELS:
        evidence_records: list[dict[str, Any]] = []
        for entry in item["evidence"]:
            path = resolve_evidence(entry, checkpoint_root)
            file_record = record(path, f"{item['sentinel_id']} evidence")
            evidence_records.append({**entry, "file": file_record})
            source_inputs.append(file_record)
        sentinels.append({
            "sentinel_id": item["sentinel_id"],
            "family_id": item["family_id"],
            "physical_case_id": item["physical_case_id"],
            "terminal_state": {
                "category": item["terminal_category"],
                "status": item["terminal_status"],
                "hard_fail_or_blocker": item["hard_fail_or_blocker"],
                "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            },
            "evidence": evidence_records,
            "next_guarded_task": item["next_guarded_task"],
        })
    # Preserve declaration order but remove duplicate shared proof records.
    unique: dict[str, dict[str, Any]] = {}
    for item in source_inputs:
        unique[item["path"]] = item
    return {
        "schema": SCHEMA,
        "status": "SOURCE_ONLY_CURRENT_14_SENTINEL_TERMINAL_AND_NEXT_TASK_INDEX",
        "generated_by_commit": git_head(),
        "scope": {
            "sentinel_count": 14,
            "reads_json_proofs_and_small_source_records_only": True,
            "reads_bi4": False,
            "reads_vtk": False,
            "reads_hdf5": False,
            "reads_native_payloads": False,
            "starts_solver": False,
            "starts_gpu": False,
            "uses_neighbor_grid_as_truth": False,
            "qualification_policy": "all QI/QN/QE remain UNKNOWN; source/initial/support/observer diagnostics are scope-limited",
        },
        "frozen_gates": {
            "whole_initial_mass": "preferred <=1%; 1-2% marginal diagnostic; >2% hard fail",
            "position": "2% registered L; 5% near event",
            "velocity_ke": "5% nonzero registered scale",
            "regional_mass": "3 percentage points of whole initial fluid mass",
            "event_time": "1% registered characteristic time",
            "time_output": "each <= one quarter of its registered task gate",
            "unknown_policy": "no interpolation, adjacent-grid truth, or output cadence inference without actual brackets/calibration",
        },
        "source_inputs": list(unique.values()),
        "sentinels": sentinels,
        "global_unknowns": [
            "No sentinel receives QI/QN/QE from this index.",
            "Native/typed conversions, solver dt/clamp traces, and physical observer calibration remain scope-specific.",
            "F2-S2/F4-S2/F5-S2/F7-S1 have no primary source-matched full solver in this index.",
        ],
    }


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
            handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    if len(SENTINELS) != 14 or len({item["sentinel_id"] for item in SENTINELS}) != 14:
        raise AssertionError("sentinel declaration is not exactly fourteen unique entries")
    for item in SENTINELS:
        if set(item["next_guarded_task"]) < {"kind", "action", "solver_launch", "success_condition"}:
            raise AssertionError(f"incomplete next task: {item['sentinel_id']}")
        if any(item["terminal_status"].lower().find(token) >= 0 for token in ("qualified", "qn_pass", "qi_pass", "qe_pass")):
            raise AssertionError(f"unbounded qualification wording: {item['sentinel_id']}")
    return {"status": "PASS", "schema": SCHEMA, "sentinel_count": 14, "payload_reads": False, "solver_started": False, "all_qualification_unknown": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--checkpoint-root", type=Path, default=Path(os.environ.get("DS02_STAGE2_CHECKPOINT_ROOT", str(DEFAULT_CHECKPOINT_ROOT))))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if args.output is None:
        parser.error("--build requires --output")
    value = build(args.checkpoint_root)
    write_new(args.output, value)
    print(json.dumps({"status": value["status"], "schema": SCHEMA, "sentinel_count": len(value["sentinels"]), "output": str(args.output.resolve()), "payload_reads": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
