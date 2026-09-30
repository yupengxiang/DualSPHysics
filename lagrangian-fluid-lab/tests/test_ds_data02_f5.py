from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ds_data02_f5 as f5


FAMILY = ROOT / "campaigns/ds-data-02/families/F5"


def _records():
    return [json.loads(line) for line in (FAMILY / "case_registry.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def test_registry_is_48_pair_preserving_nested_cases() -> None:
    rows = _records()
    assert len(rows) == 48
    assert len({row["physical_case_id"] for row in rows}) == 48
    assert Counter(row["mechanism_id"] for row in rows) == Counter({"runup_return": 24, "weir_pair": 24})
    assert Counter(row["split"] for row in rows) == Counter({"train": 24, "validation": 6, "id_test": 6, "parameter_ood_test": 6, "geometry_control_ood_test": 6})
    assert Counter(row["nested_level"] for row in rows) == Counter({"nested_8": 8, "nested_24": 16, "nested_48": 24})
    for pair_id in {row["paired_background_id"] for row in rows}:
        pair = [row for row in rows if row["paired_background_id"] == pair_id]
        assert len(pair) == 2
        assert len({row["split"] for row in pair}) == 1
        assert {row["mechanism_id"] for row in pair} == {"runup_return", "weir_pair"}


def test_reference_matrix_has_two_backgrounds_three_resolutions_and_frozen_long_window() -> None:
    matrix = json.loads((FAMILY / "definitions/reference_matrix.json").read_text(encoding="utf-8"))
    assert matrix["all_preflight"] is True
    assert len(matrix["matrix"]) == 6
    assert {row["background"] for row in matrix["matrix"]} == {"runup_return", "weir_pair"}
    assert Counter(row["resolution"] for row in matrix["matrix"]) == Counter({"coarse": 2, "medium": 2, "fine": 2})
    for row in matrix["matrix"]:
        xml = ET.parse(row["definition_path"]).getroot()
        assert xml.find(".//constantsdef/gravity") is not None
        assert xml.find(".//geometry/commands/mainlist/drawfilestl") is not None
        assert xml.find(".//geometry/commands/mainlist/drawbox[@cmt='finite_sidewall_left']") is not None
        assert xml.find(".//geometry/commands/mainlist/drawbox[@cmt='finite_sidewall_right']") is not None
        assert not xml.findall(".//parameter[@key='YPeriodicIncZ']")
        params = {node.attrib["key"]: node.attrib["value"] for node in xml.findall(".//parameter")}
        assert params["TimeMax"] == "16"
        assert params["TimeOut"] == "0.02"


def test_weir_geometry_has_real_lateral_slot_and_pair_states() -> None:
    matrix = json.loads((FAMILY / "definitions/reference_matrix.json").read_text(encoding="utf-8"))
    weir = next(row for row in matrix["matrix"] if row["background"] == "weir_pair" and row["resolution"] == "coarse")
    xml = ET.parse(weir["definition_path"]).getroot()
    boxes = {node.attrib.get("cmt") for node in xml.findall(".//geometry/commands/mainlist/drawbox")}
    assert {"weir_left_side_segment", "weir_right_side_segment"}.issubset(boxes)
    assert weir["geometry"]["weir"]["notch_y_interval_m"] == [0.25, 0.5]
    assert weir["geometry"]["weir"]["side_segments"] == 2
    assert f5._bed_profile(0.22) != f5._bed_profile(0.34)


def test_gencase_evidence_is_actual_3d_nonzero_mass_and_control_complete() -> None:
    evidence = json.loads((FAMILY / "gencase_preflight_evidence.json").read_text(encoding="utf-8"))
    checks = evidence["checks"]
    assert checks["both_completed"] is True
    assert checks["both_3d"] is True
    assert checks["both_nonzero_fluid"] is True
    assert checks["both_native_artifacts_complete"] is True
    assert checks["both_positive_mass"] is True
    assert checks["both_finite_boundary_and_control"] is True
    for row in evidence["rows"]:
        facts = row["facts"]
        assert facts["solver_dimension_from_gencase"] == 3
        assert facts["fluid_particles_stdout"] > 0
        assert facts["initial_fluid_mass_kg"] > 0
        extent = facts["fluid_transverse_extent_m"]
        assert extent["max"] - extent["min"] > 0.90
        vtk_extent = facts["fluid_vtk_bounds_m"]
        assert vtk_extent["finite"] is True
        assert vtk_extent["count"] == facts["fluid_particles_stdout"]
        assert vtk_extent["max"][1] - vtk_extent["min"][1] > 1.20
        assert facts["native_artifacts_complete"] is True
        assert facts["copied_motion"]["exists"] is True
        assert facts["motion_audit"]["time_end_s"] == 16.0


def test_qualification_requests_bind_completed_gencase_prefix_and_native_hashes() -> None:
    for name in ("qualification_runup_return_request.json", "qualification_weir_pair_request.json"):
        request = json.loads((FAMILY / name).read_text(encoding="utf-8"))
        assert request["kind"] == "qualification"
        assert request["solver_dimension_required"] == 3
        assert request["qualification_launch_authority"] == "shared_ds_data_02_runner_only_primary_process"
        prefix = Path(request["input_prefix"])
        assert prefix.with_suffix(".xml").is_file()
        assert prefix.with_suffix(".bi4").is_file()
        assert Path(request["native_artifacts"]["copied_motion"]).is_file()
        assert request["native_artifacts"]["xml_sha256"] == f5.sha256_file(prefix.with_suffix(".xml"))
        assert request["native_artifacts"]["bi4_sha256"] == f5.sha256_file(prefix.with_suffix(".bi4"))
        assert request["native_artifacts"]["copied_motion_sha256"] == f5.sha256_file(Path(request["native_artifacts"]["copied_motion"]))
        assert request["event_window_s"] == 16.0
