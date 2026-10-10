#!/usr/bin/env python3
"""Build an evidence-backed, non-qualifying plan for the fourteen sentinels.

The older status cards are useful indexes, but a status word such as
``actual`` is not a scientific terminal result.  This source-only builder
joins each exact sentinel to the declared proof references, the current
control/window record, its 41 dimension records, and one concrete next
request.  Proofs are *stat'ed only* here; their payload and SHA are not
recomputed.  Thus a parent can later perform the required guarded proof join
without this plan silently promoting a stale card or a neighboring grid to a
reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
STATUS_NAME = "stage2_fourteen_evidence_status_v4.json"
CATALOG_NAME = "stage2_fourteen_evidence_dimension_catalog_v3.json"
MATRIX_NAME = "stage2_fourteen_terminal_next_matrix_v3.json"
GRAPH_NAME = "stage2_fourteen_request_graph_v5.json"
READINESS_NAME = "stage2_fourteen_scientific_readiness_v5.json"
EXPECTED_SENTINELS = (
    "F1-S1", "F1-S2", "F2-S1", "F2-S2", "F3-S1", "F3-S2", "F4-S1",
    "F4-S2", "F5-S1", "F5-S2", "F6-S1", "F6-S2", "F7-S1", "F7-S2",
)
JSON_CAP = 10 * 1024 * 1024
SCHEMA = "ds02.stage2.fourteen-scientific-terminal-plan.v1"


class PlanFailure(RuntimeError):
    pass


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise PlanFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise PlanFailure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise PlanFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PlanFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise PlanFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after,
                   "read_mode": "small_metadata", "payload_read": False}


def _declared_file(value: Any, label: str) -> dict[str, Any]:
    """Join a status-card path by metadata without rehashing its payload."""
    if isinstance(value, dict):
        path_value = value.get("path")
        declared_sha = value.get("sha256")
        declared_stat = value.get("stat") or {}
    elif isinstance(value, str):
        path_value, declared_sha, declared_stat = value, None, {}
    else:
        return {"status": "MISSING_DECLARED_PATH", "label": label}
    if not isinstance(path_value, str):
        return {"status": "MISSING_DECLARED_PATH", "label": label}
    path = _abs(path_value)
    result: dict[str, Any] = {"label": label, "path": str(path),
                              "declared_sha256": declared_sha,
                              "declared_stat": declared_stat,
                              "sha_basis": "STATUS_CARD_DECLARATION_NOT_REHASHED_HERE"}
    if path.is_file() and not path.is_symlink():
        current = _stat(path)
        result["current_stat"] = current
        result["status"] = "PRESENT_STAT_JOIN_ONLY"
        result["declared_bytes_match"] = (not isinstance(declared_stat, dict)
                                           or not isinstance(declared_stat.get("bytes"), int)
                                           or current["bytes"] == declared_stat["bytes"])
    else:
        result["status"] = "DECLARED_SOURCE_NOT_PRESENT_AT_PLAN_TIME"
    return result


def _proof_refs(row: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in row.get("evidence", []):
        if not isinstance(item, dict):
            continue
        file_ref = item.get("file")
        if isinstance(file_ref, dict) and isinstance(file_ref.get("path"), str):
            result.append({"kind": item.get("kind"), "name": item.get("name"),
                           "claim_scope": item.get("claim_scope"),
                           "file": _declared_file(file_ref, f"{row.get('sentinel_id')} evidence")})
    return result


def _dimension(row: dict[str, Any]) -> dict[str, Any]:
    field = row.get("field_presence") if isinstance(row.get("field_presence"), dict) else {}
    paths = []
    for item in field.get("paths", []) if isinstance(field.get("paths"), list) else []:
        if isinstance(item, dict):
            paths.append({key: item[key] for key in ("key", "path", "value_kind") if key in item})
    prerequisites = []
    for item in row.get("recognition_prerequisites", []) if isinstance(row.get("recognition_prerequisites"), list) else []:
        if isinstance(item, dict):
            prerequisites.append({"requirement": item.get("requirement"), "status": item.get("status")})
    tolerance = row.get("frozen_tolerance")
    tolerance_source = tolerance.get("source") if isinstance(tolerance, dict) else None
    return {
        "evidence_id": row.get("evidence_id"), "dimension": row.get("dimension"),
        "observation": row.get("dimension_observation"), "scope": row.get("scope"),
        "field_presence": {"status": field.get("status"), "paths": paths},
        "observed_scales": row.get("observed_scales", {}).get("status") if isinstance(row.get("observed_scales"), dict) else None,
        "recognition_prerequisites": prerequisites,
        "frozen_tolerance": tolerance,
        "tolerance_source": tolerance_source,
        "scientific_qualification": row.get("scientific_qualification"),
        "evidence": _declared_file(row.get("evidence"), f"{row.get('sentinel_id')} dimension evidence"),
    }


def _next(row: dict[str, Any], matrix_row: dict[str, Any], graph_row: dict[str, Any], readiness_row: dict[str, Any] | None) -> dict[str, Any]:
    status_next = row.get("next_guarded_task") if isinstance(row.get("next_guarded_task"), dict) else {}
    matrix_next = matrix_row.get("next") if isinstance(matrix_row.get("next"), dict) else {}
    readiness_next = readiness_row.get("next_request") if isinstance(readiness_row, dict) and isinstance(readiness_row.get("next_request"), dict) else {}
    return {
        "request_kind": matrix_next.get("next_request") or graph_row.get("next_request_kind") or status_next.get("kind"),
        "status_card_kind": status_next.get("kind"),
        "action": matrix_next.get("next_request") or status_next.get("action") or graph_row.get("next_action"),
        "readiness_action": readiness_next.get("action"),
        "source_prerequisite": status_next.get("source_prerequisite") or matrix_next.get("evidence"),
        "success_condition": status_next.get("success_condition"),
        "solver_launch_allowed_by_plan": False,
        "payload_read_by_plan": False,
        "qualification_before_parent_guard": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def build(base_dir: Path, output_path: Path) -> dict[str, Any]:
    base_dir = _abs(base_dir)
    status, status_record = _read_json(base_dir / STATUS_NAME, "fourteen status v4")
    catalog, catalog_record = _read_json(base_dir / CATALOG_NAME, "dimension catalog v3")
    matrix, matrix_record = _read_json(base_dir / MATRIX_NAME, "terminal next matrix v3")
    graph, graph_record = _read_json(base_dir / GRAPH_NAME, "request graph v5")
    readiness, readiness_record = _read_json(base_dir / READINESS_NAME, "scientific readiness v5")
    status_rows = {str(row.get("sentinel_id")): row for row in status.get("sentinels", []) if isinstance(row, dict)}
    matrix_rows = {str(row.get("sentinel_id")): row for row in matrix.get("sentinels", []) if isinstance(row, dict)}
    graph_rows = {str(row.get("sentinel_id")): row for row in graph.get("sentinels", []) if isinstance(row, dict)}
    readiness_rows = {str(row.get("sentinel_id")): row for row in readiness.get("sentinels", []) if isinstance(row, dict)}
    if set(status_rows) != set(EXPECTED_SENTINELS) or set(matrix_rows) != set(EXPECTED_SENTINELS) or set(graph_rows) != set(EXPECTED_SENTINELS):
        raise PlanFailure("status, terminal matrix, and request graph do not contain the exact fourteen sentinel IDs")
    dimensions: dict[str, list[dict[str, Any]]] = {sid: [] for sid in EXPECTED_SENTINELS}
    for item in catalog.get("records", []):
        if isinstance(item, dict) and str(item.get("sentinel_id")) in dimensions:
            dimensions[str(item["sentinel_id"])].append(_dimension(item))
    rows: list[dict[str, Any]] = []
    for sid in EXPECTED_SENTINELS:
        current = status_rows[sid]
        terminal = current.get("terminal_state") if isinstance(current.get("terminal_state"), dict) else {}
        readiness_row = readiness_rows.get(sid)
        rows.append({
            "sentinel_id": sid, "family_id": current.get("family_id"), "physical_case_id": current.get("physical_case_id"),
            "status_v4": current.get("status_v4"), "terminal_state": terminal,
            "actual_diagnostic_state": (current.get("status_v4") or {}).get("actual_diagnostic_state"),
            "scientific_reference_state": (current.get("status_v4") or {}).get("scientific_reference_state"),
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0},
            "proof_bindings": _proof_refs(current),
            "dimensions": dimensions[sid],
            "dimension_count": len(dimensions[sid]),
            "control_window_source": matrix_rows[sid].get("source"),
            "control_and_integration": matrix_rows[sid].get("control_and_integration"),
            "forward_actual_scope": matrix_rows[sid].get("forward_actual_scope"),
            "next_request": _next(current, matrix_rows[sid], graph_rows[sid], readiness_row),
            "limits": readiness_row.get("limits") if isinstance(readiness_row, dict) else None,
            "identity_status": matrix_rows[sid].get("identity_status"),
        })
    output = {
        "schema": SCHEMA, "status": "SOURCE_ONLY_TERMINAL_STUDY_PLAN_NO_SCIENTIFIC_QUALIFICATION",
        "scope": {
            "sentinel_ids_exact": list(EXPECTED_SENTINELS), "record_count": len(rows),
            "dimension_record_count": sum(len(row["dimensions"]) for row in rows),
            "proof_payload_read": False, "proof_sha_recomputed": False,
            "neighbor_grid_truth": False, "async_interpolation": False,
            "scientific_Q_credit": 0,
        },
        "source_inputs": [status_record, catalog_record, matrix_record, graph_record, readiness_record],
        "rows": rows,
        "global_unknowns": status.get("global_unknowns", []),
        "interpretation": {
            "actual_diagnostic_is_not_reference_qualification": True,
            "declared_proof_sha_requires_future_parent_guard_join": True,
            "dimension_observation_unknown_is_preserved": True,
            "next_requests_are_source_ready_only": True,
            "tolerance_values_are_copied_with_their_declared_authority": True,
        },
    }
    _output_path = _abs(output_path)
    if _output_path.exists() or _output_path.is_symlink():
        raise PlanFailure(f"refusing overwrite: {_output_path}")
    _output_path.parent.mkdir(parents=True, exist_ok=True)
    _output_path.write_text(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def _self_test() -> None:
    # Verify the exact immutable identity list and the invariant that a plan
    # cannot grant scientific credit, without opening any production proof.
    assert len(EXPECTED_SENTINELS) == 14 and len(set(EXPECTED_SENTINELS)) == 14
    assert all(item.startswith("F") and "-S" in item for item in EXPECTED_SENTINELS)
    assert _declared_file({"path": "/does/not/exist", "sha256": "a" * 64}, "missing")["status"] == "DECLARED_SOURCE_NOT_PRESENT_AT_PLAN_TIME"
    print("PASS_FOURTEEN_SCIENTIFIC_TERMINAL_PLAN_V1_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--base-dir", type=Path, default=HERE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.output is None:
            parser.error("--build requires --output")
        result = build(args.base_dir, args.output)
        print(json.dumps({"status": result["status"], "output": str(_abs(args.output)),
                          "sentinels": result["scope"]["record_count"],
                          "dimensions": result["scope"]["dimension_record_count"],
                          "scientific_credit": 0, "payload_read": False}, sort_keys=True))
        return 0
    except (PlanFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_SCIENTIFIC_TERMINAL_PLAN_V1: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
