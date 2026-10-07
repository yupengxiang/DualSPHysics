#!/usr/bin/env python3
"""Assemble a concise, source-bound status for all fourteen sentinels.

This read-only report joins the exact CURRENT-bound study graph, the 13
launch-disabled original same/half-CFL request records, and the completed
GenCase mass audits.  It does not read HDF5 or native frame payloads, start a
solver, or turn a GenCase/mass result into Q-I/Q-N/Q-E credit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.fourteen-reference-status.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
GRAPH_PATH = REFERENCE / "stage2_minimal14_study_graph_v2.json"
PAIR_PATH = REFERENCE / "stage2_original_cfl_pair_cost_manifest_v2.json"
QUALITY_PATH = REFERENCE / "stage2_reference_quality_cost_v2.json"
MASS_PATHS = (
    REFERENCE / "stage2_mass_fit_probe_results_v1.json",
    REFERENCE / "stage2_mass_fit_probe_results_v2.json",
    REFERENCE / "stage2_mass_fit_probe_results_v3.json",
    REFERENCE / "stage2_f2_mass_fit_results_v4.json",
)
F2_FULL_REQUEST = REQUEST_ROOT / "stage2-full-window-canary-v1/f2_s1_fine_dp000855_same_cfl_dense.json"
F2_FULL_RECEIPT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/") / (
    "F2_S1_FULL_CFD_CANARY_DP01258_T4/f2_s1_full_cfd_canary_dp01258_t4_tout010-root-001/execution-receipt.json"
)
F4_OBSERVER_REQUEST = REQUEST_ROOT / "stage2-f4-stream-observer-v1/f4_s1_canary_stream_observer_v1.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(path)}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def compact_gate(value: dict[str, Any]) -> dict[str, Any]:
    mass = value.get("mass_gate") or value.get("whole_initial_mass") or {}
    error = mass.get("deviation_pct_vs_source", mass.get("error_pct_vs_source_target"))
    if error is None:
        error = mass.get("error_pct_vs_source_target")
    per = value.get("per_fluid_source_mass_comparison")
    if per is None:
        per = value.get("per_mk_diagnostics")
    if isinstance(per, list):
        per_status = [row.get("gate", row.get("diagnostic_3pct")) for row in per]
    elif isinstance(per, dict):
        per_status = per.get("status", "UNKNOWN")
    else:
        per_status = "UNKNOWN"
    semantics = value.get("generated_semantics") or {}
    dp_values = semantics.get("dp_values", [])
    if not dp_values:
        dp = value.get("candidate_dp_m")
    else:
        dp = dp_values[0]
    geometry = value.get("input_integrity") or value.get("continuous_vs_intentional") or {}
    receipt = value.get("receipt", {})
    request = value.get("request", {})
    return {
        "audit_version": value.get("schema", "UNKNOWN"),
        "case_id": value.get("case_id"),
        "label": value.get("label"),
        "candidate_dp_m": dp,
        "whole_initial_mass_error_pct": error,
        "whole_initial_mass_gate": mass.get("gate"),
        "per_source_mass_status": per_status,
        "generated_xml": value.get("generated_xml", {}).get("path"),
        "request": request.get("path"),
        "receipt": receipt.get("path"),
        "receipt_status": receipt.get("status"),
        "solver_started": value.get("solver_started", False),
        "full_time_hdf5_read": value.get("full_time_hdf5_read", False),
        "geometry_control_evidence": geometry,
        "scientific_qualification": {
            "QI": value.get("QI", value.get("scientific_qualification", {}).get("QI", "UNKNOWN")),
            "QN": value.get("QN", value.get("scientific_qualification", {}).get("QN", "UNKNOWN")),
            "QE": value.get("QE", value.get("scientific_qualification", {}).get("QE", "UNKNOWN")),
        },
    }


def mass_evidence() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for path in MASS_PATHS:
        report = load(path)
        version = report.get("schema", path.name)
        for item in report.get("results", []):
            row = compact_gate(item)
            row["report"] = {"path": str(path.resolve()), "sha256": sha256_file(path), "schema": version}
            result.setdefault(item["sentinel_id"], []).append(row)
    return result


def compact_spatial(row: dict[str, Any]) -> dict[str, Any]:
    xml = row.get("generated_xml") or {}
    xml_path = xml.get("path")
    if isinstance(xml, dict):
        xml_path = xml.get("path") or xml.get("file", {}).get("path")
    return {
        "grid": row.get("grid", row.get("label")),
        "label": row.get("label"),
        "requested_dp_m": row.get("requested_dp_m"),
        "candidate_particles": row.get("candidate_particles"),
        "candidate_fluid_particles": row.get("candidate_fluid_particles"),
        "candidate_sample_mass_kg": row.get("candidate_sample_mass_kg"),
        "whole_initial_mass_error_pct": row.get("whole_initial_mass_error_pct"),
        "whole_initial_mass_gate": row.get("whole_initial_mass_gate"),
        "planning_status": row.get("planning_status"),
        "continuous_geometry_control_status": row.get("continuous_geometry_control_status"),
        "generated_xml": xml_path,
        "receipt": (row.get("receipt") or {}).get("output_root") or (row.get("receipt") or {}).get("path"),
        "solver_started": row.get("solver_started", False),
        "scientific_qualification": row.get("scientific_qualification", "UNKNOWN"),
    }


def request_status(pair_rows: list[dict[str, Any]], sentinel_id: str) -> dict[str, Any]:
    rows = [row for row in pair_rows if row.get("sentinel_id") == sentinel_id]
    result: dict[str, Any] = {}
    for mode in ("original_same_cfl_dense", "original_half_cfl_dense"):
        match = [row for row in rows if row.get("mode") == mode]
        if len(match) == 1:
            row = match[0]
            path = Path(row["request_path"])
            req = load(path)
            result[mode] = {
                "status": "PREPARED_LAUNCH_DISABLED" if req.get("launch_disabled") else "REVIEW",
                "request": file_record(path),
                "full_window_s": req.get("physical_window_s"),
                "cadence_s": req.get("save_interval_s"),
                "cfl_mode": req.get("scope", {}).get("cfl_mode", mode),
                "estimated_storage_bytes": req.get("estimated_storage_bytes"),
                "solver_started": False,
                "gpu_started": False,
            }
        else:
            result[mode] = {"status": "NOT_BOUND_IN_13_SENTINEL_BATCH", "matches": len(match)}
    return result


def build() -> dict[str, Any]:
    graph = load(GRAPH_PATH)
    pair = load(PAIR_PATH)
    quality = load(QUALITY_PATH)
    evidence = mass_evidence()
    pair_rows = pair.get("requests", [])
    sentinels: list[dict[str, Any]] = []
    for source in graph["sentinels"]:
        sid = source["sentinel_id"]
        source_xml = source.get("current_binding", {}).get("generated_xml", {})
        source_receipt = source.get("current_binding", {}).get("solver_receipt", {})
        original_nodes = []
        for node in source.get("study_nodes", []):
            if node.get("grid") == "original" and node.get("cfl_mode") in {"same_cfl", "half_cfl"}:
                original_nodes.append({
                    "node_id": node.get("node_id"),
                    "mode": node.get("cfl_mode"),
                    "cadence_s": node.get("cadence_s"),
                    "full_window_s": node.get("full_physical_window_s"),
                    "planned_frames": node.get("cost", {}).get("planned_frames"),
                    "raw_native_reserved_bytes": node.get("cost", {}).get("raw_native_reserved_bytes"),
                    "status": node.get("status"),
                    "dt_sequence_and_clamp": node.get("cost", {}).get("dt_sequence_and_clamp"),
                    "observer_status": node.get("cost", {}).get("observer_status"),
                })
        row: dict[str, Any] = {
            "sentinel_id": sid,
            "family_id": source.get("family_id"),
            "physical_case_id": source.get("physical_case_id"),
            "current_identity_status": source.get("current_row_identity_status"),
            "source": {
                "xml": source_xml,
                "solver_receipt": source_receipt,
                "dp_m": source.get("source_dp_m"),
                "cfl": source.get("source_cfl"),
                "half_cfl": source.get("half_cfl"),
                "fluid_particles": source.get("source_fluid_particles"),
                "particles": source.get("source_particles"),
                "sample_mass_kg": source.get("source_sample_mass_kg"),
                "full_window_s": source.get("effective_time_window_s"),
                "dense_output_cadence_s": source.get("dense_output_cadence_s"),
                "source_part0_bytes": source.get("part_stats", {}).get("frame0_bytes"),
            },
            "spatial_candidates_from_exact_graph": [compact_spatial(x) for x in source.get("spatial_ladder", [])],
            "completed_mass_audits": evidence.get(sid, []),
            "time_output": {
                "cross_family_query_window_s": source.get("physical_query_scope", {}).get("cross_family_intersection_s"),
                "full_sentinel_window_retained": source.get("physical_query_scope", {}).get("full_sentinel_window_retained"),
                "late_event_tasks_retained": source.get("physical_query_scope", {}).get("query_policy"),
                "original_same_half_cfl_dense": original_nodes,
                "request_bindings": request_status(pair_rows, sid),
            },
            "observer_calibration": {
                "status": source.get("observer_calibration_status", "UNKNOWN"),
                "field_observables": "UNKNOWN until consumer-calibrated decoder/observer",
                "f2_structural_query_note": "F2 typed common-query output, where applicable, is structural bracket evidence only; it is not a physical macro/qualified comparison",
            },
            "effective_dt_and_clamp": {
                "source_status": source.get("dt_trace_status"),
                "RunPARTs_is_not_full_step_trace": True,
                "SaveDt_overlay": "PREPARED_OFFICIAL_XML_PATH; no current source run retroactively gains per-step evidence",
            },
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }
        sentinels.append(row)

    # Add explicit non-original special work without conflating it with the
    # 13 original dp0 time-pair requests.
    specials = {
        "F2-S1": {
            "full_window_candidate_request": file_record(F2_FULL_REQUEST),
            "actual_solver_receipt": file_record(F2_FULL_RECEIPT) if F2_FULL_RECEIPT.is_file() else "UNKNOWN",
            "meaning": "separate mass-compatible candidate full-window canary; not the original dp0 same/half-CFL pair",
            "actual_field_observer": "UNKNOWN until consumer calibration",
        },
        "F4-S1": {
            "stream_observer_request": file_record(F4_OBSERVER_REQUEST),
            "meaning": "same actual native window observer request; 2401 saved frames end at 1.200061449336894, nominal 1.200084396929538 endpoint outside",
            "actual_field_observer": "UNKNOWN; worker is byte/time provenance only",
        },
    }
    for row in sentinels:
        if row["sentinel_id"] in specials:
            row["special_prepared_or_actual"] = specials[row["sentinel_id"]]
    source_inputs = [GRAPH_PATH, PAIR_PATH, QUALITY_PATH, *MASS_PATHS]
    return {
        "schema": SCHEMA,
        "status": "PREPARED_DIAGNOSTIC_ONLY_14_SENTINEL_STATUS",
        "current_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                                        capture_output=True, text=True).stdout.strip(),
        "scope": {
            "sentinel_count": len(sentinels),
            "reads_hdf5": False,
            "reads_native_payloads": False,
            "starts_solver": False,
            "starts_gpu": False,
            "spatial_gate_policy": "whole initial source sample mass <=1% target; 1-2% marginal diagnostic; >2% hard failure; per-material diagnostics remain separate and do not override whole-mass task budget",
            "geometry_policy": "dp/h/mass/count are intentional resolution fields; continuous fill/geometry/motion and source identity must be independently bound",
            "qualification_policy": "GenCase, mass, structural query, and request validation do not grant QI/QN/QE",
        },
        "source_inputs": [{"path": str(path.resolve()), "sha256": sha256_file(path)} for path in source_inputs],
        "quality_error_budget": quality.get("error_budget_registration"),
        "sentinels": sentinels,
        "global_unknowns": [
            "No sentinel receives field-observer calibration or scientific qualification from this report.",
            "No current source run has a complete per-final-step dt sequence; RunPARTs and Run.out are summary evidence.",
            "Full-window native/typed/archive costs are planning estimates until parent guards actual runs; two-frame compression ratios are not full-time bounds.",
            "F2 coarse fixed-geometry lattice phase match remains unproven after bounded probes; no geometry or mass rescaling is authorized.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build()
    if args.output.exists():
        raise FileExistsError(f"refuse to overwrite {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "sentinels": len(result["sentinels"]),
                      "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
