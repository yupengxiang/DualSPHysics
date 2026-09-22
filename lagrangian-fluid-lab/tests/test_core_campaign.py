import json

from scripts.core_campaign import completion, load_evidence
from scripts.core_runtime import atomic_json, digest
import pytest


def test_empty_queue_never_completes_product(tmp_path):
    result = completion({}, tmp_path)
    assert not result["can_finalize"]
    assert result["unregistered_t1_case_runs"] == 432
    assert result["missing_material_case_runs"] == 288
    assert result["missing_target_material_case_runs"] == 288
    assert result["missing_target_material_case_runs"] == result["missing_material_case_runs"]
    assert result["missing_registered_material_case_runs"] == 0
    assert result["unregistered_material_case_runs"] == 288


def _write_evaluation(tmp_path, *, axis, run_id, case_id, **extra):
    payload = {"schema": "core.evaluation.v1", "execution_status": "complete",
               "axis": axis, "run_id": run_id, "case_id": case_id,
               "evaluation_mode": "formal", "formal_eligible": True,
               "diagnostic": False, "autonomous": True,
               "future_state_inputs": False,
               "registered_case_ids": [case_id], "selected_case_ids": [case_id],
               "registered_case_count": 1, "case_count": 1,
               "expected_frames": {case_id: 1},
               "cases": {
                   case_id: {
                       "score": {
                           "expected_frames": 1, "complete": True, "executed": True,
                           "failure_category": None, "selection_score": 0.0,
                       },
                       "rollout": {"expected_frames": 1, "frames_expected": 1},
                   },
               }}
    payload.update(extra)
    path = tmp_path / f"{axis}-{run_id}-{case_id}.json"
    atomic_json(path, payload)
    return {"path": path.name, "sha256": digest(path)}


def test_minimal_evaluation_receipt_cannot_count_as_completed_evaluation(tmp_path):
    reference = _write_evaluation(
        tmp_path, axis="T1", run_id="mlp-seed17", case_id="case-0")
    path = tmp_path / reference["path"]
    payload = json.loads(path.read_text())
    payload.pop("cases")
    atomic_json(path, payload)
    reference["sha256"] = digest(path)

    result = completion({"evaluations": [{"receipt": reference}]}, tmp_path)

    assert not result["checks"]["evidence_valid"]
    assert result["observed_t1_case_runs"] == 0
    assert any("score row is missing" in issue["reason"]
               for issue in result["issues"])


def test_unregistered_evaluations_do_not_shrink_any_target_denominator(tmp_path):
    registry = {"evaluations": [
        {"receipt": _write_evaluation(tmp_path, axis="T1", run_id="pilot-seed17",
                                       case_id="unregistered-t1")},
        {"receipt": _write_evaluation(tmp_path, axis="T2_macro", run_id="pilot-seed17",
                                       case_id="unregistered-material")},
    ]}

    result = completion(registry, tmp_path)

    assert not result["can_finalize"]
    assert result["missing_material_case_runs"] == 288
    assert result["missing_target_material_case_runs"] == 288
    assert result["missing_target_material_case_runs"] == result["missing_material_case_runs"]
    assert result["missing_target_t1_case_runs"] == 432
    assert result["unregistered_t1_case_runs"] == 432
    assert result["unregistered_material_case_runs"] == 288
    assert result["unregistered_t1_evidence_case_runs"] == 1
    assert result["unregistered_material_evidence_case_runs"] == 1
    assert not result["checks"]["evidence_valid"]
    assert all("outside the registered completion denominator" in issue["reason"]
               for issue in result["issues"])


