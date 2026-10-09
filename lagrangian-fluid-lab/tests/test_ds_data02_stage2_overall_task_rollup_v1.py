from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_overall_task_rollup_v1.py"
MANIFEST = ROOT / (
    "campaigns/ds-data-02/stage2/requests/"
    "overall-task-rollup-v1-root-forward-136-001/overall-task-rollup-v1-manifest.json"
)


def module():
    spec = importlib.util.spec_from_file_location("overall_task_rollup_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def replacement_manifest(tmp_path: Path, key: str, replacement: dict) -> Path:
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["source_refs"] if item["key"] == key)
    replacement_path = tmp_path / f"{key}.json"
    replacement_path.write_text(json.dumps(replacement, ensure_ascii=False), encoding="utf-8")
    entry["path"] = str(replacement_path)
    entry["sha256"] = loaded.sha256_file(replacement_path)
    output = tmp_path / f"manifest-{key}.json"
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return output


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual ROOT136 source manifest is not present")
def test_actual_rollup_preserves_catalog_boundary_and_unknown_q():
    loaded = module()
    result = loaded.derive(MANIFEST)
    assert result["schema"] == "ds02.stage2.overall-task-rollup.v1"
    assert result["catalog_scope"]["coverage"]["current_cases"] == 336
    assert result["catalog_scope"]["coverage"]["native_alias_ids"] == 1328
    assert result["catalog_scope"]["coverage"]["family_cards"] == 7
    assert result["new_reference_scope"]["native_ids"] == 153
    assert result["new_reference_scope"]["merged_into_original_catalog"] is False
    assert result["actual_evidence"]["f2_root134"]["mass_screen"]["status"] == (
        "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003"
    )
    assert result["actual_evidence"]["f3_root128"]["scientific_q"]["QN"] == "UNKNOWN"
    assert result["actual_evidence"]["f5_root123"]["mass"]["gate"] == "HARDFAIL_OVER_TWO_PERCENT"
    assert result["claim_boundary"]["physical_fate"] == "UNKNOWN"
    assert result["claim_boundary"]["dynamics"] == "UNKNOWN"


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual ROOT136 source manifest is not present")
def test_rollup_rejects_merging_root126_case_into_original_catalog(tmp_path: Path):
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    path = next(item["path"] for item in manifest["source_refs"] if item["key"] == "root126_report")
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    report["case_key"] = "F1/F1_ECC_THICK_DBC_LOWER_HEAD_V1"
    bad_manifest = replacement_manifest(tmp_path, "root126_report", report)
    with pytest.raises(loaded.RollupError, match="overlaps original catalog"):
        loaded.derive(bad_manifest)


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual ROOT136 source manifest is not present")
def test_rollup_rejects_f5_hardfail_relabel(tmp_path: Path):
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    path = next(item["path"] for item in manifest["source_refs"] if item["key"] == "f5_proof")
    proof = json.loads(Path(path).read_text(encoding="utf-8"))
    proof["mass_gate"] = "PASS"
    bad_manifest = replacement_manifest(tmp_path, "f5_proof", proof)
    with pytest.raises(loaded.RollupError):
        loaded.derive(bad_manifest)


@pytest.mark.skipif(not MANIFEST.is_file(), reason="actual ROOT136 source manifest is not present")
def test_rollup_rejects_f3_scientific_q_upgrade(tmp_path: Path):
    loaded = module()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    path = next(item["path"] for item in manifest["source_refs"] if item["key"] == "f3_report")
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    report["qualification"]["QN"] = "PASS"
    bad_manifest = replacement_manifest(tmp_path, "f3_report", report)
    with pytest.raises(loaded.RollupError):
        loaded.derive(bad_manifest)
