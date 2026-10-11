#!/usr/bin/env python3
"""Assemble a receipt-gated M4 development data card.

The M4 producer and the actual relocation worker own the expensive checks.  A
release card is deliberately a small, downstream record: it reads JSON
receipts and sidecars, verifies their declared bindings, and records the
positive isolated replay plus the two rehashed semantic negatives.  It never
opens, hashes, or scans a normalized HDF5 file.  HDF5 bindings are checked by
``stat`` against the hashes already established by the producing receipt.

The card has four fixed development-condition slots (H050, H052, H058, and
H060), an empty validation partition, and a separate mother reference.  A slot
with missing actual receipts remains pending and cannot receive credit.  The
assembler is therefore useful before all four products exist while still
providing a ``--require-complete`` gate for a final root-reviewed card.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "ds-data-02.m4.release.v1"
INPUT_SCHEMA = "ds-data-02.m4.release-input.v1"
EXECUTION_SCHEMA = "ds02.execution-receipt.v1"
DIRECT_REPORT_SCHEMA = "ds-data-02.bi4-direct-conversion.v1"
ENRICHMENT_RECEIPT_SCHEMA = "ds-data-02.m4.direct-enrichment-receipt.v1"
INTERFACE_SCHEMA = "ds-data-02.m4.native-conversion-interface.v1"
BUNDLE_SCHEMA = "ds-data-02.m4.portable-bundle.v1"
ACTUAL_VALIDATION_SCHEMA = "ds-data-02.m4.actual-validation.v1"
ACTUAL_NEGATIVE_SCHEMA = "ds-data-02.m4.actual-semantic-negative.v1"
EXTERNAL_RECONCILIATION_SCHEMA = "ds02.upstream-first.external-storage-reconciliation.v1"
EVALUATOR_SCHEMA = "ds-data-02.m4.no-model-evaluator.v1"
READER_SCHEMA = "l2.f3.canonical_manifest.v1"
ENDPOINT_SCHEMA = "ds-data-02.m4.endpoint-transport.v1"
GEOMETRY_SCHEMAS = frozenset(("ds-data-02.m2.geometry.v1", "ds-data-02.m4.geometry.v1"))
CONTROL_SCHEMAS = frozenset(("ds-data-02.m2.control.v1", "ds-data-02.m4.control.v1"))

SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
CASES: tuple[tuple[str, float], ...] = (
    ("UF_F1_MDBC_DP010_H050", 0.50),
    ("UF_F1_MDBC_DP010_H052", 0.52),
    ("UF_F1_MDBC_DP010_H058", 0.58),
    ("UF_F1_MDBC_DP010_H060", 0.60),
)
CASE_DEPTHS = dict(CASES)
MOTHER_CASE = "UF_F1_MDBC_DAMBREAK3D"
MISSING_LABELS = frozenset(("unknown", "censored"))
ROOT_FIELDS: tuple[str, ...] = (
    "time",
    "particle_id",
    "particle_zone",
    "valid",
    "position",
    "velocity",
    "density",
    "mass",
    "pressure",
    "type",
    "mk",
    "initial_type",
    "initial_mk",
    "initial_mass",
)
FRAME_FIELDS: tuple[str, ...] = (
    "position",
    "velocity",
    "density",
    "mass",
    "pressure",
    "type",
    "mk",
)
INITIAL_FIELDS: tuple[str, ...] = ("initial_type", "initial_mk", "initial_mass")
REQUIRED_BUNDLE_ARTIFACTS = frozenset(
    (
        "normalized_hdf5",
        "geometry",
        "control",
        "interface",
        "evaluator",
        "reader_manifest",
        "runtime_adapter",
        "runtime_l2_reader",
    )
)
REQUIRED_ENDPOINT_FIELDS: tuple[str, ...] = (
    "particle_id_dataset",
    "particle_zone_dataset",
    "source_valid_dataset",
    "destination_valid_dataset",
    "source_label_dataset",
    "destination_label_dataset",
    "source_position_dataset",
    "destination_position_dataset",
    "displacement_dataset",
)
REQUIRED_ACTUAL_NEGATIVES = frozenset(("typed_identity_endpoint_label", "destination_position"))
REQUIRED_REHASHED_BINDINGS = frozenset(("normalized_hdf5", "interface", "reader_manifest", "manifest_sha256"))
EXPECTED_SAVED_FRAME_COUNT = 241
EXTERNAL_COPY_CHARGE_SUFFIX = "m4-actual-validation-001::external-nas-copy-delta"
REQUIRED_EVALUATOR_CHECKS = frozenset(
    (
        "validity_aware_nonfinite_policy",
        "full_initial_identity_all_frames",
        "full_typed_zone_idp_identity",
        "all_frame_validity_mask",
        "native_exclusion_mask_bound",
        "endpoint_labels_semantic",
        "missing_endpoint_fate_not_inferred",
        "geometry_evidence",
        "control_evidence",
    )
)
REQUIRED_SEMANTIC_CONTRACT = frozenset(
    ("typed_identity_hash_tamper", "geometry_control_semantic_tamper", "control_window_semantic_tamper")
)


class ReleaseError(ValueError):
    """Raised when a release input or actual receipt is unsafe to bind."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        raise ReleaseError(f"{label} is a symlink: {raw}")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise ReleaseError(f"{label} is not a regular file: {resolved}")
    return resolved


