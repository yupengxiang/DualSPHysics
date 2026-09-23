"""Regression tests for the F4 supportcap CPU canary authorization boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f4_supportcap_affine_query_bound_cpu_canary_authorization_v1 as authorization


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_authorization_is_hash_closed_and_requires_later_execution_authority() -> None:
    value = authorization.verify()
    assert value["authorization"]["candidate_id"] == "f4_supportcap_affine_query_bound_v3"
    assert value["authorization"]["authorization_grants_runtime_execution"] is False
    assert value["execution_contract"]["future_executor_status"] == "not_implemented_or_authorized_by_this_record"
    assert value["qualification_boundary"] == {
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "credit": 0,
        "material_qualification": False,
        "qualification_claim": "none",
    }
    for item in value["hash_bindings"].values():
        path = ROOT / item["path"]
        assert path.is_file() and path.stat().st_size == item["bytes"]
        assert _sha256(path) == item["sha256"]


def test_contract_is_one_attempt_new_namespace_and_preserves_failure_evidence() -> None:
    value = json.loads(authorization.OUTPUT.read_text(encoding="utf-8"))
    attempt = value["one_attempt_contract"]
    assert attempt["max_attempts"] == 1
    assert attempt["retry"] is False
    assert attempt["old_output_reuse_forbidden"] is True
    assert attempt["old_failure_evidence_modification_forbidden"] is True
    assert not (ROOT / attempt["new_output_namespace"]).exists()
    assert all(item["exists"] is False for item in attempt["planned_artifacts_absent_at_authorization"].values())
    assert value["input_contract"]["source"]["sha256"] == authorization.SOURCE_SHA256
    assert value["input_contract"]["bounded_canary"]["seed_denominator"] == 512
    assert value["acceptance_and_failure_semantics"]["failure_status"] == "failed_one_attempt_zero_credit"


def test_contract_has_no_runtime_side_effect_and_is_immutable() -> None:
    value = json.loads(authorization.OUTPUT.read_text(encoding="utf-8"))
    controls = value["execution_controls"]
    assert controls["canary_started"] is False
    assert controls["source_hdf5_opened"] is False
    assert controls["solver_started"] is False
    assert controls["gpu_started"] is False
    assert controls["worker_started"] is False
    assert all(controls[key] == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation"))
    with pytest.raises(FileExistsError, match="immutable CPU canary authorization"):
        authorization.write_authorization()