def _qualified_scope_fixture(tmp_path, *, material=False, formal_material_receipt=None,
                            scope_id=None):
    scope_id = scope_id or ("scope-with-material" if material else "scope-t1-only")
    qualification_path = tmp_path / f"{scope_id}-qualification.json"
    atomic_json(qualification_path, {
        "schema": "core.qualification.v1", "scope_id": scope_id, "family": "F3",
        "T1_numerical": True, "extent": "parameter_range", "matrix_complete": True,
        "independent_checks_passed": True,
    })
    cases = []
    for index in range(32):
        case_id = f"{scope_id}-case-{index:02d}"
        audit_path = tmp_path / f"{case_id}-audit.json"
        atomic_json(audit_path, {
            "schema": "core.case_audit.v1", "case_id": case_id,
            "hard_integrity_pass": True,
        })
        row = {
            "case_id": case_id, "physical_case_id": case_id,
            "lineage_group_id": case_id,
            "split": "validation" if index < 16 else "train",
            "hard_integrity_pass": True, "T1_numerical": True,
            "audit": {"path": audit_path.name, "sha256": digest(audit_path)},
        }
        if material:
            sidecar_path = tmp_path / f"{case_id}-material.json"
            atomic_json(sidecar_path, {
                "schema": "core.material.sidecar.v1", "case_id": case_id,
                "macro_qualified": True, "window_complete": True,
                "source_coverage": [{"source_id": "source-0", "initial_mass_kg": 1.0,
                                      "unknown_fraction_max": 0.0}],
            })
            row["material_audit"] = {
                "path": sidecar_path.name, "sha256": digest(sidecar_path),
            }
        cases.append(row)
    scope = {
        "scope_id": scope_id, "family": "F3",
        "qualification": {"path": qualification_path.name, "sha256": digest(qualification_path)},
        "cases": cases,
    }
    if material:
        material_path = tmp_path / f"{scope_id}-material-qualification.json"
        material_payload = {
            "schema": "core.material_qualification.v1", "scope_id": scope_id,
            "T2_macro": True, "extent": "parameter_range", "matrix_complete": True,
            "required_source_ids": ["source-0"],
            "maximum_source_unknown_fraction": 0.01,
        }
        if formal_material_receipt is not None:
            material_payload["formal_acceptance_receipt"] = formal_material_receipt
        atomic_json(material_path, material_payload)
        scope["material_qualification"] = {
            "path": material_path.name, "sha256": digest(material_path),
        }
    return scope


def test_material_scope_without_formal_acceptance_receipt_is_not_qualified(tmp_path):
    registry = {"scopes": [_qualified_scope_fixture(tmp_path, material=True)]}

    result = completion(registry, tmp_path)

    assert not result["macro_t2_families"]
    assert result["required_material_case_runs"] == 0
    assert result["unregistered_material_case_runs"] == 288
    assert any("formal acceptance receipt is missing" in issue["reason"]
               for issue in result["issues"])


def test_material_formal_receipt_without_passed_root_review_is_not_qualified(tmp_path):
    registry = {"scopes": [_qualified_scope_fixture(
        tmp_path, material=True,
        formal_material_receipt={"status": "accepted", "T2_macro": True},
    )]}

    result = completion(registry, tmp_path)

    assert not result["macro_t2_families"]
    assert result["required_material_case_runs"] == 0
    assert any("root review is missing" in issue["reason"]
               for issue in result["issues"])


def _formal_training_receipt(tmp_path, run_id, *, include_evidence=True, checkpoint_path=None):
    checkpoint_path = checkpoint_path or (tmp_path / f"{run_id}.pt")
    checkpoint_path.write_bytes(b"temporary checkpoint fixture")
    checkpoint_reference = (
        checkpoint_path.name
        if checkpoint_path.resolve().parent == tmp_path.resolve()
        else str(checkpoint_path)
    )
    receipt = {
        "schema": "core.training.v1", "run_id": run_id,
        "completed_updates": 32000, "checkpoint_verified": True,
        "config": {
            "manifest_formal_release": True, "validation_formal_eligible": True,
            "evaluate_milestones": True,
            "validation_family_counts": {"F1": 4, "F3": 4, "F4": 4},
        },
        "checkpoint": {
            "schema": "core.checkpoint.v1", "update": 32000,
            "path": checkpoint_reference, "sha256": digest(checkpoint_path),
        },
    }
    if include_evidence:
        receipt["evidence_status"] = "complete"
        receipt["evidence"] = {"schema": "core.training.evidence.v1", "status": "complete"}
    receipt_path = tmp_path / f"{run_id}-training.json"
    atomic_json(receipt_path, receipt)
    return {"path": receipt_path.name, "sha256": digest(receipt_path)}


