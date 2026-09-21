#!/usr/bin/env python3
"""Root-review the second F5 geometry repair hypothesis.

The v3 preflight proved the explicit-void precursor did not remove one
fluid-only frame-0 block penetration.  This receipt binds a distinct v4 input
identity that follows the official GenCase example literally: each watertight
STL is drawn once with ``setmkbound`` and ``autofill=true``.  It authorizes one
fresh CPU/native preflight only; no solver, GPU, queue, ledger, registry, or
matrix action is opened.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1"
PROPOSAL = ROOT / "geometry-repair-proposal-audit-v1.json"
V3_PREFLIGHT = ROOT / "preflight-v3/preflight.json"
OFFICIAL_CHRONO = LAB / "vendor/official/DualSPHysics_v5.4/examples/chrono/11_CurrentWheelPulley/CaseCurrentWheel_Def.xml"
OFFICIAL_TEMPLATE = LAB / "vendor/official/DualSPHysics_v5.4/doc/xml_format/GenCase_CaseTemplate.xml"
IMPLEMENTATION = LAB / "scripts/f5_wave_runup_geometry_autofill_bound_root_review_v1.py"
TEST = LAB / "tests/test_f5_wave_runup_geometry_autofill_bound_root_review_v1.py"
OUTPUT = ROOT / "autofill-bound-root-review-v1.json"
INPUT = ROOT / "v4-input"
PREFLIGHT = ROOT / "preflight-v4"
CASE_ID = "F5_wave_runup_q0p50_dp0p0075_geomrepair_v4"
DEFINITION = INPUT / f"{CASE_ID}_Def.xml"
MOTION = INPUT / "Mov_piston_q0p50_scaled_geomrepair_v4.dat"
SLOPE = INPUT / "Slope_geomrepair_v4.stl"
BLOCKS = INPUT / "Blocks_3D_scaled_geomrepair_v4.stl"
PREFLIGHT_STEM_REL = "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/preflight-v4/generated/F5_wave_runup_q0p50_dp0p0075_geomrepair_v4"
ANCHOR_ROOT_REL = "campaigns/core-v1/runtime/attempts/f5-wave-runup-third-t1-q05-dp0075-geomrepair-v4-protected-anchor/<root-approved-attempt-id>"
ANCHOR_STEM_REL = "F5_wave_runup_q0p50_dp0p0075_geomrepair_v4_anchor"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _verify_prior() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proposal = load(PROPOSAL)
    prior = load(V3_PREFLIGHT)
    chrono = ET.parse(OFFICIAL_CHRONO).getroot()
    if proposal.get("schema") != "core.f5.third_t1.geometry_repair_proposal_audit.v1" or proposal.get("qualification_claim") != "none":
        raise ValueError("F5 proposal is not zero-credit")
    if prior.get("schema") != "core.f5.third_t1.preflight.v1" or prior.get("status") != "cpu_native_preflight_failed_geometry_repair_gate":
        raise ValueError("v3 failure evidence is not the expected geometry-gate failure")
    if prior.get("qualification_claim") != "none" or prior.get("qualified") is not False or prior.get("matrix_credit") != 0:
        raise ValueError("v3 failure carries scientific credit")
    gates = prior.get("hard_gates", {})
    if gates.get("gencase_return_code_zero") is not True or gates.get("frame0_fluid_endpoint_inside_blocks") is not False:
        raise ValueError("v3 failure is not bound to the block endpoint gate")
    if prior.get("geometry_repair", {}).get("blocks_endpoint_inside_count") != 1:
        raise ValueError("v3 failure count changed")
    if prior.get("execution_controls", {}).get("solver_invoked") is not False or prior.get("execution_controls", {}).get("gpu_started") is not False:
        raise ValueError("v3 failure claims solver/GPU execution")
    example = chrono.find(".//drawfilestl[@autofill='true']")
    if example is None:
        raise ValueError("official autofill example is missing")
    return proposal, prior, {"chrono": bind(OFFICIAL_CHRONO, "official setmkbound/autofill example"),
                             "template": bind(OFFICIAL_TEMPLATE, "official GenCase syntax template")}


def _verify_static() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    evidence = _verify_prior()
    if OUTPUT.exists() and OUTPUT.stat().st_size > 0:
        raise FileExistsError(f"v4 root-review receipt already exists: {OUTPUT}")
    if PREFLIGHT.exists() and any(PREFLIGHT.iterdir()):
        raise ValueError("v4 preflight output already exists")
    return evidence


def build_review() -> dict[str, Any]:
    proposal, prior, official = _verify_static()
    return {
        "schema": "core.f5.third_t1.geometry_autofill_bound_root_review_receipt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_id": "f5-wave-runup-third-t1-geometry-autofill-bound-root-review-v1",
        "status": "authorized_one_fresh_v4_cpu_native_preflight_only",
        "root_review_only": True,
        "family": "F5",
        "scope_id": "F5_prescribed_wave_runup_x_v1",
        "revision_id": "F5_piston_amplitude_runup_geomrepair_v4",
        "candidate_case_id": CASE_ID,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "denominator_rows": 15,
        "review_decision": {
            "authorized_now": True,
            "decision": "authorize_exactly_one_fresh_v4_cpu_native_preflight_after_autofill_bound_materialization",
            "authorized_action": "write_v4_inputs_then_run_exactly_one_fresh_cpu_gencase_native_decode",
            "authorized_definition_materialization": True,
            "authorized_cpu_native_preflight": True,
            "authorized_solver": False,
            "authorized_gpu": False,
            "authorized_queue": False,
            "authorized_registry": False,
            "authorized_ledger": False,
            "authorized_matrix": False,
            "exactly_one_preflight": True,
            "reason": "v3 failed one exact fluid-only block endpoint gate; the official GenCase example directly binds setmkbound followed by drawfilestl autofill=true, giving a distinct materialization hypothesis",
            "failure_policy": "v4 failure remains zero credit and cannot be retried with the same input; a solver anchor requires a separate root review",
        },
        "review_inputs": {
            "proposal": bind(PROPOSAL, "F5 geometry proposal-only audit"),
            "v3_preflight": bind(V3_PREFLIGHT, "v3 exact CPU/native geometry-gate failure"),
            "official_chrono_example": official["chrono"],
            "official_template": official["template"],
        },
        "fresh_identity": {
            "case_id": CASE_ID,
            "definition": rel(DEFINITION),
            "motion": rel(MOTION),
            "slope_asset": rel(SLOPE),
            "blocks_asset": rel(BLOCKS),
            "preflight_output_prefix": PREFLIGHT_STEM_REL,
            "solver_anchor_attempt_root": ANCHOR_ROOT_REL,
            "solver_output_stem": ANCHOR_STEM_REL,
            "old_v3_input_reused": False,
            "old_v3_generated_reused": False,
            "qualification_inheritance": False,
        },
        "recipe": {
            "identity": "F5_geomrepair_v4_autofill_bound",
            "commands_in_order": [
                "setmkbound mk=40",
                "drawfilestl Slope_geomrepair_v4.stl autofill=true with unchanged transform",
                "setmkbound mk=50",
                "drawfilestl Blocks_3D_scaled_geomrepair_v4.stl autofill=true with unchanged transform",
                "setmkfluid mk=0; fillbox mode=void using unchanged v2 fluid box",
            ],
            "physical_boundary_policy": "one official autofill draw per watertight STL; no separate non-autofill redraw and no threshold relaxation",
            "preserved_parameters": {"q": 0.5, "piston_scale": 1.0, "dp_m": 0.0075, "time_max_s": 16.0, "output_dt_s": 0.02,
                                      "slope_transform": {"move_m": [5.95, 0.37, 0.0], "rotate_z_deg": -90.0},
                                      "blocks_transform": {"move_m": [5.95, 0.37, 0.0], "rotate_z_deg": -90.0}},
        },
        "hard_preflight_gates": {
            "gencase_return_code_zero": True,
            "generated_xml_and_native_bi4_present": True,
            "unique_ids_and_generated_native_counts_aligned": True,
            "finite_native_arrays": True,
            "mass_metadata_match": True,
            "geometry_static_integrity": True,
            "frame0_fluid_endpoint_inside_slope": {"required_value": 0, "scope": "fluid-only", "tolerance_m": 1e-8},
            "frame0_fluid_endpoint_inside_blocks": {"required_value": 0, "scope": "fluid-only", "tolerance_m": 1e-8},
            "full_window_and_events": "not applicable until separately reviewed solver anchor",
        },
        "fixed_denominator": {"planned_rows": 15, "all_rows_retained": True, "partial_credit": False, "same_input_retry": False, "qualification_credit": 0},
        "execution_controls": {"review_only": True, "definition_written_by_review": False, "gencase_invoked": False, "native_decode_invoked": False,
                               "solver_invoked": False, "gpu_started": False, "queue_mutation": 0, "ledger_mutation": 0,
                               "registry_mutation": 0, "matrix_mutation": 0, "qualification_credit": 0},
        "hash_bindings": {"implementation": bind(IMPLEMENTATION, "v4 autofill-bound root-review implementation"),
                          "test": bind(TEST, "v4 autofill-bound root-review regression test"),
                          "proposal": bind(PROPOSAL, "F5 geometry proposal"), "v3_preflight": bind(V3_PREFLIGHT, "v3 failure evidence"),
                          "official_chrono_example": official["chrono"], "official_template": official["template"]},
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != "core.f5.third_t1.geometry_autofill_bound_root_review_receipt.v1" or value.get("status") != "authorized_one_fresh_v4_cpu_native_preflight_only":
        raise ValueError("wrong v4 root-review receipt")
    decision = value.get("review_decision", {})
    if decision.get("authorized_cpu_native_preflight") is not True or decision.get("exactly_one_preflight") is not True:
        raise ValueError("v4 preflight is not authorized exactly once")
    for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_registry", "authorized_ledger", "authorized_matrix"):
        if decision.get(key) is not False:
            raise ValueError(f"forbidden v4 authorization is open: {key}")
    if value.get("matrix_credit") != 0 or value.get("denominator_rows") != 15:
        raise ValueError("v4 denominator/credit changed")
    for item in value.get("hash_bindings", {}).values():
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise ValueError(f"stale v4 root-review binding: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        value = verify(args.output)
    else:
        value = build_review()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        verify(args.output)
    print(json.dumps({"status": value["status"], "output": rel(args.output), "sha256": sha256(args.output),
                      "solver_invoked": False, "gpu_started": False, "queue_mutation": 0, "matrix_credit": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
