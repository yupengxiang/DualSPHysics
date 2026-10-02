from __future__ import annotations

import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_f5_commensurate_dp_reference_010.py"
SPEC = importlib.util.spec_from_file_location("f5_commensurate_dp_reference_010", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("dp", "counts", "pointref", "first", "last", "particles"),
    [
        (0.05, [84, 28, 8], [0.025, 0.025, 0.045], [-0.875, -0.675, 0.045], [3.275, 0.675, 0.395], 18816),
        (0.0125, [336, 112, 32], [0.00625, 0.00625, 0.00125], [-0.89375, -0.69375, 0.02625], [3.29375, 0.69375, 0.41375], 1204224),
    ],
)
def test_commensurate_lattice_preserves_continuous_mass(
    dp: float,
    counts: list[int],
    pointref: list[float],
    first: list[float],
    last: list[float],
    particles: int,
) -> None:
    value = MODULE.lattice(dp)
    assert value["counts_xyz"] == counts
    assert value["particle_count"] == particles
    assert value["pointref_m"] == pytest.approx(pointref)
    assert value["first_center_m"] == pytest.approx(first)
    assert value["last_center_m"] == pytest.approx(last)
    assert value["native_lattice_mass_kg"] == pytest.approx(2352.0, abs=1e-9)
    assert value["mass_budget_pass"] is True
    assert value["mass_rescaling"] is False


def test_rewrite_changes_only_dp_phase_and_fluid_primitive(tmp_path: Path) -> None:
    source = MODULE.FAMILY_ROOT / "definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.xml"
    target = tmp_path / "fresh.xml"
    evidence = MODULE.rewrite_definition(source, target, 0.05, "DP005")
    root = ET.parse(target).getroot()
    assert root.tag == "case"
    text = target.read_text(encoding="utf-8")
    assert '<definition dp="0.05">' in text
    assert '<pointref x="0.025" y="0.025" z="0.045" />' in text
    assert '<point x="-0.875" y="-0.675" z="0.045" />' in text
    assert '<size x="4.15" y="1.35" z="0.35" />' in text
    assert "<modefill>void</modefill>" not in text
    assert evidence["canonical_source_equivalence"] is True


def test_case_matrix_has_two_backgrounds_and_two_new_resolution_views() -> None:
    assert set(MODULE.CASE_SPECS) == {"runup_dp005", "weir_dp005", "runup_dp00125", "weir_dp00125"}
    assert {spec["mechanism_id"] for spec in MODULE.CASE_SPECS.values()} == {"runup_return", "weir_pair"}
    assert {spec["resolution_id"] for spec in MODULE.CASE_SPECS.values()} == {"dp005", "dp00125"}


def test_lattice_rejects_non_commensurate_box() -> None:
    old_size = MODULE.FLUID_SIZE
    try:
        MODULE.FLUID_SIZE = (4.21, 1.40, 0.40)
        with pytest.raises(ValueError):
            MODULE.lattice(0.05)
    finally:
        MODULE.FLUID_SIZE = old_size
