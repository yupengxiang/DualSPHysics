from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f7_s1_three_grid_face_distance_source_diag_v1.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/f7-s1-three-grid-face-distance-source-diag-v1-root-prepared-148-001"
    / "f7-s1-three-grid-face-distance-source-diag-v1-manifest.json"
)
SPEC = importlib.util.spec_from_file_location("f7_s1_three_grid_face_distance_source_diag_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest(tmp_path: Path) -> tuple[dict, Path]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value, path


def test_actual_report_preserves_count_and_separates_aggregate_face_evidence() -> None:
    report = MODULE.build_report(MANIFEST)
    assert report["status"] == "SOURCE_XML_SELECTOR_AND_FACE_DISTANCE_DIAGNOSTIC_ONLY"
    assert [row["label"] for row in report["rungs"]] == ["coarse", "original", "fine"]
    coarse = report["rungs"][0]
    assert coarse["reported_root146"]["outside_owner_envelope_count"] == 810
    assert coarse["aggregate_face_distance"]["aggregate_max_signed_face_violation_m"] == pytest.approx(1.1102230246251565e-16)
    assert coarse["outside_count_reconciliation"]["reported_count_reproducible_from_aggregate_bounds"] == "UNKNOWN_NO_PER_PARTICLE_COUNTS"
    assert coarse["representation_allowance"]["not_a_scientific_tolerance"] is True
    assert report["rungs"][1]["reported_root146"]["outside_owner_envelope_count"] == 0
    assert report["rungs"][2]["reported_root146"]["outside_owner_envelope_count"] == 0
    assert report["official_predicate_sources"]["cpu_update_pos"]["needles_present"] is True
    assert report["official_predicate_sources"]["jsph_load_dcell_half_open"]["needles_present"] is True


def test_source_selector_phase_is_declared_only_and_not_native_phase() -> None:
    report = MODULE.build_report(MANIFEST)
    for row in report["rungs"]:
        selector = row["source_lattice_and_selector"]
        assert row["source_def"]["selector_union_is_not_owner_contract"] is True
        assert selector["native_lattice_phase"] == "UNKNOWN_NO_ARRAYS_IN_THIS_DIAGNOSTIC"
        assert selector["fluid_selector_box_count"] == 4


def test_resolution_swap_is_rejected(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    value["rungs"][0]["generated_xml_ref"] = "generated_fine"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.FaceDiagError, match="coarse generated dp"):
        MODULE.build_report(path)


def test_wrong_root146_report_is_rejected(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    value["source_refs"][next(i for i, e in enumerate(value["source_refs"]) if e["key"] == "root146_report")]["sha256"] = "deadbeef"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.FaceDiagError, match="root146_report SHA"):
        MODULE.build_report(path)
