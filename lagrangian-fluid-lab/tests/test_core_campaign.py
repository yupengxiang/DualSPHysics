import json
import hashlib
import sys
from pathlib import Path

from scripts import core_campaign as campaign
from scripts.core_campaign import completion, load_evidence, main
from scripts.core_runtime import atomic_json, canonical, digest
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
    gaps = {item["gate"] for item in result["completion_gaps"]}
    assert {
        "three_t1_families", "two_macro_t2_families", "nine_formal_training_runs",
        "t1_denominator_complete", "material_denominator_complete",
        "independent_reproduction", "causal_lineage_contracts",
    } <= gaps
    assert result["issues"] == []


def test_status_is_read_only_unless_snapshot_write_is_explicit(tmp_path, monkeypatch, capsys):
    root = tmp_path / "campaign"
    root.mkdir()
    monkeypatch.setattr(sys, "argv", ["core_campaign.py", "--lab-root", str(tmp_path),
                                        "--root", str(root), "status"])
    main()
    assert not (root / "completion.json").exists()
    json.loads(capsys.readouterr().out)

    monkeypatch.setattr(sys, "argv", ["core_campaign.py", "--lab-root", str(tmp_path),
                                        "--root", str(root), "status", "--write-snapshot"])
    main()
    snapshot = root / "completion.json"
    assert snapshot.is_file()
    assert "completion_gaps" in json.loads(snapshot.read_text())


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


_REPRODUCTION_CLAIM_FIELDS = (
    "source_host", "reproduction_host", "source_data_root", "reproduction_data_root",
    "diagnostic_only", "cross_host_reproduction", "full_horizon_reproduction",
    "full_product_reproduction", "reader_reproduced", "prediction_reproduced",
    "scoring_reproduced", "predictor_future_state_inputs",
)


def _write_json_reference(tmp_path, name, payload):
    path = tmp_path / name
    atomic_json(path, payload)
    return {"path": path.name, "sha256": digest(path)}


def _reproduction_review_binding(receipt):
    return {
        "claims": {field: receipt[field] for field in _REPRODUCTION_CLAIM_FIELDS},
        "supporting_evidence": receipt["supporting_evidence"],
    }


def _seal_reproduction_fixture(receipt_path, root_review_path, registry):
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    binding = _reproduction_review_binding(receipt)
    review = {
        "schema": "core.reproduction.root_review.v1",
        "status": "passed",
        "diagnostic_only": False,
        "full_core_reproduction_proven": True,
        "reviewed_binding_sha256": hashlib.sha256(canonical(binding).encode("utf-8")).hexdigest(),
        "verified_checks": {
            "distinct_physical_hosts": True,
            "distinct_data_roots": True,
            "reader_evidence_verified": True,
            "prediction_evidence_verified": True,
            "scoring_evidence_verified": True,
        },
    }
    atomic_json(root_review_path, review)
    receipt["root_review"] = {"path": root_review_path.name, "sha256": digest(root_review_path)}
    atomic_json(receipt_path, receipt)
    registry["independent_reproduction"] = {
        "path": receipt_path.name, "sha256": digest(receipt_path),
    }


