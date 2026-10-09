from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_role_proof_loader_v3.py"
SPEC = importlib.util.spec_from_file_location("namespace331_role_proof_loader_v3_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
L = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(L)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return _sha(path)


def _proof(tmp_path: Path, *, closure: bool, role: str = "control") -> tuple[Path, str]:
    case = {"family_id": "F1", "physical_case_id": "CASE-1"}
    request = tmp_path / "producer-request.json"
    source = tmp_path / "source-contract.json"
    source_doc = {"schema": L.FIXTURE_SOURCE_CONTRACT_SCHEMA, "status": "SOURCE_BOUND",
                  "case_identity": case, "semantic_role": role,
                  "source_region": "initial_fluid", "target_region": "receiver",
                  "control_id": "CTRL-1", "content_sha256": "a" * 64}
    source_sha = _json(source, source_doc)
    proof = {
        "schema": L.ROLE_PROOF_SCHEMA,
        "role_proof": {
            "semantic_role": role,
            "proof_status": "VERIFIED",
            "case_identity": case,
            "source_region": "initial_fluid",
            "target_region": "receiver",
            "control_id": "CTRL-1",
            "source_sha256": "a" * 64,
        },
    }
    if closure:
        request_doc = {"schema": L.FIXTURE_PRODUCER_REQUEST_SCHEMA, "status": "COMPLETED",
                       "producer_id": "TINY-PRODUCER-1", "case_identity": case,
                       "input_sha256": {"source_contract": {"path": str(source),
                                                             "sha256": source_sha}}}
        request_sha = _json(request, request_doc)
        proof["role_proof"]["producer_source_closure"] = {
            "producer_id": "TINY-PRODUCER-1",
            "producer_request": {"path": str(request), "sha256": request_sha},
            "source_contract": {"path": str(source), "sha256": source_sha},
        }
    path = tmp_path / "role-proof.json"
    return path, _json(path, proof)


def test_v3_one_pass_stat_and_producer_closure_are_required(tmp_path: Path) -> None:
    path, digest = _proof(tmp_path, closure=True)
    record = L.load_role_proof_artifact(
        path, expected_sha256=digest, expected_role="control", family_id="F1",
        physical_case_id="CASE-1", expected_control_id="CTRL-1")
    assert record["status"] == "KNOWN"
    assert record["producer_source_closure"]["producer_id"] == "TINY-PRODUCER-1"
    assert record["artifact_stat_pre"] == record["artifact_stat_post"]
    assert set(record["artifact_stat_pre"]) == {"st_dev", "st_ino", "size", "mtime_ns", "ctime_ns"}
    assert record["artifact_sha256"] == digest


def test_v3_generic_caller_strings_without_closure_stay_unknown(tmp_path: Path) -> None:
    path, digest = _proof(tmp_path, closure=False)
    record = L.load_role_proof_artifact(
        path, expected_sha256=digest, expected_role="control", family_id="F1",
        physical_case_id="CASE-1", expected_control_id="CTRL-1")
    assert record["status"] == "UNKNOWN"
    assert "generic_role_proof_missing_producer_source_closure" in record["unknown_reasons"]


def test_v3_rejects_symlink_and_wrong_expected_digest(tmp_path: Path) -> None:
    path, digest = _proof(tmp_path, closure=True)
    link = tmp_path / "role-link.json"
    link.symlink_to(path)
    with pytest.raises(L.RoleProofLoaderV3Error, match="symlink"):
        L.load_role_proof_artifact(
            link, expected_sha256=digest, expected_role="control", family_id="F1",
            physical_case_id="CASE-1", expected_control_id="CTRL-1")
    with pytest.raises(L.RoleProofLoaderV3Error, match="SHA differs"):
        L.load_role_proof_artifact(
            path, expected_sha256="b" * 64, expected_role="control", family_id="F1",
            physical_case_id="CASE-1", expected_control_id="CTRL-1")


def test_v3_accepts_real_root200_source_artifact_with_one_pass_stats() -> None:
    primary = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
    artifact = primary / (
        "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/"
        "F2_FRESH_V16_PROFILE_OUTPUT_ROOT_PROOF_V12_ACTUAL_ROOT_VERIFICATION_200.json"
    )
    if not artifact.is_file():
        pytest.skip(f"shared primary evidence is unavailable: {artifact}")
    record = L.load_role_proof_artifact(
        artifact, expected_sha256=_sha(artifact), expected_role="source", family_id="F2",
        physical_case_id="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        expected_current_sha256="df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b")
    assert record["status"] == "KNOWN"
    assert record["artifact_stat_pre"] == record["artifact_stat_post"]
    assert "producer_source_closure" not in record


def test_v3_build_request_uses_v3_loader_and_keeps_typed_result_deferred(tmp_path: Path) -> None:
    # Three real closure-bearing tiny artifacts exercise the actual builder;
    # the typed result is only statted and remains outside the loader read.
    roles = []
    for role, region, control in (("source", "initial_fluid", None),
                                  ("region_owner", "receiver", None),
                                  ("control", "receiver", "CTRL-1")):
        role_dir = tmp_path / role
        role_dir.mkdir(exist_ok=True)
        path, digest = _proof(role_dir, closure=True, role=role)
        roles.append({"role": role, "path": str(path), "sha256": digest})
    typed = tmp_path / "typed-result.json"
    typed.write_text("{}", encoding="utf-8")
    current = tmp_path / "current.json"
    current.write_text("{}", encoding="utf-8")
    # Closure fixture source SHA is deterministic and role artifacts carry it.
    request = L.build_typed_event_request_v3(
        typed, typed_result_sha256=_sha(typed),
        current_binding={"path": str(current), "sha256": "a" * 64},
        role_artifacts=roles, family_id="F1", physical_case_id="CASE-1",
        source_region="initial_fluid", target_region="receiver", control_id="CTRL-1",
        output_event_stream=tmp_path / "events.json")
    assert request["schema"] == L.REQUEST_SCHEMA
    assert request["loader_schema"] == L.SCHEMA
    assert request["typed_result"]["content_policy"].startswith("PARENT_GUARD")
    assert request["role_status"] == {"source": "KNOWN", "region_owner": "KNOWN", "control": "KNOWN"}
