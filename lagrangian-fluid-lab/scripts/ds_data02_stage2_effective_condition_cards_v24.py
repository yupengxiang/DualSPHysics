#!/usr/bin/env python3
"""Build conservative effective-condition cards for the seven actual anchors.

The cards bind each completed label product to the exact CURRENT row and to
the small owner, generated-XML, GenCase receipt, solver receipt, and
conversion-report evidence that describes its physical/control recipe.  The
builder deliberately keeps the seven anchors in separate components: a
shared family name, source role, or saved-frame schema is not evidence that
the physical geometry, control, recovery lineage, or time window is
equivalent.  It therefore grants only source-role, mass-ledger, and
saved-frame development-audit roles.  Physical fate, dynamics, continuous
events, recovery transfer, and split safety remain unknown.

This program reads JSON/XML and hashes only the explicitly bound small
evidence files.  It never opens a trajectory H5, BI4, solver output, or
materialized label H5.  It is a metadata preparation worker; a shared runner
request is provided separately and is never launched by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.effective-condition-cards.v24"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
QUALITY_SCHEMA = "ds02.stage2.family-label-quality.v3"
FAMILIES = [f"F{i}" for i in range(1, 8)]
ANCHOR_INDICES = {"F1": 0, "F2": 78, "F3": 96, "F4": 144, "F5": 192, "F6": 240, "F7": 288}
SMALL_SUFFIXES = {".json", ".xml", ".xmf", ".cfg", ".txt", ".csv", ".out", ".py"}
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}


class CardError(RuntimeError):
    """Raised when a source-bound card cannot be built safely."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Any, label: str) -> Path:
    if isinstance(value, Path):
        path = value.expanduser().resolve()
    elif isinstance(value, str) and value:
        path = Path(value).expanduser().resolve()
    else:
        raise CardError(f"{label} must be a non-empty path")
    if not path.is_file():
        raise CardError(f"{label} is missing: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise CardError(f"{label} is a forbidden scientific payload: {path}")
    return path


def read_json(path: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CardError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise CardError(f"{label} must be an object: {path}")
    return path, value


def _copy_json(value: Any) -> Any:
    """Return JSON-safe data without retaining mutable input objects."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def _first(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    return None


def _owner_condition(owner: dict[str, Any]) -> dict[str, Any]:
    physical = owner.get("physical_binding")
    if not isinstance(physical, dict):
        physical = {}
    claims = owner.get("claims") if isinstance(owner.get("claims"), dict) else {}
    source = owner.get("source") if isinstance(owner.get("source"), dict) else {}
    condition_hash = _first(owner, "physical_condition_sha256", "physical_binding_sha256", "source_plan_condition_sha256")
    return {
        "physical_condition_sha256": condition_hash,
        "condition_hash_kind": (
            "producer_declared_physical_condition"
            if owner.get("physical_condition_sha256")
            else "producer_declared_binding_or_source_plan_condition"
            if condition_hash
            else "UNAVAILABLE"
        ),
        "geometry_family_id": _first(owner, "geometry_family_id") or physical.get("geometry_family_id"),
        "control_family_id": _first(owner, "control_family_id") or physical.get("control_family_id"),
        "lineage_group_id": _first(owner, "lineage_group_id") or physical.get("lineage_group_id"),
        "mechanism_id": _first(owner, "mechanism_id") or physical.get("mechanism_id"),
        "resolution": owner.get("resolution"),
        "owner_status": _first(owner, "status", "owner_status"),
        "q_n": _first(owner, "q_n") or claims.get("q_n") or owner.get("q_n_status"),
        "q_i": _first(owner, "q_i_status"),
        "q_e": _first(owner, "q_e_status"),
        "claim_boundary": _first(owner, "claim_boundary"),
        "controls": _copy_json(_first(physical, "controls") or _first(owner, "solver_parameters") or {}),
        "geometry": _copy_json(physical.get("geometry") or {}),
        "parameters": _copy_json(physical.get("parameters") or {}),
        "initial_state": _copy_json(physical.get("initial_state") or {}),
        "event_window": _copy_json(physical.get("event_window") or {}),
        "mass_policy": _first(physical, "mass_policy") or owner.get("mass_policy"),
        "owner_source": _copy_json(source),
        "scope_flags": {
            "scientific_payloads_read_or_hashed_by_owner_builder": owner.get(
                "scientific_payloads_read_or_hashed_by_owner_builder"
            ),
            "source_payloads_read_or_hashed_by_builder": owner.get(
                "source_payloads_read_or_hashed_by_builder"
            ),
            "source_h5_scope_status": owner.get("source_h5_scope_status"),
            "precision_status": owner.get("precision_status"),
            "launch_allowed": owner.get("launch_allowed"),
        },
    }


def _xml_summary(path: Path) -> dict[str, Any]:
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError) as error:
        raise CardError(f"generated XML is invalid: {path}") from error
    wanted = {
        "gravity", "rhop0", "definition", "mkconfig", "particles", "parameter",
        "posmin", "posmax", "pointmin", "pointmax", "simulationdomain", "fixed", "fluid",
    }
    selected: list[dict[str, Any]] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in wanted:
            selected.append({"tag": tag, "attributes": dict(sorted(element.attrib.items()))})
    return {
        "root_tag": root.tag.rsplit("}", 1)[-1],
        "application": root.attrib.get("app"),
        "generated_at": root.attrib.get("date"),
        "selected_elements": selected,
    }


def _small_binding(path: Path, declared_sha256: str | None, role: str) -> dict[str, Any]:
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise CardError(f"small binding unexpectedly points to scientific payload: {path}")
    observed = sha256_file(path)
    return {
        "role": role,
        "path": str(path),
        "bytes": path.stat().st_size,
        "declared_sha256": declared_sha256,
        "observed_sha256": observed,
        "sha256_matches_declared": declared_sha256 in (None, observed),
    }


def _receipt_summary(path: Path, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, receipt = read_json(path, f"{role} receipt")
    status = receipt.get("status")
    if status != "completed" or receipt.get("returncode") not in (None, 0):
        raise CardError(f"{role} receipt is not a successful completed receipt: {path}")
    request = receipt.get("request") if isinstance(receipt.get("request"), dict) else {}
    input_hashes = receipt.get("input_hashes_at_launch")
    if not isinstance(input_hashes, dict):
        input_hashes = {}
    # Keep declared hashes for small source/config files, but never require or
    # open a BI4/H5/trajectory payload while producing this card.
    small_inputs = []
    for input_path, digest in sorted(input_hashes.items()):
        suffix = Path(str(input_path)).suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES:
            continue
        if suffix in SMALL_SUFFIXES or Path(str(input_path)).name in {"Run.out", "DsphConfig.xml"}:
            small_inputs.append({"path": str(input_path), "sha256": digest})
    summary = {
        "role": role,
        "path": str(path),
        "sha256": sha256_file(path),
        "status": status,
        "returncode": receipt.get("returncode"),
        "termination_reason": receipt.get("termination_reason"),
        "output_root": receipt.get("output_root"),
        "request_sha256": receipt.get("request_sha256"),
        "request": {
            key: _copy_json(request[key])
            for key in (
                "schema", "family_id", "case_id", "attempt_id", "kind", "cpu_threads",
                "max_wall_seconds", "estimated_storage_bytes", "gencase_prefix", "gencase_receipt",
                "solver_receipt", "tmax", "tout",
            )
            if key in request
        },
        "command": _copy_json(receipt.get("command") or []),
        "git_at_launch": _copy_json(receipt.get("git_at_launch") or {}),
        "runner_sha256": receipt.get("runner_sha256"),
        "binary_sha256": receipt.get("binary_sha256"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "gpu_seconds": receipt.get("gpu_seconds"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "fluid_particles": receipt.get("fluid_particles"),
        "total_particles": receipt.get("total_particles"),
        "small_input_hashes_at_launch": small_inputs,
        "scientific_payload_hashes_not_opened": [
            {"path": str(input_path), "sha256": digest}
            for input_path, digest in sorted(input_hashes.items())
            if Path(str(input_path)).suffix.lower() in FORBIDDEN_SUFFIXES
        ],
    }
    return summary, receipt


def _conversion_summary(path: Path) -> dict[str, Any]:
    _, report = read_json(path, "conversion report")
    source = report.get("source_provenance") if isinstance(report.get("source_provenance"), dict) else {}
    output_hdf5 = report.get("output_hdf5")
    if isinstance(output_hdf5, dict):
        output_binding = {
            "path": output_hdf5.get("path"),
            "declared_sha256": output_hdf5.get("sha256") or output_hdf5.get("output_sha256"),
            "read_by_v24": False,
        }
    else:
        output_binding = {"path": output_hdf5, "declared_sha256": report.get("output_sha256"), "read_by_v24": False}
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "schema": report.get("schema"),
        "conversion_status": report.get("conversion_status"),
        "frames": report.get("frames"),
        "particles": report.get("particles"),
        "solver_dimension": report.get("solver_dimension"),
        "coordinate_frame": report.get("coordinate_frame"),
        "identity_key": _copy_json(report.get("typed_identity") or report.get("identity_key")),
        "output_hdf5": output_binding,
        "q_i_status": report.get("q_i_status"),
        "q_n_status": report.get("q_n_status"),
        "production_eligibility": report.get("production_eligibility"),
        "source_provenance_keys": sorted(source),
        "source_provenance": {
            key: _copy_json(source[key])
            for key in ("data_root", "raw_solver_output", "solver_output", "source_h5", "input_h5", "current_case_id")
            if key in source
        },
    }


def _receipt_input_alignment(receipt: dict[str, Any], binding_paths: Iterable[Path]) -> dict[str, Any]:
    hashes = receipt.get("input_hashes_at_launch")
    if not isinstance(hashes, dict):
        return {"all_bound_paths_present": False, "paths": []}
    rows = []
    for path in binding_paths:
        digest = hashes.get(str(path))
        rows.append({"path": str(path), "present_in_receipt": digest is not None, "declared_sha256": digest})
    return {"all_bound_paths_present": all(row["present_in_receipt"] for row in rows), "paths": rows}


def _semantic_gaps(family: str, owner: dict[str, Any], quality_case: dict[str, Any]) -> list[dict[str, str]]:
    gaps = [
        {"field": "continuous_first_arrival", "status": "UNKNOWN", "reason": "quality product only brackets first observed saved-frame chord crossings"},
        {"field": "hidden_recrossings", "status": "UNKNOWN", "reason": "saved-frame labels cannot exclude crossings between saved records"},
        {"field": "physical_fate", "status": "UNKNOWN", "reason": "numerical invalidation or unclassified destination is not a proof of physical spill/flux"},
        {"field": "dynamical_impact", "status": "UNKNOWN", "reason": "mass visibility is not a bound on velocity, force, coupling, or impact error"},
        {"field": "recovery_equivalence", "status": "UNKNOWN", "reason": "completed receipt and label product do not prove transfer across a recovery/window lineage"},
        {"field": "cross_anchor_equivalence", "status": "UNKNOWN", "reason": "no exact geometry/control/source/window equality proof was supplied for another anchor"},
        {"field": "effective_split_safety", "status": "UNKNOWN", "reason": "producer split labels are metadata partitions; they are not a physical/control equivalence proof"},
    ]
    if family == "F2":
        gaps.append({"field": "recovery_source", "status": "UNKNOWN", "reason": "F2 owner records future conversion scope and the recovery report is a separate saved-label product"})
    if family == "F5" and owner.get("source_h5_scope_status"):
        gaps.append({"field": "owner_source_scope", "status": "UNKNOWN", "reason": str(owner["source_h5_scope_status"])})
    if family == "F6" and owner.get("status") == "prospective_source_only":
        gaps.append({"field": "owner_source_status", "status": "UNKNOWN", "reason": "owner metadata is prospective/source-only even though the actual label product is source-bound"})
    return gaps


def _validate_quality(current: dict[str, Any], quality: dict[str, Any], quality_manifest: Path) -> dict[str, dict[str, Any]]:
    if quality.get("schema") != QUALITY_SCHEMA:
        raise CardError("quality report schema is not v3")
    if quality.get("status") != "FAMILY_LABEL_QUALITY_V3_PASS_MASS_CENSOR_ARTIFACT_SOURCE_BOUND":
        raise CardError("quality report is not the completed source-bound seven-anchor product")
    if quality.get("manifest", {}).get("sha256") != sha256_file(quality_manifest):
        raise CardError("quality report is not bound to the supplied quality manifest")
    cases = quality.get("cases")
    if not isinstance(cases, list) or len(cases) != 7:
        raise CardError("quality report must contain exactly seven cases")
    current_by_key = {(row.get("family_id"), row.get("physical_case_id")): row for row in current.get("cases", [])}
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        identity = case.get("normalized_identity")
        if not isinstance(identity, dict):
            raise CardError("quality case lacks normalized identity")
        family = identity.get("family_id")
        key = (family, identity.get("physical_case_id"))
        if family not in FAMILIES or key not in current_by_key or family in result:
            raise CardError(f"quality identity is not an exact CURRENT anchor: {key}")
        if case.get("mass_weighted_scope", {}).get("qualification_credit") != "none":
            raise CardError(f"quality case grants qualification credit: {family}")
        if case.get("censoring_scope", {}).get("first_passage") != "first observed saved-frame chord bracket only":
            raise CardError(f"quality case first-passage scope changed: {family}")
        if any(value is not True for value in (case.get("quality_checks") or {}).values()):
            raise CardError(f"quality checks are not all closed: {family}")
        source = case.get("source")
        if not isinstance(source, dict):
            raise CardError(f"quality source is missing: {family}")
        report_path = require_file(source.get("report_path"), f"{family} label report")
        if source.get("report_sha256") != sha256_file(report_path):
            raise CardError(f"{family} label report hash mismatch")
        current_row = current_by_key[key]
        if source.get("trajectory_sha256") != current_row.get("trajectory", {}).get("producer_declared_sha256"):
            raise CardError(f"{family} quality trajectory digest differs from CURRENT producer digest")
        result[family] = case
    if sorted(result) != FAMILIES:
        raise CardError("quality report does not cover F1-F7 exactly")
    return result


def build_cards(current_path: Path | str, quality_manifest_path: Path | str,
                quality_report_path: Path | str, quality_receipt_path: Path | str,
                output: Path | str) -> dict[str, Any]:
    current_path, current = read_json(current_path, "CURRENT336")
    quality_manifest_path, quality_manifest = read_json(quality_manifest_path, "quality manifest")
    quality_report_path, quality_report = read_json(quality_report_path, "quality report")
    quality_receipt_path = require_file(quality_receipt_path, "quality execution receipt")
    if current.get("schema") != CURRENT_SCHEMA:
        raise CardError("CURRENT336 schema is not the expected v1 source")
    quality_by_family = _validate_quality(current, quality_report, quality_manifest_path)
    current_cases = current.get("cases")
    if not isinstance(current_cases, list):
        raise CardError("CURRENT336 cases is not a list")
    current_by_family: dict[str, tuple[int, dict[str, Any]]] = {}
    for family, index in ANCHOR_INDICES.items():
        if index >= len(current_cases) or not isinstance(current_cases[index], dict):
            raise CardError(f"CURRENT336 lacks registered {family} anchor index {index}")
        row = current_cases[index]
        if row.get("family_id") != family:
            raise CardError(f"CURRENT336 anchor index {index} is not {family}")
        current_by_family[family] = (index, row)

    cards = []
    components = []
    for family in FAMILIES:
        index, row = current_by_family[family]
        if index != ANCHOR_INDICES[family]:
            raise CardError(f"{family} CURRENT index changed from the registered anchor")
        identity = row.get("physical_case_id")
        quality_case = quality_by_family[family]
        bindings = row.get("source_bindings")
        if not isinstance(bindings, dict):
            raise CardError(f"{family} source_bindings is missing")
        evidence: dict[str, Any] = {}
        evidence_paths: list[Path] = []
        for role in ("owner_metadata", "generated_xml", "gencase_receipt", "solver_receipt"):
            binding = bindings.get(role)
            if not isinstance(binding, dict):
                raise CardError(f"{family} binding is missing: {role}")
            path = require_file(binding.get("path"), f"{family} {role}")
            evidence_paths.append(path)
            if role == "generated_xml":
                evidence[role] = _small_binding(path, binding.get("sha256"), role)
                evidence[role]["semantic_summary"] = _xml_summary(path)
            elif role == "owner_metadata":
                evidence[role] = _small_binding(path, binding.get("sha256"), role)
                _, owner = read_json(path, f"{family} owner metadata")
                evidence[role]["semantic_summary"] = _owner_condition(owner)
            else:
                summary, receipt = _receipt_summary(path, role)
                evidence[role] = summary
                if role == "solver_receipt":
                    solver_receipt = receipt
        conversion_path = require_file(row.get("conversion_report", {}).get("path"), f"{family} conversion report")
        evidence_paths.append(conversion_path)
        evidence["conversion_report"] = _conversion_summary(conversion_path)
        _, owner = read_json(bindings["owner_metadata"]["path"], f"{family} owner metadata")
        owner_condition = evidence["owner_metadata"]["semantic_summary"]
        # The solver receipt is expected to bind the prepared XML and the
        # successful GenCase receipt.  The owner JSON and the solver receipt
        # itself are evidence for this card, but are not solver input files;
        # requiring them in the solver's input-hash map would report a false
        # source mismatch.
        receipt_alignment = _receipt_input_alignment(
            solver_receipt,
            [Path(bindings["generated_xml"]["path"]), Path(bindings["gencase_receipt"]["path"])],
        )
        label_source = quality_case["source"]
        label_report = require_file(label_source["report_path"], f"{family} label report")
        # Only the report is read/hashed here.  The materialized label H5
        # digest is copied from the completed quality product and is not opened.
        label_binding = {
            "quality_entry_key": quality_case.get("entry_key"),
            "source_role": quality_case.get("source_role"),
            "source_role_basis": quality_case.get("source_role_basis"),
            "producer_split": quality_case.get("split"),
            "upstream_quality_product_materialized_label_h5_opened": quality_report.get("read_policy", {}).get(
                "materialized_label_h5_opened"
            ),
            "label_report": {"path": str(label_report), "sha256": sha256_file(label_report)},
            "labels_h5": {
                "path": label_source.get("labels_h5"),
                "producer_declared_sha256": label_source.get("labels_h5_sha256"),
                "read_by_v24": False,
            },
            "trajectory_h5": {
                "path": row.get("trajectory", {}).get("path"),
                "producer_declared_sha256": row.get("trajectory", {}).get("producer_declared_sha256"),
                "read_by_v24": False,
            },
            "mass_scope": {
                "whole_initial_denominator_kg": quality_case.get("mass_weighted_scope", {}).get("whole_initial_denominator_kg"),
                "unknown_final_mass_kg": quality_case.get("mass_weighted_scope", {}).get("unknown_final_mass_kg"),
                "unknown_final_fraction": quality_case.get("mass_weighted_scope", {}).get("unknown_final_fraction"),
                "screen_gate_fraction": quality_case.get("mass_weighted_scope", {}).get("screen_gate_fraction"),
                "screen_max_fraction_passes": quality_case.get("mass_weighted_scope", {}).get("screen_max_fraction_passes"),
            },
            "saved_frame_scope": {
                "first_passage": quality_case.get("censoring_scope", {}).get("first_passage"),
                "residence": quality_case.get("censoring_scope", {}).get("residence"),
                "hidden_continuous_events": quality_case.get("censoring_scope", {}).get("hidden_continuous_events"),
                "hidden_recrossings": quality_case.get("censoring_scope", {}).get("hidden_recrossings"),
            },
        }
        condition_key = {
            "owner_physical_condition_sha256": owner_condition.get("physical_condition_sha256"),
            "geometry_family_id": owner_condition.get("geometry_family_id"),
            "control_family_id": owner_condition.get("control_family_id"),
            "lineage_group_id": owner_condition.get("lineage_group_id"),
            "generated_xml_sha256": evidence["generated_xml"]["observed_sha256"],
            "gencase_receipt_sha256": evidence["gencase_receipt"]["sha256"],
            "solver_receipt_sha256": evidence["solver_receipt"]["sha256"],
            "actual_time_window_s": _copy_json(row.get("actual_time_window_s")),
            "frames": row.get("frames"),
        }
        component_id = f"v24-anchor-{family}"
        component = {
            "component_id": component_id,
            "members": [family],
            "membership_basis": "one exact CURRENT anchor; no cross-anchor merge",
            "condition_key": condition_key,
            "merge_status": "NO_CROSS_ANCHOR_MERGE",
            "merge_rule": "A merge requires equal physical condition, geometry/control template, native parent, recovery lineage, and saved window evidence; common label schema or source role is insufficient.",
            "development_role": "SOURCE_ANCHORED_ARTIFACT_AND_SAVED_FRAME_DIAGNOSTICS_ONLY",
            "scientific_qualification": "UNKNOWN",
            "split_safe": "UNKNOWN",
            "recovery_safe": "UNKNOWN",
        }
        components.append(component)
        cards.append({
            "family_id": family,
            "physical_case_id": identity,
            "current_index": index,
            "runtime_case_alias": row.get("runtime_case_alias"),
            "component_id": component_id,
            "current_binding": {
                "path": str(current_path),
                "sha256": sha256_file(current_path),
                "schema": current.get("schema"),
                "family_id": row.get("family_id"),
                "physical_case_id": row.get("physical_case_id"),
                "runtime_case_alias": row.get("runtime_case_alias"),
                "frames": row.get("frames"),
                "particles": row.get("particles"),
                "actual_time_window_s": _copy_json(row.get("actual_time_window_s")),
                "known_numeric_physical_parameters": _copy_json(row.get("known_numeric_physical_parameters") or {}),
                "trajectory_declared_sha256": row.get("trajectory", {}).get("producer_declared_sha256"),
                "trajectory_read_by_v24": False,
            },
            "condition_evidence": {
                "owner": owner_condition,
                "generated_xml": evidence["generated_xml"],
                "gencase_receipt": evidence["gencase_receipt"],
                "solver_receipt": evidence["solver_receipt"],
                "conversion_report": evidence["conversion_report"],
                "solver_receipt_binding": receipt_alignment,
            },
            "label_product_binding": label_binding,
            "task_eligibility": {
                "native_source_role_and_mass_ledger": "ELIGIBLE_DEVELOPMENT_AUDIT",
                "saved_frame_chord_censoring": "ELIGIBLE_LIMITED_DEVELOPMENT",
                "artifact_and_native_frame_diagnostics": "ELIGIBLE_DEVELOPMENT_AUDIT",
                "physical_fate_or_legal_flux": "UNKNOWN",
                "dynamical_impact": "UNKNOWN",
                "continuous_first_arrival": "UNKNOWN",
                "hidden_recrossings": "UNKNOWN",
                "recovery_window_transfer": "UNKNOWN",
                "effective_split_safety": "UNKNOWN",
                "QI": "UNKNOWN",
                "QN": "UNKNOWN",
                "QE": "UNKNOWN",
                "qualification_credit": "NONE",
            },
            "semantic_gaps": _semantic_gaps(family, owner, quality_case),
            "read_policy": {
                "current_json_opened": True,
                "quality_manifest_json_opened": True,
                "quality_report_json_opened": True,
                "small_owner_xml_receipts_conversion_opened": True,
                "label_report_json_opened": True,
                "materialized_label_h5_opened": False,
                "original_trajectory_h5_opened": False,
                "part_bi4_opened": False,
                "raw_solver_output_opened": False,
                "solver_started": False,
                "model_invoked": False,
            },
        })

    source_roles = {role: sum(card["label_product_binding"]["source_role"] == role for card in cards)
                    for role in ("native_initial_mk", "initial_spatial_region")}
    result = {
        "schema": SCHEMA,
        "status": "PREPARED_SOURCE_BOUND_EFFECTIVE_COMPONENTS_NO_PHYSICAL_QUALIFICATION",
        "producer": {
            "script_path": str(SCRIPT),
            "script_sha256": sha256_file(SCRIPT),
            "git_commit": _git_commit(),
        },
        "inputs": {
            "current336": {"path": str(current_path), "sha256": sha256_file(current_path)},
            "quality_manifest": {"path": str(quality_manifest_path), "sha256": sha256_file(quality_manifest_path)},
            "quality_report": {"path": str(quality_report_path), "sha256": sha256_file(quality_report_path)},
            "quality_execution_receipt": {"path": str(quality_receipt_path), "sha256": sha256_file(quality_receipt_path)},
        },
        "anchor_count": len(cards),
        "component_count": len(components),
        "source_role_counts": source_roles,
        "components": components,
        "cards": cards,
        "grouping_contract": {
            "component_unit": "exact CURRENT physical anchor",
            "cross_anchor_merge": "NOT_PROVEN_AND_DISALLOWED",
            "same_template_parent_recovery_window": "must all be exact before future merge; no current cross-anchor merge satisfies all fields",
            "development_subset": "seven anchors are usable only for source-role, mass-ledger, and saved-frame artifact diagnostics",
            "physical_task_qualification": "UNKNOWN",
            "effective_split_safe": "UNKNOWN",
            "recovery_safe": "UNKNOWN",
            "QN_QE_QI": "UNKNOWN_OR_NONE; this artifact grants no qualification credit",
        },
        "read_policy": {
            "current_json_opened": True,
            "quality_manifest_json_opened": True,
            "quality_report_json_opened": True,
            "quality_execution_receipt_json_opened": True,
            "owner_json_opened": True,
            "generated_xml_opened": True,
            "gencase_and_solver_receipts_opened": True,
            "conversion_reports_opened": True,
            "label_report_json_opened": True,
            "materialized_label_h5_opened": False,
            "original_trajectory_h5_opened": False,
            "part_bi4_opened": False,
            "raw_solver_output_opened": False,
            "solver_started": False,
            "model_invoked": False,
        },
        "upstream_quality_product_read_policy": _copy_json(quality_report.get("read_policy") or {}),
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise CardError(f"refusing to overwrite v24 card output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPT.parents[2], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def make_request(current_path: Path | str, quality_manifest_path: Path | str,
                 quality_report_path: Path | str, quality_receipt_path: Path | str,
                 output: Path | str, runtime_root: Path | str,
                 worker_root: Path | str) -> dict[str, Any]:
    """Prepare (but do not launch) the bounded v8 CPU metadata request."""
    paths = [
        require_file(current_path, "CURRENT336"),
        require_file(quality_manifest_path, "quality manifest"),
        require_file(quality_report_path, "quality report"),
        require_file(quality_receipt_path, "quality receipt"),
        SCRIPT,
    ]
    _, current = read_json(paths[0], "CURRENT336")
    _, quality = read_json(paths[2], "quality report")
    for family in FAMILIES:
        row = next((row for row in current.get("cases", []) if row.get("family_id") == family), None)
        case = next((case for case in quality.get("cases", []) if case.get("family_id") == family), None)
        if row is None or case is None:
            raise CardError(f"cannot build v24 request for {family}")
        for role in ("owner_metadata", "generated_xml", "gencase_receipt", "solver_receipt"):
            paths.append(require_file(row["source_bindings"][role]["path"], f"{family} {role}"))
        paths.append(require_file(row["conversion_report"]["path"], f"{family} conversion report"))
        paths.append(require_file(case["source"]["report_path"], f"{family} label report"))
    runtime_root = Path(runtime_root).expanduser().resolve()
    worker_root = Path(worker_root).expanduser().resolve()
    runtime_files = [
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
    ]
    paths.extend(require_file(path, "v8 runtime source") for path in runtime_files)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) not in seen:
            unique.append(path)
            seen.add(str(path))
    input_hashes = {str(path): sha256_file(path) for path in unique}
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise CardError(f"refusing to overwrite v24 request: {output}")
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": "ds02.stage2.effective-condition-cards-v24-request.v1",
        "attempt_id": "seven-effective-condition-cards-v24-forward-001",
        "case_id": "DS02_STAGE2_EFFECTIVE_CONDITION_CARDS_V24",
        "family_id": "infra",
        "dataset_families": FAMILIES,
        "kind": "cpu",
        "cpu_task_kind": "metadata_audit",
        "cpu_threads": 1,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 32 * 1024 * 1024,
        "cwd": str(worker_root / "lagrangian-fluid-lab/scripts"),
        "worktree_root": str(runtime_root),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(SCRIPT), "build", "--current", str(paths[0]),
            "--quality-manifest", str(paths[1]), "--quality-report", str(paths[2]),
            "--quality-receipt", str(paths[3]),
            "--output", "{attempt_root}/seven-effective-condition-cards-v24.json",
        ],
        "input_files": [str(path) for path in unique],
        "input_sha256": input_hashes,
        "launch_allowed": True,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {
            "small_json_xml_receipt_bytes_read": sum(path.stat().st_size for path in unique),
            "materialized_label_h5_bytes_read": 0,
            "original_trajectory_h5_bytes_read": 0,
            "part_bi4_bytes_read": 0,
            "raw_solver_output_bytes_read": 0,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
        "claim_boundary": {
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "continuous_first_arrival": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
            "recovery_safe": "UNKNOWN",
            "split_safe": "UNKNOWN",
            "qualification_credit": "none",
        },
        "no_cross_anchor_merge": True,
        "old_consumed_artifacts_modified": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "make-request"):
        subparser = sub.add_parser(name)
        subparser.add_argument("--current", type=Path, required=True)
        subparser.add_argument("--quality-manifest", type=Path, required=True)
        subparser.add_argument("--quality-report", type=Path, required=True)
        subparser.add_argument("--quality-receipt", type=Path, required=True)
        subparser.add_argument("--output", type=Path, required=True)
        if name == "make-request":
            subparser.add_argument("--runtime-root", type=Path, required=True)
            subparser.add_argument("--worker-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        build_cards(args.current, args.quality_manifest, args.quality_report, args.quality_receipt, args.output)
    else:
        make_request(args.current, args.quality_manifest, args.quality_report, args.quality_receipt,
                     args.output, args.runtime_root, args.worker_root)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
