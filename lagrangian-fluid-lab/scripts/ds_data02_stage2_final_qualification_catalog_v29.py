#!/usr/bin/env python3
"""Assemble the bounded per-case Stage2 qualification catalog (v29).

The v27 product is a source-closed metadata inventory.  This forward-only
assembler adds the already completed scientific audit for all 336 CURRENT
cases, the source-bound native cause and mass/censoring ledgers for the exact
118 F2/F4/F6 omission cases, and the strict seven-family quality scope.  It
does not open trajectory H5, label H5, BI4, raw solver output, or any source
payload referenced by those reports.  It copies only JSON fields and declared
provenance references.

The catalog is deliberately a qualification boundary.  QN, QE, QI, physical
fate, legal flux, continuous event truth, recovery transfer, effective split
safety, and dynamical error remain UNKNOWN.  A saved frame, a native motive,
or a source-visible mass lower bound is not promoted to any of those claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FAMILIES = [f"F{i}" for i in range(1, 8)]
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".bi2", ".bi1"}
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
V27_SCHEMA = "ds02.stage2.final-family-product.v27"
AUDIT_SCHEMA = "ds02.stage2.scientific-audit-independent-verification.v23"
IMPACT_SCHEMA = "ds02.stage2.omission-impact-ledger.v2"
MECHANISM_SCHEMA = "ds02.stage2.omission-mechanism-probe.v3"
QUALITY_SCHEMA = "ds02.stage2.family-label-quality-evaluator.v2-strict"
PRODUCT_SCHEMA = "ds02.stage2.final-qualification-catalog.v29"
MANIFEST_SCHEMA = "ds02.stage2.final-qualification-catalog-manifest.v29"
REQUEST_SCHEMA = "ds02.stage2.final-qualification-catalog-v29-request.v1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class CatalogError(RuntimeError):
    """Raised when an evidence identity or qualification boundary is open."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=SCRIPT.parents[2],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _path(value: Path | str, label: str, *, output: bool = False) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise CatalogError(f"{label} must be an absolute path: {path}")
    if not output and path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise CatalogError(f"{label} is a forbidden scientific payload: {path}")
    if not output and not path.is_file():
        raise CatalogError(f"{label} is missing: {path}")
    return path


def _json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = _path(value, label)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(data, dict):
        raise CatalogError(f"{label} must be a JSON object: {path}")
    return path, data


def _ref(path: Path, role: str) -> dict[str, Any]:
    return {"role": role, "path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise CatalogError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _require_declared_sha(path: Path, declared: Any, label: str) -> str:
    expected = _require_digest(declared, label)
    actual = sha256_file(path)
    if expected != actual:
        raise CatalogError(f"{label} digest mismatch: declared {expected}, actual {actual}")
    return actual


def _require_exact_path(actual: Any, expected: Path, label: str) -> None:
    if actual != str(expected):
        raise CatalogError(f"{label} does not bind the exact path: {actual!r} != {str(expected)!r}")


def _key(row: dict[str, Any]) -> tuple[str, str]:
    family, physical = row.get("family_id"), row.get("physical_case_id")
    if not isinstance(family, str) or not isinstance(physical, str):
        raise CatalogError(f"row lacks a valid family/physical identity: {row!r}")
    return family, physical


def _validate_current(current_path: Path, current: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], tuple[int, dict[str, Any]]]]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise CatalogError("CURRENT336 schema is not current336.v1")
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise CatalogError("CURRENT336 must contain exactly 336 cases")
    by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}
    counts = {family: 0 for family in FAMILIES}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CatalogError(f"CURRENT336 row {index} is not an object")
        family, physical = _key(row)
        if family not in FAMILIES or (family, physical) in by_key:
            raise CatalogError(f"CURRENT336 identity is invalid at index {index}")
        window = row.get("actual_time_window_s")
        if not isinstance(window, list) or len(window) != 2 or not all(isinstance(x, (int, float)) for x in window):
            raise CatalogError(f"CURRENT336 row {index} lacks an exact saved time window")
        if not isinstance(row.get("frames"), int) or row["frames"] <= 0:
            raise CatalogError(f"CURRENT336 row {index} lacks a positive frame count")
        counts[family] += 1
        by_key[(family, physical)] = (index, row)
    if counts != {family: 48 for family in FAMILIES}:
        raise CatalogError(f"CURRENT336 family counts are not 48 each: {counts}")
    return rows, by_key


