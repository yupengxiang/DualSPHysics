from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import f8_r008_terminal_fanotify_profile_verifier_v1 as profiles


def _manifest() -> dict:
    raw = (profiles.LAB / profiles.MANIFEST).read_text(encoding="utf-8")
    return json.loads(raw)


def test_profile_schema_binds_v17_v18_and_remains_proposal_only() -> None:
    result = profiles.verify_profiles()
    assert result["status"] == "static_profile_schema_pass_no_runtime_conformance"
    assert result["group_kinds"] == ["permission", "name"]
    assert result["pidfd_required_for_both_groups"] is True
    assert result["target_abi_raw_values_pinned"] is False
    assert result["pinned_kernel_conformance_passed"] is False
    assert result["fanotify_syscall_invoked"] is False
    assert result["host_capability_or_filesystem_probed"] is False
    assert result["readiness_pass"] is False
    assert result["qualification_credit"] == 0
    assert len(result["profile_sha256"]) == 64
    assert {item["path"] for item in result["contract_bindings"]} == {
        profiles.V17.as_posix(), profiles.V18.as_posix()
    }


def test_profile_validator_rejects_pidfd_downgrade_and_unprivileged_name_profile() -> None:
    value = copy.deepcopy(_manifest())
    value["profiles"][1]["init_flags_symbolic"].remove("FAN_REPORT_PIDFD")
    with pytest.raises(profiles.ProfileVerificationError, match="frozen init_flags_symbolic|downgrade PIDFD"):
        profiles.validate_manifest(value)

    value = copy.deepcopy(_manifest())
    value["profiles"][1]["capability_prerequisite"] = {
        "capability": "none", "user_namespace": "none"
    }
    with pytest.raises(profiles.ProfileVerificationError, match="CAP_SYS_ADMIN"):
        profiles.validate_manifest(value)


def test_profile_validator_rejects_abi_value_promotion_and_readiness_claims() -> None:
    value = copy.deepcopy(_manifest())
    value["profiles"][0]["target_abi_raw_init_flags_hex"] = "0x0087"
    with pytest.raises(profiles.ProfileVerificationError, match="un-pinned target ABI"):
        profiles.validate_manifest(value)

    value = copy.deepcopy(_manifest())
    value["non_claims"]["readiness_pass"] = True
    with pytest.raises(profiles.ProfileVerificationError, match="may not claim runtime readiness"):
        profiles.validate_manifest(value)

    value = copy.deepcopy(_manifest())
    value["non_claims"]["qualification_credit"] = False
    with pytest.raises(profiles.ProfileVerificationError, match="JSON integer"):
        profiles.validate_manifest(value)

    value = copy.deepcopy(_manifest())
    value["non_claims"]["readiness_pass"] = 0
    with pytest.raises(profiles.ProfileVerificationError, match="JSON booleans"):
        profiles.validate_manifest(value)

    value = copy.deepcopy(_manifest())
    value["profiles"][0]["permission_event_support_required"] = 1
    with pytest.raises(profiles.ProfileVerificationError, match="JSON boolean"):
        profiles.validate_manifest(value)


def test_profile_contract_text_checker_rejects_missing_v18_name_capability() -> None:
    value = profiles.validate_manifest(_manifest())
    v17 = (profiles.LAB / profiles.V17).read_text(encoding="utf-8")
    v18 = (profiles.LAB / profiles.V18).read_text(encoding="utf-8")
    profiles.validate_contract_texts(value, v17, v18)
    altered = v18.replace("| name/FID | `CAP_SYS_ADMIN` 在 `init_user_ns` 中对真实 supervisor 有效（因 `FAN_REPORT_PIDFD`）", "| name/FID | no capability")
    with pytest.raises(profiles.ProfileVerificationError, match="V18 no longer contains required capability"):
        profiles.validate_contract_texts(value, v17, altered)


def test_profile_validator_rejects_duplicate_group_and_unknown_fields() -> None:
    value = copy.deepcopy(_manifest())
    value["profiles"][1]["group_kind"] = "permission"
    with pytest.raises(profiles.ProfileVerificationError, match="one permission and one name"):
        profiles.validate_manifest(value)

    value = copy.deepcopy(_manifest())
    value["profiles"][0]["runtime_ready"] = True
    with pytest.raises(profiles.ProfileVerificationError, match="exactly the frozen keys"):
        profiles.validate_manifest(value)
