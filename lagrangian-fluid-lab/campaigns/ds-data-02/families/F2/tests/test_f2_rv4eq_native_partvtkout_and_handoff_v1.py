from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile


FAMILY = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_manifest_has_two_backgrounds_and_no_qualification_claim():
    path = FAMILY / "handoff_20261003/rv4_native_partvtkout_diagnostic_v2/rv4_native_partvtkout_diagnostic_v2_manifest.json"
    data = json.loads(path.read_text())
    assert data["schema"].endswith("-input")
    assert {case["background"] for case in data["cases"]} == {"CENTER", "OFFSET"}
    assert data["expected_frames"] == 401
    assert data["qualification_claim"] == "none"
    assert data["production_claim"] == "none"


def test_typed_ranges_resolve_each_fluid_source_without_label_inference():
    module = load("f2_native_identity_correction", FAMILY / "f2_rv4eq_native_typed_identity_correction_v1.py")
    xml = """<root><particles np='6'>
      <fixed mkbound='1' mk='18' begin='0' count='1'/>
      <moving mkbound='0' mk='17' begin='1' count='1'/>
      <fluid mkfluid='0' mk='1' begin='2' count='2'/>
      <fluid mkfluid='1' mk='2' begin='4' count='2'/>
    </particles></root>"""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "generated.xml"
        path.write_text(xml)
        ranges = module.typed_ranges(path)
    assert module.typed_identity(2, ranges)["type"] == 3
    assert module.typed_identity(2, ranges)["mk"] == 1
    assert module.typed_identity(5, ranges)["mk"] == 2
    assert module.typed_identity(99, ranges)["status"] == "unknown"


def test_domain_evidence_keeps_boundary_position_separate_from_physical_fate():
    module = load("f2_native_v2_domain", FAMILY / "f2_rv4eq_native_partvtkout_diagnostic_v2.py")
    signature = {
        "simulation_domain": {"low_m": [0.0, 0.0, 0.0], "high_m": [1.0, 1.0, 1.0]},
        "boundary_boxes": [
            {"mk": 0, "point_m": [0.2, 0.2, 0.2], "size_m": [0.2, 0.2, 0.2]},
            {"mk": 1, "point_m": [0.0, 0.0, 0.0], "size_m": [1.0, 1.0, 0.1]},
            {"mk": 2, "point_m": [0.0, 0.0, 0.0], "size_m": [1.0, 1.0, 0.1]},
        ],
    }
    evidence = module.classify_domain([0.4, 0.4, 1.00001], signature, 0.005)
    assert evidence["status"] == "outside_domain"
    assert evidence["outside_faces"] == ["z+"]
    geometry = module.finite_geometry([0.4, 0.4, 1.00001], signature, 0.005)
    assert geometry["moving_cup_initial_aabb"]["inside_initial_aabb_with_2dp"] is False
    assert "no physical fate inferred" in evidence["interpretation"]


def test_corrected_sidecar_keeps_raw_rows_and_native_mk_values():
    sidecar = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_NATIVE_PARTVTKOUT_DIAGNOSTIC_20261003_V2/rv4-native-partvtkout-baseline-002/rv4-native-typed-identity-correction.json")
    data = json.loads(sidecar.read_text())
    assert data["qualification_claim"] == "none"
    assert data["all_native_fate_unknown"] is True
    expected = {"CENTER": {"1": 929, "2": 296, "3": 898}, "OFFSET": {"1": 962, "2": 335, "3": 854}}
    for case in data["cases"]:
        exclusions = case["partvtkout_exclusions"]
        assert exclusions["typed_mk_totals"] == expected[case["background"]]
        corrected_rows = Path(exclusions["enriched_records"]["path"])
        assert corrected_rows.is_file()
        assert exclusions["enriched_records"]["rows"] == exclusions["row_count"]
        assert exclusions["prior_v2_enriched_records"]["path"] != str(corrected_rows)


def test_deferred_fullstate_requests_cannot_be_run_before_terminal_hash_binding():
    root = FAMILY / "handoff_20261003/rv4_fullstate_postprocess_v1"
    manifest = json.loads((root / "fullstate_postprocess_handoff_manifest_v1.json").read_text())
    assert manifest["launch_policy"]["labels"] is False
    assert manifest["launch_policy"]["root_binds_terminal_h5_report_receipt_before_labels"] is True
    for item in manifest["labels_requests"]:
        request = json.loads(Path(item["path"]).read_text())
        assert request["status"] == "deferred_until_terminal_conversion"
        assert request["runnable"] is False
        assert request["launch_allowed"] is False
        assert all(value["sha256"] is None for value in request["deferred_input_bindings"].values())
        assert request["qualification_claim"] == "none"
        assert request["production_claim"] == "none"
        assert any(path.endswith("rv4-native-typed-identity-correction.json") for path in request["static_input_files"])
        assert any(path.endswith("f2_rv4eq_native_typed_identity_correction_v1.py") for path in request["static_input_files"])
