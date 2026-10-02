"""Evidence-bound tests for the additive F2 post-solver handoff."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path


F2_ROOT = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F2"
HANDOFF = F2_ROOT / "handoff_20261002/postsolver_v7"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_v7():
    path = F2_ROOT / "f2_handoff_20261002_postsolver_v7.py"
    spec = importlib.util.spec_from_file_location("f2_postsolver_v7_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_center_medium_audit_binds_real_3d_state_and_keeps_qualification_pending():
    audit = _load_json(HANDOFF / "center_medium_actual_audit.json")
    assert audit["solver"]["status"] == "completed"
    assert audit["solver"]["returncode"] == 0
    assert audit["conversion"]["partvtk_validation"]["all_passed"] is True
    assert audit["conversion"]["q_i_status"] == "not_granted; conversion evidence only"
    assert audit["conversion"]["q_n_status"] == "not_assessed"
    assert audit["h5"]["shape"] == {"frames": 4001, "particles": 103512, "coordinate_components": 3}
    assert audit["h5"]["initial_fluid_particles"] == 3072
    assert audit["h5"]["initial_moving_nodes"] == 7080
    assert audit["mass"]["generated_xml_authoritative_initial_fluid_mass_kg_decimal"] == "24.576"
    assert audit["mass"]["strict_continuous_mass_budget_fraction"] == 1e-12
    assert audit["mass"]["h5_adapter_relative_error_to_xml_authority"] > 0
    assert audit["mass"]["partvtk_csv_display_relative_error_to_xml_authority"] > 0
    assert audit["qualification"]["q_i_granted"] is False
    assert audit["qualification"]["q_n_assessed"] is False


def test_center_medium_labels_request_uses_actual_conversion_hashes_and_is_cpu_only():
    request = _load_json(HANDOFF / "center_medium_v6_labels_request.json")
    audit = _load_json(HANDOFF / "center_medium_actual_audit.json")
    assert request["status"] == "ready_for_root_shared_labels_after_conversion_terminal"
    assert request["gpu_launch"]["family_owner_launch"] is False
    assert request["solver_launch_forbidden"] is True
    assert request["physical_condition_hash"] == audit["source"]["physical_condition_sha256"]
    assert request["numerical_recipe_hash"] == audit["source"]["numerical_parameters_sha256"]
    assert request["source_h5"]["sha256"] == audit["conversion"]["trajectory"]["sha256"]
    digest = hashlib.sha256((HANDOFF / "center_medium_actual_audit.json").read_bytes()).hexdigest()
    assert request["actual_audit"]["sha256"] == digest
    assert Path(request["source_h5"]["path"]).is_file()
    assert Path(request["expected_outputs"]["augmented_trajectory"]) != Path(request["source_h5"]["path"])
    assert all(Path(path).is_file() for path in request["input_files"])
    assert "PartVTKOut_linux64" not in " ".join(request["command"])


def test_dp005_requests_are_blocked_by_actual_full_window_native_loss():
    requests = sorted((HANDOFF / "dp005_pending_diagnosis").glob("*.json"))
    assert len(requests) == 2
    for path in requests:
        request = _load_json(path)
        assert request["status"] == "blocked_pending_native_exclusion_diagnosis"
        assert request["native_exclusion_gate"]["np_out_sum"] > 0
        assert request["actual_source"]["native_frame_count"] == 401
        assert request["actual_source"]["parts_out"] > 0
        assert request["actual_source"]["np_out_sum"] == request["native_exclusion_gate"]["np_out_sum"]
        assert request["command"][request["command"].index("--partvtk") + 1].endswith("/PartVTK_linux64")
        assert "PartVTKOut_linux64" not in " ".join(request["command"])


def test_temporal_comparison_records_realized_ratios_without_exact_half_claim():
    manifest = _load_json(HANDOFF / "temporal_comparison_manifest.json")
    assert manifest["interpretation"]["exact_half_dt_claim"] is False
    assert len(manifest["comparisons"]) == 3
    for comparison in manifest["comparisons"]:
        assert comparison["physical_condition_hash_equal"] is True
        assert comparison["bi4_hash_equal"] is True
        assert comparison["motion_hash_equal"] is True
        assert comparison["xml_check"]["physical_xml_equivalent"] is True
        assert comparison["event_operator_status"] == "deferred_until_direct_conversion_and_v6_pose_labels"


def test_xml_semantic_equality_rejects_unapproved_geometry_change(tmp_path):
    module = _load_v7()
    baseline = next(iter(sorted((HANDOFF.parent / "numerical_recipe_v4/definitions").glob("F2H10V2_CENTER_V1_MEDIUM_RV4D1_BASELINE_SAVE001/*.xml"))))
    variant = tmp_path / "geometry-mutated.xml"
    variant.write_text(baseline.read_text(encoding="utf-8").replace('pointmax x="3.00"', 'pointmax x="3.01"', 1), encoding="utf-8")
    result = module.xml_semantic_equality(baseline, variant)
    assert result["physical_xml_equivalent"] is False
    assert result["normalized_equal_after_allowed_changes"] is False
