"""ROOT191 V2 tests for the real ROOT197 inner/outer identity join.

The source request and producer metadata are real bounded JSON.  Terminal
reports are tiny manufactured evidence objects whose request hashes are
joined to those real identities; no V16/HDF5/native payload is opened.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v2.py"
ROOT_DATA_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab")
ROOT197_DIR = ROOT_DATA_WORKTREE / "campaigns/ds-data-02/stage2/requests/f2-root197-profile-fresh-proof-root-prepared-197-003"
ROOT197_INNER = ROOT197_DIR / "root197-profile-proof-request.json"
ROOT197_WRAPPER = ROOT_DATA_WORKTREE / "campaigns/ds-data-02/stage2/requests/f2-root197-profile-fresh-proof-root-forward-197-001.json"
PRODUCER_REQUEST = ROOT_DATA_WORKTREE / "campaigns/ds-data-02/stage2/requests/f2-s1-root145-v66-root179c-primary-prepared-003.json"


def load_module():
    spec = importlib.util.spec_from_file_location("root191_v2_test_module", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = load_module()


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def real_pair():
    if not ROOT197_INNER.is_file() or not ROOT197_WRAPPER.is_file() or not PRODUCER_REQUEST.is_file():
        pytest.skip("ROOT197/179C source metadata is not mounted")
    pair = S._load_pair(ROOT197_INNER, ROOT197_WRAPPER)
    return pair


def make_evidence(tmp_path: Path):
    pair = real_pair()
    producer_file_sha = S.sha256_file(PRODUCER_REQUEST)
    producer = {
        "schema": "ds02.stage2.f2-root179c.parent-report.v1",
        "status": "COMPLETED_PARENT_EXECUTOR",
        "request_sha256": producer_file_sha,
    }
    producer_receipt = {
        "schema": "ds02.stage2.f2-root179c.receipt.v1",
        "status": "COMPLETED_PARENT_EXECUTOR",
        "charge_status": "CLOSED",
        "request_sha256": producer_file_sha,
    }
    producer_proof = {
        "schema": "ds02.stage2.f2-root179c.root-proof.v1",
        "status": "PASS",
        "ledger_mutated": True,
        "request_sha256": producer_file_sha,
    }
    root197_file_sha = pair["wrapper_file_sha"]
    root_parent = write_json(tmp_path / "root197-parent.json", {
        "schema": "ds02.stage2.root197.parent-report.v1",
        "status": "COMPLETED_PARENT_EXECUTOR",
        "request_sha256": root197_file_sha,
    })
    root_receipt = write_json(tmp_path / "root197-receipt.json", {
        "schema": "ds02.stage2.root197.receipt.v1",
        "status": "COMPLETED_PARENT_EXECUTOR",
        "charge_status": "CLOSED",
        "request_sha256": root197_file_sha,
    })
    root_proof = write_json(tmp_path / "root197-proof.json", {
        "schema": "ds02.stage2.root197.root-proof.v1",
        "status": "PASS",
        "ledger_mutated": True,
        "request_sha256": root197_file_sha,
    })
    result = pair["inner"]["result"]
    proof = {
        "schema": S.V8_PROOF_SCHEMA,
        "status": "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN",
        "quality": dict(S.UNKNOWN),
        "qualification": dict(S.UNKNOWN),
        "execution": {"hdf5_or_bi4_content_read": False, "raw_opened": False},
        "v12_semantic_scope_adapter": {
            "schema": S.V12_FORWARD_SCHEMA,
            "sidecar_path": str(pair["sidecar_path"]),
            "sidecar_sha256": S.sha256_file(pair["sidecar_path"]),
            "normalized_for_v8_only": True,
            "original_result_bytes_unchanged": True,
        },
        "request": {"path": str(pair["inner_path"]), "sha256": pair["inner"]["sha256"]},
        "source_result": {"sha256": result["sha256"], "bytes": result["bytes"], "content_sha_verified": True},
        "source_binding": {"current_catalog_sha256": S.CURRENT_SHA},
    }
    proof["sha256"] = S.canonical_sha(proof)
    root_v12 = write_json(tmp_path / "root197-v12-proof.json", proof)
    return pair, {
        "root_parent": root_parent, "root_receipt": root_receipt, "root_proof": root_proof,
        "root_v12": root_v12,
        "producer_parent": write_json(tmp_path / "producer-parent.json", producer),
        "producer_receipt": write_json(tmp_path / "producer-receipt.json", producer_receipt),
        "producer_proof": write_json(tmp_path / "producer-proof.json", producer_proof),
    }


def build(tmp_path: Path):
    pair, evidence = make_evidence(tmp_path)
    output = tmp_path / "ROOT191_V2_request.json"
    value = S._build_request(
        root197_inner=ROOT197_INNER, root197_wrapper=ROOT197_WRAPPER,
        root197_parent_report=evidence["root_parent"], root197_receipt=evidence["root_receipt"],
        root197_root_proof=evidence["root_proof"], root197_v12_proof=evidence["root_v12"],
        producer_parent_report=evidence["producer_parent"], producer_receipt=evidence["producer_receipt"],
        producer_root_proof=evidence["producer_proof"], frozen_original_request=PRODUCER_REQUEST,
        output=output, case_id="STAGE2_F2_ROOT191_V2_TYPED_ONLY_NO_MODEL_20261009",
        attempt_id="f2-s1-root191-v2-typed-only-no-model-001",
        fresh_output_root=tmp_path / "STAGE2_F2_ROOT191_V2_FRESH",
    )
    return pair, evidence, output, value


def test_real_root197_pair_requires_exact_forward_suffix():
    pair = real_pair()
    assert pair["outer_attempt"] == pair["inner_attempt"] + S.WRAPPER_SUFFIX
    assert pair["profile"]["profile_sha256"] == S.PROFILE_SHA
    assert pair["profile"]["current_catalog_sha256"] == S.CURRENT_SHA


def test_root191_v2_build_and_validate_joins_all_terminal_evidence(tmp_path: Path):
    _pair, _evidence, output, built = build(tmp_path)
    assert built["payload_read"] is False
    assert built["hdf5_or_bi4_read"] is False
    checked = S.validate_request(output)
    assert checked["status"] == "ROOT191_V2_METADATA_VALIDATED_READY_FOR_PARENT"
    assert checked["root197_v12_proof"]["file_sha256"] == S.sha256_file(_evidence["root_v12"])
    assert not (tmp_path / "STAGE2_F2_ROOT191_V2_FRESH").exists()


def test_root191_v2_rejects_arbitrary_wrapper_suffix(tmp_path: Path):
    pair = real_pair()
    wrapper = json.loads(ROOT197_WRAPPER.read_text(encoding="utf-8"))
    wrapper["attempt_id"] = pair["inner_attempt"] + "-root-forward-031-001"
    bad = write_json(tmp_path / "bad-wrapper.json", wrapper)
    with pytest.raises(S.Root191V2Error, match="exact forward suffix"):
        S._load_pair(ROOT197_INNER, bad)


def test_root191_v2_rejects_changed_inner_sha_binding(tmp_path: Path):
    wrapper = json.loads(ROOT197_WRAPPER.read_text(encoding="utf-8"))
    wrapper["consumer_request_binding"]["sha256"] = "0" * 64
    bad = write_json(tmp_path / "bad-sha-wrapper.json", wrapper)
    with pytest.raises(S.Root191V2Error, match="inner file/canonical SHA"):
        S._load_pair(ROOT197_INNER, bad)
