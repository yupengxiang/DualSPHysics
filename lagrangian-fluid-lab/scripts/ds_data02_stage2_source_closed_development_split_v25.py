#!/usr/bin/env python3
"""Prepare source-closed development roles for the seven actual anchors.

This is a forward metadata consumer.  It joins the immutable predicted v24
cards, their root-verified v24 execution, the seven-family label-quality
product, and the source-closed all-118 mechanism-v3 product.  Each anchor is
kept in its own component.  The output grants only bounded saved-frame,
artifact, source-role, and native-cause bookkeeping roles; it never grants a
physical fate, recovery equivalence, effective physical split, QN, QE, or QI.

Only JSON/XML and other explicitly bound small evidence files are opened.  H5,
BI4, raw PartOut, and solver trajectory payloads are rejected as inputs to the
worker and are represented only by producer-declared paths/digests copied from
completed reports.  The worker prepares a guarded CPU request but never
launches it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.source-closed-development-split.v25"
MANIFEST_SCHEMA = "ds02.stage2.current336-task-evidence-manifest.v25"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
QUALITY_SCHEMA = "ds02.stage2.family-label-quality.v3"
MECHANISM_SCHEMA = "ds02.stage2.omission-mechanism-probe.v3"
V24_SCHEMA = "ds02.stage2.effective-condition-cards.v24"
FAMILIES = [f"F{i}" for i in range(1, 8)]
ANCHOR_INDICES = {"F1": 0, "F2": 78, "F3": 96, "F4": 144, "F5": 192, "F6": 240, "F7": 288}
MECHANISM_FAMILIES = {"F2", "F4", "F6"}
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}
SMALL_SUFFIXES = {".json", ".xml", ".xmf", ".cfg", ".txt", ".csv", ".out", ".py"}


class SplitError(RuntimeError):
    """Raised when source identity or a development-role contract is open."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Any, label: str, *, allow_forbidden: bool = False) -> Path:
    if isinstance(value, Path):
        path = value.expanduser().resolve()
    elif isinstance(value, str) and value:
        path = Path(value).expanduser().resolve()
    else:
        raise SplitError(f"{label} must be a non-empty path")
    if not path.is_file():
        raise SplitError(f"{label} is missing: {path}")
    if not allow_forbidden and path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise SplitError(f"{label} is a forbidden scientific payload: {path}")
    return path


