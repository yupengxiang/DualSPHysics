import json

from scripts.core_campaign import completion, load_evidence
from scripts.core_runtime import atomic_json, digest
import pytest


def test_empty_queue_never_completes_product(tmp_path):
    result = completion({}, tmp_path)
    assert not result["can_finalize"]
    assert result["unregistered_t1_case_runs"] == 432
    assert result["missing_material_case_runs"] == 288
    assert result["missing_registered_material_case_runs"] == 0
    assert result["unregistered_material_case_runs"] == 288


def test_report_existence_or_job_success_is_not_qualification(tmp_path):
    path = tmp_path / "report.json"
    atomic_json(path, {"execution_status": "succeeded", "T1_numerical": True})
    registry = {"scopes": [{"scope_id": "F3", "family": "F3", "qualification": {"path": "report.json", "sha256": digest(path)}}]}
    result = completion(registry, tmp_path)
    assert not result["can_finalize"]
    assert not result["t1_families"]
    assert "schema" in result["issues"][0]["reason"]


def test_changed_evidence_rejected(tmp_path):
    path = tmp_path / "report.json"
    atomic_json(path, {"passed": True})
    ref = {"path": "report.json", "sha256": digest(path)}
    assert load_evidence(ref, tmp_path)["passed"]
    atomic_json(path, {"passed": False})
    with pytest.raises(ValueError, match="hash mismatch"):
        load_evidence(ref, tmp_path)
    with pytest.raises(ValueError, match="hashed evidence"):
        load_evidence({"path": "report.json", "irrelevant": 1}, tmp_path)


def test_small_training_attempt_cannot_count_as_formal_training(tmp_path):
    path = tmp_path / "run.json"
    atomic_json(path, {"schema": "core.training.v1", "run_id": "graph_raw-seed17",
                       "completed_updates": 16, "checkpoint_verified": True})
    result = completion({"training_runs": [{"run_id": "graph_raw-seed17", "receipt": {"path": "run.json", "sha256": digest(path)}}]}, tmp_path)
    assert not result["training_runs"]
    assert not result["checks"]["nine_formal_training_runs"]


def test_full_length_diagnostic_training_is_not_formal(tmp_path):
    path = tmp_path / "run.json"
    atomic_json(path, {"schema": "core.training.v1", "run_id": "mlp-seed17",
                       "completed_updates": 32000, "checkpoint_verified": True,
                       "config": {"manifest_formal_release": False,
                                  "validation_formal_eligible": False}})
    result = completion({"training_runs": [{"run_id": "mlp-seed17", "receipt": {
        "path": "run.json", "sha256": digest(path)}}]}, tmp_path)
    assert result["training_runs"] == []
    assert "formal data" in result["issues"][0]["reason"]


def test_formal_checkpoint_bytes_are_verified(tmp_path):
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"checkpoint-before-corruption")
    receipt = {"schema": "core.training.v1", "run_id": "mlp-seed17",
               "completed_updates": 32000, "checkpoint_verified": True,
               "config": {"manifest_formal_release": True, "validation_formal_eligible": True,
                          "evaluate_milestones": True,
                          "validation_family_counts": {"F1": 4, "F3": 4, "F4": 4}},
               "checkpoint": {"schema": "core.checkpoint.v1", "update": 32000,
                              "path": "model.pt", "sha256": digest(checkpoint)}}
    checkpoint.write_bytes(b"corrupt")
    path = tmp_path / "run.json"
    atomic_json(path, receipt)
    result = completion({"training_runs": [{"run_id": "mlp-seed17", "receipt": {
        "path": "run.json", "sha256": digest(path)}}]}, tmp_path)
    assert result["training_runs"] == []
    assert "checkpoint hash mismatch" in result["issues"][0]["reason"]


def test_completed_negative_scope_is_valid_evidence_not_product_completion(tmp_path):
    path=tmp_path/'negative.json'
    atomic_json(path,{'schema':'core.qualification.v1','scope_id':'floating_pool','family':'F4','matrix_complete':True,'T1_numerical':False})
    registry={'scope_studies':[{'scope_id':'floating_pool','family':'F4','qualification':{'path':'negative.json','sha256':digest(path)}}]}
    result=completion(registry,tmp_path)
    assert result['checks']['evidence_valid']
    assert result['scope_studies'][0]['status']=='completed_negative_result'
    assert result['t1_families']==[] and not result['can_finalize']


def test_contract_catalog_supplies_typed_audit_without_registry_mutation(tmp_path):
    evidence = tmp_path / "campaigns/core-v1/evidence/contract.json"
    atomic_json(evidence, {"schema": "core.contract_audit.v1", "passed": True})
    catalog = tmp_path / "campaigns/core-v1/contract-evidence.json"
    atomic_json(catalog, {"schema": "core.contract_evidence_index.v1", "contracts": {
        "causal_lineage_contracts": {
            "path": "campaigns/core-v1/evidence/contract.json",
            "sha256": digest(evidence),
        }
    }})
    result = completion({}, tmp_path)
    assert result["checks"]["causal_lineage_contracts"] is True