def _validate_v27(
    current_path: Path,
    product_path: Path,
    product: dict[str, Any],
    manifest_path: Path,
    manifest: dict[str, Any],
    request_path: Path,
    request: dict[str, Any],
    proof_path: Path,
    proof: dict[str, Any],
    receipt_path: Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    if product.get("schema") != V27_SCHEMA:
        raise CatalogError("v27 product schema is not final-family-product.v27")
    coverage = product.get("coverage") or {}
    if coverage.get("current_case_count") != 336 or coverage.get("hidden_current_cases") != 0 or coverage.get("native_alias_cases") != 118:
        raise CatalogError("v27 product coverage is incomplete")
    inventory = product.get("case_inventory")
    if not isinstance(inventory, list) or len(inventory) != 336:
        raise CatalogError("v27 product does not expose all 336 cases")
    for item in inventory:
        if any(item.get(key) != "UNKNOWN" for key in ("QN", "QE", "QI", "physical_fate", "dynamical_impact")):
            raise CatalogError("v27 product grants unsupported scientific qualification")
    if product.get("read_policy", {}).get("original_trajectory_h5_opened_by_this_worker") is not False:
        raise CatalogError("v27 product read policy does not close trajectory H5")
    manifest_ref = (product.get("inputs") or {}).get("manifest") or {}
    _require_exact_path(manifest_ref.get("path"), manifest_path, "v27 product manifest")
    _require_declared_sha(manifest_path, manifest_ref.get("sha256"), "v27 product manifest")
    if manifest.get("schema") != "ds02.stage2.final-family-product-manifest.v27":
        raise CatalogError("v27 manifest schema is unexpected")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith("PASS_ACTUAL"):
        raise CatalogError("v27 proof is not an actual producer proof")
    if proof.get("H5_BI4_read_by_root") is not False:
        raise CatalogError("v27 proof does not close H5/BI4 scope")
    q = proof.get("scientific_qualification") or proof.get("qualification") or {}
    if any(q.get(key) not in (None, "UNKNOWN") for key in ("QN", "QE", "QI")):
        raise CatalogError("v27 proof grants qualification")
    _require_exact_path(proof.get("report"), product_path, "v27 proof product")
    _require_exact_path(proof.get("receipt"), receipt_path, "v27 proof receipt")
    _require_declared_sha(product_path, proof.get("report_sha256"), "v27 proof product")
    _require_declared_sha(receipt_path, proof.get("receipt_sha256"), "v27 proof receipt")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise CatalogError("v27 receipt is not completed")
    if receipt.get("output_root") and Path(receipt["output_root"]) != product_path.parent:
        raise CatalogError("v27 receipt output_root differs from product parent")
    producer_current = ((product.get("actual_v25") or {}).get("producer_current") or {})
    _require_exact_path(producer_current.get("path"), current_path, "v27 producer CURRENT")
    current_sha = sha256_file(current_path)
    if producer_current.get("sha256") != current_sha:
        raise CatalogError("v27 producer CURRENT digest differs")
    proof_request = proof.get("request")
    if proof_request is not None:
        _require_exact_path(proof_request, request_path, "v27 proof request")
    if proof.get("request_sha256") is not None:
        _require_declared_sha(request_path, proof.get("request_sha256"), "v27 proof request")
    if request.get("request_schema") != "ds02.stage2.final-family-product-v27-request.v1":
        raise CatalogError("v27 request schema is unexpected")
    return {
        "product": _ref(product_path, "actual v27 product"),
        "manifest": _ref(manifest_path, "actual v27 manifest"),
        "request": _ref(request_path, "actual v27 request"),
        "proof": _ref(proof_path, "actual v27 proof"),
        "receipt": _ref(receipt_path, "actual v27 receipt"),
        "producer_current": {"path": str(current_path), "sha256": current_sha},
        "qualification": copy_json(q),
    }


def _validate_scientific_audit(
    audit_path: Path,
    audit: dict[str, Any],
    by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]],
    current_sha: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    if audit.get("schema") != AUDIT_SCHEMA or audit.get("distinct_completed_cases") != 336:
        raise CatalogError("scientific audit is not the completed v23 336-case audit")
    if audit.get("by_family") != {family: 48 for family in FAMILIES}:
        raise CatalogError("scientific audit family counts are incomplete")
    rows = audit.get("verified_cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise CatalogError("scientific audit does not contain 336 verified cases")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CatalogError(f"scientific audit row {index} is not an object")
        key = _key(row)
        if key not in by_key or key in result:
            raise CatalogError(f"scientific audit identity is not exact CURRENT336 at row {index}")
        if row.get("scan_status") != "SCANNED" or row.get("exact_CURRENT_path_and_declared_sha_match") is not True:
            raise CatalogError(f"scientific audit row {index} is not a completed exact CURRENT scan")
        if row.get("frames") != by_key[key][1].get("frames"):
            raise CatalogError(f"scientific audit frame count differs for {key}")
        failures = row.get("field_failures")
        if not isinstance(failures, list):
            raise CatalogError(f"scientific audit field_failures is malformed for {key}")
        for qkey in ("QN", "QE", "QI_dynamics"):
            if row.get(qkey) not in ("NOT_ASSESSED", "UNKNOWN"):
                raise CatalogError(f"scientific audit grants {qkey} for {key}")
        for path_key, sha_key in (("trajectory", "trajectory_verified_sha256"), ("scan", "scan_sha256"), ("receipt", "receipt_sha256")):
            if not isinstance(row.get(path_key), str) or not row[path_key].startswith("/"):
                raise CatalogError(f"scientific audit {path_key} provenance is malformed for {key}")
            _require_digest(row.get(sha_key), f"scientific audit {path_key} digest")
        if "current_case_index" in row and row["current_case_index"] != by_key[key][0]:
            raise CatalogError(f"scientific audit current index differs for {key}")
        # This report's current_catalog may be a byte-equivalent audit catalog
        # alias.  Exact producer CURRENT identity is checked through v27 and
        # the per-row exact_CURRENT flag; only the digest is required here.
        result[key] = copy_json(row)
    if set(result) != set(by_key):
        raise CatalogError("scientific audit key set differs from CURRENT336")
    current_catalog = audit.get("current_catalog") or {}
    if current_catalog.get("sha256") != current_sha:
        raise CatalogError("scientific audit current catalog digest differs")
    return result


def _validate_ledger_report(
    report_path: Path,
    report: dict[str, Any],
    proof_path: Path | None,
    proof: dict[str, Any] | None,
    receipt_path: Path,
    receipt: dict[str, Any],
    schema: str,
    expected_count: int,
    current_sha: str,
    by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]],
) -> dict[tuple[str, str], dict[str, Any]]:
    if report.get("schema") != schema:
        raise CatalogError(f"ledger {report_path} has unexpected schema")
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise CatalogError(f"ledger {report_path} has {len(cases) if isinstance(cases, list) else 'invalid'} cases, expected {expected_count}")
    if report.get("read_policy", {}).get("h5_opened") not in (False, None) or report.get("read_policy", {}).get("trajectory_content_opened") not in (False, None):
        raise CatalogError(f"ledger {report_path} does not close H5 content scope")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cases:
        if not isinstance(row, dict):
            raise CatalogError(f"ledger {report_path} has a non-object case")
        key = _key(row)
        if key not in by_key or key in result:
            raise CatalogError(f"ledger {report_path} identity is not exact CURRENT/native union: {key}")
        for qkey in ("QN", "QE"):
            if row.get(qkey) not in ("NOT_ASSESSED", "UNKNOWN"):
                raise CatalogError(f"ledger {key} grants {qkey}")
        if row.get("physical_fate") not in ("UNKNOWN", "UNKNOWN_NOT_PROVEN") or row.get("dynamical_impact") not in ("UNKNOWN", "UNKNOWN_NOT_PROVEN"):
            raise CatalogError(f"ledger {key} grants physical/dynamical qualification")
        source = row.get("source_closure") or {}
        if source.get("status") not in {"FULL_PROBE_SOURCE_CLOSED", "FULL_NATIVE_SOURCE_CLOSED", "V2_NATIVE_SOURCE_CLOSED", "EXACT_NATIVE_SOURCE_CLOSED"}:
            raise CatalogError(f"ledger {key} lacks source-closure status")
        if "current_identity" in report and report["current_identity"].get("sha256") != current_sha:
            raise CatalogError("mechanism current identity differs")
        result[key] = copy_json(row)
    if report.get("coverage", {}).get("case_count") not in (None, expected_count):
        raise CatalogError(f"ledger {report_path} coverage count differs")
    if proof is not None:
        if proof.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.all118-impact-v8-independent-verification.v1", "ds02.stage2.all118-mechanism-v3-actual-independent.v1"}:
            raise CatalogError(f"ledger proof schema is unexpected: {proof_path}")
        if not str(proof.get("status", "")).startswith("PASS"):
            raise CatalogError(f"ledger proof is not PASS: {proof_path}")
        proof_output = proof.get("output")
        proof_output_path = proof_output.get("path") if isinstance(proof_output, dict) else proof_output
        proof_output_sha = proof_output.get("sha256") if isinstance(proof_output, dict) else proof.get("output_sha256")
        if proof_output_path not in (None, str(report_path)):
            raise CatalogError(f"ledger proof output path differs: {proof_path}")
        if proof_output_sha is not None:
            _require_declared_sha(report_path, proof_output_sha, f"ledger proof output {report_path}")
        proof_receipt = proof.get("receipt")
        proof_receipt_path = proof_receipt.get("path") if isinstance(proof_receipt, dict) else proof_receipt
        proof_receipt_sha = proof_receipt.get("sha256") if isinstance(proof_receipt, dict) else proof.get("receipt_sha256")
        if proof_receipt_path not in (None, str(receipt_path)):
            raise CatalogError(f"ledger proof receipt path differs: {proof_path}")
        if proof_receipt_sha is not None:
            _require_declared_sha(receipt_path, proof_receipt_sha, f"ledger proof receipt {receipt_path}")
        qualification = proof.get("scientific_qualification") or {}
        if any(qualification.get(key) not in (None, "UNKNOWN") for key in ("QN", "QE", "QI")):
            raise CatalogError(f"ledger proof grants qualification: {proof_path}")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise CatalogError(f"ledger receipt is not completed: {receipt_path}")
    if receipt.get("output_root") and Path(receipt["output_root"]) != report_path.parent:
        raise CatalogError(f"ledger receipt output_root differs: {receipt_path}")
    return result


