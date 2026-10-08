from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f2_v47_fresh_product_interface_v1.py"
spec = importlib.util.spec_from_file_location("v47_fresh_product_interface", SCRIPT)
assert spec is not None and spec.loader is not None
V47 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V47)

ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V47_ROOT = ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v47-parent-closure-root-082"
)
EXECUTOR = V47_ROOT / "f2-s1-portable-executor-request-v47-root-082.json"
PARENT = V47_ROOT / "f2-s1-portable-parent-request-v47-root-082.json"
VERIFICATION = V47_ROOT / "root-metadata-verification.json"


def _build(tmp_path: Path) -> tuple[dict, dict, Path, Path]:
    proof = tmp_path / "fresh-proof-staging.json"
    evaluator = tmp_path / "fresh-evaluator-staging.json"
    result = V47.build_pending_interfaces(
        v47_executor_request=EXECUTOR,
        v47_parent_request=PARENT,
        metadata_verification=VERIFICATION,
        proof_staging_output=proof,
        evaluator_staging_output=evaluator,
    )
    return (json.loads(proof.read_text(encoding="utf-8")),
            json.loads(evaluator.read_text(encoding="utf-8")), proof, evaluator)


@pytest.mark.skipif(not EXECUTOR.is_file() or not PARENT.is_file() or not VERIFICATION.is_file(),
                    reason="root V47 metadata fixtures are not present")
def test_real_v47_metadata_build_is_pending_and_does_not_claim_products(tmp_path: Path) -> None:
    proof, evaluator, proof_path, evaluator_path = _build(tmp_path)
    assert proof["schema"] == V47.PROOF_STAGING_SCHEMA
    assert proof["status"] == "PENDING_V47_PRODUCER_RESULT"
    assert evaluator["schema"] == V47.EVALUATOR_STAGING_SCHEMA
    assert evaluator["status"] == "BLOCKED_PENDING_FRESH_SEMANTIC_PROOF"
    assert proof["source_identity"]["actual_current_catalog_sha256"] == V47.ACTUAL_CURRENT_SHA
    assert proof["source_identity"]["relocated_runtime_view_sha256"] is None
    assert proof["evaluator_stage"]["run_allowed"] is False
    assert evaluator["evaluator_contract"]["evaluator_run_allowed"] is False
    assert evaluator["evaluator_contract"]["old_root060_result_or_proof_reuse"] == "FORBIDDEN"
    assert proof["execution_boundary"]["metadata_builder_payload_read"] is False
    assert evaluator["execution_boundary"]["hdf5_bi4_raw_read"] is False
    assert proof["qualification"] == V47.UNKNOWN
    assert evaluator["qualification"] == V47.UNKNOWN
    assert proof_path.is_file() and evaluator_path.is_file()

    for contract in (proof["expected_products"], evaluator["expected_products"]):
        for artifact in contract.values():
            assert artifact["sha256"] is None
            assert artifact["bytes"] is None
            assert artifact["stat"] is None
            assert artifact["content_sha256_deferred"] is True
    assert proof["fresh_proof_contract"]["old_proof_input"] is None
    assert proof["fresh_proof_contract"]["old_result_input"] is None


@pytest.mark.skipif(not EXECUTOR.is_file() or not PARENT.is_file() or not VERIFICATION.is_file(),
                    reason="root V47 metadata fixtures are not present")
def test_v47_builder_binds_physical_and_canonical_input_shas(tmp_path: Path) -> None:
    proof, evaluator, _, _ = _build(tmp_path)
    executor_ref = proof["input_bindings"]["executor_request"]
    parent_ref = proof["input_bindings"]["parent_request"]
    verification_ref = proof["input_bindings"]["root_metadata_verification"]
    assert executor_ref["physical_sha256"] == V47.sha256_file(EXECUTOR)
    assert parent_ref["physical_sha256"] == V47.sha256_file(PARENT)
    assert verification_ref["physical_sha256"] == V47.sha256_file(VERIFICATION)
    assert executor_ref["canonical_sha256"] == json.loads(EXECUTOR.read_text())["sha256"]
    assert parent_ref["canonical_sha256"] == json.loads(PARENT.read_text())["sha256"]
    assert verification_ref["canonical_sha256"] == json.loads(VERIFICATION.read_text())["canonical_sha256"]
    assert evaluator["proof_staging_interface"]["interface_only"] is True
    assert evaluator["proof_staging_interface"]["must_not_be_used_as_semantic_proof"] is True


@pytest.mark.skipif(not EXECUTOR.is_file() or not PARENT.is_file() or not VERIFICATION.is_file(),
                    reason="root V47 metadata fixtures are not present")
def test_v47_builder_refuses_existing_output_without_touching_v47_inputs(tmp_path: Path) -> None:
    proof = tmp_path / "existing-proof.json"
    evaluator = tmp_path / "new-evaluator.json"
    proof.write_text("sentinel\n", encoding="utf-8")
    before = V47.sha256_file(EXECUTOR)
    with pytest.raises(V47.V47FreshInterfaceError, match="existing proof/evaluator"):
        V47.build_pending_interfaces(
            v47_executor_request=EXECUTOR,
            v47_parent_request=PARENT,
            metadata_verification=VERIFICATION,
            proof_staging_output=proof,
            evaluator_staging_output=evaluator,
        )
    assert proof.read_text(encoding="utf-8") == "sentinel\n"
    assert V47.sha256_file(EXECUTOR) == before


@pytest.mark.skipif(not EXECUTOR.is_file() or not PARENT.is_file() or not VERIFICATION.is_file(),
                    reason="root V47 metadata fixtures are not present")
def test_v47_builder_rejects_tampered_metadata_without_payload_access(tmp_path: Path) -> None:
    bad = tmp_path / "bad-verification.json"
    value = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    value["execution"] = "ALREADY_RUN"
    bad.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(V47.V47FreshInterfaceError, match="no longer a pre-run record"):
        V47.build_pending_interfaces(
            v47_executor_request=EXECUTOR,
            v47_parent_request=PARENT,
            metadata_verification=bad,
            proof_staging_output=tmp_path / "proof.json",
            evaluator_staging_output=tmp_path / "evaluator.json",
        )
