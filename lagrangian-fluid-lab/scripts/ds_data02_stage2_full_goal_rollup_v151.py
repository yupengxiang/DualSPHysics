#!/usr/bin/env python3
"""Build the additive Stage2 full-goal evidence rollup (JSON only).

This is a lineage/index product.  It binds the immutable v27/v29/v30 and
ROOT136 products to the later bounded diagnostics (ROOT138--ROOT150), failed
attempts, pending launch boundaries, and the fourteen-sentinel source index.
It does not add cases to CURRENT336, does not merge the new F2 reference
recipes into the historical 118/1328 omission scope, and never opens H5,
BI4, OBI4, VTK, raw solver output, or a solver.

Reports which are large are registered by path, stat, and SHA only when the
manifest marks them ``stat_only``.  The compact independent proof remains
the source of the bounded result in that case.  Every qualification field is
kept UNKNOWN; a completed diagnostic is not a QI/QN/QE or physical-fate
claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.full-goal-rollup.v151"
MANIFEST_SCHEMA = "ds02.stage2.full-goal-rollup.manifest.v151"
FORBIDDEN_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".bi2", ".bi1", ".vtk"}
SHA256_HEX = 64


class RollupError(ValueError):
    """Raised when an evidence rollup has an open identity or scope."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stat_ref(path: Path, role: str, *, read_mode: str = "json") -> dict[str, Any]:
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
        "read_mode": read_mode,
    }


def require_json(path_value: Any, label: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise RollupError(f"{label} path is missing")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise RollupError(f"{label} must be absolute: {path}")
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


def expect(value: Any, wanted: Any, label: str) -> None:
    if value != wanted:
        raise RollupError(f"{label}: expected {wanted!r}, got {value!r}")


def unknown_block(value: Any, label: str) -> None:
    """Require qualification claims to remain explicitly UNKNOWN."""
    if not isinstance(value, dict):
        raise RollupError(f"{label} is not a qualification object")
    for key in ("QI", "QN", "QE"):
        if key in value and value[key] != "UNKNOWN":
            raise RollupError(f"{label}.{key} grants unsupported qualification")
    for key in ("physical_fate", "legal_outflow_or_spill", "legal_flux", "dynamical_impact", "dynamics"):
        if key in value and value[key] != "UNKNOWN":
            raise RollupError(f"{label}.{key} grants unsupported physical credit")


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


def load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, dict[str, Any] | None], dict[str, dict[str, Any]]]:
    manifest = read_json(path, "full-goal manifest")
    expect(manifest.get("schema"), MANIFEST_SCHEMA, "manifest schema")
    entries = manifest.get("source_refs")
    if not isinstance(entries, list) or not entries:
        raise RollupError("manifest source_refs is empty")
    paths: dict[str, Path] = {}
    values: dict[str, dict[str, Any] | None] = {}
    refs: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise RollupError("malformed manifest source reference")
        key = entry["key"]
        if key in paths:
            raise RollupError(f"duplicate source key: {key}")
        mode = entry.get("read_mode", "json")
        if mode not in {"json", "stat_only"}:
            raise RollupError(f"{key} has invalid read_mode")
        target = require_json(entry.get("path"), key)
        actual = sha256_file(target)
        if entry.get("sha256") != actual:
            raise RollupError(f"{key} SHA mismatch: declared {entry.get('sha256')}, actual {actual}")
        paths[key] = target
        refs[key] = entry
        values[key] = None if mode == "stat_only" else read_json(target, key)
    return manifest, paths, values, refs


def bound_file(proof: dict[str, Any], field: str, key: str, paths: dict[str, Path], label: str) -> None:
    value = proof.get(field)
    if value is None:
        return
    if not isinstance(value, str) or key not in paths or value != str(paths[key]):
        raise RollupError(f"{label} {field} does not bind manifest source {key}")
    digest_field = f"{field}_sha256"
    if proof.get(digest_field) is not None and proof[digest_field] != sha256_file(paths[key]):
        raise RollupError(f"{label} {digest_field} mismatch")


