#!/usr/bin/env python3
"""Build a source-bound, launch-disabled parent chain for all 14 sentinels.

This is the execution handoff between the actual small-proof inventory and a
future guarded parent.  It deliberately keeps three things separate:

* evidence that already exists and can be reused within its recorded scope;
* a concrete next worker/CLI contract and its parent materialisation gates;
* the scientific result, which remains UNKNOWN until that worker and its
  registered comparison have actually completed.

The builder reads only the small readiness/graph JSON files and the source
files for the listed workers.  It does not open native, VTK, BI4, H5, solver
reports, large forcing files, or product payloads.  Every emitted request is
execution-disabled and carries no scientific credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REFERENCE = HERE
PRIMARY_REFERENCE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
READINESS = REFERENCE / "stage2_fourteen_scientific_terminal_readiness_v2.json"
READINESS_V7 = REFERENCE / "stage2_fourteen_actual_evidence_readiness_v7.json"
GRAPH = REFERENCE / "stage2_fourteen_request_graph_v5.json"
CAP = 10 * 1024 * 1024
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SCHEMA = "ds02.stage2.fourteen-actual-parent-chain.v1"


class ChainFailure(RuntimeError):
    pass


WORKER_SPECS: dict[str, dict[str, Any]] = {
    "JSON_ONLY_EXISTING_OBSERVER_COMPARISON": {
        "worker": "stage2_f1_s1_cross_grid_geometry_diagnostic_v1.py",
        "stage": "existing_observer_metadata_comparison",
        "argv": ["--output", "{attempt_root}/report/observer-comparison.json"],
        "requires": ["actual producer/receipt/proof joins", "common saved-time/bracket metadata", "no interpolation"],
        "resources": {"cpu_threads": 1, "memory_bytes": 1073741824, "wall_seconds": 300, "storage": "small JSON report"},
    },
    "SELECTED_NATIVE_OBSERVER_AND_RUNPART_BRACKET_AUDIT": {
        "worker": "stage2_f1_s2_root279_native_compact_worker_v3.py",
        "stage": "selected_native_observer_and_runpart_bracket",
        "argv": ["--run", "--manifest", "{attempt_root}/manifest.json", "--output-dir", "{attempt_root}/report/native"],
        "requires": ["terminal solver receipt", "RunPARTs-derived frame IDs", "native header fields", "pre/post SHA/stat"],
        "resources": {"cpu_threads": 1, "memory_bytes": 4294967296, "wall_seconds": 1800, "storage": "selected native frames deferred; parent estimates from current stat"},
    },
    "SOURCE_OWNER_SUPPORT_AND_PER_MATERIAL_AUDIT": {
        "worker": "stage2_continuum_geometry_bounds_v1.py",
        "stage": "continuous_owner_geometry_repair_audit",
        "argv": ["--quality", "{attempt_root}/inputs/source-quality.json", "--output", "{attempt_root}/report/owner-geometry.json"],
        "requires": ["sentinel-specific owner geometry", "Fluid/Bound support and overlap", "native roles", "no mass rescale"],
        "resources": {"cpu_threads": 1, "memory_bytes": 2147483648, "wall_seconds": 600, "storage": "metadata/geometry report"},
    },
    "CPU_GENCASE_INITIAL_SUPPORT_QA": {
        "worker": "stage2_three_sentinel_owner_grid_initial_support_verify_v3.py",
        "stage": "initial_support_and_native_mass_gate",
        "argv": ["--verify", "--manifest", "{attempt_root}/support-manifest.json", "--request", "{attempt_root}/support-request.json", "--output", "{attempt_root}/report/initial-support.json", "--verification-output", "{attempt_root}/report/initial-support-verification.json"],
        "requires": ["terminal GenCase receipt", "source Def/XML/control closure", "native MassFluid/MassBound/Dp", "Fluid/Bound/Idp roles"],
        "resources": {"cpu_threads": 1, "memory_bytes": 4294967296, "wall_seconds": 900, "storage": "parent-reserved GenCase outputs; no solver"},
    },
    "BOUNDED_SELECTED_NATIVE_OBSERVER_AUDIT": {
        "worker": "stage2_native_physical_observer_v2.py",
        "stage": "bounded_native_observer",
        "argv": ["--raw-root", "{attempt_root}/inputs/native", "--runparts", "{attempt_root}/inputs/RunPARTs.csv", "--generated-xml", "{attempt_root}/inputs/generated.xml", "--decoder", "{attempt_root}/inputs/bi4_dump", "--decoder-source", "{attempt_root}/inputs/bi4_dump.cpp", "--output", "{attempt_root}/report/native-observer.json", "--scratch-root", "{attempt_root}/scratch", "--expected-frame-count", "{expected_frame_count}", "--expected-final-time-s", "{expected_final_time_s}", "--frames", "{frames}", "--query-times", "{query_times}"],
        "requires": ["continuous-owner/support gate", "terminal solver receipt", "selected native frame stat/SHA", "RunPARTs time source"],
        "resources": {"cpu_threads": 1, "memory_bytes": 4294967296, "wall_seconds": 1800, "storage": "parent-reserved selected frames"},
    },
    "ROOT240_COMPACT_SPATIAL_LIFECYCLE_COMPARISON": {
        "worker": "stage2_f3_s2_compact_spatial_lifecycle_compare_v2.py",
        "stage": "compact_spatial_lifecycle_comparison",
        "argv": ["--manifest", "{attempt_root}/manifest.json", "--output", "{attempt_root}/report/spatial-lifecycle.json"],
        "requires": ["coarse/middle/fine proof joins", "stable compact summary SHA/stat", "lost/reappear/new identity semantics", "no interpolation"],
        "resources": {"cpu_threads": 1, "memory_bytes": 8589934592, "wall_seconds": 1800, "storage": "deferred compact reports; parent reads after reservation"},
    },
    "BOUNDED_COMMON_TIME_OBSERVER_COMPARISON": {
        "worker": "stage2_f4_physical_observer_compare_v1.py",
        "stage": "common_time_observer_comparison",
        "argv": ["--reference", "{attempt_root}/inputs/reference.json", "--variant", "{attempt_root}/inputs/variant.json", "--output", "{attempt_root}/report/common-time.json", "--physical-case-id", "{physical_case_id}"],
        "requires": ["actual timestamps/brackets", "same source/control identity", "native fields", "integral and output checks separated"],
        "resources": {"cpu_threads": 1, "memory_bytes": 2147483648, "wall_seconds": 600, "storage": "small observer reports"},
    },
    "CPU_INITIAL_SUPPORT_QA_THEN_ONE_CANARY": {
        "worker": "stage2_four_sentinel_frame0_support_audit_v4.py",
        "stage": "initial_support_before_single_canary",
        "argv": ["--run", "--manifest", "{attempt_root}/support-manifest.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/report/initial-support.json"],
        "requires": ["source/control closure", "Fluid/Bound support", "native roles/header", "one source-matched canary only after support"],
        "resources": {"cpu_threads": 1, "memory_bytes": 4294967296, "wall_seconds": 900, "storage": "parent-reserved support products"},
    },
    "SOURCE_BOUND_GEOMETRY_DIAGNOSTIC": {
        "worker": "stage2_f5_s1_clipplane_geometry_diagnostic_v8.py",
        "stage": "official_clip_and_overlap_diagnostic",
        "argv": ["--generated-xml", "{attempt_root}/inputs/generated.xml", "--fluid-vtk", "{attempt_root}/inputs/generated_Fluid.vtk", "--bound-vtk", "{attempt_root}/inputs/generated_Bound.vtk", "--receipt", "{attempt_root}/inputs/execution-receipt.json", "--candidate-def", "{attempt_root}/inputs/candidate_Def.xml", "--source-def", "{attempt_root}/inputs/source_Def.xml", "--candidate-motion", "{attempt_root}/inputs/candidate_motion.dat", "--source-motion", "{attempt_root}/inputs/source_motion.dat", "--clip-evidence", "{attempt_root}/inputs/clip-evidence.json", "--gencase-request", "{attempt_root}/inputs/gencase-request.json", "--support-contract", "{attempt_root}/inputs/support-contract.json", "--output", "{attempt_root}/report/clip-geometry.json"],
        "requires": ["official clip semantics", "all-shape Fluid/Bound assignment", "continuous-owner volume", "preserve mass gate"],
        "resources": {"cpu_threads": 1, "memory_bytes": 4294967296, "wall_seconds": 900, "storage": "parent-reserved generated products"},
    },
    "EXPLICIT_CONTINUOUS_OWNER_AND_RIGID_STATE_AUDIT": {
        "worker": "stage2_f6_owner_rigid_metadata_audit_v1.py",
        "stage": "continuous_owner_and_rigid_state_audit",
        "argv": ["--source-audit", "{attempt_root}/inputs/source-audit.json", "--graph", "{attempt_root}/inputs/owner-graph.json", "--output", "{attempt_root}/report/owner-rigid.json"],
        "requires": ["sentinel-specific owner geometry", "rigid COM/inertia", "fluid/floater role separation", "exact motion"],
        "resources": {"cpu_threads": 1, "memory_bytes": 2147483648, "wall_seconds": 600, "storage": "small metadata report"},
    },
    "F6_S2_OWNER_AND_RIGID_INITIAL_QA": {
        "worker": "stage2_f6_initial_native_support_audit_v5.py",
        "stage": "f6_s2_owner_rigid_initial_support",
        "argv": ["--manifest", "{attempt_root}/support-manifest.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/report/f6-s2-support.json"],
        "requires": ["S2 source/control proof", "independent owner/rigid mapping", "native roles and finite fields"],
        "resources": {"cpu_threads": 1, "memory_bytes": 4294967296, "wall_seconds": 900, "storage": "parent-reserved frame-0 products"},
    },
    "CPU_INITIAL_SUPPORT_QA_THEN_SINGLE_SOURCE_MATCHED_CANARY": {
        "worker": "stage2_four_sentinel_frame0_support_audit_v4.py",
        "stage": "source_matched_initial_support_then_canary",
        "argv": ["--run", "--manifest", "{attempt_root}/support-manifest.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/report/initial-support.json"],
        "requires": ["source motion/control closure", "Fluid/Bound support", "native role/header evidence", "one source-matched canary"],
        "resources": {"cpu_threads": 1, "memory_bytes": 4294967296, "wall_seconds": 900, "storage": "parent-reserved support products"},
    },
    "KEEP_LOCAL_OUTPUT_CALIBRATION_SCOPE_OR_SNAPSHOT_MISSING_HALF_NEIGHBORS": {
        "worker": "stage2_f7_s2_output_calibration_v3.py",
        "stage": "local_output_calibration_and_missing_neighbor_scope",
        "argv": ["--run", "--same-join", "{attempt_root}/inputs/same-join.json", "--half-observer", "{attempt_root}/inputs/half-observer.json", "--same-runparts", "{attempt_root}/inputs/same-RunPARTs.csv", "--half-runparts", "{attempt_root}/inputs/half-RunPARTs.csv", "--contract", "{attempt_root}/inputs/output-contract.json", "--output", "{attempt_root}/report/output-calibration.json"],
        "requires": ["actual saved-time rows", "missing-neighbor scope", "output/integration separation"],
        "resources": {"cpu_threads": 1, "memory_bytes": 2147483648, "wall_seconds": 600, "storage": "small observer/report sidecars"},
    },
}


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ChainFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise ChainFailure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ChainFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChainFailure(f"{label} is not bounded JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ChainFailure(f"{label} is not a JSON object: {path}")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
                   "stat_before": before, "stat_after": after, "scope": "bounded_small_json"}


def _file_record(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ChainFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise ChainFailure(f"{label} exceeds 10 MiB source cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ChainFailure(f"{label} changed during bounded source read: {path}")
    return {"path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
            "stat_before": before, "stat_after": after, "scope": "bounded_source_file"}


def _worker_record(filename: str) -> dict[str, Any]:
    local = REFERENCE / filename
    record = _file_record(local, f"worker source {filename}")
    record["relative_reference_path"] = f"lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/{filename}"
    record["primary_path_after_cherry_pick"] = str(PRIMARY_REFERENCE / filename)
    return record


def _evidence_record(item: dict[str, Any]) -> dict[str, Any]:
    # The v2 readiness builder already performed the stable bounded read and
    # SHA check.  Reuse that record; this builder does not reopen proof files.
    return {"path": item.get("path"), "sha256": item.get("actual_sha256"),
            "bytes": item.get("actual_bytes"), "stat": item.get("stat"),
            "claim_scope": item.get("claim_scope"), "proof_status": item.get("proof_status"),
            "scope": "reused_from_actual_readiness_v2", "payload_read_by_this_builder": False}


def _dimension_scope(v7_row: dict[str, Any]) -> dict[str, Any]:
    raw = v7_row.get("dimension_readiness")
    if not isinstance(raw, dict):
        return {"status": "UNKNOWN", "reason": "dimension readiness is absent"}
    aliases = {
        "owner_controller": ("control_initial", "initial_support"),
        "spatial_three_grid": ("spatial_three_grid",),
        "integration_time_step": ("time_step",),
        "output_sampling": ("output_sampling",),
        "integral_vs_output": ("integral_vs_output_separated",),
        "native_fields": ("native_fields",),
        "external_anchor": ("external_anchor",),
    }
    result: dict[str, Any] = {}
    for name, keys in aliases.items():
        values = [raw.get(key, {}) for key in keys]
        result[name] = {
            "statuses": [value.get("status", "UNKNOWN") for value in values if isinstance(value, dict)],
            "evidence_ids": [eid for value in values if isinstance(value, dict)
                             for eid in value.get("evidence_ids", []) if isinstance(eid, str)],
            "scope_notes": [note for value in values if isinstance(value, dict)
                             for note in value.get("scope_notes", []) if isinstance(note, str)],
            "scientific_qualification": dict(UNKNOWN),
        }
    return result


def _classification(row: dict[str, Any], graph_row: dict[str, Any]) -> dict[str, Any]:
    terminal = row.get("terminal_state") if isinstance(row.get("terminal_state"), dict) else {}
    text = " ".join(str(value) for value in (
        terminal.get("status"), terminal.get("hard_fail_or_blocker"), row.get("unknown_impact")))
    lower = text.lower()
    if "hardfail" in lower or "hard fail" in lower:
        state = "SCOPED_DIAGNOSTIC_HARDFAIL"
    elif "source_control_only" in lower or "no_primary_run" in lower or "unknown" in lower:
        state = "ACTUAL_EVIDENCE_GAP_OR_UNKNOWN"
    else:
        state = "ACTUAL_DIAGNOSTIC_NOT_SCIENTIFIC_REFERENCE"
    return {
        "state": state,
        "reason": terminal.get("hard_fail_or_blocker", []),
        "impact": row.get("unknown_impact"),
        "next_action": graph_row.get("next_action"),
        "next_request_kind": graph_row.get("next_request_kind"),
        "scientific_qualification": dict(UNKNOWN),
    }


def _command(worker: dict[str, Any], sid: str, physical_case_id: str) -> list[str]:
    primary_worker = str(PRIMARY_REFERENCE / worker["worker"])
    args = []
    for value in worker["argv"]:
        value = str(value).replace("{physical_case_id}", physical_case_id)
        args.append(value)
    return [str(PYTHON), primary_worker, *args]


def build(output: Path | None = None) -> dict[str, Any]:
    readiness, readiness_record = _small_json(READINESS, "actual readiness v2")
    readiness_v7, readiness_v7_record = _small_json(READINESS_V7, "actual readiness v7")
    graph, graph_record = _small_json(GRAPH, "fourteen request graph v5")
    rows = readiness.get("sentinels")
    graph_rows = graph.get("sentinels")
    v7_rows = readiness_v7.get("sentinels")
    if not isinstance(rows, list) or len(rows) != 14 or not isinstance(graph_rows, list) or len(graph_rows) != 14 or not isinstance(v7_rows, list) or len(v7_rows) != 14:
        raise ChainFailure("all inputs must contain exactly fourteen sentinel rows")
    graph_by_id = {str(row.get("sentinel_id")): row for row in graph_rows}
    v7_by_id = {str(row.get("sentinel_id")): row for row in v7_rows}
    parent_rows: list[dict[str, Any]] = []
    for row in rows:
        sid = str(row.get("sentinel_id")); graph_row = graph_by_id.get(sid); v7_row = v7_by_id.get(sid)
        if graph_row is None or v7_row is None:
            raise ChainFailure(f"missing graph/readiness row for {sid}")
        kind = str(graph_row.get("next_request_kind"))
        if kind not in WORKER_SPECS:
            raise ChainFailure(f"no executable worker contract for {sid}: {kind}")
        worker = WORKER_SPECS[kind]
        worker_record = _worker_record(worker["worker"])
        evidence = [_evidence_record(item) for item in row.get("evidence", [])
                    if isinstance(item, dict) and item.get("status") == "SOURCE_BOUND_ACTUAL_SMALL_PROOF"]
        terminal = row.get("terminal_state") if isinstance(row.get("terminal_state"), dict) else {}
        physical_case_id = str(row.get("physical_case_id") or graph_row.get("physical_case_id") or "PARENT_MUST_BIND_PHYSICAL_CASE")
        request = {
            "schema": "ds02.request.v1",
            "variant_schema": f"{SCHEMA}.request",
            "status": "SOURCE_PREPARED_WAITING_PARENT_ADMISSION",
            "family_id": row.get("family_id") or graph_row.get("family_id"),
            "sentinel_id": sid,
            "physical_case_id": physical_case_id,
            "case_id": f"{sid.replace('-', '_')}_ACTUAL_PARENT_CHAIN_V1",
            "attempt_id": "PARENT_ASSIGNED_AFTER_RESERVATION",
            "cpu_task_kind": "audit",
            "cpu_threads": int(worker["resources"]["cpu_threads"]),
            "execution_allowed": False,
            "launch_disabled": True,
            "source_only": True,
            "command": _command(worker, sid, physical_case_id),
            "command_contract": {
                "worker_source": worker_record,
                "argv0_literal_venv": str(PYTHON),
                "placeholders": ["{attempt_root}", "{frames}", "{query_times}", "{expected_frame_count}", "{expected_final_time_s}"],
                "primary_path_must_be_rebound_after_cherry_pick": True,
            },
            "manifest_path": "{attempt_root}/manifest.json",
            "input_records": {item["path"]: item for item in evidence},
            "deferred_input_records": [{
                "name": "sentinel_products_or_native_frames",
                "scope": "parent_after_reservation",
                "path": "{attempt_root}/inputs",
                "reason": "worker-specific generated/native inputs are not read or hashed during source preparation",
            }],
            "materialization_requirements": {
                "exact_terminal_producer_request_receipt_proof_join": True,
                "sentinel_specific_owner_controller_identity": True,
                "native_mass_header_not_xml_fallback": True,
                "saved_time_from_actual_runparts": True,
                "integral_and_output_sampling_separate": True,
                "neighbor_grid_truth": False,
                "interpolation": False,
            },
            "resource_plan": worker["resources"],
            "scientific_qualification": dict(UNKNOWN),
            "scientific_credit": 0,
            "solver_launch": False,
            "gencase_launch": False,
            "production_payload_read_by_builder": False,
        }
        parent_rows.append({
            "sentinel_id": sid,
            "family_id": request["family_id"],
            "physical_case_id": physical_case_id,
            "actual_terminal_scope": terminal,
            "actual_scope_updates": row.get("actual_scope_updates", []),
            "reusable_evidence": evidence,
            "owner_controller_spatial_integration_output": _dimension_scope(v7_row),
            "decision": _classification(row, graph_row),
            "next_parent": {
                "request": request,
                "worker_stage": worker["stage"],
                "worker_requires": worker["requires"],
                "source_prerequisite": graph_row.get("next_action"),
                "minimum_new_evidence": row.get("minimum_new_evidence"),
                "recovery_if_gate_fails": row.get("recovery_if_gate_fails"),
            },
            "frozen_error_budget": readiness.get("frozen_policy"),
            "scientific_qualification": dict(UNKNOWN),
            "production_credit": 0,
        })
    result = {
        "schema": SCHEMA,
        "status": "SOURCE_BOUND_14_PARENT_CHAIN_NO_SCIENTIFIC_REFERENCE_CREDIT",
        "scientific_credit": 0,
        "scientific_qualification": dict(UNKNOWN),
        "sentinel_count": 14,
        "sentinels": parent_rows,
        "source_inputs": {"readiness_v2": readiness_record, "readiness_v7": readiness_v7_record, "request_graph_v5": graph_record,
                          "worker_source_paths_are_rebound_at_parent": True},
        "policy": {
            "all_requests_execution_allowed": False,
            "all_requests_launch_disabled": True,
            "all_QI_QN_QE": "UNKNOWN",
            "mass_rescale": False,
            "neighbor_grid_truth": False,
            "interpolation": False,
            "root345": "F2-S2/F3-S1/F5-S1 remain blocked until the exact ROOT345 terminal edge and native initial-support handoff are independently admitted; source package status is not a run result.",
        },
        "read_scope": {"metadata_cap_bytes": CAP, "native_vtk_bi4_h5_read": False, "large_report_read": False,
                       "solver_gencase_gpu_launch": False, "shared_ledger_mutation": False},
    }
    if output is not None:
        output = output.expanduser().absolute()
        if output.exists() or output.is_symlink():
            raise ChainFailure(f"refusing overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _self_test() -> None:
    result = build()
    assert result["sentinel_count"] == 14
    assert len(result["sentinels"]) == 14
    assert all(row["scientific_qualification"] == UNKNOWN for row in result["sentinels"])
    assert all(row["next_parent"]["request"]["execution_allowed"] is False for row in result["sentinels"])
    assert all(row["next_parent"]["request"]["launch_disabled"] is True for row in result["sentinels"])
    f1s2 = next(row for row in result["sentinels"] if row["sentinel_id"] == "F1-S2")
    assert f1s2["actual_scope_updates"]
    f2s1 = next(row for row in result["sentinels"] if row["sentinel_id"] == "F2-S1")
    assert f2s1["decision"]["state"] == "SCOPED_DIAGNOSTIC_HARDFAIL"
    print("PASS_FOURTEEN_ACTUAL_PARENT_CHAIN_SOURCE_BOUND_NO_SCIENTIFIC_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        result = build(args.output)
        print(json.dumps({"status": result["status"], "output": str(args.output.absolute()) if args.output else None,
                          "sentinel_count": result["sentinel_count"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (ChainFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_ACTUAL_PARENT_CHAIN_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
