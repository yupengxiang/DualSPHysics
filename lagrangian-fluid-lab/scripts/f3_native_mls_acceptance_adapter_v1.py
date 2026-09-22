"""Read-only acceptance bridge for F3 native-volume MLS diagnostics.

The native MLS runner and comparator already emit useful trace, checkpoint,
cadence, unknown-mass, and interval-CDF evidence.  This module gives that
evidence one strict JSON-only admission surface.  It deliberately does not
open HDF5, run a solver, submit work, or mutate the registry/ledger/matrix.

The bridge is an admission/readiness receipt, not a T2 upgrader.  Even when
all supplied scientific gates pass, ``qualification_claim`` remains ``none``
and ``qualification_credit`` remains zero.  A complete 33-row denominator is
required; a shorter list or a row marked merely diagnostic cannot be promoted
by this adapter.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


SCHEMA = "core.material.f3.native_mls_acceptance_adapter.v1"
COMPARISON_SCHEMA = "core.material.f3.native_volume_mls.comparison.v2"
SOURCE_WINDOW_SCHEMA = "core.material.f3.native_volume_mls.source_window.v1"
TRACE_SCHEMA_PREFIX = "core.material.f3.native_volume_mls.trace."
CHECKPOINT_SCHEMA_PREFIX = "core.material.f3.native_volume_mls.checkpoint."
NATIVE_INTERVAL_S = 0.002
NATIVE_CADENCE_TOLERANCE_S = 5.0e-5
FULL_WINDOW_S = 8.35
UNKNOWN_LIMIT = 0.01
CDF_LIMIT = 0.02
MATRIX_ROW_COUNT = 33
MATRIX_ROW_ORDER = "0-23 resolution_substep; 24-27 cadence; 28-32 seed_density"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_EVENTS = ("first_passage", "return", "residence")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _require_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _require_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _close(left: float, right: float, tolerance: float) -> bool:
    return abs(left - right) <= max(tolerance, 1.0e-12)


def _json_like(value: Any, path: str = "payload", active: set[int] | None = None) -> None:
    """Reject NaN/Infinity and non-JSON objects before producing a receipt."""
    if active is None:
        active = set()
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, dict):
        marker = id(value)
        if marker in active:
            raise ValueError(f"{path} contains a cycle")
        active.add(marker)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} has a non-string key")
                _json_like(item, f"{path}.{key}", active)
        finally:
            active.remove(marker)
        return
    if isinstance(value, list):
        marker = id(value)
        if marker in active:
            raise ValueError(f"{path} contains a cycle")
        active.add(marker)
        try:
            for index, item in enumerate(value):
                _json_like(item, f"{path}[{index}]", active)
        finally:
            active.remove(marker)
        return
    raise ValueError(f"{path} is not JSON-like")


def _artifact_bindings(value: Any) -> list[dict[str, str]]:
    rows = value
    if not isinstance(rows, list) or not rows:
        raise ValueError("artifact_bindings must be a non-empty list")
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_roles: set[str] = set()
    for index, raw in enumerate(rows):
        row = _require_object(raw, f"artifact_bindings[{index}]")
        artifact_id = _require_string(row.get("artifact_id"), f"artifact_bindings[{index}].artifact_id")
        role = _require_string(row.get("role"), f"artifact_bindings[{index}].role")
        digest = _require_digest(row.get("sha256"), f"artifact_bindings[{index}].sha256")
        if artifact_id in seen_ids:
            raise ValueError("artifact_bindings contains a duplicate artifact_id")
        if role in seen_roles:
            raise ValueError("artifact_bindings contains a duplicate role")
        seen_ids.add(artifact_id)
        seen_roles.add(role)
        normalized.append({"artifact_id": artifact_id, "role": role, "sha256": digest})
    required_roles = {"source_window", "checkpoint"}
    if not required_roles <= seen_roles:
        missing = sorted(required_roles - seen_roles)
        raise ValueError(f"artifact_bindings missing required roles: {missing}")
    if not ({"material_output", "trace"} & seen_roles):
        raise ValueError("artifact_bindings missing material_output or trace role")
    return normalized


def _validate_source_window(value: Any) -> dict[str, Any]:
    window = _require_object(value, "source_window")
    if window.get("schema") != SOURCE_WINDOW_SCHEMA:
        raise ValueError("source_window schema is not the native MLS source-window schema")
    start = _finite(window.get("start_s"), "source_window.start_s")
    end = _finite(window.get("end_s"), "source_window.end_s")
    observed_start = _finite(window.get("observed_start_s"), "source_window.observed_start_s")
    observed_end = _finite(window.get("observed_end_s"), "source_window.observed_end_s")
    native_interval = _finite(window.get("native_interval_s"), "source_window.native_interval_s")
    if start < 0 or end <= start or not _close(start, 0.0, 1.0e-9):
        raise ValueError("source_window time bounds are invalid")
    if not _close(end, FULL_WINDOW_S, 1.0e-9):
        raise ValueError("source_window.end_s is not the registered F3 full window")
    if not _close(observed_start, start, 1.0e-9) or not _close(observed_end, end, 1.0e-9):
        raise ValueError("source_window observed bounds do not cover the registered window")
    if not _close(native_interval, NATIVE_INTERVAL_S, NATIVE_CADENCE_TOLERANCE_S):
        raise ValueError("source_window native interval is not the registered .002 s cadence")
    for name in ("complete", "right_censored", "cadence_pass", "native_rows_exact", "no_stride_or_synthetic_cadence"):
        _require_bool(window.get(name), f"source_window.{name}")
    if window["complete"] is not True or window["right_censored"] is not False:
        raise ValueError("incomplete or right-censored source window cannot be accepted")
    if window["cadence_pass"] is not True or window["native_rows_exact"] is not True:
        raise ValueError("native cadence provenance did not pass")
    if window["no_stride_or_synthetic_cadence"] is not True:
        raise ValueError("synthetic or strided cadence cannot be accepted")
    frame_count = window.get("frame_count")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 2:
        raise ValueError("source_window.frame_count must contain at least two native frames")
    return {
        "schema": SOURCE_WINDOW_SCHEMA,
        "start_s": start,
        "end_s": end,
        "observed_start_s": observed_start,
        "observed_end_s": observed_end,
        "native_interval_s": native_interval,
        "frame_count": frame_count,
        **{name: window[name] for name in ("complete", "right_censored", "cadence_pass", "native_rows_exact", "no_stride_or_synthetic_cadence")},
    }


def _validate_checkpoint(value: Any) -> dict[str, Any]:
    checkpoint = _require_object(value, "checkpoint")
    schema = _require_string(checkpoint.get("schema"), "checkpoint.schema")
    if not schema.startswith(CHECKPOINT_SCHEMA_PREFIX):
        raise ValueError("checkpoint schema is not a native MLS checkpoint schema")
    for name in ("state_sha256", "file_sha256", "binding_sha256", "seed_hash"):
        _require_digest(checkpoint.get(name), f"checkpoint.{name}")
    committed = checkpoint.get("committed_frame")
    if isinstance(committed, bool) or not isinstance(committed, int) or committed < 2:
        raise ValueError("checkpoint.committed_frame must be at least two")
    fields = checkpoint.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("checkpoint.fields must be a non-empty list")
    if not {"position", "reliable", "permanent_unknown"} <= set(fields):
        raise ValueError("checkpoint.fields omit required native MLS state")
    checkpoint_npz = _require_string(checkpoint.get("checkpoint_npz"), "checkpoint.checkpoint_npz")
    return {
        "schema": schema,
        "state_sha256": checkpoint["state_sha256"],
        "file_sha256": checkpoint["file_sha256"],
        "binding_sha256": checkpoint["binding_sha256"],
        "seed_hash": checkpoint["seed_hash"],
        "committed_frame": committed,
        "fields": list(fields),
        "checkpoint_npz": checkpoint_npz,
    }


def _validate_cdf_bounds(row: Mapping[str, Any], event: str, side: str) -> None:
    cdf = row.get(f"{event}_cdf_bounds")
    if not isinstance(cdf, dict):
        raise ValueError(f"{side}.{event}_cdf_bounds is missing")
    times = cdf.get("time_s", cdf.get("value_s"))
    lower = cdf.get("lower_mass_fraction")
    upper = cdf.get("upper_mass_fraction")
    if not isinstance(times, list) or not isinstance(lower, list) or not isinstance(upper, list):
        raise ValueError(f"{side}.{event}_cdf_bounds is incomplete")
    if not times or len(times) != len(lower) or len(times) != len(upper):
        raise ValueError(f"{side}.{event}_cdf_bounds has inconsistent axes")
    previous = -math.inf
    for index, (time_s, low, high) in enumerate(zip(times, lower, upper)):
        time_value = _finite(time_s, f"{side}.{event}.time_s[{index}]")
        low_value = _finite(low, f"{side}.{event}.lower[{index}]")
        high_value = _finite(high, f"{side}.{event}.upper[{index}]")
        if time_value < previous or not 0.0 <= low_value <= high_value <= 1.0:
            raise ValueError(f"{side}.{event}_cdf_bounds is not a bounded monotone CDF")
        previous = time_value


def _validate_comparison(value: Any) -> dict[str, Any]:
    comparison = _require_object(value, "comparison")
    if comparison.get("schema") != COMPARISON_SCHEMA:
        raise ValueError("comparison schema is not the native MLS comparison schema")
    if comparison.get("status") != "diagnostic_only" or comparison.get("qualification_claim") != "none":
        raise ValueError("comparison carries a qualification claim")
    binding = _require_object(comparison.get("common_binding"), "comparison.common_binding")
    for name in ("source_definition", "event_definition"):
        _require_object(binding.get(name), f"comparison.common_binding.{name}")
    source_comparison = _require_object(comparison.get("source_comparison"), "comparison.source_comparison")
    if set(source_comparison) != {"0", "1"}:
        raise ValueError("comparison must contain exactly F3 source halves 0 and 1")
    normalized_sources: dict[str, Any] = {}
    for source, raw in source_comparison.items():
        item = _require_object(raw, f"comparison.source_comparison.{source}")
        for side in ("left", "right"):
            trace = _require_object(item.get(side), f"comparison.source_comparison.{source}.{side}")
            unknown = _finite(trace.get("final_unknown_fraction"), f"{source}.{side}.final_unknown_fraction")
            if not 0.0 <= unknown <= 1.0:
                raise ValueError("final unknown fraction must be in [0,1]")
            for event in _EVENTS:
                _validate_cdf_bounds(trace, event, f"{source}.{side}")
        difference = _require_object(item.get("difference"), f"comparison.source_comparison.{source}.difference")
        differences: dict[str, float] = {}
        for event in _EVENTS:
            key = f"{event}_cdf_sup_abs_difference_bound"
            value_at = _finite(difference.get(key), f"{source}.difference.{key}")
            if value_at < 0.0:
                raise ValueError(f"{key} cannot be negative")
            differences[event] = value_at
        normalized_sources[source] = {
            "left_unknown_fraction": float(item["left"]["final_unknown_fraction"]),
            "right_unknown_fraction": float(item["right"]["final_unknown_fraction"]),
            "cdf_sup_abs_difference_bound": differences,
            "unknown_pass": all(item[side]["final_unknown_fraction"] <= UNKNOWN_LIMIT for side in ("left", "right")),
            "cdf_pass": all(value <= CDF_LIMIT for value in differences.values()),
        }
    return {"schema": COMPARISON_SCHEMA, "sources": normalized_sources}


def _validate_matrix(value: Any) -> dict[str, Any]:
    rows = value
    if not isinstance(rows, list) or len(rows) != MATRIX_ROW_COUNT:
        raise ValueError("matrix_rows must contain exactly the registered 33 rows")
    normalized = []
    seen: set[int] = set()
    for index, raw in enumerate(rows):
        row = _require_object(raw, f"matrix_rows[{index}]")
        matrix_index = row.get("matrix_index")
        if isinstance(matrix_index, bool) or not isinstance(matrix_index, int) or not 0 <= matrix_index < MATRIX_ROW_COUNT:
            raise ValueError(f"matrix_rows[{index}].matrix_index is outside 0..32")
        if matrix_index in seen:
            raise ValueError("matrix_rows contains a duplicate matrix_index")
        seen.add(matrix_index)
        stage = _require_string(row.get("matrix_stage"), f"matrix_rows[{index}].matrix_stage")
        receipt = row.get("acceptance_receipt")
        _require_bool(receipt, f"matrix_rows[{index}].acceptance_receipt")
        if row.get("qualification_claim") != "none":
            raise ValueError("matrix row carries a qualification claim")
        normalized.append({
            "matrix_index": matrix_index,
            "matrix_stage": stage,
            "acceptance_receipt": receipt,
            "qualification_claim": "none",
        })
    if seen != set(range(MATRIX_ROW_COUNT)):
        raise ValueError("matrix_rows does not cover the registered 0..32 denominator")
    return {
        "row_count": MATRIX_ROW_COUNT,
        "row_order": MATRIX_ROW_ORDER,
        "acceptance_receipt_count": sum(row["acceptance_receipt"] for row in normalized),
        "ready": all(row["acceptance_receipt"] for row in normalized),
        "rows": sorted(normalized, key=lambda row: row["matrix_index"]),
    }


def build_receipt(
    *,
    comparison: Mapping[str, Any],
    source_window: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    artifact_bindings: list[Mapping[str, Any]],
    matrix_rows: list[Mapping[str, Any]],
    physical_case_id: str,
    case_id: str,
) -> dict[str, Any]:
    """Build a fail-closed diagnostic admission receipt from JSON evidence."""
    payload = {
        "comparison": comparison,
        "source_window": source_window,
        "checkpoint": checkpoint,
        "artifact_bindings": artifact_bindings,
        "matrix_rows": matrix_rows,
    }
    _json_like(payload)
    physical_case_id = _require_string(physical_case_id, "physical_case_id")
    case_id = _require_string(case_id, "case_id")
    comparison_summary = _validate_comparison(comparison)
    window_summary = _validate_source_window(source_window)
    checkpoint_summary = _validate_checkpoint(checkpoint)
    artifacts = _artifact_bindings(artifact_bindings)
    matrix_summary = _validate_matrix(matrix_rows)
    source_unknown_pass = all(
        summary["unknown_pass"] for summary in comparison_summary["sources"].values()
    )
    cdf_pass = all(summary["cdf_pass"] for summary in comparison_summary["sources"].values())
    gates = {
        "native_trace_schema": True,
        "native_checkpoint_schema": True,
        "native_cadence": True,
        "full_event_window": True,
        "per_source_unknown_mass": source_unknown_pass,
        "three_event_cdf_bounds": True,
        "cdf_scientific_gate": cdf_pass,
        "per_matrix_case_acceptance": matrix_summary["ready"],
    }
    failures = [name for name, passed in gates.items() if not passed]
    return {
        "schema": SCHEMA,
        "status": "admission_ready_but_non_qualifying" if not failures else "blocked_for_macro_t2",
        "diagnostic_only": True,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "physical_case_id": physical_case_id,
        "case_id": case_id,
        "fixed_gates": {
            "per_source_unknown_fraction_max": UNKNOWN_LIMIT,
            "cdf_sup_abs_max": CDF_LIMIT,
            "native_interval_s": NATIVE_INTERVAL_S,
            "native_cadence_tolerance_s": NATIVE_CADENCE_TOLERANCE_S,
            "full_window_s": FULL_WINDOW_S,
            "right_censored_counts_as_acceptance": False,
            "denominator_policy": "all geometric seeds; unknown and censored mass retained",
        },
        "gates": gates,
        "failure_reasons": failures,
        "comparison": comparison_summary,
        "source_window": window_summary,
        "checkpoint": checkpoint_summary,
        "artifact_bindings": artifacts,
        "matrix": matrix_summary,
        "execution_constraints": {
            "json_source_only": True,
            "hdf5_opened": False,
            "solver_started": False,
            "gpu_started": False,
            "training_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit_registered": 0,
        },
        "interpretation_boundary": (
            "This receipt joins native MLS evidence for admission/readiness only. "
            "It cannot grant F3 T2, alter the 33-row denominator, or replace exact "
            "root-owned CFD source assets."
        ),
    }


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"refusing to overwrite existing receipt: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--source-window", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--physical-case-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = build_receipt(
        comparison=_load(args.comparison),
        source_window=_load(args.source_window),
        checkpoint=_load(args.checkpoint),
        artifact_bindings=_load(args.artifacts),
        matrix_rows=_load(args.matrix),
        physical_case_id=args.physical_case_id,
        case_id=args.case_id,
    )
    _write_immutable(args.output, receipt)
    print(json.dumps({"schema": receipt["schema"], "status": receipt["status"], "output": str(args.output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
