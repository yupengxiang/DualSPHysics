"""Meaningful receipt and portability gates for the lightweight M4 release card."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from typing import Any

import pytest


MODULE_PATH = Path(__file__).with_name("m4_release.py")
SPEC = importlib.util.spec_from_file_location("m4_release_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
m4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m4)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        path.write_bytes(value)


def _binding(path: Path, *, relative: str | None = None) -> dict[str, Any]:
    return {"path": relative or str(path), "bytes": path.stat().st_size, "sha256": _sha(path)}


def _execution(path: Path, case_id: str, attempt_id: str) -> None:
    _write(
        path,
        {
            "schema": m4.EXECUTION_SCHEMA,
            "status": "completed",
            "returncode": 0,
            "request": {
                "schema": "ds-data-02.runner.request.v1",
                "case_id": case_id,
                "attempt_id": attempt_id,
            },
        },
    )


def _make_bundle(root: Path, case_id: str, depth: float, physical_hash: str, *, hdf5_bytes: bytes) -> dict[str, Any]:
    normalized = root / "normalized.h5"
    _write(normalized, hdf5_bytes)
    geometry = {
        "schema": "ds-data-02.m4.geometry.v1",
        "case_id": case_id,
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
        "solver_dimension": 3,
        "physical_condition_sha256": physical_hash,
        "physical_fate_inferred": False,
        "geometry": {
            "central_obstacle": {"label": "generated child central obstacle envelope", "low_m": [0.66, 0.3, 0.0], "size_m": [0.16, 0.4, 0.16]},
            "tank": {"low_m": [0.0, 0.0, 0.0], "size_m": [3.22, 1.0, 1.0]},
        },
    }
    control = {
        "schema": "ds-data-02.m4.control.v1",
        "case_id": case_id,
        "physical_condition_sha256": physical_hash,
        "physical_fate_inferred": False,
        "event_window": {"time_start_s": 0.0, "time_end_s": 6.0},
        "solver_parameters": {"TimeMax": 6, "TimeOut": 0.025},
    }
    _write(root / "geometry.json", geometry)
    _write(root / "control.json", control)
    identity_hash = "1" * 64
    typed_hash = "2" * 64
    exclusion_hash = "3" * 64
    interface = {
        "schema": m4.INTERFACE_SCHEMA,
        "case_id": case_id,
        "family_id": "F1",
        "status": "normalized_verified",
        "credit_status": "not_credited",
        "physical_fate_inferred": False,
        "portable_source_paths_redacted": True,
        "normalized_hdf5": _binding(normalized, relative="normalized.h5"),
        "identity_axis": {
            "key": "(Zone,Idp)",
            "full_initial_identity": True,
            "all_frames_fixed_axis": True,
            "initial_particle_count": 1,
            "frame_count": 241,
            "initial_ids_sha256": identity_hash,
            "initial_typed_ids_sha256": typed_hash,
        },
        "exclusion_mask": {
            "status": "verified",
            "count": 0,
            "ids_sha256": exclusion_hash,
            "physical_fate_inferred": False,
            "motive_semantics": "native numerical exclusion cause only",
        },
        "endpoint_transport": {
            "schema": m4.ENDPOINT_SCHEMA,
            "source_frame": 0,
            "destination_frame": "last",
            "source_valid_label": "valid_source",
            "destination_valid_label": "valid_destination",
            "missing_endpoint_labels": ["unknown", "censored"],
            "physical_fate_inferred": False,
            "particle_id_dataset": "/transport/particle_id",
            "particle_zone_dataset": "/transport/particle_zone",
            "source_valid_dataset": "/transport/source_valid",
            "destination_valid_dataset": "/transport/destination_valid",
            "source_label_dataset": "/transport/source_label",
            "destination_label_dataset": "/transport/destination_label",
            "source_position_dataset": "/transport/source_position",
            "destination_position_dataset": "/transport/destination_position",
            "displacement_dataset": "/transport/displacement",
        },
        "geometry": {"path": "geometry.json", "bytes": 0, "sha256": ""},
        "control": {"path": "control.json", "bytes": 0, "sha256": ""},
        "physical_condition": {
            "physical_condition_sha256": physical_hash,
            "depth_m": depth,
            "generated_xml_sha256": "4" * 64,
            "child_manifest_sha256": "5" * 64,
            "semantic_diff_sha256": "6" * 64,
        },
        "source_mother": {"case_id": m4.MOTHER_CASE, "role": "immutable mother metadata base; not child physical identity"},
    }
    evaluator = {
        "schema": m4.EVALUATOR_SCHEMA,
        "case_id": case_id,
        "passed": True,
        "checks": {name: True for name in m4.REQUIRED_EVALUATOR_CHECKS},
        "semantic_negative_contract": {name: "must_reject" for name in m4.REQUIRED_SEMANTIC_CONTRACT},
    }
    _write(root / "interface.json", interface)
    _write(root / "evaluator.json", evaluator)
    _write(root / "runtime/m4_portable_adapter.py", b"#!/usr/bin/env python3\n")
    _write(root / "runtime/l2_reader.py", b"# self-contained reader fixture\n")
    interface["geometry"] = _binding(root / "geometry.json", relative="geometry.json")
    interface["control"] = _binding(root / "control.json", relative="control.json")
    _write(root / "interface.json", interface)
    normalized_binding = _binding(normalized, relative="normalized.h5")
    reader = {"schema": m4.READER_SCHEMA, "repository_root": ".", "cases": [{"case_id": case_id, "hdf5": "normalized.h5", **{key: normalized_binding[key] for key in ("bytes", "sha256")}}]}
    _write(root / "reader-manifest.json", reader)
    artifacts = {
        "normalized_hdf5": normalized_binding,
        "geometry": _binding(root / "geometry.json", relative="geometry.json"),
        "control": _binding(root / "control.json", relative="control.json"),
        "interface": _binding(root / "interface.json", relative="interface.json"),
        "evaluator": _binding(root / "evaluator.json", relative="evaluator.json"),
        "reader_manifest": _binding(root / "reader-manifest.json", relative="reader-manifest.json"),
        "runtime_adapter": _binding(root / "runtime/m4_portable_adapter.py", relative="runtime/m4_portable_adapter.py"),
        "runtime_l2_reader": _binding(root / "runtime/l2_reader.py", relative="runtime/l2_reader.py"),
    }
    manifest = {
        "schema": m4.BUNDLE_SCHEMA,
        "case_id": case_id,
        "interface": "interface.json",
        "artifacts": artifacts,
        "runtime": {"adapter": "runtime/m4_portable_adapter.py", "source_paths_redacted": True},
        "portable_policy": {
            "native_decoder_in_bundle": False,
            "raw_native_payload_in_bundle": False,
            "physical_fate_inferred": False,
            "m2_bundle_modified": False,
        },
    }
    _write(root / "manifest.json", manifest)
    return {"manifest": manifest, "normalized": normalized, "geometry": geometry, "control": control, "interface": interface}


def _make_case(root: Path, case_id: str, depth: float) -> dict[str, Any]:
    physical_hash = hashlib.sha256(case_id.encode()).hexdigest()
    case_root = root / case_id
    source = case_root / "portable-source"
    destination = case_root / "nas-relocated" / "bundle"
    _make_bundle(source, case_id, depth, physical_hash, hdf5_bytes=b"intentionally-not-an-HDF5-payload")

    product = case_root / "m4-enrichment-001/product"
    product.mkdir(parents=True)
    generated_xml = case_root / "generated.xml"
    generated_xml.write_text(f"<case id='{case_id}' depth='{depth}'/>\n", encoding="utf-8")
    source_interface_path = source / "interface.json"
    source_interface = json.loads(source_interface_path.read_text(encoding="utf-8"))
    source_interface["physical_condition"]["generated_xml_sha256"] = _sha(generated_xml)
    source_interface_path.write_text(json.dumps(source_interface, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    source_manifest_path = source / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["artifacts"]["interface"] = _binding(source_interface_path, relative="interface.json")
    source_manifest_path.write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.copytree(source, destination)
    owner = {
        "schema": "ds-data-02.m4.child-owner-preparation.v1",
        "case_id": case_id,
        "physical_case_id": case_id,
        "parameter_values": {
            "initial_depth_m": depth,
            "separator_start_x_m": 0.66,
            "separator_end_x_m": 0.82,
            "separator_y_m": 0.3,
            "separator_thickness_m": 0.16,
        },
        "geometry": {"central_obstacle": {"label": "generated child central obstacle envelope", "low_m": [0.66, 0.3, 0.0], "size_m": [0.16, 0.4, 0.16]}},
    }
    owner_path = product / "owner-metadata.json"
    _write(owner_path, owner)
    enriched_hdf5 = product / "enriched.h5"
    _write(enriched_hdf5, b"intentionally-not-an-enriched-HDF5-payload")
    product_interface = {"schema": m4.INTERFACE_SCHEMA, "case_id": case_id}
    product_geometry = {"schema": "ds-data-02.m4.geometry.v1", "case_id": case_id}
    product_control = {"schema": "ds-data-02.m4.control.v1", "case_id": case_id}
    _write(product / "interface.json", product_interface)
    _write(product / "geometry.json", product_geometry)
    _write(product / "control.json", product_control)
    outputs = {
        "interface": _binding(product / "interface.json", relative="interface.json"),
        "geometry": _binding(product / "geometry.json", relative="geometry.json"),
        "control": _binding(product / "control.json", relative="control.json"),
        "owner_metadata": _binding(owner_path, relative="owner-metadata.json"),
        "enriched_hdf5": {"path": "enriched.h5", "bytes": enriched_hdf5.stat().st_size, "sha256": _sha(enriched_hdf5)},
    }
    enrichment_receipt = product / "enrichment-receipt.json"
    _write(
        enrichment_receipt,
        {
            "schema": m4.ENRICHMENT_RECEIPT_SCHEMA,
            "status": "completed",
            "case_id": case_id,
            "credit_status": "not_credited",
            "physical_fate_inferred": False,
            "physical_condition": {"sha256": physical_hash},
            "outputs": outputs,
        },
    )
    direct_hdf5 = case_root / "trajectory.h5"
    _write(direct_hdf5, b"intentionally-not-a-direct-HDF5-payload")
    direct_report = case_root / "direct-conversion-report.json"
    _write(
        direct_report,
        {
            "schema": m4.DIRECT_REPORT_SCHEMA,
            "conversion_status": "completed",
            "conversion_claim": "streaming BI4 adapter evidence only; no Q-N or production claim",
            "frames": 241,
            "particles": 1,
            "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
            "solver_dimension": {"solver_dimension": 3},
            "typed_identity": {"key": "(Zone,Idp)"},
            "output_hdf5": str(direct_hdf5),
            "output_sha256": _sha(direct_hdf5),
            "hash_scopes": {"physical_condition_sha256": physical_hash},
            "source_provenance": {"generated_xml": {"path": str(generated_xml), "sha256": _sha(generated_xml)}},
            "q_i_status": "not_granted",
            "q_n_status": "not_assessed",
            "production_eligibility": "not_evaluated",
        },
    )
    direct_exec = case_root / "m4-direct-conversion-001/execution-receipt.json"
    enrichment_exec = case_root / "m4-enrichment-001/execution-receipt.json"
    build_exec = case_root / "m4-portable-build-001/execution-receipt.json"
    _execution(direct_exec, case_id, "m4-direct-conversion-001")
    _execution(enrichment_exec, case_id, "m4-enrichment-001")
    _execution(build_exec, case_id, "m4-portable-build-001")

    isolated_report = case_root / "actual-validation/relocated-isolated-validation.json"
    _write(isolated_report, {"schema": "ds-data-02.m4.isolated-validation.v1", "validation": {"portable": True}, "namespace": {"denied_probes_passed": True}})
    negative_dir = case_root / "actual-validation/reports"
    negative_dir.mkdir(parents=True)
    negative_reports: list[str] = []
    for name in ("typed_identity_endpoint_label", "destination_position"):
        negative_path = negative_dir / f"{name}.json"
        _write(
            negative_path,
            {
                "schema": m4.ACTUAL_NEGATIVE_SCHEMA,
                "status": "rejected_as_expected",
                "negative": name,
                "artifact_layer_rehashed": True,
                "source_bundle_untouched": True,
                "mutation": {"rehashed": {key: "binding" for key in m4.REQUIRED_REHASHED_BINDINGS}},
                "production_validator": {"returncode": 1, "stderr_tail": "expected semantic error"},
            },
        )
        negative_reports.append(str(negative_path))
    source_manifest = source / "manifest.json"
    snapshot_bindings = {
        "manifest": _binding(source_manifest),
        **{
            name: _binding(source / str(declared["path"]))
            for name, declared in json.loads(source_manifest.read_text(encoding="utf-8"))["artifacts"].items()
        },
    }
    snapshot_entries = {
        str(binding["path"]): {
            "bytes": binding["bytes"],
            "sha256": binding["sha256"],
            "matches": True,
        }
        for binding in snapshot_bindings.values()
    }
    completion = _binding(enrichment_receipt)
    validation_receipt = case_root / "actual-validation/actual-validation-receipt.json"
    _write(
        validation_receipt,
        {
            "schema": m4.ACTUAL_VALIDATION_SCHEMA,
            "status": "completed",
            "case_id": case_id,
            "source_completion_receipt": completion,
            "source_bundle": {"path": str(source), "manifest_sha256": _sha(source_manifest), "file_count": 8, "bytes": 1, "production_validation": {"portable": True, "summary": {}}},
            "source_snapshot": snapshot_entries,
            "source_snapshot_after": snapshot_entries,
            "source_unchanged": True,
            "relocation": {"source_bundle": str(source), "destination_bundle": str(destination), "file_count": 8, "bytes": 1, "copy_mode": "full_regular_file_copy"},
            "isolated_replay": {"report": str(isolated_report), "portable": True, "source_paths_redacted": True, "denied_probes_passed": True},
            "semantic_negatives": {"count": 2, "passed": True, "reports": negative_reports, "scratch_removed_after_each_case": True},
            "launches": {"solver": False, "decoder": False, "converter": False},
        },
    )
    return {
        "case_id": case_id,
        "depth_m": depth,
        "direct_conversion": {"receipt": str(direct_exec), "report": str(direct_report)},
        "enrichment": {"receipt": str(enrichment_receipt), "execution_receipt": str(enrichment_exec)},
        "portable_build": {"execution_receipt": str(build_exec), "bundle_root": str(source)},
        "actual_validation": {"receipt": str(validation_receipt)},
    }


def _write_valid_cost_reconciliation(row: dict[str, Any], path: Path, *, case_id: str | None = None) -> None:
    actual_path = Path(row["actual_validation"]["receipt"])
    actual = json.loads(actual_path.read_text(encoding="utf-8"))
    case = case_id or row["case_id"]
    relocation_bytes = actual["relocation"]["bytes"]
    _write(
        path,
        {
            "schema": m4.EXTERNAL_RECONCILIATION_SCHEMA,
            "status": "completed",
            "case_id": case,
            "charge_id": f"F1/{case}/{m4.EXTERNAL_COPY_CHARGE_SUFFIX}",
            "original_preparation_bytes": 0,
            "observed_preparation_tree_bytes": relocation_bytes,
            "additional_persistent_bytes": relocation_bytes,
            "relocated_bundle": actual["relocation"]["destination_bundle"],
            "actual_relocation_evidence": _binding(actual_path),
        },
    )


def _input(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": m4.INPUT_SCHEMA,
        "release_id": "test-release",
        "release_version": "v1",
        "conditions": rows,
        "mother_reference": {"case_id": m4.MOTHER_CASE, "role": "mother_reference_only"},
    }


def test_pending_card_keeps_future_conditions_uncredited_and_validation_empty(tmp_path: Path) -> None:
    complete = _make_case(tmp_path, "UF_F1_MDBC_DP010_H050", 0.50)
    cost_path = tmp_path / "UF_F1_MDBC_DP010_H050" / "completed-cost-reconciliation.json"
    _write_valid_cost_reconciliation(complete, cost_path)
    complete["cost_reconciliation"] = str(cost_path)
    rows = [complete]
    rows.extend({"case_id": case_id, "depth_m": depth} for case_id, depth in m4.CASES[1:])
    card = m4.assemble(_input(rows))
    assert card["status"] == "pending_actual_receipts"
    assert card["development_partition"]["eligible_case_ids"] == ["UF_F1_MDBC_DP010_H050"]
    assert card["development_partition"]["condition_count"] == 4
    assert card["validation_partition"] == {
        "status": "empty_by_design",
        "condition_count": 0,
        "conditions": [],
        "reason": "one common upstream mother lineage; no fabricated validation split",
    }
    assert card["mother_reference"]["credit_status"] == "reference_only"
    assert all(not claim["claimed"] for claim in card["claims"].values())
    assert card["development_partition"]["conditions"][0]["cost_reconciliation"]["payload"]["status"] == "completed"
    pending = {row["case_id"]: row for row in card["development_partition"]["conditions"]}["UF_F1_MDBC_DP010_H052"]
    assert pending["status"] == "pending_actual_receipts"
    assert pending["credit_status"] == "not_credited"


def test_wrong_case_cost_reconciliation_cannot_promote_actual_row(tmp_path: Path) -> None:
    complete = _make_case(tmp_path, "UF_F1_MDBC_DP010_H050", 0.50)
    cost_path = tmp_path / "UF_F1_MDBC_DP010_H050" / "wrong-case-cost-reconciliation.json"
    _write_valid_cost_reconciliation(complete, cost_path, case_id="UF_F1_MDBC_DP010_H052")
    complete["cost_reconciliation"] = str(cost_path)
    rows = [complete]
    rows.extend({"case_id": case_id, "depth_m": depth} for case_id, depth in m4.CASES[1:])

    card = m4.assemble(_input(rows))
    rejected = card["development_partition"]["conditions"][0]
    assert rejected["status"] == "rejected_actual_receipts"
    assert rejected["eligible_for_development_partition"] is False
    assert "case_id" in rejected["rejection_reasons"][0]


def test_source_snapshot_binding_tamper_cannot_promote_actual_row(tmp_path: Path) -> None:
    complete = _make_case(tmp_path, "UF_F1_MDBC_DP010_H050", 0.50)
    validation_path = Path(complete["actual_validation"]["receipt"])
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    normalized_key = next(key for key in validation["source_snapshot"] if key.endswith("/normalized.h5"))
    validation["source_snapshot"][normalized_key]["sha256"] = "0" * 64
    validation_path.write_text(json.dumps(validation), encoding="utf-8")
    rows = [complete]
    rows.extend({"case_id": case_id, "depth_m": depth} for case_id, depth in m4.CASES[1:])

    card = m4.assemble(_input(rows))
    rejected = card["development_partition"]["conditions"][0]
    assert rejected["status"] == "rejected_actual_receipts"
    assert rejected["eligible_for_development_partition"] is False
    assert "binding disagrees" in rejected["rejection_reasons"][0]


def test_relocated_manifest_must_match_source_manifest(tmp_path: Path) -> None:
    complete = _make_case(tmp_path, "UF_F1_MDBC_DP010_H050", 0.50)
    destination_manifest = Path(complete["actual_validation"]["receipt"]).parents[1] / "nas-relocated/bundle/manifest.json"
    manifest = json.loads(destination_manifest.read_text(encoding="utf-8"))
    manifest["copy_marker"] = "tampered"
    destination_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [complete]
    rows.extend({"case_id": case_id, "depth_m": depth} for case_id, depth in m4.CASES[1:])

    card = m4.assemble(_input(rows))
    rejected = card["development_partition"]["conditions"][0]
    assert rejected["status"] == "rejected_actual_receipts"
    assert rejected["eligible_for_development_partition"] is False
    assert "manifest hash disagrees" in rejected["rejection_reasons"][0]


def test_four_actual_rows_bind_relocation_and_semantic_negatives_without_hdf5_read(tmp_path: Path) -> None:
    rows = [_make_case(tmp_path, case_id, depth) for case_id, depth in m4.CASES]
    card = m4.assemble(_input(rows))
    assert card["status"] == "completed_development_partition"
    assert card["development_partition"]["eligible_case_ids"] == [case_id for case_id, _ in m4.CASES]
    for row in card["development_partition"]["conditions"]:
        assert row["eligible_for_development_partition"] is True
        assert row["actual_validation"]["source_unchanged"] is True
        assert row["actual_validation"]["isolated_replay"]["denied_probes_passed"] is True
        assert row["actual_validation"]["semantic_negatives"]["passed"] is True
        assert row["fields"]["identity_axis"]["key"] == "(Zone,Idp)"
        assert row["fields"]["validity_mask"]["dataset"] == "valid"
        assert row["labels"]["missing"] == ["censored", "unknown"]
        assert row["reader_evaluator"]["self_contained_runtime"]["source_paths_redacted"] is True
        assert row["bundle"]["relocated"]["artifacts"]["runtime_adapter"]["path"].endswith("/runtime/m4_portable_adapter.py")
        assert row["no_hdf5_scan"] is True
    hashes = {row["physical_condition"]["actual"]["physical_condition_sha256"] for row in card["development_partition"]["conditions"]}
    assert len(hashes) == 4


def test_semantic_negative_failure_cannot_be_promoted(tmp_path: Path) -> None:
    row = _make_case(tmp_path, "UF_F1_MDBC_DP010_H050", 0.50)
    negative_path = Path(row["actual_validation"]["receipt"]).parent / "reports/typed_identity_endpoint_label.json"
    payload = json.loads(negative_path.read_text(encoding="utf-8"))
    payload["artifact_layer_rehashed"] = False
    negative_path.write_text(json.dumps(payload), encoding="utf-8")
    rows = [row]
    rows.extend({"case_id": case_id, "depth_m": depth} for case_id, depth in m4.CASES[1:])
    card = m4.assemble(_input(rows))
    failed = card["development_partition"]["conditions"][0]
    assert failed["status"] == "rejected_actual_receipts"
    assert failed["eligible_for_development_partition"] is False
    assert "rehashed" in failed["rejection_reasons"][0]


def test_interface_binding_tamper_is_rejected_before_credit(tmp_path: Path) -> None:
    first = _make_case(tmp_path, "UF_F1_MDBC_DP010_H050", 0.50)
    second = _make_case(tmp_path, "UF_F1_MDBC_DP010_H052", 0.52)
    second_interface = Path(second["portable_build"]["bundle_root"]) / "interface.json"
    payload = json.loads(second_interface.read_text(encoding="utf-8"))
    payload["physical_condition"]["physical_condition_sha256"] = json.loads((Path(first["portable_build"]["bundle_root"]) / "interface.json").read_text(encoding="utf-8"))["physical_condition"]["physical_condition_sha256"]
    second_interface.write_text(json.dumps(payload), encoding="utf-8")
    # The changed interface deliberately invalidates its manifest binding; the
    # row must remain rejected rather than silently receiving any credit.
    rows = [first, second]
    rows.extend({"case_id": case_id, "depth_m": depth} for case_id, depth in m4.CASES[2:])
    card = m4.assemble(_input(rows))
    row = {item["case_id"]: item for item in card["development_partition"]["conditions"]}["UF_F1_MDBC_DP010_H052"]
    assert row["eligible_for_development_partition"] is False
    assert row["status"] == "rejected_actual_receipts"
