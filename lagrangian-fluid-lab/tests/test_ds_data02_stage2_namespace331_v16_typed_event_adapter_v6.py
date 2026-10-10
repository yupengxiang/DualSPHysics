from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_v16_typed_event_adapter_v6.py"
SPEC = importlib.util.spec_from_file_location("namespace331_v16_typed_event_adapter_v6_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PLAN = PRIMARY / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
    "CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT306_V4.json"
)
REGISTRY = PRIMARY / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "typed-lifecycle-evidence-registry-v4-after-root306-001.json"
)


def _fixture_helpers():
    path = ROOT / "tests/test_ds_data02_stage2_namespace331_v16_typed_event_adapter_v2.py"
    spec = importlib.util.spec_from_file_location("event_v2_fixture_helpers_for_v6", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(case_id: str) -> dict:
    fixture = _fixture_helpers()
    request = fixture._request()
    request["case_identity"]["physical_case_id"] = case_id
    request["case_identity"]["family_id"] = "F6"
    request["lifecycle_scope"] = {
        "physical_case_id": case_id,
        "current_plan": {
            "path": str(PLAN),
            "file_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        },
        "producer_registry": {
            "path": str(REGISTRY),
            "file_sha256": hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
        },
    }
    request["request_sha256"] = MODULE.canonical_sha(request)
    return request


def test_real_v4_plan_registry_positive_s095_and_s200_without_payload() -> None:
    for case_id in (
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
    ):
        request = _request(case_id)
        context = MODULE.validate_request_v6(request, allow_fixture=True)
        scope = context["current_identity_scope"]
        assert scope["status"] == "CURRENT_EXACT_SAVED_MASK_COMPLETED"
        assert scope["join"]["status"] == "ACTUAL_SAVED_MASK_COMPLETED"
        assert scope["join"]["source_closure"] == MODULE.SOURCE_CLOSURE
        assert scope["typed_label_admission"] is False
        assert context["production_eligible"] is False
        assert context["qualification"] == MODULE.UNKNOWN_QUALIFICATION


def test_real_v4_scope_is_rejected_for_historical_alias(tmp_path: Path) -> None:
    request = _request("F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    row = next(row for row in plan["case_records"] if row["physical_case_id"] == request["case_identity"]["physical_case_id"])
    row["historical_alias"] = "HISTORICAL_ALIAS_UNRESOLVED"
    plan_copy = tmp_path / "plan-alias.json"
    plan_copy.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
    request["lifecycle_scope"]["current_plan"] = {
        "path": str(plan_copy),
        "file_sha256": hashlib.sha256(plan_copy.read_bytes()).hexdigest(),
    }
    request["request_sha256"] = MODULE.canonical_sha(request)
    with pytest.raises(MODULE.TypedEventAdapterV6Error, match="historical_alias"):
        MODULE.validate_request_v6(request, allow_fixture=True)


def test_v6_unknown_role_still_short_circuits_without_lifecycle_scope() -> None:
    fixture = _fixture_helpers()
    request = fixture._request(unknown_role="region_owner")
    result = MODULE.build_unknown_event_result_from_request(request, allow_fixture=True)
    assert result["schema"] == MODULE.UNKNOWN_ADMISSION_SCHEMA
    assert result["typed_content_read"] is False
    assert result["labels"] == []
    assert result["adapter"]["production_eligible"] is False

