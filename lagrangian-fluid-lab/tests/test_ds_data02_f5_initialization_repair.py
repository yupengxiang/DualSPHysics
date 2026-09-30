from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ds_data02_f5_initialization_repair.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f5_initialization_repair", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_cell_centre_lattice_records_noncommensurate_mass_without_rescaling():
    lattice = MODULE.cell_centre_lattice()
    assert lattice["counts_xyz"] == [140, 47, 13]
    assert lattice["particle_count"] == 85540
    assert lattice["first_center_m"] == [-0.885, -0.6849999999999999, 0.035]
    assert lattice["last_center_m"] == [3.285, 0.695, 0.395]
    assert lattice["mass_rescaling"] is False
    assert lattice["mass_budget_pass"] is False
    assert lattice["relative_mass_error"] < -0.018


def test_rewrite_changes_only_fluid_primitive(tmp_path: Path):
    target = tmp_path / "repair.xml"
    lattice = MODULE.cell_centre_lattice()
    evidence = MODULE.rewrite_definition(MODULE.SOURCE_DEFINITION, target, lattice)
    source = MODULE.SOURCE_DEFINITION.read_text(encoding="utf-8")
    repaired = target.read_text(encoding="utf-8")
    assert evidence["source_equivalence_after_fluid_token"] is True
    assert '<modefill>void</modefill>' in source
    assert '<modefill>void</modefill>' not in repaired
    assert 'cmt="initial_fluid_cell_centres_repair_001"' in repaired
    assert MODULE.canonical_geometry(source) == MODULE.canonical_geometry(repaired)
    assert 'drawfilestl file="assets/f5_continuous_bed_profile_slope_0p280.stl"' in repaired
    assert '<begin mov="1" start="0.00" finish="16" />' in repaired


def test_static_preflight_binds_old_deficit_and_fixed_physical_box():
    report = MODULE.static_preflight()
    assert report["all_static_checks"] is True
    assert report["immutable_old_observation"]["native_particles"] == 74760
    assert report["immutable_old_observation"]["fluid_center_layers_xyz"] == [139, 45, 12]
    assert report["registered_physical_contract"]["continuum_mass_kg"] == 2352.0
    assert report["support_overlap_evidence"]["old_removed_center_layer"]["particle_count"] == 300
    assert report["repair_lattice"]["mass_rescaling"] is False
