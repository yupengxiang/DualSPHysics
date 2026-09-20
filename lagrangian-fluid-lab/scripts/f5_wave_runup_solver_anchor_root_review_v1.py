#!/usr/bin/env python3
"""Build and verify the F5 v2 solver-anchor root-review contract.

The review is deliberately narrow: it may authorize exactly one protected GPU
solver anchor, but it never submits a queue job, starts a solver, touches a
CUDA device, or mutates the ledger, registry, or qualification matrix.  The
job specification is a future-runtime description bound to a fresh output
stem; the accompanying worker is a static guard only.
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
ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
PROPOSAL = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1-proposal-audit-v1.json"
V2_REVIEW = ROOT / "preflight-root-review-v2.json"
CONTRACT = ROOT / "fresh-definition-contract-v2.json"
PREFLIGHT = ROOT / "preflight-v2/preflight.json"
BOUNDARY_AUDIT = ROOT / "preflight-boundary-semantics-audit-v1.json"
DEFINITION = ROOT / "F5_wave_runup_q0p50_dp0p0075_Def.xml"
MOTION = ROOT / "Mov_piston_q0p50_scaled.dat"
REVIEW_OUTPUT = ROOT / "solver-anchor-root-review-v1.json"
JOB_OUTPUT = ROOT / "solver-anchor-job-spec-v1.json"
WORKER = LAB / "scripts/f5_wave_runup_solver_anchor_worker_v1.py"
RUNTIME_WORKER = LAB / "scripts/f5_wave_runup_solver_anchor_runtime_v1.py"
IMPLEMENTATION = LAB / "scripts/f5_wave_runup_solver_anchor_root_review_v1.py"
TEST = LAB / "tests/test_f5_wave_runup_solver_anchor_root_review_v1.py"
SOLVER = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"

CASE_ID = "F5_wave_runup_q0p50_dp0p0075_v2"
ANCHOR_STEM_REL = (
    "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/"
    "solver-anchor-v1/generated/F5_wave_runup_q0p50_dp0p0075_v2_anchor"
)
ANCHOR_STEM = LAB / ANCHOR_STEM_REL
EXPECTED_ROWS = 15
TIME_MAX_S = 16.0
OUTPUT_INTERVAL_S = 0.02


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


def _bound_path(item: dict[str, Any]) -> Path:
    return (LAB / item["path"]).resolve()


def _verify_binding(item: dict[str, Any], label: str) -> Path:
    path = _bound_path(item)
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
        raise ValueError(f"stale {label} hash binding: {path}")
    return path


def _xml_parameters(root: ET.Element) -> dict[str, str | None]:
    return {node.get("key"): node.get("value") for node in root.findall("./execution/parameters/parameter")}


def _motion_rows() -> list[list[str]]:
    return [
        line.split()
        for line in MOTION.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _verify_static_evidence() -> dict[str, Any]:
    """Verify every preflight and input artifact used by the anchor review."""

    proposal = load(PROPOSAL)
    v2_review = load(V2_REVIEW)
    contract = load(CONTRACT)
    preflight = load(PREFLIGHT)
    boundary = load(BOUNDARY_AUDIT)

    if proposal.get("schema") != "core.f5.third_t1.proposal_audit.v1":
        raise ValueError("wrong F5 proposal schema")
    if proposal.get("status") != "proposal_only_root_review_required" or proposal.get("qualification_claim") != "none":
        raise ValueError("proposal is not an unqualified root-review-only record")
    design = proposal.get("fixed_scope_design", {})
    if design.get("cell_count") != EXPECTED_ROWS or design.get("registered_window", {}).get("time_max_s") != TIME_MAX_S:
        raise ValueError("proposal denominator/window changed")
    if design.get("registered_window", {}).get("output_interval_s") != OUTPUT_INTERVAL_S:
        raise ValueError("proposal output cadence changed")
    if design.get("registered_window", {}).get("event_completion_required") is not True:
        raise ValueError("proposal does not require event completion")

    decision = v2_review.get("review_decision", {})
    if v2_review.get("schema") != "core.f5.third_t1.preflight_root_review_receipt.v2":
        raise ValueError("wrong F5 v2 preflight root-review schema")
    if v2_review.get("status") != "authorized_one_fresh_cpu_native_preflight_only":
        raise ValueError("v2 preflight root review is not closed")
    if decision.get("authorized_now") is not True or decision.get("authorized_solver") is not False:
        raise ValueError("v2 root review is not CPU/native-only")
    if any(decision.get(key) for key in ("authorized_gpu", "authorized_queue", "authorized_matrix")):
        raise ValueError("v2 root review opens a forbidden path")

    if contract.get("schema") != "core.f5.third_t1.definition_materialization.v2":
        raise ValueError("wrong F5 v2 definition contract schema")
    if contract.get("qualification_claim") != "none":
        raise ValueError("definition contract carries scientific credit")
    candidate = contract.get("candidate", {})
    if (
        candidate.get("family") != "F5"
        or candidate.get("scope_id") != "F5_prescribed_wave_runup_x_v1"
        or candidate.get("q") != 0.5
        or candidate.get("dp_m") != 0.0075
        or candidate.get("case_id") != CASE_ID
    ):
        raise ValueError("v2 candidate identity changed")
    fixed = contract.get("fixed_contract", {})
    if fixed.get("denominator_rows") != EXPECTED_ROWS:
        raise ValueError("fixed denominator is not 15 rows")
    if fixed.get("time_max_s") != TIME_MAX_S or fixed.get("output_interval_s") != OUTPUT_INTERVAL_S:
        raise ValueError("fixed time/cadence contract changed")
    if fixed.get("event_window_required") is not True or fixed.get("zero_credit_until_cpu_native_and_solver_reviews") is not True:
        raise ValueError("definition contract does not retain the hard event/credit boundary")

    authorization = preflight.get("authorization", {})
    if preflight.get("schema") != "core.f5.third_t1.preflight.v1" or preflight.get("status") != "cpu_native_preflight_passed_static_only":
        raise ValueError("v2 CPU/native preflight is not a static pass")
    if preflight.get("preflight_pass") is not True or preflight.get("qualified") is not False or preflight.get("matrix_credit") != 0:
        raise ValueError("v2 preflight carries a qualification claim")
    if authorization.get("path") != rel(V2_REVIEW) or authorization.get("sha256") != sha256(V2_REVIEW):
        raise ValueError("v2 preflight is not bound to the current v2 root review")
    controls = preflight.get("execution_controls", {})
    if controls.get("solver_invoked") is not False or controls.get("gpu_started") is not False:
        raise ValueError("v2 preflight has runtime execution evidence")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "qualification_credit"):
        if controls.get(key) != 0:
            raise ValueError(f"v2 preflight changed protected state: {key}")
    hard = preflight.get("hard_gates", {})
    for key in (
        "gencase_return_code_zero",
        "generated_xml_present",
        "native_bi4_present",
        "id_unique_and_xml_aligned",
        "finite_native_arrays",
        "mass_metadata_match",
        "geometry_static_integrity",
    ):
        if hard.get(key) is not True:
            raise ValueError(f"v2 static gate failed: {key}")

    if boundary.get("schema") != "core.f5.third_t1.preflight_boundary_semantics_audit.v1" or boundary.get("status") != "read_only_semantics_audit_passed":
        raise ValueError("boundary semantics audit is not a read-only pass")
    if boundary.get("qualification_claim") != "none":
        raise ValueError("boundary semantics audit carries scientific credit")
    if boundary.get("source", {}).get("sha256") != sha256(PREFLIGHT):
        raise ValueError("boundary semantics audit is stale")
    counts = boundary.get("counts", {})
    if (
        counts.get("identity_closure") is not True
        or counts.get("native_fixed_semantics_match") is not True
        or counts.get("generated_fixed_particles") != counts.get("native_case_nfixed")
    ):
        raise ValueError("boundary semantics identity closure failed")
    bcontrols = boundary.get("execution_controls", {})
    if bcontrols.get("solver_invoked") is not False or bcontrols.get("gpu_started") is not False:
        raise ValueError("boundary audit opened runtime execution")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "matrix_mutation", "qualification_credit"):
        if bcontrols.get(key) != 0:
            raise ValueError(f"boundary audit changed protected state: {key}")

    if not DEFINITION.is_file() or not MOTION.is_file():
        raise FileNotFoundError("fresh v2 Definition or motion file is missing")
    xml = ET.parse(DEFINITION).getroot()
    definition = xml.find("./casedef/geometry/definition")
    if definition is None or definition.get("dp") != "0.0075":
        raise ValueError("fresh Definition dp is not 0.0075 m")
    motion_ref = xml.find("./casedef/motion/objreal/mvpredef/file")
    if motion_ref is None or motion_ref.get("name") != MOTION.name:
        raise ValueError("fresh Definition is not bound to the v2 motion file")
    params = _xml_parameters(xml)
    if params.get("TimeMax") != "16" or params.get("TimeOut") != "0.02":
        raise ValueError("fresh Definition time/cadence is not 16 s/0.02 s")
    gauges = {node.get("name") for node in xml.findall("./execution/special/gauges/swl")}
    if not {"WG1", "WG2", "WG3", "WG4"} <= gauges:
        raise ValueError("fresh Definition is missing one of WG1..WG4")
    rows = _motion_rows()
    if len(rows) != 626 or not rows or rows[0][0] != "0.0000000000" or float(rows[-1][0]) < 15.0:
        raise ValueError("fresh motion identity is not closed")

    generated_xml = LAB / preflight["artifacts"]["generated_xml"]["path"]
    generated_bi4 = LAB / preflight["artifacts"]["native_bi4"]["path"]
    if not generated_xml.is_file() or not generated_bi4.is_file():
        raise FileNotFoundError("fresh generated XML/BI4 is missing")
    generated_root = ET.parse(generated_xml).getroot()
    particles = generated_root.find("./execution/particles")
    if particles is None or int(particles.get("np")) != int(preflight["generated"]["total_particles"]):
        raise ValueError("generated XML particle identity changed")
    if preflight["generated"]["total_particles"] != preflight["native"]["total_particles"]:
        raise ValueError("generated/native total particle identity is not closed")
    if preflight["generated"]["fluid_particles"] != preflight["native"]["fluid_particles"]:
        raise ValueError("generated/native fluid identity is not closed")
    if preflight.get("geometry", {}).get("pass") is not True or preflight["geometry"].get("anomalies") != []:
        raise ValueError("v2 geometry static integrity is not closed")

    if ANCHOR_STEM.exists():
        raise ValueError(f"fresh solver anchor output stem is already present: {ANCHOR_STEM}")
    preflight_stem = generated_xml.with_suffix("").resolve()
    if ANCHOR_STEM.resolve() == preflight_stem:
        raise ValueError("solver anchor stem aliases the CPU/native preflight stem")

    return {
        "proposal": proposal,
        "v2_review": v2_review,
        "contract": contract,
        "preflight": preflight,
        "boundary": boundary,
        "generated_xml": generated_xml,
        "generated_bi4": generated_bi4,
        "definition": definition,
        "params": params,
        "gauges": sorted(gauges),
        "motion_rows": rows,
    }


def _hard_integrity_gates() -> dict[str, dict[str, Any]]:
    return {
        "requested_horizon": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "saved/native trajectory reaches exactly the registered 16.0 s horizon",
        },
        "native_identity": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "native fluid IDs remain unique and no active fluid ID is missing",
        },
        "finite_active_values": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "all active position, velocity, density, mass and gauge values are finite",
        },
        "closed_face_endpoint": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "zero piston, slope and block closed-face endpoint violations",
        },
        "saved_frame_chords": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "zero saved-frame chord crossings through piston, slope or block geometry",
        },
        "domain_containment": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "zero unintended active particles outside the explicit simulation domain",
        },
        "full_window_mass": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "native source mass and full-window mass change remain within fixed root gates",
        },
    }


def _event_gates() -> dict[str, dict[str, Any]]:
    return {
        "incident_order": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "incident-wave signal reaches WG1, then WG2 and WG3 in chronological order",
        },
        "runup_threshold": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "run-up-line signal exceeds the preregistered q-independent threshold with finite first/peak time",
        },
        "return_threshold": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "run-up returns below its event threshold before the 16.0 s horizon",
        },
        "external_gauges": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "q=0.5 scale=1.0 compares WG1..WG4 with the pinned CIEMito table at fixed time origin",
        },
        "completion": {
            "required": True,
            "status": "pending_until_solver",
            "condition": "full window, all hard-integrity gates, incident/run-up/return events and external review complete",
        },
    }


def build_review() -> dict[str, Any]:
    evidence = _verify_static_evidence()
    contract = evidence["contract"]
    preflight = evidence["preflight"]
    generated_xml = evidence["generated_xml"]
    generated_bi4 = evidence["generated_bi4"]
    hard = _hard_integrity_gates()
    events = _event_gates()
    return {
        "schema": "core.f5.third_t1.solver_anchor_root_review_receipt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "record_id": "f5-wave-runup-third-t1-solver-anchor-root-review-v1",
        "status": "root_review_only_protected_gpu_solver_anchor_authorized_not_submitted",
        "root_review_only": True,
        "family": "F5",
        "scope_id": contract["candidate"]["scope_id"],
        "revision_id": contract["candidate"]["revision_id"],
        "candidate_case_id": CASE_ID,
        "qualification_claim": "none",
        "matrix_credit": 0,
        "denominator_rows": EXPECTED_ROWS,
        "review_decision": {
            "authorized_now": True,
            "decision": "approved_for_exactly_one_protected_gpu_solver_anchor",
            "authorized_action": "authorize_exactly_one_protected_gpu_solver_anchor",
            "authorized_solver": True,
            "authorized_gpu": True,
            "authorized_queue": True,
            "authorized_registry": False,
            "authorized_ledger": False,
            "authorized_matrix": False,
            "exactly_one_anchor": True,
            "authorized_case_id": CASE_ID,
            "authorized_output_stem": ANCHOR_STEM_REL,
            "reason": "v2 root review, static CPU/native preflight, boundary semantics audit and fresh generated XML/BI4 are hash-closed",
            "failure_policy": "any solver hard-integrity or event failure receives zero credit and remains in the fixed 15-row denominator",
        },
        "review_inputs": {
            "proposal": bind(PROPOSAL, "F5 third-T1 proposal audit"),
            "v2_root_review": bind(V2_REVIEW, "F5 v2 CPU/native root review"),
            "v2_preflight": bind(PREFLIGHT, "F5 v2 CPU/native static preflight"),
            "boundary_semantics_audit": bind(BOUNDARY_AUDIT, "F5 boundary semantics audit"),
            "definition_contract": bind(CONTRACT, "fresh v2 Definition contract"),
            "definition": bind(DEFINITION, "fresh v2 Definition"),
            "motion": bind(MOTION, "fresh v2 piston motion"),
            "generated_xml": bind(generated_xml, "fresh generated XML"),
            "native_bi4": bind(generated_bi4, "fresh native BI4"),
        },
        "anchor_input": {
            "case_id": CASE_ID,
            "q": 0.5,
            "piston_scale": 1.0,
            "dp_m": 0.0075,
            "time_max_s": TIME_MAX_S,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "gauge_interval_s": OUTPUT_INTERVAL_S,
            "generated_xml_stem": rel(generated_xml.with_suffix("")),
            "anchor_output_stem": ANCHOR_STEM_REL,
            "anchor_output_is_fresh": True,
            "preflight_output_reused": False,
            "old_generated_or_trajectory_reused": False,
        },
        "fixed_denominator": {
            "planned_rows": EXPECTED_ROWS,
            "required_pass_rows": EXPECTED_ROWS,
            "numerator_rows": 0,
            "preflight_credit": 0,
            "anchor_credit": 0,
            "all_rows_retained": True,
            "partial_credit": False,
            "event_censor_is_failure": True,
            "hard_integrity_failure_is_failure": True,
        },
        "hard_integrity_gates": hard,
        "event_gates": events,
        "failure_policy": {
            "failure_zero_credit": True,
            "same_input_retry": False,
            "threshold_relaxation": False,
            "horizon_extension_before_anchor": False,
            "survivor_renormalization": False,
            "registry_mutation": False,
            "ledger_mutation": False,
            "matrix_materialization": False,
            "on_failure": "retain one failed or censored anchor and keep all 15 denominator rows fixed",
        },
        "authorization": {
            "protected_gpu_anchor": True,
            "exactly_one_anchor": True,
            "solver_launch": True,
            "gpu_launch": True,
            "job_spec_creation": True,
            "direct_execution": False,
            "queue_submission": True,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "matrix_expansion": False,
        },
        "execution_controls": {
            "review_only": True,
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_materialized": False,
            "matrix_submitted": False,
            "qualification_credit": 0,
            "core_gate_changed": False,
        },
        "worker_binding": bind(WORKER, "static contract-only F5 anchor worker"),
        "hash_bindings": {
            "implementation": bind(IMPLEMENTATION, "F5 solver-anchor root-review implementation"),
            "test": bind(TEST, "F5 solver-anchor root-review regression test"),
            "worker": bind(WORKER, "F5 contract-only worker"),
            "runtime_worker": bind(RUNTIME_WORKER, "F5 protected anchor runtime worker; not yet submitted"),
        },
    }


def verify_review(path: Path = REVIEW_OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != "core.f5.third_t1.solver_anchor_root_review_receipt.v1":
        raise ValueError("wrong solver-anchor root-review schema")
    decision = value.get("review_decision", {})
    if value.get("status") != "root_review_only_protected_gpu_solver_anchor_authorized_not_submitted":
        raise ValueError("root review is not in the protected not-submitted state")
    if decision.get("exactly_one_anchor") is not True or decision.get("authorized_solver") is not True or decision.get("authorized_gpu") is not True:
        raise ValueError("root review does not authorize exactly one protected GPU solver anchor")
    if decision.get("authorized_queue") is not True:
        raise ValueError("root review does not authorize the single protected queue submission")
    if any(decision.get(key) for key in ("authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("root review opens a forbidden scientific mutation path")
    if value.get("denominator_rows") != EXPECTED_ROWS or value.get("matrix_credit") != 0:
        raise ValueError("root review denominator/credit changed")
    if value.get("failure_policy", {}).get("same_input_retry") is not False:
        raise ValueError("same-input retry is not closed")
    for item in value.get("hash_bindings", {}).values():
        _verify_binding(item, "root-review")
    _verify_static_evidence()
    if value.get("anchor_input", {}).get("anchor_output_stem") != ANCHOR_STEM_REL:
        raise ValueError("root review anchor stem changed")
    if ANCHOR_STEM.exists():
        raise ValueError("anchor output stem is no longer fresh")
    return value


def build_job(review: dict[str, Any], review_path: Path = REVIEW_OUTPUT) -> dict[str, Any]:
    evidence = _verify_static_evidence()
    if review.get("schema") != "core.f5.third_t1.solver_anchor_root_review_receipt.v1":
        raise ValueError("cannot build job from another review schema")
    input_paths = [
        (review_path, "exact F5 protected-anchor root review"),
        (V2_REVIEW, "F5 v2 CPU/native root review"),
        (PREFLIGHT, "F5 v2 CPU/native static preflight"),
        (BOUNDARY_AUDIT, "F5 boundary semantics audit"),
        (CONTRACT, "fresh v2 Definition contract"),
        (PROPOSAL, "F5 third-T1 proposal audit"),
        (DEFINITION, "fresh v2 Definition"),
        (MOTION, "fresh v2 piston motion"),
        (evidence["generated_xml"], "fresh generated XML"),
        (evidence["generated_bi4"], "fresh native BI4"),
        (WORKER, "contract-only F5 anchor worker"),
        (RUNTIME_WORKER, "protected F5 anchor runtime worker; planned only"),
        (SOLVER, "pinned DualSPHysics solver; planned only"),
        (DECODER, "pinned native BI4 decoder; planned only"),
    ]
    bindings = {path.stem.replace("-", "_"): bind(path, role) for path, role in input_paths}
    # The key is a stable human-facing alias rather than a filename-derived
    # name for the generated artifacts and root review.
    bindings = {
        "root_review": bind(review_path, "exact F5 protected-anchor root review"),
        "v2_root_review": bind(V2_REVIEW, "F5 v2 CPU/native root review"),
        "v2_preflight": bind(PREFLIGHT, "F5 v2 CPU/native static preflight"),
        "boundary_audit": bind(BOUNDARY_AUDIT, "F5 boundary semantics audit"),
        "definition_contract": bind(CONTRACT, "fresh v2 Definition contract"),
        "proposal": bind(PROPOSAL, "F5 third-T1 proposal audit"),
        "definition": bind(DEFINITION, "fresh v2 Definition"),
        "motion": bind(MOTION, "fresh v2 piston motion"),
        "generated_xml": bind(evidence["generated_xml"], "fresh generated XML"),
        "native_bi4": bind(evidence["generated_bi4"], "fresh native BI4"),
        "worker": bind(WORKER, "contract-only F5 anchor worker"),
        "runtime_worker": bind(RUNTIME_WORKER, "protected F5 anchor runtime worker; planned only"),
        "solver": bind(SOLVER, "pinned DualSPHysics solver; planned only"),
        "decoder": bind(DECODER, "pinned native BI4 decoder; planned only"),
    }
    return {
        "schema": "core.f5.third_t1.solver_anchor_job_spec.v1",
        "job_id": "f5-wave-runup-third-t1-q05-dp0075-v2-protected-gpu-anchor",
        "logical_id": "F5_wave_runup_q0p50_dp0p0075_v2_protected_gpu_anchor",
        "scope_id": "F5_prescribed_wave_runup_x_v1",
        "revision_id": evidence["contract"]["candidate"]["revision_id"],
        "family": "F5",
        "job_spec_status": "root_review_only_not_submitted",
        "root_review_only": True,
        "attempt_role": "protected_single_gpu_solver_anchor",
        "exactly_one_anchor": True,
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "prepared_case_id": CASE_ID,
        "matrix_row": {
            "index": 4,
            "row_kind": "spatial_anchor",
            "q": 0.5,
            "dp_m": 0.0075,
            "case_id": CASE_ID,
            "denominator_rows": EXPECTED_ROWS,
        },
        "root_review": {
            "path": rel(review_path),
            "sha256": sha256(review_path),
            "role": "exact-one protected GPU anchor authorization",
        },
        "anchor_input": {
            "generated_prefix": rel(evidence["generated_xml"].with_suffix("")),
            "generated_xml": rel(evidence["generated_xml"]),
            "native_bi4": rel(evidence["generated_bi4"]),
            "output_directory": rel(ANCHOR_STEM.parent),
            "output_stem": ANCHOR_STEM_REL,
            "output_stem_is_new": True,
            "preflight_stem_reused": False,
        },
        "anchor_output": {
            "stem": ANCHOR_STEM_REL,
            "execution_path_template": "{attempt_dir}/product/solver",
            "logical_stem_only": True,
        },
        "registered_window_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "gauge_interval_s": OUTPUT_INTERVAL_S,
        "event_completion_required": True,
        "hard_integrity_gates": _hard_integrity_gates(),
        "event_gates": _event_gates(),
        "failure_policy": {
            "same_input_retry": False,
            "failure_zero_credit": True,
            "threshold_relaxation": False,
            "horizon_extension_before_anchor": False,
            "event_censor_is_failure": True,
            "hard_integrity_failure_is_failure": True,
            "failed_anchor_stays_in_denominator": True,
        },
        "worker": {
            "path": rel(WORKER),
            "sha256": sha256(WORKER),
            "runtime_enabled": False,
            "contract_only": True,
            "solver_calls": 0,
            "gpu_calls": 0,
            "queue_mutations": 0,
            "ledger_mutations": 0,
            "registry_mutations": 0,
        },
        "planned_solver": {
            "binary": rel(SOLVER),
            "binary_sha256": sha256(SOLVER),
            "decoder": rel(DECODER),
            "decoder_sha256": sha256(DECODER),
            "host": "ada",
            "cuda_device_contract": "scheduler supplies exactly one CUDA UUID; worker maps it to solver -gpu:0",
            "argv_after_explicit_runtime_approval": [
                rel(SOLVER),
                "-gpu:0",
                rel(evidence["generated_xml"].with_suffix("")),
                "{attempt_dir}/product/solver",
            ],
            "solver_invoked": False,
            "gpu_started": False,
        },
        "required_outputs": [
            "product/audit.json",
            "product/observations.json",
            "product/solver/Run.out",
        ],
        "resources": {
            "cpu_cores": 4,
            "ram_mib": 65536,
            "gpu_peak_mib": 24576,
            "io_weight": 2,
            "timeout_seconds": 86400,
            "estimate_status": "planning_only_no_reservation",
            "basis": "fresh 1,279,855-fluid-particle input; no prior Core F5 solver anchor; 1.2x GPU reservation rule",
        },
        "execution_policy": {
            "submit_allowed": False,
            "solver_launch": True,
            "gpu_launch": True,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "matrix_expansion": False,
            "one_anchor_only": True,
            "same_input_retry": False,
            "failure_credit": 0,
            "qualification_claim_none": True,
            "runtime_worker_enabled": False,
        },
        "runtime_worker": {
            "path": rel(RUNTIME_WORKER),
            "sha256": sha256(RUNTIME_WORKER),
            "runtime_enabled": True,
            "solver_calls": 1,
            "gpu_calls": 1,
            "queue_mutations": 0,
            "ledger_mutations": 0,
            "registry_mutations": 0,
            "matrix_mutations": 0,
            "single_use": True,
        },
        "input_files": list(bindings.values()),
        "hash_bindings": bindings,
    }


def verify_job(path: Path = JOB_OUTPUT) -> dict[str, Any]:
    value = load(path)
    if value.get("schema") != "core.f5.third_t1.solver_anchor_job_spec.v1":
        raise ValueError("wrong F5 solver-anchor job schema")
    if value.get("job_spec_status") != "root_review_only_not_submitted" or value.get("exactly_one_anchor") is not True:
        raise ValueError("job is not a root-review-only single anchor")
    if value.get("qualification_claim") != "none" or value.get("matrix_credit") != 0:
        raise ValueError("job carries scientific credit")
    policy = value.get("execution_policy", {})
    if policy.get("submit_allowed") is not False or policy.get("solver_launch") is not True or policy.get("gpu_launch") is not True:
        raise ValueError("job execution policy is not protected")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "failure_credit"):
        if policy.get(key) != 0:
            raise ValueError(f"job mutation/credit policy is open: {key}")
    for key in ("matrix_submission", "matrix_expansion", "one_anchor_only", "same_input_retry", "qualification_claim_none"):
        expected = False if key in ("matrix_submission", "matrix_expansion", "same_input_retry") else True
        if policy.get(key) is not expected:
            raise ValueError(f"job policy changed: {key}")
    if value.get("anchor_input", {}).get("output_stem") != ANCHOR_STEM_REL or ANCHOR_STEM.exists():
        raise ValueError("anchor output stem is stale or reused")
    if value.get("root_review", {}).get("sha256") != sha256(REVIEW_OUTPUT):
        raise ValueError("job root-review binding is stale")
    for item in value.get("hash_bindings", {}).values():
        _verify_binding(item, "job")
    runtime = value.get("runtime_worker", {})
    if runtime.get("path") != rel(RUNTIME_WORKER) or runtime.get("sha256") != sha256(RUNTIME_WORKER):
        raise ValueError("runtime worker binding is stale")
    if value.get("anchor_output", {}).get("stem") != ANCHOR_STEM_REL:
        raise ValueError("logical anchor output stem is missing")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-output", type=Path, default=REVIEW_OUTPUT)
    parser.add_argument("--job-output", type=Path, default=JOB_OUTPUT)
    args = parser.parse_args()

    review = build_review()
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.review_output, review)
    verified_review = verify_review(args.review_output)
    job = build_job(verified_review)
    args.job_output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.job_output, job)
    verify_job(args.job_output)
    print(json.dumps({
        "review": {"path": rel(args.review_output), "sha256": sha256(args.review_output)},
        "job": {"path": rel(args.job_output), "sha256": sha256(args.job_output)},
        "anchor_output_stem": ANCHOR_STEM_REL,
        "solver_invoked": False,
        "gpu_started": False,
        "queue_mutation": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
