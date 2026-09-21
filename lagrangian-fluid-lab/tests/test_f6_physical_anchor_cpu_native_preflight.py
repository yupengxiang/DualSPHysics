"""Evidence tests for the bounded F6 CPU/native physical-anchor preflight."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-preflight-v1-20260921/preflight.json"
FINAL = ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-decode-amendment-v2-20260921/amendment-final.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_original_receipt_keeps_gen_case_verifier_failure_separate() -> None:
    data = _load(ORIGINAL)
    assert data["schema"] == "core.f6.physical_anchor.cpu_native_preflight.v1"
    assert data["status"] == "cpu_native_preflight_failed_hard"
    assert data["gencase"]["returncode"] == 0
    assert data["generated_groups"]["fluid"][0]["count"] == 16008
    assert data["generated_groups"]["fixed"][0]["count"] == 11806
    assert "floating" not in {item["kind"] for item in data["generated_groups"]["fixed"]}
    assert data["qualification_claim"] == "none"
    assert data["qualification_credit"] == 0
    assert data["execution_controls"]["solver_invoked"] is False
    assert data["execution_controls"]["gpu_invoked"] is False


def test_final_native_amendment_is_a_hard_body_contract_failure() -> None:
    data = _load(FINAL)
    assert data["status"] == "cpu_native_decode_completed_hard_failure"
    assert data["preflight_pass"] is False
    assert data["generated_body"]["massbody_kg"] == 4.32432
    assert data["generated_body"]["massbody_relative_error"] > 0.4
    assert data["generated_body"]["center_max_abs_error_m"] >= 0.01
    assert data["generated_body"]["inertia_max_relative_error"] > 0.8
    checks = data["checks"]
    assert checks["one_floating_body_group"] is True
    assert checks["native_ids_unique"] is True
    assert checks["native_arrays_finite"] is True
    assert checks["generated_body_mass_matches_contract"] is False
    assert checks["generated_body_center_matches_contract"] is False
    assert checks["generated_body_inertia_matches_contract"] is False
    assert data["same_input_gencase_retry"] is False
    assert data["solver_invoked"] is False
    assert data["gpu_invoked"] is False
    assert data["queue_mutation"] == 0
    assert data["registry_mutation"] == 0
    assert data["ledger_mutation"] == 0
    assert data["qualification_claim"] == "none"
    assert data["qualification_credit"] == 0