def receipt_state(receipt: dict[str, Any], label: str) -> str:
    status = receipt.get("status")
    if not isinstance(status, str):
        raise RollupError(f"{label} has unknown status {status!r}")
    status_upper = status.upper()
    failure_status = status_lower = status.lower()
    is_failure = status_lower in {"failed", "cancelled", "interrupted"} or any(token in status_upper for token in ("FAIL", "CANCEL", "INTERRUPT"))
    if status_lower not in {"completed", "failed", "cancelled", "interrupted", "running", "started"} and not is_failure:
        raise RollupError(f"{label} has unknown status {status!r}")
    # A few historical managed parent attempts deliberately emitted a
    # producer-specific failure receipt rather than the normal execution
    # receipt.  Preserve and classify those bytes; only a completed edge must
    # carry the canonical ds02.execution-receipt.v1 schema.
    if receipt.get("schema") != "ds02.execution-receipt.v1" and not is_failure:
        raise RollupError(f"{label} has unexpected nonterminal receipt schema")
    return status


def is_failure_status(status: str) -> bool:
    upper = status.upper()
    return status.lower() in {"failed", "cancelled", "interrupted"} or any(token in upper for token in ("FAIL", "CANCEL", "INTERRUPT"))


def proof_edge(
    edge: dict[str, Any],
    paths: dict[str, Path],
    values: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    edge_id = edge.get("edge_id")
    proof_key = edge.get("proof_key")
    if not isinstance(edge_id, str) or not isinstance(proof_key, str) or proof_key not in values:
        raise RollupError(f"malformed evidence edge: {edge}")
    proof = values[proof_key]
    if not isinstance(proof, dict):
        raise RollupError(f"{edge_id} proof is unavailable")
    schema = proof.get("schema")
    status = proof.get("status")
    if not isinstance(schema, str) or not isinstance(status, str):
        raise RollupError(f"{edge_id} proof lacks schema/status")
    for field, suffix in (("report", "report"), ("receipt", "receipt"), ("request", "request")):
        if proof.get(field) is None:
            continue
        target_key = edge.get(f"{suffix}_key") or f"{proof_key}_{suffix}"
        bound_file(proof, field, target_key, paths, edge_id)
    q = proof.get("scientific_qualification")
    if q is not None:
        unknown_block(q, f"{edge_id} scientific qualification")
    for key in ("qualification", "claim_boundary", "scope_limits"):
        value = proof.get(key)
        if isinstance(value, dict):
            unknown_block(value, f"{edge_id} {key}")
    if proof.get("H5_BI4_read_by_root") is True or proof.get("root_array_content_read") is True:
        raise RollupError(f"{edge_id} reports forbidden array content credit")
    if proof.get("old_products_unchanged") is False:
        raise RollupError(f"{edge_id} reports an old product mutation")

    boundary = schema.endswith("managed-external-launch-boundary.v1") or schema.endswith("actual-launch-boundary.v1")
    receipt_key = edge.get("receipt_key") or f"{proof_key}_receipt"
    receipt = values.get(receipt_key)
    terminal_kind = "pending_nonterminal"
    actual_status = "NOT_TERMINAL"
    if boundary:
        if "NOT_TERMINAL" not in status and "RUNNING" not in status and "PENDING" not in status:
            raise RollupError(f"{edge_id} boundary status is not explicitly nonterminal")
    else:
        if receipt is None:
            raise RollupError(f"{edge_id} terminal proof lacks receipt source")
        receipt_status = receipt_state(receipt, f"{edge_id} receipt")
        failed = (
            edge.get("expected_kind") == "failed_attempt"
            or is_failure_status(status)
            or isinstance(proof.get("failure"), (dict, str))
            or proof.get("cold_end_to_end_success") is False
        )
        if failed:
            if not is_failure_status(receipt_status) and receipt.get("returncode") in (None, 0):
                raise RollupError(f"{edge_id} failure proof is not backed by a failed receipt")
            terminal_kind = "failed_attempt"
            actual_status = receipt_status
        else:
            if receipt_status != "completed" or receipt.get("returncode") not in (None, 0):
                raise RollupError(f"{edge_id} terminal proof is not backed by completed receipt")
            terminal_kind = "actual_completed_diagnostic"
            actual_status = receipt_status
    return {
        "edge_id": edge_id,
        "kind": terminal_kind,
        "proof_schema": schema,
        "proof_status": status,
        "receipt_status": actual_status,
        "scientific_credit": "NONE",
        "scope": edge.get("scope", "bounded evidence only"),
        "physical_fate": "UNKNOWN",
        "dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "source": stat_ref(paths[proof_key], edge.get("role", edge_id)),
    }


def validate_catalogs(values: dict[str, dict[str, Any] | None], paths: dict[str, Path]) -> dict[str, Any]:
    v27 = values.get("v27_product")
    v29 = values.get("v29_catalog")
    v30 = values.get("v30_catalog")
    if not isinstance(v27, dict) or not isinstance(v29, dict) or not isinstance(v30, dict):
        raise RollupError("v27/v29/v30 catalog inputs are missing")
    expect(v27.get("schema"), "ds02.stage2.final-family-product.v27", "v27 schema")
    expect(v29.get("schema"), "ds02.stage2.final-qualification-catalog.v29", "v29 schema")
    expect(v30.get("schema"), "ds02.stage2.task-scope-catalog.v30", "v30 schema")
    cov27, cov29, cov30 = v27.get("coverage", {}), v29.get("coverage", {}), v30.get("coverage", {})
    expect(cov27.get("current_case_count"), 336, "v27 current cases")
    expect(cov27.get("native_alias_cases"), 118, "v27 native cases")
    expect(cov27.get("native_alias_ids"), 1328, "v27 native IDs")
    expect(cov29.get("current_cases"), 336, "v29 current cases")
    expect(cov29.get("native_impact_cases"), 118, "v29 native cases")
    expect(cov30.get("current_cases"), 336, "v30 current cases")
    unknown_block(v27.get("claim_boundary"), "v27 claim boundary")
    unknown_block(v29.get("claim_boundary"), "v29 claim boundary")
    unknown_block(v30.get("claim_boundary"), "v30 claim boundary")
    unknown_block(v29.get("scientific_qualification"), "v29 qualification")
    unknown_block(v30.get("task_qualification"), "v30 task qualification")
    cases = v29.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise RollupError("v29 case inventory is not exactly 336 rows")
    keys = []
    for row in cases:
        if not isinstance(row, dict) or not isinstance(row.get("case_key"), str):
            raise RollupError("v29 case identity is malformed")
        keys.append(row["case_key"])
    if len(set(keys)) != 336:
        raise RollupError("v29 case identity is not unique")
    cards = v27.get("family_cards")
    if not isinstance(cards, dict) or set(cards) != {f"F{i}" for i in range(1, 8)}:
        raise RollupError("v27 does not expose exactly seven family cards")
    return {
        "v27": stat_ref(paths["v27_product"], "immutable v27 family product"),
        "v29": stat_ref(paths["v29_catalog"], "immutable v29 qualification catalog"),
        "v30": stat_ref(paths["v30_catalog"], "immutable v30 task-scope catalog"),
        "current_cases": 336,
        "family_counts": cov27.get("family_counts"),
        "family_cards": 7,
        "original_native_omission_cases": 118,
        "original_native_identity_count": 1328,
        "all_q_unknown": True,
        "case_keys_sha256": hashlib.sha256("\n".join(keys).encode()).hexdigest(),
        "authoritative_products_unchanged": True,
    }


def validate_fourteen(values: dict[str, dict[str, Any] | None], paths: dict[str, Path]) -> dict[str, Any]:
    status = values.get("fourteen_source_status")
    queue = values.get("fourteen_next_requests")
    matrix = values.get("fourteen_terminal_matrix")
    if not isinstance(status, dict) or not isinstance(queue, dict) or not isinstance(matrix, dict):
        raise RollupError("fourteen-sentinel source index is incomplete")
    sentinels = status.get("sentinels")
    requests = queue.get("requests")
    matrix_rows = matrix.get("sentinels")
    if not isinstance(sentinels, list) or len(sentinels) != 14 or not isinstance(requests, list) or len(requests) != 14 or not isinstance(matrix_rows, list) or len(matrix_rows) != 14:
        raise RollupError("fourteen-sentinel count is not exactly 14")
    ids = [row.get("sentinel_id") for row in sentinels if isinstance(row, dict)]
    qids = [row.get("sentinel_id") for row in requests if isinstance(row, dict)]
    mids = [row.get("sentinel_id") for row in matrix_rows if isinstance(row, dict)]
    if len(set(ids)) != 14 or ids != qids or set(ids) != set(mids):
        raise RollupError("fourteen-sentinel identity/index mismatch")
    by_id = {row["sentinel_id"]: row for row in matrix_rows}
    rows = []
    for row in sentinels:
        sid = row["sentinel_id"]
        terminal = row.get("terminal_state") or {}
        qualification = terminal.get("scientific_qualification") or {}
        unknown_block(qualification, f"{sid} terminal qualification")
        queued = next(item for item in requests if item.get("sentinel_id") == sid)
        unknown_block(queued.get("qualification_after_task") or {}, f"{sid} next qualification")
        rows.append({
            "sentinel_id": sid,
            "family_id": row.get("family_id"),
            "physical_case_id": row.get("physical_case_id"),
            "terminal_status": terminal.get("status", "UNKNOWN"),
            "next_state": queued.get("state", "UNKNOWN"),
            "next_request_id": queued.get("request_id"),
            "identity_status": by_id[sid].get("identity_status", "UNKNOWN"),
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        })
    return {
        "count": 14,
        "sentinels": rows,
        "status": status.get("status"),
        "next_queue_status": queue.get("status"),
        "terminal_matrix_status": matrix.get("status"),
        "source": {
            "status": stat_ref(paths["fourteen_source_status"], "fourteen source status"),
            "next_requests": stat_ref(paths["fourteen_next_requests"], "fourteen next-request queue"),
            "terminal_matrix": stat_ref(paths["fourteen_terminal_matrix"], "fourteen terminal matrix"),
        },
        "claim_boundary": "source/status/next-edge index only; no QI/QN/QE, continuous-event, fate, or dynamics credit",
    }


def derive(manifest_path: Path) -> dict[str, Any]:
    manifest, paths, values, refs = load_manifest(manifest_path)
    catalog = validate_catalogs(values, paths)
    fourteen = validate_fourteen(values, paths)
    edge_specs = manifest.get("evidence_edges")
    if not isinstance(edge_specs, list) or not edge_specs:
        raise RollupError("manifest evidence_edges is empty")
    edges = [proof_edge(edge, paths, values) for edge in edge_specs]
    completed = [edge for edge in edges if edge["kind"] == "actual_completed_diagnostic"]
    failed = [edge for edge in edges if edge["kind"] == "failed_attempt"]
    pending = [edge for edge in edges if edge["kind"] == "pending_nonterminal"]
    # Explicitly preserve the new reference scopes and never infer them from
    # the historical 118/1328 counts.
    new_refs = {
        "F2_ROOT126_ROOT129": {
            "case_scope": "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0088_T4_COARSE_CANARY_ROOT_095",
            "native_identity_count": 153,
            "merged_into_original_336": False,
            "source": "ROOT136 predecessor product; retained as a distinct recipe",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "F2_ROOT138_DOMAIN_CONTROL": {
            "case_scope": "F2 ROOT130 coarse domain sensitivity reference",
            "native_identity_count": 67,
            "native_motive": "position (actual per-ID report)",
            "merged_into_original_336": False,
            "common_with_ROOT126": 27,
            "ROOT126_only": 126,
            "ROOT138_only": 40,
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "F3_ROOT150_FULL836": {
            "case_scope": "F3_S2_COARSE_FULL_NATIVE_STREAM_V3_ROOT_150",
            "native_frame_count": 836,
            "native_identity_count": 24264,
            "merged_into_original_336": False,
            "source_scope": "new reference stream audit; no CURRENT omission merge",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "F7_ROOT149_FACE_LATTICE": {
            "case_scope": "F7 three-grid coordinate/face/lattice diagnostic",
            "coarse_face_event_count": 810,
            "coarse_face_axis": "y_high",
            "coarse_violation_m": 1.1102230246251565e-16,
            "four_ulp_extended_outside_count": 0,
            "merged_into_original_336": False,
            "qualification": "diagnostic only; GenCase rounding and physical contact remain UNKNOWN",
        },
    }
    return {
        "schema": SCHEMA,
        "status": "ACTUAL_EVIDENCE_BOUND_FULL_GOAL_ROLLUP_NO_SCIENTIFIC_QUALIFICATION",
        "purpose": "Additive evidence/task graph over immutable Stage2 products and bounded later diagnostics.",
        "source_manifest": stat_ref(manifest_path, "full-goal rollup manifest"),
        "predecessors": {
            "root136": "actual predecessor rollup retained; no mutation",
            "v29": "authoritative 336-case qualification catalog",
            "v30": "authoritative task-scope index",
            "root150": "new actual F3 836-frame source audit, separate reference scope",
        },
        "original_catalog": catalog,
        "fourteen_sentinel_coverage": fourteen,
        "evidence_edges": {
            "completed_diagnostics": completed,
            "failed_attempts": failed,
            "pending_or_nonterminal": pending,
            "counts": {"completed": len(completed), "failed": len(failed), "pending": len(pending)},
        },
        "new_reference_scopes": new_refs,
        "task_graph": {
            "nodes": ["CURRENT336_V29", "TASK_SCOPE_V30", "ROOT136", "ROOT138", "ROOT139", "ROOT141", "ROOT142", "ROOT143", "ROOT146", "ROOT147", "ROOT148", "ROOT149", "ROOT150", "ROOT151"],
            "edges": [
                {"from": "CURRENT336_V29", "to": "TASK_SCOPE_V30", "kind": "immutable_catalog_to_task_scope"},
                {"from": "TASK_SCOPE_V30", "to": "ROOT151", "kind": "catalog_scope_input"},
                {"from": "ROOT136", "to": "ROOT151", "kind": "predecessor_rollup"},
                {"from": "ROOT133", "to": "ROOT150", "kind": "pending_launch_to_actual_new_stream_scope", "status": "historical_launch_sha_unknown; ROOT150 actual source is authoritative"},
                {"from": "ROOT146", "to": "ROOT148", "kind": "F7_grid_input_to_face_diagnostic"},
                {"from": "ROOT148", "to": "ROOT149", "kind": "aggregate_to_per_id_face_lattice"},
                {"from": "ROOT150", "to": "ROOT151", "kind": "actual_full836_diagnostic_edge"},
            ],
            "pending_edges_are_not_scientific_credit": True,
        },
        "scope_separation": {
            "original_current336_cases": 336,
            "original_native_omission_cases": 118,
            "original_native_identity_count": 1328,
            "new_reference_cases_not_merged": ["F2_ROOT126_ROOT129", "F2_ROOT138_DOMAIN_CONTROL", "F3_ROOT150_FULL836", "F7_ROOT149_FACE_LATTICE"],
            "new_reference_counts_do_not_modify_original_118_or_1328": True,
            "all_current_cases_exposed_to_catalog": True,
        },
        "qualification_boundary": {
            "task_inventory_and_source_identity": "ELIGIBLE_ONLY_WITHIN_EACH_EXPLICIT_SOURCE_SCOPE",
            "saved_frame_or_initial_bookkeeping": "LIMITED_DIAGNOSTIC_SCOPE_ONLY",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_outflow_or_spill": "UNKNOWN",
            "wall_contact_or_penetration": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "hidden_crossings_and_recrossings": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "conversion_implementation": "UNKNOWN_WHERE_NOT_SOURCE_CLOSED",
            "neighboring_grid_as_truth": "FORBIDDEN",
        },
        "source_access": {
            "json_only": True,
            "h5_opened_by_rollup": False,
            "bi4_opened_by_rollup": False,
            "vtk_opened_by_rollup": False,
            "raw_solver_output_opened_by_rollup": False,
            "solver_started_by_rollup": False,
            "old_products_modified": False,
        },
        "old_products_unchanged": True,
        "next_edges": {
            "root150": "actual terminal proof is included; no further claim beyond its bounded 836-frame fields and bracketed queries",
            "root133": "historical launch boundary retained separately; no retroactive all836 producer hash",
            "root140": "failed source-closure attempt retained; no conversion product",
            "root144": "failed manifest-schema attempt retained; no native-header science credit",
            "future": "any coarse candidate or additional F7 interpretation requires a new version and explicit source/physics contract",
        },
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
