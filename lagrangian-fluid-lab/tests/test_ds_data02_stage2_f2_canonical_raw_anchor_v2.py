from __future__ import annotations

import importlib.util
from pathlib import Path
import json

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_canonical_raw_anchor_v2.py"
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
        "request_overlay": {"status": "PENDING_PARENT_GUARD_CONTENT_AND_SOURCE_SHA"},
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