def _reproduction_fixture(tmp_path, *, diagnostic_only, full_product_reproduction,
                          bind_root_review=True):
    source_data_root = "/datasets/core-source"
    reproduction_data_root = "/scratch/core-relocated"
    package_sha256 = "a" * 64
    source_manifest = _write_json_reference(tmp_path, "source-package.json", {
        "schema": "core.reproduction.package_manifest.v1",
        "data_root": source_data_root, "package_sha256": package_sha256,
    })
    reproduction_manifest = _write_json_reference(tmp_path, "relocated-package.json", {
        "schema": "core.reproduction.package_manifest.v1",
        "data_root": reproduction_data_root, "package_sha256": package_sha256,
    })
    source_host_id, reproduction_host_id = "machine-source", "machine-independent"
    supporting_evidence = {
        "source_host": _write_json_reference(tmp_path, "source-host.json", {
            "schema": "core.reproduction.host_identity.v1", "passed": True,
            "hostname": "host-source", "physical_host_id": source_host_id,
        }),
        "reproduction_host": _write_json_reference(tmp_path, "reproduction-host.json", {
            "schema": "core.reproduction.host_identity.v1", "passed": True,
            "hostname": "host-independent", "physical_host_id": reproduction_host_id,
        }),
        "data_roots": _write_json_reference(tmp_path, "data-roots.json", {
            "schema": "core.reproduction.data_roots.v1", "passed": True,
            "source_data_root": source_data_root,
            "reproduction_data_root": reproduction_data_root,
            "different_data_root": True,
            "source_manifest": source_manifest,
            "reproduction_manifest": reproduction_manifest,
            "source_manifest_sha256": source_manifest["sha256"],
            "reproduction_manifest_sha256": reproduction_manifest["sha256"],
        }),
    }
    for component, claim in (("reader", "reader_reproduced"),
                             ("prediction", "prediction_reproduced"),
                             ("scoring", "scoring_reproduced")):
        component_claim_passes = full_product_reproduction
        evidence_payload = {
            "schema": "core.reproduction.component.v1",
            "component": component,
            "passed": component_claim_passes,
            claim: component_claim_passes,
            "physical_host_id": reproduction_host_id,
            "data_root": reproduction_data_root,
            "output_report": _write_json_reference(tmp_path, f"{component}-output.json", {
                "schema": {
                    "reader": "core.verification.v1",
                    "prediction": "core.model_reproduction.v1",
                    "scoring": "core.model_reproduction.score.v1",
                }[component],
                "passed": True,
                "full_horizon_reproduction": True,
                "full_product_reproduction": True,
                "predictor_future_state_inputs": False,
                "metrics": {
                    "registered_cases": 1,
                    "complete_fraction": 1.0,
                    "missing_execution": 0,
                },
                "cases": ["case-0"],
            }),
        }
        if component == "prediction":
            evidence_payload.update({
                "autonomous": True, "full_horizon": True, "future_state_inputs": False,
            })
        supporting_evidence[component] = _write_json_reference(
            tmp_path, f"{component}-evidence.json", evidence_payload)

    receipt_path = tmp_path / "reproduction.json"
    atomic_json(receipt_path, {
        "schema": "core.reproduction.v1",
        "passed": True,
        "diagnostic_only": diagnostic_only,
        "cross_host_reproduction": True,
        "full_horizon_reproduction": True,
        "full_product_reproduction": full_product_reproduction,
        "reader_reproduced": full_product_reproduction,
        "prediction_reproduced": full_product_reproduction,
        "scoring_reproduced": full_product_reproduction,
        "predictor_future_state_inputs": False,
        "source_host": "host-source",
        "reproduction_host": "host-independent",
        "source_data_root": source_data_root,
        "reproduction_data_root": reproduction_data_root,
        "supporting_evidence": supporting_evidence,
    })
    registry = {}
    if bind_root_review:
        root_review_path = tmp_path / "root-review.json"
        _seal_reproduction_fixture(receipt_path, root_review_path, registry)
    else:
        root_review_path = tmp_path / "root-review.json"
        atomic_json(root_review_path, {"status": "passed"})
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["root_review"] = {"path": root_review_path.name, "sha256": digest(root_review_path)}
        atomic_json(receipt_path, receipt)
        registry["independent_reproduction"] = {
            "path": receipt_path.name, "sha256": digest(receipt_path),
        }
    return registry


def test_diagnostic_cross_host_receipt_does_not_satisfy_independent_reproduction(tmp_path):
    registry = _reproduction_fixture(
        tmp_path, diagnostic_only=True, full_product_reproduction=False)

    result = completion(registry, tmp_path)

    assert result["checks"]["independent_reproduction"] is False
    gap = next(item for item in result["completion_gaps"] if item["gate"] == "independent_reproduction")
    assert "distinct data root" in gap["reason"]
    assert result["issues"] == []