def _directory(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink():
        raise ReleaseError(f"{label} is a symlink: {raw}")
    resolved = raw.resolve()
    if not resolved.is_dir():
        raise ReleaseError(f"{label} is not a regular directory: {resolved}")
    return resolved


def _load_json(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"{label} must be a JSON object: {path}")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ReleaseError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseError(f"{label}.path is missing")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ReleaseError(f"{label}.path is not a safe relative path: {value!r}")
    return value


def _binding(path: Path, label: str, *, hash_content: bool = True, declared: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Bind a small file, or stat an HDF5 without reading its payload."""

    path = _regular(path, label)
    size = path.stat().st_size
    if declared is not None:
        if type(declared.get("bytes")) is not int or declared["bytes"] != size:
            raise ReleaseError(f"{label}.bytes disagrees with {path}")
        digest = _sha(declared.get("sha256"), f"{label}.sha256")
        if hash_content:
            actual = _sha256(path)
            if actual != digest:
                raise ReleaseError(f"{label}.sha256 disagrees with {path}")
            verified_by = "release_assembler_recomputed"
        else:
            # Large scientific payloads are deliberately trusted only through
            # the producer/runner hash.  This module performs no HDF5 scan.
            verified_by = "upstream_receipt_declared_hash;payload_not_read_by_release_assembler"
    else:
        digest = _sha256(path) if hash_content else ""
        verified_by = "release_assembler_recomputed" if hash_content else "payload_not_read_by_release_assembler"
    result = {"path": str(path), "bytes": size, "sha256": digest}
    if not hash_content:
        result["hash_verified_by"] = verified_by
    return result


def _json_binding(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    payload = _load_json(path, label)
    return payload, _binding(path, label)


def _declared_artifact(base: Path, value: Any, label: str, *, large_payload: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseError(f"{label} is not an artifact binding")
    rel = _safe_relative(value.get("path"), label)
    path = (base / rel).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ReleaseError(f"{label}.path escapes its bundle: {rel!r}")
    return _binding(path, label, hash_content=not large_payload, declared=value)


def _walk_portable_metadata(value: Any, location: str = "metadata", *, key: str = "") -> None:
    """Reject host paths in package metadata, preserving HDF5 dataset paths."""

    if isinstance(value, Mapping):
        for name, item in value.items():
            _walk_portable_metadata(item, f"{location}.{name}", key=str(name))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_portable_metadata(item, f"{location}[{index}]", key=key)
    elif isinstance(value, str) and value.startswith("/") and not key.endswith("_dataset"):
        raise ReleaseError(f"absolute host path remains in portable metadata at {location}")


def _first_mapping(row: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _path_from(mapping: Mapping[str, Any], *keys: str) -> Path | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return Path(value).expanduser()
    return None


def _required_paths(row: Mapping[str, Any]) -> dict[str, Path | None]:
    direct = _first_mapping(row, "direct_conversion", "direct")
    enrichment = _first_mapping(row, "enrichment", "direct_enrichment")
    build = _first_mapping(row, "portable_build", "build", "bundle")
    validation = _first_mapping(row, "actual_validation", "validation", "relocation_validation")
    return {
        "direct_receipt": _path_from(row, "direct_conversion_receipt", "direct_receipt") or _path_from(direct, "receipt", "execution_receipt"),
        "direct_report": _path_from(row, "direct_conversion_report", "direct_report", "conversion_report") or _path_from(direct, "report", "direct_conversion_report"),
        "enrichment_receipt": _path_from(row, "enrichment_receipt", "enrichment_product_receipt") or _path_from(enrichment, "receipt", "product_receipt"),
        "enrichment_execution_receipt": _path_from(row, "enrichment_execution_receipt") or _path_from(enrichment, "execution_receipt", "runner_receipt"),
        "portable_build_execution_receipt": _path_from(row, "portable_build_execution_receipt") or _path_from(build, "execution_receipt", "runner_receipt"),
        "bundle_root": _path_from(row, "bundle_root", "portable_bundle") or _path_from(build, "bundle_root", "root", "path"),
        "actual_validation_receipt": _path_from(row, "actual_validation_receipt", "validation_receipt") or _path_from(validation, "receipt", "actual_receipt"),
    }


def _cost_reconciliation_path(row: Mapping[str, Any]) -> Path | None:
    validation = _first_mapping(row, "actual_validation", "validation", "relocation_validation")
    value = _path_from(row, "cost_reconciliation", "cost_reconciliation_receipt", "cost_receipt")
    if value is not None:
        return value
    return _path_from(validation, "cost_reconciliation", "cost_receipt", "cost_receipt_path")


def _cost_reconciliation(
    row: Mapping[str, Any],
    case_id: str,
    actual_validation: Mapping[str, Any],
) -> dict[str, Any] | None:
    path = _cost_reconciliation_path(row)
    if path is None:
        return None
    payload, binding = _json_binding(path, "cost reconciliation")
    if payload.get("schema") != EXTERNAL_RECONCILIATION_SCHEMA:
        raise ReleaseError("provided cost reconciliation has an unsupported schema")
    if payload.get("status") not in ("completed", "reconciled", "passed"):
        raise ReleaseError("provided cost reconciliation is not completed")
    if payload.get("case_id") != case_id:
        raise ReleaseError("cost reconciliation case_id disagrees")
    expected_charge_id = f"F1/{case_id}/{EXTERNAL_COPY_CHARGE_SUFFIX}"
    if payload.get("charge_id") != expected_charge_id:
        raise ReleaseError("cost reconciliation charge_id disagrees")

    evidence = payload.get("actual_relocation_evidence")
    expected_receipt = actual_validation.get("receipt")
    if not isinstance(evidence, Mapping) or not isinstance(expected_receipt, Mapping):
        raise ReleaseError("cost reconciliation lacks actual relocation evidence")
    evidence_path_value = evidence.get("path")
    if not isinstance(evidence_path_value, str) or not evidence_path_value:
        raise ReleaseError("cost reconciliation actual relocation evidence path is missing")
    evidence_path = _regular(Path(evidence_path_value), "cost reconciliation actual relocation evidence")
    if str(evidence_path) != expected_receipt.get("path"):
        raise ReleaseError("cost reconciliation actual relocation evidence path disagrees")
    _compare_binding(evidence, expected_receipt, "cost reconciliation actual relocation evidence")

    relocation = actual_validation.get("relocation")
    if not isinstance(relocation, Mapping):
        raise ReleaseError("cost reconciliation lacks actual relocation bytes")
    relocation_bytes = relocation.get("bytes")
    if type(relocation_bytes) is not int or relocation_bytes <= 0:
        raise ReleaseError("actual relocation bytes must be positive")
    delta = payload.get("additional_persistent_bytes")
    if type(delta) is not int or delta <= 0:
        raise ReleaseError("cost reconciliation additional bytes must be positive")
    if delta != relocation_bytes:
        raise ReleaseError("cost reconciliation additional bytes disagree with relocation.bytes")
    original_bytes = payload.get("original_preparation_bytes")
    observed_bytes = payload.get("observed_preparation_tree_bytes")
    if type(original_bytes) is not int or original_bytes < 0 or type(observed_bytes) is not int or observed_bytes < 0:
        raise ReleaseError("cost reconciliation preparation byte accounting is invalid")
    if observed_bytes < original_bytes or observed_bytes - original_bytes != delta:
        raise ReleaseError("cost reconciliation preparation byte delta disagrees with relocation.bytes")
    return {"binding": binding, "payload": payload}


def _execution_receipt(path: Path, case_id: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt, binding = _json_binding(path, label)
    if receipt.get("schema") != EXECUTION_SCHEMA:
        raise ReleaseError(f"{label} has unsupported schema: {receipt.get('schema')!r}")
    if receipt.get("status") != "completed":
        raise ReleaseError(f"{label} is not completed")
    if receipt.get("returncode") not in (None, 0):
        raise ReleaseError(f"{label} has nonzero returncode")
    request = receipt.get("request")
    if not isinstance(request, Mapping) or request.get("case_id") != case_id:
        raise ReleaseError(f"{label}.request.case_id disagrees with {case_id}")
    if request.get("schema") not in (None, "ds-data-02.runner.request.v1"):
        raise ReleaseError(f"{label}.request has an unsupported schema")
    return receipt, binding


def _compare_binding(actual: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    if actual.get("bytes") != expected.get("bytes") or actual.get("sha256") != expected.get("sha256"):
        raise ReleaseError(f"{label} binding disagrees")


def _path_key(path: Path) -> str:
    return str(path.expanduser().resolve())


def _direct_product(paths: Mapping[str, Path | None], case_id: str) -> dict[str, Any]:
    receipt_path = paths["direct_receipt"]
    report_path = paths["direct_report"]
    if receipt_path is None or report_path is None:
        raise ReleaseError("direct conversion receipt and report are required")
    receipt, receipt_binding = _execution_receipt(receipt_path, case_id, "direct conversion execution receipt")
    report, report_binding = _json_binding(report_path, "direct conversion report")
    if report.get("schema") != DIRECT_REPORT_SCHEMA or report.get("conversion_status") != "completed":
        raise ReleaseError("direct conversion report is not a completed BI4 conversion report")
    if report.get("frames") != int(report["frames"]) or int(report["frames"]) <= 0:
        raise ReleaseError("direct conversion report has no positive frame count")
    if int(report.get("particles", 0)) <= 0:
        raise ReleaseError("direct conversion report has no positive particle count")
    typed = report.get("typed_identity")
    if not isinstance(typed, Mapping) or typed.get("key") != "(Zone,Idp)":
        raise ReleaseError("direct conversion report does not bind the (Zone,Idp) identity")
    output_path_value = report.get("output_hdf5")
    if not isinstance(output_path_value, str) or not output_path_value:
        raise ReleaseError("direct conversion report lacks output_hdf5")
    output_path = _regular(Path(output_path_value), "direct conversion HDF5")
    output_declared = {"bytes": output_path.stat().st_size, "sha256": report.get("output_sha256")}
    output_binding = _binding(output_path, "direct conversion HDF5", hash_content=False, declared=output_declared)
    return {
        "execution_receipt": receipt_binding,
        "execution_status": receipt.get("status"),
        "attempt_id": receipt.get("request", {}).get("attempt_id"),
        "report": report_binding,
        "output_hdf5": output_binding,
        "summary": {
            "schema": report["schema"],
            "conversion_status": report["conversion_status"],
            "frames": int(report["frames"]),
            "particles": int(report["particles"]),
            "coordinate_frame": report.get("coordinate_frame"),
            "solver_dimension": report.get("solver_dimension"),
            "typed_identity": dict(typed),
            "conversion_claim": report.get("conversion_claim"),
            "q_i_status": report.get("q_i_status"),
            "q_n_status": report.get("q_n_status"),
            "production_eligibility": report.get("production_eligibility"),
        },
        "report_payload": report,
    }


def _enrichment_product(paths: Mapping[str, Path | None], case_id: str) -> dict[str, Any]:
    receipt_path = paths["enrichment_receipt"]
    execution_path = paths["enrichment_execution_receipt"]
    if receipt_path is None or execution_path is None:
        raise ReleaseError("enrichment product and execution receipts are required")
    receipt, receipt_binding = _json_binding(receipt_path, "enrichment receipt")
    if receipt.get("schema") != ENRICHMENT_RECEIPT_SCHEMA or receipt.get("status") != "completed":
        raise ReleaseError("enrichment receipt is not completed")
    if receipt.get("case_id") != case_id:
        raise ReleaseError("enrichment receipt case_id disagrees")
    if receipt.get("credit_status") not in (None, "not_credited"):
        raise ReleaseError("enrichment receipt grants unapproved credit")
    if receipt.get("physical_fate_inferred") is not False:
        raise ReleaseError("enrichment receipt infers physical fate")
    execution, execution_binding = _execution_receipt(execution_path, case_id, "enrichment execution receipt")
    outputs = receipt.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ReleaseError("enrichment receipt lacks outputs")
    output_bindings: dict[str, Any] = {}
    for name in ("control", "geometry", "interface", "owner_metadata", "enriched_hdf5"):
        declared = outputs.get(name)
        if not isinstance(declared, Mapping):
            raise ReleaseError(f"enrichment receipt lacks outputs.{name}")
        raw = declared.get("path")
        if not isinstance(raw, str) or not raw:
            raise ReleaseError(f"enrichment outputs.{name}.path is missing")
        path = (receipt_path.parent / raw).resolve()
        if name == "enriched_hdf5":
            output_bindings[name] = _binding(path, f"enrichment output {name}", hash_content=False, declared=declared)
        else:
            output_bindings[name] = _binding(path, f"enrichment output {name}", declared=declared)
    interface = _load_json((receipt_path.parent / outputs["interface"]["path"]).resolve(), "enrichment interface")
    if interface.get("schema") != INTERFACE_SCHEMA or interface.get("case_id") != case_id:
        raise ReleaseError("enrichment interface is not the expected M4 interface")
    physical = receipt.get("physical_condition")
    if not isinstance(physical, Mapping) or not isinstance(physical.get("sha256"), str):
        raise ReleaseError("enrichment receipt lacks physical-condition hash")
    return {
        "receipt": receipt_binding,
        "execution_receipt": execution_binding,
        "execution_status": execution.get("status"),
        "attempt_id": execution.get("request", {}).get("attempt_id"),
        "outputs": output_bindings,
        "physical_condition": dict(physical),
        "native_exclusion": receipt.get("native_exclusion"),
        "source": receipt.get("source"),
        "receipt_payload": receipt,
    }


def _assert_interface_shape(interface: Mapping[str, Any], manifest: Mapping[str, Any], *, case_id: str) -> dict[str, Any]:
    if interface.get("schema") != INTERFACE_SCHEMA or interface.get("case_id") != case_id:
        raise ReleaseError("bundle interface schema or case_id is invalid")
    if interface.get("family_id") != "F1" or interface.get("status") != "normalized_verified":
        raise ReleaseError("bundle interface is not a verified F1 product")
    if interface.get("credit_status") != "not_credited" or interface.get("physical_fate_inferred") is not False:
        raise ReleaseError("bundle interface has an unsafe credit or fate status")
    normalized = interface.get("normalized_hdf5")
    artifacts = manifest.get("artifacts")
    if not isinstance(normalized, Mapping) or not isinstance(artifacts, Mapping):
        raise ReleaseError("bundle interface or artifacts are missing")
    if normalized.get("path") != "normalized.h5":
        raise ReleaseError("bundle interface does not bind normalized.h5")
    _compare_binding(normalized, artifacts.get("normalized_hdf5", {}), "interface normalized HDF5")
    identity = interface.get("identity_axis")
    if not isinstance(identity, Mapping) or identity.get("key") != "(Zone,Idp)":
        raise ReleaseError("bundle interface lacks the full (Zone,Idp) identity axis")
    if identity.get("full_initial_identity") is not True or identity.get("all_frames_fixed_axis") is not True:
        raise ReleaseError("bundle interface does not retain the full initial identity on all frames")
    if type(identity.get("initial_particle_count")) is not int or identity["initial_particle_count"] <= 0:
        raise ReleaseError("bundle interface has no positive initial particle count")
    if type(identity.get("frame_count")) is not int or identity["frame_count"] <= 0:
        raise ReleaseError("bundle interface has no positive frame count")
    _sha(identity.get("initial_ids_sha256"), "identity_axis.initial_ids_sha256")
    _sha(identity.get("initial_typed_ids_sha256", identity.get("initial_identity_sha256")), "identity_axis.initial_typed_ids_sha256")
    exclusion = interface.get("exclusion_mask")
    if not isinstance(exclusion, Mapping) or exclusion.get("status") != "verified":
        raise ReleaseError("bundle interface lacks a verified native exclusion mask")
    if type(exclusion.get("count")) is not int or exclusion["count"] < 0:
        raise ReleaseError("bundle interface has an invalid native exclusion count")
    _sha(exclusion.get("ids_sha256"), "exclusion_mask.ids_sha256")
    if exclusion.get("physical_fate_inferred") is not False:
        raise ReleaseError("native exclusion mask infers physical fate")
    endpoints = interface.get("endpoint_transport")
    if not isinstance(endpoints, Mapping) or endpoints.get("schema") != ENDPOINT_SCHEMA:
        raise ReleaseError("bundle interface lacks the endpoint transport contract")
    if endpoints.get("source_frame") != 0 or endpoints.get("destination_frame") != "last":
        raise ReleaseError("endpoint transport does not bind first and last frames")
    if endpoints.get("source_valid_label") != "valid_source" or endpoints.get("destination_valid_label") != "valid_destination":
        raise ReleaseError("endpoint valid labels are not explicit")
    if set(endpoints.get("missing_endpoint_labels", [])) != MISSING_LABELS:
        raise ReleaseError("endpoint missing labels must be exactly unknown and censored")
    if endpoints.get("physical_fate_inferred") is not False:
        raise ReleaseError("endpoint transport infers physical fate")
    for key in REQUIRED_ENDPOINT_FIELDS:
        value = endpoints.get(key)
        if not isinstance(value, str) or not value.startswith("/"):
            raise ReleaseError(f"endpoint transport field {key} is not an HDF5 dataset path")
    for name in ("geometry", "control"):
        binding = interface.get(name)
        if not isinstance(binding, Mapping):
            raise ReleaseError(f"bundle interface lacks {name} binding")
        if binding.get("path") != f"{name}.json":
            raise ReleaseError(f"bundle interface {name} binding is not package-local")
        _compare_binding(binding, artifacts.get(name, {}), f"interface {name}")
    physical = interface.get("physical_condition")
    if not isinstance(physical, Mapping):
        raise ReleaseError("bundle interface lacks physical-condition identity")
    physical_hash = _sha(physical.get("physical_condition_sha256"), "physical_condition_sha256")
    depth = physical.get("depth_m")
    if type(depth) not in (int, float):
        raise ReleaseError("bundle interface lacks physical depth")
    source_mother = interface.get("source_mother")
    if not isinstance(source_mother, Mapping) or source_mother.get("case_id") != MOTHER_CASE:
        raise ReleaseError("bundle interface does not mark the mother as reference-only")
    if interface.get("portable_source_paths_redacted") is not True:
        raise ReleaseError("bundle interface does not redact source paths")
    return {
        "identity_axis": dict(identity),
        "exclusion_mask": dict(exclusion),
        "endpoint_transport": dict(endpoints),
        "physical_condition": dict(physical),
        "source_mother": dict(source_mother),
        "physical_condition_sha256": physical_hash,
    }


def _bundle(bundle_root: Path, case_id: str, label: str) -> dict[str, Any]:
    root = _directory(bundle_root, label)
    manifest, manifest_binding = _json_binding(root / "manifest.json", f"{label} manifest")
    if manifest.get("schema") != BUNDLE_SCHEMA or manifest.get("case_id") != case_id:
        raise ReleaseError(f"{label} manifest schema or case_id is invalid")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or not REQUIRED_BUNDLE_ARTIFACTS.issubset(artifacts):
        raise ReleaseError(f"{label} manifest lacks required artifacts")
    artifact_bindings: dict[str, Any] = {}
    for name, declared in artifacts.items():
        artifact_bindings[name] = _declared_artifact(root, declared, f"{label} artifact {name}", large_payload=name == "normalized_hdf5")
    interface = _load_json(root / "interface.json", f"{label} interface")
    geometry = _load_json(root / "geometry.json", f"{label} geometry")
    control = _load_json(root / "control.json", f"{label} control")
    evaluator = _load_json(root / "evaluator.json", f"{label} evaluator")
    reader = _load_json(root / "reader-manifest.json", f"{label} reader manifest")
    for payload, name in ((interface, "interface"), (geometry, "geometry"), (control, "control"), (evaluator, "evaluator"), (reader, "reader_manifest")):
        _walk_portable_metadata(payload, f"{label}.{name}")
    interface_summary = _assert_interface_shape(interface, manifest, case_id=case_id)
    if geometry.get("schema") not in GEOMETRY_SCHEMAS or geometry.get("case_id") != case_id:
        raise ReleaseError(f"{label} geometry sidecar schema or case_id is invalid")
    if geometry.get("physical_fate_inferred") is not False:
        raise ReleaseError(f"{label} geometry sidecar infers physical fate")
    if control.get("schema") not in CONTROL_SCHEMAS or control.get("case_id") != case_id:
        raise ReleaseError(f"{label} control sidecar schema or case_id is invalid")
    if control.get("physical_fate_inferred") is not False:
        raise ReleaseError(f"{label} control sidecar infers physical fate")
    if not isinstance(geometry.get("geometry"), Mapping) or not geometry["geometry"]:
        raise ReleaseError(f"{label} geometry sidecar lacks geometry evidence")
    if not isinstance(geometry.get("coordinate_frame"), str) or not geometry["coordinate_frame"]:
        raise ReleaseError(f"{label} geometry sidecar lacks coordinate frame")
    if geometry.get("solver_dimension") != 3:
        raise ReleaseError(f"{label} geometry sidecar is not three-dimensional")
    if not isinstance(control.get("event_window"), Mapping) or not control["event_window"]:
        raise ReleaseError(f"{label} control sidecar lacks event window")
    physical_hash = interface_summary["physical_condition_sha256"]
    if geometry.get("physical_condition_sha256") != physical_hash or control.get("physical_condition_sha256") != physical_hash:
        raise ReleaseError(f"{label} geometry/control physical-condition hashes disagree")
    if evaluator.get("schema") != EVALUATOR_SCHEMA or evaluator.get("case_id") != case_id or evaluator.get("passed") is not True:
        raise ReleaseError(f"{label} evaluator did not pass")
    checks = evaluator.get("checks")
    if not isinstance(checks, Mapping) or set(checks) != REQUIRED_EVALUATOR_CHECKS or not all(checks.values()):
        raise ReleaseError(f"{label} evaluator checks are incomplete")
    contract = evaluator.get("semantic_negative_contract")
    if not isinstance(contract, Mapping) or set(contract) != REQUIRED_SEMANTIC_CONTRACT or not all(value == "must_reject" for value in contract.values()):
        raise ReleaseError(f"{label} evaluator semantic-negative contract is incomplete")
    if reader.get("schema") != READER_SCHEMA or reader.get("repository_root") != ".":
        raise ReleaseError(f"{label} reader manifest is not package-local")
    cases = reader.get("cases")
    if not isinstance(cases, list) or len(cases) != 1 or not isinstance(cases[0], Mapping):
        raise ReleaseError(f"{label} reader manifest must contain one case")
    reader_case = cases[0]
    normalized = artifacts["normalized_hdf5"]
    if reader_case.get("case_id") != case_id or reader_case.get("hdf5") != "normalized.h5":
        raise ReleaseError(f"{label} reader manifest case does not bind normalized.h5")
    if reader_case.get("bytes") != normalized.get("bytes") or reader_case.get("sha256") != normalized.get("sha256"):
        raise ReleaseError(f"{label} reader manifest disagrees with normalized HDF5")
    policy = manifest.get("portable_policy")
    if not isinstance(policy, Mapping) or any(policy.get(key) is not False for key in ("native_decoder_in_bundle", "raw_native_payload_in_bundle", "physical_fate_inferred", "m2_bundle_modified")):
        raise ReleaseError(f"{label} portable policy is unsafe")
    runtime = manifest.get("runtime")
    if not isinstance(runtime, Mapping) or runtime.get("source_paths_redacted") is not True or runtime.get("adapter") != "runtime/m4_portable_adapter.py":
        raise ReleaseError(f"{label} runtime is not self-contained")
    if artifacts["runtime_adapter"].get("path") != "runtime/m4_portable_adapter.py" or artifacts["runtime_l2_reader"].get("path") != "runtime/l2_reader.py":
        raise ReleaseError(f"{label} runtime artifacts are not package-local")
    return {
        "root": str(root),
        "manifest": manifest_binding,
        "manifest_payload": manifest,
        "artifacts": artifact_bindings,
        "interface": interface,
        "geometry": geometry,
        "control": control,
        "evaluator": evaluator,
        "reader_manifest": reader,
        "interface_summary": interface_summary,
        "self_contained_runtime": {
            "source_paths_redacted": True,
            "runtime_adapter": artifact_bindings["runtime_adapter"],
            "runtime_l2_reader": artifact_bindings["runtime_l2_reader"],
            "portable_policy": dict(policy),
        },
    }


def _snapshot_entry(snapshot: Mapping[str, Any], path: Path) -> Mapping[str, Any] | None:
    exact = snapshot.get(str(path))
    if isinstance(exact, Mapping):
        return exact
    for key, value in snapshot.items():
        if isinstance(key, str) and key.endswith("/" + path.name) and isinstance(value, Mapping):
            return value
    return None


def _actual_validation(paths: Mapping[str, Path | None], case_id: str, source_bundle: Mapping[str, Any], enrichment: Mapping[str, Any]) -> dict[str, Any]:
    receipt_path = paths["actual_validation_receipt"]
    if receipt_path is None:
        raise ReleaseError("actual validation receipt is required")
    receipt, receipt_binding = _json_binding(receipt_path, "actual validation receipt")
    if receipt.get("schema") != ACTUAL_VALIDATION_SCHEMA or receipt.get("status") != "completed":
        raise ReleaseError("actual validation receipt is not completed")
    if receipt.get("case_id") != case_id:
        raise ReleaseError("actual validation case_id disagrees")
    if receipt.get("source_unchanged") is not True:
        raise ReleaseError("actual validation does not prove source immutability")
    completion = receipt.get("source_completion_receipt")
    if not isinstance(completion, Mapping):
        raise ReleaseError("actual validation lacks source completion receipt")
    _compare_binding(completion, enrichment["receipt"], "actual validation source completion receipt")
    source = receipt.get("source_bundle")
    if not isinstance(source, Mapping) or _path_key(Path(str(source.get("path", "")))) != _path_key(Path(source_bundle["root"])):
        raise ReleaseError("actual validation source bundle disagrees with portable source")
    if source.get("manifest_sha256") != source_bundle["manifest"]["sha256"]:
        raise ReleaseError("actual validation source manifest hash disagrees")
    production_validation = source.get("production_validation")
    if not isinstance(production_validation, Mapping) or production_validation.get("portable") is not True:
        raise ReleaseError("actual validation lacks a positive source portable replay precondition")
    for snapshot_name in ("source_snapshot", "source_snapshot_after"):
        snapshot = receipt.get(snapshot_name)
        if not isinstance(snapshot, Mapping) or not snapshot:
            raise ReleaseError(f"actual validation lacks {snapshot_name}")
        # The actual worker has already hashed these files.  Compare its
        # metadata against the producer manifest without opening any HDF5.
        snapshot_bindings = {"manifest": source_bundle["manifest"], **source_bundle["artifacts"]}
        for name, expected in snapshot_bindings.items():
            artifact_path = Path(expected["path"])
            entry = _snapshot_entry(snapshot, artifact_path)
            if not isinstance(entry, Mapping) or entry.get("matches") is not True:
                raise ReleaseError(f"actual validation {snapshot_name} does not bind unchanged {name}")
            _compare_binding(entry, expected, f"actual validation {snapshot_name} {name}")
    isolated = receipt.get("isolated_replay")
    if not isinstance(isolated, Mapping) or isolated.get("portable") is not True or isolated.get("source_paths_redacted") is not True or isolated.get("denied_probes_passed") is not True:
        raise ReleaseError("actual validation lacks positive isolated replay gates")
    isolated_report = isolated.get("report")
    isolated_report_binding = None
    if isinstance(isolated_report, str) and isolated_report:
        isolated_report_binding = _binding(Path(isolated_report), "isolated replay report")
    relocation = receipt.get("relocation")
    if not isinstance(relocation, Mapping):
        raise ReleaseError("actual validation lacks relocation binding")
    destination_value = relocation.get("destination_bundle")
    if not isinstance(destination_value, str) or not destination_value:
        raise ReleaseError("actual validation lacks relocated bundle path")
    destination_root = _directory(Path(destination_value), "relocated bundle")
    if destination_root == Path(source_bundle["root"]).resolve():
        raise ReleaseError("relocated bundle is the source bundle")
    relocated = _bundle(destination_root, case_id, "relocated bundle")
    if relocated["manifest"]["sha256"] != source_bundle["manifest"]["sha256"]:
        raise ReleaseError("relocated bundle manifest hash disagrees with source bundle")
    negatives = receipt.get("semantic_negatives")
    if not isinstance(negatives, Mapping) or negatives.get("count") != 2 or negatives.get("passed") is not True or negatives.get("scratch_removed_after_each_case") is not True:
        raise ReleaseError("actual validation lacks both passed semantic negatives")
    reports = negatives.get("reports")
    if not isinstance(reports, list) or len(reports) != 2:
        raise ReleaseError("actual validation semantic-negative report list is incomplete")
    negative_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for report_value in reports:
        if not isinstance(report_value, str):
            raise ReleaseError("actual validation semantic-negative report path is invalid")
        negative, negative_binding = _json_binding(Path(report_value), "actual semantic-negative report")
        if negative.get("schema") != ACTUAL_NEGATIVE_SCHEMA or negative.get("status") != "rejected_as_expected":
            raise ReleaseError("actual semantic-negative report is not a passed rejection")
        name = negative.get("negative")
        if name not in REQUIRED_ACTUAL_NEGATIVES or name in seen:
            raise ReleaseError("actual semantic-negative reports do not cover the two required cases")
        seen.add(name)
        if negative.get("artifact_layer_rehashed") is not True or negative.get("source_bundle_untouched") is not True:
            raise ReleaseError(f"actual semantic-negative {name} lacks rehashed source-immutable evidence")
        mutation = negative.get("mutation")
        rehashed = mutation.get("rehashed") if isinstance(mutation, Mapping) else None
        if not isinstance(rehashed, Mapping) or not REQUIRED_REHASHED_BINDINGS.issubset(rehashed):
            raise ReleaseError(f"actual semantic-negative {name} did not rebind every artifact layer")
        validator = negative.get("production_validator")
        if not isinstance(validator, Mapping) or validator.get("returncode") == 0:
            raise ReleaseError(f"actual semantic-negative {name} lacks a rejecting production-validator result")
        negative_rows.append({"report": negative_binding, "payload": negative})
    if seen != REQUIRED_ACTUAL_NEGATIVES:
        raise ReleaseError("actual semantic-negative set is incomplete")
    return {
        "receipt": receipt_binding,
        "receipt_payload": receipt,
        "source_unchanged": True,
        "isolated_replay": {
            "report": isolated_report_binding,
            "portable": True,
            "source_paths_redacted": True,
            "denied_probes_passed": True,
        },
        "relocation": {
            "source_bundle": str(Path(source_bundle["root"]).resolve()),
            "destination_bundle": str(destination_root),
            "file_count": relocation.get("file_count"),
            "bytes": relocation.get("bytes"),
            "copy_mode": relocation.get("copy_mode"),
            "manifest": relocated["manifest"],
            "bundle": relocated,
        },
        "semantic_negatives": {
            "count": 2,
            "passed": True,
            "reports": negative_rows,
            "scratch_removed_after_each_case": True,
        },
        "launches": receipt.get("launches"),
    }


def _owner_and_xml(
    direct: Mapping[str, Any],
    enrichment: Mapping[str, Any],
    interface: Mapping[str, Any],
    geometry_payload: Mapping[str, Any],
    expected_depth: float,
    case_id: str,
) -> dict[str, Any]:
    report = direct["report_payload"]
    provenance = report.get("source_provenance")
    if not isinstance(provenance, Mapping):
        raise ReleaseError("direct report lacks source provenance")
    result: dict[str, Any] = {}
    for key, label in (("generated_xml", "generated child XML"), ("owner_metadata", "child owner metadata")):
        if key == "owner_metadata":
            bound = enrichment["outputs"].get("owner_metadata")
            if not isinstance(bound, Mapping):
                raise ReleaseError("enrichment receipt lacks final child owner metadata binding")
            path = _regular(Path(str(bound["path"])), label)
            bound = dict(bound)
        else:
            value = provenance.get(key)
            if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
                raise ReleaseError(f"direct report lacks {label} binding")
            path = _regular(Path(value["path"]), label)
            expected_hash = value.get("sha256")
            declared = {"bytes": path.stat().st_size, "sha256": expected_hash}
            bound = _binding(path, label, declared=declared)
        result[key] = bound
        if key == "generated_xml":
            physical = interface["physical_condition"]
            if physical.get("generated_xml_sha256") != bound["sha256"]:
                raise ReleaseError("generated child XML hash disagrees with physical condition")
        else:
            owner = _load_json(path, label)
            if owner.get("physical_case_id") != case_id:
                raise ReleaseError("child owner metadata physical_case_id disagrees")
            params = owner.get("parameter_values")
            geometry = owner.get("geometry")
            owner_obstacle = geometry.get("central_obstacle") if isinstance(geometry, Mapping) else None
            if not isinstance(owner_obstacle, Mapping):
                raise ReleaseError("child owner metadata lacks central obstacle geometry")
            expected_obstacle = geometry_payload.get("geometry", {}).get("central_obstacle")
            if owner_obstacle != expected_obstacle:
                raise ReleaseError("owner and geometry sidecar central obstacle fields disagree")
            if isinstance(params, Mapping):
                expected_obstacle = owner_obstacle
                low = expected_obstacle.get("low_m") if isinstance(expected_obstacle, Mapping) else None
                size = expected_obstacle.get("size_m") if isinstance(expected_obstacle, Mapping) else None
                if isinstance(low, list) and isinstance(size, list) and len(low) >= 2 and len(size) >= 3:
                    expected = {
                        "separator_start_x_m": low[0],
                        "separator_end_x_m": low[0] + size[0],
                        "separator_y_m": low[1],
                        "separator_thickness_m": size[2],
                    }
                    for name, actual in expected.items():
                        if name in params and (
                            not isinstance(params[name], (int, float))
                            or not math.isclose(float(params[name]), float(actual), rel_tol=0.0, abs_tol=1.0e-12)
                        ):
                            raise ReleaseError(f"owner metadata {name} disagrees with actual central obstacle")
            initial_depth = params.get("initial_depth_m") if isinstance(params, Mapping) else None
            if initial_depth is not None and abs(float(initial_depth) - expected_depth) > 1.0e-12:
                raise ReleaseError("owner metadata initial depth disagrees with release condition")
    return result


def _condition(row: Mapping[str, Any]) -> dict[str, Any]:
    case_id = row.get("case_id")
    if case_id not in CASE_DEPTHS:
        raise ReleaseError(f"condition case_id must be one of the four M4 children: {case_id!r}")
    expected_depth = CASE_DEPTHS[case_id]
    if type(row.get("depth_m")) not in (int, float) or abs(float(row["depth_m"]) - expected_depth) > 1.0e-12:
        raise ReleaseError(f"{case_id} depth_m must be {expected_depth}")
    paths = _required_paths(row)
    cost_path = _cost_reconciliation_path(row)
    missing = [name for name, path in paths.items() if path is None or not path.exists()]
    if cost_path is not None and not cost_path.exists():
        missing.append("cost_reconciliation")
    base = {
        "case_id": case_id,
        "planned_depth_m": expected_depth,
        "planned_saved_frame_count": EXPECTED_SAVED_FRAME_COUNT,
        "role": "development_candidate",
        "credit_status": "not_credited",
        "eligible_for_development_partition": False,
        "status": "pending_actual_receipts" if missing else "rejected_actual_receipts",
        "gates": {name: False for name in ("direct_conversion", "enrichment", "portable_bundle", "isolated_replay", "semantic_negatives", "source_immutable")},
        "missing_receipts": sorted(missing),
        "rejection_reasons": [],
        "physical_condition": {"planned_depth_m": expected_depth, "actual": None},
        "hash_lineage": {},
    }
    if missing:
        return base
    try:
        direct = _direct_product(paths, case_id)
        enrichment = _enrichment_product(paths, case_id)
        source_bundle = _bundle(paths["bundle_root"] or Path(""), case_id, "source portable bundle")
        build_receipt, build_binding = _execution_receipt(paths["portable_build_execution_receipt"] or Path(""), case_id, "portable build execution receipt")
        if source_bundle["interface_summary"]["physical_condition_sha256"] != enrichment["physical_condition"]["sha256"]:
            raise ReleaseError("bundle and enrichment physical-condition hashes disagree")
        interface = source_bundle["interface"]
        direct_physical = direct["report_payload"].get("hash_scopes", {}).get("physical_condition_sha256")
        if direct_physical != source_bundle["interface_summary"]["physical_condition_sha256"]:
            raise ReleaseError("direct conversion physical-condition hash disagrees with bundle")
        actual_frames = source_bundle["interface_summary"]["identity_axis"].get("frame_count")
        if actual_frames != EXPECTED_SAVED_FRAME_COUNT or direct["summary"]["frames"] != EXPECTED_SAVED_FRAME_COUNT:
            raise ReleaseError("actual save.025 products must bind exactly 241 frames")
        actual_depth = interface["physical_condition"].get("depth_m")
        if type(actual_depth) not in (int, float) or abs(float(actual_depth) - expected_depth) > 1.0e-12:
            raise ReleaseError("bundle physical depth disagrees with condition slot")
        owner_xml = _owner_and_xml(direct, enrichment, interface, source_bundle["geometry"], expected_depth, case_id)
        actual_validation = _actual_validation(paths, case_id, source_bundle, enrichment)
        cost_reconciliation = _cost_reconciliation(row, case_id, actual_validation)
        base.update(
            {
                "status": "eligible_development_condition",
                "eligible_for_development_partition": True,
                "missing_receipts": [],
                "gates": {
                    "direct_conversion": True,
                    "enrichment": True,
                    "portable_bundle": True,
                    "isolated_replay": True,
                    "semantic_negatives": True,
                    "source_immutable": True,
                },
                "receipts": {
                    "direct_conversion": direct["execution_receipt"],
                    "enrichment": enrichment["execution_receipt"],
                    "portable_build": build_binding,
                    "enrichment_product": enrichment["receipt"],
                    "actual_validation": actual_validation["receipt"],
                },
                "actual_validation": {
                    "source_unchanged": True,
                    "isolated_replay": actual_validation["isolated_replay"],
                    "relocation": {key: value for key, value in actual_validation["relocation"].items() if key != "bundle"},
                    "semantic_negatives": {
                        "count": 2,
                        "passed": True,
                        "reports": [row["report"] for row in actual_validation["semantic_negatives"]["reports"]],
                        "scratch_removed_after_each_case": True,
                    },
                },
                "fields": {
                    "root_fields": list(ROOT_FIELDS),
                    "frame_fields": list(FRAME_FIELDS),
                    "initial_fields": list(INITIAL_FIELDS),
                    "validity_mask": {
                        "dataset": "valid",
                        "semantics": "explicit per-frame numerical validity; non-finite values are permitted only where false",
                        "all_frames_fixed_identity": True,
                    },
                    "identity_axis": source_bundle["interface_summary"]["identity_axis"],
                    "native_exclusion": source_bundle["interface_summary"]["exclusion_mask"],
                    "endpoint_transport": source_bundle["interface_summary"]["endpoint_transport"],
                },
                "labels": {
                    "source_valid": source_bundle["interface_summary"]["endpoint_transport"].get("source_valid_label"),
                    "destination_valid": source_bundle["interface_summary"]["endpoint_transport"].get("destination_valid_label"),
                    "missing": sorted(MISSING_LABELS),
                    "physical_fate_inferred": False,
                    "transport_contract": source_bundle["interface_summary"]["endpoint_transport"],
                },
                "geometry": {"binding": source_bundle["artifacts"]["geometry"], "payload": source_bundle["geometry"]},
                "control": {"binding": source_bundle["artifacts"]["control"], "payload": source_bundle["control"]},
                "reader_evaluator": {
                    "reader_manifest": {"binding": source_bundle["artifacts"]["reader_manifest"], "payload": source_bundle["reader_manifest"]},
                    "evaluator": {"binding": source_bundle["artifacts"]["evaluator"], "payload": source_bundle["evaluator"]},
                    "self_contained_runtime": source_bundle["self_contained_runtime"],
                },
                "physical_condition": {
                    "planned_depth_m": expected_depth,
                    "actual": source_bundle["interface_summary"]["physical_condition"],
                    "generated_xml": owner_xml["generated_xml"],
                    "owner_metadata": owner_xml["owner_metadata"],
                },
                "hash_lineage": {
                    "direct_conversion": {
                        "execution_receipt": direct["execution_receipt"],
                        "report": direct["report"],
                        "output_hdf5": direct["output_hdf5"],
                    },
                    "enrichment": {
                        "execution_receipt": enrichment["execution_receipt"],
                        "receipt": enrichment["receipt"],
                        "outputs": enrichment["outputs"],
                    },
                    "portable_build": {"execution_receipt": build_binding, "bundle_manifest": source_bundle["manifest"]},
                    "actual_validation": {"receipt": actual_validation["receipt"], "source_bundle": source_bundle["manifest"], "relocated_bundle": actual_validation["relocation"]["manifest"]},
                    "physical_condition_sha256": source_bundle["interface_summary"]["physical_condition_sha256"],
                },
                "source_mother": {**source_bundle["interface_summary"]["source_mother"], "credit_status": "reference_only"},
                "bundle": {
                    "source": {
                        "root": source_bundle["root"],
                        "manifest": source_bundle["manifest"],
                        "artifacts": source_bundle["artifacts"],
                        "self_contained_runtime": source_bundle["self_contained_runtime"],
                    },
                    "relocated": {
                        "root": actual_validation["relocation"]["destination_bundle"],
                        "manifest": actual_validation["relocation"]["manifest"],
                        "artifacts": actual_validation["relocation"]["bundle"]["artifacts"],
                        "self_contained_runtime": actual_validation["relocation"]["bundle"]["self_contained_runtime"],
                    },
                },
                "no_hdf5_scan": True,
            }
        )
        if cost_reconciliation is not None:
            base["cost_reconciliation"] = cost_reconciliation
            base["hash_lineage"]["cost_reconciliation"] = cost_reconciliation["binding"]
    except (ReleaseError, KeyError, TypeError, ValueError, OSError) as exc:
        base["status"] = "rejected_actual_receipts"
        base["rejection_reasons"] = [str(exc)]
    return base


def _validate_input(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if payload.get("schema") != INPUT_SCHEMA:
        raise ReleaseError(f"input schema must be {INPUT_SCHEMA}")
    conditions = payload.get("conditions")
    if not isinstance(conditions, list) or len(conditions) != len(CASES):
        raise ReleaseError("input must contain exactly four condition rows")
    by_case: dict[str, Mapping[str, Any]] = {}
    for row in conditions:
        if not isinstance(row, Mapping):
            raise ReleaseError("condition rows must be objects")
        case_id = row.get("case_id")
        if case_id in by_case:
            raise ReleaseError(f"duplicate condition row: {case_id}")
        by_case[case_id] = row
    if set(by_case) != set(CASE_DEPTHS):
        raise ReleaseError("input condition rows must be H050, H052, H058, and H060")
    mother = payload.get("mother_reference")
    if not isinstance(mother, Mapping):
        raise ReleaseError("mother_reference is required and must remain separate")
    if mother.get("case_id") not in (None, MOTHER_CASE):
        raise ReleaseError("mother_reference.case_id must identify the official mother")
    return [by_case[case_id] for case_id, _ in CASES]


def _mother_reference(payload: Mapping[str, Any]) -> dict[str, Any]:
    mother = dict(payload["mother_reference"])
    mother.setdefault("case_id", MOTHER_CASE)
    mother.setdefault("role", "mother_reference_only")
    mother["credit_status"] = "reference_only"
    mother["eligible_for_development_partition"] = False
    mother["used_for_validation"] = False
    mother.setdefault("reason", "common upstream mother lineage; no independent heldout credit")
    # The assembler records a supplied binding, but never invents a mother
    # conversion or promotes it into a child condition.
    for key in ("receipt", "bundle_manifest", "source"):
        value = mother.get(key)
        if isinstance(value, str) and value:
            path = _regular(Path(value), f"mother reference {key}")
            mother[key] = _binding(path, f"mother reference {key}")
        elif isinstance(value, Mapping) and isinstance(value.get("path"), str):
            path = _regular(Path(value["path"]), f"mother reference {key}")
            mother[key] = _binding(path, f"mother reference {key}")
    return mother


def assemble(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build a candidate release card from a four-row receipt manifest."""

    rows = _validate_input(payload)
    conditions = [_condition(row) for row in rows]
    seen_hashes: dict[str, str] = {}
    for row in conditions:
        if not row.get("eligible_for_development_partition"):
            continue
        physical = row.get("physical_condition", {}).get("actual", {})
        digest = physical.get("physical_condition_sha256") if isinstance(physical, Mapping) else None
        if digest in seen_hashes:
            row["status"] = "rejected_duplicate_physical_condition"
            row["eligible_for_development_partition"] = False
            row["rejection_reasons"] = [f"physical condition hash duplicates {seen_hashes[digest]}"]
            row["credit_status"] = "not_credited"
        elif isinstance(digest, str):
            seen_hashes[digest] = row["case_id"]
    eligible = [row["case_id"] for row in conditions if row.get("eligible_for_development_partition")]
    all_complete = len(eligible) == len(CASES)
    release_id = payload.get("release_id") or "ds-data-02-m4-development"
    version = payload.get("release_version") or "candidate"
    return {
        "schema": SCHEMA,
        "release_id": release_id,
        "release_version": version,
        "status": "completed_development_partition" if all_complete else "pending_actual_receipts",
        "candidate_only": True,
        "credit_status": "not_credited",
        "development_partition": {
            "status": "receipt_gated_candidate",
            "condition_count": len(CASES),
            "eligible_condition_count": len(eligible),
            "conditions": conditions,
            "eligible_case_ids": eligible,
            "credit_status": "not_credited",
            "lineage_policy": "all four conditions share the upstream mother lineage; no independent heldout credit",
        },
        "validation_partition": {
            "status": "empty_by_design",
            "condition_count": 0,
            "conditions": [],
            "reason": "one common upstream mother lineage; no fabricated validation split",
        },
        "mother_reference": _mother_reference(payload),
        "claims": {
            "q_n": {"claimed": False, "reason": "release assembly records conversion evidence only"},
            "q_e": {"claimed": False, "reason": "release assembly does not assess Q-E"},
            "convergence": {"claimed": False, "reason": "release assembly does not assess convergence"},
            "physical_fate": {"claimed": False, "reason": "native exclusions and endpoint censoring remain numerical UNKNOWN/unknown/censored"},
            "heldout_validation": {"claimed": False, "reason": "validation partition is intentionally empty"},
        },
        "release_gates": {
            "required_cases": [case_id for case_id, _ in CASES],
            "required_positive_isolated_replay": True,
            "required_rehashed_semantic_negatives": sorted(REQUIRED_ACTUAL_NEGATIVES),
            "source_bundle_immutable": True,
            "provided_cost_reconciliation_must_be_completed": True,
            "hdf5_scanned_by_release_assembler": False,
            "ready_for_root_final_review": all_complete,
        },
    }


# Descriptive public alias for callers that treat the card builder as an
# adapter rather than invoking the command-line entry point.
assemble_release = assemble


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ReleaseError(f"refusing to overwrite existing release card: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + f".partial-{os.getpid()}")
    if partial.exists() or partial.is_symlink():
        raise ReleaseError(f"stale partial release card exists: {partial}")
    try:
        with partial.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="ds-data-02.m4.release-input.v1 JSON")
    parser.add_argument("--output", required=True, type=Path, help="new candidate release card JSON")
    parser.add_argument("--require-complete", action="store_true", help="return nonzero unless all four actual rows pass")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _load_json(args.input, "release input")
        card = assemble(payload)
        _write_json(args.output, card)
        if args.require_complete and card["status"] != "completed_development_partition":
            print("m4-release: candidate remains pending actual receipts", file=sys.stderr)
            return 2
    except (ReleaseError, OSError, ValueError, TypeError) as exc:
        print(f"m4-release: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"schema": card["schema"], "status": card["status"], "eligible_case_ids": card["development_partition"]["eligible_case_ids"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
