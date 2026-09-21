from __future__ import annotations

import json
from pathlib import Path

from scripts.f2_submerged_orifice_postrun_rebind_v3 import (
    CONTRACT,
    PREFLIGHT,
    REBINDS,
    RECEIPT,
    verify,
)


def test_postrun_rebind_is_present_and_science_neutral():
    result = verify(REBINDS)
    assert result["immutable_result"]["preflight_status"] == "cpu_native_preflight_failed_hard_audit"
    assert result["immutable_result"]["qualification_claim"] == "none"
    assert result["immutable_result"]["matrix_credit"] == 0
    assert result["changed_science_fields"] == []
    assert result["execution_controls"]["solver_invoked"] is False
    assert result["execution_controls"]["gencase_invoked"] is False


def test_rebound_json_references_current_sources():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    assert Path(receipt["hash_bindings"]["v3_root_review_adapter"]["path"]).is_file()
    assert Path(contract["input_bindings"]["runner"]["path"]).is_file()
    assert Path(preflight["runner"]["path"]).is_file()
    assert preflight["status"] == "cpu_native_preflight_failed_hard_audit"
    assert preflight["matrix_credit"] == 0
