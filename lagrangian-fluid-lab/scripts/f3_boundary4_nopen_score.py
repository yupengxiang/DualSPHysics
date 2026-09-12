"""Score the current NoPenetration four-layer bridge against NP01.

This is a read-only diagnostic.  The bridge has a different boundary asset and
is not an NP01--NP14 source until a prospective qualification plan is issued.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import f3_nopen_stage_score as stage
from scripts.f3_timestep_evidence import evidence as timestep_evidence
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256, utc_now


BASE_ID = "F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen"
NP05_ID = "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen"
NP06_ID = "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen"
BRIDGE_ID = "F3_CELL4_LONG_dp0p01_a1p000_noslip_visco1_nopen"
OUTPUT = OUT / "F3-NOPEN-BOUNDARY4-DIAGNOSTIC.json"


def _source(case_id, cfl=.05):
    audit = json.loads((OUT / (case_id + "-AUDIT.json")).read_text())
    prepared = json.loads((OUT / (case_id + "-PREPARED.json")).read_text())
    return dict(case_id=case_id, plan_case_id=case_id,
                hdf5_path=(LAB / audit["hdf5"]).resolve(), audit=audit,
                native_timestep=timestep_evidence(case_id),
                entry={"output_interval_s": .01, "coef_dt_min": cfl},
                prepared=prepared)


def run():
    base = _source(BASE_ID)
    np05 = _source(NP05_ID)
    np06 = _source(NP06_ID)
    bridge = _source(BRIDGE_ID)
    with (stage.CachedSource(base) as a, stage.CachedSource(np05) as e,
          stage.CachedSource(np06) as f, stage.CachedSource(bridge) as b):
        # GenCase assigns fluid IDs after boundary particles.  Adding a layer
        # therefore shifts the IDs even though the fluid count and masses are
        # unchanged; use the registered macro distribution operator rather
        # than pretending that trajectories have the same identity axis.
        panel = stage.score_pair(a, b, kind="np01_vs_nopen_boundary4",
                                 step_s=.01, threshold=.05, same_ids=False)
        bridge_np05 = stage.score_pair(b, e, kind="nopen_boundary4_vs_np05",
                                       step_s=.01, threshold=.05, same_ids=False)
        bridge_np06 = stage.score_pair(b, f, kind="nopen_boundary4_vs_np06",
                                       step_s=.01, threshold=.05, same_ids=False)
    result = dict(
        schema="f3.nopen.boundary4.diagnostic.v1", status="completed",
        created_at_utc=utc_now(), case_ids=[BASE_ID, BRIDGE_ID],
        scope=("Current NoPenetration=True four-layer bridge only; diagnostic evidence. "
               "It does not rewrite the frozen nominal gate or qualify a recipe."),
        boundary_change="vdp 0,1,2 -> 0,1,2,3",
        identity_alignment=("not available: GenCase shifts fluid particle IDs from 42480..57059 "
                            "to 58448..73027; fluid count and per-particle masses remain equal"),
        effective_modes={
            BASE_ID: {"solver_mode": "-mdbc_noslip:1", "no_penetration": True},
            BRIDGE_ID: {"solver_mode": "-mdbc_noslip:1", "no_penetration": True},
        },
        panels={name: {k: value[k] for k in (
            "kind", "case_ids", "time_window_s", "target_count", "threshold",
            "maxima", "peak_times_s", "status")}
                for name, value in (("np01_vs_nopen_boundary4", panel),
                                    ("nopen_boundary4_vs_np05", bridge_np05),
                                    ("nopen_boundary4_vs_np06", bridge_np06))},
        source_audit_sha256={name: sha256(OUT / (name + "-AUDIT.json"))
                             for name in (BASE_ID, NP05_ID, NP06_ID, BRIDGE_ID)},
        scorer_sha256=sha256(Path(__file__)),
        stage_scorer_sha256=sha256(LAB / "scripts/f3_nopen_stage_score.py"),
    )
    atomic_json(OUTPUT, result)
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == "__main__":
    run()
