from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_verify_root312_v2_metadata as subject


def test_metadata_fixture_preserves_8_of_8_and_3_plus_4_roles() -> None:
    result = subject._self_test()
    assert result["status"] == "PASS"
    assert result["selected_original118_case_count"] == 7
    assert result["excluded_diagnostic_case_count"] == 9
    assert result["payload_opened"] is False


def test_inspect_rejects_subset_case_not_in_full_proof(tmp_path: Path) -> None:
    p296 = subject._fixture_proof(tmp_path, subject.v2.ROOT296, 0)
    p297 = subject._fixture_proof(tmp_path, subject.v2.ROOT297, 100)
    selection = subject._fixture_selection(tmp_path)
    value = json.loads(selection.read_text(encoding="utf-8"))
    value["bundles"][0]["selected_case_ids"][0] = "ROOT296_NOT_IN_PROOF"
    selection.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(subject.v2.Root312V2Error, match="absent"):
        subject.inspect(p296, p297, selection)


def test_inspect_rejects_non_deferred_records_edge(tmp_path: Path) -> None:
    p296 = subject._fixture_proof(tmp_path, subject.v2.ROOT296, 0)
    p297 = subject._fixture_proof(tmp_path, subject.v2.ROOT297, 100)
    selection = subject._fixture_selection(tmp_path)
    value = json.loads(p296.read_text(encoding="utf-8"))
    value["case_verifications"][0]["records_stat_only"]["content_opened_by_preparer"] = True
    p296.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(subject.Root312MetadataError, match="deferred"):
        subject.inspect(p296, p297, selection)
