from __future__ import annotations

import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f5_cell_centre_exact_005.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f5_cell_centre_exact_005", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_exact_lattice_keeps_registered_continuum_and_mass() -> None:
    lattice = MODULE.lattice()

    assert lattice["counts_xyz"] == [168, 56, 16]
    assert lattice["particle_count"] == 150528
    assert lattice["continuous_volume_m3"] == 2.352
    assert lattice["continuous_mass_kg"] == 2352.0
    assert lattice["native_lattice_mass_kg"] == pytest.approx(2352.0)
    assert lattice["mass_rescaling"] is False
    assert lattice["draw_size_m"] == [4.19, 1.375, 0.375]
    assert lattice["expected_generated_phase_first_m"] == [-0.875, -0.675, 0.025]
    assert lattice["expected_generated_phase_last_m"] == [3.3, 0.7, 0.4]


def test_rewrite_changes_only_fluid_primitive(tmp_path: Path) -> None:
    source = MODULE.FAMILY_ROOT / "definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.xml"
    target = tmp_path / "exact.xml"
    evidence = MODULE.rewrite_definition(source, target)
    text = target.read_text(encoding="utf-8")
    ET.parse(target)

    assert evidence["source_equivalence_after_fluid_token"] is True
    assert 'cmt="initial_fluid_cell_centres_exact_dp025_005"' in text
    assert 'size x="4.19" y="1.375" z="0.375"' in text
    assert '<fillbox x="2" y="0.18" z="0.10">' not in text
    for marker in ("tank_floor", "finite_sidewall_left", "finite_sidewall_right", "prescribed_piston", "drawfilestl"):
        assert marker in text


def test_new_scope_preserves_old_negative_evidence() -> None:
    ledger = MODULE.previous_failure_ledger()

    assert ledger["scope"] == MODULE.SCOPE
    assert ledger["old_repairs_are_immutable"] is True
    assert ledger["repair_003_phase_evidence"]["fluid_axis_counts_xyz"] == [167, 56, 16]
    assert ledger["repair_004_phase_evidence"]["fluid_axis_counts_xyz"] == [169, 56, 16]
    assert ledger["repair_004_phase_evidence"]["fluid_bounds_m"]["max"][0] == 3.325
