from __future__ import annotations

import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts/ds_data02_f5_initialization_repair_003.py"
SPEC = importlib.util.spec_from_file_location("f5_repair_003", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_commensurate_lattice_is_exact_registered_mass() -> None:
    value = MODULE.lattice()
    assert value["counts_xyz"] == [168, 56, 16]
    assert value["particle_count"] == 150528
    assert value["native_lattice_mass_kg"] == 2352.000000000001
    assert abs(value["relative_mass_error"]) < 1e-12
    assert value["mass_budget_pass"] is True
    assert value["mass_rescaling"] is False
    assert value["first_center_m"] == pytest.approx([-0.8875, -0.6875, 0.0325])
    assert value["last_center_m"] == pytest.approx([3.2875, 0.6875, 0.4075])


def test_rewrite_changes_only_registered_fluid_primitive(tmp_path: Path) -> None:
    source = MODULE.FAMILY_ROOT / "definitions/F5_REF_RUNUP_NOMINAL_MEDIUM.xml"
    target = tmp_path / "fresh.xml"
    evidence = MODULE.rewrite_definition(source, target)
    assert evidence["replacement_count"] == 1
    root = ET.parse(target).getroot()
    assert root.tag == "case"
    text = target.read_text(encoding="utf-8")
    assert '<drawbox cmt="initial_fluid_cell_centres_repair_003">' in text
    assert '<point x="-0.8875" y="-0.6875" z="0.0325" />' in text
    assert '<size x="4.175" y="1.375" z="0.375" />' in text
    assert '<modefill>void</modefill>' not in text
    assert evidence["source_equivalence_after_fluid_token"] is True


def test_previous_repair_ledger_keeps_negative_evidence() -> None:
    value = MODULE.previous_failure_ledger()
    assert value["old_repairs_are_immutable"] is True
    assert value["repair_001"]["boundary_overlap_or_loss"].startswith("4004")
    assert value["repair_002"]["fixed_boundary_delta"] == 0
    assert value["repair_002"]["relative_mass_error"] == -0.2133
    assert value["interpretation"]["new_scope_reason"].startswith("DP=.025")


def test_audit_parser_reports_fluid_boundary_overlap() -> None:
    csv = """junk\nPos.x [m],Pos.y [m],Pos.z [m],Mass [kg],Type,Mk\n0,0,0,0.015625,3,1\n0.025,0,0,0.015625,0,40\n"""
    path = Path("/tmp/f5-repair-003-test.csv")
    path.write_text(csv, encoding="utf-8")
    try:
        value = MODULE.parse_partvtk_csv(path)
    finally:
        path.unlink(missing_ok=True)
    assert value["fluid_count"] == 1
    assert value["type_counts"] == {"3": 1, "0": 1}
    assert value["exact_fluid_boundary_coordinate_overlap_count"] == 0
