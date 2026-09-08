#!/usr/bin/env python3
"""Assemble the R6-N3 machine report into a reviewer handoff packet."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
N3_REPORT = CAMPAIGN / "r6-n3-endpoint-closure.json"
BRIDGE_REPORT = CAMPAIGN / "r6-n3-bridge-h10.json"
MATERIAL_REPORT = CAMPAIGN / "r6-n3-material-reference.json"
PERFORMANCE_REPORT = CAMPAIGN / "r6-n3-performance.json"
PROFILE_REPORT = CAMPAIGN / "r6-n3-phase-profile.json"
FORENSICS_REPORT = CAMPAIGN / "r6-n3-endpoint-forensics.json"
HANDOFF = CAMPAIGN / "R6-N3-LATEST-HANDOFF.md"
REVIEW_PACKET = CAMPAIGN / "R6-N3-REVIEW-PACKET.md"


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(path.resolve())


def read(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _git(command: list[str]) -> str | None:
    try:
        return subprocess.run(command, cwd=LAB.parent, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _audit_rows(report: dict[str, Any]) -> list[str]:
    rows = []
    for item in report.get("audits", []):
        classification = item.get("missing_identity_classification", {})
        rows.append(
            f"| `{item.get('case_id')}` | `{item.get('r6_full_time_audit_status')}` | "
            f"{item.get('initial_identities_missing_at_final', classification.get('missing_count', 'n/a'))} | "
            f"`{classification.get('status', 'n/a')}` | `{classification.get('exclusion_evidence_reason_counts', {})}` |"
        )
    return rows


def _bridge_rows(report: dict[str, Any]) -> list[str]:
    rows = []
    for item in report.get("audits", []):
        classification = item.get("missing_identity_classification", {})
        rows.append(
            f"| `{item.get('case_id')}` | `{item.get('r6_full_time_audit_status')}` | "
            f"{classification.get('missing_count', 'n/a')} | `{classification.get('status', 'n/a')}` |"
        )
    return rows


def _bridge_comparison_rows(report: dict[str, Any]) -> list[str]:
    rows = []
    for name, item in report.get("comparisons", {}).items():
        maxima = item.get("maxima", {})
        thresholds = item.get("thresholds", {})
        rows.append(
            f"| `{name}` | `{item.get('status', 'n/a')}` | "
            f"{maxima.get('distribution_tv', 'n/a')} / {thresholds.get('distribution_tv', 'n/a')} | "
            f"{maxima.get('com_l2_m', 'n/a')} / {thresholds.get('com_l2_m', 'n/a')} | "
            f"{maxima.get('front_q90_abs_delta_m', 'n/a')} / {thresholds.get('front_q90_abs_delta_m', 'n/a')} |"
        )
    return rows


def _forensic_fine_rows(report: dict[str, Any]) -> list[str]:
    rows = []
    for item in report.get("cases", []):
        if item.get("resolution") != "fine" or not item.get("case_id", "").startswith("R6_F1_"):
            continue
        rows.append(
            f"| `{item.get('case_id')}` | `{item.get('status', 'n/a')}` | "
            f"{item.get('missing_identity_count', 'n/a')} | "
            f"`{item.get('status', 'n/a')}` | `{item.get('partout_reason_counts', {})}` |"
        )
    return rows


def _p3_summary(report: dict[str, Any]) -> str:
    configs = report.get("configurations", [])
    lines = []
    for item in configs:
        extrema = item.get("source_extrema", {})
        unknown = {source: values.get("active_tracer_unknown") for source, values in extrema.items()}
        target = {source: values.get("target_occupancy") for source, values in extrema.items()}
        lines.append(
            f"| `{item.get('config_id')}` | {item.get('seed_count')} | {item.get('substeps')} | "
            f"`{target}` | `{unknown}` | `{item.get('first_passage_status_mass_fractions_by_source', {})}` |"
        )
    return "\n".join(lines) if lines else "| none | | | | | |"


def build() -> tuple[dict[str, Any], str, str]:
    n3 = read(N3_REPORT, {})
    bridge = read(BRIDGE_REPORT, {})
    material = read(MATERIAL_REPORT, {})
    performance = read(PERFORMANCE_REPORT, {})
    profile = read(PROFILE_REPORT, {})
    forensics = read(FORENSICS_REPORT, {})
    endpoint_pass = bool(n3.get("audits")) and all(item.get("r6_full_time_audit_status") == "pass" for item in n3.get("audits", []))
    bridge_audit_pass = bool(bridge.get("audits")) and all(item.get("r6_full_time_audit_status") == "pass" for item in bridge.get("audits", []))
    bridge_comparison_pass = bool(bridge.get("comparisons")) and all(
        item.get("status") == "pass_diagnostic" for item in bridge.get("comparisons", {}).values()
    )
    p3_complete = len(material.get("configurations", [])) == 6
    p4_decision = performance.get("decision", {})
    if endpoint_pass and bridge_audit_pass and bridge_comparison_pass:
        route_status = "candidate_same_cfl_h10_bridge_only"
    elif endpoint_pass and bridge_audit_pass:
        route_status = "candidate_same_cfl_h10_bridge_resolution_tv_blocked"
    else:
        route_status = "blocked_or_incomplete"
    decision = {
        "formal_release": False,
        "development_authorized": False,
        "t1_status": route_status,
        "endpoint_cfl_probe": "pass_full_time_no_identity_loss" if endpoint_pass else "failed_or_incomplete",
        "h10_bridge": (
            "pass_full_time_same_cfl_triplet"
            if bridge_audit_pass and bridge_comparison_pass
            else "pass_full_time_triplet_resolution_tv_blocked"
            if bridge_audit_pass
            else "failed_or_incomplete"
        ),
        "t2_status": material.get("acceptance_status", "not_run"),
        "p4_cuda_status": p4_decision.get("status", "not_run"),
        "reason_not_formal": (
            "the endpoint fine probe and h10 triplet use CFL 0.1, but h09/h11 "
            "coarse/medium have not been rerun under the same recipe; within the "
            "h10 bridge, coarse-to-medium distribution TV is 0.0569047619 > 0.05; "
            "no cross-resolution three-height production recipe is admitted"
        ),
    }
    summary = {
        "schema_version": "r6-n3-review-packet-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_branch": _git(["git", "branch", "--show-current"]),
        "git_head_at_generation": _git(["git", "rev-parse", "HEAD"]),
        "baseline_commit": "dcfef001eed3889ca6a055619a31dd4964515638",
        "decision": decision,
        "endpoint_audit_count": len(n3.get("audits", [])),
        "bridge_audit_count": len(bridge.get("audits", [])),
        "bridge_audit_pass": bridge_audit_pass,
        "bridge_comparison_pass": bridge_comparison_pass,
        "material_configuration_count": len(material.get("configurations", [])),
        "p1_case_count": len(forensics.get("cases", [])),
        "profile_bytes": profile.get("bytes"),
        "artifacts": {
            "endpoint_closure": relpath(N3_REPORT),
            "bridge": relpath(BRIDGE_REPORT),
            "p0_profile": relpath(PROFILE_REPORT),
            "p1_forensics": relpath(FORENSICS_REPORT),
            "p3_material": relpath(MATERIAL_REPORT),
            "p4_performance": relpath(PERFORMANCE_REPORT),
        },
        "resource_budget": {
            "new_solver_cases_used": 2 + len(bridge.get("solver_runs", [])),
            "new_solver_case_cap": 8,
            "bridge_case_cap": 3,
            "protected_gpu_indices": [0, 1, 2, 3],
            "allowed_gpu_indices": [4, 5, 6, 7],
        },
    }
    endpoint_rows = "\n".join(_audit_rows(n3)) or "| none | | | | |"
    legacy_fine_rows = "\n".join(_forensic_fine_rows(forensics)) or "| none | | | | |"
    p1_identity_rows = "\n".join([legacy_fine_rows, endpoint_rows])
    bridge_rows = "\n".join(_bridge_rows(bridge)) or "| not run | | | |"
    bridge_comparison_rows = "\n".join(_bridge_comparison_rows(bridge)) or "| not run | | | | |"
    speedups = performance.get("speedups", {})
    parity = performance.get("cuda_parity", {})
    common = material.get("supplemental_common_physical_point_groups", [])
    common_text = "; ".join(
        f"{item.get('group_id', item.get('status'))}: end-reliable={item.get('reliable_fraction_at_end')}, wall-crossings={item.get('wall_crossing_count')}"
        for item in common
    ) or "not run"
    handoff = f"""# R6-N3 latest handoff

