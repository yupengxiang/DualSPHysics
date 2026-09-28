#!/usr/bin/env python3
"""Fail-closed intake for fresh F4 Tallwall120 material terminal evidence.

The intake is an evidence contract, not a launcher.  It consumes bounded JSON
receipts and filesystem metadata only.  In particular, the DEV_07 trajectory
HDF5 is never opened or rehashed here, and this module never starts or controls
solver, worker, GPU, or queue processes.  Existing short-window material
diagnostics are retained as negative provenance; they cannot be promoted to a
fresh terminal result or to T2 credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.material.f4.tallwall120.terminal_evidence_intake.v1"
TERMINAL_EVIDENCE_SCHEMA = "core.material.f4.tallwall120.terminal_evidence.v1"
OBSERVED_AT_UTC = "2026-09-28T00:00:00Z"
MAX_JSON_BYTES = 8 * 1024 * 1024
HDF5_SUFFIXES = {".h5", ".hdf5"}

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
CASE_ID = "F4_resting_pool_laminar_tallwall120_x_v1_DEV_07"
SOURCE_HDF5 = (
    "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/"
    "f4-tallwall120-production-dev-07/product/trajectory.h5"
)
SOURCE_SHA256 = "6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae"
SOURCE_BYTES = 2_067_911_708
SOURCE_FRAMES = 218
SOURCE_TRANSITIONS = 217
SOURCE_END_S = 4.340002980805959
REQUIRED_EVENT_WINDOW_S = 8.68
EXPECTED_Q = 0.23437500000000008
EXPECTED_DP_M = 0.0075
EXPECTED_SEEDS = 512
EXPECTED_SUBSTEPS = 2
EXPECTED_NEIGHBOUR_VARIANT = "baseline24"
UNKNOWN_LIMIT = 0.01
MASS_CLOSURE_ERROR_LIMIT = 1.0e-12

PROPOSAL = Path("reports/F4-TALLWALL120-MATERIAL-COARSE-PROPOSAL-2026-09-28.json")
COLLECTION = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "collection-refresh-terminal32-formal-v1.json"
)
READER = Path("reports/F4-TALLWALL120-CORE-READER-SMOKE-2026-09-28.json")
DIAGNOSTIC = Path(
    "reports/F4-TALLWALL120-DEV07-MATERIAL-BASELINE24-DIAGNOSTIC-2026-09-28.json"
)
CONSISTENCY_AUDIT = Path(
    "reports/F4-TALLWALL120-MATERIAL-RECEIPT-CONSISTENCY-AUDIT-2026-09-28.json"
)
HOST_IO_PROJECTION = Path(
    "reports/F4-TALLWALL120-COARSE-HOST-IO-ADMISSION-PROJECTION-2026-09-28.json"
)
DEFAULT_OUTPUT_NAMESPACE = (
    "campaigns/core-v1/material/proposals/"
    "f4-tallwall120-production-dev-07/coarse-baseline24-s2-r001-source-6ae8ca70"
)
TERMINAL_EVIDENCE = Path(
    DEFAULT_OUTPUT_NAMESPACE + "/product/tallwall120_material.json"
)
DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F4-TALLWALL120-MATERIAL-TERMINAL-EVIDENCE-INTAKE-V1-2026-09-28.zh-CN.md"
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash only bounded non-HDF5 files."""

    path = Path(path)
    if path.suffix.lower() in HDF5_SUFFIXES:
        raise ValueError(f"HDF5 content is outside the intake boundary: {path}")
    size = path.stat().st_size
    if size > MAX_JSON_BYTES:
        raise ValueError(f"file exceeds the bounded intake limit: {path} ({size} bytes)")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_json(root: Path, value: str | Path) -> dict[str, Any]:
    path = _resolve(root, value)
    if path.suffix.lower() in HDF5_SUFFIXES:
        raise ValueError(f"HDF5 JSON read is forbidden: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"JSON input exceeds bound: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object: {path}")
    return payload


def _small_ref(root: Path, value: str | Path, role: str) -> dict[str, Any]:
    path = _resolve(root, value)
    result: dict[str, Any] = {
        "role": role,
        "path": _relative(root, path),
        "exists": path.is_file(),
        "bytes": None,
        "sha256": None,
        "content_read": False,
    }
    if path.suffix.lower() in HDF5_SUFFIXES:
        result["error"] = "hdf5_outside_bounded_json_boundary"
        return result
    if not path.is_file():
        result["error"] = "missing_file"
        return result
    result["bytes"] = path.stat().st_size
    if result["bytes"] > MAX_JSON_BYTES:
        result["error"] = "file_exceeds_bounded_limit"
        return result
    result["sha256"] = sha256_file(path)
    return result


def _hdf5_metadata(root: Path, value: str | Path, declared_sha256: str) -> dict[str, Any]:
    """Stat the trajectory without opening, hashing, or reading its content."""

    path = _resolve(root, value)
    exists = path.is_file()
    return {
        "path": _relative(root, path),
        "exists": exists,
        "bytes": path.stat().st_size if exists else None,
        "declared_sha256": declared_sha256,
        "content_read": False,
        "content_hash_recomputed": False,
        "metadata_only": True,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(value: Any) -> bool:
    return value is True


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _number(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and "" not in path.parts


def _check(
    name: str,
    passed: bool,
    reason: str,
    *,
    observed: Any = None,
    expected: Any = None,
) -> dict[str, Any]:
    return {
        "check": name,
        "passed": bool(passed),
        "reason": reason,
        "observed": observed,
        "expected": expected,
    }


def _output_identity_digest(identity: Mapping[str, Any]) -> str | None:
    try:
        return _sha256_bytes(_canonical(dict(identity)))
    except (TypeError, ValueError):
        return None


def _terminal_check_result(
    name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None
) -> dict[str, Any]:
    return _check(name, passed, reason, observed=observed, expected=expected)


def evaluate_terminal_evidence(
    evidence: Mapping[str, Any] | None,
    *,
    expected_namespace: str = DEFAULT_OUTPUT_NAMESPACE,
) -> dict[str, Any]:
    """Validate one terminal sidecar without reading any trajectory content.

    The function is intentionally usable with an in-memory mapping so tests can
    exercise the contract without creating or reading production artifacts.
    """

    checks: list[dict[str, Any]] = []
    if evidence is None:
        checks.append(
            _terminal_check_result(
                "fresh_terminal_evidence_present",
                False,
                "fresh terminal evidence sidecar is missing",
            )
        )
        return {
            "present": False,
            "status": "missing",
            "checks": checks,
            "failed_checks": [item["check"] for item in checks if not item["passed"]],
            "blocking_reasons": ["missing_fresh_terminal_evidence"],
            "observed": {},
            "gate_projection": {
                "mass_closure": False,
                "unknown_gate": False,
                "coverage_reported": False,
                "event_window_complete": False,
            },
        }

    data = _mapping(evidence)
    source = _mapping(data.get("source"))
    config = _mapping(data.get("material_config"))
    attempt = _mapping(data.get("attempt"))
    terminal = _mapping(data.get("terminal"))
    metrics = _mapping(data.get("metrics"))

    checks.append(
        _terminal_check_result(
            "fresh_terminal_evidence_present", True, "terminal evidence object supplied"
        )
    )
    checks.append(
        _terminal_check_result(
            "terminal_schema",
            data.get("schema") == TERMINAL_EVIDENCE_SCHEMA,
            "terminal evidence schema must be the registered V1 sidecar schema",
            observed=data.get("schema"),
            expected=TERMINAL_EVIDENCE_SCHEMA,
        )
    )
    checks.append(
        _terminal_check_result(
            "terminal_source_and_case_binding",
            source.get("case_id") == CASE_ID
            and source.get("scope_id") == SCOPE_ID
            and source.get("source_hdf5") == SOURCE_HDF5
            and source.get("source_sha256") == SOURCE_SHA256,
            "terminal source path, case, scope, and trajectory SHA must match DEV_07",
            observed={
                "case_id": source.get("case_id"),
                "scope_id": source.get("scope_id"),
                "source_hdf5": source.get("source_hdf5"),
                "source_sha256": source.get("source_sha256"),
            },
            expected={
                "case_id": CASE_ID,
                "scope_id": SCOPE_ID,
                "source_hdf5": SOURCE_HDF5,
                "source_sha256": SOURCE_SHA256,
            },
        )
    )
    config_expected = {
        "q": EXPECTED_Q,
        "dp_m": EXPECTED_DP_M,
        "seeds": EXPECTED_SEEDS,
        "substeps": EXPECTED_SUBSTEPS,
        "neighbour_variant": EXPECTED_NEIGHBOUR_VARIANT,
        "source_frames": SOURCE_FRAMES,
        "source_transitions": SOURCE_TRANSITIONS,
        "required_event_window_s": REQUIRED_EVENT_WINDOW_S,
    }
    config_observed = {key: config.get(key) for key in config_expected}
    config_match = all(config_observed[key] == value for key, value in config_expected.items())
    checks.append(
        _terminal_check_result(
            "terminal_material_config_exact",
            config_match,
            "terminal material config must match the source-bound proposal",
            observed=config_observed,
            expected=config_expected,
        )
    )

    output_identity = _mapping(attempt.get("output_identity"))
    identity_digest = _output_identity_digest(output_identity)
    identity_paths = [output_identity.get(name) for name in (
        "result_json", "trace_hdf5", "diagnosis_json", "checkpoint_manifest"
    )]
    identity_paths_valid = all(
        _safe_relative_path(path)
        and str(path).startswith(expected_namespace.rstrip("/") + "/")
        and Path(str(path)).suffix.lower() in {".json", ".h5"}
        for path in identity_paths
    )
    attempt_match = (
        isinstance(attempt.get("attempt_id"), str)
        and bool(attempt.get("attempt_id"))
        and _bool(attempt.get("fresh_attempt"))
        and attempt.get("output_namespace") == expected_namespace
        and attempt.get("namespace_preexisting_at_start") is False
        and attempt.get("historical_trace_reuse") is False
        and attempt.get("overwrite_allowed") is False
        and identity_paths_valid
        and identity_digest is not None
        and attempt.get("output_identity_sha256") == identity_digest
    )
    checks.append(
        _terminal_check_result(
            "fresh_attempt_output_identity",
            attempt_match,
            "attempt must be fresh, namespace-bound, non-overwriting, and content-addressed",
            observed={
                "attempt_id": attempt.get("attempt_id"),
                "output_namespace": attempt.get("output_namespace"),
                "fresh_attempt": attempt.get("fresh_attempt"),
                "namespace_preexisting_at_start": attempt.get("namespace_preexisting_at_start"),
                "historical_trace_reuse": attempt.get("historical_trace_reuse"),
                "output_identity_sha256": attempt.get("output_identity_sha256"),
                "computed_output_identity_sha256": identity_digest,
                "identity_paths_valid": identity_paths_valid,
            },
            expected={
                "output_namespace": expected_namespace,
                "fresh_attempt": True,
                "namespace_preexisting_at_start": False,
                "historical_trace_reuse": False,
                "overwrite_allowed": False,
            },
        )
    )

    terminal_status = terminal.get("status")
    top_status = data.get("status")
    checks.append(
        _terminal_check_result(
            "terminal_status_is_complete",
            top_status == "completed" and terminal_status == "completed",
            "both sidecar and terminal projection must declare completed",
            observed={"sidecar_status": top_status, "terminal_status": terminal_status},
            expected={"sidecar_status": "completed", "terminal_status": "completed"},
        )
    )

    frame_count = terminal.get("frame_count")
    transition_count = terminal.get("transition_count")
    frame_contract = (
        isinstance(frame_count, int)
        and not isinstance(frame_count, bool)
        and frame_count >= SOURCE_FRAMES
        and isinstance(transition_count, int)
        and not isinstance(transition_count, bool)
        and transition_count >= SOURCE_TRANSITIONS
        and transition_count == frame_count - 1
        and terminal.get("committed_frame") == frame_count - 1
        and terminal.get("committed_transition") == transition_count - 1
    )
    checks.append(
        _terminal_check_result(
            "terminal_frames_and_transitions_complete",
            frame_contract,
            "terminal evidence must retain the full source frame/transition denominator",
            observed={
                "frame_count": frame_count,
                "transition_count": transition_count,
                "committed_frame": terminal.get("committed_frame"),
                "committed_transition": terminal.get("committed_transition"),
            },
            expected={
                "minimum_frame_count": SOURCE_FRAMES,
                "minimum_transition_count": SOURCE_TRANSITIONS,
                "transition_equals_frame_minus_one": True,
            },
        )
    )

    end_time = _number(terminal.get("committed_time_s"))
    event_complete = (
        _bool(terminal.get("event_window_complete"))
        and terminal.get("event_window_status") == "complete"
        and end_time is not None
        and end_time >= REQUIRED_EVENT_WINDOW_S
    )
    checks.append(
        _terminal_check_result(
            "terminal_event_window_complete",
            event_complete,
            "terminal event window must be complete through the required 8.68 s horizon",
            observed={
                "event_window_complete": terminal.get("event_window_complete"),
                "event_window_status": terminal.get("event_window_status"),
                "committed_time_s": terminal.get("committed_time_s"),
            },
            expected={
                "event_window_complete": True,
                "event_window_status": "complete",
                "minimum_committed_time_s": REQUIRED_EVENT_WINDOW_S,
            },
        )
    )

    mass_error = _number(metrics.get("mass_closure_error"))
    mass_closure = (
        _bool(metrics.get("mass_closed"))
        and mass_error is not None
        and abs(mass_error) <= MASS_CLOSURE_ERROR_LIMIT
    )
    checks.append(
        _terminal_check_result(
            "terminal_mass_closure",
            mass_closure,
            "terminal mass closure must be explicit and within the fixed diagnostic bound",
            observed={
                "mass_closed": metrics.get("mass_closed"),
                "mass_closure_error": metrics.get("mass_closure_error"),
            },
            expected={"mass_closed": True, "absolute_error_max": MASS_CLOSURE_ERROR_LIMIT},
        )
    )

    unknown = _number(metrics.get("unknown_fraction_max"))
    unknown_gate = (
        unknown is not None
        and 0.0 <= unknown <= 1.0
        and unknown <= UNKNOWN_LIMIT
        and _bool(metrics.get("unknown_gate_pass"))
    )
    checks.append(
        _terminal_check_result(
            "terminal_unknown_gate",
            unknown_gate,
            "terminal unknown fraction must remain in the fixed 1% gate and be explicit",
            observed={
                "unknown_fraction_max": metrics.get("unknown_fraction_max"),
                "unknown_gate_pass": metrics.get("unknown_gate_pass"),
            },
            expected={"unknown_fraction_max_max": UNKNOWN_LIMIT, "unknown_gate_pass": True},
        )
    )

    coverage = _number(metrics.get("common_reliable_path_coverage"))
    coverage_reported = coverage is not None and 0.0 <= coverage <= 1.0
    checks.append(
        _terminal_check_result(
            "terminal_common_reliable_coverage_reported",
            coverage_reported,
            "terminal common reliable path coverage must be finite and bounded",
            observed=metrics.get("common_reliable_path_coverage"),
            expected="finite value in [0, 1]",
        )
    )

    failed = [item["check"] for item in checks if not item["passed"]]
    reasons: list[str] = []
    reason_by_check = {
        "terminal_source_and_case_binding": "terminal_source_or_case_binding_mismatch",
        "terminal_material_config_exact": "terminal_material_config_drift",
        "fresh_attempt_output_identity": "fresh_attempt_or_output_identity_invalid",
        "terminal_status_is_complete": "terminal_status_missing_or_not_completed",
        "terminal_frames_and_transitions_complete": "terminal_frame_transition_denominator_incomplete",
        "terminal_event_window_complete": "terminal_event_window_partial_or_right_censored",
        "terminal_mass_closure": "terminal_mass_closure_missing_or_failed",
        "terminal_unknown_gate": "terminal_unknown_gate_missing_or_failed",
        "terminal_common_reliable_coverage_reported": "terminal_common_reliable_coverage_missing_or_invalid",
        "terminal_schema": "terminal_evidence_schema_mismatch",
    }
    for name in failed:
        if name in reason_by_check:
            reasons.append(reason_by_check[name])
    if not reasons:
        reasons.append("terminal_evidence_not_authorized_by_this_diagnostic_intake")
    return {
        "present": True,
        "status": str(data.get("status", "unknown")),
        "checks": checks,
        "failed_checks": failed,
        "blocking_reasons": list(dict.fromkeys(reasons)),
        "observed": {
            "source": dict(source),
            "material_config": dict(config),
            "attempt_id": attempt.get("attempt_id"),
            "output_namespace": attempt.get("output_namespace"),
            "terminal_status": terminal_status,
            "frame_count": frame_count,
            "transition_count": transition_count,
            "committed_time_s": end_time,
            "mass_closed": metrics.get("mass_closed"),
            "mass_closure_error": mass_error,
            "unknown_fraction_max": unknown,
            "common_reliable_path_coverage": coverage,
            "event_window_complete": terminal.get("event_window_complete"),
            "event_window_status": terminal.get("event_window_status"),
        },
        "gate_projection": {
            "mass_closure": mass_closure,
            "unknown_gate": unknown_gate,
            "coverage_reported": coverage_reported,
            "event_window_complete": event_complete,
        },
    }


def _case_row(collection: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = collection.get("cases", [])
    if not isinstance(rows, list):
        return {}
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == CASE_ID]
    return matches[0] if len(matches) == 1 else {}


def _proposal_config(proposal: Mapping[str, Any]) -> dict[str, Any]:
    parameters = _mapping(proposal.get("parameter_contract"))
    return {
        "q": parameters.get("q"),
        "dp_m": parameters.get("dp_m"),
        "seeds": parameters.get("seeds"),
        "substeps": parameters.get("substeps"),
        "neighbour_variant": parameters.get("neighbour_variant"),
        "source_frames": parameters.get("native_frame_count"),
        "source_transitions": parameters.get("native_transition_count"),
        "required_event_window_s": parameters.get("extension_window_s"),
    }


def _input_config_checks(
    proposal: Mapping[str, Any],
    collection: Mapping[str, Any],
    reader: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
    consistency: Mapping[str, Any],
    host_io: Mapping[str, Any],
    collection_ref: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target = _mapping(proposal.get("target"))
    row = _case_row(collection)
    diag_source = _mapping(diagnostic.get("source"))
    diag_identity = _mapping(diag_source.get("case_identity"))
    diag_parameters = _mapping(diagnostic.get("parameters"))
    trace = _mapping(diagnostic.get("trace"))
    decision = _mapping(diagnostic.get("decision"))
    reader_result = _mapping(reader.get("reader_result"))
    collection_sha = collection_ref.get("sha256")
    proposal_manifest = _mapping(_mapping(proposal.get("source_manifest_contract")).get("core_collection_manifest"))
    proposal_config = _proposal_config(proposal)

    checks = [
        _check(
            "proposal_schema_and_identity",
            proposal.get("schema") == "core.material.f4.tallwall120.coarse_proposal.v1"
            and target.get("family") == FAMILY
            and target.get("case_id") == CASE_ID
            and target.get("scope_id") == SCOPE_ID,
            "coarse proposal schema and DEV_07 identity must be exact",
            observed={"schema": proposal.get("schema"), "target": dict(target)},
        ),
        _check(
            "target_source_sha_exact",
            target.get("source_hdf5") == SOURCE_HDF5
            and target.get("source_sha256") == SOURCE_SHA256
            and target.get("source_bytes") == SOURCE_BYTES,
            "proposal target must bind the exact DEV_07 source path, SHA, and byte metadata",
            observed={
                "path": target.get("source_hdf5"),
                "sha256": target.get("source_sha256"),
                "bytes": target.get("source_bytes"),
            },
            expected={"path": SOURCE_HDF5, "sha256": SOURCE_SHA256, "bytes": SOURCE_BYTES},
        ),
        _check(
            "collection_manifest_ref_bound",
            proposal_manifest.get("path") == COLLECTION.as_posix()
            and proposal_manifest.get("sha256") == collection_sha,
            "proposal collection reference must bind the current collection manifest bytes",
            observed={"path": proposal_manifest.get("path"), "sha256": proposal_manifest.get("sha256")},
            expected={"path": COLLECTION.as_posix(), "sha256": collection_sha},
        ),
        _check(
            "collection_case_source_sha_exact",
            row.get("trajectory", {}).get("sha256") == SOURCE_SHA256,
            "collection DEV_07 row must retain the target source SHA",
            observed=row.get("trajectory", {}).get("sha256"),
            expected=SOURCE_SHA256,
        ),
        _check(
            "collection_case_source_path_exact",
            row.get("trajectory", {}).get("path") == SOURCE_HDF5,
            "collection DEV_07 row must declare the proposal's archives-v2 source path",
            observed=row.get("trajectory", {}).get("path"),
            expected=SOURCE_HDF5,
        ),
        _check(
            "reader_ref_manifest_path_exact",
            reader.get("manifest") == COLLECTION.as_posix(),
            "reader smoke must name the same collection manifest",
            observed=reader.get("manifest"),
            expected=COLLECTION.as_posix(),
        ),
        _check(
            "reader_ref_manifest_sha_current",
            reader.get("manifest_sha256") == collection_sha,
            "reader smoke manifest SHA must match current collection bytes",
            observed=reader.get("manifest_sha256"),
            expected=collection_sha,
        ),
        _check(
            "reader_trusted_formal_gate_closed",
            reader_result.get("reader_formal_eligible") is False
            and reader_result.get("formal_credit_granted_by_this_smoke") is False,
            "reader smoke must remain non-formal and non-crediting",
            observed={
                "reader_formal_eligible": reader_result.get("reader_formal_eligible"),
                "formal_credit_granted_by_this_smoke": reader_result.get(
                    "formal_credit_granted_by_this_smoke"
                ),
            },
            expected={"reader_formal_eligible": False, "formal_credit_granted_by_this_smoke": False},
        ),
        _check(
            "diagnostic_source_sha_exact",
            diag_source.get("repo_relative_path") == SOURCE_HDF5
            and diag_source.get("case_identity", {}).get("case_id") == CASE_ID
            and diag_source.get("before", {}).get("sha256") == SOURCE_SHA256
            and diag_source.get("after", {}).get("sha256") == SOURCE_SHA256,
            "DEV_07 diagnostic source path/case/SHA must bind the same target",
            observed={
                "path": diag_source.get("repo_relative_path"),
                "case_id": diag_identity.get("case_id"),
                "before_sha256": diag_source.get("before", {}).get("sha256"),
                "after_sha256": diag_source.get("after", {}).get("sha256"),
            },
            expected={"path": SOURCE_HDF5, "case_id": CASE_ID, "sha256": SOURCE_SHA256},
        ),
        _check(
            "diagnostic_material_config_matches_proposal",
            diag_parameters.get("q") == proposal_config["q"]
            and diag_parameters.get("dp_m") == proposal_config["dp_m"]
            and diag_parameters.get("seeds") == proposal_config["seeds"]
            and diag_parameters.get("substeps") == proposal_config["substeps"]
            and diag_parameters.get("neighbour_variant") == proposal_config["neighbour_variant"],
            "historical diagnostic material config must not be reused when it drifts from the proposal",
            observed={
                "q": diag_parameters.get("q"),
                "dp_m": diag_parameters.get("dp_m"),
                "seeds": diag_parameters.get("seeds"),
                "substeps": diag_parameters.get("substeps"),
                "neighbour_variant": diag_parameters.get("neighbour_variant"),
            },
            expected={
                "q": proposal_config["q"],
                "dp_m": proposal_config["dp_m"],
                "seeds": proposal_config["seeds"],
                "substeps": proposal_config["substeps"],
                "neighbour_variant": proposal_config["neighbour_variant"],
            },
        ),
        _check(
            "diagnostic_negative_boundary_preserved",
            diagnostic.get("status") == "completed_diagnostic_only"
            and decision.get("classification") == "diagnostic_negative"
            and trace.get("event_window_complete") is False
            and trace.get("event_window_status") == "right_censored_or_unresolved"
            and trace.get("unknown_fraction_max") == 1.0
            and trace.get("common_reliable_path_coverage") == 0.0
            and decision.get("T2") is False
            and decision.get("credit") == 0,
            "known diagnostic-negative/right-censored evidence must remain negative",
            observed={
                "status": diagnostic.get("status"),
                "classification": decision.get("classification"),
                "event_window_complete": trace.get("event_window_complete"),
                "event_window_status": trace.get("event_window_status"),
                "unknown_fraction_max": trace.get("unknown_fraction_max"),
                "common_reliable_path_coverage": trace.get("common_reliable_path_coverage"),
                "T2": decision.get("T2"),
                "credit": decision.get("credit"),
            },
        ),
        _check(
            "consistency_audit_is_blocked",
            consistency.get("schema") == "core.material.f4.tallwall120.receipt_consistency_audit.v1"
            and consistency.get("status") == "blocked_fail_closed",
            "receipt drift audit must remain fail-closed",
            observed={"schema": consistency.get("schema"), "status": consistency.get("status")},
        ),
        _check(
            "fresh_execution_authority_absent",
            host_io.get("status") == "diagnostic_admission_blocked"
            and _mapping(host_io.get("authorization_boundary")).get("launch_admitted") is False
            and _mapping(host_io.get("authorization_boundary")).get("credit") == 0,
            "host-I/O projection is not execution authorization and must not mint credit",
            observed={
                "status": host_io.get("status"),
                "launch_admitted": _mapping(host_io.get("authorization_boundary")).get("launch_admitted"),
                "credit": _mapping(host_io.get("authorization_boundary")).get("credit"),
            },
        ),
    ]
    details = {
        "proposal_config": proposal_config,
        "diagnostic_trace": {
            "committed_frame": trace.get("committed_frame"),
            "frame_count": trace.get("frame_count"),
            "transition_count": trace.get("transition_count"),
            "committed_time_s": trace.get("committed_time_s"),
            "event_window_complete": trace.get("event_window_complete"),
            "event_window_status": trace.get("event_window_status"),
            "mass_closed": trace.get("mass_closed"),
            "unknown_fraction_max": trace.get("unknown_fraction_max"),
            "common_reliable_path_coverage": trace.get("common_reliable_path_coverage"),
            "historical_trace_path": _mapping(trace.get("output")).get("path"),
        },
        "collection_case": {
            "case_id": row.get("case_id"),
            "trajectory_path": row.get("trajectory", {}).get("path"),
            "trajectory_sha256": row.get("trajectory", {}).get("sha256"),
        },
    }
    return checks, details


def build_report(
    lab_root: str | Path = LAB_ROOT,
    *,
    terminal_evidence_path: str | Path = TERMINAL_EVIDENCE,
    observed_at_utc: str = OBSERVED_AT_UTC,
) -> dict[str, Any]:
    """Build a deterministic JSON-only intake report."""

    root = Path(lab_root).resolve()
    proposal = _read_json(root, PROPOSAL)
    collection = _read_json(root, COLLECTION)
    reader = _read_json(root, READER)
    diagnostic = _read_json(root, DIAGNOSTIC)
    consistency = _read_json(root, CONSISTENCY_AUDIT)
    host_io = _read_json(root, HOST_IO_PROJECTION)
    input_paths = {
        "proposal": (PROPOSAL, "committed F4 coarse material proposal"),
        "collection_manifest": (COLLECTION, "current F4 collection manifest"),
        "reader_smoke": (READER, "F4 Core reader smoke receipt"),
        "diagnostic": (DIAGNOSTIC, "DEV_07 material diagnostic receipt"),
        "consistency_audit": (CONSISTENCY_AUDIT, "F4 receipt consistency audit"),
        "host_io_projection": (HOST_IO_PROJECTION, "F4 coarse host-I/O projection"),
        "implementation": (Path(__file__).resolve(), "terminal evidence intake implementation"),
    }
    refs = {
        name: _small_ref(root, path, role) for name, (path, role) in input_paths.items()
    }
    source_target = _mapping(proposal.get("target"))
    source_metadata = _hdf5_metadata(
        root, SOURCE_HDF5, str(source_target.get("source_sha256", SOURCE_SHA256))
    )
    checks, input_details = _input_config_checks(
        proposal,
        collection,
        reader,
        diagnostic,
        consistency,
        host_io,
        refs["collection_manifest"],
    )

    terminal_path = _resolve(root, terminal_evidence_path)
    terminal_ref = _small_ref(root, terminal_path, "fresh F4 material terminal evidence sidecar")
    terminal_payload: dict[str, Any] | None = None
    terminal_input_error: str | None = None
    if terminal_ref["exists"] and terminal_ref.get("error") is None:
        try:
            terminal_payload = _read_json(root, terminal_evidence_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            terminal_input_error = f"{type(error).__name__}: {error}"
    terminal_result = evaluate_terminal_evidence(terminal_payload)
    if terminal_input_error:
        terminal_result = {
            **terminal_result,
            "input_error": terminal_input_error,
            "blocking_reasons": list(
                dict.fromkeys(terminal_result["blocking_reasons"] + ["terminal_evidence_json_invalid"])
            ),
        }

    failed_checks = [item["check"] for item in checks if not item["passed"]]
    blocking_reasons = [
        "fresh_terminal_evidence_missing_at_planned_output_namespace"
        if not terminal_ref["exists"]
        else None,
        "terminal_evidence_intake_is_not_an_execution_authorization",
        "current_dev07_material_diagnostic_is_right_censored_or_unresolved",
        "current_dev07_material_diagnostic_unknown_fraction_is_1.0",
        "current_dev07_material_diagnostic_common_reliable_path_coverage_is_0.0",
        "historical_material_diagnostic_is_not_a_fresh_attempt_and_must_not_be_reused",
        "collection_manifest_archives_v1_vs_proposal_archives_v2_path_drift",
        "reader_smoke_manifest_sha_is_stale_against_current_collection",
        "reader_trusted_formal_gate_is_closed",
        "fresh_root_resource_runtime_authorization_is_absent",
    ]
    if not _mapping(input_details.get("diagnostic_trace")).get("event_window_complete"):
        blocking_reasons.append("known_material_diagnostic_event_window_is_incomplete")
    if not _mapping(input_details.get("diagnostic_trace")).get("mass_closed"):
        blocking_reasons.append("known_material_diagnostic_mass_closure_is_not_passed")
    blocking_reasons.extend(terminal_result.get("blocking_reasons", []))
    blocking_reasons.extend(
        {
            "collection_case_source_path_exact": "collection_case_archives_v1_path_does_not_match_archives_v2_target",
            "reader_ref_manifest_sha_current": "reader_smoke_manifest_sha_does_not_match_current_collection",
            "diagnostic_material_config_matches_proposal": "historical_diagnostic_material_config_drifts_from_fresh_proposal",
        }.get(name, f"failed_check:{name}")
        for name in failed_checks
    )
    blocking_reasons = list(dict.fromkeys(item for item in blocking_reasons if item))

    source_ref_consistency = {
        "proposal_sha256": source_target.get("source_sha256"),
        "collection_sha256": input_details["collection_case"].get("trajectory_sha256"),
        "diagnostic_before_sha256": _mapping(_mapping(diagnostic.get("source")).get("before")).get("sha256"),
        "diagnostic_after_sha256": _mapping(_mapping(diagnostic.get("source")).get("after")).get("sha256"),
        "target_hdf5_metadata": source_metadata,
        "all_declared_source_sha256_match": all(
            value == SOURCE_SHA256
            for value in (
                source_target.get("source_sha256"),
                input_details["collection_case"].get("trajectory_sha256"),
                _mapping(_mapping(diagnostic.get("source")).get("before")).get("sha256"),
                _mapping(_mapping(diagnostic.get("source")).get("after")).get("sha256"),
            )
        ),
    }
    return {
        "schema": SCHEMA,
        "observed_at_utc": observed_at_utc,
        "status": "blocked_fail_closed",
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "case_id": CASE_ID,
            "source_hdf5": SOURCE_HDF5,
            "source_sha256": SOURCE_SHA256,
        },
        "input_boundary": {
            "bounded_json_only": True,
            "max_json_bytes": MAX_JSON_BYTES,
            "hdf5_metadata_only": True,
            "hdf5_content_read": False,
            "hdf5_hash_recomputed": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_mutation": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "input_bindings": refs,
        "source_ref_consistency": source_ref_consistency,
        "material_config_contract": {
            "q": EXPECTED_Q,
            "dp_m": EXPECTED_DP_M,
            "seeds": EXPECTED_SEEDS,
            "substeps": EXPECTED_SUBSTEPS,
            "neighbour_variant": EXPECTED_NEIGHBOUR_VARIANT,
            "required_source_frames": SOURCE_FRAMES,
            "required_source_transitions": SOURCE_TRANSITIONS,
            "required_event_window_s": REQUIRED_EVENT_WINDOW_S,
            "native_source_window_s": SOURCE_END_S,
            "unknown_fraction_limit": UNKNOWN_LIMIT,
            "mass_closure_error_limit": MASS_CLOSURE_ERROR_LIMIT,
            "right_censor_policy": "fail closed; no event imputation or partial credit",
        },
        "proposal_collection_reader_diagnostic_projection": input_details,
        "fresh_attempt_contract": {
            "planned_output_namespace": DEFAULT_OUTPUT_NAMESPACE,
            "terminal_evidence_path": _relative(root, terminal_path),
            "fresh_attempt_required": True,
            "namespace_must_be_absent_before_attempt": True,
            "overwrite_allowed": False,
            "historical_trace_reuse": False,
            "historical_diagnostic_trace": input_details["diagnostic_trace"].get("historical_trace_path"),
            "terminal_evidence_ref": terminal_ref,
            "terminal_input_error": terminal_input_error,
        },
        "terminal_evidence_intake": terminal_result,
        "checks": checks,
        "failed_checks": failed_checks,
        "blocking_reasons": blocking_reasons,
        "qualification": {
            "diagnostic_only": True,
            "formal": False,
            "formal_eligible": False,
            "T1": False,
            "T2": False,
            "qualification": False,
            "credit": 0,
            "qualification_credit": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "gate_mutation": 0,
            "completion_mutation": 0,
        },
        "scientific_boundary": {
            "native_source_event_window_not_material_event_evidence": True,
            "historical_diagnostic_negative_not_promoted": True,
            "right_censored_is_not_complete": True,
            "unknown_remains_in_full_denominator": True,
            "coverage_is_reported_not_imputed": True,
            "fresh_terminal_result_required": True,
            "no_T2_or_partial_credit": True,
        },
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    qualification = _mapping(report.get("qualification"))
    projection = _mapping(report.get("proposal_collection_reader_diagnostic_projection"))
    trace = _mapping(projection.get("diagnostic_trace"))
    terminal = _mapping(report.get("terminal_evidence_intake"))
    lines = [
        "# F4 Tallwall120 material terminal evidence intake V1",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- schema：`{report.get('schema')}`",
        f"- target：`{CASE_ID}`",
        f"- source trajectory SHA-256：`{SOURCE_SHA256}`",
        "",
        "## 合同边界",
        "",
        "本 intake 只读取有界 JSON 和文件系统元数据；不打开或重哈希目标 HDF5，" \
        "不启动、停止或重启 solver/worker/GPU/queue，也不修改 PLAN、registry、ledger、分母或 gate。",
        "",
        "固定配置为 `q=0.23437500000000008`、`dp_m=0.0075`、" \
        "`512 seeds`、`substeps=2`、`baseline24`；必须保留至少 `218 frames / 217 transitions`，" \
        "并完整达到 `8.68 s` event window。",
        "",
        "## 当前证据",
        "",
        f"- fresh terminal sidecar：`{terminal.get('status')}`；" \
        f"阻塞：`{', '.join(terminal.get('blocking_reasons', [])) or 'none'}`",
        f"- 已有 diagnostic：event window=`{trace.get('event_window_status')}`，" \
        f"unknown=`{trace.get('unknown_fraction_max')}`，" \
        f"common reliable coverage=`{trace.get('common_reliable_path_coverage')}`；仅为 negative provenance。",
        "- collection 的 DEV_07 行仍声明 archives-v1，而 proposal target 是 archives-v2；" \
        "reader smoke 的 manifest SHA 也已漂移，trusted reader formal gate 保持关闭。",
        "",
        "## Qualification boundary",
        "",
        f"`diagnostic_only={qualification.get('diagnostic_only')}`、" \
        f"`formal={qualification.get('formal')}`、`T1={qualification.get('T1')}`、" \
        f"`T2={qualification.get('T2')}`、`qualification={qualification.get('qualification')}`、" \
        f"`credit={qualification.get('credit')}`。",
        "",
        "## 阻塞",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.get("blocking_reasons", []))
    lines.extend([
        "",
        "下一安全动作是取得新的 root/resource/runtime authorization，在固定 fresh namespace 中产生" \
        "完整 terminal sidecar；在此之前不得把历史 `/tmp` trace、native source event flag 或 reader manifest 声明提升为 material T2。",
        "",
    ])
    return "\n".join(lines)


def write_outputs(
    report: Mapping[str, Any], output: str | Path, zh_output: str | Path
) -> tuple[Path, Path]:
    output_path = Path(output).resolve()
    zh_path = Path(zh_output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    zh_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    zh_path.write_text(render_markdown(report), encoding="utf-8")
    return output_path, zh_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB_ROOT)
    parser.add_argument("--terminal-evidence", type=Path, default=TERMINAL_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    args = parser.parse_args(argv)
    report = build_report(args.lab_root, terminal_evidence_path=args.terminal_evidence)
    write_outputs(report, args.output, args.zh_output)
    print(
        json.dumps(
            {
                "output": str(Path(args.output).resolve()),
                "zh_output": str(Path(args.zh_output).resolve()),
                "schema": report["schema"],
                "status": report["status"],
                "terminal_status": report["terminal_evidence_intake"]["status"],
                "failed_checks": len(report["failed_checks"]),
                "credit": report["qualification"]["credit"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
