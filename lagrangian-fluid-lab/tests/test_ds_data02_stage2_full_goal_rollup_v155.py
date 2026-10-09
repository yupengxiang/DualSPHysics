from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_full_goal_rollup_v155.py"
SPEC = importlib.util.spec_from_file_location("full_goal_rollup_v155", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


def test_unknown_block_rejects_scientific_credit() -> None:
    MODULE.unknown_block({"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "fixture")
    with pytest.raises(MODULE.RollupError, match="grants unsupported"):
        MODULE.unknown_block({"QN": "PASS"}, "fixture")
    with pytest.raises(MODULE.RollupError, match="physical credit"):
        MODULE.unknown_block({"physical_fate": "SPILL"}, "fixture")


def test_failed_and_pending_edges_keep_distinct_terminal_states(tmp_path: Path) -> None:
    pending_proof = _write(
        tmp_path / "pending-proof.json",
        {
            "schema": "ds02.stage2.managed-external-launch-boundary.v1",
            "status": "MANAGED_LAUNCH_REQUESTED_NOT_TERMINAL",
            "request": str(tmp_path / "pending-request.json"),
            "request_sha256": "placeholder",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    )
    pending_request = _write(tmp_path / "pending-request.json", {"schema": "ds02.request.v1"})
    pending_proof_data = json.loads(pending_proof.read_text())
    pending_proof_data["request_sha256"] = MODULE.sha256_file(pending_request)
    pending_proof.write_text(json.dumps(pending_proof_data) + "\n")
    paths = {"pending_proof": pending_proof, "pending_request": pending_request}
    values = {"pending_proof": pending_proof_data, "pending_request": json.loads(pending_request.read_text())}
    edge = MODULE.proof_edge(
        {
            "edge_id": "PENDING",
            "proof_key": "pending_proof",
            "request_key": "pending_request",
            "role": "fixture pending",
        },
        paths,
        values,
    )
    assert edge["kind"] == "pending_nonterminal"
    assert edge["scientific_credit"] == "NONE"

    failed_receipt = _write(
        tmp_path / "failed-receipt.json",
        {"schema": "ds02.execution-receipt.v1", "status": "failed", "returncode": 1},
    )
    failed_request = _write(tmp_path / "failed-request.json", {"schema": "ds02.request.v1"})
    failed_proof = _write(
        tmp_path / "failed-proof.json",
        {
            "schema": "ds02.stage2.root-actual-verification.v1",
            "status": "VERIFIED_ACTUAL_FAILED_BEFORE_DECODE",
            "request": str(failed_request),
            "request_sha256": MODULE.sha256_file(failed_request),
            "receipt": str(failed_receipt),
            "receipt_sha256": MODULE.sha256_file(failed_receipt),
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "root_array_content_read": False,
            "old_products_unchanged": True,
        },
    )
    paths.update({"failed_proof": failed_proof, "failed_request": failed_request, "failed_receipt": failed_receipt})
    values.update({"failed_proof": json.loads(failed_proof.read_text()), "failed_request": json.loads(failed_request.read_text()), "failed_receipt": json.loads(failed_receipt.read_text())})
    edge = MODULE.proof_edge(
        {
            "edge_id": "FAILED",
            "proof_key": "failed_proof",
            "request_key": "failed_request",
            "receipt_key": "failed_receipt",
            "role": "fixture failed",
        },
        paths,
        values,
    )
    assert edge["kind"] == "failed_attempt"
    assert edge["receipt_status"] == "failed"
    assert edge["scientific_credit"] == "NONE"


def test_explicit_completed_producer_status_is_terminal() -> None:
    receipt = {"schema": "ds02.stage2.external-solver-report.v5", "status": "COMPLETED_DEVELOPMENT_UNKNOWN"}
    assert MODULE.receipt_state(receipt, "producer") == "COMPLETED_DEVELOPMENT_UNKNOWN"
    assert MODULE.is_completed_status("COMPLETED_DEVELOPMENT_UNKNOWN")
    with pytest.raises(MODULE.RollupError, match="unknown status"):
        MODULE.receipt_state({"schema": "other", "status": "MAYBE_DONE"}, "producer")


def test_manifest_records_new_reference_cases_without_merging() -> None:
    manifest_path = SCRIPT_PATH.parents[1] / "campaigns" / "ds-data-02" / "stage2" / "requests" / "full-goal-rollup-v155-root-prepared-155-001" / "full-goal-rollup-v155-manifest.json"
    if not manifest_path.exists():
        pytest.skip("prepared manifest is supplied by the root integration checkout")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema"] == MODULE.MANIFEST_SCHEMA
    assert manifest["contract"]["original_current_cases"] == 336
    assert manifest["contract"]["original_native_identity_count"] == 1328
    assert set(manifest["contract"]["new_reference_cases_not_merged"]) == {
        "F2_ROOT126_ROOT129",
        "F2_ROOT138_DOMAIN_CONTROL",
        "F2_ROOT142_NATIVE_MOTIVES",
        "F2_ROOT145_FAILED_V55",
        "F3_ROOT150_FULL836",
        "F3_ROOT153_MIDDLE_METADATA",
        "F3_PHASE_RECOVERY_LEGACY",
        "F4_ROOT152_COMMON_TIME_GAPS",
        "F7_ROOT149_FACE_LATTICE",
        "F7_ROOT154_SELECTOR_CANDIDATE",
    }
    assert len(manifest["evidence_edges"]) == 19
    edges = {edge["edge_id"]: edge for edge in manifest["evidence_edges"]}
    assert edges["ROOT138_STREAM"]["proof_key"] == "root138_stream_proof"
    assert edges["ROOT142_MOTIVES"]["proof_key"] == "root142_proof"
    assert edges["ROOT133"]["superseded_by"] == "ROOT150"
    assert edges["ROOT140"]["superseded_by"] == "ROOT145"
    assert "request_key" not in edges["F3_PHASE_RECOVERY_LEGACY"]


def test_derived_edges_keep_stream_and_motive_products_distinct() -> None:
    manifest_path = SCRIPT_PATH.parents[1] / "campaigns" / "ds-data-02" / "stage2" / "requests" / "full-goal-rollup-v155-root-prepared-155-001" / "full-goal-rollup-v155-manifest.json"
    if not manifest_path.exists():
        pytest.skip("prepared manifest is supplied by the root integration checkout")
    result = MODULE.derive(manifest_path)
    edges = {edge["edge_id"]: edge for group in result["evidence_edges"].values() if isinstance(group, list) for edge in group}
    assert edges["ROOT138_STREAM"]["proof_status"].startswith("VERIFIED_ACTUAL_NUMERICAL_DOMAIN_CONTROL")
    assert edges["ROOT142_MOTIVES"]["proof_status"].startswith("VERIFIED_ACTUAL_F2_67_NATIVE_PER_ID")
    assert edges["ROOT138_STREAM"]["source"]["role"].startswith("F2 ROOT130 numerical")
    assert edges["ROOT142_MOTIVES"]["source"]["role"].startswith("F2 ROOT130 67-ID")
    assert edges["ROOT154_F7_SELECTOR_CANDIDATE"]["scientific_credit"] == "NONE"
