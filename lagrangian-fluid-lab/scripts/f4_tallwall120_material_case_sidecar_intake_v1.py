#!/usr/bin/env python3
"""Fail-closed intake for one F4 Tallwall120 material event-window sidecar.

This is a single-case evidence contract, not a runner.  It consumes bounded
JSON receipts and filesystem metadata only.  The DEV_07 trajectory HDF5 is
never opened or hashed, and this module never starts or controls a solver,
worker, GPU, or queue.  A sidecar can describe a completed diagnostic event
window, but this intake never mints T1/T2/qualification credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]

SCHEMA = "core.material.f4.tallwall120.case_sidecar_intake.v1"
MATERIAL_CASE_SIDECAR_SCHEMA = "core.material.f4.tallwall120.material_case_sidecar.v1"
COLLECTION_SCHEMA = "core.f4.tallwall120.production_collection.v1"
READER_SCHEMA = "local.f4.core_reader_smoke.stdout.v1"
ARCHIVE_SCHEMA = "core.verified_archive.v1"
PROPOSAL_SCHEMA = "core.material.f4.tallwall120.coarse_proposal.v1"
CONSISTENCY_SCHEMA = "core.material.f4.tallwall120.receipt_consistency_audit.v1"

OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
MAX_JSON_BYTES = 8 * 1024 * 1024
HDF5_SUFFIXES = {".h5", ".hdf5"}

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = f"{SCOPE_ID}_DEV_07"
CASE_SPLIT = "train"
SOURCE_HDF5 = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
SOURCE_SHA256 = "6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae"
SOURCE_BYTES = 2_067_911_708
SOURCE_FRAMES = 218
SOURCE_TRANSITIONS = 217
SOURCE_END_S = 4.340002980805959
EXPECTED_Q = 0.23437500000000008
EXPECTED_DP_M = 0.0075
EXPECTED_SEEDS = 512
EXPECTED_SUBSTEPS = 2
EXPECTED_NEIGHBOUR_VARIANT = "baseline24"
REQUIRED_EVENT_WINDOW_S = 8.68
MASS_CLOSURE_ERROR_MAX = 1.0e-12
UNKNOWN_FRACTION_MAX = 0.01
RELIABLE_COVERAGE_MIN = 1.0
REQUIRED_TERMINAL_MARKER = "material_event_window_terminal_v1"
REQUIRED_RIGHT_CENSOR_STATUS = "not_right_censored"

PROPOSAL = Path("reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
COLLECTION = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "collection-refresh-terminal32-formal-v1.json"
)
READER = Path("reports/F4-TALLWALL120-CORE-READER-SMOKE-2026-09-28.json")
CONSISTENCY_AUDIT = Path(
    "reports/F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json"
)
SOURCE_ARCHIVE = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/archive.json"
)

# This is the fresh namespace recorded by UPDATE-322's source-bound proposal.
# It is deliberately not created by this intake.
DEFAULT_OUTPUT_NAMESPACE = Path(
    "campaigns/core-v1/material/proposals/"
    "f4-tallwall120-production-dev-07/coarse-baseline24-s2-r001-source-6ae8ca70"
)
DEFAULT_SIDECAR = DEFAULT_OUTPUT_NAMESPACE / "product/material_case_sidecar.json"
DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-CASE-SIDECAR-INTAKE-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-CASE-SIDECAR-INTAKE-V1-2026-09-28.zh-CN.md"
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_relative(value: str | Path, *, field: str) -> str:
    text = str(value).replace("\\", "/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise ValueError(f"{field} must be a non-empty relative path without dot segments")
    if "" in path.parts:
        raise ValueError(f"{field} contains an empty path segment")
    return path.as_posix()


def _resolve(root: Path, value: str | Path, *, field: str) -> Path:
    root = Path(root).resolve()
    candidate_value = Path(value)
    if candidate_value.is_absolute():
        candidate = candidate_value.resolve()
    else:
        candidate = (root / _safe_relative(value, field=field)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{field} escapes the lab root") from error
    return candidate


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_json(root: Path, value: str | Path, *, role: str) -> dict[str, Any]:
    path = _resolve(root, value, field=f"{role}.path")
    if path.suffix.lower() in HDF5_SUFFIXES:
        raise ValueError(f"HDF5 content is outside the bounded JSON boundary: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        raise ValueError(f"bounded JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object for {role}: {path}")
    return payload


def _bounded_ref(
    root: Path,
    value: str | Path,
    role: str,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Read/hash only a bounded non-HDF5 metadata file."""

    path = _resolve(root, value, field=f"{role}.path")
    result: dict[str, Any] = {
        "role": role,
        "path": _relative(root, path),
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "expected_sha256": expected_sha256,
        "content_read": False,
        "content_hash_recomputed": False,
    }
    if path.suffix.lower() in HDF5_SUFFIXES:
        result["error"] = "hdf5_content_outside_bounded_json_boundary"
        return result
    if not path.is_file():
        result["error"] = "missing_file"
        return result
    size = path.stat().st_size
    result["bytes"] = size
    if size > MAX_JSON_BYTES:
        result["error"] = "file_exceeds_bounded_limit"
        return result
    data = path.read_bytes()
    digest = _sha256_bytes(data)
    result.update(
        {
            "sha256": digest,
            "expected_sha256_match": digest == expected_sha256 if expected_sha256 else None,
            "content_read": True,
            "content_hash_recomputed": True,
        }
    )
    return result


