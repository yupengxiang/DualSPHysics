#!/usr/bin/env python3
"""Build a source-bound Stage2 qualification and coverage gap matrix.

This is a JSON-only consumer of the already completed CURRENT336, v27/v29/v30
catalog products, seven-family cards/evaluator, product-access record, and the
fixed fourteen-sentinel source index.  It exposes per-case diagnostic scope
and records why a task is usable, weak, missing, or contradicted.  It never
opens trajectory/label H5, BI4/OBI4, VTK, raw solver output, or a model.

The matrix is an inventory and qualification boundary.  It does not promote
native motives, saved-frame brackets, finite-field checks, source-visible mass
lower bounds, or anchor task labels to QI/QN/QE, physical fate, legal flux,
continuous event truth, recovery transfer, or dynamics/error bounds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FAMILIES = [f"F{i}" for i in range(1, 8)]
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
V24_SCHEMA = "ds02.stage2.effective-condition-cards.v24"
V25_SCHEMA = "ds02.stage2.source-closed-development-split.v25"
V27_SCHEMA = "ds02.stage2.final-family-product.v27"
V29_SCHEMA = "ds02.stage2.final-qualification-catalog.v29"
V30_SCHEMA = "ds02.stage2.task-scope-catalog.v30"
QUALITY_SCHEMA = "ds02.stage2.family-label-quality-evaluator.v2-strict"
ACCESS_SCHEMA = "ds02.stage2.product-access-provenance.v1"
DETAIL_SCHEMA = "ds02.stage2.scientific-scan-detail.v2"
SENTINEL_SCHEMA = "ds02.stage2.fourteen-source-status.v3"
SENTINEL_NEXT_SCHEMA = "ds02.stage2.fourteen-source-status.v3-next-requests"
MATRIX_SCHEMA = "ds02.stage2.whole-goal-qualification-gap-matrix.v2"
MANIFEST_SCHEMA = "ds02.stage2.whole-goal-qualification-gap-matrix.manifest.v2"
REQUEST_SCHEMA = "ds02.stage2.whole-goal-qualification-gap-matrix-request.v2"
CURRENT336_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
V27_MANIFEST_SCHEMA = "ds02.stage2.final-family-product-manifest.v27"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".hdf", ".bi4", ".obi4", ".vtk", ".vtu", ".raw"}
STATUS_VALUES = {"evidence_verified", "weak", "missing", "contradicted", "not_applicable"}
Q_KEYS = ("QN", "QE", "QI", "physical_fate", "dynamical_impact")


class MatrixError(RuntimeError):
    """Raised when an input identity or bounded contract is open."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise MatrixError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _path(value: Any, label: str, *, output: bool = False) -> Path:
    if not isinstance(value, (str, Path)):
        raise MatrixError(f"{label} must be an absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise MatrixError(f"{label} must be an absolute path")
    if not output and path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise MatrixError(f"{label} is forbidden scientific payload: {path}")
    if not output and not path.is_file():
        raise MatrixError(f"{label} is missing: {path}")
    return path


def _ref(path: Path, role: str, *, source_scope: str = "JSON_ONLY") -> dict[str, Any]:
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
        "source_scope": source_scope,
    }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MatrixError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise MatrixError(f"{label} must be a JSON object: {path}")
    return data


