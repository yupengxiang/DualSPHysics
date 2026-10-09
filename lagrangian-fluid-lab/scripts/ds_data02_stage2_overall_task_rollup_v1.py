#!/usr/bin/env python3
"""Build a source-only overall Stage2 task rollup.

The rollup joins three small, completed products to the immutable 336-case
catalog lineage:

* ROOT134's additive F2 card (and its ROOT126/129 new reference case),
* ROOT128's F3 initial-support audit, and
* ROOT123's F5 initial-mass hard-fail proof.

It consumes JSON only.  It never opens H5, BI4, OBI4, PartOut, VTK, raw
solver output, or a solver.  Task-scope eligibility is recorded separately
from QI/QN/QE and from physical fate/dynamics.  ROOT126's 153 identities are
kept outside the original CURRENT336/118/1328 catalog because their case key
is a new reference recipe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.overall-task-rollup.v1"
MANIFEST_SCHEMA = "ds02.stage2.overall-task-rollup.manifest.v1"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".bi2", ".bi1", ".vtk"}


class RollupError(ValueError):
    """Raised when a source-bound rollup cannot be trusted."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_ref(path: Path, role: str) -> dict[str, Any]:
    st = path.stat()
    return {
        "role": role,
        "path": str(path),
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "ctime_ns": st.st_ctime_ns,
        "st_dev": st.st_dev,
        "st_ino": st.st_ino,
        "sha256": sha256_file(path),
    }


