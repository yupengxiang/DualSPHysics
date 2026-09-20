#!/usr/bin/env python3
"""Materialize the v2 F5 input with adjacent STL assets.

v1 reached GenCase but stopped before decoding because the Definition's
relative ``Slope.stl`` asset was only stored below a provenance directory.
This repair uses a new input/output identity and places every Definition-
referenced asset beside the Definition.  It does not reopen v1 products.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any


LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))
from scripts.f5_wave_runup_definition_writer_v1 import (  # noqa: E402
    OFFICIAL,
    PROPOSAL,
    ROOT_REVIEW,
    SCALE,
    Q,
    DP,
    TMAX,
    TOUT,
    GAUGE_CADENCE,
    MOTION_OUTPUT,
    DEFINITION_OUTPUT,
    bind,
    load,
    sha256,
    write_definition,
    write_motion,
)


V1_PREFLIGHT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v1/preflight-v1/preflight.json"
OUTPUT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
CONTRACT = OUTPUT / "fresh-definition-contract-v2.json"


def build() -> dict[str, Any]:
    proposal = load(PROPOSAL)
    review = load(ROOT_REVIEW)
    v1 = load(V1_PREFLIGHT)
    assert proposal["schema"] == "core.f5.third_t1.proposal_audit.v1"
    assert review["schema"] == "core.f5.third_t1.root_review_receipt.v1"
    assert review["review_decision"]["authorized_action"] == "write_one_fresh_definition_and_scaled_motion_file"
    assert v1["status"] == "cpu_native_preflight_failed_hard_audit"
    assert v1.get("failure_reason") == "GenCase returned nonzero"
    if OUTPUT.exists():
        raise FileExistsError(f"v2 output already exists: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    motion_path = OUTPUT / MOTION_OUTPUT
    definition_path = OUTPUT / DEFINITION_OUTPUT
    motion = write_motion(OFFICIAL / "Mov_piston.dat", motion_path, SCALE)
    definition = write_definition(OFFICIAL / "CaseWaveRunup_Def.xml", definition_path, motion_path.name)
    copied_assets = []
    for name in ("Slope.stl", "Blocks_3D_scaled.stl", "wg1234.txt", "EXP_CaseWaveRunup_CIEMito.txt"):
        target = OUTPUT / name
        shutil.copy2(OFFICIAL / name, target)
        copied_assets.append(bind(target, "Definition-adjacent F5 source asset"))
    source_asset_names = {"Slope.stl", "Blocks_3D_scaled.stl", motion_path.name}
    referenced = {"Slope.stl", "Blocks_3D_scaled.stl", motion_path.name}
    assert referenced <= {path.name for path in OUTPUT.iterdir() if path.is_file()}
    result = {
        "schema": "core.f5.third_t1.definition_materialization.v2",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "definition_written_preflight_pending",
        "qualification_claim": "none",
        "candidate": {"family": "F5", "scope_id": "F5_prescribed_wave_runup_x_v1", "revision_id": "F5_piston_amplitude_runup_v2",
                      "q": Q, "piston_scale": SCALE, "dp_m": DP, "case_id": "F5_wave_runup_q0p50_dp0p0075_v2"},
        "repair_lineage": {
            "prior_v1_failure": bind(V1_PREFLIGHT, "v1 GenCase asset-closure failure"),
            "failure_class": "definition_relative_asset_not_adjacent",
            "repair_hypothesis": "place Slope.stl, Blocks_3D_scaled.stl and motion beside the fresh Definition",
            "prior_output_reused": False,
            "prior_generated_xml_reused": False,
            "prior_bi4_reused": False,
            "prior_trajectory_reused": False,
        },
        "authorization": {
            "root_review": bind(ROOT_REVIEW, "F5 initial root review"),
            "authorized_action": "write_one_fresh_definition_and_scaled_motion_file",
            "gencase_authorized": False,
            "native_decode_authorized": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
        },
        "fresh_identity": {
            "definition": definition,
            "motion": motion,
            "definition_adjacent_assets": copied_assets,
            "required_relative_assets": sorted(source_asset_names),
            "output_directory": str(OUTPUT.resolve().relative_to(LAB)),
        },
        "fixed_contract": {"denominator_rows": 15, "time_max_s": TMAX, "output_interval_s": TOUT,
                           "gauge_interval_s": GAUGE_CADENCE, "event_window_required": True,
                           "zero_credit_until_cpu_native_and_solver_reviews": True},
        "implementation": bind(Path(__file__), "F5 v2 Definition writer"),
        "execution_controls": {"definition_written": True, "motion_written": True, "gencase_invoked": False,
                               "native_decode_invoked": False, "solver_invoked": False, "gpu_started": False,
                               "matrix_materialized": False, "matrix_submitted": False, "qualification_credit": 0},
    }
    CONTRACT.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        value = load(CONTRACT)
        print(json.dumps({"status": value["status"], "contract": str(CONTRACT), "sha256": sha256(CONTRACT)}, indent=2))
        return 0
    value = build()
    print(json.dumps({"status": value["status"], "output": str(OUTPUT), "contract_sha256": sha256(CONTRACT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
