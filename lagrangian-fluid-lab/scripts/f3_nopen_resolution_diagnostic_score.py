"""Score the CFL-half root-cause diagnostic without touching qualification gates."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import f3_nopen_stage_score as stage
from scripts.f3_timestep_evidence import evidence as timestep_evidence
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256, utc_now


DIAGNOSTIC_ID = "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen_cflhalf_retry"
BASE_ID = "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen"
NP01_ID = "F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen"
OUTPUT = OUT / "F3-NOPEN-NP06-CFLHALF-DIAGNOSTIC.json"


def _source(case_id, *, cfl):
    audit = json.loads((OUT / (case_id + "-AUDIT.json")).read_text())
    return dict(
        case_id=case_id,
        plan_case_id=case_id,
        hdf5_path=(LAB / audit["hdf5"]).resolve(),
        audit=audit,
        native_timestep=timestep_evidence(case_id),
        entry={"output_interval_s": .01, "coef_dt_min": cfl},
    )


def _slim(panel):
    return dict(
        kind=panel["kind"], case_ids=panel["case_ids"], time_window_s=panel["time_window_s"],
        target_count=panel["target_count"], threshold=panel["threshold"],
        maxima=panel["maxima"], peak_times_s=panel["peak_times_s"], status=panel["status"],
        same_identity_interpolation_diagnostic=panel.get("same_identity_interpolation_diagnostic"),
    )


def run():
    np01 = _source(NP01_ID, cfl=.05)
    np06 = _source(BASE_ID, cfl=.05)
    half = _source(DIAGNOSTIC_ID, cfl=.025)
    with stage.CachedSource(np01) as a, stage.CachedSource(np06) as b, stage.CachedSource(half) as c:
        production = stage.score_pair(a, c, kind="np01_vs_cflhalf", step_s=.01, threshold=.05)
        spatial = stage.score_pair(b, c, kind="np06_vs_cflhalf", step_s=.01, threshold=.01,
                                   same_ids=True)
    result = dict(
        schema="f3.nopen.resolution_diagnostic.v1", status="completed",
        created_at_utc=utc_now(), case_ids=[NP01_ID, BASE_ID, DIAGNOSTIC_ID],
        scope=("Root-cause diagnostic only; no qualification gate, production resolution, "
               "endpoint or domain status is changed."),
        native_timestep={name: timestep_evidence(name) for name in (BASE_ID, DIAGNOSTIC_ID)},
        panels={"np01_vs_cflhalf": _slim(production), "np06_vs_cflhalf": _slim(spatial)},
        source_audit_sha256={name: sha256(OUT / (name + "-AUDIT.json"))
                             for name in (NP01_ID, BASE_ID, DIAGNOSTIC_ID)},
        scorer_sha256=sha256(Path(__file__)), stage_scorer_sha256=sha256(LAB / "scripts/f3_nopen_stage_score.py"),
    )
    atomic_json(OUTPUT, result)
    print(json.dumps({"output": str(OUTPUT), "panels": result["panels"],
                      "native_dt": result["native_timestep"]}, indent=2), flush=True)
    return result


if __name__ == "__main__":
    run()
