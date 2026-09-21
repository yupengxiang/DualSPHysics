"""Evidence tests for the one-shot F6 v9 solver canary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
AUTH = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-solver-canary-v9-20260921"
ATTEMPT = AUTH / "attempt-001"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def test_v9_authorization_binds_exactly_one_cpu_worker_without_mutation() -> None:
    job = load(AUTH / "job.json")
    review = load(AUTH / "root-review.json")
    worker = LAB / "scripts/f6_physical_anchor_solver_canary_v9.py"
    assert review["status"] == "root_review_authorized_one_cpu_solver_canary"
    assert review["decision"]["authorized_cpu_solver"] is True
    assert review["decision"]["authorized_gpu"] is False
    assert review["decision"]["exactly_one_solver_attempt"] is True
    assert job["job_status"] == "root_authorized_not_started"
    assert job["attempt"] == 1
    assert job["runtime_worker"]["path"] == "scripts/f6_physical_anchor_solver_canary_v9.py"
    assert job["runtime_worker"]["sha256"] == digest(worker)
    policy = job["execution_policy"]
    assert policy["exactly_one_solver_attempt"] is True
    assert policy["same_input_retry"] is False
    assert policy["resume"] is False
    assert all(policy[key] is False for key in ("queue_submission", "registry_mutation", "ledger_mutation", "matrix_submission"))
    assert job["qualification_claim"] == "none"
    assert job["qualification_credit"] == 0
    assert job["T1"] is False


def test_v9_canary_preserves_complete_negative_receipt_and_zero_credit() -> None:
    receipt = load(ATTEMPT / "execution-receipt.json")
    native = load(ATTEMPT / "native-frame-audit.json")
    sidecar = load(ATTEMPT / "body-state-force-torque-sidecar.json")
    assert receipt["status"] == "solver_completed_hard_failure"
    assert receipt["returncode"] == 0
    assert receipt["frames"] == {"count": 301, "indices_first": [0, 1, 2], "indices_last": [298, 299, 300]}
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert receipt["T1"] is False
    controls = receipt["execution_controls"]
    assert controls["solver_invoked"] is True
    assert controls["gpu_started"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False
    assert native["checks"]["frame_count_exact"] is True
    assert native["checks"]["native_arrays_finite"] is True
    assert native["checks"]["native_identity_fixed"] is True
    assert native["checks"]["fluid_group_count_fixed"] is True
    assert native["checks"]["body_group_count_fixed"] is True
    assert native["checks"]["native_time_cadence_exact"] is False
    checks = sidecar["audit"]["checks"]
    assert checks["contact_time_in_predicted_window"] is True
    assert checks["closed_face_contact_zero"] is True
    assert checks["closed_face_penetration_zero"] is True
    assert checks["open_face_mass_flux_zero"] is True
    assert checks["sidecar_cadence_exact"] is False
    assert checks["settle_hold_complete"] is False
    assert checks["settle_hold_uncensored"] is False
