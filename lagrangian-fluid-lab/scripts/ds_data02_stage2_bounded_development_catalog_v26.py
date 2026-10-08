#!/usr/bin/env python3
"""Build a bounded, source-indexed task catalog for all 336 CURRENT cases.

The catalog is deliberately a JSON-only consumer.  It joins the already
completed v25 source-closed metadata product, the source-closed all-118 native
cause product, the root-verified seven-family cards/quality product, and the
small root proof records for the full raw reconstructions.  It does not open
trajectory H5, materialized label H5, BI4, PartOut, or solver output.

Every CURRENT row is emitted exactly once.  An emitted task scope is a
bookkeeping or saved-frame artifact scope; physical destination, legal flux,
continuous event truth, dynamics, recovery transfer, effective split safety,
QN, QE, and QI remain UNKNOWN unless a separate future product proves them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.bounded-development-catalog.v26"
MANIFEST_SCHEMA = "ds02.stage2.bounded-development-manifest.v26"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
V25_SCHEMA = "ds02.stage2.source-closed-development-split.v25"
MECHANISM_SCHEMA = "ds02.stage2.omission-mechanism-probe.v3"
QUALITY_SCHEMA = "ds02.stage2.family-label-quality.v3"
FAMILIES = [f"F{i}" for i in range(1, 8)]
ANCHOR_INDICES = {"F1": 0, "F2": 78, "F3": 96, "F4": 144, "F5": 192, "F6": 240, "F7": 288}
MECHANISM_FAMILIES = {"F2", "F4", "F6"}
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}


class CatalogError(RuntimeError):
    """Raised when an evidence identity or catalog invariant is open."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def require_file(value: Any, label: str, *, allow_forbidden: bool = False) -> Path:
    if isinstance(value, Path):
        path = value.expanduser().resolve()
    elif isinstance(value, str) and value:
        path = Path(value).expanduser().resolve()
    else:
        raise CatalogError(f"{label} must be a non-empty path")
    if not path.is_file():
        raise CatalogError(f"{label} is missing: {path}")
    if not allow_forbidden and path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise CatalogError(f"{label} is a forbidden scientific payload: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise CatalogError(f"{label} must be a JSON object: {path}")
    return path, payload


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=SCRIPT.parents[2], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _ref(path: Path, role: str) -> dict[str, Any]:
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise CatalogError(f"{role} cannot bind a forbidden payload: {path}")
    return {"role": role, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _receipt_summary(path: Path, receipt: dict[str, Any], role: str, report_path: Path) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise CatalogError(f"{role} receipt schema is not execution-receipt.v1")
    if receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise CatalogError(f"{role} receipt is not a successful completed receipt")
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or Path(output_root).expanduser().resolve() != report_path.parent:
        raise CatalogError(f"{role} receipt output_root does not equal report parent")
    attempt_id = receipt.get("request", {}).get("attempt_id")
    if attempt_id and Path(output_root).name != attempt_id:
        raise CatalogError(f"{role} receipt attempt_id differs from output directory")
    return {
        "path": str(path), "sha256": sha256_file(path), "status": receipt.get("status"),
        "returncode": receipt.get("returncode"), "output_root": output_root,
        "request_sha256": receipt.get("request_sha256"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
    }


def _validate_current(path: Path, current: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], tuple[int, dict[str, Any]]]]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise CatalogError("CURRENT336 schema is not current336.v1")
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise CatalogError(f"CURRENT336 must contain exactly 336 cases, found {len(rows) if isinstance(rows, list) else 'non-list'}")
    by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
    family_counts = {family: 0 for family in FAMILIES}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CatalogError(f"CURRENT336 case {index} is not an object")
        family = row.get("family_id"); physical = row.get("physical_case_id")
        key = (family, physical)
        if family not in FAMILIES or not isinstance(physical, str) or key in by_key:
            raise CatalogError(f"CURRENT336 case identity is not unique/known at index {index}: {key}")
        if not isinstance(row.get("frames"), int) or row["frames"] <= 0:
            raise CatalogError(f"CURRENT336 case {key} lacks a positive frame count")
        window = row.get("actual_time_window_s")
        if not isinstance(window, list) or len(window) != 2 or not all(isinstance(value, (int, float)) for value in window):
            raise CatalogError(f"CURRENT336 case {key} lacks an exact two-endpoint time window")
        bindings = row.get("source_bindings")
        if not isinstance(bindings, dict) or not bindings:
            raise CatalogError(f"CURRENT336 case {key} lacks source bindings")
        family_counts[family] += 1
        by_key[key] = (index, row)
    if family_counts != {family: 48 for family in FAMILIES}:
        raise CatalogError(f"CURRENT336 family counts are not 48 each: {family_counts}")
    return rows, by_key


def _validate_v25(path: Path, v25: dict[str, Any], current_path: Path, current: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if v25.get("schema") != V25_SCHEMA:
        raise CatalogError("v25 source-closed product has an unexpected schema")
    if v25.get("inputs", {}).get("current336", {}).get("sha256") != sha256_file(current_path):
        raise CatalogError("v25 product is bound to another CURRENT336")
    components = v25.get("components")
    if not isinstance(components, list) or len(components) != 7:
        raise CatalogError("v25 product must preserve exactly seven components")
    component_by_family: dict[str, dict[str, Any]] = {}
    for component in components:
        members = component.get("members")
        if not isinstance(members, list) or len(members) != 1:
            raise CatalogError("v25 component must have one exact anchor member")
        family = members[0].get("family_id")
        if family not in FAMILIES or family in component_by_family:
            raise CatalogError(f"v25 component has a duplicate/unknown family: {family}")
        index = members[0].get("current_index")
        if index != ANCHOR_INDICES[family]:
            raise CatalogError(f"v25 component {family} is not the exact registered anchor index")
        row = current.get("cases", [])[index]
        if row.get("family_id") != family or row.get("physical_case_id") != members[0].get("physical_case_id"):
            raise CatalogError(f"v25 component {family} identity differs from CURRENT336")
        component_by_family[family] = component
    if sorted(component_by_family) != FAMILIES:
        raise CatalogError("v25 components do not cover all seven families")
    return component_by_family, {
        "path": str(path), "sha256": sha256_file(path),
        "status": v25.get("status"),
        "verification": copy_json(v25.get("verification") or {}),
    }


def _validate_v25_actual_proof(path: Path, proof: dict[str, Any], current_path: Path) -> dict[str, Any]:
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise CatalogError("v25 actual proof has an unexpected schema")
    if proof.get("status") != "PASS_ACTUAL_SEVEN_SOURCE_CLOSED_DEVELOPMENT_COMPONENT_ROLES":
        raise CatalogError("v25 actual proof is not the completed component-role verification")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("hidden_test") is not False or proof.get("all336_development_exposed") is not True:
        raise CatalogError("v25 actual proof does not close H5/BI4, hidden-test, and all336 scope")
    if proof.get("scientific_qualification", {}).get("QN") != "UNKNOWN" or proof.get("scientific_qualification", {}).get("QE") != "UNKNOWN" or proof.get("scientific_qualification", {}).get("QI") != "UNKNOWN":
        raise CatalogError("v25 actual proof grants scientific qualification")
    fresh = proof.get("fresh_small_inputs")
    current_hashes = [item.get("sha256") for item in fresh if isinstance(item, dict) and item.get("path") == str(current_path)] if isinstance(fresh, list) else []
    if current_hashes != [sha256_file(current_path)]:
        raise CatalogError("v25 actual proof does not bind this CURRENT336")
    if proof.get("native_omission_count") != 1328 or proof.get("same_parent_role_conflicts") != []:
        raise CatalogError("v25 actual proof does not preserve the verified native/source component closure")
    return {
        "path": str(path), "sha256": sha256_file(path), "schema": proof.get("schema"),
        "status": proof.get("status"), "request": {"path": proof.get("request"), "sha256": proof.get("request_sha256")},
        "receipt": {"path": proof.get("receipt"), "sha256": proof.get("receipt_sha256")},
        "report": {"path": proof.get("report"), "sha256": proof.get("report_sha256")},
        "output_evidence_manifest": {"path": proof.get("output_evidence_manifest"), "sha256": proof.get("output_evidence_manifest_sha256")},
        "actual_launch_git": copy_json(proof.get("actual_launch_git") or {}),
        "parent_actual_prepost_content_hashes_equal": proof.get("parent_actual_prepost_content_hashes_equal"),
        "development_role_counts": copy_json(proof.get("development_role_counts") or {}),
        "native_omission_count": proof.get("native_omission_count"),
        "all336_development_exposed": proof.get("all336_development_exposed"),
        "hidden_test": proof.get("hidden_test"),
        "scientific_qualification": copy_json(proof.get("scientific_qualification") or {}),
        "qualification_credit": proof.get("qualification_credit"),
    }


def _validate_quality(manifest_path: Path, manifest: dict[str, Any], report_path: Path, report: dict[str, Any],
                      receipt_path: Path, receipt: dict[str, Any], current_path: Path,
                      by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    if report.get("schema") != QUALITY_SCHEMA or report.get("status") != "FAMILY_LABEL_QUALITY_V3_PASS_MASS_CENSOR_ARTIFACT_SOURCE_BOUND":
        raise CatalogError("quality report is not the completed v3 source-bound product")
    if report.get("manifest", {}).get("sha256") != sha256_file(manifest_path):
        raise CatalogError("quality report does not bind its supplied manifest")
    _receipt_summary(receipt_path, receipt, "quality", report_path)
    cases = report.get("cases")
    entries = manifest.get("entries")
    if not isinstance(cases, list) or len(cases) != 7 or not isinstance(entries, list) or len(entries) != 7:
        raise CatalogError("quality product must contain exactly seven cases and seven manifest entries")
    entry_by_key = {(entry.get("family_id"), entry.get("physical_case_id")): entry for entry in entries}
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        identity = case.get("normalized_identity")
        if not isinstance(identity, dict):
            raise CatalogError("quality case lacks normalized identity")
        family = identity.get("family_id"); physical = identity.get("physical_case_id"); key = (family, physical)
        if family not in FAMILIES or family in result or key not in by_key or key not in entry_by_key:
            raise CatalogError(f"quality case is not an exact CURRENT/manifest anchor: {key}")
        if by_key[key][0] != ANCHOR_INDICES[family]:
            raise CatalogError(f"quality case {family} is not the registered CURRENT anchor")
        source_role = case.get("source_role")
        if source_role not in {"native_initial_mk", "initial_spatial_region"}:
            raise CatalogError(f"quality case {family} has unsupported source role {source_role!r}")
        source = case.get("source") if isinstance(case.get("source"), dict) else {}
        report_value = source.get("report_path")
        if not isinstance(report_value, str) or not report_value:
            raise CatalogError(f"quality case {family} lacks its small label report path")
        case_report_path = require_file(report_value, f"quality case {family} label report")
        if source.get("report_sha256") != sha256_file(case_report_path):
            raise CatalogError(f"quality case {family} label report digest differs")
        checks = case.get("quality_checks")
        if not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
            raise CatalogError(f"quality case {family} has incomplete quality checks")
        result[family] = {
            "physical_case_id": physical, "source_role": source_role,
            "source_role_basis": case.get("source_role_basis"), "split": case.get("split"),
            "entry_key": case.get("entry_key"), "quality_checks": copy_json(checks),
            "censoring_scope": copy_json(case.get("censoring_scope") or {}),
            "mass_weighted_scope": copy_json(case.get("mass_weighted_scope") or {}),
            "read_policy": copy_json(case.get("read_policy") or {}),
            "report_path": str(case_report_path), "report_sha256": source.get("report_sha256"),
        }
    if sorted(result) != FAMILIES:
        raise CatalogError("quality product does not cover F1-F7 exactly")
    return result


def _validate_mechanism(report_path: Path, report: dict[str, Any], receipt_path: Path, receipt: dict[str, Any],
                        current_path: Path, by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]]) -> dict[tuple[str, str], dict[str, Any]]:
    if report.get("schema") != MECHANISM_SCHEMA or report.get("status") != "MECHANISM_PROBE_SOURCE_CLOSED_F2_S1_UPGRADED_NO_H5":
        raise CatalogError("mechanism v3 report is not the completed source-closed product")
    if report.get("current_identity", {}).get("sha256") != sha256_file(current_path):
        raise CatalogError("mechanism v3 report is bound to another CURRENT336")
    policy = report.get("read_policy")
    if not isinstance(policy, dict) or any(policy.get(key) is not False for key in ("h5_opened", "trajectory_content_opened", "raw_partout_opened", "solver_started")):
        raise CatalogError("mechanism v3 read policy does not close H5/BI4/solver scope")
    _receipt_summary(receipt_path, receipt, "mechanism v3", report_path)
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise CatalogError("mechanism v3 must contain exactly 118 cases")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for case in cases:
        family = case.get("family_id"); physical = case.get("physical_case_id"); key = (family, physical)
        if family not in MECHANISM_FAMILIES or key not in by_key or key in result:
            raise CatalogError(f"mechanism v3 case is not a unique CURRENT F2/F4/F6 case: {key}")
        native = case.get("native_gate") if isinstance(case.get("native_gate"), dict) else {}
        cause = native.get("cause") if isinstance(native.get("cause"), dict) else {}
        mass = case.get("mass_visibility") if isinstance(case.get("mass_visibility"), dict) else {}
        result[key] = {
            "case_key": case.get("case_key"), "family_id": family, "physical_case_id": physical,
            "native_gate": {
                "motive": native.get("motive"), "native_count": native.get("native_count"),
                "runparts_totals": copy_json(native.get("runparts_totals") or {}),
                "cause": copy_json(cause),
            },
            "first_missing_window_s": copy_json(case.get("first_missing_window_s")),
            "mass_visibility": copy_json(mass),
            "printed_final_bounds_observation": copy_json(case.get("printed_final_bounds_observation") or {}),
            "density_gate_observation": copy_json(case.get("density_gate_observation") or {}),
            "physical_fate": case.get("physical_fate"), "legal_outflow_or_spill": case.get("legal_outflow_or_spill"),
            "dynamical_impact": case.get("dynamical_impact"),
            "source_closure": copy_json(case.get("source_closure") or {}),
            "source_closure_claim_boundary": copy_json(case.get("source_closure_claim_boundary") or {}),
        }
    counts = {family: sum(key[0] == family for key in result) for family in sorted(MECHANISM_FAMILIES)}
    if counts != {"F2": 48, "F4": 22, "F6": 48}:
        raise CatalogError(f"mechanism v3 family coverage differs: {counts}")
    return result


def _validate_full_raw_proof(path: Path, proof: dict[str, Any], family: str) -> dict[str, Any]:
    if not str(proof.get("schema", "")).startswith(f"ds02.stage2.{family.lower()}-full"):
        raise CatalogError(f"{family} full raw proof schema does not identify {family}")
    if proof.get("status") != "PASS_ACTUAL_FULL_RAW_RECONSTRUCTION_BYTE_IDENTICAL_CURRENT_TYPED":
        raise CatalogError(f"{family} full raw proof is not a completed byte-identity proof")
    if proof.get("root_original_reference_h5_reread") is not False or proof.get("root_new_reconstructed_h5_byte_hash_read") is not False:
        raise CatalogError(f"{family} full raw proof reports an unapproved second root H5 read")
    qualification = proof.get("scientific_qualification") or {}
    if any(qualification.get(key) != "UNKNOWN" for key in ("QN", "QE", "QI")):
        raise CatalogError(f"{family} full raw proof grants qualification")
    return {
        "family_id": family, "path": str(path), "sha256": sha256_file(path),
        "schema": proof.get("schema"), "status": proof.get("status"),
        "request": {"path": proof.get("request"), "sha256": proof.get("request_sha256")},
        "receipt": {"path": proof.get("receipt"), "sha256": proof.get("receipt_sha256")},
        "report": {"path": proof.get("report"), "sha256": proof.get("report_sha256")},
        "native_frame_count": proof.get("native_frame_count"), "particles": proof.get("particles"),
        "actual_time_window_s": copy_json(proof.get("actual_time_window_s")),
        "all_typed_fields_and_entire_file_byte_identity_verified": proof.get("all_typed_fields_and_entire_file_byte_identity_verified"),
        "verification_scope": proof.get("verification_scope"),
        "scientific_qualification": copy_json(qualification),
        "root_original_reference_h5_reread": proof.get("root_original_reference_h5_reread"),
        "root_new_reconstructed_h5_byte_hash_read": proof.get("root_new_reconstructed_h5_byte_hash_read"),
        "goal_complete": proof.get("goal_complete"),
    }


def _compact_bindings(row: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for role, value in sorted((row.get("source_bindings") or {}).items()):
        if not isinstance(value, dict):
            continue
        path = value.get("path")
        declared = value.get("sha256") or value.get("recomputed_sha256")
        if not isinstance(path, str):
            continue
        suffix = Path(path).suffix.lower()
        result.append({
            "role": role, "path": None if suffix in FORBIDDEN_SUFFIXES else path,
            "forbidden_payload_path_omitted": suffix in FORBIDDEN_SUFFIXES,
            "declared_sha256": declared,
            "source_binding_status": "CURRENT_DECLARED_BINDING_ONLY",
        })
    return result


def _anchor_component(component_by_family: dict[str, dict[str, Any]], family: str) -> dict[str, Any] | None:
    return component_by_family.get(family)


def _window_signature(row: dict[str, Any]) -> str:
    return canonical_sha({
        "frames": row.get("frames"), "particles": row.get("particles"),
        "actual_time_window_s": row.get("actual_time_window_s"),
    })


def _case_record(index: int, row: dict[str, Any], component_by_family: dict[str, dict[str, Any]],
                 quality_by_family: dict[str, dict[str, Any]], mechanism_by_key: dict[tuple[str, str], dict[str, Any]],
                 full_raw_by_family: dict[str, dict[str, Any]]) -> dict[str, Any]:
    family = row["family_id"]; physical = row["physical_case_id"]; key = (family, physical)
    component = _anchor_component(component_by_family, family) if index == ANCHOR_INDICES.get(family) else None
    is_anchor = component is not None and component.get("members", [{}])[0].get("physical_case_id") == physical
    quality = quality_by_family.get(family) if is_anchor else None
    mechanism = mechanism_by_key.get(key)
    component_id = component.get("component_id") if is_anchor else f"current-unmerged-{family}-{index:03d}"
    condition_graph = component.get("condition_graph") if is_anchor else None
    if is_anchor:
        condition = {
            "status": "SOURCE_CLOSED_METADATA_ONLY_EXACT_ANCHOR",
            "component_id": component_id,
            "control_family_id": (condition_graph or {}).get("condition", {}).get("control_family_id"),
            "geometry_family_id": (condition_graph or {}).get("condition", {}).get("geometry_family_id"),
            "lineage_group_id": (condition_graph or {}).get("condition", {}).get("lineage_group_id"),
            "physical_condition_sha256": (condition_graph or {}).get("condition", {}).get("physical_condition_sha256"),
            "controls": copy_json((condition_graph or {}).get("condition", {}).get("controls") or {}),
            "geometry": copy_json((condition_graph or {}).get("condition", {}).get("geometry") or {}),
            "known_numeric_physical_parameters": copy_json(row.get("known_numeric_physical_parameters") or {}),
            "transfer_to_other_case": "UNKNOWN_UNPROVEN",
        }
    else:
        condition = {
            "status": "CURRENT_SOURCE_BINDINGS_ONLY_NO_EQUIVALENCE_CLAIM",
            "component_id": component_id,
            "control_family_id": "UNKNOWN_CURRENT_ONLY",
            "geometry_family_id": "UNKNOWN_CURRENT_ONLY",
            "lineage_group_id": "UNKNOWN_CURRENT_ONLY",
            "physical_condition_sha256": None,
            "controls": {}, "geometry": {},
            "known_numeric_physical_parameters": copy_json(row.get("known_numeric_physical_parameters") or {}),
            "transfer_to_other_case": "UNKNOWN_UNPROVEN",
        }
    if is_anchor:
        source_role = quality.get("source_role") if quality else "UNKNOWN"
        saved_scope = "ELIGIBLE_DEVELOPMENT_SAVED_FRAME_ARTIFACT_SOURCE_CLOSED"
        metadata_scope = "ELIGIBLE_DEVELOPMENT_OWNER_CONTROL_GEOMETRY_METADATA"
    elif mechanism:
        source_role = "native_initial_mk"
        saved_scope = "NOT_SELECTED_NO_COMPLETED_ANCHOR_LABEL_QUALITY_PRODUCT"
        metadata_scope = "ELIGIBLE_CURRENT_SOURCE_BINDING_METADATA"
    else:
        source_role = "UNKNOWN_SOURCE_ROLE"
        saved_scope = "NOT_AVAILABLE_NO_COMPLETED_LABEL_QUALITY_PRODUCT"
        metadata_scope = "ELIGIBLE_CURRENT_SOURCE_BINDING_METADATA"
    if mechanism:
        native_gate = mechanism["native_gate"]
        numerical_scope = {
            "status": "SOURCE_VISIBLE_NATIVE_NUMERICAL_GATE_ONLY",
            "motive": native_gate.get("motive"), "native_count": native_gate.get("native_count"),
            "runparts_totals": copy_json(native_gate.get("runparts_totals") or {}),
            "cause": copy_json(native_gate.get("cause") or {}),
            "first_missing_window_s": copy_json(mechanism.get("first_missing_window_s")),
            "event_time_semantics": "saved-record bracket/window only; exact continuous event time UNKNOWN",
            "physical_destination": "UNKNOWN",
            "legal_outflow_or_spill": mechanism.get("legal_outflow_or_spill") or "UNKNOWN_NOT_PROVEN",
        }
        mass_scope = {
            "status": "SOURCE_VISIBLE_MASS_LOWER_BOUND_ONLY",
            "visibility": copy_json(mechanism.get("mass_visibility") or {}),
            "unknown_width": "UNKNOWN",
            "dynamical_error": "UNKNOWN",
        }
    else:
        numerical_scope = {
            "status": "NOT_AUDITED_BY_ALL118_NATIVE_PRODUCT",
            "motive": "UNKNOWN", "native_count": "UNKNOWN",
            "first_missing_window_s": "UNKNOWN",
            "event_time_semantics": "not available from this catalog",
            "physical_destination": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
        }
        mass_scope = {
            "status": "NO_SOURCE_VISIBLE_MISSING_MASS_JOIN_IN_THIS_CATALOG",
            "visibility": "UNKNOWN", "unknown_width": "UNKNOWN", "dynamical_error": "UNKNOWN",
        }
    if quality:
        censoring = {
            "status": "SOURCE_CLOSED_SAVED_FRAME_QUALITY_PRODUCT",
            "first_passage": quality.get("censoring_scope", {}).get("first_passage", "UNKNOWN"),
            "hidden_continuous_events": quality.get("censoring_scope", {}).get("hidden_continuous_events", "UNKNOWN"),
            "hidden_recrossings": quality.get("censoring_scope", {}).get("hidden_recrossings", "UNKNOWN"),
            "residence": quality.get("censoring_scope", {}).get("residence", "UNKNOWN"),
            "numerical_loss_identity_censoring": quality.get("censoring_scope", {}).get("numerical_loss_identity_censoring", "UNKNOWN"),
            "quality_report_checks_closed": True,
        }
    else:
        censoring = {
            "status": "CURRENT_METADATA_ONLY",
            "first_passage": "UNKNOWN", "hidden_continuous_events": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN", "residence": "UNKNOWN",
            "numerical_loss_identity_censoring": "UNKNOWN",
        }
    full_raw = full_raw_by_family.get(family) if is_anchor else None
    return {
        "current_index": index, "family_id": family, "physical_case_id": physical,
        "runtime_case_alias": row.get("runtime_case_alias"),
        "identity": {"family_id": family, "physical_case_id": physical, "runtime_case_alias": row.get("runtime_case_alias")},
        "condition_group": condition,
        "window": {
            "frames": row.get("frames"), "particles": row.get("particles"),
            "actual_time_window_s": copy_json(row.get("actual_time_window_s")),
            "window_signature": _window_signature(row),
            "transfer_to_other_case": "UNKNOWN_UNPROVEN",
        },
        "source": {
            "source_role": source_role,
            "source_role_basis": quality.get("source_role_basis") if quality else ("native gate family role" if mechanism else "not closed"),
            "bindings": _compact_bindings(row),
            "conversion_report_declared_sha256": (row.get("conversion_report") or {}).get("recomputed_sha256"),
            "trajectory_content_opened_by_this_catalog": False,
        },
        "task_eligibility": {
            "owner_control_geometry_metadata": metadata_scope,
            "source_role_mass_ledger": "ELIGIBLE_SOURCE_ROLE_BOOKKEEPING_ONLY" if quality or mechanism else "UNKNOWN_SOURCE_ROLE",
            "saved_frame_artifact": saved_scope,
            "native_cause_alias_join": "ELIGIBLE_ALL118_NATIVE_METADATA_ONLY" if mechanism else "NOT_SELECTED",
            "material_region_event_transport": "EXCLUDED_UNSUPPORTED",
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
            "effective_split_safe": "UNKNOWN", "recovery_window_transfer": "UNKNOWN",
            "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "NONE",
        },
        "failure_or_censoring_scope": {
            "scientific_scan_status": row.get("scientific_scan_status"),
            "native_numerical_scope": numerical_scope,
            "censoring": censoring,
            "mass_scope": mass_scope,
            "unresolved_reasons": [
                "physical destination/fate is not identified by source-visible native omission",
                "continuous event time, hidden crossings, and residence beyond saved brackets are UNKNOWN",
                "dynamical/QN/QE/QI qualification is outside this metadata product",
            ],
        },
        "lineage": {
            "component_id": component_id,
            "same_parent_derivatives_stay_in_component": True,
            "cross_component_transfer": "DISALLOWED_UNLESS_EXACT_PHYSICAL_CONTROL_GEOMETRY_PARENT_RECOVERY_WINDOW_EQUALITY_IS_PROVEN",
            "v24_anchor": bool(is_anchor),
            "v24_component_source_closed": bool(is_anchor),
            "full_raw_reconstruction_proof": full_raw,
        },
    }


def build(current_path: Path | str, v25_path: Path | str, v25_manifest_path: Path | str, v25_actual_proof_path: Path | str,
          quality_manifest_path: Path | str, quality_report_path: Path | str, quality_receipt_path: Path | str,
          mechanism_report_path: Path | str, mechanism_receipt_path: Path | str,
          full_raw_proof_paths: dict[str, Path | str], manifest_output: Path | str,
          output: Path | str) -> dict[str, Any]:
    current_path, current = read_json(current_path, "CURRENT336")
    v25_path, v25 = read_json(v25_path, "v25 source-closed catalog")
    v25_manifest_path, v25_manifest = read_json(v25_manifest_path, "v25 evidence manifest")
    v25_actual_proof_path, v25_actual_proof = read_json(v25_actual_proof_path, "v25 actual verification proof")
    quality_manifest_path, quality_manifest = read_json(quality_manifest_path, "seven-family quality manifest")
    quality_report_path, quality_report = read_json(quality_report_path, "seven-family quality report")
    quality_receipt_path, quality_receipt = read_json(quality_receipt_path, "seven-family quality receipt")
    mechanism_report_path, mechanism_report = read_json(mechanism_report_path, "all-118 mechanism report")
    mechanism_receipt_path, mechanism_receipt = read_json(mechanism_receipt_path, "all-118 mechanism receipt")
    rows, by_key = _validate_current(current_path, current)
    component_by_family, v25_summary = _validate_v25(v25_path, v25, current_path, current)
    v25_actual_summary = _validate_v25_actual_proof(v25_actual_proof_path, v25_actual_proof, current_path)
    quality_by_family = _validate_quality(quality_manifest_path, quality_manifest, quality_report_path, quality_report,
                                          quality_receipt_path, quality_receipt, current_path, by_key)
    mechanism_by_key = _validate_mechanism(mechanism_report_path, mechanism_report, mechanism_receipt_path,
                                           mechanism_receipt, current_path, by_key)
    full_raw_by_family: dict[str, dict[str, Any]] = {}
    full_raw_refs: list[dict[str, Any]] = []
    for family, value in sorted(full_raw_proof_paths.items()):
        if family not in FAMILIES:
            raise CatalogError(f"unknown full raw proof family: {family}")
        path = require_file(value, f"{family} full raw proof")
        _proof_path, proof = read_json(path, f"{family} full raw proof")
        summary = _validate_full_raw_proof(path, proof, family)
        full_raw_by_family[family] = summary
        full_raw_refs.append(summary)
    case_records = [_case_record(index, row, component_by_family, quality_by_family, mechanism_by_key, full_raw_by_family)
                    for index, row in enumerate(rows)]
    keys = [(record["family_id"], record["physical_case_id"]) for record in case_records]
    if len(keys) != 336 or len(set(keys)) != 336:
        raise CatalogError("v26 case records are not an exact 336-case identity closure")
    if {record["current_index"] for record in case_records} != set(range(336)):
        raise CatalogError("v26 case records do not cover every CURRENT index exactly once")
    family_counts = {family: sum(record["family_id"] == family for record in case_records) for family in FAMILIES}
    native_counts = {family: sum(record["task_eligibility"]["native_cause_alias_join"].startswith("ELIGIBLE") and record["family_id"] == family for record in case_records) for family in FAMILIES}
    task_case_keys = {
        "owner_control_geometry_metadata": [record["identity"] for record in case_records],
        "saved_frame_artifact": [record["identity"] for record in case_records if record["task_eligibility"]["saved_frame_artifact"].startswith("ELIGIBLE")],
        "source_role_mass_ledger": [record["identity"] for record in case_records if record["task_eligibility"]["source_role_mass_ledger"].startswith("ELIGIBLE")],
        "native_cause_alias_join": [record["identity"] for record in case_records if record["task_eligibility"]["native_cause_alias_join"].startswith("ELIGIBLE")],
        "material_region_event_transport": [],
    }
    manifest_cases = [{
        "current_index": record["current_index"], "family_id": record["family_id"],
        "physical_case_id": record["physical_case_id"], "runtime_case_alias": record["runtime_case_alias"],
        "component_id": record["lineage"]["component_id"], "window_signature": record["window"]["window_signature"],
        "source_role": record["source"]["source_role"],
        "task_eligibility": copy_json(record["task_eligibility"]),
        "failure_or_censoring_scope": copy_json(record["failure_or_censoring_scope"]),
    } for record in case_records]
    source_refs = [
        _ref(current_path, "CURRENT336"), _ref(v25_path, "v25 catalog"), _ref(v25_manifest_path, "v25 evidence manifest"), _ref(v25_actual_proof_path, "v25 actual proof"),
        _ref(quality_manifest_path, "quality manifest"), _ref(quality_report_path, "quality report"), _ref(quality_receipt_path, "quality receipt"),
        _ref(mechanism_report_path, "mechanism v3 report"), _ref(mechanism_receipt_path, "mechanism v3 receipt"),
        *[_ref(Path(value["path"]), f"{value['family_id']} full raw proof") for value in full_raw_refs],
    ]
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "PREPARED_EXACT_CURRENT336_BOUNDED_TASK_SCOPE_NO_PHYSICAL_QUALIFICATION",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT), "git_commit": _git_commit()},
        "current336": {"path": str(current_path), "sha256": sha256_file(current_path), "schema": current.get("schema"), "case_count": 336},
        "v25": {"path": str(v25_path), "sha256": sha256_file(v25_path), "manifest": {"path": str(v25_manifest_path), "sha256": sha256_file(v25_manifest_path)}, "verification": v25_summary, "actual_verification_proof": v25_actual_summary},
        "quality": {"manifest": _ref(quality_manifest_path, "quality manifest"), "report": _ref(quality_report_path, "quality report"), "receipt": _ref(quality_receipt_path, "quality receipt"), "case_count": 7},
        "mechanism_v3": {"report": _ref(mechanism_report_path, "mechanism v3 report"), "receipt": _ref(mechanism_receipt_path, "mechanism v3 receipt"), "case_count": 118, "family_counts": {"F2": 48, "F4": 22, "F6": 48}, "alias_semantic_closure": "exact (family_id, physical_case_id) -> CURRENT index/runtime_case_alias; no particle observations copied"},
        "full_raw_reconstruction_proofs": full_raw_refs,
        "source_refs": source_refs,
        "case_count": 336, "family_counts": family_counts, "native_alias_counts": native_counts,
        "cases": manifest_cases,
        "read_policy": {
            "current_json_opened": True, "v25_json_opened": True, "quality_manifest_report_receipt_opened": True,
            "mechanism_report_receipt_opened": True, "full_raw_proof_json_opened": True,
            "materialized_label_h5_opened_by_this_worker": False, "original_trajectory_h5_opened_by_this_worker": False,
            "part_bi4_opened_by_this_worker": False, "raw_solver_output_opened_by_this_worker": False,
            "solver_started": False, "model_invoked": False,
            "upstream_quality_materialized_label_h5_read": "as declared by upstream quality product; not reopened here",
        },
    }
    manifest_output = Path(manifest_output).expanduser().resolve()
    if manifest_output.exists():
        raise CatalogError(f"refusing to overwrite v26 manifest: {manifest_output}")
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema": SCHEMA, "status": "PREPARED_EXACT_CURRENT336_BOUNDED_TASK_SCOPE_NO_PHYSICAL_QUALIFICATION",
        "producer": manifest["producer"],
        "inputs": {
            "manifest": {"path": str(manifest_output), "sha256": sha256_file(manifest_output)},
            "current336": {"path": str(current_path), "sha256": sha256_file(current_path)},
            "v25": {"path": str(v25_path), "sha256": sha256_file(v25_path)},
            "v25_actual_proof": {"path": str(v25_actual_proof_path), "sha256": sha256_file(v25_actual_proof_path)},
            "quality_report": {"path": str(quality_report_path), "sha256": sha256_file(quality_report_path)},
            "mechanism_v3_report": {"path": str(mechanism_report_path), "sha256": sha256_file(mechanism_report_path)},
            "full_raw_reconstruction_proofs": [{"family_id": ref["family_id"], "path": ref["path"], "sha256": ref["sha256"]} for ref in full_raw_refs],
        },
        "coverage": {
            "current_case_count": 336, "family_counts": family_counts, "case_indices_closed": True,
            "all118_native_alias_case_count": 118, "all118_family_counts": {"F2": 48, "F4": 22, "F6": 48},
            "seven_actual_anchor_count": 7, "full_raw_proof_family_count": len(full_raw_refs),
            "hidden_current_cases": 0,
        },
        "family_cards": {
            family: {
                "current_case_count": family_counts[family],
                "anchor_current_index": ANCHOR_INDICES[family],
                "anchor_physical_case_id": rows[ANCHOR_INDICES[family]]["physical_case_id"],
                "anchor_component_id": case_records[ANCHOR_INDICES[family]]["lineage"]["component_id"],
                "anchor_source_role": case_records[ANCHOR_INDICES[family]]["source"]["source_role"],
                "anchor_saved_frame_scope": case_records[ANCHOR_INDICES[family]]["task_eligibility"]["saved_frame_artifact"],
                "full_raw_reconstruction_proof": full_raw_by_family.get(family),
                "full_raw_reconstruction_proof_status": "ROOT_VERIFIED_SMALL_PROOF" if family in full_raw_by_family else "NOT_SUPPLIED_PENDING_ROOT_PROOF",
                "native_alias_case_count": native_counts[family],
                "scientific_status": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN", "recovery_safe": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN"},
            } for family in FAMILIES
        },
        "task_case_keys": task_case_keys,
        "failure_censoring_summary": {
            "all_cases_have_explicit_record": True,
            "native_numerical_gate_cases": 118,
            "not_audited_by_native_product": 218,
            "saved_frame_quality_anchor_cases": 7,
            "physical_destination_known": 0,
            "continuous_event_truth_known": 0,
            "dynamical_qualification_known": 0,
            "unknown_reasons": [
                "source-visible numerical exclusion is not physical spill/flux/fate",
                "saved-frame chord bracket is not continuous first arrival and does not close hidden recrossings",
                "mass lower bound is not a bounded velocity/impact/coupling error",
                "same family, source role, or saved-window label does not prove effective condition equivalence",
            ],
        },
        "cases": case_records,
        "scope_contract": {
            "eligible": ["exact current source-binding metadata", "seven source-closed saved-frame artifacts", "118 native motive/source-visible alias joins"],
            "excluded": ["physical destination/fate", "legal outflow or net flux", "continuous events", "dynamics/QN/QE/QI", "effective split safety", "recovery transfer"],
            "whole_initial_mass_gate": "screen only; no qualification credit and no per-MK denominator substitution",
            "same_parent_derivatives": "must remain inside exact component; no cross-source-role or cross-window transfer",
        },
        "read_policy": manifest["read_policy"],
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise CatalogError(f"refusing to overwrite v26 catalog: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _all_inputs(current_path: Path, v25_path: Path, v25_manifest_path: Path, v25_actual_proof_path: Path, quality_manifest_path: Path,
                quality_report_path: Path, quality_receipt_path: Path, mechanism_report_path: Path,
                mechanism_receipt_path: Path, full_raw_proof_paths: dict[str, Path], runtime_root: Path,
                worker_root: Path) -> list[Path]:
    paths = [SCRIPT, current_path, v25_path, v25_manifest_path, v25_actual_proof_path, quality_manifest_path, quality_report_path,
             quality_receipt_path, mechanism_report_path, mechanism_receipt_path, *full_raw_proof_paths.values()]
    paths.extend(runtime_root / "lagrangian-fluid-lab/scripts" / name for name in (
        "ds_data02_runtime_v8.py", "ds_data02_stage2_dispatch_v8.py", "ds_data02_strict_dispatch_v8.py"))
    paths.append(worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_bounded_development_catalog_v26.py")
    unique: list[Path] = []; seen: set[str] = set()
    for path in paths:
        path = Path(path).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise CatalogError(f"v26 request cannot bind forbidden payload: {path}")
        if not path.is_file():
            raise CatalogError(f"v26 request input is missing: {path}")
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    return unique


def make_request(current_path: Path | str, v25_path: Path | str, v25_manifest_path: Path | str, v25_actual_proof_path: Path | str,
                 quality_manifest_path: Path | str, quality_report_path: Path | str, quality_receipt_path: Path | str,
                 mechanism_report_path: Path | str, mechanism_receipt_path: Path | str,
                 full_raw_proof_paths: dict[str, Path | str], output: Path | str,
                 runtime_root: Path | str, worker_root: Path | str,
                 attempt_id: str = "current336-bounded-development-catalog-v26-forward-001") -> dict[str, Any]:
    current_path = require_file(current_path, "CURRENT336")
    v25_path = require_file(v25_path, "v25 catalog")
    v25_manifest_path = require_file(v25_manifest_path, "v25 manifest")
    v25_actual_proof_path = require_file(v25_actual_proof_path, "v25 actual proof")
    quality_manifest_path = require_file(quality_manifest_path, "quality manifest")
    quality_report_path = require_file(quality_report_path, "quality report")
    quality_receipt_path = require_file(quality_receipt_path, "quality receipt")
    mechanism_report_path = require_file(mechanism_report_path, "mechanism report")
    mechanism_receipt_path = require_file(mechanism_receipt_path, "mechanism receipt")
    proofs = {family: require_file(value, f"{family} full raw proof") for family, value in full_raw_proof_paths.items()}
    if not {"F4", "F5", "F6"}.issubset(proofs):
        raise CatalogError("v26 request requires the root-verified F4/F5/F6 full raw proof JSONs")
    runtime_root = Path(runtime_root).expanduser().resolve(); worker_root = Path(worker_root).expanduser().resolve()
    inputs = _all_inputs(current_path, v25_path, v25_manifest_path, v25_actual_proof_path, quality_manifest_path, quality_report_path,
                         quality_receipt_path, mechanism_report_path, mechanism_receipt_path, proofs,
                         runtime_root, worker_root)
    hashes = {str(path): sha256_file(path) for path in inputs}
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_bounded_development_catalog_v26.py"
    request = {
        "schema": "ds02.runner-request.v1", "request_schema": "ds02.stage2.bounded-development-catalog-v26-request.v1",
        "attempt_id": attempt_id, "case_id": "DS02_STAGE2_BOUNDED_DEVELOPMENT_CATALOG_V26", "family_id": "infra",
        "dataset_families": FAMILIES, "kind": "cpu", "cpu_task_kind": "metadata_audit", "cpu_threads": 1,
        "max_wall_seconds": 900, "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(worker_root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(worker_root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "build",
                     "--current", str(current_path), "--v25", str(v25_path), "--v25-manifest", str(v25_manifest_path), "--v25-actual-proof", str(v25_actual_proof_path),
                     "--quality-manifest", str(quality_manifest_path), "--quality-report", str(quality_report_path),
                     "--quality-receipt", str(quality_receipt_path), "--mechanism-report", str(mechanism_report_path),
                     "--mechanism-receipt", str(mechanism_receipt_path),
                     *sum((["--full-raw-proof", family, str(proofs[family])] for family in sorted(proofs)), []),
                     "--manifest-output", "{attempt_root}/current336-bounded-development-manifest-v26.json",
                     "--output", "{attempt_root}/current336-bounded-development-catalog-v26.json"],
        "input_files": [str(path) for path in inputs], "input_sha256": hashes,
        "launch_allowed": True, "primary_launch_owner": "root", "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {"small_json_receipt_proof_bytes_read": sum(path.stat().st_size for path in inputs),
                        "materialized_label_h5_bytes_read": 0, "original_trajectory_h5_bytes_read": 0,
                        "part_bi4_bytes_read": 0, "raw_solver_output_bytes_read": 0,
                        "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "continuous_events": "UNKNOWN",
                            "effective_split_safe": "UNKNOWN", "recovery_safe": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "none"},
        "coverage_contract": {"exact_current_case_count": 336, "hidden_current_cases": 0, "native_alias_cases": 118, "seven_anchor_cards": 7},
        "upstream_quality_h5": "quality producer's prior materialized-label H5 read is represented only by report/receipt; this worker does not reopen it",
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise CatalogError(f"refusing to overwrite v26 request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "make-request"):
        p = sub.add_parser(name)
        for arg in ("current", "v25", "v25-manifest", "v25-actual-proof", "quality-manifest", "quality-report", "quality-receipt", "mechanism-report", "mechanism-receipt"):
            p.add_argument(f"--{arg}", type=Path, required=True)
        p.add_argument("--full-raw-proof", nargs=2, action="append", metavar=("FAMILY", "PATH"), required=True)
        p.add_argument("--output", type=Path, required=True)
        if name == "build":
            p.add_argument("--manifest-output", type=Path, required=True)
        else:
            p.add_argument("--runtime-root", type=Path, required=True); p.add_argument("--worker-root", type=Path, required=True)
            p.add_argument("--attempt-id", default="current336-bounded-development-catalog-v26-forward-001")
    args = parser.parse_args(argv)
    proofs = {family: path for family, path in args.full_raw_proof}
    if not {"F4", "F5", "F6"}.issubset(proofs):
        parser.error("--full-raw-proof must include F4, F5, and F6")
    if args.command == "build":
        build(args.current, args.v25, args.v25_manifest, args.v25_actual_proof, args.quality_manifest, args.quality_report, args.quality_receipt,
              args.mechanism_report, args.mechanism_receipt, proofs, args.manifest_output, args.output)
    else:
        make_request(args.current, args.v25, args.v25_manifest, args.v25_actual_proof, args.quality_manifest, args.quality_report, args.quality_receipt,
                     args.mechanism_report, args.mechanism_receipt, proofs, args.output, args.runtime_root, args.worker_root, args.attempt_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
