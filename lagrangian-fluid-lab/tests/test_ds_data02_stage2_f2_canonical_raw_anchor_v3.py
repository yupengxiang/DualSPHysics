from __future__ import annotations

import importlib.util
from pathlib import Path
import json

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_canonical_raw_anchor_v3.py"
SPEC = importlib.util.spec_from_file_location("f2_canonical_anchor_v2_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _current() -> dict:
    rows = [{"family_id": "F2", "physical_case_id": MODULE.CANONICAL_ID},
            {"family_id": "F2", "physical_case_id": "other"}]
    rows.extend({"family_id": "F1", "physical_case_id": f"F1-{i}"} for i in range(334))
    # Build a 336-row object with the canonical and alias at their contract
    # indices; selection tests intentionally do not read production files.
    rows[65] = {"family_id": "F2", "physical_case_id": MODULE.CANONICAL_ID}
    rows[78] = {"family_id": "F2", "physical_case_id": MODULE.HISTORICAL_ALIAS_ID}
    return {"schema": MODULE.CURRENT_CATALOG_SCHEMA, "cases": rows}


def test_exact_canonical_row_is_selected() -> None:
    row = MODULE.select_canonical(_current())
    assert row["physical_case_id"] == MODULE.CANONICAL_ID


def test_historical_alias_is_hard_rejected() -> None:
    with pytest.raises(MODULE.AnchorError, match="historical unresolved"):
        MODULE.select_canonical(_current(), index=78)


def test_neighbor_or_wrong_index_cannot_be_used_as_anchor() -> None:
    with pytest.raises(MODULE.AnchorError, match="row 65"):
        MODULE.select_canonical(_current(), index=66)


def test_plan_validator_requires_deferred_parent_tree_hash(tmp_path: Path) -> None:
    plan = {
        "schema": MODULE.SCHEMA,
        "selection": {"current_index": 65, "physical_case_id": MODULE.CANONICAL_ID,
                       "historical_alias_rejected": MODULE.HISTORICAL_ALIAS_ID},
        "current_binding": {"sha256": MODULE.CURRENT_SHA},
        "raw_binding": {"expected_raw_tree_sha256": MODULE.PENDING},
        "request_overlay": {
            "status": "PENDING_PARENT_GUARD_CONTENT_AND_SOURCE_SHA_V3",
            "request": {
                "source_hashes_preverified_by_parent": False,
                "v15_request": {"actionable_template_paths_copied": False},
            },
        },
        "qualification": dict(MODULE.UNKNOWN_QUALIFICATION),
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    result = MODULE.validate_plan(path)
    assert result["canonical"] is True
    plan["raw_binding"]["expected_raw_tree_sha256"] = "0" * 64
    path.write_text(json.dumps(plan))
    with pytest.raises(MODULE.AnchorError, match="defer raw tree hash"):
        MODULE.validate_plan(path)


def test_scientific_suffix_is_stat_only_even_when_small(tmp_path: Path) -> None:
    partout = tmp_path / "PartOut_000.obi4"
    partout.write_bytes(b"small native payload")
    declared = "a" * 64
    result = MODULE._stat_ref(partout, "native_partout", declared)
    assert result["sha256"] == declared
    assert result["content_sha_status"] == "PRODUCER_DECLARED_PARENT_RECHECK"
    assert result["content_read_by_planner"] is False
    assert result["scientific_payload_stat_only"] is True
    assert result["stat_pre"] == result["stat_post"]


def test_metadata_read_is_bounded_and_has_stable_pre_post_stat(tmp_path: Path) -> None:
    metadata = tmp_path / "receipt.json"
    metadata.write_text('{"status":"COMPLETED"}\n', encoding="utf-8")
    result = MODULE._stat_ref(metadata, "receipt")
    assert result["content_sha_status"] == "CONTENT_SHA_OBSERVED_METADATA"
    assert result["content_read_by_planner"] is True
    assert result["stat_pre"] == result["stat_post"]

    too_large = tmp_path / "too-large.json"
    too_large.write_bytes(b"{" + b" " * MODULE.METADATA_READ_LIMIT)
    with pytest.raises(MODULE.AnchorError, match="metadata read limit"):
        MODULE._load(too_large, "large metadata")


def test_historical_template_actionable_paths_are_not_copied(tmp_path: Path) -> None:
    template = tmp_path / "old-template.json"
    template.write_text(json.dumps({
        "source_files": [{"path": "/old/worktree/raw/Part_0000.bi4"}],
        "output_root": "/old/worktree/products",
        "nested": {"request": {"path": "/old/worktree/request.json"}},
    }), encoding="utf-8")
    request = MODULE._request_skeleton(
        template,
        row={"physical_case_id": MODULE.CANONICAL_ID, "runtime_case_alias": "alias"},
        current_path=tmp_path / "CURRENT336.json",
        modules={}, raw={}, sources=[], plan_id="tiny",
    )
    encoded = json.dumps(request, sort_keys=True)
    assert "/old/worktree/raw/Part_0000.bi4" not in encoded
    assert "/old/worktree/products" not in encoded
    assert request["source_hashes_preverified_by_parent"] is False
    assert request["v15_request"]["actionable_template_paths_copied"] is False
