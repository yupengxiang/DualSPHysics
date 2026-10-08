from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_final_family_product_assembler_v27.py"
SPEC = importlib.util.spec_from_file_location("stage2_final_family_product_v27", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
CONSUMERS = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-consumers/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FORENSICS = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-forensics/DualSPHysics")
CURRENT = FORENSICS / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
V25_PROOF = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/SOURCE_CLOSED_DEVELOPMENT_SPLIT_V25_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
V25_ROOT = DATA / "families/infra/DS02_STAGE2_SOURCE_CLOSED_DEVELOPMENT_SPLIT_V25/current336-source-closed-development-split-v25-forward-001-root-forward-030-001"
RAW_STATE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/SEVEN_RAW_ANCHOR_ACTUAL_STATE_030.json"
RAW_INDEX = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/family-bundles-v1/six-family-native-raw-anchor-index-v1-001.json"
F2_ROOT = CONSUMERS / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v4"
QUALITY_MANIFEST = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/family-label-quality-v3/f1-f7-source-role-manifest-forward-001.json"
QUALITY_PROOF = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/SEVEN_FAMILY_QUALITY_EVALUATOR_V2_STRICT_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
QUALITY_ROOT = DATA / "families/infra/DS02_STAGE2_SEVEN_FAMILY_LABEL_QUALITY_EVALUATOR_V2_STRICT/seven-family-label-quality-evaluator-v2-strict-forward-001-root-forward-030-001"


def _actual_kwargs(tmp_path: Path) -> dict[str, Path]:
    return {
        "current_path": CURRENT,
        "v25_proof_path": V25_PROOF,
        "v25_report_path": V25_ROOT / "current336-source-closed-development-split-v25.json",
        "v25_manifest_path": V25_ROOT / "current336-task-evidence-manifest-v25.json",
        "v25_receipt_path": V25_ROOT / "execution-receipt.json",
        "raw_state_path": RAW_STATE,
        "raw_index_path": RAW_INDEX,
        "f2_bundle_path": F2_ROOT / "f2-s1-native-raw-to-label-bundle-v4-001.json",
        "f2_request_path": F2_ROOT / "f2-s1-native-raw-to-label-portable-request-v4-001.json",
        "quality_manifest_path": QUALITY_MANIFEST,
        "quality_proof_path": QUALITY_PROOF,
        "quality_report_path": QUALITY_ROOT / "seven-family-label-quality-evaluator-v2-strict.json",
        "quality_receipt_path": QUALITY_ROOT / "execution-receipt.json",
        "manifest_output": tmp_path / "final-family-product-manifest-v27.json",
        "output": tmp_path / "final-family-product-v27.json",
    }


INPUT_KEYS = tuple(key for key in _actual_kwargs(Path("/tmp")) if key not in {"manifest_output", "output"})


def test_fresh_small_inputs_list_and_map_are_normalized_without_aliasing():
    path = "/producer/CURRENT336.json"
    digest = "a" * 64
    assert MODULE._normalize_fresh_small_inputs([{"path": path, "sha256": digest}]) == [{"path": path, "sha256": digest}]
    assert MODULE._normalize_fresh_small_inputs({path: digest}) == [{"path": path, "sha256": digest}]
    assert MODULE._normalize_fresh_small_inputs({"entries": [{"path": path, "sha256": digest}]}) == [{"path": path, "sha256": digest}]
    with pytest.raises(MODULE.ProductError):
        MODULE._normalize_fresh_small_inputs({path: "b" * 63})


def test_actual_v25_proof_uses_forensics_current_path_and_rejects_same_bytes_alias(tmp_path: Path):
    if not all(path.exists() for path in (CURRENT, V25_PROOF, V25_ROOT / "current336-source-closed-development-split-v25.json", V25_ROOT / "current336-task-evidence-manifest-v25.json", V25_ROOT / "execution-receipt.json")):
        pytest.skip("shared actual v25 evidence is not mounted")
    proof_path, proof = MODULE._json(V25_PROOF, "v25 proof")
    report_path, report = MODULE._json(V25_ROOT / "current336-source-closed-development-split-v25.json", "v25 report")
    manifest_path, manifest = MODULE._json(V25_ROOT / "current336-task-evidence-manifest-v25.json", "v25 manifest")
    receipt_path, receipt = MODULE._json(V25_ROOT / "execution-receipt.json", "v25 receipt")
    summary = MODULE._validate_actual_v25(CURRENT, proof_path, proof, report_path, report, manifest_path, manifest, receipt_path, receipt)
    assert summary["producer_current"]["path"] == str(CURRENT)
    alias = tmp_path / "CURRENT336-alias.json"
    alias.write_bytes(CURRENT.read_bytes())
    with pytest.raises(MODULE.ProductError, match="exact producer path|v25 report CURRENT336"):
        MODULE._validate_actual_v25(alias, proof_path, proof, report_path, report, manifest_path, manifest, receipt_path, receipt)


def test_actual_json_only_assembler_exposes_336_and_preserves_unknowns(tmp_path: Path):
    paths = _actual_kwargs(tmp_path)
    if not all(paths[key].exists() for key in INPUT_KEYS):
        pytest.skip("shared actual Stage2 JSON evidence is not mounted")
    result = MODULE.build(**paths)
    assert result["coverage"]["current_case_count"] == 336
    assert result["coverage"]["hidden_current_cases"] == 0
    assert set(result["family_cards"]) == {f"F{i}" for i in range(1, 8)}
    assert result["family_cards"]["F3"]["failure_or_censoring"]["specific_parent_boundary"]["original_parent_replay"] == "NOT_RECOVERED"
    assert result["family_cards"]["F2"]["raw_reconstruction"]["raw_index_parent_slot"]["status"] == "F2_NATIVE_V4_TERMINAL_VERIFIED; EXECUTABLE_PORTABLE_V4_FORWARD"
    assert result["claim_boundary"]["physical_fate"] == "UNKNOWN"
    assert result["read_policy"]["original_trajectory_h5_opened_by_this_worker"] is False
    assert result["raw_anchor_index"]["f2_reference"]["bundle"]["index_declared_digest_matches"] is False
    assert all(Path(ref["path"]).suffix.lower() not in MODULE.FORBIDDEN_SUFFIXES for ref in result["inputs"]["source_refs"])


def test_v27_manifest_and_product_are_never_overwritten(tmp_path: Path):
    paths = _actual_kwargs(tmp_path)
    if not all(paths[key].exists() for key in INPUT_KEYS):
        pytest.skip("shared actual Stage2 evidence is not mounted")
    result = MODULE.build(**paths)
    assert json.loads(paths["output"].read_text())["schema"] == result["schema"]
    with pytest.raises(MODULE.ProductError, match="refusing to overwrite"):
        MODULE.build(**paths)