def _validate_quality(
    quality_path: Path,
    quality: dict[str, Any],
    proof_path: Path,
    proof: dict[str, Any],
    receipt_path: Path,
    receipt: dict[str, Any],
    by_key: dict[tuple[str, str], tuple[int, dict[str, Any]]],
) -> dict[tuple[str, str], dict[str, Any]]:
    if quality.get("schema") != QUALITY_SCHEMA or quality.get("status") != "PASS_SEVEN_FAMILY_TASK_SCOPE_STRICT_PRODUCER_BOUND_NO_QUALIFICATION":
        raise CatalogError("strict quality report is not the completed producer-bound report")
    cards = quality.get("family_cards")
    if quality.get("family_count") != 7 or not isinstance(cards, list) or len(cards) != 7:
        raise CatalogError("strict quality report does not contain seven cards")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for card in cards:
        if not isinstance(card, dict):
            raise CatalogError("strict quality card is not an object")
        key = _key(card)
        if key not in by_key or key in result or card.get("quality_checks_closed") is not True:
            raise CatalogError(f"strict quality card is not an exact closed CURRENT anchor: {key}")
        eligibility = card.get("task_eligibility") or {}
        if any(eligibility.get(name) not in ("UNKNOWN", "ELIGIBLE_DEVELOPMENT_AUDIT", "ELIGIBLE_LIMITED_DEVELOPMENT") for name in ("QN", "QE", "QI", "physical_fate", "dynamical_impact")):
            raise CatalogError(f"strict quality card grants unsupported scope: {key}")
        result[key] = copy_json(card)
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or proof.get("status") != "PASS_ACTUAL_SEVEN_FAMILY_QUALITY_STRICT_PRODUCER_BOUND":
        raise CatalogError("strict quality proof is not the completed proof")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("original_trajectory_H5_BI4_or_label_H5_reopened") is not False:
        raise CatalogError("strict quality proof has an open read policy")
    _require_exact_path(proof.get("report"), quality_path, "strict quality proof report")
    _require_declared_sha(quality_path, proof.get("report_sha256"), "strict quality proof report")
    _require_exact_path(proof.get("receipt"), receipt_path, "strict quality proof receipt")
    _require_declared_sha(receipt_path, proof.get("receipt_sha256"), "strict quality proof receipt")
    q = proof.get("scientific_qualification") or {}
    if any(q.get(name) not in (None, "UNKNOWN") for name in ("QN", "QE", "QI")):
        raise CatalogError("strict quality proof grants qualification")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") not in (None, 0):
        raise CatalogError("strict quality receipt is not completed")
    if receipt.get("output_root") and Path(receipt["output_root"]) != quality_path.parent:
        raise CatalogError("strict quality receipt output_root differs")
    return result


