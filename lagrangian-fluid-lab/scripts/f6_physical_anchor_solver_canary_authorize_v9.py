#!/usr/bin/env python3
"""Authorize exactly one CPU solver canary for the F6 v9 anchor.

This command performs the second, independent root review after the v9
CPU/native input preflight.  It writes a hash-bound review and job contract;
it never starts a solver, GPU process, queue submission, registry mutation,
ledger mutation, or matrix submission.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
SOURCE_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v9-20260921"
PREFLIGHT_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-cpu-native-preflight-v9-20260921"
AUTH_ROOT = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-solver-canary-v9-20260921"
SCRIPT = Path(__file__).resolve()
RUNTIME_WORKER = LAB / "scripts/f6_physical_anchor_solver_canary_v9.py"
SOLVER = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4CPU_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
FLOATING_INFO = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/FloatingInfo_linux64"

DEFINITION = SOURCE_ROOT / "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v9_20260921_Def.xml"
CONTRACT = SOURCE_ROOT / "definition-contract.json"
SIDECAR_SCHEMA = SOURCE_ROOT / "body-state-force-torque-sidecar-schema.json"
EVENT = SOURCE_ROOT / "event-window-contract.json"
ROOT_PREFLIGHT = SOURCE_ROOT / "preflight.json"
ROOT_PROPOSAL = SOURCE_ROOT / "proposal.json"
NATIVE_PREFLIGHT = PREFLIGHT_ROOT / "preflight.json"
GENERATED_PREFIX = PREFLIGHT_ROOT / "generated/F6_physical_anchor_explicit_body_v9_cpu_native_preflight_20260921"

SCHEMA = "core.f6.physical_anchor.protected_solver_canary_job.v1"
REVIEW_SCHEMA = "core.f6.physical_anchor.protected_solver_canary_root_review.v1"
DEFINITION_ID = "CORE_F6_physical_anchor_single_body_gravity_explicit_body_v9_20260921"
BODY_ID = "F6_physical_anchor_body_kappa_20260921"
CASE_ID = "F6_explicit_body_v9_protected_solver_canary_20260921"
TMAX = 1.5
TOUT = 0.005
EXPECTED_FRAMES = 301


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        display = str(path.relative_to(LAB))
    except ValueError:
        display = str(path)
    return {"path": display, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proposal = load(ROOT_PROPOSAL)
    native = load(NATIVE_PREFLIGHT)
    root = load(ROOT_PREFLIGHT)
    if proposal.get("case_id") != DEFINITION_ID or proposal.get("T1") is not False:
        raise ValueError("v9 proposal identity or T1 guard is invalid")
    decision = proposal.get("root_review_decision", {})
    if decision.get("cpu_preflight_pass") is not True or decision.get("event_window_is_analytically_auditable") is not True:
        raise ValueError("v9 proposal does not support a protected canary")
    if decision.get("solver_canary_authorized_now") is not False:
        raise ValueError("the v9 proposal must not self-authorize execution")
    if native.get("status") != "cpu_native_preflight_pass_exact_one" or native.get("preflight_pass") is not True:
        raise ValueError("v9 CPU/native preflight is not an exact-one pass")
    if native.get("qualification_claim") != "none" or native.get("qualification_credit") != 0 or native.get("T1") is not False:
        raise ValueError("v9 CPU/native receipt carries science credit")
    controls = native.get("execution_controls", {})
    if any(controls.get(key) for key in ("solver_invoked", "gpu_invoked", "job_created", "matrix_submission")):
        raise ValueError("v9 native preflight already opened a protected execution path")
    if any(controls.get(key) not in (0, False) for key in ("queue_mutation", "registry_mutation", "ledger_mutation")):
        raise ValueError("v9 native preflight mutated protected state")
    for path in (DEFINITION, CONTRACT, SIDECAR_SCHEMA, EVENT, ROOT_PREFLIGHT, ROOT_PROPOSAL, NATIVE_PREFLIGHT, GENERATED_PREFIX.with_suffix(".xml"), GENERATED_PREFIX.with_suffix(".bi4"), SOLVER, DECODER, FLOATING_INFO, SCRIPT, RUNTIME_WORKER):
        if not path.is_file():
            raise FileNotFoundError(path)
    return proposal, native, root


def create() -> dict[str, Any]:
    proposal, native, root = validate_inputs()
    event = load(EVENT)
    AUTH_ROOT.mkdir(parents=True, exist_ok=True)
    review_path = AUTH_ROOT / "root-review.json"
    job_path = AUTH_ROOT / "job.json"
    review = {
        "schema": REVIEW_SCHEMA,
        "review_id": "F6_explicit_body_v9_solver_canary_root_review_20260921",
        "created_at_utc": stamp(),
        "status": "root_review_authorized_one_cpu_solver_canary",
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_physical_anchor_v1",
        "case_id": DEFINITION_ID,
        "body_id": BODY_ID,
        "decision": {
            "authorized_solver": True,
            "authorized_gpu": False,
            "authorized_cpu_solver": True,
            "authorized_queue": False,
            "authorized_registry": False,
            "authorized_ledger": False,
            "authorized_matrix": False,
            "exactly_one_solver_attempt": True,
            "same_input_retry": False,
            "resume": False,
        },
        "basis": {
            "proposal": ref(ROOT_PROPOSAL, "v9 conditional canary proposal"),
            "root_preflight": ref(ROOT_PREFLIGHT, "v9 root CPU preflight"),
            "native_preflight": ref(NATIVE_PREFLIGHT, "v9 exact-one CPU/native preflight"),
            "definition_contract": ref(CONTRACT, "v9 Definition contract"),
            "event_window": ref(EVENT, "v9 event-window contract"),
            "body_sidecar_schema": ref(SIDECAR_SCHEMA, "v9 body-state/force/torque schema"),
            "runtime_worker": ref(RUNTIME_WORKER, "single-use CPU solver worker"),
        },
        "window": {
            "start_s": 0.0,
            "end_s": TMAX,
            "cadence_s": TOUT,
            "expected_frames": EXPECTED_FRAMES,
            "settle_hold_s": [1.0, 1.5],
            "contact_window_s": event.get("predicted_events", {}).get("contact_prediction_window_s", [0.1869141263, 0.2269141263]),
        },
        "hard_failure_policy": [
            "input hash mismatch, duplicate invocation, retry or resume",
            "solver failure, missing or censored frame, non-increasing time or cadence mismatch",
            "non-finite body sidecar, body identity change, contact-window miss",
            "closed-tank-face contact or penetration, unexplained top-open mass flux",
            "any registry/ledger/matrix/queue mutation",
        ],
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "execution_controls": {
            "solver_invoked": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_submission": False,
        },
    }
    write(review_path, review)
    generated_xml = GENERATED_PREFIX.with_suffix(".xml")
    generated_bi4 = GENERATED_PREFIX.with_suffix(".bi4")
    job = {
        "schema": SCHEMA,
        "job_id": CASE_ID,
        "job_status": "root_authorized_not_started",
        "attempt": 1,
        "input_count": 1,
        "case_id": DEFINITION_ID,
        "body_id": BODY_ID,
        "family": "F6",
        "scope_id": "F6_fluid_rigid_body_physical_anchor_v1",
        "root_review": ref(review_path, "independent root authorization"),
        "window": review["window"],
        "solver": {
            "binary": ref(SOLVER, "pinned CPU DualSPHysics solver"),
            "argv": [str(SOLVER), "-tmax:1.5", "-tout:0.005", str(GENERATED_PREFIX), "<attempt>/solver"],
            "cuda_visible_devices": "",
            "threads": 32,
            "timeout_seconds": 3600,
        },
        "floating_info": ref(FLOATING_INFO, "pinned floating-body sidecar converter"),
        "decoder": ref(DECODER, "pinned native BI4 decoder"),
        "runtime_worker": ref(RUNTIME_WORKER, "single-use CPU solver worker"),
        "inputs": {
            "definition": ref(DEFINITION, "fresh v9 Definition"),
            "definition_contract": ref(CONTRACT, "v9 Definition contract"),
            "sidecar_schema": ref(SIDECAR_SCHEMA, "body-state/force/torque sidecar schema"),
            "event_window": ref(EVENT, "event-window contract"),
            "root_preflight": ref(ROOT_PREFLIGHT, "v9 root preflight"),
            "proposal": ref(ROOT_PROPOSAL, "v9 conditional proposal"),
            "native_preflight": ref(NATIVE_PREFLIGHT, "v9 native preflight"),
            "generated_xml": ref(generated_xml, "GenCase generated XML"),
            "generated_bi4": ref(generated_bi4, "GenCase native initial state"),
        },
        "execution_policy": {
            "exactly_one_solver_attempt": True,
            "same_input_retry": False,
            "resume": False,
            "queue_submission": False,
            "registry_mutation": False,
            "ledger_mutation": False,
            "matrix_submission": False,
            "failure_credit": 0,
        },
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
    }
    write(job_path, job)
    return {"status": review["status"], "review": str(review_path), "job": str(job_path), "job_sha256": sha256(job_path)}


def main() -> int:
    result = create()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
