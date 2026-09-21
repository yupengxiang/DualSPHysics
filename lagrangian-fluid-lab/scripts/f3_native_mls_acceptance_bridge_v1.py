#!/usr/bin/env python3
"""Build a read-only, versioned acceptance bridge for F3 native MLS receipts.

The native MLS workers and the F3 T2 gap audit already emit diagnostic JSON
sidecars.  This module adapts those sidecars to the shape an independent Core
material acceptance collector can consume.  It is deliberately a bridge, not
the collector: no trace is promoted, no matrix row is completed, and no T2
credit is granted here.

Only JSON receipts and source text are read.  In particular, this module does
not import ``h5py`` or open an HDF5 path copied into a receipt.  Source and
trace hashes are inherited from the upstream audit's JSON closure.  The
resulting formal receipt is therefore explicit about a blocked decision when
the fixed gates or full-window evidence are absent.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any


SCHEMA = "core.material.f3.native_volume_mls.acceptance_bridge.v1"
RECEIPT_SCHEMA = "core.material.f3.native_volume_mls.acceptance_receipt.v1"
GAP_SCHEMA = "core.material.f3.t2.admission_acceptance_gap_audit.v1"

# These values are copied from the registered F3 gate contract.  The bridge
# checks the upstream receipt against them; it never accepts a caller-provided
# replacement.
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
NATIVE_INTERVAL_S = 0.002
CADENCE_TOLERANCE_S = 5.0e-5
FULL_WINDOW_S = 8.35

TRACE_TO_CHECKPOINT = {
    "core.material.f3.native_volume_mls.trace.v1":
    "core.material.f3.native_volume_mls.checkpoint.v1",
    "core.material.f3.native_volume_mls.trace.v2":
    "core.material.f3.native_volume_mls.checkpoint.v2",
    "core.material.f3.native_volume_mls.trace.temporal.v3":
    "core.material.f3.native_volume_mls.checkpoint.temporal.v3",
}

DEFAULT_OUTPUT_NAME = (
    "campaigns/core-v1/material/evidence/"
    "f3-native-mls-acceptance-bridge-v1-20260921.json"
)
DEFAULT_REPORT_NAME = "reports/F3-NATIVE-MLS-ACCEPTANCE-BRIDGE-2026-09-21.zh-CN.md"

INPUTS: dict[str, Path] = {
    "t2_gap_audit": Path(
        "campaigns/core-v1/material/evidence/"
        "f3-t2-admission-acceptance-gap-audit-20260921.json"
    ),
    "native_mls_v1": Path("scripts/f3_native_volume_mls.py"),
    "native_mls_v2": Path("scripts/f3_native_volume_mls_v2.py"),
    "native_mls_temporal_v3": Path("scripts/f3_native_volume_mls_temporal_v3.py"),
    "native_mls_compare": Path("scripts/f3_native_volume_mls_compare.py"),
    "native_cadence_adapter": Path("scripts/f3_native_cadence_adapter_v1.py"),
    "core_material_acceptance": Path("scripts/core_material_acceptance.py"),
    # The bridge itself is hash-bound in the output.  This makes the receipt
    # versioned even when it is produced by a caller using a custom output
    # path.
    "bridge_implementation": Path(__file__),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_path(lab_root: Path, value: str | Path) -> Path:
    value_path = Path(value)
    if value_path.is_absolute():
        return value_path
    root = Path(lab_root).resolve()
    candidates = (root / value_path, root.parent / value_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _display_path(lab_root: Path, path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(Path(lab_root).resolve()))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _bind_file(lab_root: Path, value: str | Path, role: str) -> dict[str, Any]:
    path = _resolve_path(lab_root, value)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": _display_path(lab_root, path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "role": role,
    }


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be finite") from error
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _as_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _require_equal(actual: Any, expected: Any, name: str) -> None:
    if actual != expected:
        raise ValueError(f"{name} drifted: expected {expected!r}, got {actual!r}")


def _validate_registered_gates(gap: dict[str, Any]) -> dict[str, Any]:
    registered = gap.get("registered_gates")
    if not isinstance(registered, dict):
        raise ValueError("gap audit has no registered_gates object")
    _require_equal(
        _finite(registered.get("unknown_fraction_per_source_max"), "unknown limit"),
        UNKNOWN_LIMIT,
        "unknown limit",
    )
    _require_equal(
        _finite(registered.get("f3_cdf_sup_abs_difference_max"), "CDF limit"),
        CDF_LIMIT,
        "CDF limit",
    )
    _require_equal(
        _finite(registered.get("native_source_interval_s"), "native interval"),
        NATIVE_INTERVAL_S,
        "native interval",
    )
    _require_equal(
        _finite(
            registered.get("native_source_cadence_integrity_tolerance_s"),
            "cadence tolerance",
        ),
        CADENCE_TOLERANCE_S,
        "cadence tolerance",
    )
    _require_equal(
        _finite(registered.get("full_source_window_s"), "full source window"),
        FULL_WINDOW_S,
        "full source window",
    )
    _require_equal(registered.get("right_censored_is_not_acceptance"), True, "right-censor policy")
    _require_equal(registered.get("no_partial_credit"), True, "partial-credit policy")
    return {
        "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
        "cdf_sup_abs_difference_max": CDF_LIMIT,
        "native_source_interval_s": NATIVE_INTERVAL_S,
        "native_source_cadence_integrity_tolerance_s": CADENCE_TOLERANCE_S,
        "full_source_window_s": FULL_WINDOW_S,
        "right_censored_is_not_acceptance": True,
        "no_partial_credit": True,
        "denominator_policy": registered.get("denominator_policy"),
    }


def _validate_gap_identity(gap: dict[str, Any]) -> None:
    _require_equal(gap.get("schema"), GAP_SCHEMA, "upstream gap schema")
    if gap.get("qualification_claim") not in ("none", None):
        raise ValueError("upstream gap audit carries a qualification claim")
    if gap.get("T2_macro") is True or gap.get("T2_path") is True:
        raise ValueError("upstream gap audit cannot claim T2")
    _require_equal(gap.get("qualification_credit"), "none", "upstream qualification credit")
    constraints = gap.get("execution_constraints")
    if not isinstance(constraints, dict):
        raise ValueError("upstream gap audit has no execution constraints")
    for name in (
        "solver_started",
        "gpu_started",
        "new_job_submitted",
        "T1_denominator_changed",
        "T2_denominator_changed",
        "thresholds_changed",
        "old_evidence_overwritten",
    ):
        if constraints.get(name) is not False:
            raise ValueError(f"upstream gap audit violates read-only boundary: {name}")
    for name in ("queue_mutation", "registry_mutation", "central_ledger_mutation", "matrix_mutation"):
        if constraints.get(name) != 0:
            raise ValueError(f"upstream gap audit has nonzero mutation: {name}")


def _source_rows(
    source_window: dict[str, Any],
    cdf_sources: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = source_window.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("gap audit source-window summary has no rows")
    output: list[dict[str, Any]] = []
    seen_rows: set[int] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("source-window row must be an object")
        row_id = raw.get("row")
        if isinstance(row_id, bool) or not isinstance(row_id, int) or row_id in seen_rows:
            raise ValueError("source-window rows must have unique integer row ids")
        seen_rows.add(row_id)
        trace = raw.get("trace")
        source_window_meta = raw.get("source_window")
        unknown = raw.get("unknown")
        cdf = raw.get("cdf")
        if not all(isinstance(item, dict) for item in (trace, source_window_meta, unknown, cdf)):
            raise ValueError(f"row {row_id} has incomplete source-window summary")
        trace_schema = trace.get("schema")
        checkpoint_schema = TRACE_TO_CHECKPOINT.get(str(trace_schema))
        if checkpoint_schema is None:
            raise ValueError(f"row {row_id} has unsupported trace schema: {trace_schema}")
        source_rows = unknown.get("source_rows")
        if not isinstance(source_rows, list) or not source_rows:
            raise ValueError(f"row {row_id} has no per-source unknown rows")
        normalized_unknown: list[dict[str, Any]] = []
        source_ids: set[str] = set()
        for source in source_rows:
            if not isinstance(source, dict):
                raise ValueError(f"row {row_id} source unknown row is not an object")
            source_id = str(source.get("source_id"))
            if not source_id or source_id in source_ids:
                raise ValueError(f"row {row_id} has duplicate/empty source id")
            source_ids.add(source_id)
            denominator = source.get("denominator")
            unknown_count = source.get("unknown_count")
            if (
                isinstance(denominator, bool)
                or not isinstance(denominator, int)
                or denominator <= 0
                or isinstance(unknown_count, bool)
                or not isinstance(unknown_count, int)
                or unknown_count < 0
                or unknown_count > denominator
            ):
                raise ValueError(f"row {row_id} source {source_id} has invalid denominator/count")
            fraction = _finite(source.get("unknown_fraction"), "unknown fraction")
            expected_fraction = unknown_count / denominator
            if abs(fraction - expected_fraction) > 1.0e-12:
                raise ValueError(f"row {row_id} source {source_id} unknown fraction is not count-bound")
            expected_pass = fraction <= UNKNOWN_LIMIT
            input_pass = source.get("gate_pass")
            if input_pass is not None and bool(input_pass) != expected_pass:
                raise ValueError(f"row {row_id} source {source_id} unknown gate disagrees with fraction")
            normalized_unknown.append(
                {
                    "source_id": source_id,
                    "seed_denominator": denominator,
                    "terminal_unknown_count": unknown_count,
                    "terminal_unknown_fraction": fraction,
                    "maximum_allowed_unknown_fraction": UNKNOWN_LIMIT,
                    "unknown_gate_pass": expected_pass,
                    "first_failure_frame": source.get("first_failure_frame"),
                    "first_failure_time_s": source.get("first_failure_time_s"),
                    "first_failure_reason_counts": dict(
                        sorted((source.get("first_failure_reason_counts") or {}).items())
                    ),
                    "denominator_policy": (
                        "all geometric seeds carrying this source label; unknown and "
                        "right-censored event paths remain in the denominator"
                    ),
                }
            )
        cdf_rows: list[dict[str, Any]] = []
        row_cdf_max = _finite(cdf.get("maximum"), "row CDF maximum")
        for source_id, metric in sorted(cdf_sources.items()):
            if not isinstance(metric, dict):
                raise ValueError(f"CDF source {source_id} is not an object")
            first = _finite(metric.get("first_passage_sup"), "first-passage CDF bound")
            returned = _finite(metric.get("return_sup"), "return CDF bound")
            residence = _finite(metric.get("residence_sup"), "residence CDF bound")
            cdf_max = max(first, returned, residence)
            cdf_rows.append(
                {
                    "source_id": str(source_id),
                    "first_passage_cdf_sup_abs_difference": first,
                    "return_cdf_sup_abs_difference": returned,
                    "residence_cdf_sup_abs_difference": residence,
                    "maximum_cdf_sup_abs_difference": cdf_max,
                    "cdf_gate_pass": cdf_max <= CDF_LIMIT,
                    "residence_cdf_bounds_present": bool(metric.get("has_residence_cdf_bounds")),
                    "denominator_policy": (
                        "all seeds in this source half; permanent_unknown remains in the "
                        "source denominator and unresolved events contribute upper bounds"
                    ),
                }
            )
        if not cdf_rows:
            raise ValueError(f"row {row_id} has no CDF source rows")
        expected_row_max = max(item["maximum_cdf_sup_abs_difference"] for item in cdf_rows)
        if abs(row_cdf_max - expected_row_max) > 1.0e-12:
            raise ValueError(f"row {row_id} CDF maximum is not bound to event metrics")
        source_end = _finite(source_window_meta.get("time_end_s"), "source-window end time")
        output.append(
            {
                "row": row_id,
                "case_id": raw.get("case_id"),
                "failure_classification": list(raw.get("failure_classification") or []),
                "source_window": {
                    "frames": source_window_meta.get("frames"),
                    "particles": source_window_meta.get("particles"),
                    "time_end_s": source_end,
                    "required_full_window_s": FULL_WINDOW_S,
                    "full_window_complete": source_end >= FULL_WINDOW_S - CADENCE_TOLERANCE_S,
                    "integrity_pass": _as_bool(source_window_meta.get("integrity_pass"), "source integrity"),
                    "mass_closure_pass": _as_bool(source_window_meta.get("mass_closure_pass"), "source mass closure"),
                    "cadence_pass": _as_bool(source_window_meta.get("cadence_pass"), "source cadence"),
                    "hash_pass": _as_bool(source_window_meta.get("hash_pass"), "source hash"),
                    "max_timestamp_error_s": source_window_meta.get("max_timestamp_error_s"),
                    "provenance_role": "inherited source-window audit; HDF5 not reopened by bridge",
                },
                "trace": {
                    "schema": trace_schema,
                    "checkpoint_schema": checkpoint_schema,
                    "frames": trace.get("frames"),
                    "seeds": trace.get("seeds"),
                    "integrity_pass": _as_bool(trace.get("integrity_pass"), "trace integrity"),
                    "mass_closure_pass": _as_bool(trace.get("mass_closure_pass"), "trace mass closure"),
                    "cadence_pass": _as_bool(trace.get("cadence_pass"), "trace cadence"),
                    "reader_reconstruction_pass": _as_bool(
                        trace.get("reader_reconstruction_pass"), "reader reconstruction"
                    ),
                    "source_hash_pass": _as_bool(trace.get("source_hash_pass"), "source hash"),
                    "native_mass_match_pass": _as_bool(
                        trace.get("native_mass_match_pass"), "native mass match"
                    ),
                    "checkpoint_pass": _as_bool(trace.get("checkpoint_pass"), "checkpoint"),
                    "schema_binding_pass": True,
                },
                "unknown": {
                    "limit": UNKNOWN_LIMIT,
                    "maximum_source_unknown_fraction": _finite(
                        unknown.get("maximum_fraction"), "maximum source unknown fraction"
                    ),
                    "gate_pass": bool(unknown.get("pass")),
                    "source_rows": normalized_unknown,
                    "all_sources_pass": all(row["unknown_gate_pass"] for row in normalized_unknown),
                },
                "cdf": {
                    "limit": CDF_LIMIT,
                    "maximum": row_cdf_max,
                    "source_rows": cdf_rows,
                    "all_events_pass": all(row["cdf_gate_pass"] for row in cdf_rows),
                    "residence_cdf_bounds_present": all(
                        row["residence_cdf_bounds_present"] for row in cdf_rows
                    ),
                },
            }
        )
    return output


def _event_contract() -> dict[str, Any]:
    return {
        "schema": "core.material.f3.native_volume_mls.event_contract.v1",
        "first_passage": (
            "continuous crossing of x=0 into opposite source half on accepted linear RK segment"
        ),
        "return": "first later crossing back to the seed's origin half",
        "residence": "accepted segment time in the opposite source half",
        "unknown_policy": (
            "permanent_unknown seeds remain in every source denominator; event lower bound "
            "uses finite observed times and upper bound adds unresolved unknown mass from its "
            "first possible failure time"
        ),
        "residence_policy": (
            "all seeds contribute observed residence; support-loss seeds receive a conservative "
            "remaining-window upper interval; reliable no-event seeds contribute exact zero"
        ),
        "right_censoring": {
            "unknown_event_paths_are_right_censored": True,
            "right_censored_counts_as_acceptance": False,
            "full_window_required_for_acceptance": True,
            "partial_window_credit": False,
        },
    }


def _cdf_summary(cdf_rows: list[dict[str, Any]]) -> dict[str, Any]:
    # The retained row 29/31 comparisons share one source-level pair.  Keep a
    # single per-source CDF record in the bridge receipt and make the reuse
    # explicit instead of accidentally counting the same source twice.
    by_source: dict[str, dict[str, Any]] = {}
    for row in cdf_rows:
        source_id = str(row["source_id"])
        previous = by_source.get(source_id)
        if previous is not None:
            for key in (
                "first_passage_cdf_sup_abs_difference",
                "return_cdf_sup_abs_difference",
                "residence_cdf_sup_abs_difference",
                "maximum_cdf_sup_abs_difference",
                "cdf_gate_pass",
                "residence_cdf_bounds_present",
            ):
                if previous.get(key) != row.get(key):
                    raise ValueError(f"reused CDF source {source_id} has inconsistent metrics")
            continue
        by_source[source_id] = row
    unique_rows = [by_source[key] for key in sorted(by_source)]
    flattened = [
        (str(row["source_id"]), event, row[key])
        for row in unique_rows
        for event, key in (
            ("first_passage", "first_passage_cdf_sup_abs_difference"),
            ("return", "return_cdf_sup_abs_difference"),
            ("residence", "residence_cdf_sup_abs_difference"),
        )
    ]
    maximum = max((value for _, _, value in flattened), default=None)
    return {
        "limit": CDF_LIMIT,
        "event_names": ["first_passage", "return", "residence"],
        "source_count": len(unique_rows),
        "maximum_observed": maximum,
        "all_events_pass": bool(flattened) and all(value <= CDF_LIMIT for _, _, value in flattened),
        "by_source": unique_rows,
        "source_rows_reused_across_diagnostic_rows": len(cdf_rows) != len(unique_rows),
    }


def build_bridge(lab_root: Path) -> dict[str, Any]:
    """Build a blocked-or-admissible bridge from JSON/source inputs only."""
    lab_root = Path(lab_root).resolve()
    bound_inputs = {
        name: _bind_file(lab_root, value, "bridge input")
        for name, value in INPUTS.items()
        if name != "bridge_implementation"
    }
    # Bind the implementation after resolving __file__, preserving a stable
    # lab-relative path in the receipt.
    bound_inputs["bridge_implementation"] = _bind_file(
        lab_root, INPUTS["bridge_implementation"], "versioned acceptance bridge implementation"
    )
    gap_path = _resolve_path(lab_root, INPUTS["t2_gap_audit"])
    gap = _load_json(gap_path)
    _validate_gap_identity(gap)
    gates = _validate_registered_gates(gap)

    observed = gap.get("observed_gate_comparison")
    if not isinstance(observed, dict):
        raise ValueError("gap audit has no observed_gate_comparison")
    source_window = observed.get("source_window")
    cadence = observed.get("native_cadence")
    comparison = observed.get("comparison")
    if not all(isinstance(item, dict) for item in (source_window, cadence, comparison)):
        raise ValueError("gap audit is missing source-window/cadence/comparison summaries")
    cdf_sources = comparison.get("sources")
    if not isinstance(cdf_sources, list) or not cdf_sources:
        raise ValueError("gap audit comparison has no source-level CDF rows")
    cdf_by_source = {
        str(row.get("source")): row
        for row in cdf_sources
        if isinstance(row, dict) and row.get("source") is not None
    }
    rows = _source_rows(source_window, cdf_by_source)
    if not rows:
        raise ValueError("bridge has no source-window rows")

    source_window_integrity = bool(source_window.get("source_window_integrity_pass"))
    source_rows_full_window = all(
        row["source_window"]["full_window_complete"] for row in rows
    )
    unknown_gate = bool(source_window.get("unknown_mass", {}).get("all_rows_pass")) and all(
        row["unknown"]["all_sources_pass"] for row in rows
    )
    cdf_gate = bool(source_window.get("cdf", {}).get("all_rows_pass")) and all(
        row["cdf"]["all_events_pass"] for row in rows
    )
    cadence_source = cadence.get("source") if isinstance(cadence.get("source"), dict) else {}
    cadence_view = (
        cadence.get("direct_every_fifth_view")
        if isinstance(cadence.get("direct_every_fifth_view"), dict)
        else {}
    )
    canary = cadence.get("bounded_canary") if isinstance(cadence.get("bounded_canary"), dict) else {}
    cadence_gate = bool(cadence.get("source_preflight_pass")) and bool(cadence_view.get("pass"))
    canary_full_window = bool(canary.get("full_event_window"))
    canary_right_censored = bool(canary.get("right_censored"))
    matrix = gap.get("matrix") if isinstance(gap.get("matrix"), dict) else {}
    matrix_rows = matrix.get("registered_row_count")
    if isinstance(matrix_rows, bool) or not isinstance(matrix_rows, int) or matrix_rows <= 0:
        raise ValueError("gap audit matrix row count is invalid")
    formal_receipts = matrix.get("formal_acceptance_receipt_count")
    diagnostics = matrix.get("diagnostic_terminal_rows")
    if not isinstance(diagnostics, list):
        raise ValueError("gap audit matrix has no diagnostic row list")
    matrix_acceptance_gate = formal_receipts == matrix_rows
    trace_schema_gate = all(row["trace"]["schema_binding_pass"] for row in rows)
    checkpoint_schema_gate = all(
        row["trace"]["checkpoint_schema"] == TRACE_TO_CHECKPOINT[row["trace"]["schema"]]
        for row in rows
    )
    full_event_gate = source_rows_full_window and canary_full_window and not canary_right_censored
    acceptance_gates = {
        "trace_schema_binding": trace_schema_gate,
        "checkpoint_schema_binding": checkpoint_schema_gate,
        "source_window_integrity": source_window_integrity,
        "native_cadence_provenance": cadence_gate,
        "per_source_unknown_fraction": unknown_gate,
        "first_passage_return_residence_cdf": cdf_gate,
        "residence_cdf_bounds_present": all(
            row["cdf"]["residence_cdf_bounds_present"] for row in rows
        ),
        "full_event_window": full_event_gate,
        "right_censored_event": not canary_right_censored,
        "per_matrix_formal_acceptance_receipts": matrix_acceptance_gate,
    }
    bridge_pass = all(acceptance_gates.values())
    qualification_claim = "none"
    qualification_credit = "none" if not bridge_pass else "deferred_to_independent_collector"
    blocking_reasons: list[str] = []
    if not unknown_gate:
        blocking_reasons.append(
            f"per-source unknown gate fails: maximum {_finite(source_window['unknown_mass'].get('maximum_observed'), 'unknown maximum')} > {UNKNOWN_LIMIT}"
        )
    if not cdf_gate:
        blocking_reasons.append(
            f"first-passage/return/residence CDF gate fails: maximum {_finite(source_window['cdf'].get('maximum_observed'), 'CDF maximum')} > {CDF_LIMIT}"
        )
    if canary_right_censored or not canary_full_window:
        blocking_reasons.append(
            "bounded native-cadence canary is right-censored or shorter than the full registered event window; it has zero acceptance credit"
        )
    if formal_receipts != 0:
        blocking_reasons.append("upstream matrix summary changed its expected zero formal-receipt boundary")
    blocking_reasons.append(
        f"the registered {matrix_rows}-row overlay contains diagnostic rows only; diagnostic completion cannot promote a row to T2"
    )
    if not source_window_integrity:
        blocking_reasons.append("source-window integrity closure is incomplete")

    inherited_gap_bindings = gap.get("input_bindings")
    if not isinstance(inherited_gap_bindings, dict):
        raise ValueError("upstream gap audit has no input binding closure")
    source_window_binding = inherited_gap_bindings.get("source_window_audit")
    if not isinstance(source_window_binding, dict):
        raise ValueError("upstream gap audit has no source-window audit binding")
    cadence_binding_names = (
        "native_cadence_preflight",
        "native_cadence_selection",
        "native_cadence_canary",
    )
    inherited_cadence_bindings = {
        name: inherited_gap_bindings[name]
        for name in cadence_binding_names
        if isinstance(inherited_gap_bindings.get(name), dict)
    }
    source_window_provenance = {
        "audit_binding": {
            **source_window_binding,
            "role": "inherited source-window JSON audit; not reopened by bridge",
        },
        "required_full_window_s": FULL_WINDOW_S,
        "rows": [
            {
                "row": row["row"],
                "case_id": row["case_id"],
                "frames": row["source_window"]["frames"],
                "time_end_s": row["source_window"]["time_end_s"],
                "full_window_complete": row["source_window"]["full_window_complete"],
                "trace_schema": row["trace"]["schema"],
                "checkpoint_schema": row["trace"]["checkpoint_schema"],
                "provenance_role": row["source_window"]["provenance_role"],
            }
            for row in rows
        ],
        "source_paths_and_hashes": (
            "inherited from the upstream gap audit's source-window JSON closure; bridge did not reopen or rehash HDF5"
        ),
    }
    cadence_provenance = {
        "native_interval_s": NATIVE_INTERVAL_S,
        "cadence_tolerance_s": CADENCE_TOLERANCE_S,
        "source_preflight_pass": bool(cadence.get("source_preflight_pass")),
        "source": {
            "frames": cadence_source.get("frames"),
            "time_end_s": cadence_source.get("time_end_s"),
            "cadence_pass": cadence_source.get("cadence_pass"),
            "interpolation": cadence_source.get("interpolation"),
            "max_interval_error_s": cadence_source.get("max_interval_error_s"),
            "max_cumulative_time_error_s": cadence_source.get("max_cumulative_time_error_s"),
            "full_event_window_available": cadence_source.get("full_event_window_available"),
        },
        "direct_every_fifth_view": {
            "pass": cadence_view.get("pass"),
            "mode": cadence_view.get("mode"),
            "source_frame_count": cadence_view.get("source_frame_count"),
            "logical_frame_count": cadence_view.get("logical_frame_count"),
            "interpolation": cadence_view.get("interpolation"),
            "derived_view_is_independent_solve": False,
        },
        "bounded_canary": {
            "committed_frames": canary.get("committed_frames"),
            "time_end_s": canary.get("time_end_s"),
            "full_event_window": canary_full_window,
            "right_censored": canary_right_censored,
            "acceptance_credit": 0,
        },
        "inherited_json_bindings": inherited_cadence_bindings,
    }
    event_contract = _event_contract()
    cdf_rows = [item for row in rows for item in row["cdf"]["source_rows"]]
    formal_receipt = {
        "schema": RECEIPT_SCHEMA,
        "version": 1,
        "status": "accepted" if bridge_pass else "blocked",
        "decision": "eligible_for_independent_collector" if bridge_pass else "blocked",
        "qualification_claim": qualification_claim,
        "qualification_credit": qualification_credit,
        "credit": 1 if bridge_pass else 0,
        "T2_macro": False,
        "T2_path": False,
        "independent_collector_required": True,
        "diagnostic_rows_promoted": False,
    }
    return {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "admission_surface_complete_but_no_t2_claim" if bridge_pass else "blocked_for_acceptance",
        "decision": formal_receipt["decision"],
        "qualification_claim": qualification_claim,
        "qualification_credit": "none",
        "T2_macro": False,
        "T2_path": False,
        "fixed_gates": gates,
        "trace_and_checkpoint_schema": {
            "accepted_trace_schemas": sorted(TRACE_TO_CHECKPOINT),
            "trace_to_checkpoint": dict(TRACE_TO_CHECKPOINT),
            "rows": [
                {
                    "row": row["row"],
                    "trace_schema": row["trace"]["schema"],
                    "checkpoint_schema": row["trace"]["checkpoint_schema"],
                    "trace_schema_pass": row["trace"]["schema_binding_pass"],
                    "checkpoint_schema_pass": row["trace"]["schema_binding_pass"],
                }
                for row in rows
            ],
        },
        "source_window_provenance": source_window_provenance,
        "cadence_provenance": cadence_provenance,
        "denominator_policy": {
            "source": "all geometric seeds carrying each source label",
            "unknown": "unknown seeds remain in each source denominator",
            "cdf": "all seeds in each source half; no reliable-only denominator",
            "right_censor": "right-censored event paths remain in the denominator",
            "partial_credit": False,
        },
        "per_source_unknown": {
            "limit": UNKNOWN_LIMIT,
            "maximum_observed": source_window["unknown_mass"].get("maximum_observed"),
            "all_rows_pass": unknown_gate,
            "rows": [
                {
                    "row": row["row"],
                    "case_id": row["case_id"],
                    "maximum_source_unknown_fraction": row["unknown"]["maximum_source_unknown_fraction"],
                    "gate_pass": row["unknown"]["gate_pass"],
                    "sources": row["unknown"]["source_rows"],
                }
                for row in rows
            ],
        },
        "cdf_bounds": {
            **_cdf_summary(cdf_rows),
            "comparison_status": comparison.get("status"),
            "qualification_claim": comparison.get("qualification_claim"),
        },
        "event_contract": event_contract,
        "acceptance_gates": acceptance_gates,
        "formal_acceptance_receipt": formal_receipt,
        "matrix": {
            "registered_row_count": matrix_rows,
            "registered_row_order": matrix.get("registered_row_order"),
            "diagnostic_terminal_rows": sorted(int(value) for value in diagnostics),
            "upstream_formal_acceptance_receipt_count": formal_receipts,
            "formal_acceptance_receipt_count": 0,
            "diagnostic_rows_do_not_upgrade_t2": True,
            "material_matrix_ready": False,
            "qualification_credit": "none",
        },
        "admission_surface_pass": bridge_pass,
        "blocking_reasons": blocking_reasons,
        "execution_constraints": {
            "read_only": True,
            "json_and_source_only": True,
            "source_h5_opened": False,
            "terminal_h5_opened": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_started": False,
            "new_job_submitted": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "matrix_mutation": 0,
            "T1_denominator_changed": False,
            "T2_denominator_changed": False,
            "scientific_denominator_changed": False,
            "thresholds_changed": False,
            "old_evidence_overwritten": False,
        },
        "input_bindings": bound_inputs,
        "interpretation_boundary": (
            "This bridge adapts diagnostic JSON into a fail-closed formal receipt shape. "
            "A blocked receipt has zero credit. A future accepted bridge receipt still "
            "cannot promote diagnostic rows or claim T2 without an independent collector."
        ),
    }


def render_report(value: dict[str, Any], evidence_path: Path) -> str:
    gates = value["acceptance_gates"]
    unknown = value["per_source_unknown"]
    cdf = value["cdf_bounds"]
    matrix = value["matrix"]
    receipt = value["formal_acceptance_receipt"]
    status = "通过 bridge 结构检查但仍不授予 T2" if value["admission_surface_pass"] else "blocked（zero credit）"
    lines = [
        "# F3 native MLS acceptance adapter/receipt bridge（2026-09-21）",
        "",
        f"结论：本次只读 bridge 为 `{status}`。formal receipt 状态为 `{receipt['status']}`、credit=`{receipt['credit']}`；始终保持 `T2_macro=false`、`T2_path=false`、`qualification_claim=none`。",
        "",
        "本脚本只读取上游 gap JSON 和源码文本/哈希；没有打开 HDF5（包括 source/trace/checkpoint 文件），没有启动 solver、GPU 或 queue，也没有修改 registry、ledger、matrix、T1/T2 分母、固定阈值或旧 evidence。",
        "",
        f"机器回执：`{evidence_path}`；SHA-256：`{sha256_file(evidence_path) if evidence_path.is_file() else 'written-after-report'}`。",
        "",
        "## 固定门与桥接结果",
        "",
        "| 门 | 固定规则 | bridge 结果 |",
        "|---|---:|---|",
        f"| trace/checkpoint schema | 允许 v1/v2/temporal-v3 的成对 schema | `{str(gates['trace_schema_binding'] and gates['checkpoint_schema_binding']).lower()}` |",
        f"| source-window 完整性 | 质量、hash、reader、mass、checkpoint 绑定 | `{str(gates['source_window_integrity']).lower()}` |",
        f"| native cadence | `.002 s`，source tolerance `{CADENCE_TOLERANCE_S}` s，direct every-fifth 无插值 | `{str(gates['native_cadence_provenance']).lower()}` |",
        f"| 逐 source unknown | `<= {UNKNOWN_LIMIT}` | `{str(gates['per_source_unknown_fraction']).lower()}`；最大 `{unknown['maximum_observed']}` |",
        f"| first-passage / return / residence CDF | 每 source、全分母、sup `<= {CDF_LIMIT}` | `{str(gates['first_passage_return_residence_cdf']).lower()}`；最大 `{cdf['maximum_observed']}` |",
        f"| right-censored event | right-censor 不计 acceptance | `{str(gates['right_censored_event']).lower()}` |",
        f"| full event window | `{FULL_WINDOW_S}` s 且无 right-censor | `{str(gates['full_event_window']).lower()}` |",
        f"| formal matrix receipts | `{matrix['registered_row_count']}` 行均须独立 receipt | `{str(gates['per_matrix_formal_acceptance_receipts']).lower()}`；当前 `{matrix['formal_acceptance_receipt_count']}` |",
        "",
        "## 证据绑定",
        "",
        f"当前上游 source-window 行数为 `{len(value['source_window_provenance']['rows'])}`。每行保留 trace schema、checkpoint schema、frame/time-end 和 full-window 判断；source/trace HDF5 的路径和 hash 由 gap audit 的 JSON closure 继承，bridge 不重新打开或重新 hash HDF5。",
        "",
        "unknown 逐 source 保留 denominator、unknown count/fraction、首次失败 frame/time 和 reason counts；unknown 不能被 aggregate 数字隐藏。三类 CDF 均保留 source-level sup bound，并按全 source 分母计算。",
        "",
        f"event contract 固定 first-passage、return、residence 定义；permanent unknown 和未观察事件属于 right-censor，bounded native cadence canary 当前 full-window=`{str(value['cadence_provenance']['bounded_canary']['full_event_window']).lower()}`、right-censored=`{str(value['cadence_provenance']['bounded_canary']['right_censored']).lower()}`，因此 acceptance credit 为 0。",
        "",
        "## 33-row diagnostic 边界",
        "",
        f"注册矩阵为 `{matrix['registered_row_count']}` 行（`{matrix['registered_row_order']}`）；当前 diagnostic terminal rows 为 `{len(matrix['diagnostic_terminal_rows'])}`，formal acceptance receipt 为 `0`。diagnostic row 完成、terminal trace、matched-decimation view 或 source 可用都不能升级 T2。",
        "",
        "## 阻塞原因",
        "",
    ]
    lines.extend(f"{index}. {reason}" for index, reason in enumerate(value["blocking_reasons"], 1))
    lines.extend(["", "## 输入哈希", ""])
    for name, binding in value["input_bindings"].items():
        lines.append(f"- `{name}`：`{binding['path']}` — `{binding['sha256']}`")
    return "\n".join(lines) + "\n"


def write_artifacts(value: dict[str, Any], output: Path, report: Path) -> None:
    output = Path(output).resolve()
    report = Path(report).resolve()
    if output.exists() or report.exists():
        raise FileExistsError("refusing to overwrite existing bridge evidence/report")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(value, output), encoding="utf-8")


def verify_receipt(path: Path, lab_root: Path) -> dict[str, Any]:
    """Verify bridge receipt hashes without touching any HDF5 path."""
    value = _load_json(Path(path))
    _require_equal(value.get("schema"), SCHEMA, "bridge schema")
    _require_equal(value.get("T2_macro"), False, "T2_macro")
    _require_equal(value.get("T2_path"), False, "T2_path")
    _require_equal(value.get("qualification_credit"), "none", "qualification credit")
    for name, binding in value.get("input_bindings", {}).items():
        bound = _resolve_path(lab_root, binding["path"])
        if not bound.is_file():
            raise FileNotFoundError(bound)
        if bound.stat().st_size != binding["bytes"]:
            raise ValueError(f"input size changed: {name}")
        if sha256_file(bound) != binding["sha256"]:
            raise ValueError(f"input hash changed: {name}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--lab-root", type=Path, default=default_root)
    parser.add_argument("--output", type=Path, default=default_root / DEFAULT_OUTPUT_NAME)
    parser.add_argument("--report", type=Path, default=default_root / DEFAULT_REPORT_NAME)
    args = parser.parse_args(argv)
    value = build_bridge(args.lab_root.resolve())
    write_artifacts(value, args.output, args.report)
    print(
        json.dumps(
            {
                "schema": value["schema"],
                "status": value["status"],
                "decision": value["decision"],
                "T2_macro": value["T2_macro"],
                "credit": value["formal_acceptance_receipt"]["credit"],
                "output": str(Path(args.output).resolve()),
                "report": str(Path(args.report).resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
