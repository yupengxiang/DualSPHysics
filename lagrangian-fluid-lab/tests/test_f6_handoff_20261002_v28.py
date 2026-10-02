from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f6_handoff_20261002_v28.py"
SPEC = importlib.util.spec_from_file_location("f6_handoff_v28_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_v28_actual_preflight_passes_both_mechanisms():
    path = MODULE.OUTPUT
    assert path.is_file()
    audit = json.loads(path.read_text(encoding="utf-8"))
    assert audit["status"] == "all_two_actual_gencase_preflight_pass"
    assert len(audit["cases"]) == 2
    for case in audit["cases"]:
        assert case["preflight_pass"] is True
        assert case["generated_native_contract"]["solver_dimension"] == 3
        assert case["generated_native_contract"]["type_counts"]["fluid"] == 327680
        assert case["generated_native_contract"]["fluid_mass_kg"] == 5120.0
        assert case["generated_native_contract"]["floating_contract"]["massbody_kg"] == 128.0
        assert case["generated_native_contract"]["floating_contract"]["center_m"] == [2.4, 1.2, 1.08]
        assert case["native_boundary_vtk"]["fixed_face_coverage"]["all_declared_faces_nonzero"] is True
        assert case["initial_geometry"]["body_fluid_overlap_volume_m3"] == 0.0
    wave = next(case for case in audit["cases"] if case["mechanism_id"] == "wave_no_contact")
    simple = next(case for case in audit["cases"] if case["mechanism_id"] == "simple_free_response")
    assert wave["generated_native_contract"]["type_counts"]["moving"] > 0
    assert simple["generated_native_contract"]["type_counts"]["moving"] == 0


def test_v28_keeps_massbound_particle_sum_separate_from_aggregate_mass():
    audit = json.loads(MODULE.OUTPUT.read_text(encoding="utf-8"))
    for case in audit["cases"]:
        contract = case["generated_native_contract"]["floating_contract"]
        assert contract["massbody_kg"] == 128.0
        assert contract["type2_particle_mass_sum_kg"] != contract["massbody_kg"]