def test_full_product_cross_host_reproduction_requires_relocated_reader_prediction_and_score(tmp_path):
    registry = _reproduction_fixture(
        tmp_path, diagnostic_only=False, full_product_reproduction=True)

    result = completion(registry, tmp_path)

    assert result["checks"]["independent_reproduction"] is True


def test_status_only_root_review_cannot_admit_unbound_product_claims(tmp_path):
    registry = _reproduction_fixture(
        tmp_path, diagnostic_only=False, full_product_reproduction=True,
        bind_root_review=False)

    result = completion(registry, tmp_path)

    assert result["checks"]["independent_reproduction"] is False


def test_review_binding_must_match_the_claims_and_hashed_component_evidence(tmp_path):
    registry = _reproduction_fixture(
        tmp_path, diagnostic_only=False, full_product_reproduction=True)
    receipt_path = tmp_path / "reproduction.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["supporting_evidence"].pop("reader")
    atomic_json(receipt_path, receipt)
    registry["independent_reproduction"]["sha256"] = digest(receipt_path)

    result = completion(registry, tmp_path)

    assert result["checks"]["independent_reproduction"] is False


def test_untyped_component_output_cannot_pass_even_with_a_fresh_root_review(tmp_path):
    registry = _reproduction_fixture(
        tmp_path, diagnostic_only=False, full_product_reproduction=True)
    receipt_path = tmp_path / "reproduction.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    reader_ref = receipt["supporting_evidence"]["reader"]
    reader_path = tmp_path / reader_ref["path"]
    reader = json.loads(reader_path.read_text(encoding="utf-8"))
    output_ref = reader["output_report"]
    output_path = tmp_path / output_ref["path"]
    atomic_json(output_path, {"status": "passed"})
    output_ref["sha256"] = digest(output_path)
    atomic_json(reader_path, reader)
    reader_ref["sha256"] = digest(reader_path)
    atomic_json(receipt_path, receipt)
    _seal_reproduction_fixture(receipt_path, tmp_path / "root-review.json", registry)

    result = completion(registry, tmp_path)

    assert result["checks"]["independent_reproduction"] is False


def test_different_hostnames_with_same_physical_host_identity_do_not_pass(tmp_path):
    registry = _reproduction_fixture(
        tmp_path, diagnostic_only=False, full_product_reproduction=True)
    receipt_path = tmp_path / "reproduction.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    source_host_ref = receipt["supporting_evidence"]["source_host"]
    source_host_path = tmp_path / source_host_ref["path"]
    source_host = json.loads(source_host_path.read_text(encoding="utf-8"))
    source_host["physical_host_id"] = "machine-independent"
    atomic_json(source_host_path, source_host)
    receipt["supporting_evidence"]["source_host"]["sha256"] = digest(source_host_path)
    atomic_json(receipt_path, receipt)
    _seal_reproduction_fixture(receipt_path, tmp_path / "root-review.json", registry)

    result = completion(registry, tmp_path)

    assert result["checks"]["independent_reproduction"] is False


