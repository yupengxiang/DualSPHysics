"""Small source-only contract tests for ROOT275 preparation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).with_name("ds_data02_stage2_build_root275_f4_native_source.py")
SPEC = importlib.util.spec_from_file_location("root275_source_builder_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_reviewed_target_set_is_seven_and_disjoint_from_root280() -> None:
    assert len(MODULE.TARGET_CASES) == 7
    assert len(set(MODULE.TARGET_CASES)) == 7
    assert not set(MODULE.TARGET_CASES).intersection(MODULE.ROOT280_CASES)


def test_parent_groups_cover_exact_target_without_extra_case() -> None:
    selected: set[str] = set()
    for root in ("ROOT296", "ROOT297"):
        _paths, _request, _selection, _manifest, rows = MODULE._load_parent(root)
        selected.update(rows)
    assert selected == set(MODULE.TARGET_CASES)


def test_self_test_keeps_payload_and_launch_closed() -> None:
    result = MODULE._self_test()
    assert result["status"] == "PASS"
    assert result["payload_opened"] is False
    assert result["launch_allowed"] is False


def test_deferred_edges_are_payload_only() -> None:
    for case_id in MODULE.TARGET_CASES:
        assert case_id.startswith("F4_")
    assert all(Path(case_id).suffix.lower() not in MODULE.PAYLOAD_SUFFIXES for case_id in MODULE.TARGET_CASES)
