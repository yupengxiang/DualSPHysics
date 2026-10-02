from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f5_cell_centre_index_audit_008.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f5_cell_centre_index_audit_008", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_partvtk_decimal_rounding_maps_to_registered_integer_index() -> None:
    index, residual = MODULE._registered_index(3.2874999, 0)

    assert index == 167
    assert residual == pytest.approx(1.0e-7, abs=1.0e-14)
    assert residual <= MODULE.INDEX_COORDINATE_TOLERANCE_M


def test_registered_lattice_contract_is_unchanged() -> None:
    lattice = MODULE.lattice()

    assert lattice["counts_xyz"] == [168, 56, 16]
    assert lattice["particle_count"] == 150528
    assert lattice["pointref_m"] == [0.0125, 0.0125, 0.0075]
    assert lattice["draw_size_m"] == [4.175, 1.375, 0.375]
    assert lattice["continuous_mass_kg"] == 2352.0