def test_different_path_strings_for_same_canonical_data_root_do_not_pass(tmp_path):
    registry = _reproduction_fixture(
        tmp_path, diagnostic_only=False, full_product_reproduction=True)
    receipt_path = tmp_path / "reproduction.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    aliased_source_root = "/scratch/core-relocated/."
    source_manifest_ref = receipt["supporting_evidence"]["data_roots"]
    roots_path = tmp_path / source_manifest_ref["path"]
    roots = json.loads(roots_path.read_text(encoding="utf-8"))
    manifest_ref = roots["source_manifest"]
    manifest_path = tmp_path / manifest_ref["path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["data_root"] = aliased_source_root
    atomic_json(manifest_path, manifest)
    roots["source_manifest"]["sha256"] = digest(manifest_path)
    roots["source_manifest_sha256"] = digest(manifest_path)
    roots["source_data_root"] = aliased_source_root
    atomic_json(roots_path, roots)
    receipt["supporting_evidence"]["data_roots"]["sha256"] = digest(roots_path)
    receipt["source_data_root"] = aliased_source_root
    atomic_json(receipt_path, receipt)
    _seal_reproduction_fixture(receipt_path, tmp_path / "root-review.json", registry)

    result = completion(registry, tmp_path)

    assert result["checks"]["independent_reproduction"] is False


@pytest.mark.parametrize("field,value", [
    ("reproduction_data_root", "/datasets/core-source"),
    ("source_host", "host-independent"),
    ("reader_reproduced", False),
    ("prediction_reproduced", False),
    ("scoring_reproduced", False),
])
def test_reproduction_gate_rejects_same_host_root_or_missing_product_step(tmp_path, field, value):
    registry = _reproduction_fixture(
        tmp_path, diagnostic_only=False, full_product_reproduction=True)
    receipt_path = tmp_path / "reproduction.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt[field] = value
    atomic_json(receipt_path, receipt)
    registry["independent_reproduction"]["sha256"] = digest(receipt_path)

    result = completion(registry, tmp_path)

    assert result["checks"]["independent_reproduction"] is False


def test_current_registered_diagnostic_receipt_is_not_independent_reproduction():
    lab = Path(__file__).resolve().parents[1]
    registry = json.loads((lab / "campaigns/core-v1/registry.json").read_text(encoding="utf-8"))

    result = completion(registry, lab)

    assert result["checks"]["independent_reproduction"] is False


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


@pytest.mark.parametrize(("marker", "reason"), [
    ("diagnostic_only", "qualification-only/diagnostic"),
    ("qualification_only", "qualification-only/diagnostic"),
    ("root_review_only", "not root-admitted"),
    ("formal_eligible_false", "not formal evidence"),
])
def test_preflight_or_diagnostic_cannot_claim_qualification_credit(tmp_path, marker, reason):
    scope = _qualified_scope_fixture(tmp_path)
    qualification_path = tmp_path / scope["qualification"]["path"]
    receipt = json.loads(qualification_path.read_text(encoding="utf-8"))
    receipt.update({
        "status": "cpu_native_preflight_passed_zero_credit",
        "qualification_credit": 0,
        "T1_numerical": True,
    })
    if marker == "formal_eligible_false":
        receipt["formal_eligible"] = False
    else:
        receipt[marker] = True
    atomic_json(qualification_path, receipt)
    scope["qualification"]["sha256"] = digest(qualification_path)

    result = completion({"scopes": [scope]}, tmp_path)

    assert result["t1_families"] == []
    assert result["required_t1_case_runs"] == 0
    assert result["missing_target_t1_case_runs"] == 432
    assert not result["checks"]["three_t1_families"]
    assert not result["checks"]["evidence_valid"]
    assert any(reason in issue["reason"] for issue in result["issues"])


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


@pytest.mark.parametrize("entry_key", ["scope_studies", "scopes"])
def test_synthetic_qualification_schema_rejected_before_gate_markers(
    tmp_path, monkeypatch, entry_key,
):
    reads = []

    class SchemaReadProbe(dict):
        def get(self, key, default=None):
            reads.append(key)
            if key in {
                "qualification_only", "diagnostic_only", "formal_eligible",
                "formal_release", "formal", "root_review_only", "root_admitted",
                "root_admission", "root_review", "T1_numerical", "matrix_complete",
            }:
                raise AssertionError(f"gate marker read before schema rejection: {key}")
            if key == "schema":
                return "core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v8"
            return default

    monkeypatch.setattr(campaign, "load_evidence", lambda *_args: SchemaReadProbe())
    ref = {"path": "synthetic.json", "sha256": "0" * 64}
    if entry_key == "scope_studies":
        registration = {"scope_id": "synthetic-scope", "family": "F8",
                        "qualification": ref}
    else:
        registration = {"scope_id": "synthetic-scope", "family": "F8",
                        "qualification": ref, "cases": []}

    result = completion({entry_key: [registration]}, tmp_path)

    assert reads == ["schema"]
    assert result["scope_studies"] == []
    assert result["t1_families"] == []
    assert any("schema mismatch" in issue["reason"] for issue in result["issues"])


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