Generated: {summary['generated_at_utc']}
Baseline: `{summary['baseline_commit']}`  Branch at generation: `{summary.get('git_branch')}`

## Decision

`formal_v0.1 = NO_GO` and `development_authorized = false` remain invariant.
The N3 result is `{route_status}`: the two endpoint fine probes and the h10
coarse/medium/fine bridge all use the same controlled `cflnumber=0.1`, but the
other endpoint resolutions were not rerun under that recipe.  In addition, the
h10 coarse-to-medium distribution comparison is above its diagnostic TV gate.
Therefore this round does not admit a three-height, three-resolution T1
production recipe.

| item | result |
|---|---|
| endpoint CFL probe | `{decision['endpoint_cfl_probe']}` |
| h10 same-CFL bridge | `{decision['h10_bridge']}` |
| T2 material | `{decision['t2_status']}` |
| CUDA candidate | `{decision['p4_cuda_status']}` |
| G4/development | `not launched` |

## P1 identity cause

The old N2 fine losses are solver-native density exclusions, not top absorption;
the new CFL endpoint probes retain all fine-grid identities:

| case | status/audit | missing final identities | classification | native evidence |
|---|---|---:|---|---|
{p1_identity_rows}

The identity-level report joins `PartOut` particle IDs to `RunPARTs.csv` native
counters, records the last valid state and failure window, and checks event
positions against the resolved GenCase particle envelope.  The physical top is
open geometrically but is not registered as an absorbing outlet.

