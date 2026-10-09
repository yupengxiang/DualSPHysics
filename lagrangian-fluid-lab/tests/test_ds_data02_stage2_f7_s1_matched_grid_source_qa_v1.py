from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f7_s1_matched_grid_source_qa_v1.py"
MANIFEST = (
    Path(__file__).parents[1]
    / "campaigns/ds-data-02/stage2/requests/f7-s1-matched-grid-source-qa-v1-root-prepared-143-001"
    / "f7-s1-matched-grid-source-qa-v1-manifest.json"
)
SPEC = importlib.util.spec_from_file_location("f7_s1_matched_grid_source_qa_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest(tmp_path: Path) -> tuple[dict, Path]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value, path


def _refresh_ref(entry: dict, path: Path) -> None:
    stat = path.stat()
    entry.update(
        {
            "path": str(path),
            "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns,
            "st_dev": stat.st_dev,
            "st_ino": stat.st_ino,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )


def test_actual_small_source_manifest_reports_three_rungs() -> None:
    report = MODULE.build_report(MANIFEST)
    assert report["status"] == "SOURCE_CONTROL_CLOSED_MASS_DIAGNOSTIC_ONLY_NO_SOURCE_MATCHED_SOLVER"
    assert [row["label"] for row in report["rungs"]] == ["coarse", "original", "fine"]
    assert [row["mass_diagnostic"]["source_sample_gate"] for row in report["rungs"]] == [
        "HARD_FAIL_GT2PCT_DIAGNOSTIC",
        "PASS_TARGET_1PCT_DIAGNOSTIC",
        "HARD_FAIL_GT2PCT_DIAGNOSTIC",
    ]
    assert report["mass_semantics"]["continuum_owner_mass_kg"] == 320.1984
    assert report["mass_semantics"]["official_discrete_sample_mass_kg"] > 320.1984
    assert report["source_control"]["continuous_owner_equivalence"] == "UNKNOWN"


def test_wrong_physical_case_is_rejected(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    value["physical_case_id"] = "F7_OBSTACLE_QUINTIC_B08_A065"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.MatchedGridQAError, match="manifest physical case"):
        MODULE.build_report(path)


def test_swapping_resolution_source_rejects_dp_contract(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    coarse = next(ref for ref in value["source_refs"] if ref["key"] == "def_coarse")
    fine = next(ref for ref in value["source_refs"] if ref["key"] == "def_fine")
    coarse.update(fine)
    coarse["key"] = "def_coarse"
    value["rungs"][0]["definition_ref"] = "def_coarse"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.MatchedGridQAError, match="coarse Def dp"):
        MODULE.build_report(path)


def test_changed_control_is_not_treated_as_resolution_only(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    original = next(ref for ref in value["source_refs"] if ref["key"] == "def_coarse")
    source = Path(original["path"]).read_text(encoding="utf-8")
    changed = tmp_path / "changed_Def.xml"
    changed.write_text(source.replace('z="-9.81"', 'z="-9.80"', 1), encoding="utf-8")
    _refresh_ref(original, changed)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.MatchedGridQAError, match="Def control/geometry/motion signatures differ"):
        MODULE.build_report(path)


def test_owner_mass_cannot_replace_discrete_denominator(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    value["official_discrete_sample_mass_kg"] = value["continuum_owner_mass_kg"]
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.MatchedGridQAError, match="discrete sample mass"):
        MODULE.build_report(path)
