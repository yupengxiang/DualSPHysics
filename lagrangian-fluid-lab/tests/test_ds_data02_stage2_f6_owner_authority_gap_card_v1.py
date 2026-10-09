from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f6_owner_authority_gap_card_v1.py"
MANIFEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f6-owner-authority-gap-card-v1-root-prepared-162-001/"
    / "f6-owner-authority-gap-card-v1-manifest.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f6_owner_authority_gap_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_actual_f6_owner_gap_keeps_body_and_sample_masses_separate():
    loaded = module()
    report = loaded.derive(MANIFEST)
    assert report["status"] == "F6_OWNER_AUTHORITY_GAP_BOUND_SOURCE_ONLY"
    assert report["mass_semantics"]["physical_rigid_body_mass_kg"] == pytest.approx(128.0)
    assert report["mass_semantics"]["sample_floating_mass_values_kg"] == [256.0, 257.87353515625]
    assert report["mass_semantics"]["continuum_fluid_owner_mass_kg"] is None
    assert report["mass_semantics"]["continuum_fluid_owner_mass_status"] == loaded.UNKNOWN_OWNER
    assert len(report["rows"]) == 6
    assert all(row["continuous_fluid_owner_authority"] == loaded.UNKNOWN_OWNER for row in report["rows"])


def test_gap_lists_source_inputs_needed_for_continuous_owner():
    loaded = module()
    report = loaded.derive(MANIFEST)
    missing = report["owner_gap"]["unresolved_inputs"]
    assert len(missing) == 3
    assert report["owner_gap"]["drawbox_or_particle_count_cannot_close_owner"] is True
    assert report["next_request_readiness"]["no_owner_inference_from_particles"] is True
    assert report["qualification"] == {
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "physical_fate": "UNKNOWN",
        "dynamics": "UNKNOWN",
    }


def test_manifest_is_json_only_and_binds_five_immutable_sources():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["contract"]["json_only"] is True
    assert manifest["contract"]["no_h5_bi4_obi4_vtk"] is True
    assert manifest["contract"]["no_owner_inference_from_particles"] is True
    assert len(manifest["source_refs"]) == 5
    assert all(Path(ref["path"]).suffix == ".json" for ref in manifest["source_refs"])