def load_manifest(manifest_path: Path | str) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any]]]:
    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest = _read_json(manifest_path, "qualification-gap manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise MatrixError(f"unexpected matrix manifest schema: {manifest.get('schema')!r}")
    refs = manifest.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise MatrixError("matrix manifest source_refs is empty")
    paths: dict[str, Path] = {}
    records: dict[str, dict[str, Any]] = {}
    for item in refs:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise MatrixError("malformed matrix source reference")
        key = item["key"]
        if key in paths:
            raise MatrixError(f"duplicate matrix source key: {key}")
        path = _path(item.get("path"), f"source {key}")
        expected = _require_sha(item.get("sha256"), f"source {key}")
        actual = _ref(path, str(item.get("role", key)), source_scope=str(item.get("source_scope", "JSON_ONLY")))
        if actual["sha256"] != expected:
            raise MatrixError(f"source {key} digest changed: {expected} != {actual['sha256']}")
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if field in item and item[field] is not None and actual[field] != item[field]:
                raise MatrixError(f"source {key} {field} changed")
        paths[key] = path
        records[key] = actual
    current = records.get("current336")
    if current is None or current["sha256"] != CURRENT336_SHA256:
        actual = current["sha256"] if current else None
        raise MatrixError(f"CURRENT336 must bind exact SHA {CURRENT336_SHA256}; got {actual}")
    declared_current = (manifest.get("source_index") or {}).get("current336")
    if not isinstance(declared_current, dict) or declared_current.get("sha256") != CURRENT336_SHA256:
        raise MatrixError("manifest source_index.current336 does not bind the required CURRENT336 SHA")
    return manifest, paths, records


def _json_source(paths: dict[str, Path], key: str) -> dict[str, Any]:
    return _read_json(paths[key], key)


def _case_key(row: dict[str, Any]) -> str | None:
    value = row.get("case_key")
    if isinstance(value, str) and "/" in value:
        return value
    family, physical = row.get("family_id"), row.get("physical_case_id")
    if isinstance(family, str) and isinstance(physical, str):
        return f"{family}/{physical}"
    return None


def _family_case_key(row: dict[str, Any]) -> tuple[str, str] | None:
    key = _case_key(row)
    if key is None:
        return None
    family, physical = key.split("/", 1)
    return family, physical


def _unknown_qualification(row: dict[str, Any]) -> bool:
    dimensions = row.get("qualification_dimensions") or {}
    q = dimensions.get("error_qualification") or {}
    return all(q.get(key) == "UNKNOWN" for key in Q_KEYS)


def _validate_current(current: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise MatrixError("CURRENT336 schema is not current336.v1")
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise MatrixError("CURRENT336 must expose exactly 336 cases")
    by_key: dict[str, dict[str, Any]] = {}
    counts = {family: 0 for family in FAMILIES}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MatrixError(f"CURRENT336 row {index} is not an object")
        key = _case_key(row)
        if key is None or key in by_key or key.split("/", 1)[0] not in FAMILIES:
            raise MatrixError(f"CURRENT336 identity is invalid at row {index}")
        if row.get("current_index", index) != index:
            raise MatrixError(f"CURRENT336 ordering/current_index differs at row {index}")
        by_key[key] = row
        counts[key.split("/", 1)[0]] += 1
    if counts != {family: 48 for family in FAMILIES}:
        raise MatrixError(f"CURRENT336 family counts are not 48 each: {counts}")
    return rows, by_key


def _rows_by_key(value: Any, label: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not isinstance(value, list):
        raise MatrixError(f"{label} is not a list")
    result: dict[str, dict[str, Any]] = {}
    malformed: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            malformed.append("NON_OBJECT")
            continue
        key = _case_key(row)
        if key is None or key in result:
            malformed.append(str(key or "MALFORMED"))
            continue
        result[key] = row
    return result, malformed


def _validate_product_shapes(
    current_keys: set[str],
    v29: dict[str, Any],
    v29_rows: dict[str, dict[str, Any]],
    v30: dict[str, Any],
    v30_rows: dict[str, dict[str, Any]],
    v27_product: dict[str, Any],
    v27_manifest: dict[str, Any],
    v24: dict[str, Any],
    v25: dict[str, Any],
    quality: dict[str, Any],
    access: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, str]:
    """Reject malformed product joins before emitting any verified status.

    This is intentionally a shape/identity check.  It does not convert the
    products' task diagnostics into scientific qualification.
    """
    if v29.get("schema") != V29_SCHEMA:
        raise MatrixError(f"v29 schema is not {V29_SCHEMA}")
    if v30.get("schema") != V30_SCHEMA:
        raise MatrixError(f"v30 schema is not {V30_SCHEMA}")
    if v27_product.get("schema") != V27_SCHEMA:
        raise MatrixError(f"v27 product schema is not {V27_SCHEMA}")
    if v27_manifest.get("schema") != V27_MANIFEST_SCHEMA:
        raise MatrixError(f"v27 manifest schema is not {V27_MANIFEST_SCHEMA}")
    if v24.get("schema") != V24_SCHEMA:
        raise MatrixError(f"v24 schema is not {V24_SCHEMA}")
    if v25.get("schema") != V25_SCHEMA:
        raise MatrixError(f"v25 schema is not {V25_SCHEMA}")
    if quality.get("schema") != QUALITY_SCHEMA:
        raise MatrixError(f"quality schema is not {QUALITY_SCHEMA}")
    if access.get("schema") != ACCESS_SCHEMA:
        raise MatrixError(f"access schema is not {ACCESS_SCHEMA}")
    if detail.get("schema") != DETAIL_SCHEMA:
        raise MatrixError(f"detail schema is not {DETAIL_SCHEMA}")

    if len(v29_rows) != 336 or len(v30_rows) != 336:
        raise MatrixError("v29/v30 must each contain exactly 336 unique case rows")
    if set(v29_rows) != current_keys:
        raise MatrixError("v29 case key set differs from exact CURRENT336 case key set")
    if set(v30_rows) != current_keys:
        raise MatrixError("v30 case key set differs from exact CURRENT336 case key set")
    native_count = sum(row.get("native_omission") is not None for row in v29_rows.values())
    if native_count != 118:
        raise MatrixError(f"v29 native omission count must be 118, got {native_count}")

    family_keys = set(FAMILIES)
    v27_product_cards = v27_product.get("family_cards")
    v27_manifest_cards = v27_manifest.get("cards")
    if not isinstance(v27_product_cards, dict) or set(v27_product_cards) != family_keys:
        raise MatrixError("v27 product family_cards are not exactly F1..F7")
    if not isinstance(v27_manifest_cards, dict) or set(v27_manifest_cards) != family_keys:
        raise MatrixError("v27 manifest cards are not exactly F1..F7")
    if not isinstance(v27_product.get("case_inventory"), list) or len(v27_product["case_inventory"]) != 336:
        raise MatrixError("v27 product case_inventory is not exactly 336 rows")
    if not isinstance(v27_manifest.get("case_inventory"), list) or len(v27_manifest["case_inventory"]) != 336:
        raise MatrixError("v27 manifest case_inventory is not exactly 336 rows")

    cards = v24.get("cards")
    components = v25.get("components")
    quality_rows = quality.get("family_cards")
    if not isinstance(cards, list) or {row.get("family_id") for row in cards if isinstance(row, dict)} != family_keys or len(cards) != 7:
        raise MatrixError("v24 cards are not exactly one row per family")
    component_families = {str(row.get("component_id", "")).rsplit("-", 1)[-1] for row in components if isinstance(row, dict)} if isinstance(components, list) else set()
    if not isinstance(components, list) or len(components) != 7 or component_families != family_keys:
        raise MatrixError("v25 components are not exactly one row per family")
    if not isinstance(quality_rows, list) or len(quality_rows) != 7 or {row.get("family_id") for row in quality_rows if isinstance(row, dict)} != family_keys:
        raise MatrixError("quality family_cards are not exactly one row per family")
    if detail.get("case_count") != 336 or not isinstance(detail.get("detail_cards"), list) or len(detail["detail_cards"]) != 336:
        raise MatrixError("scientific detail product is not exactly 336 rows")
    return {
        "v29_product": "evidence_verified",
        "v30_product": "evidence_verified",
        "v27_product": "evidence_verified",
        "v27_manifest": "evidence_verified",
        "v24_cards": "evidence_verified",
        "v25_split": "evidence_verified",
        "quality_report": "evidence_verified",
        "access_report": "evidence_verified",
        "detail_report": "evidence_verified",
    }


def _catalog_artifact(name: str, path: Path, data: dict[str, Any], schema: str, count: int | None = None) -> dict[str, Any]:
    issues: list[str] = []
    if data.get("schema") != schema:
        issues.append(f"schema={data.get('schema')!r}")
    if count is not None:
        actual_count = data.get("case_count", data.get("coverage", {}).get("current_cases"))
        if actual_count != count:
            issues.append(f"count={actual_count!r}")
    return {
        "name": name,
        "status": "contradicted" if issues else "evidence_verified",
        "evidence": _ref(path, name),
        "issues": issues,
        "scientific_qualification": "UNKNOWN",
    }


def _case_record(current: dict[str, Any], v29: dict[str, Any] | None, v30: dict[str, Any] | None) -> dict[str, Any]:
    key = _case_key(current)
    assert key is not None
    issues: list[str] = []
    if v29 is None:
        issues.append("v29_case_missing")
    if v30 is None:
        issues.append("v30_case_missing")
    if v29 is not None and not _unknown_qualification(v29):
        issues.append("v29_qualification_not_UNKNOWN")
    if v30 is not None and any((v30.get("error_qualification") or {}).get(q) not in (None, "UNKNOWN") for q in Q_KEYS):
        issues.append("v30_qualification_not_UNKNOWN")
    if current.get("family_id") != (v29 or {}).get("current", {}).get("family_id", current.get("family_id")):
        issues.append("v29_family_mismatch")
    if current.get("physical_case_id") != (v29 or {}).get("current", {}).get("physical_case_id", current.get("physical_case_id")):
        issues.append("v29_physical_case_mismatch")
    identity = "contradicted" if issues else "evidence_verified"

    if v29 is None or v30 is None:
        explanation = "missing"
    elif issues:
        explanation = "contradicted"
    else:
        explanation = "evidence_verified"

    native = v29.get("native_omission") if v29 else None
    if native is None:
        omission = {
            "status": "not_applicable",
            "reason": "case is outside the exact 118 native omission ledger",
            "native_motive": None,
            "native_count": 0,
            "physical_fate": "UNKNOWN",
        }
    else:
        source = native.get("source_closure") or {}
        native_issues: list[str] = []
        if source.get("status") not in {"FULL_PROBE_SOURCE_CLOSED", "FULL_NATIVE_SOURCE_CLOSED", "V2_NATIVE_SOURCE_CLOSED", "EXACT_NATIVE_SOURCE_CLOSED"}:
            native_issues.append("native_source_closure_not_closed")
        if not isinstance(native.get("native_count"), int) or not isinstance(native.get("native_motive"), str):
            native_issues.append("native_identity_fields_missing")
        omission = {
            "status": "contradicted" if native_issues else "evidence_verified",
            "reason": "exact native motive/identity/source-visible lower-bound scope only",
            "native_motive": native.get("native_motive"),
            "native_count": native.get("native_count"),
            "source_closure_status": source.get("status"),
            "missing_fraction_lower_bound": (native.get("source_visible_mass") or {}).get("missing_source_visible_fraction_lower_bound"),
            "first_missing_window_s": (native.get("saved_censoring") or {}).get("first_missing_window_s"),
            "physical_fate": "UNKNOWN",
            "issues": native_issues,
        }

    dimensions = (v29 or {}).get("qualification_dimensions") or {}
    finite = dimensions.get("finite_fields")
    if v29 is None or not isinstance(finite, dict):
        finite_status = "missing"
    elif "audit_status" not in finite or "field_failures" not in finite:
        finite_status = "missing"
    elif not isinstance(finite.get("audit_status"), str) or not isinstance(finite.get("field_failures"), list):
        finite_status = "contradicted"
    else:
        finite_status = "evidence_verified"
    v30_finite = (v30 or {}).get("finite_field_scope") or {}
    lifecycle = v30_finite.get("lifecycle") if isinstance(v30_finite, dict) else None
    lifecycle_status = "missing" if lifecycle in (None, "NOT_EXPOSED_IN_AUDIT_ROW", "NOT_EXPOSED_IN_THIS_AUDIT_ROW") else "evidence_verified" if isinstance(lifecycle, str) else "contradicted"
    quality = (v30 or {}).get("quality_scope") or {}
    quality_status = "evidence_verified" if quality.get("status") == "ELIGIBLE_STRICT_ANCHOR_TASK_SCOPE" else "weak"
    return {
        "case_key": key,
        "current_index": current.get("current_index"),
        "family_id": current.get("family_id"),
        "physical_case_id": current.get("physical_case_id"),
        "record_status": identity,
        "case_explanation": {
            "status": explanation,
            "identity_and_scope": "exact CURRENT336/v29/v30 join" if explanation == "evidence_verified" else "see issues",
            "issues": issues,
        },
        "omission_scope": omission,
        "finite_field_scope": {
            "status": finite_status,
            "field_failure_count": len(finite.get("field_failures", [])) if isinstance(finite, dict) and isinstance(finite.get("field_failures"), list) else None,
            "audit_status": finite.get("audit_status") if isinstance(finite, dict) else None,
            "qualification_credit": "diagnostic only; no numerical error bound",
        },
        "lifecycle_scope_status": lifecycle_status,
        "lifecycle_scope": {
            "status": lifecycle_status,
            "value": lifecycle,
            "qualification_credit": "diagnostic only; lifecycle coverage is absent when the source product marks it NOT_EXPOSED",
        },
        "task_scope": {
            "status": quality_status,
            "source_role": quality.get("source_role"),
            "split": quality.get("split"),
            "task_eligibility": copy_json(quality.get("task_eligibility")) if isinstance(quality.get("task_eligibility"), dict) else None,
            "qualification_credit": "NONE",
        },
        "qualification_gap": {
            "status": "weak",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN",
            "continuous_event_truth": "UNKNOWN", "recovery_transfer": "UNKNOWN",
            "effective_split_safe": "UNKNOWN", "dynamical_impact": "UNKNOWN",
            "reason": "bounded metadata/native diagnostics exist, but no physical/error qualification was established",
        },
    }


def _sentinel_matrix(status: dict[str, Any], next_requests: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if status.get("schema") != SENTINEL_SCHEMA or next_requests.get("schema") != SENTINEL_NEXT_SCHEMA:
        raise MatrixError("fourteen-sentinel source status schemas are not exact")
    sentinels = status.get("sentinels")
    requests = next_requests.get("requests")
    if not isinstance(sentinels, list) or len(sentinels) != 14 or not isinstance(requests, list) or len(requests) != 14:
        raise MatrixError("fourteen-sentinel source status does not contain exactly 14 rows")
    sentinel_ids = [row.get("sentinel_id") for row in sentinels if isinstance(row, dict)]
    request_ids = [row.get("request_id") for row in requests if isinstance(row, dict)]
    if len(sentinel_ids) != 14 or len(set(sentinel_ids)) != 14:
        raise MatrixError("fourteen-sentinel rows contain duplicate or missing sentinel IDs")
    if len(request_ids) != 14 or len(set(request_ids)) != 14:
        raise MatrixError("fourteen-sentinel next requests contain duplicate or missing request IDs")
    request_by_id = {row.get("sentinel_id"): row for row in requests if isinstance(row, dict)}
    result: list[dict[str, Any]] = []
    by_family: dict[str, list[dict[str, Any]]] = {family: [] for family in FAMILIES}
    for row in sentinels:
        if not isinstance(row, dict):
            raise MatrixError("sentinel row is not an object")
        sid, family = row.get("sentinel_id"), row.get("family_id")
        evidence = row.get("evidence")
        issues: list[str] = []
        if not isinstance(sid, str) or family not in FAMILIES:
            issues.append("identity_missing")
        if not isinstance(evidence, list) or not evidence:
            issues.append("evidence_missing")
        else:
            for item in evidence:
                file_info = item.get("file") if isinstance(item, dict) else None
                if not isinstance(file_info, dict) or not isinstance(file_info.get("path"), str) or not SHA_RE.fullmatch(str(file_info.get("sha256", ""))):
                    issues.append("evidence_path_or_sha_missing")
                    break
        next_row = request_by_id.get(sid)
        if next_row is None:
            issues.append("next_request_missing")
        terminal = row.get("terminal_state") or {}
        q = terminal.get("scientific_qualification") or {}
        item = {
            "sentinel_id": sid,
            "family_id": family,
            "physical_case_id": row.get("physical_case_id"),
            "status": "contradicted" if issues else "evidence_verified",
            "terminal_status": terminal.get("status"),
            "terminal_category": terminal.get("category"),
            "scientific_qualification": {key: q.get(key, "UNKNOWN") for key in ("QI", "QN", "QE")},
            "evidence": copy_json(evidence) if isinstance(evidence, list) else [],
            "next_request": {
                "status": "weak" if next_row else "missing",
                "request_id": next_row.get("request_id") if next_row else None,
                "task_kind": next_row.get("task_kind") if next_row else None,
                "qualification_after_task": copy_json(next_row.get("qualification_after_task")) if next_row else None,
                "temporality": "HISTORIC_FROZEN_INDEX_NOT_CURRENT_SCHEDULER",
                "reason": "v3 next requests are a pinned source index; actual later terminal proofs require a separate current binding",
            },
            "issues": issues,
        }
        result.append(item)
        if family in by_family:
            by_family[family].append(item)
    if any(len(by_family[family]) != 2 for family in FAMILIES):
        raise MatrixError("fourteen-sentinel rows are not exactly two per family")
    return result, by_family


def _family_rows(v24: dict[str, Any], v25: dict[str, Any], quality: dict[str, Any], v27: dict[str, Any], sentinels: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    cards = {row.get("family_id"): row for row in v24.get("cards", []) if isinstance(row, dict)}
    components = {str(row.get("component_id", "")).rsplit("-", 1)[-1]: row for row in v25.get("components", []) if isinstance(row, dict)}
    quality_rows = {row.get("family_id"): row for row in quality.get("family_cards", []) if isinstance(row, dict)}
    product_cards = v27.get("cards", {}) if isinstance(v27.get("cards"), dict) else {}
    result: list[dict[str, Any]] = []
    for family in FAMILIES:
        card, component, qcard = cards.get(family), components.get(family), quality_rows.get(family)
        issues: list[str] = []
        if card is None or component is None or qcard is None or family not in product_cards:
            issues.append("family_card_or_component_missing")
        card_status = "evidence_verified" if not issues else "missing"
        scientific = "weak"
        if qcard and any(qcard.get("task_eligibility", {}).get(key) not in (None, "UNKNOWN") for key in ("QI", "QN", "QE")):
            issues.append("quality_card_grants_scientific_qualification")
            scientific = "contradicted"
        item = {
            "family_id": family,
            "status": "contradicted" if any("grants" in issue for issue in issues) else card_status,
            "card_scope": card_status,
            "source_component_scope": "evidence_verified" if component is not None else "missing",
            "quality_evaluator_scope": "evidence_verified" if qcard and qcard.get("quality_checks_closed") is True else "weak" if qcard else "missing",
            "sentinel_scope": "evidence_verified" if len(sentinels.get(family, [])) == 2 and all(row["status"] == "evidence_verified" for row in sentinels.get(family, [])) else "weak",
            "scientific_qualification": scientific,
            "task_scopes": ["saved_frame_artifact", "source_role_mass_ledger", "native_cause_alias_join", "owner_control_geometry_metadata"],
            "issues": issues,
            "unknowns": ["QI", "QN", "QE", "physical_fate", "legal_flux", "continuous_events", "recovery_transfer", "effective_split_safe", "dynamics"],
        }
        result.append(item)
    return result


def _artifact_matrix(paths: dict[str, Path], records: dict[str, dict[str, Any]], validation: dict[str, str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    def add(name: str, key: str, scope: str, gap: list[str] | None = None, *, status: str | None = None) -> None:
        entries.append({"name": name, "status": status or validation.get(key, "missing"), "scope": scope, "evidence": records.get(key), "gaps": gap or []})
    add("CURRENT336_inventory", "current336", "336 exact case identities; SHA pinned", status="evidence_verified")
    add("v29_qualification_catalog", "v29_product", "336 case audit and 118 native impact scope; all scientific Q UNKNOWN")
    add("v30_task_scope_catalog", "v30_product", "finite/identity/motive/saved-bracket task diagnostics; no Q credit")
    add("v27_seven_family_product", "v27_product", "seven family cards and 336 inventory; metadata only")
    add("v24_effective_condition_cards", "v24_cards", "seven source components; physical qualification UNKNOWN")
    add("v25_development_split", "v25_split", "source-closed artifact/task roles; scientific split safety UNKNOWN")
    add("seven_family_quality_evaluator_v2", "quality_report", "strict producer-bound task evaluator; no scientific qualification")
    add("scientific_scan_detail_v2", "detail_report", "336 scan-field detail and provenance; no H5 opened by consumer")
    add("fourteen_sentinel_source_index", "sentinel_status", "14 exact sentinel rows and declared evidence paths", status="evidence_verified")
    add("product_access_and_license", "access_report", "workspace metadata/license provenance", ["external access and redistribution rights UNKNOWN_NOT_ESTABLISHED"], status="weak")
    add("native_identity_task_loader", "native_loader", "loader source is pinned; physical task qualification unsupported", status="evidence_verified")
    add("native_identity_task_evaluator_v3", "native_evaluator", "strict case/Idp/motive source join interface is pinned", status="evidence_verified")
    add("v28_replay_chain", "v28_product", "metadata product available; portable raw-to-typed replay remains pending consumer guard", ["portable replay pending", "scientific fate/dynamics UNKNOWN"], status="weak")
    add("f2_new_reference_exclusion", "v29_product", "new ROOT130/138/142 reference scopes are excluded from the original 336/118 universe")
    return entries


def build_matrix(manifest_path: Path | str, output: Path | str) -> dict[str, Any]:
    manifest, paths, records = load_manifest(manifest_path)
    current = _json_source(paths, "current336")
    current_rows, current_by_key = _validate_current(current)
    v29 = _json_source(paths, "v29_product")
    v30 = _json_source(paths, "v30_product")
    v27_product = _json_source(paths, "v27_product")
    v27 = _json_source(paths, "v27_manifest")
    v24 = _json_source(paths, "v24_cards")
    v25 = _json_source(paths, "v25_split")
    quality = _json_source(paths, "quality_report")
    access = _json_source(paths, "access_report")
    detail = _json_source(paths, "detail_report")
    sentinel_status = _json_source(paths, "sentinel_status")
    sentinel_next = _json_source(paths, "sentinel_next")
    sentinel_rows, sentinel_by_family = _sentinel_matrix(sentinel_status, sentinel_next)

    v29_rows, v29_bad = _rows_by_key(v29.get("cases"), "v29 cases")
    v30_rows, v30_bad = _rows_by_key(v30.get("cases"), "v30 cases")
    if v29_bad or v30_bad:
        raise MatrixError("v29/v30 contains malformed or duplicate case rows")
    validation = _validate_product_shapes(set(current_by_key), v29, v29_rows, v30, v30_rows, v27_product, v27, v24, v25, quality, access, detail)
    case_rows = [_case_record(row, v29_rows.get(key), v30_rows.get(key)) for row in current_rows for key in [_case_key(row)] if key is not None]
    if len(case_rows) != 336:
        raise MatrixError("case matrix did not produce 336 rows")
    family_rows = _family_rows(v24, v25, quality, v27, sentinel_by_family)
    artifacts = _artifact_matrix(paths, records, validation)

    def count_status(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
        counts = {status: 0 for status in STATUS_VALUES}
        for row in rows:
            status = row.get(field)
            if isinstance(status, dict):
                status = status.get("status")
            if status not in counts:
                status = "missing"
            counts[status] += 1
        return counts

    contradiction_count = sum(row["record_status"] == "contradicted" or row["case_explanation"]["status"] == "contradicted" for row in case_rows)
    result = {
        "schema": MATRIX_SCHEMA,
        "status": "ACTUAL_JSON_ONLY_336_CASE_QUALIFICATION_GAP_MATRIX_Q_UNKNOWN",
        "producer": {"script_path": str(SCRIPT), "script_sha256": sha256_file(SCRIPT)},
        "current_binding": {"path": str(paths["current336"]), "sha256": records["current336"]["sha256"], "required_sha256": CURRENT336_SHA256, "case_count": 336, "family_counts": {family: 48 for family in FAMILIES}},
        "coverage": {
            "case_count": len(case_rows),
            "case_record_status": count_status(case_rows, "record_status"),
            "case_explanation_status": count_status(case_rows, "case_explanation"),
            "omission_scope_status": count_status(case_rows, "omission_scope"),
            "finite_scope_status": count_status(case_rows, "finite_field_scope"),
            "lifecycle_scope_status": count_status(case_rows, "lifecycle_scope_status"),
            "task_scope_status": count_status(case_rows, "task_scope"),
            "native_omission_cases": sum(row["omission_scope"]["status"] == "evidence_verified" for row in case_rows),
            "non_native_cases_explicitly_not_applicable": sum(row["omission_scope"]["status"] == "not_applicable" for row in case_rows),
            "contradicted_case_rows": contradiction_count,
            "all_scientific_qualification_unknown": True,
        },
        "cases": case_rows,
        "family_matrix": family_rows,
        "sentinel_matrix": sentinel_rows,
        "artifact_matrix": artifacts,
        "qualification_gap_matrix": {
            "finite_field_diagnostics": {"status": "evidence_verified", "usable_scope": "field-failure list and audit status only", "error_bound": "UNKNOWN"},
            "active_finite_lifecycle": {"status": "missing", "usable_scope": "not exposed for the 290 non-native rows; only 46 rows expose a closed lifecycle field", "error_bound": "UNKNOWN"},
            "native_motive_identity_and_saved_brackets": {"status": "evidence_verified", "usable_scope": "exact 118 source-closed native records", "physical_destination": "UNKNOWN", "continuous_event_time": "UNKNOWN"},
            "seven_anchor_task_labels": {"status": "evidence_verified", "usable_scope": "source-role and saved-frame task diagnostics", "scientific_qualification": "UNKNOWN"},
            "physical_qualification": {"status": "missing", "reason": "no QI/QN/QE, legal flux, continuous event, fate, or dynamics/error evidence in the bounded products"},
            "effective_split_safety": {"status": "weak", "reason": "component assignments are source-closed, but transfer/split safety remains UNKNOWN"},
            "license_and_redistribution": {"status": "weak", "reason": "workspace license paths are recorded; external access and redistribution are UNKNOWN_NOT_ESTABLISHED"},
            "portable_replay": {"status": "weak", "reason": "v28 replay chain remains pending consumer guard"},
            "sentinel_next_ready_inventory": {"status": "weak", "reason": "v3 is a historic frozen index; refresh it by binding actual later terminal proofs before treating next requests as current"},
        },
        "usable_task_subsets": {
            "current_inventory": {"status": "evidence_verified", "count": 336, "qualification_credit": "none"},
            "finite_field_diagnostics": {"status": "evidence_verified", "count": 336, "qualification_credit": "none"},
            "active_finite_lifecycle_diagnostics": {"status": "weak", "count": 46, "qualification_credit": "reported lifecycle field only; 290 cases missing lifecycle exposure"},
            "native_cause_and_identity": {"status": "evidence_verified", "count": 118, "qualification_credit": "native motive/ID only"},
            "saved_record_censor_brackets": {"status": "evidence_verified", "count": 118, "qualification_credit": "bracket only"},
            "seven_anchor_saved_frame_artifacts": {"status": "evidence_verified", "count": 7, "qualification_credit": "task diagnostics only"},
            "physical_QI_QN_QE": {"status": "missing", "count": 0, "qualification_credit": "none"},
        },
        "new_reference_scope_exclusion": {
            "status": "evidence_verified",
            "universe": "original CURRENT336 and exact 118 omission aliases only",
            "excluded_scopes": [
                "F2 ROOT130/138 domain-control and new 67-ID reference cases",
                "F2 ROOT095/105/126 coarse canary/reference cases",
                "F3 ROOT150 full836 stream and ROOT153 metadata staging",
                "F7 ROOT141/146/148/149/154/160 selector and spatial candidate references",
            ],
            "rule": "No new reference case is merged into the 336 or 118 counts.",
        },
        "priority_executable_product_gap": {
            "status": "missing",
            "product": "current_sentinel_terminal_index",
            "why_priority": "the bound fourteen-sentinel next-request file is historic and cannot represent ROOT163/164/167/175 terminal state or ROOT170 pending state",
            "next_action": "build a JSON-only source-bound refresh joining the actual terminal proofs/receipts to the same 14 sentinel identities before any new array or solver work",
            "scope": "metadata/status/receipt joins only; no QI/QN/QE or physical transfer credit",
        },
        "source_inputs": records,
        "source_index_declared": copy_json(manifest.get("source_index", {})),
        "read_policy": {
            "json_opened": True,
            "python_source_hashed_only": True,
            "xml_opened": False,
            "trajectory_h5_opened": False,
            "label_h5_opened": False,
            "bi4_opened": False,
            "obi4_opened": False,
            "vtk_opened": False,
            "raw_solver_output_opened": False,
            "solver_started": False,
            "model_invoked": False,
            "new_reference_payload_opened": False,
        },
        "claim_boundary": {
            "evidence_categories": sorted(STATUS_VALUES),
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_events": "UNKNOWN",
            "recovery_transfer": "UNKNOWN", "effective_split_safe": "UNKNOWN", "dynamical_impact": "UNKNOWN",
            "qualification_credit": "NONE",
        },
    }
    output = _path(output, "matrix output", output=True).resolve()
    if output.exists():
        raise MatrixError(f"refusing to overwrite matrix output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, result)
    return result


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
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


def make_request(manifest_path: Path | str, output: Path | str, worker_root: Path | str, runtime_root: Path | str, attempt_id: str = "whole-goal-qualification-gap-matrix-v2-root-prepared-176-001") -> dict[str, Any]:
    manifest, paths, records = load_manifest(manifest_path)
    worker_root = Path(worker_root).expanduser().resolve()
    runtime_root = Path(runtime_root).expanduser().resolve()
    worker = worker_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_whole_goal_qualification_gap_matrix_v2.py"
    runtime_files = [runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py", runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py", runtime_root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]
    all_paths = [worker, Path(manifest_path).expanduser().resolve(), *paths.values(), *runtime_files]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in all_paths:
        path = _path(str(path), "matrix request input")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    hashes = {str(path): sha256_file(path) for path in unique}
    output = _path(output, "matrix request output", output=True).resolve()
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": REQUEST_SCHEMA,
        "attempt_id": attempt_id,
        "case_id": "DS02_STAGE2_WHOLE_GOAL_QUALIFICATION_GAP_MATRIX_V1",
        "family_id": "infra",
        "dataset_families": FAMILIES,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "max_memory_bytes": 2 * 1024**3,
        "estimated_storage_bytes": 32 * 1024**2,
        "estimated_input_read_bytes": sum(path.stat().st_size for path in unique),
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_obi4_read_bytes": 0,
        "cwd": str(worker.parent),
        "worktree_root": str(worker_root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "build", "--manifest", str(Path(manifest_path).expanduser().resolve()), "--output", "{attempt_root}/whole-goal-qualification-gap-matrix-v2.json"],
        "input_files": [str(path) for path in unique],
        "input_sha256": hashes,
        "launch_allowed": True,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU",
        "source_cost": {"json_bytes_read": sum(path.stat().st_size for path in unique if path.suffix.lower() == ".json"), "python_source_bytes_hashed": sum(path.stat().st_size for path in unique if path.suffix.lower() == ".py"), "trajectory_h5_bytes_read": 0, "label_h5_bytes_read": 0, "bi4_bytes_read": 0, "raw_solver_output_bytes_read": 0, "solver_started": False, "model_invoked": False},
        "read_policy": {"metadata_json_opened": True, "python_source_hashed_only": True, "trajectory_h5_opened": False, "materialized_label_h5_opened": False, "part_bi4_opened": False, "raw_solver_output_opened": False, "solver_started": False, "model_invoked": False},
        "claim_boundary": {"case_count": 336, "native_omission_cases": 118, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_events": "UNKNOWN", "effective_split_safe": "UNKNOWN", "dynamical_impact": "UNKNOWN", "new_reference_scopes_excluded": True},
        "manifest_contract": manifest.get("contract"),
        "output": str(output),
    }
    if output.exists():
        raise MatrixError(f"refusing to overwrite request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, request)
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    request = sub.add_parser("make-request")
    request.add_argument("--manifest", type=Path, required=True)
    request.add_argument("--output", type=Path, required=True)
    request.add_argument("--worker-root", type=Path, required=True)
    request.add_argument("--runtime-root", type=Path, required=True)
    request.add_argument("--attempt-id", default="whole-goal-qualification-gap-matrix-v2-root-prepared-176-001")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_matrix(args.manifest, args.output)
        else:
            make_request(args.manifest, args.output, args.worker_root, args.runtime_root, args.attempt_id)
    except MatrixError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
