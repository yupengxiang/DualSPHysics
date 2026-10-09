from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f7_s1_fixed_owner_phase_diagnostic_v1.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f7-s1-fixed-owner-phase-diagnostic-v1-root-prepared-161-001/"
    / "f7-s1-fixed-owner-phase-diagnostic-v1-manifest.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f7_fixed_owner_phase_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_phase_reports_unrepresented_z_tail_without_mass_fit():
    loaded = module()
    phase = loaded._axis_phase(0.05, 0.482, 0.025)
    assert phase["whole_contained_cells"] == 17
    assert phase["unrepresented_high_tail_m"] == pytest.approx(0.007)
    assert phase["high_phase_mod_dp"] == pytest.approx(0.28)


def test_real_source_contract_marks_dp_mismatch_and_support_gap():
    loaded = module()
    report = loaded.derive(MANIFEST)
    assert report["status"] == "F7_FIXED_OWNER_PHASE_AND_SOURCE_DP_MISMATCH_NO_GENCASE"
    contract = report["source_contract"]
    assert contract["source_control_dp_m"] == pytest.approx(0.02)
    assert contract["candidate_coarse_def_dp_m"] == pytest.approx(0.025)
    assert contract["source_control_and_lattice_dp_match"] is False
    lattice = report["phase_and_quadrature"]
    assert lattice["full_contained_cell_count"] == 20944
    assert lattice["paddle_center_excluded_cell_count"] == 1020
    assert lattice["selected_cell_count"] == 19924
    assert lattice["represented_mass_kg"] == pytest.approx(311.3125)
    assert lattice["mass_fit_search"] is False
    assert report["qualification"] == {
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "physical_fate": "UNKNOWN",
        "dynamics": "UNKNOWN",
    }


def test_manifest_is_payload_free_and_source_bound():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["contract"]["json_xml_only"] is True
    assert manifest["contract"]["no_h5_bi4_obi4_vtk"] is True
    assert manifest["contract"]["mass_fit_search"] is False
    assert all(Path(ref["path"]).suffix.lower() in {".json", ".xml"} for ref in manifest["source_refs"])