def require_json(path_value: Any, label: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise RollupError(f"{label} path is missing")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise RollupError(f"{label} is not an existing file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise RollupError(f"{label} points to forbidden scientific payload: {path}")
    if path.suffix.lower() != ".json":
        raise RollupError(f"{label} is not JSON: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RollupError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RollupError(f"{label} is not a JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise RollupError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise RollupError(f"{label}: expected {wanted!r}, got {value!r}")


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise RollupError(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise RollupError(f"{label} is not finite")
    return result


def q_unknown(block: Any, label: str) -> None:
    if not isinstance(block, dict):
        raise RollupError(f"{label} is not a qualification object")
    for key in ("QI", "QN", "QE"):
        expect(block.get(key), "UNKNOWN", f"{label}.{key}")


def load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest = read_json(path, "overall task rollup manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    entries = manifest.get("source_refs")
    if not isinstance(entries, list) or not entries:
        raise RollupError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    products: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise RollupError("malformed manifest source reference")
        key = entry["key"]
        if key in paths:
            raise RollupError(f"duplicate source key: {key}")
        path_value = require_json(entry.get("path"), key)
        actual = sha256_file(path_value)
        expect(entry.get("sha256"), actual, f"{key} SHA")
        paths[key] = path_value
        products[key] = read_json(path_value, key)
    return manifest, paths, products


def proof_binding(proof: dict[str, Any], key: str, path: Path, label: str) -> None:
    value = proof.get(key)
    if value != str(path):
        raise RollupError(f"{label} {key} path does not bind the source")


def proof_hash_binding(proof: dict[str, Any], key: str, path: Path, label: str) -> None:
    expect(proof.get(key), sha256_file(path), f"{label} {key} SHA")


def validate_receipt(receipt: dict[str, Any], label: str) -> None:
    expect(receipt.get("schema"), "ds02.execution-receipt.v1", f"{label} schema")
    expect(receipt.get("status"), "completed", f"{label} status")
    expect(receipt.get("returncode"), 0, f"{label} returncode")
    if receipt.get("model_invoked") is True or receipt.get("cfd_invoked") is True:
        raise RollupError(f"{label} reports a model/CFD invocation")


def validate_root134(products: dict[str, dict[str, Any]], paths: dict[str, Path]) -> dict[str, Any]:
    report = products["root134_report"]
    proof = products["root134_proof"]
    receipt = products["root134_receipt"]
    expect(report.get("schema"), "ds02.stage2.f2.family-card.v3", "ROOT134 report schema")
    expect(report.get("family_id"), "F2", "ROOT134 family")
    expect(report.get("status"), "PREPARED_F2_ADDITIVE_CARD_V3_NATIVE_STREAM_DOMAIN_BOUND_NO_SCIENTIFIC_CREDIT", "ROOT134 status")
    expect(proof.get("schema"), "ds02.stage2.root-actual-verification.v1", "ROOT134 proof schema")
    expect(proof.get("status"), "VERIFIED_ACTUAL_F2_ADDITIVE_CARD_V3_SOURCE_DIAGNOSTIC_UNKNOWN_Q", "ROOT134 proof status")
    proof_binding(proof, "report", paths["root134_report"], "ROOT134 proof")
    proof_hash_binding(proof, "report_sha256", paths["root134_report"], "ROOT134 proof")
    proof_binding(proof, "receipt", paths["root134_receipt"], "ROOT134 proof")
    proof_hash_binding(proof, "receipt_sha256", paths["root134_receipt"], "ROOT134 proof")
    if "root134_request" in paths:
        proof_binding(proof, "request", paths["root134_request"], "ROOT134 proof")
        proof_hash_binding(proof, "request_sha256", paths["root134_request"], "ROOT134 proof")
    validate_receipt(receipt, "ROOT134 receipt")
    if proof.get("H5_BI4_read_by_root") is True or proof.get("root_array_content_read") is True:
        raise RollupError("ROOT134 proof reports forbidden array content access")
    q_unknown(report.get("claim_boundary"), "ROOT134 claim boundary")
    q_unknown(report.get("task_eligibility"), "ROOT134 task eligibility")
    stream = report.get("actual_root126_stream")
    sidecar = report.get("actual_root129_sidecar")
    if not isinstance(stream, dict) or not isinstance(sidecar, dict):
        raise RollupError("ROOT134 report lacks ROOT126/ROOT129 evidence")
    expect(stream.get("native_omission_count"), 153, "ROOT134 native omission count")
    expect(stream.get("frame_count"), 401, "ROOT134 frame count")
    expect(sidecar.get("native_omission_count"), 153, "ROOT134 sidecar omission count")
    expect(sidecar.get("status"), None, "ROOT129 consumed top-level status")
    product_status = sidecar.get("product_status")
    if product_status is not None:
        expect(product_status, "V8_STREAM_SOURCE_CLOSED_UNKNOWN_MASS_SCREEN_FAIL", "ROOT129 normalized product status")
    mass = report.get("mass_and_censoring")
    if not isinstance(mass, dict):
        raise RollupError("ROOT134 mass_and_censoring is missing")
    fraction = finite(mass.get("unknown_identity_fraction_xml_whole"), "ROOT134 unknown fraction")
    if fraction <= 0.003:
        raise RollupError("ROOT134 no longer preserves the frozen .003 screen failure")
    return {
        "source": {
            "report": stat_ref(paths["root134_report"], "ROOT134 card report"),
            "proof": stat_ref(paths["root134_proof"], "ROOT134 verification proof"),
            "receipt": stat_ref(paths["root134_receipt"], "ROOT134 execution receipt"),
        },
        "schema": report["schema"],
        "status": report["status"],
        "case_scope": "F2 additive source/card diagnostic; ROOT126 case is recorded separately below",
        "native_stream": {
            "frames": 401,
            "native_ids": 153,
            "native_integrity": "SOURCE_CLOSED_401_FRAME_STREAM_AND_IDENTITY_JOIN",
            "native_bi4_field_stream": True,
            "typed_hdf5_product": False,
        },
        "mass_screen": {
            "xml_whole_initial_mass_kg": finite(mass.get("xml_whole_initial_mass_kg"), "ROOT134 XML mass"),
            "native_excluded_mass_lower_bound_kg": finite(mass.get("native_excluded_mass_lower_bound_kg"), "ROOT134 excluded mass"),
            "unknown_identity_fraction_xml_whole": fraction,
            "frozen_max": 0.003,
            "status": "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003",
            "meaning": "visibility lower bound only; no velocity, force, coupling, fate, or dynamics bound",
        },
        "task_eligibility": {
            "native_frame_integrity_and_identity": "ELIGIBLE_SOURCE_CLOSED_DEVELOPMENT_DIAGNOSTIC",
            "source_MK_and_mass_bookkeeping": "ELIGIBLE_SOURCE_CLOSED_INITIAL_AXIS_ONLY",
            "numerical_position_exclusion_and_saved_bracket": "ELIGIBLE_NUMERICAL_CAUSE_DIAGNOSTIC",
            "physical_destination": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
            "wall_contact_or_penetration": "UNKNOWN",
            "continuous_event_time": "UNKNOWN_SAVED_BRACKET_ONLY",
            "conversion_filtering": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "corrections_without_old_mutation": {
            "card_lineage_role": {
                "observed_consumed_value": report.get("card_lineage", {}).get("role"),
                "normalized_value": "additive F2 card over immutable V2 identity card",
                "reason": "schema and family_id are F2; consumed ROOT134 bytes remain immutable",
            },
            "root129_status": {
                "observed_top_level_value": sidecar.get("status"),
                "normalized_value": "V8_STREAM_SOURCE_CLOSED_UNKNOWN_MASS_SCREEN_FAIL",
                "source_field": "ROOT129.product.status",
            },
            "typed_stream_wording": {
                "normalized_value": "native BI4 saved-field stream; no typed HDF5 product",
                "reason": "ROOT126 stream reads native BI4 fields and emits JSON; no typed HDF5 artifact exists",
            },
        },
        "scientific_q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
    }


def validate_root126_new_case(products: dict[str, dict[str, Any]], paths: dict[str, Path], catalog_case_keys: set[str], catalog_physical_ids: set[str]) -> dict[str, Any]:
    report = products["root126_report"]
    sidecar = products["root129_report"]
    expect(report.get("schema"), "ds02.stage2.f2.coarse-active-stream.v8", "ROOT126 report schema")
    expect(report.get("family_id"), "F2", "ROOT126 family")
    expect(report.get("status"), "COMPLETED_F2_COARSE_ACTIVE_FLUID_STREAM_V8_EXACT_NATIVE_MASS_BITS", "ROOT126 status")
    case_key = report.get("case_key")
    physical_case_id = report.get("physical_case_id")
    if not isinstance(case_key, str) or not isinstance(physical_case_id, str):
        raise RollupError("ROOT126 case identity is missing")
    forms = {case_key, physical_case_id, f"F2/{case_key}", f"F2/{physical_case_id}"}
    overlap = sorted(forms & (catalog_case_keys | catalog_physical_ids))
    if overlap:
        raise RollupError(f"ROOT126 new reference case overlaps original catalog: {overlap}")
    join = report.get("native_identity_join")
    if not isinstance(join, dict) or join.get("native_row_count") != 153:
        raise RollupError("ROOT126 native row count is not 153")
    expect(sidecar.get("schema"), "ds02.stage2.f2.coarse-active-stream-result-sidecar.v2", "ROOT129 schema")
    expect(sidecar.get("case_key"), case_key, "ROOT129 case key")
    product = sidecar.get("product")
    if not isinstance(product, dict):
        raise RollupError("ROOT129 product is missing")
    expect(product.get("status"), "V8_STREAM_SOURCE_CLOSED_UNKNOWN_MASS_SCREEN_FAIL", "ROOT129 product status")
    q_unknown(product.get("qualification"), "ROOT129 qualification")
    return {
        "case_key": case_key,
        "physical_case_id": physical_case_id,
        "family_id": "F2",
        "native_ids": 153,
        "source": {
            "root126_report": stat_ref(paths["root126_report"], "ROOT126 active stream report"),
            "root129_report": stat_ref(paths["root129_report"], "ROOT129 stream sidecar"),
        },
        "merged_into_original_catalog": False,
        "catalog_overlap_checked_forms": sorted(forms),
        "reason": "ROOT126/129 case key is a new coarse canary recipe absent from CURRENT336/v29 and must not be added to the original 1328 native omission total",
        "native_cause": "NUMERICAL_POSITION_STREAM_SCOPE",
        "mass_screen": "FAIL_OVER_FROZEN_XML_WHOLE_INITIAL_0P003",
        "physical_fate": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN",
        "dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }


def validate_f3(products: dict[str, dict[str, Any]], paths: dict[str, Path]) -> dict[str, Any]:
    report = products["f3_report"]
    proof = products["f3_proof"]
    receipt = products["f3_receipt"]
    expect(report.get("schema"), "ds02.stage2.f3.s2.initial-support-audit.v6", "ROOT128 report schema")
    expect(report.get("status"), "COMPLETED_F3_S2_INITIAL_SUPPORT_AUDIT_V6", "ROOT128 report status")
    expect(report.get("family_id"), "F3", "ROOT128 family")
    expect(proof.get("status"), "VERIFIED_ACTUAL_F3_DP015_SUPPORT_V6_BOUNDED_INITIAL_DIAGNOSTIC", "ROOT128 proof status")
    proof_binding(proof, "report", paths["f3_report"], "ROOT128 proof")
    proof_hash_binding(proof, "report_sha256", paths["f3_report"], "ROOT128 proof")
    proof_binding(proof, "receipt", paths["f3_receipt"], "ROOT128 proof")
    proof_hash_binding(proof, "receipt_sha256", paths["f3_receipt"], "ROOT128 proof")
    if "f3_request" in paths:
        proof_binding(proof, "request", paths["f3_request"], "ROOT128 proof")
        proof_hash_binding(proof, "request_sha256", paths["f3_request"], "ROOT128 proof")
    validate_receipt(receipt, "ROOT128 receipt")
    scope = report.get("scope")
    if not isinstance(scope, dict) or scope.get("solver_started") is not False or scope.get("hdf5_read") is not False:
        raise RollupError("ROOT128 scope does not preserve no-solver/no-HDF5 contract")
    q_unknown(report.get("qualification"), "ROOT128 qualification")
    generated = report.get("generated")
    mass = report.get("mass_audit")
    if not isinstance(generated, dict) or not isinstance(mass, dict):
        raise RollupError("ROOT128 generated/mass audit is missing")
    expect(generated.get("fluid_count"), 4320, "ROOT128 fluid count")
    expect(generated.get("sample_mass_kg"), 14.58, "ROOT128 sample mass")
    expect(mass.get("continuous_mass_qualification"), "UNKNOWN", "ROOT128 continuous mass qualification")
    expect(mass.get("mass_rescale"), False, "ROOT128 mass rescale")
    return {
        "source": {
            "report": stat_ref(paths["f3_report"], "ROOT128 F3 support report"),
            "proof": stat_ref(paths["f3_proof"], "ROOT128 verification proof"),
            "receipt": stat_ref(paths["f3_receipt"], "ROOT128 execution receipt"),
        },
        "family_id": "F3",
        "physical_case_id": report["physical_case_id"],
        "sentinel_id": report.get("sentinel_id"),
        "initial_support": {
            "dp_m": finite(generated.get("dp_m"), "ROOT128 dp"),
            "fluid_count": generated["fluid_count"],
            "fixed_or_bound_count": generated["fixed_or_bound_count"],
            "sample_mass_kg": finite(generated.get("sample_mass_kg"), "ROOT128 sample mass"),
            "continuous_owner_mass_kg": finite(mass.get("continuous_owner_mass_kg"), "ROOT128 owner mass"),
            "discrete_sample_gate": mass.get("discrete_sample_gate"),
            "continuous_mass_qualification": "UNKNOWN",
        },
        "task_eligibility": {
            "initial_source_bound_id_axis_support": "ELIGIBLE_INITIAL_BOOKKEEPING_DIAGNOSTIC",
            "continuous_owner_equivalence": "UNKNOWN",
            "no_penetration": "UNKNOWN",
            "flux_or_fate": "UNKNOWN",
            "solver_accuracy": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "scientific_q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
    }


def validate_f5(products: dict[str, dict[str, Any]], paths: dict[str, Path]) -> dict[str, Any]:
    proof = products["f5_proof"]
    receipt = products["f5_receipt"]
    expect(proof.get("schema"), "ds02.stage2.root-actual-verification.v1", "ROOT123 proof schema")
    expect(proof.get("status"), "VERIFIED_ACTUAL_F5_YZERO_INITIAL_MASS_HARDFAIL_GEOMETRY_PENDING", "ROOT123 proof status")
    proof_binding(proof, "receipt", paths["f5_receipt"], "ROOT123 proof")
    proof_hash_binding(proof, "receipt_sha256", paths["f5_receipt"], "ROOT123 proof")
    if "f5_request" in paths:
        proof_binding(proof, "request", paths["f5_request"], "ROOT123 proof")
        proof_hash_binding(proof, "request_sha256", paths["f5_request"], "ROOT123 proof")
    validate_receipt(receipt, "ROOT123 receipt")
    expect(proof.get("mass_gate"), "HARDFAIL_OVER_TWO_PERCENT", "ROOT123 mass gate")
    expect(proof.get("mass_rescale"), False, "ROOT123 mass rescale")
    error = finite(proof.get("relative_mass_error"), "ROOT123 relative mass error")
    if not error < -0.02:
        raise RollupError("ROOT123 hard-fail error no longer exceeds 2 percent")
    expect(proof.get("root_array_read_or_hash"), False, "ROOT123 array read")
    expect(proof.get("solver_started"), False, "ROOT123 solver started")
    q_unknown(proof.get("scientific_qualification"), "ROOT123 qualification")
    return {
        "source": {
            "proof": stat_ref(paths["f5_proof"], "ROOT123 verification proof"),
            "receipt": stat_ref(paths["f5_receipt"], "ROOT123 execution receipt"),
        },
        "family_id": "F5",
        "recipe": "F5_S1_CLIPPLANE_YZERO_DP005_GENCASE_ROOT_123",
        "initial_counts": {
            "fluid": proof.get("actual_fluid_count"),
            "fixed": proof.get("actual_fixed_count"),
            "moving": proof.get("actual_moving_count"),
            "total": proof.get("actual_total_count"),
        },
        "mass": {
            "massfluid_kg": finite(proof.get("actual_massfluid_kg"), "ROOT123 MassFluid"),
            "sample_initial_mass_kg": finite(proof.get("sample_initial_mass_kg"), "ROOT123 sample mass"),
            "continuous_owner_mass_kg": finite(proof.get("continuous_owner_mass_kg"), "ROOT123 owner mass"),
            "relative_mass_error": error,
            "gate": "HARDFAIL_OVER_TWO_PERCENT",
            "mass_rescale": False,
        },
        "geometry": {
            "status": proof.get("geometry_gate"),
            "global_shapes_pending": True,
        },
        "task_eligibility": {
            "initial_count_and_sample_mass": "ELIGIBLE_HARDFAIL_RECORD_ONLY",
            "support": "UNKNOWN_PENDING_GEOMETRY",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "scientific_q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN"},
    }


def validate_catalogs(products: dict[str, dict[str, Any]], paths: dict[str, Path]) -> tuple[dict[str, Any], set[str], set[str]]:
    v27 = products["v27_product"]
    v29 = products["v29_catalog"]
    v30 = products["v30_catalog"]
    expect(v27.get("schema"), "ds02.stage2.final-family-product.v27", "v27 schema")
    expect(v29.get("schema"), "ds02.stage2.final-qualification-catalog.v29", "v29 schema")
    expect(v30.get("schema"), "ds02.stage2.task-scope-catalog.v30", "v30 schema")
    expect(v27.get("coverage", {}).get("current_case_count"), 336, "v27 current count")
    expect(v29.get("coverage", {}).get("current_cases"), 336, "v29 current count")
    expect(v30.get("coverage", {}).get("current_cases"), 336, "v30 current count")
    expect(v27.get("coverage", {}).get("native_alias_cases"), 118, "v27 native case count")
    expect(v27.get("coverage", {}).get("native_alias_ids"), 1328, "v27 native id count")
    expect(v29.get("coverage", {}).get("native_impact_cases"), 118, "v29 native impact count")
    expect(v30.get("coverage", {}).get("native_motive_id_cases"), 118, "v30 native motive count")
    expect(v27.get("coverage", {}).get("family_counts"), {f"F{i}": 48 for i in range(1, 8)}, "v27 family counts")
    cards = v27.get("family_cards")
    if not isinstance(cards, dict) or set(cards) != {f"F{i}" for i in range(1, 8)}:
        raise RollupError("v27 does not expose exactly seven family cards")
    for family, card in cards.items():
        if not isinstance(card, dict):
            raise RollupError(f"v27 {family} card is malformed")
        expect(card.get("family_id"), family, f"v27 {family} family")
        q_unknown(card.get("task_eligibility"), f"v27 {family} qualification")
    q_unknown(v27.get("claim_boundary"), "v27 claim boundary")
    q_unknown(v29.get("claim_boundary"), "v29 claim boundary")
    q_unknown(v30.get("claim_boundary"), "v30 claim boundary")
    q_unknown(v29.get("scientific_qualification"), "v29 scientific qualification")
    q_unknown(v30.get("task_qualification"), "v30 task qualification")
    quality_stat: dict[str, Any] | None = None
    if "quality_proof" in products:
        quality = products["quality_proof"]
        expect(quality.get("schema"), "ds02.stage2.root-actual-verification.v1", "seven-family quality proof schema")
        expect(quality.get("status"), "PASS_ACTUAL_SEVEN_FAMILY_QUALITY_STRICT_PRODUCER_BOUND", "seven-family quality proof status")
        q_unknown(quality.get("scientific_qualification"), "seven-family quality proof qualification")
        if quality.get("H5_BI4_read_by_root") is True or quality.get("original_trajectory_H5_BI4_or_label_H5_reopened") is True:
            raise RollupError("seven-family quality proof reports forbidden scientific payload access")
        quality_stat = stat_ref(paths["quality_proof"], "seven-family strict quality proof")
    case_inventory = v27.get("case_inventory")
    if not isinstance(case_inventory, list) or len(case_inventory) != 336:
        raise RollupError("v27 case inventory is not exactly 336 rows")
    case_keys: set[str] = set()
    physical_ids: set[str] = set()
    for row in case_inventory:
        if not isinstance(row, dict):
            raise RollupError("v27 case inventory contains a malformed row")
        if isinstance(row.get("physical_case_id"), str):
            physical_ids.add(row["physical_case_id"])
        if isinstance(row.get("family_id"), str) and isinstance(row.get("physical_case_id"), str):
            case_keys.add(f"{row['family_id']}/{row['physical_case_id']}")
    v29_case_rows = v29.get("cases")
    v30_case_rows = v30.get("cases")
    if not isinstance(v29_case_rows, list) or len(v29_case_rows) != 336 or not isinstance(v30_case_rows, list) or len(v30_case_rows) != 336:
        raise RollupError("v29/v30 case inventory is not exactly 336 rows")
    for row in v29_case_rows:
        if isinstance(row, dict) and isinstance(row.get("case_key"), str):
            case_keys.add(row["case_key"])
    return {
        "v27": stat_ref(paths["v27_product"], "v27 seven-family product"),
        "v29": stat_ref(paths["v29_catalog"], "v29 qualification catalog"),
        "v30": stat_ref(paths["v30_catalog"], "v30 task-scope catalog"),
        "coverage": {
            "current_cases": 336,
            "family_cards": 7,
            "family_counts": {f"F{i}": 48 for i in range(1, 8)},
            "native_alias_cases": 118,
            "native_alias_ids": 1328,
            "all_q_unknown": True,
        },
        "authoritative_products_unchanged": True,
        "quality_proof": quality_stat,
    }, case_keys, physical_ids


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest, paths, products = load_manifest(manifest_path)
    catalog, catalog_case_keys, catalog_physical_ids = validate_catalogs(products, paths)
    f2 = validate_root134(products, paths)
    new_reference = validate_root126_new_case(products, paths, catalog_case_keys, catalog_physical_ids)
    f3 = validate_f3(products, paths)
    f5 = validate_f5(products, paths)
    return {
        "schema": SCHEMA,
        "status": "PREPARED_OVERALL_TASK_ROLLUP_V1_ROOT134_ROOT128_ROOT123_NO_SCIENTIFIC_QUALIFICATION",
        "purpose": "Forward-only JSON rollup of task eligibility and preserved scientific unknowns; original 336 catalog remains authoritative.",
        "source_manifest": stat_ref(manifest_path, "overall task rollup manifest"),
        "catalog_scope": catalog,
        "new_reference_scope": new_reference,
        "actual_evidence": {
            "f2_root134": f2,
            "f3_root128": f3,
            "f5_root123": f5,
        },
        "task_eligibility_vs_scientific_q": {
            "F2": f2["task_eligibility"],
            "F3": f3["task_eligibility"],
            "F5": f5["task_eligibility"],
        },
        "failure_and_censoring": {
            "original_catalog_native_identity_count": 1328,
            "original_catalog_native_case_count": 118,
            "root126_new_reference_native_identity_count": 153,
            "root126_new_reference_merged_into_original_catalog": False,
            "f2_unknown_fraction_screen": 0.005513513601786032,
            "f2_frozen_unknown_fraction_max": 0.003,
            "f5_mass_gate": "HARDFAIL_OVER_TWO_PERCENT",
            "f3_continuous_owner_equivalence": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "source_access": {
            "json_only": True,
            "h5_opened": False,
            "bi4_opened": False,
            "partout_opened": False,
            "vtk_opened": False,
            "raw_solver_output_opened": False,
            "solver_started": False,
            "old_products_modified": False,
        },
        "claim_boundary": {
            "task_inventory_and_source_identity": "ELIGIBLE_WITHIN_EXPLICIT_SOURCE_SCOPES",
            "saved_frame_or_initial_bookkeeping": "LIMITED_DIAGNOSTIC_SCOPE_ONLY",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "wall_contact": "UNKNOWN",
            "continuous_events": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "old_products_unchanged": True,
        "manifest_contract": manifest.get("contract"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = derive(args.manifest.expanduser().resolve())
        atomic_json(args.output, result)
    except RollupError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
