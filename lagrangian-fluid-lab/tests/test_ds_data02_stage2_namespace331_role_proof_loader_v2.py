"""Role-proof-loader V2 tests, including real small ROOT200/V26 artifacts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_role_proof_loader_v2.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = _load(SCRIPT, "namespace331_role_proof_loader_v2_test")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _proof(tmp_path: Path, role: str, *, case: str = "CASE-1", region: str = "receiver") -> Path:
    value = {
        "schema": L.ROLE_PROOF_SCHEMA,
        "role_proof": {
            "semantic_role": role,
            "proof_status": "VERIFIED",
            "case_identity": {"family_id": "F1", "physical_case_id": case},
            "source_region": "initial_fluid",
            "target_region": region,
            "control_id": "CTRL-1",
            "source_sha256": "a" * 64,
        },
    }
    path = tmp_path / f"{role}.json"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def test_explicit_role_proof_derives_all_semantics_from_artifact(tmp_path: Path) -> None:
    path = _proof(tmp_path, "control")
    record = L.load_role_proof_artifact(
        path, expected_sha256=_sha(path), expected_role="control", family_id="F1",
        physical_case_id="CASE-1", expected_control_id="CTRL-1")
    assert record["status"] == "KNOWN"
    assert record["derived_semantic_role"] == "control"
    assert record["control_id"] == "CTRL-1"
    assert record["case_identity"]["physical_case_id"] == "CASE-1"


def test_caller_role_cannot_promote_different_artifact(tmp_path: Path) -> None:
    path = _proof(tmp_path, "control")
    record = L.load_role_proof_artifact(
        path, expected_sha256=_sha(path), expected_role="source", family_id="F1",
        physical_case_id="CASE-1", expected_current_sha256="a" * 64)
    assert record["status"] == "UNKNOWN"
    assert "artifact_role_does_not_match_requested_role" in record["unknown_reasons"]


def test_tampered_hash_and_unsafe_xml_fail_closed(tmp_path: Path) -> None:
    path = _proof(tmp_path, "source")
    with pytest.raises(L.RoleProofLoaderError, match="SHA differs"):
        L.load_role_proof_artifact(
            path, expected_sha256="b" * 64, expected_role="source", family_id="F1",
            physical_case_id="CASE-1", expected_current_sha256="a" * 64)
    xml = tmp_path / "unsafe.xml"
    xml.write_text("<!DOCTYPE case [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><case/>",
                   encoding="utf-8")
    with pytest.raises(L.RoleProofLoaderError, match="external entity"):
        L.load_role_proof_artifact(
            xml, expected_sha256=_sha(xml), expected_role="source", family_id="F1",
            physical_case_id="CASE-1")


def test_real_root200_source_owner_and_v26_region_artifacts_are_hash_bound(tmp_path: Path) -> None:
    primary = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
    root200 = primary / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F2_FRESH_V16_PROFILE_OUTPUT_ROOT_PROOF_V12_ACTUAL_ROOT_VERIFICATION_200.json"
    owner = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_140_f2_actual_native_typed157_home4gib_v1/owners/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010-actual-native-typed157-owner.json")
    v26 = primary / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v26-effective-condition-directory/cases/F2/078-F2.json"
    for path in (root200, owner, v26):
        if not path.is_file():
            pytest.skip(f"shared primary evidence is unavailable: {path}")
    common = {"family_id": "F2",
              "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"}
    source = L.load_role_proof_artifact(
        root200, expected_sha256=_sha(root200), expected_role="source", **common,
        expected_current_sha256="df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b")
    assert source["status"] == "KNOWN"
    control = L.load_role_proof_artifact(
        owner, expected_sha256=_sha(owner), expected_role="control", **common,
        expected_control_id="F2_CTRL_SMOOTH_ROTATE_Y_V1")
    assert control["status"] == "KNOWN"
    region = L.load_role_proof_artifact(
        v26, expected_sha256=_sha(v26), expected_role="region_owner", **common,
        expected_target_region="receiver")
    assert region["status"] == "UNKNOWN"
    assert "owner_artifact_has_no_explicit_region" in region["unknown_reasons"]


def test_real_artifacts_build_source_only_request_without_reading_typed_result(tmp_path: Path) -> None:
    primary = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
    root200 = primary / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F2_FRESH_V16_PROFILE_OUTPUT_ROOT_PROOF_V12_ACTUAL_ROOT_VERIFICATION_200.json"
    owner = Path("/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_140_f2_actual_native_typed157_home4gib_v1/owners/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010-actual-native-typed157-owner.json")
    v26 = primary / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v26-effective-condition-directory/cases/F2/078-F2.json"
    current = primary / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
    typed = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009/f2-s1-root200-v14-profile-output-001-root-forward-030-001/fresh-v16-proof-v12.json")
    paths = (root200, owner, v26, current, typed)
    for path in paths:
        if not path.exists():
            pytest.skip(f"shared primary evidence is unavailable: {path}")
    request = L.build_typed_event_request_v2(
        typed, typed_result_sha256="0eb798e28e62c7dc9524d6acfb950b19e8d9024544c8d8fcc61e78eb161e6269",
        current_binding={"path": str(current),
                         "sha256": "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"},
        role_artifacts=[
            {"role": "source", "path": str(root200), "sha256": _sha(root200)},
            {"role": "region_owner", "path": str(v26), "sha256": _sha(v26)},
            {"role": "control", "path": str(owner), "sha256": _sha(owner)},
        ], family_id="F2",
        physical_case_id="F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_ROT090".replace("RY014", "RY014_FILL080"),
        source_region="initial_fluid", target_region="receiver",
        control_id="F2_CTRL_SMOOTH_ROTATE_Y_V1",
        output_event_stream=tmp_path / "events.json")
    assert request["schema"] == L.REQUEST_SCHEMA
    assert request["status"] == "ROLE_PROOF_METADATA_PARTIAL_UNKNOWN"
    # ROOT200 proves the exact CURRENT/case source binding, but it does not
    # carry the requested source-region field; V2 therefore keeps it UNKNOWN.
    # The owner artifact proves the control condition, while V26 explicitly
    # leaves physical owner-region semantics unresolved.
    assert request["role_status"] == {"source": "UNKNOWN", "region_owner": "UNKNOWN", "control": "KNOWN"}
    assert request["typed_result"]["content_policy"].startswith("PARENT_GUARD")
    assert request["large_content_policy"]["typed_result_content_read_by_builder"] is False
