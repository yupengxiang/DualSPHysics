from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
SCOPE_ROOT = FAMILY_ROOT / "commensurate_cellcenter_v4"
GENERATOR_PATH = FAMILY_ROOT / "f2_commensurate_fallback.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("f2_commensurate_fallback", GENERATOR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_commensurate_population_matches_continuous_volume() -> None:
    generator = _load_generator()
    expected = {
        "coarse": (384, 128),
        "medium": (3072, 1024),
        "fine": (24576, 8192),
    }
    for resolution, (total, per_band) in expected.items():
        result = generator.expected_population(generator.RESOLUTIONS[resolution])
        assert result["total_particle_count"] == total
        assert result["source_band_particle_count"] == per_band
        assert abs(result["relative_mass_error"]) < 1e-12


def test_cell_center_commands_are_three_disjoint_drawboxes() -> None:
    generator = _load_generator()
    commands = generator.fluid_commands(0.02, "drawbox_cellcenter")
    assert commands.count('<setmkfluid mk="') == 3
    assert commands.count("<drawbox>") == 3
    assert "<fillbox" not in commands
    assert 'point x="0.0625" y="-0.11" z="0.71"' in commands
    assert 'size x="0.3" y="0.06" z="0.3"' in commands
    assert 'point x="0.0625" y="-0.03" z="0.71"' in commands
    assert 'point x="0.0625" y="0.05" z="0.71"' in commands


def test_v4_scope_has_two_mothers_and_three_resolution_views() -> None:
    manifest = json.loads((SCOPE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scope_id"] == "F2_SCOPE_COMMENSURATE_CELLCENTER_V4"
    assert manifest["registry_role"].startswith("new_scope_new_physical_mothers")
    assert len(manifest["cases"]) == 6
    by_physical = defaultdict(list)
    for entry in manifest["cases"]:
        by_physical[entry["physical_case_id"]].append(entry["resolution"])
    assert sorted(by_physical) == ["F2_COMM4_CENTER_V1", "F2_COMM4_OFFSET_V1"]
    assert all(sorted(resolutions) == ["coarse", "fine", "medium"] for resolutions in by_physical.values())
    assert manifest["physical_geometry"]["fluid_size_m"] == [0.32, 0.24, 0.32]
    assert manifest["physical_geometry"]["source_band_width_m"] == 0.08


def test_semantic_sidecar_separates_physics_from_resolution_recipe() -> None:
    sidecar = json.loads((SCOPE_ROOT / "semantic_hashes.json").read_text(encoding="utf-8"))
    assert sidecar["status"] == "evidence_binding_sidecar_only"
    assert sidecar["qualification_claim"] == "none"
    grouped = defaultdict(list)
    for entry in sidecar["cases"]:
        grouped[entry["background"]].append(entry)
    for entries in grouped.values():
        assert len({entry["physical_condition_hash"] for entry in entries}) == 1
        assert len({entry["numerical_recipe_hash"] for entry in entries}) == 3
    assert "DtFixed" not in sidecar["physical_hash_semantics"]
    assert "solver execution parameters" in sidecar["physical_hash_semantics"]


def test_initial_handoff_is_structure_only_and_binds_all_six_cases() -> None:
    handoff = json.loads((SCOPE_ROOT / "initial_audit_handoff.json").read_text(encoding="utf-8"))
    assert handoff["status"] == "PASS_INITIAL_STRUCTURE_ONLY"
    assert handoff["qualification_claim"] == "none"
    assert handoff["production_claim"] == "none"
    assert handoff["initial_partvtk_audit"]["all_six_cases_passed"] is True
    assert len(handoff["gencase_cases"]) == 6
    assert all(case["gencase"]["dimension"] == 3 for case in handoff["gencase_cases"])
    assert all(case["initial_partvtk_audit"]["typed_id_duplicates"] == 0 for case in handoff["gencase_cases"])
    assert all(case["initial_partvtk_audit"]["fluid_position_duplicates"] == 0 for case in handoff["gencase_cases"])
    budget = handoff["scientific_budget"]
    assert budget["event_window_s"] == [0.0, 4.0]
    assert budget["reference_save_cadence_s"] == 0.01
    assert budget["internal_integrator_study"]["independent_comparison_required"] is True
    assert "DtMin" in budget["internal_integrator_study"]["policy"]


def test_solver_requests_bind_completed_gencase_prefix_and_native_artifacts() -> None:
    requests = sorted((SCOPE_ROOT / "requests").glob("*_qualification_request.json"))
    assert len(requests) == 6
    for path in requests:
        request = json.loads(path.read_text(encoding="utf-8"))
        assert request["kind"] == "qualification"
        assert request["qualification_launch_authority"] == "shared_ds_data_02_runner_only_primary_process"
        assert "{attempt_root}" not in request["command"][1]
        assert request["gencase_input_prefix"].endswith(request["case_id"])
        assert request["gencase_artifacts"]["bi4"]["path"].endswith(request["case_id"] + ".bi4")
        assert request["gencase_artifacts"]["xml"]["path"].endswith(request["case_id"] + ".xml")
        assert request["gencase_artifacts"]["copied_motion"]["path"].endswith("_motion.dat")
        assert request["physical_condition_hash"]
        assert request["numerical_recipe_hash"]
