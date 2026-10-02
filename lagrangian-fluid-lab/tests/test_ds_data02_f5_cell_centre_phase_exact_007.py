from __future__ import annotations

import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f5_cell_centre_phase_exact_007.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f5_cell_centre_phase_exact_007", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_phase_exact_lattice_keeps_registered_continuum_and_mass() -> None:
    lattice = MODULE.lattice()

    assert lattice["counts_xyz"] == [168, 56, 16]
    assert lattice["particle_count"] == 150528
    assert lattice["continuous_volume_m3"] == 2.352
    assert lattice["continuous_mass_kg"] == 2352.0
    assert lattice["native_lattice_mass_kg"] == pytest.approx(2352.0)
    assert lattice["mass_rescaling"] is False
    assert lattice["pointref_m"] == [0.0125, 0.0125, 0.0075]
    assert lattice["draw_size_m"] == [4.175, 1.375, 0.375]
    assert lattice["expected_generated_phase_first_m"] == pytest.approx([-0.8875, -0.6875, 0.0325])
    assert lattice["expected_generated_phase_last_m"] == pytest.approx([3.2875, 0.6875, 0.4075])


def test_rewrite_makes_pointref_and_fluid_primitive_explicit(tmp_path: Path) -> None:
    source = MODULE.FAMILY_ROOT / "definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.xml"
    target = tmp_path / "phase-exact-007.xml"
    evidence = MODULE.rewrite_definition(source, target)
    text = target.read_text(encoding="utf-8")
    ET.parse(target)

    assert evidence["source_equivalence_after_fluid_and_pointref_tokens"] is True
    assert '<pointref x="0.0125" y="0.0125" z="0.0075" />' in text
    assert 'cmt="initial_fluid_cell_centres_phase_exact_dp025_007"' in text
    assert 'size x="4.175" y="1.375" z="0.375"' in text
    assert '<fillbox x="2" y="0.18" z="0.10">' not in text


def test_prior_phase_failures_are_preserved_as_input() -> None:
    ledger = MODULE.previous_failure_ledger()

    assert ledger["scope"] == MODULE.SCOPE
    assert ledger["old_repairs_are_immutable"] is True
    assert ledger["v5_phase_evidence"]["full_expected_grid_match"] is False
    assert ledger["v5_phase_evidence"]["nearest_expected_center_residual_m_xyz"] == [0.0125, 0.0125, 0.0075]
    assert ledger["v6_phase_evidence"]["full_expected_grid_match"] is False
    assert ledger["v6_phase_evidence"]["axis_counts_xyz"] == [169, 56, 16]