def _hdf5_metadata(root: Path, value: str | Path, declared_sha256: Any, declared_bytes: Any) -> dict[str, Any]:
    """Stat a trajectory only; never open, read, or hash its content."""

    path = _resolve(root, value, field="source_hdf5")
    exists = path.is_file()
    return {
        "path": _relative(root, path),
        "exists": exists,
        "bytes": path.stat().st_size if exists else None,
        "declared_sha256": declared_sha256,
        "declared_bytes": declared_bytes,
        "byte_size_match": bool(exists and path.stat().st_size == declared_bytes),
        "content_read": False,
        "content_hash_recomputed": False,
        "metadata_only": True,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _number(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _check(name: str, passed: bool, reason: str, **details: Any) -> dict[str, Any]:
    result = {"check": name, "passed": bool(passed), "reason": reason}
    result.update(details)
    return result


def _case_row(collection: Mapping[str, Any]) -> Mapping[str, Any]:
    reader_manifest = collection.get("reader_manifest")
    container = reader_manifest if isinstance(reader_manifest, Mapping) and isinstance(reader_manifest.get("cases"), list) else collection
    rows = container.get("cases", [])
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == CASE_ID]
    return matches[0] if len(matches) == 1 else {}


def _archive_output(archive: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    for item in archive.get("outputs", []):
        if isinstance(item, Mapping) and item.get("path") == path:
            return item
    return {}


def _claim_flags(sidecar: Mapping[str, Any]) -> dict[str, Any]:
    claims = _mapping(sidecar.get("claims"))
    return {
        "diagnostic_only": sidecar.get("diagnostic_only", claims.get("diagnostic_only")),
        "proposal_only": sidecar.get("proposal_only", claims.get("proposal_only")),
        "formal": sidecar.get("formal", claims.get("formal")),
        "formal_eligible": sidecar.get("formal_eligible", claims.get("formal_eligible")),
        "qualification": sidecar.get("qualification", claims.get("qualification")),
        "T1": sidecar.get("T1", claims.get("T1")),
        "T2": sidecar.get("T2", claims.get("T2")),
        "credit": sidecar.get("credit", claims.get("credit")),
        "qualification_credit": sidecar.get(
            "qualification_credit", claims.get("qualification_credit")
        ),
    }


def evaluate_sidecar(
    sidecar: Mapping[str, Any] | None,
    *,
    expected_namespace: str = DEFAULT_OUTPUT_NAMESPACE.as_posix(),
    expected_sidecar_path: str = DEFAULT_SIDECAR.as_posix(),
    expected_archive_sha256: str | None = None,
) -> dict[str, Any]:
    """Evaluate one in-memory sidecar without touching any trajectory file."""

    if sidecar is None:
        return {
            "present": False,
            "status": "missing",
            "case_id": CASE_ID,
            "failed_checks": ["sidecar_present"],
            "blocking_reasons": ["missing_material_case_sidecar"],
            "checks": [
                _check(
                    "sidecar_present",
                    False,
                    "default material case sidecar is missing; no terminal evidence is inferred",
                )
            ],
            "observed": {},
            "gate_projection": {
                "event_window_complete": False,
                "mass_closure": False,
                "unknown_gate": False,
                "reliable_coverage": False,
                "right_censor_clear": False,
            },
            "credit": 0,
        }

    source = _mapping(sidecar.get("source"))
    archive = _mapping(source.get("archive_manifest"))
    config = _mapping(sidecar.get("material_config"))
    output = _mapping(sidecar.get("output"))
    terminal = _mapping(sidecar.get("terminal"))
    metrics = _mapping(sidecar.get("metrics"))
    claims = _claim_flags(sidecar)
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            "sidecar_schema",
            sidecar.get("schema") == MATERIAL_CASE_SIDECAR_SCHEMA,
            "sidecar schema must be the registered single-case material schema",
            observed=sidecar.get("schema"),
            expected=MATERIAL_CASE_SIDECAR_SCHEMA,
        )
    )
    checks.append(
        _check(
            "dev07_case_scope_binding",
            sidecar.get("family") == FAMILY
            and sidecar.get("scope_id") == SCOPE_ID
            and sidecar.get("case_id") == CASE_ID
            and sidecar.get("split") == CASE_SPLIT,
            "family, scope, case, and split must bind DEV_07",
            observed={
                "family": sidecar.get("family"),
                "scope_id": sidecar.get("scope_id"),
                "case_id": sidecar.get("case_id"),
                "split": sidecar.get("split"),
            },
            expected={"family": FAMILY, "scope_id": SCOPE_ID, "case_id": CASE_ID, "split": CASE_SPLIT},
        )
    )
    checks.append(
        _check(
            "dev07_source_binding",
            source.get("hdf5") == SOURCE_HDF5
            and source.get("sha256") == SOURCE_SHA256
            and source.get("bytes") == SOURCE_BYTES,
            "sidecar source must bind the exact DEV_07 trajectory identity",
            observed={"hdf5": source.get("hdf5"), "sha256": source.get("sha256"), "bytes": source.get("bytes")},
            expected={"hdf5": SOURCE_HDF5, "sha256": SOURCE_SHA256, "bytes": SOURCE_BYTES},
        )
    )
    checks.append(
        _check(
            "archives_v2_identity_binding",
            archive.get("path") == SOURCE_ARCHIVE.as_posix()
            and archive.get("sha256") == source.get("archive_manifest_sha256")
            and (
                expected_archive_sha256 is None
                or archive.get("sha256") == expected_archive_sha256
            ),
            "sidecar must carry the exact archives-v2 manifest path and digest",
            observed={
                "path": archive.get("path"),
                "sha256": archive.get("sha256"),
                "source_archive_manifest_sha256": source.get("archive_manifest_sha256"),
            },
            expected={
                "path": SOURCE_ARCHIVE.as_posix(),
                "sha256": expected_archive_sha256 or "source-bound archive digest",
            },
        )
    )
    checks.append(
        _check(
            "case_q_binding",
            _finite(config.get("q"))
            and float(config.get("q")) == EXPECTED_Q
            and config.get("dp_m") == EXPECTED_DP_M
            and config.get("seeds") == EXPECTED_SEEDS
            and config.get("substeps") == EXPECTED_SUBSTEPS
            and config.get("neighbour_variant") == EXPECTED_NEIGHBOUR_VARIANT,
            "material q and coarse configuration must match the source-bound proposal",
            observed={key: config.get(key) for key in ("q", "dp_m", "seeds", "substeps", "neighbour_variant")},
            expected={
                "q": EXPECTED_Q,
                "dp_m": EXPECTED_DP_M,
                "seeds": EXPECTED_SEEDS,
                "substeps": EXPECTED_SUBSTEPS,
                "neighbour_variant": EXPECTED_NEIGHBOUR_VARIANT,
            },
        )
    )
    checks.append(
        _check(
            "fresh_output_namespace",
            output.get("namespace") == expected_namespace
            and output.get("sidecar_path") == expected_sidecar_path
            and output.get("fresh") is True
            and output.get("namespace_preexisting_at_start") is False
            and output.get("overwrite_allowed") is False
            and output.get("historical_trace_reuse") is False,
            "sidecar output must be fresh, namespace-bound, and non-overwriting",
            observed=dict(output),
            expected={
                "namespace": expected_namespace,
                "sidecar_path": expected_sidecar_path,
                "fresh": True,
                "namespace_preexisting_at_start": False,
                "overwrite_allowed": False,
                "historical_trace_reuse": False,
            },
        )
    )

    terminal_end = _number(terminal.get("event_window_end_s"))
    event_window_complete = (
        terminal.get("terminal_marker") == REQUIRED_TERMINAL_MARKER
        and terminal.get("terminal_marker_present") is True
        and terminal.get("status") == "complete"
        and terminal.get("execution_complete") is True
        and terminal.get("event_window_status") == "complete"
        and terminal.get("event_window_complete") is True
        and terminal_end is not None
        and terminal_end >= REQUIRED_EVENT_WINDOW_S
    )
    checks.append(
        _check(
            "event_window_terminal_marker",
            event_window_complete,
            "terminal marker, complete status, and the full 8.68 s event window are required",
            observed={
                "terminal_marker": terminal.get("terminal_marker"),
                "terminal_marker_present": terminal.get("terminal_marker_present"),
                "status": terminal.get("status"),
                "execution_complete": terminal.get("execution_complete"),
                "event_window_status": terminal.get("event_window_status"),
                "event_window_complete": terminal.get("event_window_complete"),
                "event_window_end_s": terminal_end,
            },
            expected={
                "terminal_marker": REQUIRED_TERMINAL_MARKER,
                "status": "complete",
                "event_window_status": "complete",
                "event_window_end_s_min": REQUIRED_EVENT_WINDOW_S,
            },
        )
    )
    mass_error = _number(metrics.get("mass_closure_error"))
    mass_pass = (
        metrics.get("mass_closed") is True
        and metrics.get("mass_closure_pass") is True
        and mass_error is not None
        and abs(mass_error) <= MASS_CLOSURE_ERROR_MAX
    )
    checks.append(
        _check(
            "mass_closure_marker",
            mass_pass,
            "mass closure must be explicit and within the fixed bound",
            observed={
                "mass_closed": metrics.get("mass_closed"),
                "mass_closure_pass": metrics.get("mass_closure_pass"),
                "mass_closure_error": mass_error,
            },
            expected={"mass_closed": True, "mass_closure_pass": True, "absolute_error_max": MASS_CLOSURE_ERROR_MAX},
        )
    )
    unknown = _number(metrics.get("unknown_fraction_max"))
    unknown_pass = (
        metrics.get("unknown_gate_pass") is True
        and unknown is not None
        and 0.0 <= unknown <= UNKNOWN_FRACTION_MAX
    )
    checks.append(
        _check(
            "unknown_fraction_marker",
            unknown_pass,
            "unknown fraction must be explicit and remain at or below 1%",
            observed={"unknown_fraction_max": unknown, "unknown_gate_pass": metrics.get("unknown_gate_pass")},
            expected={"unknown_fraction_max": UNKNOWN_FRACTION_MAX, "unknown_gate_pass": True},
        )
    )
    coverage = _number(metrics.get("reliable_coverage"))
    coverage_pass = (
        metrics.get("reliable_coverage_pass") is True
        and coverage is not None
        and RELIABLE_COVERAGE_MIN <= coverage <= 1.0
    )
    checks.append(
        _check(
            "reliable_coverage_marker",
            coverage_pass,
            "reliable event-window coverage must be explicit and complete",
            observed={"reliable_coverage": coverage, "reliable_coverage_pass": metrics.get("reliable_coverage_pass")},
            expected={"reliable_coverage_min": RELIABLE_COVERAGE_MIN, "reliable_coverage_pass": True},
        )
    )
    right_censor_pass = (
        terminal.get("right_censor_status") == REQUIRED_RIGHT_CENSOR_STATUS
        and metrics.get("right_censor_status") == REQUIRED_RIGHT_CENSOR_STATUS
    )
    checks.append(
        _check(
            "right_censor_terminal_status",
            right_censor_pass,
            "terminal and metric projections must explicitly clear right censoring",
            observed={
                "terminal_right_censor_status": terminal.get("right_censor_status"),
                "metrics_right_censor_status": metrics.get("right_censor_status"),
            },
            expected={"right_censor_status": REQUIRED_RIGHT_CENSOR_STATUS},
        )
    )

    flags_pass = (
        claims.get("diagnostic_only") is True
        and claims.get("proposal_only") is False
        and claims.get("formal") is False
        and claims.get("formal_eligible") is False
        and claims.get("qualification") is False
        and claims.get("T1") is False
        and claims.get("T2") is False
        and claims.get("credit") == 0
        and claims.get("qualification_credit") == 0
    )
    checks.append(
        _check(
            "diagnostic_formal_credit_flags",
            flags_pass,
            "a sidecar must remain diagnostic-only and may not self-assert T1/T2 or credit",
            observed=claims,
            expected={
                "diagnostic_only": True,
                "proposal_only": False,
                "formal": False,
                "formal_eligible": False,
                "qualification": False,
                "T1": False,
                "T2": False,
                "credit": 0,
                "qualification_credit": 0,
            },
        )
    )

    failed = [item["check"] for item in checks if not item["passed"]]
    reason_map = {
        "sidecar_schema": "sidecar_schema_mismatch",
        "dev07_case_scope_binding": "dev07_case_or_scope_mismatch",
        "dev07_source_binding": "dev07_source_binding_mismatch",
        "archives_v2_identity_binding": "archives_identity_mismatch",
        "case_q_binding": "case_q_or_material_config_mismatch",
        "fresh_output_namespace": "fresh_output_namespace_invalid",
        "event_window_terminal_marker": "missing_or_incomplete_event_window_terminal",
        "mass_closure_marker": "mass_closure_missing_or_failed",
        "unknown_fraction_marker": "unknown_fraction_missing_or_failed",
        "reliable_coverage_marker": "reliable_coverage_missing_or_failed",
        "right_censor_terminal_status": "right_censored_or_unresolved",
        "diagnostic_formal_credit_flags": "formal_or_credit_claim_present",
    }
    blocking_reasons = [reason_map.get(name, name) for name in failed]
    status = "complete" if not blocking_reasons else "blocked"
    return {
        "present": True,
        "status": status,
        "case_id": sidecar.get("case_id"),
        "failed_checks": failed,
        "blocking_reasons": list(dict.fromkeys(blocking_reasons)),
        "checks": checks,
        "observed": {
            "source": dict(source),
            "material_config": dict(config),
            "output": dict(output),
            "terminal": dict(terminal),
            "metrics": dict(metrics),
            "claims": claims,
        },
        "gate_projection": {
            "event_window_complete": event_window_complete,
            "mass_closure": mass_pass,
            "unknown_gate": unknown_pass,
            "reliable_coverage": coverage_pass,
            "right_censor_clear": right_censor_pass,
        },
        "credit": 0,
    }


