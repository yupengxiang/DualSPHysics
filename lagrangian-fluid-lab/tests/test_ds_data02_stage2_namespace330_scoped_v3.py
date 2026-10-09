"""Schema-aware namespace330-v3 proof joins."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace330_scoped_v3.py"
V1_TEST = ROOT / "tests/test_ds_data02_stage2_namespace330_qualification.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N330 = _load(SCRIPT, "namespace330_scoped_v3")
N330_V1_TEST = _load(V1_TEST, "namespace330_v1_fixture_for_v3")


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _build(tmp_path: Path, native: list[Path], mass: list[Path]):
    paths = N330_V1_TEST._fixture(tmp_path / "inputs")
    return N330.build_namespace330_scoped_v3(
        current_path=paths["current"], audit_path=paths["audit"],
        lifecycle_path=paths["lifecycle"], v26_path=paths["v26"],
        source_access_path=paths["access"], native_proof_paths=native,
        mass_proof_paths=mass, output_dir=tmp_path / "v3-output",
        request_id="namespace330-v3-test-001")


def test_v3_uses_actual_native_schema_and_scope_ids_are_provenance(tmp_path: Path) -> None:
    paths = N330_V1_TEST._fixture(tmp_path / "inputs")
    current = json.loads(paths["current"].read_text())
    case_id = current["cases"][0]["physical_case_id"]
    native_rows = [
        {"physical_case_id": case_id, "status": "COMPLETED",
         "native_cause_categories": ["target_exit", "censor_none"],
         "target_fluid_identity_count": 21,
         "saved_frame_matches": 241,
         "exact_join_rows": 21},
    ]
    native1 = _write(tmp_path / "native1.json", {
        "schema": "root268.native.v3", "scope_id": "root268-a",
        "case_verifications": native_rows})
    native2 = _write(tmp_path / "native2.json", {
        "schema": "root268.native.v3", "scope_id": "root268-b",
        "case_verifications": [dict(native_rows[0], native_cause_categories=["censor_none", "target_exit"]) ]})
    built = _build(tmp_path, [native1, native2], [])
    catalog = json.loads(Path(built["catalog_path"]).read_text())
    row = catalog["cases"][0]["native_proof_observation"]
    assert row["status"] == "COMPLETED"
    assert row["scope_ids"] == ["root268-a", "root268-b"]
    assert row["native_cause_categories"] == ["censor_none", "target_exit"]
    assert row["target_fluid_identity_count"] == 21
    assert row["saved_frame_matches"] == 241
    assert row["exact_join_rows"] == 21
    assert row["conflict_reason"] is None
    assert row["native_exit_cause"] == "UNKNOWN"


def test_v3_selected_typed_mass_never_falls_back_to_expected(tmp_path: Path) -> None:
    paths = N330_V1_TEST._fixture(tmp_path / "inputs")
    current = json.loads(paths["current"].read_text())
    case0 = current["cases"][0]["physical_case_id"]
    case1 = current["cases"][1]["physical_case_id"]
    mass = _write(tmp_path / "mass.json", {
        "schema": "root313.mass.v6", "scope_id": "mass313",
        "case_verifications": [
            {"physical_case_id": case0, "status": "COMPLETED",
             "selected_typed_initial_mass": {"sum_kg": 21.114, "count": 17,
                                               "status": "SELECTED_TYPED_INITIAL_MASS_VERIFIED",
                                               "excluded_mass_kg": 0.25},
             "case_total_initial_mass_kg": 21.364,
             "expected_initial_mass_kg": 999.0},
            {"physical_case_id": case1, "status": "COMPLETED",
             "expected_initial_mass_kg": 8.0},
        ],
    })
    built = _build(tmp_path, [], [mass])
    catalog = json.loads(Path(built["catalog_path"]).read_text())
    rows = catalog["cases"]
    first = rows[0]["mass_proof_observation"]
    second = rows[1]["mass_proof_observation"]
    assert first["selected_initial_mass_sum_kg"] == pytest.approx(21.114)
    assert first["selected_initial_mass_count"] == 17
    assert first["selected_initial_mass_status"] == "COMPLETED"
    assert first["selected_exclusion_mass_kg"] == pytest.approx(0.25)
    assert first["case_total_initial_mass_kg"] == pytest.approx(21.364)
    assert first["expected_initial_mass_kg"] == pytest.approx(999.0)
    assert first["initial_mass_kg"] == pytest.approx(21.114)
    assert second["expected_initial_mass_kg"] == pytest.approx(8.0)
    assert second["initial_mass_kg"] is None
    assert second["selected_initial_mass_status"] is None


def test_v3_rejects_conflicting_measurements_but_not_different_scope_ids(tmp_path: Path) -> None:
    paths = N330_V1_TEST._fixture(tmp_path / "inputs")
    case_id = json.loads(paths["current"].read_text())["cases"][0]["physical_case_id"]
    one = _write(tmp_path / "one.json", {
        "schema": "root258.mass.v6", "scope_id": "scope-a",
        "case_verifications": [{"physical_case_id": case_id, "status": "COMPLETED",
                                 "selected_initial_mass_sum_kg": 2.0,
                                 "selected_initial_mass_count": 1,
                                 "selected_initial_mass_status": "VERIFIED"}]})
    two = _write(tmp_path / "two.json", {
        "schema": "root264.mass.v6", "scope_id": "scope-b",
        "case_verifications": [{"physical_case_id": case_id, "status": "COMPLETED",
                                 "selected_initial_mass_sum_kg": 3.0,
                                 "selected_initial_mass_count": 1,
                                 "selected_initial_mass_status": "VERIFIED"}]})
    built = _build(tmp_path, [], [one, two])
    row = json.loads(Path(built["catalog_path"]).read_text())["cases"][0]["mass_proof_observation"]
    assert row["status"] == "AMBIGUOUS_CONFLICT"
    assert row["initial_mass_kg"] is None
    assert row["selected_initial_mass_sum_kg"] is None


def test_v3_top_level_aggregate_and_noncanonical_rows_do_not_attach(tmp_path: Path) -> None:
    paths = N330_V1_TEST._fixture(tmp_path / "inputs")
    proof = _write(tmp_path / "legacy-top.json", {
        "schema": "legacy.root219.proof.v1", "status": "PASS",
        "family_id": "F6", "native_cause_categories": ["aggregate"],
        "target_fluid_identity_count": 336,
        "case_verifications": [{"physical_case_id": "F6_ALIAS_ONLY",
                                "status": "COMPLETED",
                                "native_cause_categories": ["alias"]}],
    })
    built = _build(tmp_path, [proof], [])
    catalog = json.loads(Path(built["catalog_path"]).read_text())
    assert catalog["input_summary"]["native"]["unmatched_case_rows"] == 1
    assert catalog["input_summary"]["native"]["unscoped_top_level_proofs"] == 0
    assert all(row["native_proof_observation"]["status"] == "UNKNOWN_NO_EXACT_CASE_ROW"
               for row in catalog["cases"])


def test_v3_loader_preserves_unknown_qualification(tmp_path: Path) -> None:
    built = _build(tmp_path, [], [])
    loaded = N330.load_namespace330_scoped_v3(tmp_path / "v3-output")
    assert loaded["case_count"] == 336
    assert loaded["schema"] == N330.CATALOG_SCHEMA
