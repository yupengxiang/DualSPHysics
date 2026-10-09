"""Source-only v24 seven-family card/split/rights index tests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
STAGE2 = ROOT / "campaigns/ds-data-02/stage2"
SCRIPT = ROOT / "scripts/ds_data02_stage2_family_cards_v24.py"


def _load():
    spec = importlib.util.spec_from_file_location("family_cards_v24_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v24_builds_all_cards_with_conservative_effective_split(tmp_path: Path) -> None:
    module = _load()
    result = module.build(
        stage2_root=STAGE2,
        output_dir=tmp_path / "v24",
        repo_root=ROOT,
    )
    index = json.loads(Path(result["index"]).read_text())
    assert index["schema"] == module.INDEX_SCHEMA
    assert index["qualification"] == module.UNKNOWN
    assert index["effective_physical_split"]["split_safe"] is False
    assert index["replay_delivery"]["all_parent_guard_required"] is True
    assert index["read_scope"]["hdf5_opened"] is False
    assert index["read_scope"]["jsonl_opened"] is False
    assert index["sha256"] == module.canonical_sha(index)
    assert set(index["family_cards"]) == set(module.FAMILIES)
    assert index["family_cards"]["F2"]["gap_count"] >= 1

    for family in module.FAMILIES:
        card_path = Path(result["cards"][family])
        card = json.loads(card_path.read_text())
        assert card["schema"] == module.CARD_SCHEMA
        assert card["qualification"] == module.UNKNOWN
        assert card["effective_physical_split"]["split_safe"] is False
        assert card["raw_anchor"]["parent_guard_required"] is True
        assert card["replay_delivery"]["portable_credit"] == "NOT_CLAIMED"
        assert card["read_scope"]["raw_arrays_opened"] is False
        assert card["sha256"] == module.canonical_sha(card)
    assert json.loads(Path(result["cards"]["F2"]).read_text())["raw_anchor"]["anchor_current_index"] == 78


def test_v24_rejects_a_card_that_changes_qualification(tmp_path: Path) -> None:
    module = _load()
    cards = tmp_path / "cards"
    cards.mkdir()
    source_cards = STAGE2 / "lineage/v23-source-proof"
    for family in module.FAMILIES:
        shutil.copy2(source_cards / f"{family}-family-card-v23-source-proof.json",
                     cards / f"{family}-family-card-v23-source-proof.json")
    bad_path = cards / "F1-family-card-v23-source-proof.json"
    bad = json.loads(bad_path.read_text())
    bad["qualification"]["QI"] = "QUALIFIED"
    # Leave the immutable embedded SHA unchanged.  The source-only builder
    # must reject this before producing any v24 output.
    bad_path.write_text(json.dumps(bad, sort_keys=True) + "\n")
    with pytest.raises(module.FamilyCardV24Error, match="canonical SHA differs"):
        module.build(stage2_root=STAGE2, output_dir=tmp_path / "bad-output",
                     cards_dir=cards, repo_root=ROOT)
