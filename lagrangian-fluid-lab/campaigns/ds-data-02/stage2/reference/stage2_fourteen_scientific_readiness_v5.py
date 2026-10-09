#!/usr/bin/env python3
"""Build a compact, source-only scientific readiness graph for all 14 sentinels.

The graph consumes only the existing small status/index JSON files.  It is an
execution map, not a qualification report: every QI/QN/QE value remains
UNKNOWN, bracketed asynchronous observations remain bracketed, and an actual
diagnostic or metadata parent task is never promoted to a reference pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
STATUS_V4 = HERE / "stage2_fourteen_evidence_status_v4.json"
GRAPH_V5 = HERE / "stage2_fourteen_request_graph_v5.json"
SCHEMA = "ds02.stage2.fourteen-scientific-readiness.v5"

FROZEN_TOLERANCE = {
    "position_fraction_of_registered_L": {"value": 0.02, "measured": False, "scope": "registered task tolerance only"},
    "velocity_and_ke_fraction_of_registered_nonzero_scale": {"value": 0.05, "measured": False, "scope": "registered task tolerance only"},
    "event_time_fraction_of_registered_T": {"value": 0.01, "measured": False, "scope": "event T remains UNKNOWN unless source event is registered"},
    "time_and_output_each_fraction_of_task_tolerance": {"value": 0.25, "measured": False, "scope": "calibration gate, not a reported error"},
    "whole_initial_fluid_mass_target_pct": {"value": 1.0, "measured": False, "scope": "initial owner mass gate"},
    "whole_initial_fluid_mass_hard_upper_pct": {"value": 2.0, "measured": False, "scope": "hard upper gate"},
}


OVERRIDES: dict[str, dict[str, Any]] = {
    "F1-S1": {
        "recipe": "owner-matched dp=.010/.005/.0025 GenCase products and same/half-CFL runs exist",
        "owner": "40.2 kg owner/support evidence is closed for the matched F1-S1 recipe",
        "control": "same/half runs and ROOT207 header/calibration exist; saved-time alignment remains asynchronous",
        "initial_support": "ROOT207 native header/role/mass diagnostics terminal; no world-axis or continuum Q",
        "three_grid": "three spatial levels exist; observed cross-grid differences exceed the registered position gate; neighbor grids are not truth",
        "window": "1.6 s same/half windows with selected native observations; exact/bracketed times retained",
        "next": {"kind": "BOUNDED_COMMON_QUERY_OBSERVER_COMPARISON", "action": "Compare existing F1-S1 native fields at actual RunPART brackets and separate time/output from spatial differences; no new finer solver."},
    },
    "F1-S2": {
        "recipe": "340 kg owner, ROOT233 initial support, ROOT260 CFL entrypoint, and ROOT271 .5 s same/half source pair prepared",
        "owner": "ROOT227 owner audit is available; native sample mass remains separate from 340 kg owner",
        "control": "ROOT260 establishes the source entrypoint; ROOT271 changes .5 s SaveDt/.005 output and CFL pair, but terminal receipts are pending",
        "initial_support": "ROOT233 is a limited frame-0 support diagnostic; selected native dynamic support is still pending for ROOT271",
        "three_grid": "existing DP0225/DP017 source runs are diagnostic only; no three-grid scientific credit",
        "window": "existing full-window diagnostics plus pending .5 s pair; no interpolation or endpoint truth",
        "next": {"kind": "ROOT271_TERMINAL_INTAKE_NATIVE_SELECTED_OBSERVER", "action": "After ROOT273 terminal receipts, derive frame IDs and [0,.25,.5] brackets from each actual RunPARTs.csv, then parent-guard selected native fields."},
    },
    "F2-S1": {
        "recipe": "owner-centered cell-selector ladder has actual coarse/middle/fine GenCase QA, while legacy native source remains a mass mismatch",
        "owner": "18.876 kg continuous owner is fixed; old/native 21.114 kg (+11.8%) is a hard failure and is not rescaled",
        "control": "source controls and motion are retained; numerical-domain sensitivity was observed but is not a physical Q",
        "initial_support": "cell-selector support QA is terminal for the three generated products; continuous equivalence remains source-limited",
        "three_grid": "coarse/middle/fine initial products exist at owner-centered selectors; solver/reference qualification is absent",
        "window": "existing full-window runs are diagnostic only; no new solver until owner/support admission is closed",
        "next": {"kind": "SOURCE_OWNER_SUPPORT_AND_PER_MATERIAL_AUDIT", "action": "Close fill/continuous-owner support and per-MK semantics on the existing products before any additional CFD."},
    },
    "F2-S2": {
        "recipe": "CURRENT source/control is closed; generated initial products and mass/support remain unmeasured",
        "owner": "continuous owner equivalence UNKNOWN",
        "control": "source control binding CLOSED for this sentinel",
        "initial_support": "UNKNOWN; no generated support/mass audit yet",
        "three_grid": "no accepted three-grid source ladder",
        "window": "no qualified dynamic window",
        "next": {"kind": "PARENT_GUARDED_GENCASE_INITIAL_SUPPORT_QA", "action": "Run one exact CURRENT GenCase source/control preflight and audit XML/Fluid/Bound support, mass, overlap, and motion assets."},
    },
    "F3-S1": {
        "recipe": "source/label/cost anchor exists; matched three-grid initial/control closure is incomplete",
        "owner": "continuous owner/support UNKNOWN",
        "control": "source control only; no matched dynamic control proof",
        "initial_support": "selected native/support audit not terminal",
        "three_grid": "no accepted three-grid scientific comparison",
        "window": "bounded source/cost evidence only",
        "next": {"kind": "BOUNDED_SELECTED_NATIVE_OBSERVER_AUDIT", "action": "Use a source-bound selected observer and RunPART bracket audit; keep no-flux/contact and cross-grid truth UNKNOWN."},
    },
    "F3-S2": {
        "recipe": "coarse/middle/fine owner-centered products and external runs have terminal native diagnostics",
        "owner": "14.58 kg initial owner/support evidence is bounded; continuous-equivalence and fate of exclusions remain limited",
        "control": "same-CFL control/forcing lineage is joined for ROOT133/162/170; half-CFL and half-output pair results are diagnostics",
        "initial_support": "ROOT128/150/167/177/178 support/native summaries are terminal with finite/identity/MassFluid checks",
        "three_grid": "coarse/middle/fine native full-window diagnostics exist; no neighbor-grid truth",
        "window": "8.35 s windows, selected/full compact summaries, and ROOT195 brackets; time/output/integration errors remain UNKNOWN",
        "next": {"kind": "SOURCE_BOUND_MIDDLE_FINE_OBSERVER_COMPARISON", "action": "Consume compact summaries with strict producer/receipt/proof joins; keep lifecycle, async time, integration and output errors separate."},
    },
    "F4-S1": {
        "recipe": "coarse/same/half/fine source observers and missing-row diagnostics exist",
        "owner": "continuous owner/reference admission UNKNOWN",
        "control": "same/half/fine control metadata is retained; no interpolation credit",
        "initial_support": "native selected fields finite in bounded reports; physical support/Q unknown",
        "three_grid": "diagnostic rows exist; no truth grid",
        "window": "common-time report and 24 missing rows per run are terminal diagnostics",
        "next": {"kind": "BOUNDED_COMMON_TIME_OBSERVER_COMPARISON", "action": "Use real RunPART saved times and brackets; separate output sampling from integration/spatial differences."},
    },
    "F4-S2": {
        "recipe": "source-bound SaveDt plan only",
        "owner": "UNKNOWN",
        "control": "source control plan available; execution not terminal",
        "initial_support": "UNKNOWN",
        "three_grid": "no accepted three-grid products",
        "window": "no qualified dynamic window",
        "next": {"kind": "PARENT_GUARDED_INITIAL_SUPPORT_QA", "action": "Audit one exact gap/offset/velocity source product before selecting one canary."},
    },
    "F5-S1": {
        "recipe": "official clip source is understood; y-half/y-zero products are actual mass/support diagnostics",
        "owner": "continuous clip/overlap volume is not closed",
        "control": "motion/boundary source is retained; old 26 s XML and actual 16 s window remain distinct",
        "initial_support": "dp=.010 hard fail, dp=.005 marginal; clip outside zero does not prove flux/no-penetration",
        "three_grid": "no accepted three-grid source recipe; mass-fit is forbidden",
        "window": "16 s source window and 14.4 s motion scope remain explicit; no solver qualification",
        "next": {"kind": "SOURCE_BOUND_CLIP_GEOMETRY_DIAGNOSTIC", "action": "Compare all-shape selector/support semantics under the frozen clip and continuous owner; retain mass gates."},
    },
    "F5-S2": {
        "recipe": "source control closed; initial product not audited",
        "owner": "UNKNOWN",
        "control": "source/motion control closed; 16 s physical window must remain distinct from 26 s XML",
        "initial_support": "UNKNOWN",
        "three_grid": "no accepted three-grid source recipe",
        "window": "no qualified dynamic window",
        "next": {"kind": "PARENT_GUARDED_GENCASE_INITIAL_SUPPORT_QA", "action": "Prepare one exact source product and audit support/mass before any solver."},
    },
    "F6-S1": {
        "recipe": "current/ coarse/fine GenCase products exist, but ROOT272 V5 identity failure is preserved and ROOT276 V6 is pending",
        "owner": "ROOT252 continuous owner 4851.988676250775 kg is separate from body mass 128 kg and legacy sample 5120 kg",
        "control": "rigid/source metadata ROOT244 is terminal; continuous fluid support is not closed",
        "initial_support": "ROOT272 V5 failed because a producer receipt omitted physical_case_id; ROOT276 must emit per-case UNKNOWN rather than fallback",
        "three_grid": "coarse/fine source products exist; no accepted support-equivalent three-grid study",
        "window": "no dynamic qualification window",
        "next": {"kind": "ROOT276_PARTIAL_IDENTITY_INITIAL_SUPPORT_V6", "action": "Join each actual producer request case/attempt/source XML/input hashes to the explicit sentinel-grid mapping; run support only for closed cases."},
    },
    "F6-S2": {
        "recipe": "current/coarse/fine products exist with the same identity/support limitation as F6-S1",
        "owner": "ROOT252 owner and ROOT244 rigid metadata remain separate; continuous support UNKNOWN",
        "control": "omega=2.0 source/rigid control metadata exists; no dynamic qualification",
        "initial_support": "ROOT276 partial identity/support audit pending; missing physical identity must remain UNKNOWN",
        "three_grid": "source products are diagnostics only",
        "window": "no qualified dynamic window",
        "next": {"kind": "ROOT276_PARTIAL_IDENTITY_INITIAL_SUPPORT_V6", "action": "Close producer identity and initial support per case, without treating sentinel labels as physical identities."},
    },
    "F7-S1": {
        "recipe": "label/mass probes exist; source-matched full run is not closed",
        "owner": "UNKNOWN",
        "control": "motion/source matching and initial support remain incomplete",
        "initial_support": "UNKNOWN",
        "three_grid": "no accepted three-grid recipe",
        "window": "no qualified full window",
        "next": {"kind": "PARENT_GUARDED_INITIAL_SUPPORT_QA", "action": "Close exact source/control/motion and initial support, then propose one canary with actual storage estimate."},
    },
    "F7-S2": {
        "recipe": "same/half-CFL full windows and selected/native/output diagnostics are terminal",
        "owner": "initial sample/source evidence exists; physical/reference owner and spatial truth remain UNKNOWN",
        "control": "same/half CFL and output calibration are separated; missing half-CFL neighbor brackets remain UNKNOWN",
        "initial_support": "native selected fields finite/identity-stable in baseline and half reports",
        "three_grid": "no accepted spatial three-grid truth",
        "window": "12 s same/half windows and join20/half17 diagnostics terminal; no interpolation",
        "next": {"kind": "LOCAL_OUTPUT_SCOPE_OR_UNIQUE_HALF_NEIGHBOR_SNAPSHOT", "action": "Retain local output diagnostic; schedule only the unique missing half-CFL neighbors if a registered bracket requires them."},
    },
}


def _read_small(path: Path, label: str) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} is not a regular file: {path}")
    stat = path.stat()
    if stat.st_size > 4 * 1024 * 1024:
        raise ValueError(f"{label} exceeds 4 MiB: {path}")
    raw = path.read_bytes()
    after = path.stat()
    if (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError(f"{label} changed while read: {path}")
    return json.loads(raw.decode("utf-8")), {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "stat": {"dev": after.st_dev, "ino": after.st_ino, "mtime_ns": after.st_mtime_ns, "ctime_ns": after.st_ctime_ns}}


def build(output: Path) -> dict[str, Any]:
    status, source_record = _read_small(STATUS_V4, "fourteen evidence status v4")
    graph, graph_record = _read_small(GRAPH_V5, "fourteen request graph v5")
    source_by_id = {str(item["sentinel_id"]): item for item in status.get("sentinels", []) if isinstance(item, dict) and item.get("sentinel_id")}
    graph_by_id = {str(item["sentinel_id"]): item for item in graph.get("sentinels", []) if isinstance(item, dict) and item.get("sentinel_id")}
    expected = ["F1-S1", "F1-S2", "F2-S1", "F2-S2", "F3-S1", "F3-S2", "F4-S1", "F4-S2", "F5-S1", "F5-S2", "F6-S1", "F6-S2", "F7-S1", "F7-S2"]
    if set(source_by_id) != set(expected):
        raise ValueError(f"status index identity mismatch: {sorted(source_by_id)}")
    sentinels: list[dict[str, Any]] = []
    for sid in expected:
        source = source_by_id[sid]
        graph_item = graph_by_id.get(sid, {})
        override = OVERRIDES[sid]
        sentinels.append({
            "sentinel_id": sid,
            "family_id": source.get("family_id"),
            "physical_case_id": source.get("physical_case_id"),
            "actual_evidence_scope": source.get("status_v4", {}).get("actual_diagnostic_state", source.get("terminal_state", {}).get("status", "UNKNOWN")),
            "evidence_proof_ids": source.get("status_v4", {}).get("proof_ids_added", []),
            "recipe": override["recipe"],
            "owner_status": override["owner"],
            "control_status": override["control"],
            "initial_support_status": override["initial_support"],
            "three_grid_status": override["three_grid"],
            "window_status": override["window"],
            "registered_tolerance": copy_tolerance(),
            "next_request": override["next"],
            "source_index_next_kind": graph_item.get("next_request_kind"),
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "limits": {
                "neighbor_grid_truth": False,
                "interpolation": False,
                "bracket_width_is_error": False,
                "native_sample_mass_is_continuum_owner_mass": False,
                "physical_fate_from_disappearance": False,
            },
        })
    families: dict[str, dict[str, Any]] = {}
    for item in sentinels:
        fam = str(item["family_id"])
        families.setdefault(fam, {"family_id": fam, "sentinel_ids": [], "current_scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "family_next_focus": []})
        families[fam]["sentinel_ids"].append(item["sentinel_id"])
        families[fam]["family_next_focus"].append({"sentinel_id": item["sentinel_id"], "kind": item["next_request"]["kind"]})
    result = {
        "schema": SCHEMA,
        "status": "SOURCE_ONLY_READINESS_GRAPH_NOT_SCIENTIFIC_QUALIFICATION",
        "generated_by": {"path": str(HERE / Path(__file__).name), "payload_read": False},
        "source_snapshot": {"status_v4": source_record, "request_graph_v5": graph_record},
        "scope": {
            "sentinel_count": 14,
            "family_count": 7,
            "reads": ["small status/index JSON only"],
            "reads_production_native": False,
            "starts_solver": False,
            "starts_gpu": False,
            "all_QI_QN_QE": "UNKNOWN",
        },
        "frozen_tolerance": FROZEN_TOLERANCE,
        "families": list(families.values()),
        "sentinels": sentinels,
        "current_additions": {
            "ROOT271": "F1-S2 .5 s same/half source pair is prepared; actual terminal receipts/RunPARTs are required before native intake",
            "ROOT276": "F6-S1/S2 V6 per-case identity/support audit pending; missing physical_case_id remains UNKNOWN",
            "ROOT207_217": "calibration/storage proofs are bounded component/header evidence and do not grant world-axis or scientific Q",
        },
        "global_limits": [
            "Metadata completion is not a scientific reference pass.",
            "Actual finite/native/identity diagnostics do not prove continuum equivalence, integration error, output error, or external validation.",
            "Same-time and bracketed observations retain their actual saved times; no interpolation or neighbor-grid truth.",
            "Native sample mass, continuum owner mass, rigid body mass, and floating sample mass remain separate quantities.",
        ],
    }
    output = output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise ValueError(f"refusing overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return result


def copy_tolerance() -> dict[str, Any]:
    return json.loads(json.dumps(FROZEN_TOLERANCE))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "sentinels": len(result["sentinels"]), "payload_read": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