def _load_optional_sidecar(root: Path, sidecar_path: str | Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    path = _resolve(root, sidecar_path, field="sidecar")
    reference: dict[str, Any] = {
        "path": _relative(root, path),
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "content_read": False,
        "content_hash_recomputed": False,
        "error": None,
    }
    if path.suffix.lower() in HDF5_SUFFIXES:
        reference["error"] = "hdf5_sidecar_forbidden"
        return None, reference
    if not path.is_file():
        reference["error"] = "missing_file"
        return None, reference
    size = path.stat().st_size
    reference["bytes"] = size
    if size > MAX_JSON_BYTES:
        reference["error"] = "file_exceeds_bounded_limit"
        return None, reference
    try:
        data = path.read_bytes()
        reference.update(
            {
                "sha256": _sha256_bytes(data),
                "content_read": True,
                "content_hash_recomputed": True,
            }
        )
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("sidecar must be a JSON object")
        return payload, reference
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        reference["error"] = f"invalid_json:{type(error).__name__}"
        return None, reference


def _read_inputs(root: Path) -> dict[str, dict[str, Any]]:
    return {
        "proposal": _read_json(root, PROPOSAL, role="proposal"),
        "collection": _read_json(root, COLLECTION, role="collection_manifest"),
        "reader": _read_json(root, READER, role="reader_smoke"),
        "consistency": _read_json(root, CONSISTENCY_AUDIT, role="consistency_audit"),
        "archive": _read_json(root, SOURCE_ARCHIVE, role="source_archive"),
    }


def build_report(
    root: str | Path = LAB_ROOT,
    *,
    sidecar_path: str | Path = DEFAULT_SIDECAR,
) -> dict[str, Any]:
    """Build the deterministic single-case intake report."""

    root = Path(root).resolve()
    inputs = _read_inputs(root)
    proposal = inputs["proposal"]
    collection = inputs["collection"]
    reader = inputs["reader"]
    consistency = inputs["consistency"]
    archive = inputs["archive"]
    proposal_target = _mapping(proposal.get("target"))
    proposal_params = _mapping(proposal.get("parameter_contract"))
    proposal_manifest = _mapping(_mapping(proposal.get("source_manifest_contract")).get("direct_source_manifest"))
    proposal_collection = _mapping(_mapping(proposal.get("source_manifest_contract")).get("core_collection_manifest"))
    row = _case_row(collection)
    row_trajectory = _mapping(row.get("trajectory"))
    archive_trajectory = _archive_output(archive, "product/trajectory.h5")

    proposal_ref = _bounded_ref(root, PROPOSAL, "proposal")
    collection_ref = _bounded_ref(root, COLLECTION, "collection_manifest")
    reader_ref = _bounded_ref(root, READER, "reader_smoke")
    consistency_ref = _bounded_ref(root, CONSISTENCY_AUDIT, "consistency_audit")
    archive_ref = _bounded_ref(root, SOURCE_ARCHIVE, "source_archive", expected_sha256=proposal_manifest.get("sha256"))
    source_metadata = _hdf5_metadata(
        root,
        SOURCE_HDF5,
        proposal_target.get("source_sha256"),
        proposal_target.get("source_bytes"),
    )
    expected_namespace = DEFAULT_OUTPUT_NAMESPACE.as_posix()
    sidecar, sidecar_ref = _load_optional_sidecar(root, sidecar_path)
    expected_sidecar_path = sidecar_ref["path"]
    sidecar_result = evaluate_sidecar(
        sidecar,
        expected_namespace=expected_namespace,
        expected_sidecar_path=expected_sidecar_path,
        expected_archive_sha256=archive_ref.get("sha256"),
    )

    reader_result = _mapping(reader.get("reader_result"))
    consistency_archives = _mapping(consistency.get("archives_path_binding"))
    checks = [
        _check(
            "proposal_identity",
            proposal.get("schema") == PROPOSAL_SCHEMA
            and proposal_target.get("family") == FAMILY
            and proposal_target.get("scope_id") == SCOPE_ID
            and proposal_target.get("case_id") == CASE_ID
            and proposal_target.get("source_hdf5") == SOURCE_HDF5
            and proposal_target.get("source_sha256") == SOURCE_SHA256
            and proposal_target.get("source_bytes") == SOURCE_BYTES,
            "coarse proposal must bind the exact DEV_07 source identity",
            observed={
                "schema": proposal.get("schema"),
                "family": proposal_target.get("family"),
                "scope_id": proposal_target.get("scope_id"),
                "case_id": proposal_target.get("case_id"),
                "source_hdf5": proposal_target.get("source_hdf5"),
                "source_sha256": proposal_target.get("source_sha256"),
                "source_bytes": proposal_target.get("source_bytes"),
            },
        ),
        _check(
            "proposal_q_binding",
            proposal_params.get("q") == EXPECTED_Q
            and proposal_params.get("dp_m") == EXPECTED_DP_M
            and proposal_params.get("seeds") == EXPECTED_SEEDS
            and proposal_params.get("substeps") == EXPECTED_SUBSTEPS
            and proposal_params.get("neighbour_variant") == EXPECTED_NEIGHBOUR_VARIANT,
            "proposal q and material configuration must be exact",
            observed={key: proposal_params.get(key) for key in ("q", "dp_m", "seeds", "substeps", "neighbour_variant")},
        ),
        _check(
            "proposal_archive_identity",
            proposal_manifest.get("path") == SOURCE_ARCHIVE.as_posix()
            and proposal_manifest.get("sha256") == archive_ref.get("sha256")
            and proposal_manifest.get("schema") == ARCHIVE_SCHEMA,
            "proposal direct source manifest must bind the bounded archives-v2 manifest",
            observed={
                "path": proposal_manifest.get("path"),
                "declared_sha256": proposal_manifest.get("sha256"),
                "observed_sha256": archive_ref.get("sha256"),
                "schema": proposal_manifest.get("schema"),
            },
        ),
        _check(
            "collection_manifest_identity",
            collection.get("schema") == COLLECTION_SCHEMA
            and collection.get("family") == FAMILY
            and collection.get("scope_id") == SCOPE_ID
            and proposal_collection.get("path") == COLLECTION.as_posix()
            and proposal_collection.get("sha256") == collection_ref.get("sha256"),
            "collection manifest path, schema, scope, and proposal SHA must agree",
            observed={
                "schema": collection.get("schema"),
                "family": collection.get("family"),
                "scope_id": collection.get("scope_id"),
                "path": proposal_collection.get("path"),
                "declared_sha256": proposal_collection.get("sha256"),
                "observed_sha256": collection_ref.get("sha256"),
            },
        ),
        _check(
            "collection_dev07_source_identity",
            row.get("case_id") == CASE_ID
            and row.get("family") == FAMILY
            and row.get("split") == CASE_SPLIT
            and row_trajectory.get("sha256") == SOURCE_SHA256
            and row_trajectory.get("path") == SOURCE_HDF5,
            "collection DEV_07 row must carry the exact source path and SHA",
            observed={
                "case_id": row.get("case_id"),
                "family": row.get("family"),
                "split": row.get("split"),
                "source_hdf5": row_trajectory.get("path"),
                "source_sha256": row_trajectory.get("sha256"),
            },
        ),
        _check(
            "reader_identity_and_non_t2",
            reader.get("schema") == READER_SCHEMA
            and reader.get("manifest") == COLLECTION.as_posix()
            and reader.get("manifest_sha256") == collection_ref.get("sha256")
            and reader.get("family") == FAMILY
            and reader.get("scope_id") == SCOPE_ID
            and reader_result.get("diagnostic_only") is True
            and reader_result.get("reader_formal_eligible") is False
            and reader_result.get("formal_credit_granted_by_this_smoke") is False
            and reader_result.get("t2_credit_granted_by_this_smoke") is False
            and reader_result.get("qualification_credit") == 0,
            "reader smoke must bind the current manifest and remain diagnostic/non-T2",
            observed={
                "schema": reader.get("schema"),
                "manifest": reader.get("manifest"),
                "manifest_sha256": reader.get("manifest_sha256"),
                "current_manifest_sha256": collection_ref.get("sha256"),
                "reader_result": dict(reader_result),
            },
        ),
        _check(
            "archives_manifest_output_identity",
            archive.get("schema") == ARCHIVE_SCHEMA
            and archive.get("execution_status") == "succeeded"
            and archive.get("job_id") == "f4-tallwall120-production-dev-07"
            and archive_trajectory.get("path") == "product/trajectory.h5"
            and archive_trajectory.get("sha256") == SOURCE_SHA256
            and archive_trajectory.get("bytes") == SOURCE_BYTES,
            "archives-v2 manifest output must bind the exact trajectory metadata",
            observed={
                "schema": archive.get("schema"),
                "execution_status": archive.get("execution_status"),
                "job_id": archive.get("job_id"),
                "trajectory": dict(archive_trajectory),
            },
        ),
        _check(
            "archives_consistency_identity",
            consistency.get("schema") == CONSISTENCY_SCHEMA
            and consistency_archives.get("proposal_target_hdf5") == SOURCE_HDF5
            and consistency_archives.get("source_sha256_match") is True,
            "receipt consistency must bind the proposal source and preserve SHA identity",
            observed={
                "schema": consistency.get("schema"),
                "archives_path_binding": dict(consistency_archives),
            },
        ),
        _check(
            "fresh_namespace_absent",
            not _resolve(root, expected_namespace, field="fresh_output_namespace").exists(),
            "fresh output namespace must be absent before an authorized producer run",
            observed={
                "namespace": expected_namespace,
                "exists": _resolve(root, expected_namespace, field="fresh_output_namespace").exists(),
            },
        ),
        _check(
            "source_hdf5_metadata_only",
            source_metadata["exists"] is True
            and source_metadata["byte_size_match"] is True
            and source_metadata["content_read"] is False
            and source_metadata["content_hash_recomputed"] is False,
            "trajectory HDF5 may be stat-checked but never opened or rehashed",
            observed=source_metadata,
        ),
        _check(
            "sidecar_path_under_fresh_namespace",
            sidecar_ref.get("path", "").startswith(expected_namespace.rstrip("/") + "/")
            and Path(str(sidecar_ref.get("path", ""))).suffix.lower() == ".json",
            "the default intake target is the one fresh namespace-bound JSON sidecar",
            observed={"path": sidecar_ref.get("path")},
            expected={"namespace_prefix": expected_namespace + "/", "suffix": ".json"},
        ),
        _check(
            "sidecar_terminal_intake",
            sidecar_result.get("present") is True and sidecar_result.get("status") == "complete",
            "a complete event-window sidecar is required; missing/partial input fails closed",
            observed={
                "present": sidecar_result.get("present"),
                "status": sidecar_result.get("status"),
                "blocking_reasons": sidecar_result.get("blocking_reasons"),
            },
        ),
    ]

    blocking_reasons = [item["check"] for item in checks if not item["passed"]]
    for reason in sidecar_result.get("blocking_reasons", []):
        if reason not in blocking_reasons:
            blocking_reasons.append(reason)
    # Keep the known archives-v1/v2 path drift visible even when all other
    # bounded checks are sound; the reader smoke cannot be silently promoted.
    if consistency_archives.get("exact_path_match") is not True:
        blocking_reasons.append("archives_v1_v2_path_drift")
    if reader.get("manifest_sha256") != collection_ref.get("sha256"):
        blocking_reasons.append("reader_manifest_sha_drift")
    blocking_reasons = list(dict.fromkeys(blocking_reasons))

    report_status = "blocked_fail_closed" if blocking_reasons else "case_sidecar_intake_ready_non_authorizing"
    return {
        "schema": SCHEMA,
        "observed_at_utc": OBSERVED_AT_UTC,
        "status": report_status,
        "decision": "diagnostic_only_single_case_sidecar_intake",
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "case_id": CASE_ID,
            "split": CASE_SPLIT,
            "focus": "one F4 Tallwall120 material event-window sidecar",
        },
        "required_contract": {
            "source_hdf5": SOURCE_HDF5,
            "source_sha256": SOURCE_SHA256,
            "source_bytes": SOURCE_BYTES,
            "q": EXPECTED_Q,
            "dp_m": EXPECTED_DP_M,
            "seeds": EXPECTED_SEEDS,
            "substeps": EXPECTED_SUBSTEPS,
            "neighbour_variant": EXPECTED_NEIGHBOUR_VARIANT,
            "event_window_s": REQUIRED_EVENT_WINDOW_S,
            "mass_closure_error_max": MASS_CLOSURE_ERROR_MAX,
            "unknown_fraction_max": UNKNOWN_FRACTION_MAX,
            "reliable_coverage_min": RELIABLE_COVERAGE_MIN,
            "terminal_marker": REQUIRED_TERMINAL_MARKER,
            "right_censor_status": REQUIRED_RIGHT_CENSOR_STATUS,
        },
        "input_bindings": {
            "proposal": proposal_ref,
            "collection_manifest": collection_ref,
            "reader_smoke": reader_ref,
            "consistency_audit": consistency_ref,
            "source_archive": archive_ref,
            "sidecar": sidecar_ref,
        },
        "source_binding": {
            "proposal_target": dict(proposal_target),
            "collection_case": {
                "case_id": row.get("case_id"),
                "family": row.get("family"),
                "split": row.get("split"),
                "source_hdf5": row_trajectory.get("path"),
                "source_sha256": row_trajectory.get("sha256"),
            },
            "reader": {
                "manifest": reader.get("manifest"),
                "manifest_sha256": reader.get("manifest_sha256"),
                "current_manifest_sha256": collection_ref.get("sha256"),
                "diagnostic_only": reader_result.get("diagnostic_only"),
                "formal_eligible": reader_result.get("reader_formal_eligible"),
                "t2_credit": reader_result.get("t2_credit_granted_by_this_smoke"),
            },
            "archives": {
                "manifest_path": SOURCE_ARCHIVE.as_posix(),
                "manifest_sha256": archive_ref.get("sha256"),
                "trajectory_output": dict(archive_trajectory),
                "consistency_path_match": consistency_archives.get("exact_path_match"),
                "consistency_source_sha256_match": consistency_archives.get("source_sha256_match"),
            },
            "trajectory_hdf5": source_metadata,
        },
        "fresh_output_namespace": {
            "namespace": expected_namespace,
            "sidecar_path": expected_sidecar_path,
            "exists": _resolve(root, expected_namespace, field="fresh_output_namespace").exists(),
            "overwrite_allowed": False,
            "historical_trace_reuse": False,
            "execution_authorized": False,
        },
        "case_sidecar_intake": sidecar_result,
        "checks": checks,
        "blocking_reasons": blocking_reasons,
        "scientific_boundary": {
            "reader_smoke_is_not_t2": True,
            "proposal_is_not_t2": True,
            "single_case_sidecar_is_not_qualification": True,
            "right_censored_event_window_is_not_imputed": True,
            "partial_credit_is_forbidden": True,
        },
        "qualification": {
            "diagnostic_only": True,
            "contract_only": True,
            "formal": False,
            "formal_eligible": False,
            "qualification": False,
            "T1": False,
            "T2": False,
            "credit": 0,
            "qualification_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "mutation": 0,
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "hdf5_metadata_only": True,
            "hdf5_content_read": False,
            "hdf5_hash_recomputed": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_started": False,
            "production_hdf5_mutated": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    if report.get("status") not in {"blocked_fail_closed", "case_sidecar_intake_ready_non_authorizing"}:
        errors.append("status")
    qualification = _mapping(report.get("qualification"))
    for key, expected in {
        "diagnostic_only": True,
        "contract_only": True,
        "formal": False,
        "formal_eligible": False,
        "qualification": False,
        "T1": False,
        "T2": False,
        "credit": 0,
        "qualification_credit": 0,
    }.items():
        if qualification.get(key) != expected:
            errors.append(f"qualification.{key}")
    boundary = _mapping(report.get("input_boundary"))
    for key, expected in {
        "bounded_json_only": True,
        "hdf5_metadata_only": True,
        "hdf5_content_read": False,
        "hdf5_hash_recomputed": False,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
    }.items():
        if boundary.get(key) != expected:
            errors.append(f"input_boundary.{key}")
    case_intake = _mapping(report.get("case_sidecar_intake"))
    if report.get("status") == "blocked_fail_closed" and case_intake.get("present") is False:
        if "missing_material_case_sidecar" not in report.get("blocking_reasons", []):
            errors.append("missing_sidecar_blocker")
    return errors


def verify_report(
    report_path: str | Path = DEFAULT_REPORT,
    root: str | Path = LAB_ROOT,
    *,
    sidecar_path: str | Path = DEFAULT_SIDECAR,
) -> dict[str, Any]:
    path = _resolve(Path(root), report_path, field="report")
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise TypeError("report must be a JSON object")
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid report: " + ", ".join(errors))
    expected = build_report(root, sidecar_path=sidecar_path)
    if report != expected:
        raise ValueError("checked-in report does not exactly match build_report()")
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    intake = _mapping(report.get("case_sidecar_intake"))
    qualification = _mapping(report.get("qualification"))
    boundary = _mapping(report.get("input_boundary"))
    blockers = report.get("blocking_reasons", [])
    blocker_text = ", ".join(str(item) for item in blockers) or "无"
    return "\n".join(
        [
            "# F4 Tallwall120 material case sidecar intake V1",
            "",
            f"- status: `{report.get('status')}`",
            f"- case: `{report.get('scope', {}).get('case_id')}`",
            f"- q: `{report.get('required_contract', {}).get('q')}`",
            f"- sidecar status: `{intake.get('status')}`; present=`{intake.get('present')}`",
            f"- blockers: {blocker_text}",
            "",
            "## 边界",
            "",
            "本 intake 只消费 bounded JSON 与文件系统元数据；trajectory HDF5 只允许 stat，未打开、未重哈希。未启动 solver、worker、GPU 或 queue。",
            "",
            "## 单案例契约",
            "",
            "DEV_07 必须绑定 proposal、archives-v2 manifest、collection/reader identity、q、fresh output namespace、event-window terminal marker、mass closure、unknown fraction、reliable coverage 与 right-censor status。sidecar 缺失、部分终态或删失窗口均 fail-closed。",
            "",
            "## 资格边界",
            "",
            f"diagnostic_only=`{qualification.get('diagnostic_only')}`，formal=`{qualification.get('formal')}`，formal_eligible=`{qualification.get('formal_eligible')}`，T1=`{qualification.get('T1')}`，T2=`{qualification.get('T2')}`，credit=`{qualification.get('credit')}`。reader smoke 与 proposal 均不被提升为 T2。",
            "",
            "## Mutation / execution",
            "",
            f"registry/ledger/denominator/gate/completion mutation 均为 `0`；HDF5 content read=`{boundary.get('hdf5_content_read')}`，HDF5 hash recomputed=`{boundary.get('hdf5_hash_recomputed')}`，solver/worker/GPU/queue started 均为 `False`。",
            "",
            "机器报告由 `build_report()` 精确绑定；本文件只是其中文 companion。",
            "",
        ]
    )


def write_outputs(
    report: Mapping[str, Any],
    *,
    output: str | Path = DEFAULT_REPORT,
    zh_output: str | Path = DEFAULT_ZH_REPORT,
    root: str | Path = LAB_ROOT,
) -> None:
    root = Path(root).resolve()
    output_path = _resolve(root, output, field="output")
    zh_path = _resolve(root, zh_output, field="zh_output")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    output_partial = output_path.with_name(output_path.name + ".partial")
    zh_partial = zh_path.with_name(zh_path.name + ".partial")
    output_partial.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    zh_partial.write_text(render_markdown(report), encoding="utf-8")
    output_partial.replace(output_path)
    zh_partial.replace(zh_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    args = parser.parse_args(argv)
    report = build_report(args.lab_root, sidecar_path=args.sidecar)
    write_outputs(report, output=args.output, zh_output=args.zh_output, root=args.lab_root)
    print(json.dumps({
        "output": str(_resolve(args.lab_root, args.output, field="output")),
        "schema": report["schema"],
        "status": report["status"],
        "sidecar_status": report["case_sidecar_intake"]["status"],
        "formal": report["qualification"]["formal"],
        "T2": report["qualification"]["T2"],
        "credit": report["qualification"]["credit"],
        "mutation": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
