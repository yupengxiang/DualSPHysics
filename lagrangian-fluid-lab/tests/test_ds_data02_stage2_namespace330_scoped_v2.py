"""Case-scoped proof tests for namespace330-v2."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace330_scoped_v2.py"
V1_TEST = ROOT / "tests/test_ds_data02_stage2_namespace330_qualification.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


N330V2 = _load(SCRIPT, "namespace330_scoped_v2")
N330V1_TEST = _load(V1_TEST, "namespace330_v1_test_fixture")


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _proofs(tmp_path: Path, paths: dict[str, Path]) -> tuple[Path, Path]:
    current = json.loads(paths["current"].read_text())
    case0 = current["cases"][0]["physical_case_id"]
    case1 = current["cases"][1]["physical_case_id"]
    native = _write(tmp_path / "native-proof.json", {
        "schema": "proof.native.case-verification.v1",
        "scope_id": "native-root258-scope",
        "status": "PASS_ACTUAL_NATIVE_SCOPE_ONLY",
        "case_verifications": [
            {"physical_case_id": case0, "status": "PASS", "exit_cause": "OBSERVED_TARGET_EXIT",
             "fluid_initial_mass_kg": 4.25, "frames": 161,
             "fluid_cumulative_unique_missing": 0, "fluid_missing_final_count": 0},
            # This is an alias/non-CURRENT row and must not attach to case1 or
            # to the whole F1 family.
            {"physical_case_id": "F1_FALLBACK_ECC_COARSE", "status": "PASS",
             "exit_cause": "ALIAS_ONLY", "fluid_initial_mass_kg": 999.0},
        ],
    })
    mass = _write(tmp_path / "mass-proof.json", {
        "schema": "proof.mass.case-verification.v1",
        "scope_id": "mass-root264-scope",
        "status": "COMPLETED_DEVELOPMENT_UNKNOWN",
        "case_verifications": [
            {"physical_case_id": case0, "status": "COMPLETED",
             "expected_initial_mass_kg": 4.25, "observed_initial_mass_kg": 4.25,
             "mass_match": True},
            {"physical_case_id": case1, "status": "FAILED_INITIAL_MASS_RECONCILIATION",
             "expected_initial_mass_kg": 8.0, "observed_initial_mass_kg": None,
             "failure_reason": "source body mismatch"},
        ],
    })
    return native, mass


def _build(tmp_path: Path, *, native: list[Path] | None = None,
           mass: list[Path] | None = None):
    paths = N330V1_TEST._fixture(tmp_path / "inputs")
    native_path, mass_path = _proofs(tmp_path, paths)
    result = N330V2.build_namespace330_scoped_v2(
        current_path=paths["current"], audit_path=paths["audit"],
        lifecycle_path=paths["lifecycle"], v26_path=paths["v26"],
        output_dir=tmp_path / "namespace331", source_access_path=paths["access"],
        native_proof_paths=native if native is not None else [native_path],
        mass_proof_paths=mass if mass is not None else [mass_path],
        request_id="scoped-v2-test-001")
    return paths, native_path, mass_path, result


def test_v2_maps_only_exact_case_rows_and_keeps_failure_null(tmp_path: Path) -> None:
    _paths, _native, _mass, built = _build(tmp_path)
    catalog = json.loads(Path(built["catalog_path"]).read_text())
    rows = {row["canonical_case_id"]: row for row in catalog["cases"]}
    case0 = next(iter(rows))
    case1 = list(rows)[1]
    assert rows[case0]["native_proof_observation"]["status"] == "COMPLETED"
    assert rows[case0]["native_proof_observation"]["native_exit_cause"] == "OBSERVED_TARGET_EXIT"
    assert rows[case0]["native_proof_observation"]["initial_mass_kg"] == pytest.approx(4.25)
    assert rows[case0]["mass_proof_observation"]["mass_match"] is True
    assert rows[case0]["mass_proof_observation"]["initial_mass_kg"] == pytest.approx(4.25)
    assert rows[case1]["mass_proof_observation"]["status"] == "FAILED_OR_UNKNOWN"
    assert rows[case1]["mass_proof_observation"]["initial_mass_kg"] is None
    assert rows[case1]["mass_proof_observation"]["observed_initial_mass_kg"] is None
    assert rows[case1]["native_proof_observation"]["status"] == "UNKNOWN_NO_EXACT_CASE_ROW"
    assert rows[case1]["physical"]["native_exit_cause"] == "UNKNOWN"
    assert catalog["input_summary"]["native"]["unmatched_case_rows"] == 1
    assert catalog["input_summary"]["mass"]["matching_case_rows"] == 2
    assert all(row["qualification"] == N330V2.UNKNOWN_QUALIFICATION for row in rows.values())


def test_v2_does_not_attach_top_level_or_family_aggregate(tmp_path: Path) -> None:
    paths = N330V1_TEST._fixture(tmp_path / "inputs")
    aggregate = _write(tmp_path / "aggregate.json", {
        "schema": "proof.family.aggregate.v1", "family_id": "F1", "status": "PASS",
        "initial_mass_kg": 1234.0, "exit_cause": "FAMILY_TOTAL_ONLY",
    })
    result = N330V2.build_namespace330_scoped_v2(
        current_path=paths["current"], audit_path=paths["audit"],
        lifecycle_path=paths["lifecycle"], v26_path=paths["v26"],
        output_dir=tmp_path / "namespace330", native_proof_paths=[aggregate],
        mass_proof_paths=[])
    catalog = json.loads(Path(result["catalog_path"]).read_text())
    assert catalog["input_summary"]["native"]["unscoped_top_level_proofs"] == 1
    assert all(row["native_proof_observation"]["status"] == "UNKNOWN_NO_EXACT_CASE_ROW"
               for row in catalog["cases"])


def test_v2_conflicting_exact_proof_rows_are_unknown_not_averaged(tmp_path: Path) -> None:
    paths = N330V1_TEST._fixture(tmp_path / "inputs")
    case0 = json.loads(paths["current"].read_text())["cases"][0]["physical_case_id"]
    one = _write(tmp_path / "mass-one.json", {
        "schema": "proof.mass.v1", "scope_id": "one", "case_verifications": [
            {"physical_case_id": case0, "status": "COMPLETED", "initial_mass_kg": 1.0}]})
    two = _write(tmp_path / "mass-two.json", {
        "schema": "proof.mass.v1", "scope_id": "two", "case_verifications": [
            {"physical_case_id": case0, "status": "COMPLETED", "initial_mass_kg": 2.0}]})
    result = N330V2.build_namespace330_scoped_v2(
        current_path=paths["current"], audit_path=paths["audit"],
        lifecycle_path=paths["lifecycle"], v26_path=paths["v26"],
        output_dir=tmp_path / "namespace330", mass_proof_paths=[one, two])
    catalog = json.loads(Path(result["catalog_path"]).read_text())
    row = catalog["cases"][0]
    assert row["mass_proof_observation"]["status"] == "AMBIGUOUS_CONFLICT"
    assert row["mass_proof_observation"]["initial_mass_kg"] is None
    assert row["mass_proof_observation"]["mass_match"] is None


def test_v2_loader_and_mutation_guard(tmp_path: Path) -> None:
    _paths, _native, _mass, built = _build(tmp_path)
    loaded = N330V2.load_namespace330_scoped_v2(tmp_path / "namespace331")
    assert loaded["case_count"] == 336
    catalog_path = Path(built["catalog_path"])
    catalog = json.loads(catalog_path.read_text())
    catalog["cases"][0]["qualification"]["QI"] = "QUALIFIED"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(N330V2.Namespace330ScopedError, match="schema/SHA mismatch"):
        N330V2.load_namespace330_scoped_v2(tmp_path / "namespace331")

