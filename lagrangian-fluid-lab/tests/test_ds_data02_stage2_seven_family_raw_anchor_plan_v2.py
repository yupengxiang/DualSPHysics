from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_seven_family_raw_anchor_plan_v2.py"
CURRENT = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"


def _module():
    spec = importlib.util.spec_from_file_location("seven_family_anchor_v2_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_current_build_selects_canonical_f2_and_defers_content(tmp_path: Path) -> None:
    module = _module()
    result = module.build(
        current=CURRENT,
        repo_root=ROOT,
        card_dir=tmp_path / "cards",
        output_dir=tmp_path / "plan",
    )
    assert result["schema"] == module.INDEX_SCHEMA
    assert len(result["families"]) == 7
    assert result["alias_policy"]["F2_alias_selection"] == "REJECT"
    f2 = next(row for row in result["families"] if row["family_id"] == "F2")
    assert f2["anchor_case"]["current_index"] == 65
    assert f2["anchor_case"]["physical_case_id"] == module.F2_CANONICAL_CASE
    assert f2["anchor_case"]["physical_case_id"] != module.F2_HISTORICAL_ALIAS
    assert all(row["raw_anchor"]["raw_tree_sha256"] == module.PENDING
               for row in result["families"])
    assert all(row["raw_anchor"]["per_frame_content_sha256"] == module.PENDING
               for row in result["families"])
    plan_path = tmp_path / "plan/seven-family-raw-anchor-plan-v2.json"
    checked = module.validate(plan_path)
    assert checked["selected_F2_index"] == 65
    assert checked["qualification"] == module.UNKNOWN


def test_validator_rejects_invented_raw_hash_and_preserves_alias_gate(tmp_path: Path) -> None:
    module = _module()
    module.build(current=CURRENT, repo_root=ROOT, card_dir=tmp_path / "cards",
                 output_dir=tmp_path / "plan")
    path = tmp_path / "plan/seven-family-raw-anchor-plan-v2.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["families"][0]["raw_anchor"]["raw_tree_sha256"] = "a" * 64
    value["sha256"] = module.canonical_sha(value)
    bad = tmp_path / "bad-hash.json"
    bad.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.SevenFamilyAnchorError, match="invented raw content hash"):
        module.validate(bad)

    alias = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
    f2 = next(row for row in alias["families"] if row["family_id"] == "F2")
    f2["anchor_case"]["current_index"] = 78
    f2["anchor_case"]["physical_case_id"] = module.F2_HISTORICAL_ALIAS
    alias["sha256"] = module.canonical_sha(alias)
    alias_path = tmp_path / "bad-alias.json"
    alias_path.write_text(json.dumps(alias), encoding="utf-8")
    with pytest.raises(module.SevenFamilyAnchorError, match="F2 canonical row/identity"):
        module.validate(alias_path)
