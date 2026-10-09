from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f7_s1_native_path_stat_qa_v1.py"
MANIFEST = (
    Path(__file__).parents[1]
    / "campaigns/ds-data-02/stage2/requests/f7-s1-native-path-stat-qa-v1-root-prepared-144-001"
    / "f7-s1-native-path-stat-qa-v1-manifest.json"
)
SPEC = importlib.util.spec_from_file_location("f7_s1_native_path_stat_qa_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest(tmp_path: Path) -> tuple[dict, Path]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value, path


def test_actual_manifest_reports_stat_only_native_paths() -> None:
    report = MODULE.build_report(MANIFEST)
    assert report["status"] == "SOURCE_CONTROL_AND_NATIVE_PATH_STATS_CLOSED_NO_NATIVE_CONTENT_READ"
    assert [row["label"] for row in report["rungs"]] == ["coarse", "original", "fine"]
    assert report["source_control"]["all_three_nonresolution_controls_equal"] is True
    assert [row["sample_mass_error_pct"] for row in report["rungs"]] == [
        pytest.approx(9.442183660933653),
        pytest.approx(0.0),
        pytest.approx(-3.4357936117936236),
    ]
    for row in report["rungs"]:
        assert row["prepared_native_path"]["sha256"] == "NOT_READ_BY_POLICY"
        assert row["native_payload_content_read"] is False
        assert row["sampling_phase_clipping"]["lattice_phase"] == "UNKNOWN_NATIVE_PAYLOAD_NOT_READ"
    assert report["source_control"]["owner_mass_is_not_discrete_denominator"] is True


def test_wrong_physical_case_is_rejected(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    value["physical_case_id"] = "F7_WRONG_CASE"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.NativePathStatQAError, match="manifest physical case"):
        MODULE.build_report(path)


def test_native_stat_byte_mismatch_is_rejected(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    entry = next(ref for ref in value["source_refs"] if ref["key"] == "native_stat_coarse")
    entry["bytes"] += 1
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.NativePathStatQAError, match="native_stat_coarse bytes"):
        MODULE.build_report(path)


def test_native_stat_requires_payload_suffix_and_unread_sha(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    entry = next(ref for ref in value["source_refs"] if ref["key"] == "native_stat_coarse")
    entry["path"] = str(Path(value["source_refs"][0]["path"]))
    entry["sha256"] = "NOT_READ_BY_POLICY"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.NativePathStatQAError, match="stat-only suffix is unsupported"):
        MODULE.build_report(path)


def test_native_content_sha_cannot_be_smuggled_into_stat_only_contract(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    entry = next(ref for ref in value["source_refs"] if ref["key"] == "native_stat_fine")
    entry["sha256"] = "deadbeef"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.NativePathStatQAError, match="native_stat_fine SHA policy"):
        MODULE.build_report(path)