def read_json(path: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SplitError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise SplitError(f"{label} must be an object: {path}")
    return path, value


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPT.parents[2], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _binding(path: Path, declared: str | None, role: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in FORBIDDEN_SUFFIXES:
        raise SplitError(f"{role} is a forbidden scientific payload: {path}")
    if suffix not in SMALL_SUFFIXES and path.name not in {"Run.out", "DsphConfig.xml"}:
        raise SplitError(f"{role} is not an allowed small evidence file: {path}")
    observed = sha256_file(path)
    if declared and declared != observed:
        raise SplitError(f"{role} hash differs from its declared evidence digest: {path}")
    return {"role": role, "path": str(path), "bytes": path.stat().st_size,
            "sha256": observed, "declared_sha256": declared,
            "sha256_matches_declared": declared in (None, observed)}


def _v24_card_small_bindings(card: dict[str, Any], current_row: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    evidence = card.get("condition_evidence")
    if not isinstance(evidence, dict):
        raise SplitError(f"{card.get('family_id')} v24 card lacks condition evidence")
    result: list[dict[str, Any]] = []
    for role in ("owner", "generated_xml", "gencase_receipt", "solver_receipt", "conversion_report"):
        value = evidence.get(role)
        # v24 intentionally stores the owner path in CURRENT source_bindings
        # while storing only its semantic summary in the card.  Recover the
        # already bound owner path from that exact CURRENT row; never search
        # for a substitute owner file.
        if role == "owner" and isinstance(current_row, dict):
            value = current_row.get("source_bindings", {}).get("owner_metadata")
        if not isinstance(value, dict):
            raise SplitError(f"{card.get('family_id')} v24 card lacks {role}")
        path_value = value.get("path")
        path = require_file(path_value, f"{card.get('family_id')} {role}")
        declared = value.get("observed_sha256") or value.get("sha256")
        result.append(_binding(path, declared, f"{card.get('family_id')} {role}"))
    label = card.get("label_product_binding", {}).get("label_report")
    if not isinstance(label, dict):
        raise SplitError(f"{card.get('family_id')} v24 card lacks label report")
    path = require_file(label.get("path"), f"{card.get('family_id')} label report")
    result.append(_binding(path, label.get("sha256"), f"{card.get('family_id')} label report"))
    return result


def _unique_bindings(bindings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        unique[binding["path"]] = binding
    return [unique[path] for path in sorted(unique)]


def _validate_receipt(receipt_path: Path, receipt: dict[str, Any], label: str) -> dict[str, Any]:
    if receipt.get("schema") != "ds02.execution-receipt.v1":
        raise SplitError(f"{label} receipt schema is not execution-receipt.v1")
    if receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise SplitError(f"{label} receipt is not completed successfully")
    return {
        "path": str(receipt_path),
        "sha256": sha256_file(receipt_path),
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "output_root": receipt.get("output_root"),
        "request_sha256": receipt.get("request_sha256"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
    }


def _validate_quality(current: dict[str, Any], manifest_path: Path, quality: dict[str, Any], receipt_path: Path,
                      receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if quality.get("schema") != QUALITY_SCHEMA or quality.get("status") != "FAMILY_LABEL_QUALITY_V3_PASS_MASS_CENSOR_ARTIFACT_SOURCE_BOUND":
        raise SplitError("seven-family quality report is not the actual v3 product")
    if quality.get("manifest", {}).get("sha256") != sha256_file(manifest_path):
        raise SplitError("quality report does not bind the supplied quality manifest")
    _validate_receipt(receipt_path, receipt, "quality")
    cases = quality.get("cases")
    if not isinstance(cases, list) or len(cases) != 7:
        raise SplitError("quality report must contain seven anchor cases")
    current_keys = {(row.get("family_id"), row.get("physical_case_id")): (index, row) for index, row in enumerate(current.get("cases", []))}
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        identity = case.get("normalized_identity")
        source = case.get("source")
        if not isinstance(identity, dict) or not isinstance(source, dict):
            raise SplitError("quality case lacks normalized identity or source")
        family = identity.get("family_id")
        key = (family, identity.get("physical_case_id"))
        if family not in FAMILIES or key not in current_keys or family in result:
            raise SplitError(f"quality case is not an exact CURRENT anchor: {key}")
        current_index, _current_row = current_keys[key]
        if current_index != ANCHOR_INDICES[family]:
            raise SplitError(f"quality case {family} is not the registered CURRENT anchor index")
        report = require_file(source.get("report_path"), f"{family} label report")
        if source.get("report_sha256") != sha256_file(report):
            raise SplitError(f"{family} label report hash differs")
        if not isinstance(case.get("split"), str) or not case["split"].startswith("development"):
            raise SplitError(f"{family} quality split is not a development role")
        source_role = source.get("source_role") or case.get("source_role")
        if source_role not in {"native_initial_mk", "initial_spatial_region"}:
            raise SplitError(f"{family} quality source role is unsupported: {source_role}")
        result[family] = {
            "family_id": family,
            "physical_case_id": identity["physical_case_id"],
            "entry_key": case.get("entry_key"),
            "split": case["split"],
            "source_role": source_role,
            "source_role_basis": case.get("source_role_basis"),
            "quality_checks": copy_json(case.get("quality_checks") or {}),
            "censoring_scope": copy_json(case.get("censoring_scope") or {}),
            "mass_weighted_scope": copy_json(case.get("mass_weighted_scope") or {}),
            "source": {
                "report": {"path": str(report), "sha256": sha256_file(report)},
                "labels_h5": source.get("labels_h5"),
                "labels_h5_sha256": source.get("labels_h5_sha256"),
                "trajectory_sha256": source.get("trajectory_sha256"),
                "raw_solver_output": source.get("raw_solver_output"),
                "h5_opened_by_quality_producer": quality.get("read_policy", {}).get("materialized_label_h5_opened"),
            },
        }
    if sorted(result) != FAMILIES:
        raise SplitError("quality report does not cover all seven families")
    return result


def _validate_v24(predicted_path: Path, predicted: dict[str, Any], actual_path: Path, actual: dict[str, Any],
                  proof_path: Path, proof: dict[str, Any], current_path: Path, current: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    for label, value in (("predicted", predicted), ("actual", actual)):
        if value.get("schema") != V24_SCHEMA:
            raise SplitError(f"v24 {label} card schema is not v24")
        if value.get("anchor_count") != 7 or len(value.get("cards", [])) != 7:
            raise SplitError(f"v24 {label} cards do not contain seven anchors")
        if value.get("inputs", {}).get("current336", {}).get("sha256") != sha256_file(current_path):
            raise SplitError(f"v24 {label} cards are bound to another CURRENT336")
    if predicted.get("status") != "PREPARED_SOURCE_BOUND_EFFECTIVE_COMPONENTS_NO_PHYSICAL_QUALIFICATION":
        raise SplitError("predicted v24 cards have an unexpected status")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith("PASS_ACTUAL_SEVEN_CONDITION_CARDS"):
        raise SplitError("v24 root actual proof is not the completed source-join verification")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("raw_H5_second_read") is not False:
        raise SplitError("v24 actual proof reports a forbidden trajectory/BI4 read")
    if proof.get("scientific_qualification", {}).get("QN") != "UNKNOWN" or proof.get("scientific_qualification", {}).get("QE") != "UNKNOWN":
        raise SplitError("v24 actual proof grants scientific qualification")
    proof_report = require_file(proof.get("report"), "v24 actual proof report")
    proof_receipt = require_file(proof.get("receipt"), "v24 actual execution receipt")
    proof_request = require_file(proof.get("request"), "v24 actual request")
    if proof_report != actual_path or proof.get("report_sha256") != sha256_file(actual_path):
        raise SplitError("v24 actual proof report path or digest differs")
    if proof.get("receipt_sha256") != sha256_file(proof_receipt):
        raise SplitError("v24 actual proof receipt digest differs")
    actual_receipt = json.loads(proof_receipt.read_text(encoding="utf-8"))
    _validate_receipt(proof_receipt, actual_receipt, "v24 actual")
    actual_request = json.loads(proof_request.read_text(encoding="utf-8"))
    if actual_request.get("schema") not in {"ds02.runner-request.v1", "ds02.request.v1"}:
        raise SplitError("v24 actual request schema is not a guarded request")
    current_by_key = {(row.get("family_id"), row.get("physical_case_id")): (index, row) for index, row in enumerate(current.get("cases", []))}
    result: dict[str, dict[str, Any]] = {}
    for value, label in ((predicted, "predicted"), (actual, "actual")):
        seen: set[str] = set()
        for card in value["cards"]:
            family = card.get("family_id")
            key = (family, card.get("physical_case_id"))
            if family not in FAMILIES or family in seen or key not in current_by_key:
                raise SplitError(f"v24 {label} card is not an exact CURRENT anchor: {key}")
            current_index, _current_row = current_by_key[key]
            if current_index != ANCHOR_INDICES[family] or card.get("current_index") != ANCHOR_INDICES[family]:
                raise SplitError(f"v24 {label} card {family} is not the registered CURRENT anchor index")
            seen.add(family)
    predicted_by_family = {card["family_id"]: card for card in predicted["cards"]}
    actual_by_family = {card["family_id"]: card for card in actual["cards"]}
    for family in FAMILIES:
        p = predicted_by_family[family]; a = actual_by_family[family]
        for field in ("physical_case_id", "current_index", "component_id", "runtime_case_alias"):
            if p.get(field) != a.get(field):
                raise SplitError(f"v24 actual {family} differs from predicted on {field}")
        _v24_card_small_bindings(p, current_by_key[(family, p.get("physical_case_id"))][1])
    proof_summary = {
        "path": str(proof_path), "sha256": sha256_file(proof_path), "status": proof.get("status"),
        "report": {"path": str(actual_path), "sha256": sha256_file(actual_path)},
        "receipt": {"path": str(proof_receipt), "sha256": sha256_file(proof_receipt)},
        "request": {"path": str(proof_request), "sha256": sha256_file(proof_request)},
        "parent_actual_prepost_content_hashes_equal": proof.get("parent_actual_prepost_content_hashes_equal"),
        "parent_charge": copy_json(proof.get("parent_charge") or {}),
        "H5_BI4_read_by_root": proof.get("H5_BI4_read_by_root"),
        "raw_H5_second_read": proof.get("raw_H5_second_read"),
        "scientific_qualification": copy_json(proof.get("scientific_qualification") or {}),
        "qualification_credit": proof.get("qualification_credit"),
        "verified_anchor_count": len(proof.get("verified_anchors") or []),
    }
    return predicted_by_family, {"predicted_path": str(predicted_path), "predicted_sha256": sha256_file(predicted_path),
                                 "actual_path": str(actual_path), "actual_sha256": sha256_file(actual_path),
                                 "actual_verification": proof_summary}


def _validate_mechanism(current_path: Path, current: dict[str, Any], report_path: Path, report: dict[str, Any],
                        receipt_path: Path, receipt: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("schema") != MECHANISM_SCHEMA or report.get("status") != "MECHANISM_PROBE_SOURCE_CLOSED_F2_S1_UPGRADED_NO_H5":
        raise SplitError("all-118 mechanism report is not the completed v3 source-closed product")
    identity = report.get("current_identity")
    if not isinstance(identity, dict) or identity.get("sha256") != sha256_file(current_path):
        raise SplitError("mechanism v3 report is bound to another CURRENT336")
    policy = report.get("read_policy")
    if not isinstance(policy, dict) or any(policy.get(key) is not False for key in ("h5_opened", "trajectory_content_opened", "raw_partout_opened", "solver_started")):
        raise SplitError("mechanism v3 read policy does not close H5/BI4/solver scope")
    _validate_receipt(receipt_path, receipt, "mechanism v3")
    if isinstance(receipt.get("output_root"), str) and Path(receipt["output_root"]).expanduser().resolve() != report_path.parent:
        raise SplitError("mechanism v3 receipt output root differs from report parent")
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise SplitError("mechanism v3 report is not exactly 118 cases")
    current_by_key = {(row.get("family_id"), row.get("physical_case_id")): (index, row) for index, row in enumerate(current.get("cases", []))}
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for case in cases:
        family = case.get("family_id"); physical = case.get("physical_case_id"); key = (family, physical)
        if family not in MECHANISM_FAMILIES or key not in current_by_key or key in seen:
            raise SplitError(f"mechanism v3 case is not a unique CURRENT F2/F4/F6 case: {key}")
        seen.add(key)
        index, row = current_by_key[key]
        native = case.get("native_gate") if isinstance(case.get("native_gate"), dict) else {}
        cause = native.get("cause") if isinstance(native.get("cause"), dict) else {}
        mass = case.get("mass_visibility") if isinstance(case.get("mass_visibility"), dict) else {}
        source_closure = case.get("source_closure") if isinstance(case.get("source_closure"), dict) else {}
        result.append({
            "case_key": case.get("case_key"), "family_id": family, "physical_case_id": physical,
            "current_index": index, "runtime_case_alias": row.get("runtime_case_alias"),
            "source_role": "native_initial_mk" if family in {"F2", "F4", "F6"} else "UNKNOWN",
            "native_gate": {"motive": native.get("motive"), "native_count": native.get("native_count"),
                            "runparts_totals": copy_json(native.get("runparts_totals") or {}),
                            "cause": copy_json(cause)},
            "first_missing_window_s": copy_json(case.get("first_missing_window_s")),
            "mass_visibility": {key: mass.get(key) for key in (
                "initial_fluid_mass_denominator_kg", "missing_source_visible_mass_lower_bound_kg",
                "missing_source_visible_fraction_lower_bound", "screen_gate_fraction", "screen") if key in mass},
            "physical_fate": case.get("physical_fate"),
            "legal_outflow_or_spill": case.get("legal_outflow_or_spill"),
            "dynamical_impact": case.get("dynamical_impact"),
            "source_closure": {"status": source_closure.get("status"), "claim_boundary": copy_json(case.get("source_closure_claim_boundary") or {})},
        })
    counts = {family: sum(row["family_id"] == family for row in result) for family in sorted(MECHANISM_FAMILIES)}
    expected = {"F2": 48, "F4": 22, "F6": 48}
    if counts != expected:
        raise SplitError(f"mechanism v3 family coverage differs: {counts}")
    return result


def _development_role(split: str) -> str:
    return {
        "development": "development_train",
        "development_validation": "development_validation",
        "development_test": "development_test",
    }.get(split, "development_unassigned")


def _condition_graph(family: str, current_row: dict[str, Any], card: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    evidence = card["condition_evidence"]
    owner_value = evidence["owner"]
    owner = owner_value.get("semantic_summary") if isinstance(owner_value.get("semantic_summary"), dict) else owner_value
    if not isinstance(owner, dict):
        owner = {}
    generated = evidence["generated_xml"]
    solver = evidence["solver_receipt"]
    solver_join = evidence.get("solver_receipt_binding") or {}
    quality_source = quality["source"]
    component_id = card["component_id"]
    return {
        "component_id": component_id,
        "nodes": [
            {"id": f"{component_id}:condition", "kind": "physical_control_geometry", "status": "SOURCE_CLOSED_METADATA_ONLY"},
            {"id": f"{component_id}:native_parent", "kind": "native_solver_parent", "status": "SOURCE_CLOSED"},
            {"id": f"{component_id}:recovery_product", "kind": "saved_label_quality_product", "status": "SOURCE_CLOSED_PRODUCT_METADATA"},
            {"id": f"{component_id}:window", "kind": "saved_frame_window", "status": "SOURCE_CLOSED_METADATA_ONLY"},
        ],
        "edges": [
            {"from": f"{component_id}:condition", "to": f"{component_id}:native_parent", "relation": "generated_and_solved_under", "evidence": ["generated_xml", "gencase_receipt", "solver_receipt"]},
            {"from": f"{component_id}:native_parent", "to": f"{component_id}:recovery_product", "relation": "produced_saved_label_product", "evidence": ["quality_report", "label_report"]},
            {"from": f"{component_id}:recovery_product", "to": f"{component_id}:window", "relation": "bounded_by_saved_window", "evidence": ["CURRENT336", "quality_censoring_scope"]},
        ],
        "condition": {
            "physical_condition_sha256": owner.get("physical_condition_sha256"),
            "geometry_family_id": owner.get("geometry_family_id"),
            "control_family_id": owner.get("control_family_id"),
            "lineage_group_id": owner.get("lineage_group_id"),
            "mechanism_id": owner.get("mechanism_id"),
            "controls": copy_json(owner.get("controls") or {}),
            "geometry": copy_json(owner.get("geometry") or {}),
            "parameters": copy_json(owner.get("parameters") or {}),
            "known_numeric_physical_parameters": copy_json(current_row.get("known_numeric_physical_parameters") or {}),
            "generated_xml_summary": copy_json(generated.get("semantic_summary") or {}),
        },
        "native_parent": {
            "generated_xml": copy_json(evidence["generated_xml"]),
            "gencase_receipt": copy_json(evidence["gencase_receipt"]),
            "solver_receipt": copy_json(evidence["solver_receipt"]),
            "solver_output_root": solver.get("output_root"),
            "solver_xml_and_gencase_join": copy_json(solver_join),
            "same_parent_derivatives_must_stay_in_component": True,
        },
        "recovery": {
            "quality_entry_key": quality.get("entry_key"),
            "quality_report": copy_json(quality_source["report"]),
            "producer_split": quality.get("split"),
            "source_role": quality.get("source_role"),
            "source_role_basis": quality.get("source_role_basis"),
            "labels_h5": {"path": quality_source.get("labels_h5"), "producer_declared_sha256": quality_source.get("labels_h5_sha256"), "opened_by_v25": False},
            "trajectory_h5": {"path": current_row.get("trajectory", {}).get("path"), "producer_declared_sha256": current_row.get("trajectory", {}).get("producer_declared_sha256"), "opened_by_v25": False},
            "recovery_equivalence_to_other_anchor": "UNKNOWN",
        },
        "window": {
            "frames": current_row.get("frames"),
            "particles": current_row.get("particles"),
            "actual_time_window_s": copy_json(current_row.get("actual_time_window_s")),
            "censoring_scope": copy_json(quality.get("censoring_scope") or {}),
            "window_transfer_to_other_anchor": "UNKNOWN",
        },
    }


def _component(family: str, row: dict[str, Any], card: dict[str, Any], quality: dict[str, Any]) -> dict[str, Any]:
    role = _development_role(quality["split"])
    source_role = quality["source_role"]
    component_id = card["component_id"]
    return {
        "component_id": component_id,
        "members": [{"family_id": family, "physical_case_id": row.get("physical_case_id"), "current_index": row.get("current_index")}],
        "component_unit": "one exact CURRENT anchor; no cross-anchor merge",
        "condition_graph": _condition_graph(family, row, card, quality),
        "development_roles": {
            "saved_frame_artifact": role,
            "source_role_mass_ledger": f"{role}:{source_role}",
            "native_cause_alias_join": "development_metadata_native_cause_only" if family in MECHANISM_FAMILIES else "not_selected_by_all118_mechanism_v3",
            "owner_control_geometry": "development_source_closed_metadata",
            "component_derivatives": "all same-parent derivatives remain within this component",
        },
        "supported_scope": {
            "saved_frame_artifact": "exact producer label report and saved-frame quality metadata for this anchor",
            "mass_ledger": f"source-role-specific bookkeeping only ({source_role}); whole-initial denominator remains task-specific",
            "native_cause_alias_join": "native motive/source-visibility join only; physical destination remains unknown" if family in MECHANISM_FAMILIES else "not applicable",
            "scientific_qualification": "none",
        },
        "unsupported_transfer_exclusions": [
            "same upstream quality split does not establish physical/control/geometry equivalence with another component",
            f"source role {source_role} cannot transfer mass interpretation to the other source role",
            "native parent, recovery lineage, and saved window cannot transfer across anchors without exact equality evidence",
            "saved-frame chord observations cannot be promoted to continuous first arrival or hidden-event truth",
            "native numerical position/density cause cannot be promoted to physical spill, legal flux, or dynamical error",
            "QN, QE, and QI remain UNKNOWN and receive no credit",
        ],
        "same_parent_role_conflicts": [],
        "cross_component_transfer_edges": [],
        "scientific_status": {
            "effective_split_safe": "UNKNOWN",
            "recovery_safe": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "continuous_first_arrival": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "QI": "UNKNOWN",
        },
    }


def build(current_path: Path | str, quality_manifest_path: Path | str, quality_report_path: Path | str,
          quality_receipt_path: Path | str, mechanism_report_path: Path | str, mechanism_receipt_path: Path | str,
          v24_predicted_path: Path | str, v24_actual_path: Path | str, v24_proof_path: Path | str,
          manifest_output: Path | str, output: Path | str) -> dict[str, Any]:
    current_path, current = read_json(current_path, "CURRENT336")
    quality_manifest_path, quality_manifest = read_json(quality_manifest_path, "seven-family quality manifest")
    quality_report_path, quality_report = read_json(quality_report_path, "seven-family quality report")
    quality_receipt_path, quality_receipt = read_json(quality_receipt_path, "seven-family quality receipt")
    mechanism_report_path, mechanism_report = read_json(mechanism_report_path, "all-118 mechanism report")
    mechanism_receipt_path, mechanism_receipt = read_json(mechanism_receipt_path, "all-118 mechanism receipt")
    v24_predicted_path, v24_predicted = read_json(v24_predicted_path, "predicted v24 cards")
    v24_actual_path, v24_actual = read_json(v24_actual_path, "actual v24 cards")
    v24_proof_path, v24_proof = read_json(v24_proof_path, "v24 actual verification proof")
    if current.get("schema") != CURRENT_SCHEMA:
        raise SplitError("CURRENT336 schema is not current336.v1")
    quality_by_family = _validate_quality(current, quality_manifest_path, quality_report, quality_receipt_path, quality_receipt)
    predicted_by_family, v24_verification = _validate_v24(v24_predicted_path, v24_predicted, v24_actual_path, v24_actual, v24_proof_path, v24_proof, current_path, current)
    mechanism_rows = _validate_mechanism(current_path, current, mechanism_report_path, mechanism_report, mechanism_receipt_path, mechanism_receipt)
    current_by_family: dict[str, dict[str, Any]] = {}
    for family, index in ANCHOR_INDICES.items():
        if index >= len(current.get("cases", [])):
            raise SplitError(f"CURRENT336 lacks anchor index {index} for {family}")
        row = current.get("cases", [])[index]
        if not isinstance(row, dict) or row.get("family_id") != family:
            raise SplitError(f"CURRENT336 anchor index {index} is not {family}")
        row = copy_json(row); row["current_index"] = index; current_by_family[family] = row
    if sorted(current_by_family) != FAMILIES:
        raise SplitError("CURRENT336 lacks one or more family anchors")
    components = [_component(family, current_by_family[family], predicted_by_family[family], quality_by_family[family]) for family in FAMILIES]
    evidence_bindings: list[dict[str, Any]] = []
    for family in FAMILIES:
        evidence_bindings.extend(_v24_card_small_bindings(predicted_by_family[family], current_by_family[family]))
    evidence_bindings = _unique_bindings(evidence_bindings)
    current_alias = [{
        "case_key": item["case_key"], "family_id": item["family_id"], "physical_case_id": item["physical_case_id"],
        "current_index": item["current_index"], "runtime_case_alias": item["runtime_case_alias"],
        "native_motive": item["native_gate"].get("motive"), "native_count": item["native_gate"].get("native_count"),
        "first_missing_window_s": item["first_missing_window_s"], "mass_visibility": item["mass_visibility"],
        "physical_fate": item["physical_fate"], "dynamical_impact": item["dynamical_impact"],
        "source_closure": item["source_closure"],
    } for item in mechanism_rows]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_SOURCE_CLOSED_TASK_EVIDENCE",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT), "git_commit": _git_commit()},
        "current336": {"path": str(current_path), "sha256": sha256_file(current_path), "schema": current.get("schema"), "case_count": len(current.get("cases", []))},
        "quality": {
            "manifest": {"path": str(quality_manifest_path), "sha256": sha256_file(quality_manifest_path)},
            "report": {"path": str(quality_report_path), "sha256": sha256_file(quality_report_path)},
            "receipt": {"path": str(quality_receipt_path), "sha256": sha256_file(quality_receipt_path)},
            "case_count": 7,
        },
        "mechanism_v3": {
            "report": {"path": str(mechanism_report_path), "sha256": sha256_file(mechanism_report_path)},
            "receipt": {"path": str(mechanism_receipt_path), "sha256": sha256_file(mechanism_receipt_path)},
            "case_count": len(mechanism_rows), "family_counts": {family: sum(item["family_id"] == family for item in mechanism_rows) for family in sorted(MECHANISM_FAMILIES)},
            "alias_semantic_closure": "exact (family_id, physical_case_id) -> CURRENT index/runtime_case_alias; no particle observations copied",
        },
        "effective_condition_cards_v24": {
            "predicted": {"path": v24_verification["predicted_path"], "sha256": v24_verification["predicted_sha256"], "preserved": True},
            "actual": {"path": v24_verification["actual_path"], "sha256": v24_verification["actual_sha256"], "root_verified": True},
            "actual_verification": v24_verification["actual_verification"],
        },
        "small_source_evidence": evidence_bindings,
        "tasks": [
            {"task_id": "saved_frame_artifact_diagnostics", "selection": "seven exact v24 anchors", "role": "development metadata only", "scientific_qualification": "UNKNOWN"},
            {"task_id": "source_role_mass_ledger_diagnostics", "selection": "seven exact v24 anchors", "role": "source-role-specific development bookkeeping", "scientific_qualification": "UNKNOWN"},
            {"task_id": "native_cause_mass_censoring_alias_join", "selection": "all 118 exact F2/F4/F6 mechanism-v3 cases", "role": "native motive/source-visible accounting only", "scientific_qualification": "UNKNOWN"},
            {"task_id": "physical_fate_and_dynamics", "selection": "none", "role": "EXCLUDED_UNSUPPORTED", "reason": "all producer claim boundaries remain UNKNOWN"},
        ],
        "read_policy": {
            "current_json_opened": True, "quality_manifest_report_receipt_opened": True, "mechanism_report_receipt_opened": True,
            "v24_predicted_actual_proof_opened": True, "small_owner_xml_receipts_conversion_label_reports_opened": True,
            "mechanism_particle_observations_copied": False, "materialized_label_h5_opened": False,
            "original_trajectory_h5_opened": False, "part_bi4_opened": False, "raw_solver_output_opened": False,
            "solver_started": False, "model_invoked": False,
        },
    }
    manifest_output = Path(manifest_output).expanduser().resolve()
    if manifest_output.exists():
        raise SplitError(f"refusing to overwrite v25 manifest: {manifest_output}")
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema": SCHEMA,
        "status": "PREPARED_SOURCE_CLOSED_DEVELOPMENT_SPLIT_V24_ACTUAL_VERIFIED_NO_PHYSICAL_QUALIFICATION",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT), "git_commit": _git_commit()},
        "inputs": {
            "task_evidence_manifest": {"path": str(manifest_output), "sha256": sha256_file(manifest_output)},
            "current336": {"path": str(current_path), "sha256": sha256_file(current_path)},
            "quality_report": {"path": str(quality_report_path), "sha256": sha256_file(quality_report_path)},
            "mechanism_v3_report": {"path": str(mechanism_report_path), "sha256": sha256_file(mechanism_report_path)},
            "v24_predicted_cards": {"path": str(v24_predicted_path), "sha256": sha256_file(v24_predicted_path)},
            "v24_actual_cards": {"path": str(v24_actual_path), "sha256": sha256_file(v24_actual_path)},
            "v24_actual_proof": {"path": str(v24_proof_path), "sha256": sha256_file(v24_proof_path)},
        },
        "verification": {
            "v24_predicted_cards_preserved": True,
            "v24_actual_cards_root_verified": True,
            "v24_actual_verification": v24_verification["actual_verification"],
            "v25_actual_guarded_run": "PENDING_ROOT_GUARDED_RUN",
        },
        "component_count": 7,
        "components": components,
        "mechanism_alias_semantic_closure": {
            "report": {"path": str(mechanism_report_path), "sha256": sha256_file(mechanism_report_path)},
            "receipt": {"path": str(mechanism_receipt_path), "sha256": sha256_file(mechanism_receipt_path)},
            "current_identity": {"path": str(current_path), "sha256": sha256_file(current_path)},
            "case_count": len(current_alias), "family_counts": {family: sum(row["family_id"] == family for row in current_alias) for family in sorted(MECHANISM_FAMILIES)},
            "cases": current_alias,
            "source_fate_and_dynamics": "UNKNOWN for every case; native cause/source-visible lower bounds only",
        },
        "development_split": {
            "split_unit": "exact source-closed anchor component",
            "assignments": [{"family_id": family, "component_id": components[i]["component_id"], "saved_frame_role": _development_role(quality_by_family[family]["split"]), "source_role": quality_by_family[family]["source_role"], "scientific_split_safe": "UNKNOWN"} for i, family in enumerate(FAMILIES)],
            "supported_task_scopes": ["saved_frame_artifact", "source_role_mass_ledger", "native_cause_alias_join", "owner_control_geometry_metadata"],
            "same_parent_derivatives_rule": "derivatives from one native parent remain in its component and cannot cross source roles or quality roles",
            "cross_component_merge": "DISALLOWED_UNLESS_EXACT_PHYSICAL_CONTROL_GEOMETRY_PARENT_RECOVERY_WINDOW_EQUALITY_IS_LATER_PROVEN",
            "unsupported_transfer_exclusions": [
                "native_initial_mk and initial_spatial_region are disjoint source roles; no transfer or pooled mass denominator",
                "development/development_validation/development_test labels are producer metadata roles, not physical train/validation/test safety",
                "different physical cases, controls, geometries, native parents, recovery products, or windows cannot be merged by family name or schema",
                "native position/density motives and source-visible mass lower bounds do not identify legal spill, physical fate, or dynamical error",
                "saved-frame first passage is a saved chord bracket; continuous arrivals, re-entry, recrossing, and residence transfer remain UNKNOWN",
                "QN, QE, QI and all physical qualification credit are excluded",
            ],
            "same_parent_role_conflicts": [], "cross_component_transfer_edges": [],
            "physical_qualification": "UNKNOWN",
        },
        "read_policy": manifest["read_policy"],
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise SplitError(f"refusing to overwrite v25 split: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _all_input_paths(current_path: Path, quality_manifest_path: Path, quality_report_path: Path, quality_receipt_path: Path,
                     mechanism_report_path: Path, mechanism_receipt_path: Path, v24_predicted_path: Path, v24_actual_path: Path,
                     v24_proof_path: Path, v24_predicted_request_path: Path, v24_actual_request_path: Path,
                     v24_predicted: dict[str, Any]) -> list[Path]:
    _current_path, current = read_json(current_path, "CURRENT336 for v25 request inputs")
    current_rows = {row.get("family_id"): row for row in current.get("cases", []) if isinstance(row, dict)}
    paths = [SCRIPT, current_path, quality_manifest_path, quality_report_path, quality_receipt_path,
             mechanism_report_path, mechanism_receipt_path, v24_predicted_path, v24_actual_path, v24_proof_path,
             v24_predicted_request_path, v24_actual_request_path]
    for family in FAMILIES:
        card = next(card for card in v24_predicted["cards"] if card.get("family_id") == family)
        paths.extend(Path(row["path"]) for row in _v24_card_small_bindings(card, current_rows.get(family)))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = Path(path).expanduser().resolve()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise SplitError(f"request input would read forbidden payload: {path}")
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    return unique


def make_request(current_path: Path | str, quality_manifest_path: Path | str, quality_report_path: Path | str,
                 quality_receipt_path: Path | str, mechanism_report_path: Path | str, mechanism_receipt_path: Path | str,
                 v24_predicted_path: Path | str, v24_actual_path: Path | str, v24_proof_path: Path | str,
                 v24_predicted_request_path: Path | str, v24_actual_request_path: Path | str,
                 output: Path | str, runtime_root: Path | str, worker_root: Path | str,
                 attempt_id: str = "current336-source-closed-development-split-v25-forward-001") -> dict[str, Any]:
    current_path, current = read_json(current_path, "CURRENT336")
    quality_manifest_path, _ = read_json(quality_manifest_path, "quality manifest")
    quality_report_path, _ = read_json(quality_report_path, "quality report")
    quality_receipt_path, _ = read_json(quality_receipt_path, "quality receipt")
    mechanism_report_path, _ = read_json(mechanism_report_path, "mechanism report")
    mechanism_receipt_path, _ = read_json(mechanism_receipt_path, "mechanism receipt")
    v24_predicted_path, v24_predicted = read_json(v24_predicted_path, "predicted v24 cards")
    v24_actual_path = require_file(v24_actual_path, "actual v24 cards")
    v24_proof_path = require_file(v24_proof_path, "v24 proof")
    v24_predicted_request_path = require_file(v24_predicted_request_path, "predicted v24 request")
    v24_actual_request_path = require_file(v24_actual_request_path, "actual v24 request")
    inputs = _all_input_paths(current_path, quality_manifest_path, quality_report_path, quality_receipt_path,
                              mechanism_report_path, mechanism_receipt_path, v24_predicted_path, v24_actual_path,
                              v24_proof_path, v24_predicted_request_path, v24_actual_request_path, v24_predicted)
    runtime_root = Path(runtime_root).expanduser().resolve(); worker_root = Path(worker_root).expanduser().resolve()
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_source_closed_development_split_v25.py"
    runtimes = [runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
                runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
                runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
                runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]
    inputs.extend(runtimes)
    unique: list[Path] = []; seen: set[str] = set()
    for path in inputs:
        path = path.resolve()
        if str(path) not in seen: unique.append(path); seen.add(str(path))
    missing = [str(path) for path in unique if not path.is_file()]
    hashes = {str(path): sha256_file(path) for path in unique if path.is_file()}
    output = Path(output).expanduser().resolve()
    if output.exists(): raise SplitError(f"refusing to overwrite v25 request: {output}")
    request = {
        "schema": "ds02.runner-request.v1", "request_schema": "ds02.stage2.source-closed-development-split-v25-request.v1",
        "attempt_id": attempt_id, "case_id": "DS02_STAGE2_SOURCE_CLOSED_DEVELOPMENT_SPLIT_V25", "family_id": "infra",
        "dataset_families": FAMILIES, "kind": "cpu", "cpu_task_kind": "metadata_audit", "cpu_threads": 1,
        "max_wall_seconds": 600, "estimated_storage_bytes": 32 * 1024 * 1024,
        "cwd": str(worker_root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(worker_root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "build",
                     "--current", str(current_path), "--quality-manifest", str(quality_manifest_path), "--quality-report", str(quality_report_path),
                     "--quality-receipt", str(quality_receipt_path), "--mechanism-report", str(mechanism_report_path), "--mechanism-receipt", str(mechanism_receipt_path),
                     "--v24-predicted", str(v24_predicted_path), "--v24-actual", str(v24_actual_path), "--v24-proof", str(v24_proof_path),
                     "--manifest-output", "{attempt_root}/current336-task-evidence-manifest-v25.json", "--output", "{attempt_root}/current336-source-closed-development-split-v25.json"],
        "input_files": [str(path) for path in unique], "input_sha256": hashes,
        "launch_allowed": not missing, "primary_launch_owner": "root", "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {"small_json_xml_receipt_bytes_read": sum(path.stat().st_size for path in unique if path.is_file()), "materialized_label_h5_bytes_read": 0, "original_trajectory_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "raw_solver_output_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN", "recovery_safe": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "none"},
        "v24_predicted_cards_preserved": True, "v24_actual_cards_required_root_verified": True, "mechanism_v3_alias_semantic_closure": True,
        "missing_guard_sources": missing,
    }
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "make-request"):
        p = sub.add_parser(name)
        for arg in ("current", "quality-manifest", "quality-report", "quality-receipt", "mechanism-report", "mechanism-receipt", "v24-predicted", "v24-actual", "v24-proof"):
            p.add_argument(f"--{arg}", type=Path, required=True)
        if name == "build": p.add_argument("--manifest-output", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        if name == "make-request":
            p.add_argument("--v24-predicted-request", type=Path, required=True); p.add_argument("--v24-actual-request", type=Path, required=True)
            p.add_argument("--runtime-root", type=Path, required=True); p.add_argument("--worker-root", type=Path, required=True)
            p.add_argument("--attempt-id", default="current336-source-closed-development-split-v25-forward-001")
    args = parser.parse_args(argv)
    if args.command == "build":
        build(args.current, args.quality_manifest, args.quality_report, args.quality_receipt, args.mechanism_report, args.mechanism_receipt, args.v24_predicted, args.v24_actual, args.v24_proof, args.manifest_output, args.output)
    else:
        make_request(args.current, args.quality_manifest, args.quality_report, args.quality_receipt, args.mechanism_report, args.mechanism_receipt, args.v24_predicted, args.v24_actual, args.v24_proof, args.v24_predicted_request, args.v24_actual_request, args.output, args.runtime_root, args.worker_root, args.attempt_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