## P2 endpoint and bridge evidence

| case | full-time audit | missing | classification |
|---|---|---:|---|
{bridge_rows}

The two endpoint N3 cases each saved 1,501 frames and retained all initial
identities.  Solver `PartsOut=0` and `NpOutRho=0` were observed for both.  The
h10 bridge also has `PartsOut=0` for all three resolutions.  Pair comparisons
remain numerical diagnostics, not external-fluid validation.

| comparison | status | max TV / gate | max COM / gate (m) | max q90 / gate (m) |
|---|---|---:|---:|---:|
{bridge_comparison_rows}

The coarse-to-medium bridge is `fail_diagnostic` because max TV is
`0.056904761904761875` against a `0.05` gate; medium-to-fine is
`pass_diagnostic`.  This is recorded as a resolution-consistency blocker, not
as particle-identity loss.

## P3 material reference

Six existing bundles were reused (medium 256/512 seeds × substeps 2/4; fine
512 seeds × substeps 2/4).  The report stores full saved-time source-wise
target occupancy, cumulative first passage, active unknown, solver-identity
unknown, error, and support-gate rejection.  First passage and terminal
destination are separate; no survivor renormalization is used.

Supplemental same-physical-point groups: {common_text}.

| bundle | seeds | substeps | max target occupancy by source | max active unknown by source | first-passage mass by source |
|---|---:|---:|---|---|---|
{_p3_summary(material)}

Acceptance remains candidate T2 numerical reference only; source labels are
initial-depth measurement strata, not material lineage.

## P4 performance

Two saved windows were measured with NumPy reference, current exact CPU Torch,
and opt-in exact CUDA top-k.  HDF5/sidecar I/O, transfers, neighbor queries,
finite-wall sweep, integration, output encoding, warmup, and explicit CUDA
synchronization are recorded in the machine report.  Speedups were:

`cpu_torch_vs_numpy={speedups.get('cpu_torch_vs_numpy')}`, `cuda_vs_numpy={speedups.get('cuda_vs_numpy')}`, `cuda_vs_cpu_torch={speedups.get('cuda_vs_cpu_torch')}`.

CUDA parity maxima were `{parity.get('max_position_delta_m')} m` and
`{parity.get('max_velocity_delta_mps')} m/s`; the 2× end-to-end gate is
`{p4_decision.get('two_x_end_to_end_gate')}`.  Production remains on CPU.

## Reproducibility and artifacts

- P0 compact profile: `{summary['artifacts']['p0_profile']}` (must remain under 100 KiB).
- P1 forensic evidence: `{summary['artifacts']['p1_forensics']}`.
- P2 endpoint closure: `{summary['artifacts']['endpoint_closure']}`.
- P2 h10 bridge: `{summary['artifacts']['bridge']}`.
- P3 material reference: `{summary['artifacts']['p3_material']}`.
- P4 performance: `{summary['artifacts']['p4_performance']}`.
- Raw BI4/attempt directories are intentionally ignored by Git but remain locally traceable from the reports and hashes.

## Remaining gate

To admit a same-recipe three-height T1 candidate, an explicitly authorized
follow-up would need the missing h09/h11 coarse and medium products under the
same accepted CFL recipe (or a reviewer-approved alternative).  This N3
budget stops after 2 endpoint probes + 3 bridge cases; no blind Cartesian scan,
F6 rerun, G4 ranking, or formal release was performed.
"""
    review = f"""# R6-N3 reviewer packet

This packet is for the cloud reviewer.  It is based on baseline
`{summary['baseline_commit']}` and the N3 reports below; all conclusions are
candidate numerical evidence only.

## Requested review

1. Confirm whether the P1 `PartOut`/`RunPARTs` joins support the conclusion that
   the old fine-grid losses are density exclusions rather than top absorption.
2. Assess whether `cflnumber=0.1` is an acceptable single-factor numerical
   repair probe.  The endpoint and h10 bridge are deliberately not promoted to
   formal T1 because h09/h11 coarse/medium were not rerun at that recipe and
   the h10 coarse-to-medium TV diagnostic failed (`0.0569047619 > 0.05`).
3. Check the P3 source-wise full-time semantics: target occupancy, first
   passage, terminal category, unknown/error, support rejection, and no
   survivor renormalization.
4. Check P4 parity and the decision to retain the CPU tracer path because CUDA
   is only `{speedups.get('cuda_vs_cpu_torch')}`× end-to-end versus CPU Torch.
5. Recommend the next bounded gate, including whether the missing same-recipe
   endpoint resolutions justify a new solver budget.

## Evidence files

- P0: `{summary['artifacts']['p0_profile']}`
- P1: `{summary['artifacts']['p1_forensics']}`
- P2 endpoints: `{summary['artifacts']['endpoint_closure']}`
- P2 bridge: `{summary['artifacts']['bridge']}`
- P3: `{summary['artifacts']['p3_material']}`
- P4: `{summary['artifacts']['p4_performance']}`

## Current disposition

`formal_release=false`, `development_authorized=false`, `G4=not launched`.
Please treat all raw attempt directories as local provenance rather than Git
artifacts; the machine reports contain SHA-256 hashes and exact paths.
"""
    return summary, handoff, review


def main() -> int:
    summary, handoff, review = build()
    N3_REPORT.write_text(json.dumps({**read(N3_REPORT, {}), "n3_decision": summary["decision"], "review_packet": {"summary": "R6-N3-REVIEW-PACKET.md", "handoff": "R6-N3-LATEST-HANDOFF.md"}}, indent=2, ensure_ascii=False) + "\n")
    HANDOFF.write_text(handoff)
    REVIEW_PACKET.write_text(review)
    print(json.dumps({
        "decision": summary["decision"],
        "handoff": relpath(HANDOFF),
        "review_packet": relpath(REVIEW_PACKET),
        "profile_bytes": summary.get("profile_bytes"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
