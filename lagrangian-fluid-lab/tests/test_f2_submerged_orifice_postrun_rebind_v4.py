from __future__ import annotations

import json

from scripts.f2_submerged_orifice_postrun_rebind_v4 import REBIND, verify


def test_v4_postrun_rebind_is_verifier_only_and_zero_credit():
    result = verify(REBIND)
    assert result["status"] == "rebound_verifier_only_no_science_change"
    assert result["changed_science_fields"] == []
    assert result["immutable_result"]["preflight_status"] == "cpu_native_preflight_failed_hard_audit"
    assert result["immutable_result"]["zero_boundnor_count"] == 29484
    assert result["immutable_result"]["zero_normal_size_count"] == 29484
    assert result["immutable_result"]["qualification_claim"] == "none"
    assert result["immutable_result"]["matrix_credit"] == 0


def test_v4_postrun_rebind_keeps_execution_closed():
    result = json.loads(REBIND.read_text(encoding="utf-8"))
    controls = result["execution_controls"]
    for key in ("solver_invoked", "gpu_invoked", "gencase_invoked", "native_decoder_invoked", "job_created", "matrix_submission"):
        assert controls[key] is False
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        assert controls[key] == 0
