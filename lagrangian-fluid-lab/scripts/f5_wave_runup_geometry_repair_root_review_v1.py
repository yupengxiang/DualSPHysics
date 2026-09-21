#!/usr/bin/env python3
"""Review the F5 geometry repair and authorize one fresh CPU/native preflight.

This is a static, read-only root review.  It binds the proposed v3 identity,
the official GenCase syntax evidence, and the prior v2 zero-credit evidence.
It does not materialize inputs, invoke GenCase or the decoder, start a solver,
touch CUDA, submit a queue job, or mutate the registry, ledger, or matrix.
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
PROPOSAL = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/geometry-repair-proposal-audit-v1.json"
PRIOR_ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-root-review-v2.json"
PRIOR_PREFLIGHT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-v2/preflight.json"
PRIOR_BOUNDARY = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-boundary-semantics-audit-v1.json"
PRIOR_V2_DEFINITION = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/F5_wave_runup_q0p50_dp0p0075_Def.xml"
OFFICIAL_TEMPLATE = LAB / "vendor/official/DualSPHysics_v5.4/doc/xml_format/GenCase_CaseTemplate.xml"
OFFICIAL_CHRONO = LAB / "vendor/official/DualSPHysics_v5.4/examples/chrono/11_CurrentWheelPulley/CaseCurrentWheel_Def.xml"
IMPLEMENTATION = LAB / "scripts/f5_wave_runup_geometry_repair_root_review_v1.py"
TEST = LAB / "tests/test_f5_wave_runup_geometry_repair_root_review_v1.py"
OUTPUT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/root-review-receipt-v1.json"
INPUT_DIR = OUTPUT.parent / "input"
PREFLIGHT_DIR = OUTPUT.parent / "preflight-v3"
CASE_ID = "F5_wave_runup_q0p50_dp0p0075_geomrepair_v3"
DEFINITION = INPUT_DIR / f"{CASE_ID}_Def.xml"
MOTION = INPUT_DIR / "Mov_piston_q0p50_scaled_geomrepair_v3.dat"
SLOPE = INPUT_DIR / "Slope_geomrepair_v3.stl"
BLOCKS = INPUT_DIR / "Blocks_3D_scaled_geomrepair_v3.stl"
PREFLIGHT_STEM_REL = "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/preflight-v3/generated/F5_wave_runup_q0p50_dp0p0075_geomrepair_v3"
ANCHOR_ROOT_REL = "campaigns/core-v1/runtime/attempts/f5-wave-runup-third-t1-q05-dp0075-geomrepair-v3-protected-anchor/<root-approved-attempt-id>"
ANCHOR_STEM_REL = "F5_wave_runup_q0p50_dp0p0075_geomrepair_v3_anchor"
EXPECTED_ROWS = 15
TIME_MAX_S = 16.0
OUTPUT_DT_S = 0.02


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


def _verify_binding(item: dict[str, Any], label: str) -> Path:
    path = (LAB / item["path"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
        raise ValueError(f"stale {label} binding: {path}")
    return path


def _proposal_checks(proposal: dict[str, Any]) -> None:
    if proposal.get("schema") != "core.f5.third_t1.geometry_repair_proposal_audit.v1":
        raise ValueError("wrong geometry-repair proposal schema")
    if proposal.get("status") != "proposal_only_root_review_required" or proposal.get("qualification_claim") != "none":
        raise ValueError("geometry proposal is not zero-credit and proposal-only")
    fixed = proposal.get("fixed_matrix_contract", {})
    if fixed.get("denominator_rows") != EXPECTED_ROWS or fixed.get("same_input_retry") is not False:
        raise ValueError("fixed denominator or retry policy changed")
    if fixed.get("matrix_submission_authorized") is not False or fixed.get("qualification_credit") != 0:
        raise ValueError("proposal opens matrix or qualification credit")
    identity = proposal.get("input_output_identity", {})
    fresh = identity.get("new_input_identity", {})
    expected = {
        "case_id": CASE_ID,
        "definition": rel(DEFINITION),
        "motion": rel(MOTION),
        "slope_asset": rel(SLOPE),
        "blocks_asset": rel(BLOCKS),
    }
    for key, value in expected.items():
        if fresh.get(key) != value:
            raise ValueError(f"proposal identity mismatch for {key}")
    if fresh.get("materialized") is not False or fresh.get("old_generated_input_reused") is not False:
        raise ValueError("proposal identity is already materialized or reuses old input")
    output = identity.get("new_output_identity", {})
    if output.get("preflight_output_prefix") != PREFLIGHT_STEM_REL or output.get("solver_output_stem") != ANCHOR_STEM_REL:
        raise ValueError("proposal output identity mismatch")
    if output.get("old_output_reuse_forbidden") is not True:
        raise ValueError("old output reuse is not forbidden")
    next_step = proposal.get("next_step", {})
    if next_step.get("decision") != "root_review_required" or next_step.get("no_action_until_review") is not True:
        raise ValueError("proposal does not require a fresh root review")


def _verify_prior_evidence(proposal: dict[str, Any]) -> dict[str, Any]:
    prior_root = load(PRIOR_ROOT)
    prior_preflight = load(PRIOR_PREFLIGHT)
    prior_boundary = load(PRIOR_BOUNDARY)
    if prior_root.get("schema") != "core.f5.third_t1.preflight_root_review_receipt.v2":
        raise ValueError("prior v2 root review schema changed")
    decision = prior_root.get("review_decision", {})
    if prior_root.get("status") != "authorized_one_fresh_cpu_native_preflight_only" or decision.get("authorized_solver") is not False:
        raise ValueError("prior v2 root review is not CPU/native-only")
    if any(decision.get(key) for key in ("authorized_gpu", "authorized_queue", "authorized_matrix")):
        raise ValueError("prior v2 root review opens a forbidden path")
    if prior_preflight.get("qualification_claim") != "none" or prior_preflight.get("qualified") is not False or prior_preflight.get("matrix_credit") != 0:
        raise ValueError("prior v2 preflight carries scientific credit")
    controls = prior_preflight.get("execution_controls", {})
    if controls.get("solver_invoked") is not False or controls.get("gpu_started") is not False:
        raise ValueError("prior v2 preflight claims solver/GPU execution")
    if prior_boundary.get("qualification_claim") != "none":
        raise ValueError("prior boundary audit carries scientific credit")
    for item in proposal.get("reviewed_artifacts", []):
        if not isinstance(item, dict) or item.get("path", "").startswith("reports/"):
            continue
        path = LAB / item["path"]
        if not path.is_file() or sha256(path) != item.get("sha256"):
            raise ValueError(f"proposal reviewed artifact is stale: {path}")
    return {"root": prior_root, "preflight": prior_preflight, "boundary": prior_boundary}


def _verify_syntax_and_prior_definition() -> dict[str, Any]:
    template_text = OFFICIAL_TEMPLATE.read_text(encoding="utf-8", errors="replace")
    chrono_text = OFFICIAL_CHRONO.read_text(encoding="utf-8", errors="replace")
    if '<drawfilestl file="File.stl" autofill="true" />' not in template_text:
        raise ValueError("official GenCase template does not bind drawfilestl autofill syntax")
    if '<setmkvoid />' not in template_text:
        raise ValueError("official GenCase template does not bind setmkvoid syntax")
    chrono_root = ET.parse(OFFICIAL_CHRONO).getroot()
    autofill = chrono_root.find(".//drawfilestl[@autofill='true']")
    if autofill is None:
        raise ValueError("official GenCase example does not use autofill=true")
    root = ET.parse(PRIOR_V2_DEFINITION).getroot()
    commands = root.findall("./casedef/geometry/commands/mainlist/*")
    source_draws = [node for node in commands if node.tag == "drawfilestl" and node.get("file") in {"Slope.stl", "Blocks_3D_scaled.stl"}]
    if len(source_draws) != 2 or any(node.get("autofill") is not None for node in source_draws):
        raise ValueError("prior v2 source STL draw identity changed")
    if any(node.tag == "setmkvoid" for node in commands):
        raise ValueError("prior v2 unexpectedly contains the proposed void precursor")
    return {
        "template": bind(OFFICIAL_TEMPLATE, "official GenCase XML template syntax"),
        "chrono_example": bind(OFFICIAL_CHRONO, "official GenCase autofill example"),
        "prior_definition": bind(PRIOR_V2_DEFINITION, "prior v2 Definition audited for missing precursor"),
        "autofill_literal": '<drawfilestl file="<asset>" autofill="true"> ... transforms ... </drawfilestl>',
        "void_literal": "<setmkvoid /> before each transformed autofill STL draw",
    }


def _verify_static_inputs() -> dict[str, Any]:
    proposal = load(PROPOSAL)
    _proposal_checks(proposal)
    prior = _verify_prior_evidence(proposal)
    syntax = _verify_syntax_and_prior_definition()
    if OUTPUT.exists() and OUTPUT.stat().st_size > 0:
        # Rebuilding an existing receipt is allowed only through verify; the
        # CLI refuses accidental replacement by default.
        raise FileExistsError(f"root-review receipt already exists: {OUTPUT}")
    # The receipt may be regenerated after materialization solely to refresh
    # implementation/test hash bindings.  It still refuses to reopen a
    # preflight output; the input contract and its hashes are checked by the
    # dedicated preflight root contract.
    if PREFLIGHT_DIR.exists() and any(PREFLIGHT_DIR.iterdir()):
        raise ValueError("fresh v3 preflight output is already materialized")
    return {"proposal": proposal, "prior": prior, "syntax": syntax}


def _recipe() -> dict[str, Any]:
    return {
        "identity": "F5_geomrepair_v3_explicit_void_precursor",
        "purpose": "materialize closed STL interiors as void before redrawing the unchanged physical boundary faces",
        "commands_in_order": [
            "setmkvoid",
            "drawfilestl Slope_geomrepair_v3.stl autofill=true with drawmove(5.95,0.37,0) and drawrotate(0,0,-90)",
            "setmkbound mk=40",
            "drawfilestl Slope_geomrepair_v3.stl without autofill with the unchanged transform",
            "setmkvoid",
            "drawfilestl Blocks_3D_scaled_geomrepair_v3.stl autofill=true with drawmove(5.95,0.37,0) and drawrotate(0,0,-90)",
            "setmkbound mk=50",
            "drawfilestl Blocks_3D_scaled_geomrepair_v3.stl without autofill with the unchanged transform",
            "setmkfluid mk=0; fillbox mode=void using the unchanged v2 fluid box",
        ],
        "source_asset_policy": "byte-identical copies receive new v3 names; no derived shell, transform, threshold, or event change is authorized",
        "preserved_parameters": {"q": 0.5, "piston_scale": 1.0, "dp_m": 0.0075, "time_max_s": TIME_MAX_S, "output_dt_s": OUTPUT_DT_S,
                                  "slope_transform": {"move_m": [5.95, 0.37, 0.0], "rotate_z_deg": -90.0},
                                  "blocks_transform": {"move_m": [5.95, 0.37, 0.0], "rotate_z_deg": -90.0}},
        "semantic_limits": [
            "The void precursor is a hypothesis test, not evidence of qualification.",
            "Exact fluid-only endpoint and saved-chord gates remain hard; contact-band diagnostics cannot waive them.",
            "A successful preflight authorizes no solver anchor; a separate root review is required after full input/native evidence.",
        ],
    }


def build_review() -> dict[str, Any]:
    evidence = _verify_static_inputs()
    return {
        "schema": "core.f5.third_t1.geometry_repair_root_review_receipt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_id": "f5-wave-runup-third-t1-geometry-repair-root-review-v1",
        "status": "authorized_one_fresh_cpu_native_preflight_only",
        "root_review_only": True,
        "family": "F5",
        "scope_id": "F5_prescribed_wave_runup_x_v1",
        "revision_id": "F5_piston_amplitude_runup_geomrepair_v3",
        "candidate_case_id": CASE_ID,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "denominator_rows": EXPECTED_ROWS,
        "review_decision": {
            "authorized_now": True,
            "decision": "authorize_exactly_one_fresh_cpu_native_preflight_after_v3_materialization",
            "authorized_action": "write_v3_inputs_then_run_exactly_one_fresh_cpu_gencase_native_decode",
            "authorized_definition_materialization": True,
            "authorized_cpu_native_preflight": True,
            "authorized_solver": False,
            "authorized_gpu": False,
            "authorized_queue": False,
            "authorized_registry": False,
            "authorized_ledger": False,
            "authorized_matrix": False,
            "exactly_one_preflight": True,
            "reason": "official GenCase template and example bind setmkvoid/autofill syntax; v2 zero-credit evidence shows the unqualified geometry defect; the v3 input and output identity are new",
            "failure_policy": "any v3 hard-gate failure retains zero credit and cannot be retried with the same input; solver anchor requires a later review",
        },
        "review_inputs": {
            "proposal": bind(PROPOSAL, "F5 geometry repair proposal-only audit"),
            "prior_root_review": bind(PRIOR_ROOT, "prior v2 CPU/native root review"),
            "prior_preflight": bind(PRIOR_PREFLIGHT, "prior v2 static preflight"),
            "prior_boundary_audit": bind(PRIOR_BOUNDARY, "prior v2 boundary semantics audit"),
            "official_template": evidence["syntax"]["template"],
            "official_chrono_example": evidence["syntax"]["chrono_example"],
            "prior_definition": evidence["syntax"]["prior_definition"],
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
            "old_generated_input_reused": False,
            "old_trajectory_reused": False,
            "qualification_inheritance": False,
        },
        "recipe": _recipe(),
        "hard_preflight_gates": {
            "gencase_return_code_zero": "required",
            "generated_xml_and_native_bi4_present": "required",
            "unique_ids_and_generated_native_counts_aligned": "required",
            "finite_native_arrays": "required",
            "mass_metadata_match": "required",
            "geometry_static_integrity": "required",
            "frame0_fluid_endpoint_inside_slope": {"required_value": 0, "scope": "fluid-only", "tolerance_m": 1.0e-8},
            "frame0_fluid_endpoint_inside_blocks": {"required_value": 0, "scope": "fluid-only", "tolerance_m": 1.0e-8},
            "event_and_full_window": "not applicable until a separately reviewed solver anchor",
        },
        "fixed_denominator": {
            "planned_rows": EXPECTED_ROWS,
            "all_rows_retained": True,
            "partial_credit": False,
            "same_input_retry": False,
            "qualification_credit": 0,
        },
        "execution_controls": {
            "review_only": True,
            "definition_written_by_review": False,
            "motion_written_by_review": False,
            "gencase_invoked": False,
            "native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
        },
        "hash_bindings": {
            "implementation": bind(IMPLEMENTATION, "F5 geometry repair root-review implementation"),
            "test": bind(TEST, "F5 geometry repair root-review regression test"),
            "proposal": bind(PROPOSAL, "F5 geometry repair proposal"),
            "official_template": evidence["syntax"]["template"],
            "official_chrono_example": evidence["syntax"]["chrono_example"],
        },
    }


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != "core.f5.third_t1.geometry_repair_root_review_receipt.v1":
        raise ValueError("wrong geometry repair root-review schema")
    if value.get("status") != "authorized_one_fresh_cpu_native_preflight_only":
        raise ValueError("root review is not CPU/native-only")
    decision = value.get("review_decision", {})
    if decision.get("authorized_cpu_native_preflight") is not True or decision.get("exactly_one_preflight") is not True:
        raise ValueError("root review does not authorize exactly one preflight")
    for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_registry", "authorized_ledger", "authorized_matrix"):
        if decision.get(key) is not False:
            raise ValueError(f"forbidden authorization is open: {key}")
    if value.get("denominator_rows") != EXPECTED_ROWS or value.get("matrix_credit") != 0:
        raise ValueError("root review denominator/credit changed")
    if value.get("fixed_denominator", {}).get("same_input_retry") is not False:
        raise ValueError("same-input retry is not closed")
    controls = value.get("execution_controls", {})
    for key in ("gencase_invoked", "native_decode_invoked", "solver_invoked", "gpu_started"):
        if controls.get(key) is not False:
            raise ValueError(f"root review claims execution: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "matrix_mutation", "qualification_credit"):
        if controls.get(key) != 0:
            raise ValueError(f"root review changed protected state: {key}")
    for item in value.get("hash_bindings", {}).values():
        _verify_binding(item, "root-review")
    if value.get("fresh_identity", {}).get("case_id") != CASE_ID:
        raise ValueError("fresh case identity changed")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        value = verify(args.output)
    else:
        value = build_review()
        write_json(args.output, value)
        verify(args.output)
    print(json.dumps({"status": value["status"], "output": rel(args.output), "sha256": sha256(args.output),
                      "gencase_invoked": False, "native_decode_invoked": False, "solver_invoked": False,
                      "gpu_started": False, "queue_mutation": 0, "matrix_credit": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
