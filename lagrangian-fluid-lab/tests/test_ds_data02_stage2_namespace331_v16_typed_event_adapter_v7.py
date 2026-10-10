from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_v16_typed_event_adapter_v7.py"
SPEC = importlib.util.spec_from_file_location("namespace331_v16_typed_event_adapter_v7_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
BASE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
PLAN = BASE / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY = BASE / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"
F5_CASE = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M105_T100"
S095_CASE = "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025"


def _fixture_helpers():
    path = ROOT / "tests/test_ds_data02_stage2_namespace331_v16_typed_event_adapter_v2.py"
    spec = importlib.util.spec_from_file_location("event_v2_fixture_helpers_for_v7", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(case_id: str, family: str) -> dict:
    fixture = _fixture_helpers()
    request = fixture._request()
    request["case_identity"]["physical_case_id"] = case_id
    request["case_identity"]["family_id"] = family
    request["lifecycle_scope"] = {
        "physical_case_id": case_id,
        "current_plan": {"path": str(PLAN), "file_sha256": hashlib.sha256(PLAN.read_bytes()).hexdigest()},
        "producer_registry": {"path": str(REGISTRY), "file_sha256": hashlib.sha256(REGISTRY.read_bytes()).hexdigest()},
    }
    request["request_sha256"] = MODULE.canonical_sha(request)
    return request


def test_real_root307_retry_lineage_selects_only_completed_terminal() -> None:
    context = MODULE.validate_request_v7(_request(F5_CASE, "F5"), allow_fixture=True)
    join = context["current_identity_scope"]["join"]
    assert join["plan_attempt_id"].startswith("root327-")
    assert join["producer_id"] == "ROOT327"
    assert join["failed_history_count"] == 1
    assert join["completed_producer_count"] == 1
    assert join["typed_label_admission"] is False
    assert context["production_eligible"] is False


def test_real_root307_single_lineage_s095_remains_supported() -> None:
    context = MODULE.validate_request_v7(_request(S095_CASE, "F6"), allow_fixture=True)
    join = context["current_identity_scope"]["join"]
    assert join["producer_id"] == "ROOT269"
    assert join["failed_history_count"] == 0
    assert join["source_closure"] == MODULE.SOURCE_CLOSURE


def test_crossed_retry_proof_is_rejected(tmp_path: Path) -> None:
    request = _request(F5_CASE, "F5")
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    root327 = next(item for item in registry["producers"] if item.get("producer_id") == "ROOT327")
    root269 = next(item for item in registry["producers"] if item.get("producer_id") == "ROOT269")
    root327["proof"] = copy.deepcopy(root269["proof"])
    bad_registry = tmp_path / "registry-crossed-proof.json"
    bad_registry.write_text(json.dumps(registry, sort_keys=True) + "\n", encoding="utf-8")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    plan["evidence_registry"] = {"path": str(bad_registry), "sha256": hashlib.sha256(bad_registry.read_bytes()).hexdigest()}
    bad_plan = tmp_path / "plan-crossed-proof.json"
    bad_plan.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")
    request["lifecycle_scope"]["current_plan"] = {
        "path": str(bad_plan), "file_sha256": hashlib.sha256(bad_plan.read_bytes()).hexdigest(),
    }
    request["lifecycle_scope"]["producer_registry"] = {
        "path": str(bad_registry), "file_sha256": hashlib.sha256(bad_registry.read_bytes()).hexdigest(),
    }
    request["request_sha256"] = MODULE.canonical_sha(request)
    with pytest.raises(MODULE.TypedEventAdapterV7Error, match="proof request path|proof request SHA"):
        MODULE.validate_request_v7(request, allow_fixture=True)

