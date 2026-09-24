"""CPU tests for the versioned F4 tall-wall production collection boundary."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from scripts import core_f4_tallwall120_production_collector as collector
from scripts.core_cfd_dataset import open_dataset


LAB = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = LAB / "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")
    return path


def _trajectory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        handle["time"] = [0.0, 0.01]
        handle["position"] = np.asarray(
            [[[0.1, 0.1, 0.1], [0.2, 0.1, 0.1]],
             [[0.11, 0.1, 0.1], [0.2, 0.1, 0.1]]], dtype=float)
        handle["velocity"] = np.asarray(
            [[[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
             [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]]], dtype=float)
        handle["particle_id"] = [1, 2]
        handle["particle_zone"] = [0, 0]
        handle["mass"] = [1.0, 1.0]
        handle["valid"] = [[True, True], [True, True]]


def _synthetic_collection(tmp_path: Path, *, missing: set[int] | None = None,
                          failed: set[int] | None = None,
                          qualification_product: bool = False):
    missing = set(missing or ())
    failed = set(failed or ())
    root = tmp_path
    design = json.loads((PRODUCTION_ROOT / "production-design.json").read_text())
    design_path = _write_json(root / "production-design.json", design)
    qualification = {
        "schema": "core.f4.tallwall120.production_qualification_binding.v1",
        "summary": {
            "family": collector.FAMILY, "scope_id": collector.SCOPE_ID,
            "matrix_complete": True, "T1_numerical": True,
            "promotion_status": "candidate",
            "binding": {"verified": True, "artifact_bindings_verified": True},
        },
    }
    qualification_path = _write_json(root / "qualification.json", qualification)
    prepared_rows = []
    product_rows = []
    for design_row in design["cases"]:
        index = design_row["index"]
        source_prepared = json.loads(
            (PRODUCTION_ROOT / "first-eight/case-00/prepared.json").read_text())
        config = source_prepared["config"]
        config = copy.deepcopy(config)
        config.update({
            "case_id": design_row["case_id"],
            "split": design_row["split"],
            "physical_case_id": f"physical-{index:02d}",
            "lineage_group_id": f"lineage-{index:02d}",
            "parameter": {"name": "drop_left_x_m", "value": design_row["parameter"],
                           "candidate_range": [0.25, 0.47]},
        })
        prepared = copy.deepcopy(source_prepared)
        prepared["config"] = config
        prepared_path = _write_json(root / f"prepared/case-{index:02d}.json", prepared)
        prepared_rows.append({"index": index, "case_id": design_row["case_id"],
                              "prepared": str(prepared_path.relative_to(root)),
                              "prepared_sha256": _sha(prepared_path)})
        if index in missing:
            continue
        trajectory = root / f"products/case-{index:02d}/trajectory.h5"
        _trajectory(trajectory)
        audit_payload = {
            "schema": "core.cfd.v1", "case_id": design_row["case_id"],
            "structural": {
                "path": "trajectory.h5", "full_scan": True,
                "frame_count": 2, "particle_count": 2,
                "datasets": {
                    "particle_id": [2], "position": [2, 2, 3],
                    "velocity": [2, 2, 3], "mass": [2, 2],
                    "time": [2], "valid": [2, 2],
                },
                "attrs": {"identity_key": "particle_id"},
                "finite_active": {"position": True, "velocity": True, "mass": True},
                "initial_valid_count": 2, "identities_ever_valid": 2,
                "death_count": 0, "birth_count": 0,
            },
            "requested_horizon_reached": True,
            "hard_integrity_pass": index not in failed,
            "source_mass_gate_pass": True, "event_window_complete": index not in failed,
        }
        audit_path = _write_json(trajectory.parent / "audit.json", audit_payload)
        result_payload = {
            "schema": "core.cfd.v1", "case_id": design_row["case_id"],
            "hard_integrity_pass": index not in failed,
            "source_mass_gate_pass": True, "event_window_complete": index not in failed,
            "conversion": {"hdf5": str(trajectory), "sha256": _sha(trajectory)},
        }
        result_path = _write_json(trajectory.parent / "result.json", result_payload)
        observations_path = _write_json(
            trajectory.parent / "observations.json", {"time_s": [0.0, 0.01]})
        execution_payload = {
            "schema": "core.verified_archive.v1", "execution_status": "succeeded",
            "outputs": [
                {"path": f"product/{name}", "sha256": _sha(path)}
                for name, path in (("audit.json", audit_path), ("result.json", result_path),
                                    ("observations.json", observations_path),
                                    ("trajectory.h5", trajectory))
            ],
        }
        execution_path = _write_json(trajectory.parent / "archive.json", execution_payload)
        product_rows.append({
            "case_id": design_row["case_id"],
            "audit": {"path": str(audit_path.relative_to(root)), "sha256": _sha(audit_path)},
            "result": {"path": str(result_path.relative_to(root)), "sha256": _sha(result_path)},
            "observations": {"path": str(observations_path.relative_to(root)), "sha256": _sha(observations_path)},
            "execution": {"path": str(execution_path.relative_to(root)), "sha256": _sha(execution_path)},
            "trajectory": {"path": str(trajectory.relative_to(root)), "sha256": _sha(trajectory)},
        })
    batch = {
        "schema": collector.PRODUCTION_BATCH_SCHEMA,
        "registered_denominator": 32,
        "production_design_sha256": collector.canonical_sha256(design),
        "qualification_receipt_sha256": _sha(qualification_path),
        "prepared": prepared_rows,
    }
    batch_path = _write_json(root / "batch.json", batch)
    if qualification_product:
        product_rows.append({"case_id": "qualification-cell-00", "split": "qualification",
                             "qualification_only": True})
    products_path = _write_json(root / "products.json", {"cases": product_rows})
    return design_path, batch_path, qualification_path, products_path


def test_synthetic_qualification_rejected_before_collection(tmp_path):
    class SchemaReadProbe(dict):
        reads = []

        def get(self, key, default=None):
            self.reads.append(key)
            if key != "schema":
                raise AssertionError(f"qualification field read before schema rejection: {key}")
            return super().get(key, default)

    qualification = SchemaReadProbe({
        "schema": "core.f8.synthetic_diagnostic.v1",
        "summary": {
            "family": "F4", "scope_id": collector.SCOPE_ID,
            "matrix_complete": True, "T1_numerical": True,
        },
    })

    with pytest.raises(collector.CollectionError, match="qualification receipt schema mismatch"):
        collector.collect_f4_production({}, {}, qualification, tmp_path)
    assert qualification.reads == ["schema"]


def test_real_first_eight_is_reader_hold_with_fixed_denominator(tmp_path):
    result = collector.collect_f4_production(
        PRODUCTION_ROOT / "production-design.json",
        PRODUCTION_ROOT / "first-eight/manifest.json",
        PRODUCTION_ROOT / "qualification-tick.json",
        LAB,
    )
    assert result["registered_case_count"] == 32
    assert result["prepared_case_count"] == 8
    assert result["fixed_split_counts"] == collector.EXPECTED_SPLITS
    assert result["observed_split_counts"] == collector.EXPECTED_SPLITS
    assert result["execution_complete_count"] == 0
    assert result["reader_manifest"] is None
    assert result["formal_eligible"] is False
    assert "formal release was not requested" in result["hold_reasons"]
    assert all(row["split"] in collector.EXPECTED_SPLITS for row in result["cases"])

    # A partial collection never becomes a reader by accident: pending
    # denominator rows must fail closed until an explicit reader view exists.
    partial_path = _write_json(tmp_path / "partial-collection.json", result)
    with pytest.raises(ValueError, match="no reader manifest"):
        open_dataset(partial_path, LAB)


def test_complete_products_bind_reader_and_preserve_tall_wall(tmp_path):
    design, batch, qualification, products = _synthetic_collection(tmp_path)
    result = collector.collect_f4_production(
        design, batch, qualification, tmp_path, products=products,
        formal_release_requested=False)
    assert result["formal_eligible"] is False
    assert result["execution_complete_count"] == 32
    assert result["scientifically_passed_case_count"] == 32
    assert result["reader_case_count"] == 32
    assert result["training_manifest"] is None
    assert result["qualification_evidence_verified"] is False
    reader = result["reader_manifest"]
    assert reader["cases"][0]["provenance"]["production_design"]["canonical_sha256"]
    reader_path = _write_json(tmp_path / "reader.json", reader)
    with open_dataset(reader_path, tmp_path) as dataset:
        assert len(dataset.case_ids("train")) == 16
        assert len(dataset.case_ids("validation")) == 4
        assert len(dataset.case_ids("id_test")) == 6
        assert len(dataset.case_ids("ood_test")) == 6
        geometry = dataset.known_inputs(dataset.case_ids("validation")[0]).geometry
        assert np.max(geometry.triangles[:, :, 2]) == pytest.approx(1.2)
        now, _, dt, target = dataset.training_transition(dataset.case_ids("train")[0], 0)
        assert dt == pytest.approx(0.01)
        assert target.displacement.shape == now.position.shape

    # The versioned collection is also a public reader source.  It must use
    # only the explicitly materialized reader view while retaining the
    # collection's 32-case accounting outside the CoreDataset API.
    collection_path = _write_json(tmp_path / "collection.json", result)
    with open_dataset(collection_path, tmp_path) as dataset:
        assert len(dataset.case_ids("train")) == 16
        assert len(dataset.case_ids("validation")) == 4


def test_failed_and_missing_cases_stay_in_denominator_and_qualification_is_excluded(tmp_path):
    design, batch, qualification, products = _synthetic_collection(
        tmp_path, missing={4}, failed={3}, qualification_product=True)
    result = collector.collect_f4_production(
        design, batch, qualification, tmp_path, products=products,
        formal_release_requested=False)
    assert result["registered_case_count"] == 32
    assert result["failure_denominator"]["included_case_count"] == 32
    assert result["failed_case_count"] == 1
    assert result["pending_case_count"] == 1
    assert result["qualification_excluded_product_count"] == 1
    assert result["formal_eligible"] is False
    assert result["reader_case_count"] == 31
    assert result["cases"][3]["failure_category"] == "hard_integrity"
    assert result["cases"][4]["status"] == "pending_audit"
    assert all(row["case_id"] != "qualification-cell-00"
               for row in (result["reader_manifest"] or {}).get("cases", []))


def test_rehashed_qualification_and_batch_cannot_open_formal_release(tmp_path):
    design, batch, qualification, products = _synthetic_collection(tmp_path)
    forged = json.loads(qualification.read_text())
    # The attacker changes the evaluator result, recomputes the qualification
    # file hash, and updates the batch binding.  Summary/binding booleans alone
    # must not promote this record.
    forged["result"] = {"matrix_complete": False, "T1_numerical": False}
    forged_path = _write_json(tmp_path / "forged-qualification.json", forged)
    batch_payload = json.loads(batch.read_text())
    batch_payload["qualification_receipt_sha256"] = _sha(forged_path)
    forged_batch = _write_json(tmp_path / "forged-batch.json", batch_payload)
    with pytest.raises(collector.CollectionError, match="differs from the bound summary"):
        collector.collect_f4_production(
            design, forged_batch, forged_path, tmp_path, products=products,
            formal_release_requested=True)


def test_formal_case_reuses_authoritative_full_axis_audit(tmp_path):
    design_path, batch_path, qualification_path, products_path = _synthetic_collection(tmp_path)
    design = json.loads(design_path.read_text())
    product_index = json.loads(products_path.read_text())
    product = product_index["cases"][0]
    prepared = json.loads((tmp_path / "prepared/case-00.json").read_text())
    prepared_ref = {"path": "prepared/case-00.json", "sha256": _sha(tmp_path / "prepared/case-00.json")}
    record, reader = collector._case_record(
        0, design["cases"][0], {"payload": prepared, "ref": prepared_ref}, product,
        root=tmp_path, source_parent=tmp_path,
        qualification_ref={"path": "qualification.json", "sha256": _sha(qualification_path)},
        design_ref={"path": "production-design.json", "sha256": _sha(design_path)},
        batch_ref={"path": "batch.json", "sha256": _sha(batch_path)},
        strict_audit=True)
    assert record["authoritative_audit_verified"] is True
    assert record["status"] == "completed"
    assert reader["sha256"] == product["trajectory"]["sha256"]


def test_first_eight_and_remaining_twenty_four_batches_merge_without_split_loss(tmp_path):
    design, batch, qualification, products = _synthetic_collection(tmp_path)
    original = json.loads(batch.read_text())
    first = copy.deepcopy(original)
    remaining = copy.deepcopy(original)
    first["batch_status"] = "first_8"
    remaining["batch_status"] = "remaining_24"
    first["prepared"] = original["prepared"][:8]
    remaining["prepared"] = original["prepared"][8:]
    first_path = _write_json(tmp_path / "batch-first-eight.json", first)
    remaining_path = _write_json(tmp_path / "batch-remaining-24.json", remaining)
    result = collector.collect_f4_production(
        design, [first_path, remaining_path], qualification, tmp_path,
        products=products, formal_release_requested=False)
    assert result["prepared_case_count"] == 32
    assert len(result["production_batches"]) == 2
    assert result["fixed_split_counts"] == collector.EXPECTED_SPLITS
    assert all(row["status"] == "completed" for row in result["cases"])
    assert {row["provenance"]["batch_manifest"]["path"] for row in result["reader_manifest"]["cases"]} == {
        "batch-first-eight.json", "batch-remaining-24.json"
    }

    duplicate_path = _write_json(tmp_path / "batch-duplicate.json", first)
    with pytest.raises(collector.CollectionError, match="overlap prepared indices"):
        collector.collect_f4_production(
            design, [first_path, duplicate_path], qualification, tmp_path,
            products=products, formal_release_requested=False)


def test_lineage_cross_split_is_rejected_before_reader_manifest(tmp_path):
    design, batch, qualification, products = _synthetic_collection(tmp_path)
    prepared_path = tmp_path / "prepared/case-04.json"
    prepared = json.loads(prepared_path.read_text())
    prepared["config"]["physical_case_id"] = "physical-00"
    prepared_path.write_text(json.dumps(prepared))
    # The batch binding is deliberately updated: this test targets physical
    # split isolation, not a stale prepared hash.
    batch_payload = json.loads(batch.read_text())
    for item in batch_payload["prepared"]:
        if item["index"] == 4:
            item["prepared_sha256"] = _sha(prepared_path)
    batch.write_text(json.dumps(batch_payload))
    with pytest.raises(ValueError, match="physical case crosses splits"):
        collector.collect_f4_production(
            design, batch, qualification, tmp_path, products=products,
            formal_release_requested=False)


def test_multifamily_assembly_holds_when_a_family_is_missing(tmp_path):
    design, batch, qualification, products = _synthetic_collection(tmp_path)
    result = collector.collect_f4_production(
        design, batch, qualification, tmp_path, products=products,
        formal_release_requested=False)
    assembly = collector.assemble_multifamily_manifest(
        [result], tmp_path, required_families=("F3", "F4"),
        expected_case_counts={"F3": 32, "F4": 32}, formal_release_requested=True)
    assert assembly["formal_eligible"] is False
    assert any("family F3" in reason for reason in assembly["hold_reasons"])
    assert assembly["manifest"]["formal_release"] is False
    assert assembly["family_case_counts"] == {"F4": 32}
