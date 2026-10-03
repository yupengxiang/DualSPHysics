"""Unit tests for F1 ECC thick-boundary DBC direct converter bindings and templates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDOFF_ROOT = (
    ROOT
    / "campaigns/ds-data-02/families/F1/handoff_20261003/f1_ecc_thick_boundary_dbc_direct_conversion_001"
)
MANIFEST_PATH = HANDOFF_ROOT / "manifest.json"
INVENTORY_PATH = HANDOFF_ROOT / "inventory.json"
OWNER_METADATA_DIR = HANDOFF_ROOT / "owner_metadata"
REQUESTS_DIR = HANDOFF_ROOT / "requests"

import sys
sys.path.insert(0, str(ROOT / "scripts"))
import ds_data02_direct_convert as dc
from ds_data02_f1_ecc_thick_boundary_dbc_conversion_v1 import (
    CASES,
    PHYSICAL_CONTRACT,
    sha256_file,
)


def _load_json(path: Path) -> dict:
    assert path.is_file(), f"missing JSON file: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_structure_and_safety_controls() -> None:
    manifest = _load_json(MANIFEST_PATH)
    assert manifest["schema"] == "ds02.f1.ecc-thick-boundary-dbc-conversion-manifest.v1"
    assert manifest["family_id"] == "F1"
    assert manifest["recipe_id"] == "F1_ECC_THICK_BOUNDARY_DBC_CONVERSION_001"
    assert manifest["launch_allowed"] is False
    assert manifest["root_only_launch"] is True
    assert manifest["review_status"] == "root_review_only"
    assert manifest["solver_or_gpu_started"] is False
    assert manifest["conversion_started"] is False
    assert manifest["q_n_status"] == "not_assessed"
    assert manifest["qualification_claim"] == "none"
    assert manifest["production_claim"] == "none"

    # Caps override older stale text
    assert manifest["approved_caps"]["qualification_storage_cap_gib"] == 320.0
    assert manifest["approved_caps"]["home_free_floor_gib"] == 500.0


@pytest.mark.parametrize("role", ["coarse", "medium", "fine"])
def test_physical_binding_contract_and_owner_metadata(role: str) -> None:
    owner_path = OWNER_METADATA_DIR / f"{role}-owner-metadata.json"
    owner = _load_json(owner_path)
    assert owner["schema"] == "ds02.f1.direct-conversion-owner-metadata.v1"
    assert owner["family_id"] == "F1"
    assert owner["resolution"] == role
    assert owner["q_n_status"] == "not_assessed"

    # Validate physical binding against direct converter's strict validator
    binding = owner["physical_binding"]
    validated = dc._validate_physical_binding(binding)
    assert isinstance(validated, dict)
    assert validated["family_id"] == "F1"
    assert validated["physical_case_id"] == "F1_ECCENTRIC_THICK_BOUNDARY_DBC"
    assert validated["mechanism_id"] == "eccentric_obstacle"
    assert validated["parameters"]["fluid_mass_kg"] == 80.4
    assert validated["controls"]["boundary"] == 1
    assert validated["controls"]["step_algorithm"] == 1
    assert validated["controls"]["kernel"] == 1
    assert validated["controls"]["viscosity"] == 0.1
    assert validated["controls"]["density_dt"] == 2
    assert validated["event_window"]["time_end_s"] == 1.6

    # Verify numeric binding
    numeric = owner["numeric_binding"]
    c = CASES[role]
    assert numeric["dp_m"] == c["dp_m"]
    assert numeric["boundary"] == 1
    assert numeric["boundary_name"] == "DBC"
    assert numeric["time_max_s"] == 1.6
    assert numeric["time_out_s"] == 0.001
    assert numeric["expected_frames"] == 1601
    assert numeric["expected_particles"] == c["expected_particles"]
    assert numeric["expected_fluid_particles"] == c["expected_fluid"]
    assert numeric["expected_fixed_particles"] == c["expected_fixed"]
    assert numeric["expected_fluid_mass_kg"] == 80.4

    # Verify source provenance paths exist and hashes match
    prov = owner["source_provenance"]
    for key, path_str in [
        ("definition_source", prov["definition_source"]),
        ("child_gencase_xml", prov["child_gencase_xml"]),
        ("child_gencase_bi4", prov["child_gencase_bi4"]),
        ("gencase_receipt", prov["gencase_receipt"]),
        ("solver_receipt", prov["solver_receipt"]),
        ("solver_log", prov["solver_log"]),
        ("native_storage_publication", prov["native_storage_publication"]),
        ("cpu_publication_receipt", prov["cpu_publication_receipt"]),
    ]:
        p = Path(path_str)
        assert p.is_file(), f"{key} missing: {p}"
        sha_key = f"{key}_sha256"
        assert prov[sha_key] == sha256_file(p), f"hash mismatch for {key}"


@pytest.mark.parametrize("role", ["coarse", "medium", "fine"])
def test_converter_request_safety_and_inputs(role: str) -> None:
    req_path = REQUESTS_DIR / f"{role}-converter-request.json"
    req = _load_json(req_path)
    c = CASES[role]

    assert req["schema"] == "ds02.runner.request.v2"
    assert req["family_id"] == "F1"
    assert req["case_id"] == c["case_id"]
    assert req["kind"] == "cpu"
    assert req["cpu_task_kind"] == "conversion"
    assert req["cpu_threads"] == 4
    assert req["launch_allowed"] is False
    assert req["root_only_launch"] is True
    assert req["review_status"] == "root_review_only"
    assert req["q_n_status"] == "not_assessed"

    # Storage estimates within approved bounds
    storage = req["hdf5_storage_estimate"]
    assert storage["planning_guard_gib"] <= 320.0
    assert storage["approved_qualification_cap_gib"] == 320.0
    assert storage["home_nvme_floor_bytes"] == 536870912000
    assert storage["within_approved_cap"] is True

    # Frame counts and particles
    assert req["source_data"]["frame_count"] == 1601
    assert req["source_data"]["actual_boundary"] == "DBC"
    assert req["source_data"]["actual_dimension"] == "3D"
    assert req["typed_identity_contract"]["generated_np"] == c["expected_particles"]

    # Verify input hashes
    for p_str, expected_hash in req["input_hashes"].items():
        p = Path(p_str)
        assert p.is_file(), f"missing input file: {p}"
        assert sha256_file(p) == expected_hash, f"hash mismatch: {p}"


def test_fine_exclusions_preserved() -> None:
    req_fine = _load_json(REQUESTS_DIR / "fine-converter-request.json")
    owner_fine = _load_json(OWNER_METADATA_DIR / "fine-owner-metadata.json")

    assert req_fine["source_data"]["actual_parts_out"] == 179
    assert req_fine["typed_identity_contract"]["fine_excluded_particles"] == 179

    transient = owner_fine["typed_contract"]["transient_exclusions"]
    assert transient["observed_count"] == 179
    assert "unknown" in transient["policy"].lower()
    assert "no false zero" in transient["policy"].lower()


def test_inventory_home_published_files() -> None:
    inventory = _load_json(INVENTORY_PATH)
    assert inventory["schema"] == "ds02.f1.ecc-thick-boundary-dbc-inventory.v1"
    assert inventory["status"] == "home_publication_verified"

    for role in ["coarse", "medium", "fine"]:
        res = inventory["resolutions"][role]
        assert res["published_file_count"] == 1609
        assert res["frames"] == 1601
        assert res["sample_verification"]["all_samples_present"] is True

        home_data = Path(res["home_data_root"])
        assert home_data.is_dir()
        assert (home_data / "Part_0000.bi4").is_file()
        assert (home_data / "Part_1600.bi4").is_file()
        assert (home_data / "Part_Head.ibi4").is_file()
