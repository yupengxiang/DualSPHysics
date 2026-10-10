#!/usr/bin/env python3
"""Materialize an exact, source-bound next-action graph for fourteen sentinels.

The older readiness/status cards are useful indexes but are not scientific
results.  This additive reader joins each indexed evidence row to the actual
small proof file and its recorded SHA, then emits an actionable parent gate
for the next study.  It never infers qualification from a status word,
neighboring-grid behavior, an asynchronous bracket, or a source label.

Only JSON and small proof files are read (10 MiB cap).  No native/VTK/H5/BI4
payload is opened and no parent, solver, GenCase, GPU lease, or ledger is
started.  Every output retains QI/QN/QE=UNKNOWN and production_credit=0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
GRAPH = HERE / "stage2_fourteen_request_graph_v5.json"
INVENTORY = HERE / "stage2_fourteen_evidence_dimension_inventory_v2.json"
READINESS = HERE / "stage2_fourteen_actual_evidence_readiness_v8_addendum.json"
SCHEMA = "ds02.stage2.fourteen-science-execution-closure.v1"
CAP = 10 * 1024 * 1024
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

GATE_BY_KIND: dict[str, dict[str, Any]] = {
    "JSON_ONLY_EXISTING_OBSERVER_COMPARISON": {
        "parent_kind": "bounded_metadata_comparison",
        "requires": ["exact producer/request/receipt/proof joins", "common actual saved-time/bracket metadata", "no interpolation"],
        "resource_plan": "1 CPU, <=1 GiB, <=300 s, metadata/report sidecars only",
    },
    "SELECTED_NATIVE_OBSERVER_AND_RUNPART_BRACKET_AUDIT": {
        "parent_kind": "guarded_selected_native_observer",
        "requires": ["terminal source receipt", "RunPARTs-derived frame IDs", "native MassFluid/MassBound and role fields", "pre/post SHA/stat"],
        "resource_plan": "parent chooses source bytes and decoder budget after terminal receipt; no neighbor truth",
    },
    "SOURCE_OWNER_SUPPORT_AND_PER_MATERIAL_AUDIT": {
        "parent_kind": "source_owner_support_gate",
        "requires": ["sentinel-specific continuous-owner geometry proof", "Fluid/Bound support and overlap", "native roles", "no mass rescale"],
        "resource_plan": "bounded CPU initial-support audit before any solver",
    },
    "CPU_GENCASE_INITIAL_SUPPORT_QA": {
        "parent_kind": "gencase_only_initial_support",
        "requires": ["actual source Def/XML/control closure", "terminal GenCase receipt", "native MassFluid/MassBound/Dp", "Fluid/Bound/Idp role checks"],
        "resource_plan": "1 CPU, <=4 GiB, GenCase/support only; parent must reserve output",
    },
    "BOUNDED_SELECTED_NATIVE_OBSERVER_AUDIT": {
        "parent_kind": "bounded_native_observer",
        "requires": ["continuous owner/support gate", "terminal solver receipt", "selected native frame SHA/stat", "time source from RunPARTs"],
        "resource_plan": "serial observer after source/solver terminal; no payload read during preparation",
    },
    "ROOT240_COMPACT_SPATIAL_LIFECYCLE_COMPARISON": {
        "parent_kind": "guarded_compact_report_comparison",
        "requires": ["coarse/middle/fine producer proof joins", "compact summary stable SHA/stat", "lost/reappear/new identity semantics", "no interpolation"],
        "resource_plan": "metadata worker reads deferred reports under parent reservation; no Q credit by itself",
    },
    "BOUNDED_COMMON_TIME_OBSERVER_COMPARISON": {
        "parent_kind": "common_time_native_observer",
        "requires": ["actual timestamps and bracket endpoints", "same source/control identity", "native fields", "integral and output checks kept separate"],
        "resource_plan": "serial bounded observer; asynchronous rows remain diagnostics",
    },
    "CPU_INITIAL_SUPPORT_QA_THEN_ONE_CANARY": {
        "parent_kind": "initial_support_then_single_canary",
        "requires": ["initial support/control gate", "source-specific owner", "one terminal canary before any grid ladder"],
        "resource_plan": "CPU support first; parent computes one external-v5 canary budget only after support pass",
    },
    "SOURCE_BOUND_GEOMETRY_DIAGNOSTIC": {
        "parent_kind": "source_clip_geometry_diagnostic",
        "requires": ["official clip/draw semantics", "all-shape boundary/overlap evidence", "continuous-owner mass definition", "preserve hard gates"],
        "resource_plan": "bounded geometry/GenCase support only; no solver while mass/support unresolved",
    },
    "EXPLICIT_CONTINUOUS_OWNER_AND_RIGID_STATE_AUDIT": {
        "parent_kind": "continuous_owner_rigid_initial_audit",
        "requires": ["sentinel-specific owner geometry", "rigid COM/inertia and role separation", "fluid/floater gap/velocity", "native source fields"],
        "resource_plan": "metadata plus guarded initial support; no inherited owner target",
    },
    "F6_S2_OWNER_AND_RIGID_INITIAL_QA": {
        "parent_kind": "continuous_owner_rigid_initial_audit",
        "requires": ["S2 source/control proof", "independent owner/rigid mapping", "native roles and finite fields"],
        "resource_plan": "bounded initial QA; S1 owner cannot be copied",
    },
    "CPU_INITIAL_SUPPORT_QA_THEN_SINGLE_SOURCE_MATCHED_CANARY": {
        "parent_kind": "initial_support_then_single_canary",
        "requires": ["source motion/control closure", "Fluid/Bound support", "native role/header evidence", "one matched canary"],
        "resource_plan": "CPU support first; external-v5 resources remain parent-only",
    },
    "KEEP_LOCAL_OUTPUT_CALIBRATION_SCOPE_OR_SNAPSHOT_MISSING_HALF_NEIGHBORS": {
        "parent_kind": "bounded_output_calibration",
        "requires": ["actual saved-time rows", "missing-neighbor scope explicitly retained", "output/integration dimensions separate"],
        "resource_plan": "metadata/report sidecar only unless a uniquely missing native snapshot is approved",
    },
}


class ClosureFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _small(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path).expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ClosureFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise ClosureFailure(f"{label} exceeds 10 MiB cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise ClosureFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClosureFailure(f"{label} is not bounded JSON") from exc
    if not isinstance(value, dict):
        raise ClosureFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                   "stat_before": before, "stat_after": after, "read_scope": "bounded_small_proof"}


def _source_bound(source: Any) -> tuple[dict[str, Any], str | None]:
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        return {"status": "UNBOUND", "reason": "evidence row has no source path"}, None
    try:
        value, record = _small(Path(source["path"]), "evidence source")
    except ClosureFailure as exc:
        return {"status": "UNBOUND", "reason": str(exc), "path": source.get("path")}, None
    expected = source.get("sha256")
    if not isinstance(expected, str) or expected.lower() != record["sha256"].lower():
        return {"status": "HASH_MISMATCH", "path": record["path"], "actual_sha256": record["sha256"],
                "expected_sha256": expected}, record["sha256"]
    return {"status": "SOURCE_BOUND_DIAGNOSTIC", "record": record,
            "source_status": source.get("status"), "payload_claim": source.get("read_mode")}, record["sha256"]


def _load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    graph, graph_rec = _small(GRAPH, "fourteen request graph")
    inventory, inventory_rec = _small(INVENTORY, "fourteen evidence inventory")
    readiness, readiness_rec = _small(READINESS, "fourteen readiness addendum")
    if len(graph.get("sentinels", [])) != 14 or len(inventory.get("sentinels", [])) != 14:
        raise ClosureFailure("inputs do not contain exactly fourteen sentinels")
    return graph, inventory, readiness, {"graph": graph_rec, "inventory": inventory_rec, "readiness": readiness_rec}


def build(output: Path | None = None) -> dict[str, Any]:
    graph, inventory, readiness, source_records = _load_inputs()
    graph_rows = {str(row["sentinel_id"]): row for row in graph["sentinels"]}
    inventory_rows = {str(row["sentinel_id"]): row for row in inventory["sentinels"]}
    updated = readiness.get("updated_sentinels", {})
    sentinels: list[dict[str, Any]] = []
    for sid in sorted(graph_rows):
        graph_row = graph_rows[sid]
        inv_row = inventory_rows.get(sid, {})
        dimensions: dict[str, Any] = {}
        bound = 0
        unbound = 0
        for dimension, raw in (inv_row.get("dimensions") or {}).items():
            evidence = raw.get("evidence", []) if isinstance(raw, dict) else []
            refs = []
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                joined, actual_sha = _source_bound(item.get("source"))
                refs.append({"evidence_id": item.get("evidence_id"), "actual_flag": item.get("actual"),
                             "observed_flag": item.get("observed"), "source": joined})
                if joined.get("status") == "SOURCE_BOUND_DIAGNOSTIC" and item.get("actual") is True and item.get("observed") is True:
                    bound += 1
                else:
                    unbound += 1
            dimensions[dimension] = {
                "catalog_status": raw.get("status") if isinstance(raw, dict) else "UNAVAILABLE",
                "evidence_count": len(refs), "source_bound_diagnostic_count": sum(r["source"].get("status") == "SOURCE_BOUND_DIAGNOSTIC" for r in refs),
                "evidence": refs,
                "dimension_observation": "ACTUAL_DIAGNOSTIC_ONLY" if any(r["source"].get("status") == "SOURCE_BOUND_DIAGNOSTIC" and r["actual_flag"] is True and r["observed_flag"] is True for r in refs) else "UNKNOWN",
                "scientific_qualification": dict(UNKNOWN),
            }
        kind = str(graph_row.get("next_request_kind"))
        gate = GATE_BY_KIND.get(kind, {"parent_kind": "parent_review_required", "requires": ["sentinel-specific source/receipt/proof joins"], "resource_plan": "parent must bound resources"})
        addendum = updated.get(sid, {}) if isinstance(updated, dict) else {}
        sentinels.append({
            "sentinel_id": sid, "family_id": graph_row.get("family_id"), "physical_case_id": graph_row.get("physical_case_id"),
            "current_state": graph_row.get("current_state"), "next_request_kind": kind,
            "next_action": graph_row.get("next_action"), "admitted_source_update": addendum.get("status"),
            "dimensions": dimensions, "source_bound_diagnostic_evidence_count": bound,
            "unbound_or_nonactual_evidence_count": unbound,
            "next_gate": gate, "parent_only": True, "launch_by_builder": False,
            "scientific_qualification": dict(UNKNOWN), "production_credit": 0,
        })
    result = {
        "schema": SCHEMA, "status": "SOURCE_BOUND_EXECUTION_CLOSURE_NO_SCIENTIFIC_CREDIT",
        "scientific_credit": 0, "scientific_qualification": dict(UNKNOWN),
        "sentinel_count": len(sentinels), "sentinels": sentinels,
        "source_inputs": source_records,
        "read_scope": {"bounded_json_and_small_proofs": True, "metadata_cap_bytes": CAP,
                       "production_native_payload": False, "production_vtk_h5_bi4": False,
                       "solver_gencase_gpu_launch": False, "neighbor_grid_truth": False,
                       "interpolation": False},
        "admission_policy": {
            "ROOT345_product_map": "requires raw producer request SHA, terminal execution receipt, exact case/attempt/output root, stat+terminal product SHA records",
            "initial_support": "must bind native MassFluid/MassBound/Dp and typed roles; XML mass is never a substitute",
            "continuous_owner": "must be sentinel-specific geometry/control evidence; cross-sentinel target labels are UNVERIFIED",
            "native_header_adapter": "custom bi4_dump build/source closure is a hard parent gate; manufactured ABI proof grants zero production credit",
            "qualification": "QI/QN/QE remain UNKNOWN until an actual preregistered study completes",
        },
    }
    if output is not None:
        output = Path(output).expanduser().absolute()
        if output.exists() or output.is_symlink():
            raise ClosureFailure(f"refusing overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def _self_test() -> None:
    result = build()
    assert result["sentinel_count"] == 14
    assert result["scientific_credit"] == 0
    assert all(row["scientific_qualification"] == UNKNOWN for row in result["sentinels"])
    assert all(row["parent_only"] and not row["launch_by_builder"] for row in result["sentinels"])
    assert any(row["next_request_kind"] == "CPU_GENCASE_INITIAL_SUPPORT_QA" for row in result["sentinels"])
    print("PASS_FOURTEEN_EXACT_SOURCE_BOUND_EXECUTION_CLOSURE_NO_SCIENTIFIC_CREDIT")


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
    except (ClosureFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_SCIENCE_EXECUTION_CLOSURE_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
