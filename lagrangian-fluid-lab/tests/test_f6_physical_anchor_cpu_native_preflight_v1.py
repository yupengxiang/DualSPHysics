import json
from pathlib import Path

import pytest

from scripts.f6_physical_anchor_cpu_native_preflight_v1 import OUTPUT_DIR, run


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-preflight-v1-20260921"


def load(name: str) -> dict:
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def test_v1_authorization_is_single_cpu_native_and_zero_credit():
    authorization = load("authorization.json")
    assert authorization["status"] == "authorized_for_exactly_one_cpu_native_preflight"
    assert authorization["root_authorized_for_cpu_native_preflight"] is True
    assert authorization["single_input"]["simulation_input_count"] == 1
    assert authorization["single_input"]["old_xml_bi4_hdf5_reused_as_input"] is False
    permissions = authorization["permissions"]
    assert permissions["cpu_gencase"] is True
    assert permissions["native_decode"] is True
    assert permissions["solver_launch"] is False
    assert permissions["gpu_launch"] is False
    assert permissions["queue_mutation"] == 0
    assert permissions["registry_mutation"] == 0
    assert permissions["ledger_mutation"] == 0
    assert permissions["matrix_submission"] is False
    assert permissions["qualification_credit"] == 0
    assert authorization["qualification_claim"] == "none"
    assert authorization["execution_policy"]["same_input_retry"] is False


def test_v1_preserves_preliminary_verifier_failure_before_native_decode():
    receipt = load("preflight.json")
    assert receipt["status"] == "cpu_native_preflight_failed_hard"
    assert receipt["gencase"]["returncode"] == 0
    assert receipt["execution_controls"]["cpu_gencase_invoked"] is True
    assert receipt["execution_controls"]["cpu_native_decode_invoked"] is False
    assert receipt["native_decoder_invoked"] is False
    assert receipt["preliminary_failure"]["kind"] == "verifier_infrastructure_failure"
    assert receipt["preliminary_failure"]["native_decode_was_invoked"] is False
    assert receipt["same_input_retry"] is False
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    controls = receipt["execution_controls"]
    assert controls["solver_invoked"] is False
    assert controls["gpu_invoked"] is False
    assert controls["queue_mutation"] == 0
    assert controls["registry_mutation"] == 0
    assert controls["ledger_mutation"] == 0
    assert controls["matrix_submission"] is False


def test_generated_xml_exposes_floating_group_that_initial_verifier_missed():
    xml = (OUTPUT / "generated/F6_physical_anchor_cpu_native_preflight_20260921.xml").read_text(encoding="utf-8")
    assert '<floating mkbound="8"' in xml
    assert '<fluid mkfluid="0"' in xml
    assert "<fixed mkbound=\"0\"" in xml


def test_existing_one_shot_output_refuses_same_input_retry():
    with pytest.raises(RuntimeError, match="same-input retry"):
        run(OUTPUT_DIR)
