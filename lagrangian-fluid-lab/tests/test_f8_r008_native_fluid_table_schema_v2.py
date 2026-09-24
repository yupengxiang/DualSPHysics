from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
R008 = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008"
V1_SCHEMA = R008 / "t1-metric-semantics-proposal-v2/native-fluid-table-schema-v1.json"
V2_DIR = R008 / "native-fluid-table-schema-v2"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v2_is_additive_and_preserves_the_reviewed_v1_contract() -> None:
    proposal = _json(V2_DIR / "proposal.json")
    schema = _json(V2_DIR / "schema.json")
    v1_bytes = V1_SCHEMA.read_bytes()
    assert hashlib.sha256(v1_bytes).hexdigest() == proposal["predecessor"]["sha256"]
    assert proposal["predecessor"]["preserved_unchanged"] is True
    assert schema["schema"] == "core.cfd.f8.r008_native_fluid_frame_table.v2"
    assert schema["supersedes_for_new_D_tables"] == proposal["predecessor"]["schema"]
    assert "density" not in _json(V1_SCHEMA)["datasets"]
    assert set(schema["datasets"]) == {
        "time", "particle_id", "position", "velocity", "density", "mass", "valid",
    }


def test_density_and_invariant_mass_have_separate_raw_sources() -> None:
    schema = _json(V2_DIR / "schema.json")
    assert schema["datasets"]["density"]["semantics"].startswith("raw native Rhop values")
    assert "float32" in schema["datasets"]["density"]["dtype"]
    mass = schema["datasets"]["mass"]["semantics"]
    assert "MassFluid binary64" in mass
    assert "bitwise invariant" in mass
    assert "never recomputed from time-varying density" in mass
    assert "Rhop is time-varying state" in schema["source_projection"]["density_mass_distinction"]


def test_v2_requires_full_axis_and_exact_fluid_only_projection() -> None:
    schema = _json(V2_DIR / "schema.json")
    assert "complete frozen C raw-solver axis" in schema["datasets"]["time"]["semantics"]
    assert "strictly increasing exact fluid-ID projection" in schema["datasets"]["particle_id"]["semantics"]
    assert "[0, CaseNp) exactly once" in schema["source_projection"]["raw_frame_identity_gate"]
    assert "every table row maps one-to-one" in schema["verification"]["full_axis"]
    assert "finite" in schema["datasets"]["position"]["semantics"]
    assert "finite" in schema["datasets"]["velocity"]["semantics"]
    assert "before float32 conversion" in schema["source_projection"]["mass_binary64_gate"]


def test_v2_hdf5_dimensions_storage_and_reading_are_bounded() -> None:
    schema = _json(V2_DIR / "schema.json")
    container = schema["container"]
    assert container["maximum_file_bytes"] == 2 * 1024**3
    assert container["maximum_uncompressed_dataset_bytes"] == 1024**3
    assert container["maximum_time_rows"] == 1497
    assert container["maximum_particle_rows"] == 10752
    assert container["maximum_time_particle_cells"] == 1497 * 10752
    assert container["dimensions_must_be_checked_before_dataset_reads"] is True
    assert "never load a whole trajectory dataset" in container["stream_reading"]
    assert "exactly FALSE=0 and TRUE=1" in schema["root_attributes"]["attribute_types"]["conversion_complete"]
    assert "LZF is the only filter" in container["particle_dataset_chunking"]
    assert "one complete chunk per time row" in container["particle_dataset_chunking"]
    assert container["external_links_or_storage"] is False
    assert container["virtual_datasets"] is False
    strings = schema["root_attributes"]["attribute_types"]["all_other_attributes"]
    assert "fixed-length UTF-8" in strings
    assert "no variable-length heap allocation" in strings
    assert schema["datasets"]["valid"]["dtype"] == (
        "HDF5 boolean enum over unsigned byte with exactly FALSE=0 and TRUE=1"
    )


def test_contract_proposal_does_not_change_scientific_or_execution_gates() -> None:
    proposal = _json(V2_DIR / "proposal.json")
    assert proposal["status"] == "static_design_review_passed_implementation_only"
    assert proposal["changed_fields"] == []
    assert all(value is True for value in proposal["gates_unchanged"].values())
    assert all(value is False for key, value in proposal["execution_authority"].items()
               if key != "qualification_credit")
    assert proposal["execution_authority"]["qualification_credit"] == 0
    assert proposal["implementation_boundary"]["qualification_claim"] == "none"
    assert "solver" in proposal["implementation_boundary"]["forbidden_in_this_proposal"]
    assert "worker" in proposal["implementation_boundary"]["forbidden_in_this_proposal"]
    assert proposal["compatibility"]["v1_tables_and_adapter"].startswith("remain readable only")
