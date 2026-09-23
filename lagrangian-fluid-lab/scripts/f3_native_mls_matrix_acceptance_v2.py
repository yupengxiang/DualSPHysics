"""Strict JSON-only acceptance of the complete F3 native-MLS matrix.

The v1 adapter accepted a 33-row denominator whose per-row evidence was only
a caller-supplied boolean.  This version requires typed, per-row evidence and
explicit artifact hash references, evaluates the frozen scientific gates per
row, and still never grants T2 credit.  HDF5/NPZ payloads are not opened; their
immutable artifact hashes are supplied by the execution receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from scripts import f3_native_mls_acceptance_adapter_v1 as v1


SCHEMA = "core.material.f3.native_mls_matrix_acceptance.v2"
MATRIX_EVIDENCE_SCHEMA = "core.material.f3.native_mls_matrix_evidence.v2"
MATRIX_ROW_COUNT = v1.MATRIX_ROW_COUNT
ROW_STAGE_BY_INDEX = tuple(
    "resolution_substep" if index < 24 else
    "cadence" if index < 28 else
    "seed_density"
    for index in range(MATRIX_ROW_COUNT)
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_row(raw: Any, seen_ids: set[int], seen_configs: set[str]) -> dict[str, Any]:
    row = v1._require_object(raw, "matrix row")
    index = row.get("matrix_index")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < MATRIX_ROW_COUNT:
        raise ValueError("matrix_index must be in 0..32")
    if index in seen_ids:
        raise ValueError("matrix evidence contains a duplicate matrix_index")
    seen_ids.add(index)
    stage = v1._require_string(row.get("matrix_stage"), "matrix_stage")
    if stage != ROW_STAGE_BY_INDEX[index]:
        raise ValueError(f"matrix row {index} must use stage {ROW_STAGE_BY_INDEX[index]}")
    config_digest = row.get("configuration_sha256")
    if not isinstance(config_digest, str) or not _SHA256.fullmatch(config_digest):
        raise ValueError("configuration_sha256 must be a lowercase SHA-256 digest")
    if config_digest in seen_configs:
        raise ValueError("matrix evidence contains a duplicate configuration binding")
    seen_configs.add(config_digest)
    physical_case_id = v1._require_string(row.get("physical_case_id"), "physical_case_id")
    case_id = v1._require_string(row.get("case_id"), "case_id")
    trace_schema = v1._require_string(row.get("trace_schema"), "trace_schema")
    if not trace_schema.startswith(v1.TRACE_SCHEMA_PREFIX):
        raise ValueError("trace_schema is not a native-MLS trace schema")

    evidence = v1._require_object(row.get("evidence"), "evidence")
    comparison = v1._validate_comparison(evidence.get("comparison"))
    source_window = v1._validate_source_window(evidence.get("source_window"))
    checkpoint = v1._validate_checkpoint(evidence.get("checkpoint"))
    artifact_bindings = v1._artifact_bindings(evidence.get("artifact_bindings"))
    roles = {item["role"] for item in artifact_bindings}
    if "comparison" not in roles:
        raise ValueError("row artifact_bindings must include comparison")

    source_pass = all(item["unknown_pass"] for item in comparison["sources"].values())
    cdf_pass = all(item["cdf_pass"] for item in comparison["sources"].values())
    gates = {
        "native_trace_schema": True,
        "native_checkpoint_schema": True,
        "native_cadence": source_window["cadence_pass"] and source_window["native_rows_exact"],
        "full_event_window": source_window["complete"] and not source_window["right_censored"],
        "per_source_unknown_mass": source_pass,
        "three_event_cdf_bounds": True,
        "cdf_scientific_gate": cdf_pass,
        "row_artifacts_bound": True,
    }
    return {
        "matrix_index": index,
        "matrix_stage": stage,
        "configuration_sha256": config_digest,
        "physical_case_id": physical_case_id,
        "case_id": case_id,
        "passed": all(gates.values()),
        "qualification_claim": "none",
        "qualification_credit": 0,
        "gates": gates,
        "failure_reasons": [name for name, passed in gates.items() if not passed],
        "evidence_sha256": _canonical_digest(evidence),
        "comparison": comparison,
        "source_window": source_window,
        "checkpoint": checkpoint,
        "artifact_bindings": artifact_bindings,
    }


def build_matrix_receipt(*, matrix_evidence: Mapping[str, Any], scope_id: str) -> dict[str, Any]:
    """Evaluate all 33 native-MLS rows without trusting supplied pass booleans."""
    payload = dict(matrix_evidence)
    v1._json_like(payload)
    if payload.get("schema") != MATRIX_EVIDENCE_SCHEMA:
        raise ValueError("matrix evidence schema mismatch")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != MATRIX_ROW_COUNT:
        raise ValueError("matrix evidence must contain exactly 33 rows")
    scope_id = v1._require_string(scope_id, "scope_id")
    seen_ids: set[int] = set()
    seen_configs: set[str] = set()
    seen_case_ids: set[str] = set()
    normalized = [
        _validate_row(row, seen_ids, seen_configs)
        for row in rows
    ]
    if seen_ids != set(range(MATRIX_ROW_COUNT)):
        raise ValueError("matrix evidence does not cover the registered 0..32 denominator")
    for row in normalized:
        if row["case_id"] in seen_case_ids:
            raise ValueError("matrix evidence contains a duplicate case_id")
        seen_case_ids.add(row["case_id"])
    seen_output_artifacts: set[tuple[str, str]] = set()
    for row in normalized:
        for binding in row["artifact_bindings"]:
            role = binding["role"]
            if role not in {"comparison", "checkpoint", "trace", "material_output"}:
                continue
            identity = (role, binding["artifact_id"])
            if identity in seen_output_artifacts:
                raise ValueError(f"matrix evidence reuses a {role} artifact across rows")
            seen_output_artifacts.add(identity)
    normalized.sort(key=lambda item: item["matrix_index"])
    passed_rows = sum(item["passed"] for item in normalized)
    gates = {
        "full_matrix_denominator": len(normalized) == MATRIX_ROW_COUNT,
        "all_rows_pass_fixed_gates": passed_rows == MATRIX_ROW_COUNT,
    }
    failures = [name for name, passed in gates.items() if not passed]
    return {
        "schema": SCHEMA,
        "status": "matrix_evidence_complete_but_non_qualifying" if not failures else "blocked_for_macro_t2",
        "scope_id": scope_id,
        "matrix_evidence_sha256": _canonical_digest(payload),
        "matrix": {
            "row_count": MATRIX_ROW_COUNT,
            "row_order": v1.MATRIX_ROW_ORDER,
            "evaluated_row_count": len(normalized),
            "passed_row_count": passed_rows,
            "failed_row_count": MATRIX_ROW_COUNT - passed_rows,
            "ready": all(gates.values()),
            "rows": normalized,
        },
        "gates": gates,
        "failure_reasons": failures,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T2_macro": False,
        "T2_path": False,
        "fixed_gates": {
            "per_source_unknown_fraction_max": v1.UNKNOWN_LIMIT,
            "cdf_sup_abs_max": v1.CDF_LIMIT,
            "native_interval_s": v1.NATIVE_INTERVAL_S,
            "native_cadence_tolerance_s": v1.NATIVE_CADENCE_TOLERANCE_S,
            "full_window_s": v1.FULL_WINDOW_S,
            "right_censored_counts_as_acceptance": False,
            "denominator_policy": "all 33 registered matrix rows; unknown and censored mass retained",
        },
        "execution_constraints": {
            "json_source_only": True,
            "hdf5_opened": False,
            "npz_opened": False,
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
            "This receipt evaluates typed per-row JSON evidence under the frozen 33-row denominator. "
            "It is not an independent root review and never grants T2 qualification or credit."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON core.material.f3.native_mls_matrix_evidence.v2")
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.input.read_bytes()
    matrix_evidence = json.loads(raw.decode("utf-8"))
    receipt = build_matrix_receipt(matrix_evidence=matrix_evidence, scope_id=args.scope_id)
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"schema": receipt["schema"], "status": receipt["status"], "output": str(output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
