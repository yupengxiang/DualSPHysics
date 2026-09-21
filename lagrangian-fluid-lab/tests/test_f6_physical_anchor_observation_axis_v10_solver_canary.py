"""Hash-bound scientific gates for the one-shot F6 v10 solver canary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-20260921"
)
RECEIPT = ROOT / "attempt-001/execution-receipt.json"
SIDECAR = ROOT / "attempt-001/body-state-force-torque-sidecar.json"
JOB = ROOT / "job.json"
REVIEW = ROOT / "root-review.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v10_solver_receipt_is_complete_but_nonqualifying() -> None:
    receipt = load(RECEIPT)
    assert receipt["status"] == "solver_completed_sidecar_pass_pending_scientific_review"
    assert receipt["scope_id"] == "F6_fluid_rigid_body_physical_anchor_v2"
    assert receipt["returncode"] == 0
    assert receipt["frames"]["count"] == 301
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["T1"] is False

    gates = receipt["hard_gates"]
    assert all(gates.values())
    controls = receipt["execution_controls"]
    assert controls["solver_invoked"] is True
    assert controls["gpu_started"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False


def test_v10_uses_actual_time_axis_and_observation_hold() -> None:
    receipt = load(RECEIPT)
    axis = receipt["time_axis_contract"]
    assert axis["native_time_axis"] == "solver_reported_actual_TimeStep"
    assert axis["max_gap_s"] == 0.0055
    assert axis["terminal_target_s"] == 1.5
    assert axis["terminal_overshoot_max_s"] == 0.0005
    assert axis["equilibrium_status"] == "not_claimed"

    sidecar = load(SIDECAR)
    audit = sidecar["audit"]
    assert audit["native_time_axis"] == "solver_reported_actual_TimeStep"
    assert audit["max_native_gap_s"] <= 0.0055
    assert audit["observation_window_s"] == [1.0, 1.5]
    assert audit["equilibrium_status"] == "not_claimed"
    assert audit["checks"]["observation_hold_bracketed"] is True
    assert audit["checks"]["observation_hold_no_equilibrium_claim"] is True


def test_v10_event_and_sidecar_contracts_are_hash_bound() -> None:
    receipt = load(RECEIPT)
    sidecar = load(SIDECAR)
    assert receipt["root_review"]["sha256"] == sha256(REVIEW)
    assert receipt["job"]["sha256"] == sha256(JOB)
    assert receipt["runtime_worker"]["path"].endswith(
        "scripts/f6_physical_anchor_observation_axis_v10_solver_canary.py"
    )
    assert sidecar["audit"]["contact_time_s"] is not None
    assert sidecar["audit"]["checks"]["contact_time_in_predicted_window"] is True
    assert sidecar["audit"]["checks"]["closed_face_contact_zero"] is True
    assert sidecar["audit"]["checks"]["closed_face_penetration_zero"] is True
    assert sidecar["audit"]["checks"]["open_face_mass_flux_zero"] is True


def test_v10_job_keeps_retry_and_scientific_state_closed() -> None:
    job = load(JOB)
    policy = job["execution_policy"]
    assert job["job_status"] == "root_authorized_not_started"
    assert job["attempt"] == 1
    assert policy["exactly_one_solver_attempt"] is True
    assert policy["same_input_retry"] is False
    assert policy["resume"] is False
    assert policy["queue_submission"] is False
    assert policy["registry_mutation"] is False
    assert policy["ledger_mutation"] is False
    assert policy["matrix_submission"] is False
    assert job["qualification_claim"] == "none"
    assert job["qualification_credit"] == 0
    assert job["T1"] is False