def test_unknown_training_run_cannot_count_as_formal_run(tmp_path):
    registry = {"training_runs": [{
        "run_id": "mlp-seed17-diagnostic",
        "receipt": _formal_training_receipt(tmp_path, "mlp-seed17-diagnostic"),
    }]}

    result = completion(registry, tmp_path)

    assert result["training_runs"] == []
    assert result["missing_training_runs"] == sorted(
        {"mlp-seed17", "mlp-seed29", "mlp-seed43",
         "graph_raw-seed17", "graph_raw-seed29", "graph_raw-seed43",
         "graph_residual-seed17", "graph_residual-seed29", "graph_residual-seed43"})
    assert not result["checks"]["nine_formal_training_runs"]
    assert any("not in expected formal run denominator" in issue["reason"]
               for issue in result["issues"])


def test_missing_formal_training_evidence_receipt_cannot_count(tmp_path):
    registry = {"training_runs": [{
        "run_id": "mlp-seed17",
        "receipt": _formal_training_receipt(tmp_path, "mlp-seed17", include_evidence=False),
    }]}

    result = completion(registry, tmp_path)

    assert result["training_runs"] == []
    assert not result["checks"]["nine_formal_training_runs"]
    assert any("evidence receipt is missing or incomplete" in issue["reason"]
               for issue in result["issues"])


def test_checkpoint_outside_data_root_cannot_be_formal_evidence(tmp_path):
    outside = tmp_path.parent / "outside-checkpoint.pt"
    outside.write_bytes(b"outside temporary checkpoint fixture")
    receipt_ref = _formal_training_receipt(tmp_path, "mlp-seed17", checkpoint_path=outside)
    registry = {"training_runs": [{"run_id": "mlp-seed17", "receipt": receipt_ref}]}

    result = completion(registry, tmp_path)

    assert result["training_runs"] == []
    assert any("checkpoint path must be portable" in issue["reason"]
               for issue in result["issues"])


def test_report_existence_or_job_success_is_not_qualification(tmp_path):
    path = tmp_path / "report.json"
    atomic_json(path, {"execution_status": "succeeded", "T1_numerical": True})
    registry = {"scopes": [{"scope_id": "F3", "family": "F3", "qualification": {"path": "report.json", "sha256": digest(path)}}]}
    result = completion(registry, tmp_path)
    assert not result["can_finalize"]
    assert not result["t1_families"]
    assert "schema" in result["issues"][0]["reason"]


def test_scope_family_must_match_qualification_family(tmp_path):
    scope = _qualified_scope_fixture(tmp_path)
    scope["family"] = "F4"

    result = completion({"scopes": [scope]}, tmp_path)

    assert not result["t1_families"]
    assert not result["checks"]["evidence_valid"]
    assert any("schema/scope mismatch" in issue["reason"]
               for issue in result["issues"])


def test_case_identity_cannot_be_reused_across_scopes(tmp_path):
    first = _qualified_scope_fixture(tmp_path, scope_id="scope-first")
    second = _qualified_scope_fixture(tmp_path, scope_id="scope-second")
    second["scope_id"] = "scope-second"
    second_qualification = tmp_path / "scope-second-qualification.json"
    atomic_json(second_qualification, {
        "schema": "core.qualification.v1", "scope_id": "scope-second", "family": "F4",
        "T1_numerical": True, "extent": "parameter_range", "matrix_complete": True,
        "independent_checks_passed": True,
    })
    second["family"] = "F4"
    second["qualification"] = {
        "path": second_qualification.name, "sha256": digest(second_qualification),
    }
    for source, duplicate in zip(first["cases"], second["cases"]):
        duplicate["case_id"] = source["case_id"]
        duplicate["physical_case_id"] = source["physical_case_id"]
        duplicate["audit"] = source["audit"]

    result = completion({"scopes": [first, second]}, tmp_path)

    assert result["t1_families"] == ["F3"]
    assert not result["checks"]["evidence_valid"]
    assert any("registered in multiple scopes" in issue["reason"]
               for issue in result["issues"])


def test_training_validation_counts_must_bind_to_registered_families(tmp_path):
    scope = _qualified_scope_fixture(tmp_path)
    receipt = _formal_training_receipt(tmp_path, "mlp-seed17")
    registry = {
        "scopes": [scope],
        "training_runs": [{"run_id": "mlp-seed17", "receipt": receipt}],
    }

    result = completion(registry, tmp_path)

    assert result["training_runs"] == []
    assert any("exactly the registered families" in issue["reason"]
               for issue in result["issues"])


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
