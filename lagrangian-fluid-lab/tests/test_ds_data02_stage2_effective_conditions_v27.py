from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_effective_conditions_v27.py"
V26_INDEX = ROOT / "campaigns/ds-data-02/stage2/lineage/v26-effective-condition-directory/EFFECTIVE_PHYSICAL_SPLIT_INDEX_V26.json"


def _load():
    spec = importlib.util.spec_from_file_location("effective_conditions_v27_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _axis(key: str | None, status: str = "SOURCE_BOUND_SEMANTIC"):
    return {"key": key, "status": status}


def _case(*, geometry="g", control="c", initial="i", resolution="r1",
          window="w1", recovery="x1"):
    return {
        "family_id": "F1",
        "effective_condition": {"axes": {
            "geometry": _axis(geometry), "control": _axis(control),
            "initial_state": _axis(initial), "resolution": _axis(resolution),
            "window": _axis(window), "recovery": _axis(recovery),
        }},
    }


def test_physical_union_keeps_resolution_window_recovery_together():
    module = _load()
    base = _case()
    changed_detail = _case(resolution="r2", window="w2", recovery="x2")
    assert module._physical_key(base)[0] == module._physical_key(changed_detail)[0]
    assert module._physical_key(base)[1] is False
    assert module._physical_key(_case(geometry="different"))[0] != module._physical_key(base)[0]


def test_unknown_physical_axis_is_explicitly_unsafe():
    module = _load()
    value = _case(control=None)
    value["effective_condition"]["axes"]["control"] = _axis(None, "UNKNOWN_UNASSIGNED")
    group_id, unknown, payload = module._physical_key(value)
    assert unknown is True
    assert ":PHYSICAL_UNKNOWN:" in group_id
    assert payload["physical_axes"]["control"]["status"] == "UNKNOWN"


def test_actual_v26_transform_reads_only_case_metadata(tmp_path: Path):
    module = _load()
    if not V26_INDEX.is_file():
        pytest.skip("V26 metadata index is not present")
    result = module.build_from_index(v26_index=V26_INDEX, output_dir=tmp_path / "fresh-v27")
    assert result["case_count"] == 336
    assert result["physical_union_group_count"] >= 1
    index = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
    assert index["schema"] == module.INDEX_SCHEMA
    assert len(index["cases"]) == 336
    assert index["leakage_policy"]["physical_union_is_upper_boundary"] is True
    assert all(item["split_safe"] is False for item in index["physical_union_groups"])
    request = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
    assert len(request["source_inputs"]["v26_case_details"]) == 336
    assert request["read_policy"]["hdf5"] == "FORBID"
