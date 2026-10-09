"""Source-only v25 calibration rebind and effective split tests."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STAGE2 = ROOT / "campaigns/ds-data-02/stage2"
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_cards_v25.py"


def _load():
    spec = importlib.util.spec_from_file_location("family_cards_v25_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(module, tmp_path: Path):
    return module.build(stage2_root=STAGE2, output_dir=tmp_path / "v25")


def test_v25_rebinds_real_all118_calibration_and_preserves_old_path_as_provenance(
    tmp_path: Path,
) -> None:
    module = _load()
    result = _build(module, tmp_path)
    index = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
    calibration = index["calibration_rebind"]
    actual = calibration["actual_v22_binding"]
    assert actual["path"].startswith("/home/jade/Projects/DualSPHysics-data/")
    assert actual["observed_sha256"] == "6d2dfdd53a0909824fe2f772655ab48561dac76d6cc8b2ea0bfe069172d4f2b6"
    assert actual["receipt_observed_sha256"] == "05b19cd9b5ac594eb8cfeeb859533740f63c4c69639150a620187f2d1d445cd1"
    assert actual["coverage"] == {"selected_case_count": 118, "selected_native_id_count": 1328,
                                   "families": {"F2": 48, "F4": 22, "F6": 48}}
    historical = calibration["historical_v23_binding"]
    assert historical["actionable"] is False
    assert "ds-data-02-stage2/DualSPHysics" in historical["path"]
    assert calibration["rebind_status"] == "ACTUAL_V22_INFRA_PATH_REBOUND_SAME_CONTENT_SHA"
    for family in ("F2", "F4", "F6"):
        card = json.loads(Path(result["cards"][family]).read_text(encoding="utf-8"))
        assert card["calibration_evidence"]["actual_v22_binding"]["observed_sha256"] == actual["observed_sha256"]
        assert "evidence_missing:all118_label_calibration" not in card["gaps"]
        assert "all118_label_calibration_rebound_from_actual_v22_infra_path" in card["gaps"]
        assert card["qualification"] == module.UNKNOWN
    f5 = json.loads(Path(result["cards"]["F5"]).read_text(encoding="utf-8"))
    assert "evidence_missing:all118_label_calibration" in f5["gaps"]
    assert "all118_label_calibration_not_scoped_to_this_family" in f5["gaps"]


def test_v25_anchor_scope_keeps_unknown_cases_together_and_excludes_owner_sha(
    tmp_path: Path,
) -> None:
    module = _load()
    result = _build(module, tmp_path)
    index = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
    split = index["effective_physical_split"]
    assert split["split_safe"] is False
    assert split["anchor_count"] == 7
    assert split["unassigned_cases_per_family"] == 47
    assert split["owner_sha256_not_identity"] is True
    assert split["leakage_groups"]
    assert all(group["split_safe"] is False for group in split["leakage_groups"])
    for family in module.FAMILIES:
        card = json.loads(Path(result["cards"][family]).read_text(encoding="utf-8"))
        physical = card["effective_physical_split"]
        assert physical["anchor_only"] is True
        assert physical["unassigned_case_count"] == 47
        assert physical["owner_sha256_used_as_identity"] is False
        assert physical["unknown_group"]["case_count"] == 48
        assert card["read_scope"]["hdf5_opened"] is False
        assert card["read_scope"]["raw_arrays_opened"] is False
        assert card["sha256"] == module.canonical_sha(card)


def test_owner_sha_alone_never_forms_cross_family_leakage_group() -> None:
    module = _load()
    signatures = {
        "F1": {"family_id": "F1", "exact_physical_source_components": [],
               "owner_sha_used_as_identity": False},
        "F2": {"family_id": "F2", "exact_physical_source_components": [],
               "owner_sha_used_as_identity": False},
    }
    groups = module._leakage_groups(signatures)
    assert groups[0]["kind"] == "NO_CROSS_FAMILY_EXACT_COMPONENT_OBSERVED"
    assert groups[0]["families"] == []

    # An explicitly shared generated XML SHA is a candidate leakage group;
    # this does not turn it into a safe split or use owner hashes.
    shared = copy.deepcopy(signatures)
    for value in shared.values():
        value["exact_physical_source_components"] = [{"role": "generated_xml", "sha256": "a" * 64}]
    groups = module._leakage_groups(shared)
    assert groups[0]["kind"] == "EXACT_SHARED_PHYSICAL_SOURCE_COMPONENT"
    assert groups[0]["families"] == ["F1", "F2"]
    assert groups[0]["split_safe"] is False


def test_v25_rejects_stale_or_tampered_actual_calibration_declaration(tmp_path: Path) -> None:
    module = _load()
    v22 = json.loads((STAGE2 / "lineage/v22-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V22.json").read_text())
    v22["evidence_bindings"]["all118_label_calibration"]["sha256"] = "0" * 64
    bad_v22 = tmp_path / "bad-v22.json"
    bad_v22.write_text(json.dumps(v22), encoding="utf-8")
    with pytest.raises(module.FamilyCardV25Error, match="SHA declarations differ"):
        module.build(stage2_root=STAGE2, output_dir=tmp_path / "bad-output",
                     v22_access_index=bad_v22)
