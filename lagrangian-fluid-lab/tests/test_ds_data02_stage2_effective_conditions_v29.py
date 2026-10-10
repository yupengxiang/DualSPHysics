from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT27 = ROOT / "scripts/ds_data02_stage2_effective_conditions_v27.py"
SCRIPT29 = ROOT / "scripts/ds_data02_stage2_effective_conditions_v29.py"
V26 = ROOT / "campaigns/ds-data-02/stage2/lineage/v26-effective-condition-directory/EFFECTIVE_PHYSICAL_SPLIT_INDEX_V26.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v29_actual_v27_union_audit_is_all336_and_unsafe(tmp_path: Path) -> None:
    v27 = _load(SCRIPT27, "effective_conditions_v27_for_v29_test")
    v29 = _load(SCRIPT29, "effective_conditions_v29_test")
    built = v27.build_from_index(v26_index=V26, output_dir=tmp_path / "v27")
    result = v29.build_leakage_audit(v27_index=built["index"], output_dir=tmp_path / "v29")
    assert result["case_count"] == 336
    assert result["unsafe_group_count"] == result["physical_union_group_count"]
    assert result["split_safe"] is False
    audit = json.loads(Path(result["audit"]).read_text(encoding="utf-8"))
    assert audit["policy"]["qualification_credit"] == "NONE"
    assert audit["policy"]["diagnostic_subgroups"] == ["resolution", "window", "recovery"]


def test_v29_rejects_physical_axis_collision(tmp_path: Path) -> None:
    v27 = _load(SCRIPT27, "effective_conditions_v27_for_v29_collision_test")
    v29 = _load(SCRIPT29, "effective_conditions_v29_collision_test")
    built = v27.build_from_index(v26_index=V26, output_dir=tmp_path / "v27")
    index = json.loads(Path(built["index"]).read_text(encoding="utf-8"))
    group = index["physical_union_groups"][0]
    group["physical_axes"] = copy.deepcopy(group["physical_axes"])
    group["physical_axes"]["geometry"]["key"] = "changed-from-member"
    with pytest.raises(v29.EffectiveConditionV29Error, match="declared axes differ"):
        v29.validate_index(index)


def test_v29_rejects_split_safe_group(tmp_path: Path) -> None:
    v27 = _load(SCRIPT27, "effective_conditions_v27_for_v29_safe_test")
    v29 = _load(SCRIPT29, "effective_conditions_v29_safe_test")
    built = v27.build_from_index(v26_index=V26, output_dir=tmp_path / "v27")
    index = json.loads(Path(built["index"]).read_text(encoding="utf-8"))
    index["physical_union_groups"][0]["split_safe"] = True
    with pytest.raises(v29.EffectiveConditionV29Error, match="split_safe"):
        v29.validate_index(index)
