"""All-CURRENT source-only effective condition directory tests."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STAGE2 = ROOT / "campaigns/ds-data-02/stage2"
SCRIPT = ROOT / "scripts/ds_data02_stage2_effective_conditions_v26.py"


def _load():
    spec = importlib.util.spec_from_file_location("effective_conditions_v26_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v26_builds_all336_case_directory_without_payload_reads(tmp_path: Path) -> None:
    module = _load()
    result = module.build(stage2_root=STAGE2, output_dir=tmp_path / "v26")
    index = json.loads(Path(result["index"]).read_text(encoding="utf-8"))
    assert index["schema"] == module.INDEX_SCHEMA
    assert index["coverage"]["all336_identities"] is True
    assert index["coverage"]["case_count"] == 336
    assert index["coverage"]["family_counts"] == {f"F{i}": 48 for i in range(1, 8)}
    assert len(index["cases"]) == 336
    assert len(list((tmp_path / "v26" / "cases").rglob("*.json"))) == 336
    assert index["qualification"] == module.UNKNOWN
    assert index["sha256"] == module.canonical_sha(index)
    # F3's generated definition is explicitly shared by all 48 rows; this is
    # a source-component leakage observation, not a physical equivalence claim.
    shared = [g for g in index["source_component_leakage_groups"] if g["role"] == "generated_xml"]
    assert shared and shared[0]["families"] == ["F3"]
    assert len(shared[0]["current_indices"]) == 48
    for entry in index["cases"]:
        case = json.loads(Path(entry["case_path"]).read_text(encoding="utf-8"))
        assert case["sha256"] == module.canonical_sha(case)
        assert case["read_scope"]["hdf5_opened"] is False
        assert case["read_scope"]["raw_arrays_opened"] is False
        assert case["effective_condition"]["owner_sha256_used_as_identity"] is False


def _axis(module, key: str, status: str = "SOURCE_BOUND_SEMANTIC") -> dict:
    return {"status": status, "key": key, "payload": {"fixture": key}, "reason": "fixture"}


def test_resolution_recovery_and_window_never_cross_groups() -> None:
    module = _load()
    base = {name: _axis(module, name) for name in
            ("geometry", "control", "initial_state", "resolution", "window", "recovery")}
    same, same_status = module.effective_condition_key("F1", base)
    assert same_status == "SOURCE_BOUND_CONSERVATIVE"
    assert same == module.effective_condition_key("F1", base)[0]

    for dimension in ("resolution", "window", "recovery"):
        changed = {name: dict(value) for name, value in base.items()}
        changed[dimension]["key"] = f"{dimension}-changed"
        different, _ = module.effective_condition_key("F1", changed)
        assert different != same, dimension

    unknown = {name: dict(value) for name, value in base.items()}
    unknown["recovery"] = _axis(module, "ignored", "UNKNOWN_UNASSIGNED")
    unknown_group, unknown_status = module.effective_condition_key("F1", unknown)
    assert unknown_group is not None
    assert unknown_status == "UNKNOWN_CONSERVATIVE_GROUP"


def test_owner_hash_is_not_a_condition_identity() -> None:
    module = _load()
    axes = {name: _axis(module, name) for name in
            ("geometry", "control", "initial_state", "resolution", "window", "recovery")}
    left, _ = module.effective_condition_key("F2", axes)
    altered = {name: dict(value) for name, value in axes.items()}
    altered["geometry"]["payload"] = {"owner_sha256": "a" * 64}
    # The key is derived from the semantic key, not an owner SHA payload.
    right, _ = module.effective_condition_key("F2", altered)
    assert right == left


def test_v26_rejects_non336_or_wrong_catalog_schema(tmp_path: Path) -> None:
    module = _load()
    bad = tmp_path / "bad-current.json"
    bad.write_text(json.dumps({"schema": "wrong", "cases": []}), encoding="utf-8")
    with pytest.raises(module.EffectiveConditionV26Error, match="unexpected CURRENT catalog schema"):
        module.build(stage2_root=STAGE2, output_dir=tmp_path / "out",
                     current_catalog=bad)
