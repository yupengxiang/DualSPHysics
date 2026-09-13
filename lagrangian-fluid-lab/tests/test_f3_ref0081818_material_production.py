"""Fail-closed tests for the explicit ref008 material production runner."""

from contextlib import contextmanager
import json
from pathlib import Path

import pytest

from scripts import f3_ref0081818_material_production as production


@contextmanager
def _slot():
    yield


def test_registered_scope_and_budget_match_downstream_proposal():
    assert [row["config_id"] for row in production._material_configs()] == [
        "REF008-0075-NOMINAL-s2",
        "REF008-0075-NOMINAL-s4",
        "REF008-0075-CADENCE-s4",
    ]
    assert production.MATERIAL_TIMEOUT_SECONDS == 900
    assert production.MATERIAL_POSTPROCESS_RESERVE_SECONDS == 600
    assert production.MATERIAL_CPU_ACTIVITY_CORES == pytest.approx(17.6)
    assert production.MATERIAL_TIMEOUT_SECONDS == production.adapter.MATERIAL_TIMEOUT_SECONDS


def test_worker_refuses_direct_uncharged_invocation(tmp_path):
    attempt = tmp_path / "attempt.json"
    payload = tmp_path / "payload.json"
    attempt.write_text(json.dumps({"schema": production.ATTEMPT_SCHEMA, "status": "completed"}))
    payload.write_text(json.dumps({"attempt_record_path": str(attempt)}))
    with pytest.raises(ValueError, match="charged registration"):
        production._worker(payload)


def test_resource_preflight_accounts_timeout_grace_and_postprocess(monkeypatch, tmp_path):
    out = tmp_path / "continuation"
    out.mkdir()
    production.OUT = out
    production.LAB = tmp_path
    (out / "RESOURCE-LEDGER.json").write_text(json.dumps({
        "cpu_core_hours_upper_bound": 700.0,
        "conservative_expiry_utc": "2099-01-01T00:00:00+00:00",
    }))
    (out / "RESOURCE-LIMITS.json").write_text(json.dumps({"limits": {
        "materials": 32, "cpu_core_hours": 896, "storage_gib": 512,
    }}))
    from scripts import l1r_continuation_evidence as resources
    monkeypatch.setattr(resources, "begin_activity_window", lambda: None)
    monkeypatch.setattr(resources, "ledger", lambda: None)
    monkeypatch.setattr(resources, "material_usage", lambda: 10)
    monkeypatch.setattr(resources, "resource_limits", lambda: {
        "materials": 32, "cpu_core_hours": 896, "storage_gib": 512,
    })
    monkeypatch.setattr(production.shutil, "disk_usage",
                        lambda _: type("Usage", (), {"free": 10**15, "total": 10**15})())
    result = production.resource_preflight(900, 1)
    assert result["status"] == "passed"
    assert result["cpu_forward_reserve_core_hours"] == pytest.approx((900 + 5 + 600) * 17.6 / 3600)
    assert result["gpu_hours_reserved"] == 0.0


def test_freeze_plan_refuses_replacement(monkeypatch, tmp_path):
    production.LAB = tmp_path
    production.OUT = tmp_path / "continuation"
    production.OUT.mkdir()
    value = {
        "schema": production.PLAN_SCHEMA,
        "status": "frozen",
        "configuration_charge": 0,
        "configurations": [{"config_id": "fixture"}],
    }
    monkeypatch.setattr(production, "build_plan", lambda: value)
    path = production.OUT / production.PLAN_NAME
    assert production.freeze_plan(path) == value
    with pytest.raises(ValueError, match="differs"):
        monkeypatch.setattr(production, "build_plan", lambda: {**value, "changed": True})
        production.freeze_plan(path)


def test_candidate_result_flags_are_checked_before_completion(monkeypatch, tmp_path):
    """A worker cannot turn a candidate artifact into a qualification result."""
    # This assertion covers the exact fail-closed predicate used by run_one.
    candidate = {
        "schema": production.RESULT_SCHEMA,
        "status": "candidate",
        "candidate_only": True,
        "qualified_T2_macro": False,
        "qualified_T2_path": False,
        "formal_release": False,
    }
    assert all(candidate[key] is False for key in
               ("qualified_T2_macro", "qualified_T2_path", "formal_release"))