def _audit_mass(audit: dict[str, Any]) -> tuple[float | None, int | None, int | None]:
    if isinstance(audit.get("fluid_initial_mass_kg"), (int, float)):
        mass = float(audit["fluid_initial_mass_kg"])
        initial_absent = audit.get("fluid_initially_absent_count")
        missing = audit.get("fluid_cumulative_unique_missing")
    else:
        ledger = audit.get("fluid_ledger") or {}
        mass = ledger.get("typed_initial_mass_kg") if isinstance(ledger.get("typed_initial_mass_kg"), (int, float)) else None
        initial_absent = ledger.get("initially_absent_count")
        missing = ledger.get("cumulative_unique_missing")
    return mass, initial_absent if isinstance(initial_absent, int) else None, missing if isinstance(missing, int) else None


def _source_binding_metadata(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role, item in sorted((row.get("source_bindings") or {}).items()):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        # These are CURRENT declarations.  This worker intentionally does not
        # open or rehash the referenced payloads; their exact producer hashes
        # remain in the bound CURRENT/audit reports.
        result[role] = {
            "path": item["path"],
            "declared_sha256": item.get("sha256") or item.get("recomputed_sha256"),
            "accessible_declared": item.get("accessible"),
            "content_opened_by_this_worker": False,
        }
    return result


def _native_summary(impact: dict[str, Any], mechanism: dict[str, Any]) -> dict[str, Any]:
    cause = copy_json(impact.get("native_numerical_cause") or {})
    gate = copy_json(mechanism.get("native_gate") or {})
    if cause.get("motive") != gate.get("motive") or cause.get("native_count") != gate.get("native_count"):
        raise CatalogError(f"native cause/mechanism mismatch for {impact.get('case_key')}")
    mass = impact.get("mass_impact") or {}
    censor = impact.get("censoring") or {}
    observations = mechanism.get("particle_observations")
    saved = mechanism.get("saved_record_impacts")
    return {
        "case_key": impact.get("case_key"),
        "native_motive": cause.get("motive"),
        "native_count": cause.get("native_count"),
        "native_exit_cause_counts": copy_json(cause.get("exit_cause_counts") or {}),
        "runparts_totals": copy_json((gate.get("runparts_totals") or {})),
        "source_closure": copy_json(impact.get("source_closure") or mechanism.get("source_closure") or {}),
        "source_visible_mass": {
            "initial_fluid_mass_denominator_kg": mass.get("initial_fluid_mass_denominator_kg"),
            "missing_source_visible_mass_lower_bound_kg": mass.get("source_visible_missing_mass_lower_bound_kg"),
            "missing_source_visible_fraction_lower_bound": mass.get("source_visible_missing_fraction_lower_bound"),
            "screen": mass.get("screen"),
            "screen_gate_fraction": mass.get("screen_gate_fraction"),
            "source_mk_partition": copy_json(mass.get("source_mk_partition") or {}),
            "interpretation": mass.get("claim_boundary", "source-visible lower bound only; not physical outflow or bounded dynamical error"),
        },
        "saved_censoring": {
            "first_missing_window_s": copy_json(impact.get("first_missing_window_s") or (impact.get("censoring") or {}).get("first_missing_window_s") or mechanism.get("first_missing_window_s")),
            "particle_observation_count": len(observations) if isinstance(observations, list) else None,
            "saved_record_impact_count": len(saved) if isinstance(saved, list) else None,
            "event_time_semantics": "saved-record bracket only; exact physical event time UNKNOWN",
            "cross_time_system_aggregation": "forbidden",
        },
        "endpoint_diagnostics": {
            "density_gate_observation": copy_json(mechanism.get("density_gate_observation") or {}),
            "printed_final_bounds_observation": copy_json(mechanism.get("printed_final_bounds_observation") or {}),
            "endpoint_predicates_are_causes": False,
        },
        "physical_fate": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
        "dynamical_impact": "UNKNOWN",
        "conversion_omission": copy_json((impact.get("conversion_omission") or {}).get("converter_source_closure", "UNKNOWN")),
        "source_report_roles": {
            "impact_v8": "mass/censoring/source closure",
            "mechanism_v3": "native motive/endpoint diagnostic and saved-record semantics",
        },
    }


def _case_record(
    index: int,
    current: dict[str, Any],
    audit: dict[str, Any],
    impact: dict[str, Any] | None,
    mechanism: dict[str, Any] | None,
    quality: dict[str, Any] | None,
    v27_card: dict[str, Any] | None,
) -> dict[str, Any]:
    key = _key(current)
    mass, initial_absent, missing = _audit_mass(audit)
    native = _native_summary(impact, mechanism) if impact is not None and mechanism is not None else None
    field_failures = copy_json(audit.get("field_failures") or [])
    finite = {
        "audit_status": "SCIENTIFIC_AUDIT_FIELD_FAILURES_EMPTY" if not field_failures else "SCIENTIFIC_AUDIT_FIELD_FAILURES_PRESENT",
        "field_failures": field_failures,
        "fluid_initially_absent_count": initial_absent,
        "fluid_cumulative_unique_missing": missing,
        "active_finite_lifecycle_fields": copy_json((audit.get("fluid_ledger") or {}).get("active_nonfinite")) if isinstance(audit.get("fluid_ledger"), dict) else "NOT_EXPOSED_IN_THIS_AUDIT_ROW",
        "credit": "finite/identity audit scope only; no QN/QE/QI or dynamics credit",
    }
    if native:
        time_scope = {
            "current_saved_window_s": copy_json(current.get("actual_time_window_s")),
            "frames": current.get("frames"),
            "first_missing_window_s": copy_json(native["saved_censoring"].get("first_missing_window_s")),
            "event_time": "UNKNOWN; saved-record bracket only",
        }
        censor_scope = {
            "status": "SOURCE_BOUND_NATIVE_SAVED_RECORD_CENSORING",
            "first_missing_window_s": copy_json(native["saved_censoring"].get("first_missing_window_s")),
            "hidden_continuous_crossings": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
            "physical_destination": "UNKNOWN",
        }
        id_scope = {
            "current_identity": "EXACT_CURRENT336_CASE",
            "native_identity": "NATIVE_ID_MOTIVE_SOURCE_CLOSED",
            "identity_key": "(Zone,Idp)",
            "native_count": native.get("native_count"),
        }
        mass_scope = native["source_visible_mass"]
    else:
        time_scope = {"current_saved_window_s": copy_json(current.get("actual_time_window_s")), "frames": current.get("frames"), "event_time": "UNKNOWN"}
        censor_scope = {
            "status": "NO_NATIVE_118_CENSOR_RECORD_FOR_THIS_CASE",
            "scan_missing_count": missing,
            "hidden_continuous_crossings": "UNKNOWN",
            "hidden_recrossings": "UNKNOWN",
            "physical_destination": "UNKNOWN",
        }
        id_scope = {"current_identity": "EXACT_CURRENT336_CASE", "native_identity": "NOT_IN_118_NATIVE_LEDGER", "identity_key": "CURRENT metadata identity only"}
        mass_scope = {
            "initial_fluid_mass_kg": mass,
            "scientific_scan_missing_count": missing,
            "source_visible_native_lower_bound": "NOT_COMPUTED_BY_NATIVE_LEDGER_FOR_THIS_CASE",
        }
    return {
        "case_key": f"{key[0]}/{key[1]}",
        "current": {
            "current_index": index,
            "family_id": current.get("family_id"),
            "physical_case_id": current.get("physical_case_id"),
            "runtime_case_alias": current.get("runtime_case_alias"),
            "frames": current.get("frames"),
            "particles": current.get("particles"),
            "actual_time_window_s": copy_json(current.get("actual_time_window_s")),
            "known_numeric_physical_parameters": copy_json(current.get("known_numeric_physical_parameters") or {}),
            "source_bindings": _source_binding_metadata(current),
            "source_role": (v27_card or {}).get("source_role", "CURRENT_DECLARED_SOURCE_ROLE"),
        },
        "scientific_audit": {
            "status": audit.get("scan_status"),
            "frames": audit.get("frames"),
            "trajectory_provenance": {"path": audit.get("trajectory"), "declared_sha256": audit.get("trajectory_verified_sha256"), "content_opened_by_this_worker": False},
            "scan_provenance": {"path": audit.get("scan"), "declared_sha256": audit.get("scan_sha256")},
            "receipt_provenance": {"path": audit.get("receipt"), "declared_sha256": audit.get("receipt_sha256")},
            "exact_current_binding": audit.get("exact_CURRENT_path_and_declared_sha_match"),
            "initial_fluid_mass_kg": mass,
            "missing_counts": {"initially_absent": initial_absent, "cumulative_unique": missing, "final": audit.get("fluid_missing_final_count", (audit.get("fluid_ledger") or {}).get("missing_at_final"))},
            "fluid_ledger": copy_json(audit.get("fluid_ledger")) if isinstance(audit.get("fluid_ledger"), dict) else None,
            "field_failures": field_failures,
        },
        "native_omission": native,
        "quality_scope": copy_json(quality) if quality is not None else {"status": "NOT_EVALUATED_NON_ANCHOR"},
        "qualification_dimensions": {
            "mass": mass_scope,
            "finite_fields": finite,
            "identity": id_scope,
            "time": time_scope,
            "censoring": censor_scope,
            "failed_scope": {
                "scientific_audit_field_failures": field_failures,
                "producer_parent_failure_or_recovery": "UNKNOWN_FOR_NON_ANCHOR" if v27_card is None else copy_json((v27_card.get("raw_reconstruction") or {}).get("full_original_parent_replay_recovered")),
                "error_scope": "metadata/field-audit failure scope only; no numerical solution error bound",
            },
            "error_qualification": {
                "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN",
                "physical_fate": "UNKNOWN", "legal_outflow_or_spill": "UNKNOWN",
                "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN",
                "qualification_credit": "NONE",
            },
        },
        "claim_boundary": {
            "native_motive": "credited only for exact source-bound 118 ledger cases" if native else "not available for this case",
            "mass": "source-visible lower bound only" if native else "scientific scan initial mass/missing count only",
            "saved_time": "saved frame/window metadata; exact physical event time UNKNOWN",
            "finite": "field audit scope only",
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN",
        },
        "read_policy": {
            "current_json_opened": True,
            "scientific_audit_json_opened": True,
            "native_impact_and_mechanism_json_opened": native is not None,
            "trajectory_h5_opened": False,
            "materialized_label_h5_opened": False,
            "part_bi4_opened": False,
            "raw_solver_output_opened": False,
            "solver_started": False,
            "model_invoked": False,
        },
    }


def _load_and_validate(
    current_path: Path,
    product_path: Path,
    product: dict[str, Any],
    manifest_path: Path,
    manifest: dict[str, Any],
    v27_request_path: Path,
    v27_request: dict[str, Any],
    v27_proof_path: Path,
    v27_proof: dict[str, Any],
    v27_receipt_path: Path,
    v27_receipt: dict[str, Any],
    audit_path: Path,
    impact_path: Path,
    impact_proof_path: Path,
    impact_receipt_path: Path,
    mechanism_path: Path,
    mechanism_proof_path: Path,
    mechanism_receipt_path: Path,
    quality_path: Path,
    quality_proof_path: Path,
    quality_receipt_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current, current_data = _json(current_path, "producer CURRENT336")
    rows, by_key = _validate_current(current, current_data)
    current_sha = sha256_file(current)
    v27_summary = _validate_v27(current, product_path, product, manifest_path, manifest, v27_request_path, v27_request, v27_proof_path, v27_proof, v27_receipt_path, v27_receipt)
    audit_path, audit = _json(audit_path, "scientific audit v23")
    audit_by_key = _validate_scientific_audit(audit_path, audit, by_key, current_sha)
    impact_path, impact = _json(impact_path, "all118 impact v8")
    impact_receipt_path, impact_receipt = _json(impact_receipt_path, "all118 impact receipt")
    impact_proof_path, impact_proof = _json(impact_proof_path, "all118 impact proof")
    impact_by_key = _validate_ledger_report(impact_path, impact, impact_proof_path, impact_proof, impact_receipt_path, impact_receipt, IMPACT_SCHEMA, 118, current_sha, by_key)
    mechanism_path, mechanism = _json(mechanism_path, "all118 mechanism v3")
    mechanism_receipt_path, mechanism_receipt = _json(mechanism_receipt_path, "all118 mechanism receipt")
    mechanism_proof_path, mechanism_proof = _json(mechanism_proof_path, "all118 mechanism proof")
    mechanism_by_key = _validate_ledger_report(mechanism_path, mechanism, mechanism_proof_path, mechanism_proof, mechanism_receipt_path, mechanism_receipt, MECHANISM_SCHEMA, 118, current_sha, by_key)
    if set(impact_by_key) != set(mechanism_by_key):
        raise CatalogError("impact and mechanism case sets differ")
    quality_path, quality = _json(quality_path, "strict seven-family quality report")
    quality_receipt_path, quality_receipt = _json(quality_receipt_path, "strict quality receipt")
    quality_proof_path, quality_proof = _json(quality_proof_path, "strict quality proof")
    quality_by_key = _validate_quality(quality_path, quality, quality_proof_path, quality_proof, quality_receipt_path, quality_receipt, by_key)
    cards = product.get("family_cards") or {}
    catalog_cases = []
    for index, row in enumerate(rows):
        key = _key(row)
        card = cards.get(row.get("family_id")) if index in {0, 78, 96, 144, 192, 240, 288} else None
        catalog_cases.append(_case_record(index, row, audit_by_key[key], impact_by_key.get(key), mechanism_by_key.get(key), quality_by_key.get(key), card))
    sources = {
        "v27": v27_summary,
        "current": _ref(current, "producer CURRENT336"),
        "scientific_audit_v23": _ref(audit_path, "336-case scientific audit v23"),
        "impact_v8": {"report": _ref(impact_path, "all118 impact v8 report"), "proof": _ref(impact_proof_path, "all118 impact v8 proof"), "receipt": _ref(impact_receipt_path, "all118 impact v8 receipt")},
        "mechanism_v3": {"report": _ref(mechanism_path, "all118 mechanism v3 report"), "proof": _ref(mechanism_proof_path, "all118 mechanism v3 proof"), "receipt": _ref(mechanism_receipt_path, "all118 mechanism v3 receipt")},
        "quality_v2_strict": {"report": _ref(quality_path, "seven-family strict quality report"), "proof": _ref(quality_proof_path, "seven-family strict quality proof"), "receipt": _ref(quality_receipt_path, "seven-family strict quality receipt")},
    }
    source_counts = {
        "current_cases": len(rows),
        "scientific_audit_cases": len(audit_by_key),
        "native_impact_cases": len(impact_by_key),
        "native_mechanism_cases": len(mechanism_by_key),
        "quality_anchor_cases": len(quality_by_key),
        "audit_native_intersection": len(set(audit_by_key) & set(impact_by_key)),
        "non_native_cases": len(set(by_key) - set(impact_by_key)),
        "all_qn_qe_qi_unknown": all(case["qualification_dimensions"]["error_qualification"][key] == "UNKNOWN" for case in catalog_cases for key in ("QN", "QE", "QI")),
    }
    result = {
        "schema": PRODUCT_SCHEMA,
        "status": "ACTUAL_336_CASE_AUDIT_AND_118_NATIVE_IMPACT_BOUND_NO_SCIENTIFIC_QUALIFICATION",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT), "git_commit": _git_commit()},
        "inputs": sources,
        "coverage": source_counts,
        "scientific_qualification": {"QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "effective_split_safe": "UNKNOWN", "qualification_credit": "NONE"},
        "claim_boundary": {
            "mass": "336 audit initial mass/missing counts; 118 source-visible native lower bounds only; no physical mass-outflow or dynamics-error bound",
            "finite": "saved scientific field/lifecycle audit scope only",
            "identity": "exact CURRENT336 and, for 118 cases, native (Zone,Idp)/motive source closure",
            "time": "CURRENT saved windows and audit frames; native missing times are saved-record brackets only",
            "censoring": "native 118 endpoint/missing censoring scope; hidden continuous crossings/recrossings UNKNOWN",
            "failed_scope": "field failure lists and preserved producer/recovery boundaries only; no solution-error qualification",
            "physical_fate": "UNKNOWN", "legal_outflow_or_spill": "UNKNOWN", "dynamical_impact": "UNKNOWN",
            "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN",
        },
        "cases": catalog_cases,
        "read_policy": {
            "current_json_opened": True,
            "v27_and_report_json_opened": True,
            "trajectory_h5_opened": False,
            "materialized_label_h5_opened": False,
            "part_bi4_opened": False,
            "raw_solver_output_opened": False,
            "solver_started": False,
            "model_invoked": False,
        },
        "qualification_credit": "NONE; bounded metadata, scientific audit fields, native source-cause/mass/censoring scope, and strict quality task scope only",
        "manifest_path": None,
    }
    return catalog_cases, {"result": result, "sources": sources, "current_sha": current_sha}


def build_catalog(
    current_path: Path | str,
    v27_product_path: Path | str,
    v27_manifest_path: Path | str,
    v27_request_path: Path | str,
    v27_proof_path: Path | str,
    v27_receipt_path: Path | str,
    audit_path: Path | str,
    impact_path: Path | str,
    impact_proof_path: Path | str,
    impact_receipt_path: Path | str,
    mechanism_path: Path | str,
    mechanism_proof_path: Path | str,
    mechanism_receipt_path: Path | str,
    quality_path: Path | str,
    quality_proof_path: Path | str,
    quality_receipt_path: Path | str,
    output: Path | str,
    manifest_output: Path | str,
) -> dict[str, Any]:
    current_path = _path(current_path, "producer CURRENT336")
    v27_product_path, product = _json(v27_product_path, "actual v27 product")
    v27_manifest_path, manifest = _json(v27_manifest_path, "actual v27 manifest")
    v27_request_path, v27_request = _json(v27_request_path, "actual v27 request")
    v27_proof_path, v27_proof = _json(v27_proof_path, "actual v27 proof")
    v27_receipt_path, v27_receipt = _json(v27_receipt_path, "actual v27 receipt")
    args = [
        (audit_path, "scientific audit v23"), (impact_path, "all118 impact v8"), (impact_proof_path, "all118 impact proof"), (impact_receipt_path, "all118 impact receipt"),
        (mechanism_path, "all118 mechanism v3"), (mechanism_proof_path, "all118 mechanism proof"), (mechanism_receipt_path, "all118 mechanism receipt"),
        (quality_path, "strict quality report"), (quality_proof_path, "strict quality proof"), (quality_receipt_path, "strict quality receipt"),
    ]
    paths = {label: _path(value, label) for value, label in args}
    _, prepared = _load_and_validate(
        current_path, v27_product_path, product, v27_manifest_path, manifest, v27_request_path, v27_request,
        v27_proof_path, v27_proof, v27_receipt_path, v27_receipt,
        paths["scientific audit v23"], paths["all118 impact v8"], paths["all118 impact proof"], paths["all118 impact receipt"],
        paths["all118 mechanism v3"], paths["all118 mechanism proof"], paths["all118 mechanism receipt"],
        paths["strict quality report"], paths["strict quality proof"], paths["strict quality receipt"],
    )
    output = _path(output, "catalog output", output=True).resolve()
    manifest_output = _path(manifest_output, "catalog manifest output", output=True).resolve()
    if output.exists() or manifest_output.exists():
        raise CatalogError(f"refusing to overwrite v29 output/manifest: {output} {manifest_output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    prepared["result"]["manifest_path"] = str(manifest_output)
    output.write_text(json.dumps(prepared["result"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": prepared["result"]["status"],
        "product": _ref(output, "v29 qualification catalog"),
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT), "git_commit": _git_commit()},
        "inputs": prepared["sources"],
        "coverage": prepared["result"]["coverage"],
        "read_policy": prepared["result"]["read_policy"],
        "qualification_boundary": prepared["result"]["claim_boundary"],
    }
    manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return prepared["result"]


def make_request(
    current_path: Path | str,
    v27_product_path: Path | str,
    v27_manifest_path: Path | str,
    v27_request_path: Path | str,
    v27_proof_path: Path | str,
    v27_receipt_path: Path | str,
    audit_path: Path | str,
    impact_path: Path | str,
    impact_proof_path: Path | str,
    impact_receipt_path: Path | str,
    mechanism_path: Path | str,
    mechanism_proof_path: Path | str,
    mechanism_receipt_path: Path | str,
    quality_path: Path | str,
    quality_proof_path: Path | str,
    quality_receipt_path: Path | str,
    output: Path | str,
    runtime_root: Path | str,
    worker_root: Path | str,
    attempt_id: str = "final-qualification-catalog-v29-forward-001",
) -> dict[str, Any]:
    """Create the shared-runner request after all actual JSON identities pass."""
    current_path = _path(current_path, "producer CURRENT336")
    v27_product_path, product = _json(v27_product_path, "actual v27 product")
    v27_manifest_path, manifest = _json(v27_manifest_path, "actual v27 manifest")
    v27_request_path, v27_request = _json(v27_request_path, "actual v27 request")
    v27_proof_path, v27_proof = _json(v27_proof_path, "actual v27 proof")
    v27_receipt_path, v27_receipt = _json(v27_receipt_path, "actual v27 receipt")
    paths = {
        "scientific audit v23": _path(audit_path, "scientific audit v23"),
        "all118 impact v8": _path(impact_path, "all118 impact v8"),
        "all118 impact proof": _path(impact_proof_path, "all118 impact proof"),
        "all118 impact receipt": _path(impact_receipt_path, "all118 impact receipt"),
        "all118 mechanism v3": _path(mechanism_path, "all118 mechanism v3"),
        "all118 mechanism proof": _path(mechanism_proof_path, "all118 mechanism proof"),
        "all118 mechanism receipt": _path(mechanism_receipt_path, "all118 mechanism receipt"),
        "strict quality report": _path(quality_path, "strict quality report"),
        "strict quality proof": _path(quality_proof_path, "strict quality proof"),
        "strict quality receipt": _path(quality_receipt_path, "strict quality receipt"),
    }
    _load_and_validate(
        current_path, v27_product_path, product, v27_manifest_path, manifest, v27_request_path, v27_request,
        v27_proof_path, v27_proof, v27_receipt_path, v27_receipt,
        paths["scientific audit v23"], paths["all118 impact v8"], paths["all118 impact proof"], paths["all118 impact receipt"],
        paths["all118 mechanism v3"], paths["all118 mechanism proof"], paths["all118 mechanism receipt"],
        paths["strict quality report"], paths["strict quality proof"], paths["strict quality receipt"],
    )
    runtime_root = Path(runtime_root).expanduser().resolve()
    worker_root = Path(worker_root).expanduser().resolve()
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_final_qualification_catalog_v29.py"
    runtime_files = [
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
        runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
    ]
    source_inputs = [
        worker, *runtime_files, current_path, v27_product_path, v27_manifest_path, v27_request_path, v27_proof_path, v27_receipt_path,
        paths["scientific audit v23"], paths["all118 impact v8"], paths["all118 impact proof"], paths["all118 impact receipt"],
        paths["all118 mechanism v3"], paths["all118 mechanism proof"], paths["all118 mechanism receipt"],
        paths["strict quality report"], paths["strict quality proof"], paths["strict quality receipt"],
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in source_inputs:
        path = _path(path, "v29 request input")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    hashes = {str(path): sha256_file(path) for path in unique}
    output_placeholder = "{attempt_root}/final-qualification-catalog-v29.json"
    manifest_placeholder = "{attempt_root}/final-qualification-catalog-manifest-v29.json"
    command = [
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "build",
        "--current", str(current_path), "--v27-product", str(v27_product_path), "--v27-manifest", str(v27_manifest_path),
        "--v27-request", str(v27_request_path), "--v27-proof", str(v27_proof_path), "--v27-receipt", str(v27_receipt_path),
        "--audit", str(paths["scientific audit v23"]), "--impact", str(paths["all118 impact v8"]), "--impact-proof", str(paths["all118 impact proof"]), "--impact-receipt", str(paths["all118 impact receipt"]),
        "--mechanism", str(paths["all118 mechanism v3"]), "--mechanism-proof", str(paths["all118 mechanism proof"]), "--mechanism-receipt", str(paths["all118 mechanism receipt"]),
        "--quality", str(paths["strict quality report"]), "--quality-proof", str(paths["strict quality proof"]), "--quality-receipt", str(paths["strict quality receipt"]),
        "--output", output_placeholder, "--manifest-output", manifest_placeholder,
    ]
    result = {
        "schema": "ds02.runner-request.v1",
        "request_schema": REQUEST_SCHEMA,
        "attempt_id": attempt_id,
        "case_id": "DS02_STAGE2_FINAL_QUALIFICATION_CATALOG_V29",
        "family_id": "infra",
        "dataset_families": FAMILIES,
        "kind": "cpu",
        "cpu_task_kind": "metadata_scientific_audit_catalog",
        "cpu_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 32 * 1024 * 1024,
        "cwd": str(worker_root / "lagrangian-fluid-lab/scripts"),
        "worktree_root": str(worker_root),
        "command": command,
        "input_files": [str(path) for path in unique],
        "input_sha256": hashes,
        "launch_allowed": True,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {
            "small_json_and_receipt_bytes_read": sum(path.stat().st_size for path in unique if path.suffix.lower() == ".json"),
            "trajectory_h5_bytes_read": 0, "materialized_label_h5_bytes_read": 0, "part_bi4_bytes_read": 0,
            "raw_solver_output_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False,
        },
        "coverage_contract": {"current_cases": 336, "scientific_audit_cases": 336, "native_impact_cases": 118, "quality_anchor_cases": 7, "non_anchor_cases_remain_explicit": True},
        "claim_boundary": {"mass": "source-visible lower bound only for native 118", "finite": "field audit scope only", "identity": "CURRENT plus native motive scope", "time": "saved windows/brackets only", "censoring": "hidden continuous events UNKNOWN", "failed_scope": "field/producer failure scope only", "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "QI": "UNKNOWN", "qualification_credit": "none"},
        "read_policy": {"metadata_json_opened": True, "trajectory_h5_opened": False, "materialized_label_h5_opened": False, "part_bi4_opened": False, "raw_solver_output_opened": False, "solver_started": False, "model_invoked": False},
    }
    output = _path(output, "v29 request output", output=True).resolve()
    if output.exists():
        raise CatalogError(f"refusing to overwrite v29 request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "make-request"):
        p = sub.add_parser(name)
        p.add_argument("--current", type=Path, required=True)
        p.add_argument("--v27-product", type=Path, required=True)
        p.add_argument("--v27-manifest", type=Path, required=True)
        p.add_argument("--v27-request", type=Path, required=True)
        p.add_argument("--v27-proof", type=Path, required=True)
        p.add_argument("--v27-receipt", type=Path, required=True)
        p.add_argument("--audit", type=Path, required=True)
        p.add_argument("--impact", type=Path, required=True)
        p.add_argument("--impact-proof", type=Path, required=True)
        p.add_argument("--impact-receipt", type=Path, required=True)
        p.add_argument("--mechanism", type=Path, required=True)
        p.add_argument("--mechanism-proof", type=Path, required=True)
        p.add_argument("--mechanism-receipt", type=Path, required=True)
        p.add_argument("--quality", type=Path, required=True)
        p.add_argument("--quality-proof", type=Path, required=True)
        p.add_argument("--quality-receipt", type=Path, required=True)
        if name == "build":
            p.add_argument("--output", type=Path, required=True)
            p.add_argument("--manifest-output", type=Path, required=True)
        else:
            p.add_argument("--output", type=Path, required=True)
            p.add_argument("--runtime-root", type=Path, required=True)
            p.add_argument("--worker-root", type=Path, required=True)
            p.add_argument("--attempt-id", default="final-qualification-catalog-v29-forward-001")
    args = parser.parse_args(argv)
    common = dict(
        current_path=args.current, v27_product_path=args.v27_product, v27_manifest_path=args.v27_manifest,
        v27_request_path=args.v27_request, v27_proof_path=args.v27_proof, v27_receipt_path=args.v27_receipt,
        audit_path=args.audit, impact_path=args.impact, impact_proof_path=args.impact_proof, impact_receipt_path=args.impact_receipt,
        mechanism_path=args.mechanism, mechanism_proof_path=args.mechanism_proof, mechanism_receipt_path=args.mechanism_receipt,
        quality_path=args.quality, quality_proof_path=args.quality_proof, quality_receipt_path=args.quality_receipt,
    )
    if args.command == "build":
        build_catalog(**common, output=args.output, manifest_output=args.manifest_output)
    else:
        make_request(**common, output=args.output, runtime_root=args.runtime_root, worker_root=args.worker_root, attempt_id=args.attempt_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
