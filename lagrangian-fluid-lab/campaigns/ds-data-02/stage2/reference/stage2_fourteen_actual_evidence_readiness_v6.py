#!/usr/bin/env python3
"""Build an additive, source-only 14-sentinel evidence readiness snapshot.

This wrapper consumes the checked-in v4 evidence registry, v2 dimension
inventory, and v5 request graph.  It reads only those small metadata files; it
does not open any producer payload, solver output, BI4/VTK/H5 array, or proof
file listed by the registry.  The resulting table keeps exact proof paths,
SHA256 values, and claim scopes while stating the minimum next parent for each
sentinel, a planning resource class, and the impact of each unresolved gate.

The same source contract emits a three-sentinel calibration preregistration
for F2-S2, F3-S1, and F5-S1.  Spatial, integration, output-sampling, and
native-header observations are separate tasks.  Bracketed asynchronous rows,
neighboring grids, XML mass, and saved-time differences never become truth or
QI/QN/QE credit in this file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
JSON_CAP = 10 * 1024 * 1024
STATUS_V4 = HERE / "stage2_fourteen_evidence_status_v4.json"
DIMENSIONS_V2 = HERE / "stage2_fourteen_evidence_dimension_inventory_v2.json"
REQUEST_GRAPH_V5 = HERE / "stage2_fourteen_request_graph_v5.json"
REGISTRY_CORRECTION = HERE / "stage2_fourteen_registry_scope_correction_v1.json"
READINESS_SCHEMA = "ds02.stage2.fourteen-actual-evidence-readiness.v6"
CALIBRATION_SCHEMA = "ds02.stage2.three-sentinel-calibration-preregister.v1"
SENTINELS = tuple(f"F{i}-S{j}" for i in range(1, 8) for j in (1, 2))


class ReadinessFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ReadinessFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ReadinessFailure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise ReadinessFailure(f"{label} changed during read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessFailure(f"{label} is not JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReadinessFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                   "stat": after, "read_scope": "small_metadata_only"}


def _source_record(path: Path, label: str) -> dict[str, Any]:
    _, record = _small_json(path, label)
    return record


def _proof_ref(evidence: dict[str, Any]) -> dict[str, Any]:
    file = evidence.get("file") if isinstance(evidence.get("file"), dict) else {}
    return {
        "name": evidence.get("name"),
        "kind": evidence.get("kind"),
        "claim_scope": evidence.get("claim_scope"),
        "path": file.get("path", evidence.get("path")),
        "bytes": file.get("bytes"),
        "sha256": file.get("sha256"),
        "mtime_ns": file.get("mtime_ns"),
        "source_metadata_only": True,
        "scientific_credit": False,
    }


def _cost_for(kind: str) -> dict[str, Any]:
    """Conservative planning classes; these are not actual receipt costs."""
    if kind == "JSON_ONLY_EXISTING_OBSERVER_COMPARISON":
        return {"cpu_threads": 1, "wall_seconds_upper_bound": 600, "memory_bytes": 2 * 1024**3,
                "gpu": False, "storage": "small JSON/report only; existing native reads are deferred",
                "basis": "planning class, no actual parent receipt"}
    if kind in {"SELECTED_NATIVE_OBSERVER_AND_RUNPART_BRACKET_AUDIT", "BOUNDED_SELECTED_NATIVE_OBSERVER_AUDIT",
                "BOUNDED_COMMON_TIME_OBSERVER_COMPARISON", "KEEP_LOCAL_OUTPUT_CALIBRATION_SCOPE_OR_SNAPSHOT_MISSING_HALF_NEIGHBORS"}:
        return {"cpu_threads": 1, "wall_seconds_upper_bound": 1800, "memory_bytes": 4 * 1024**3,
                "gpu": False, "storage": "selected native frames deferred; parent must reserve from actual stat",
                "basis": "planning class, no actual parent receipt"}
    if kind in {"CPU_GENCASE_INITIAL_SUPPORT_QA", "CPU_INITIAL_SUPPORT_QA_THEN_ONE_CANARY",
                "CPU_INITIAL_SUPPORT_QA_THEN_SINGLE_SOURCE_MATCHED_CANARY"}:
        return {"cpu_threads": 1, "wall_seconds_upper_bound": 900, "memory_bytes": 4 * 1024**3,
                "gpu": False, "storage": "generated XML/Fluid/Bound/BI4 deferred; no numeric forecast accepted",
                "basis": "bounded GenCase-only planning class, no solver"}
    if kind in {"SOURCE_OWNER_SUPPORT_AND_PER_MATERIAL_AUDIT", "SOURCE_BOUND_GEOMETRY_DIAGNOSTIC",
                "EXPLICIT_CONTINUOUS_OWNER_AND_RIGID_STATE_AUDIT", "F6_S2_OWNER_AND_RIGID_INITIAL_QA"}:
        return {"cpu_threads": 1, "wall_seconds_upper_bound": 900, "memory_bytes": 2 * 1024**3,
                "gpu": False, "storage": "small source metadata plus guarded support fields if required",
                "basis": "bounded source/support planning class, no solver"}
    if kind == "BI4_SOURCE_SNAPSHOT_THEN_EXTERNAL_V5_REQUEST":
        return {"cpu_threads": 1, "wall_seconds_upper_bound": 1800, "memory_bytes": 2 * 1024**3,
                "gpu": False, "storage": "one parent-reserved BI4 stream; exact bytes established after reservation",
                "basis": "snapshot-only planning class, no solver"}
    return {"cpu_threads": 1, "wall_seconds_upper_bound": 900, "memory_bytes": 2 * 1024**3,
            "gpu": False, "storage": "source metadata/stat only until a parent binds payload",
            "basis": "default bounded CPU planning class, no actual parent receipt"}


MINIMUMS: dict[str, dict[str, Any]] = {
    "F1-S1": {"next": "Use existing same/half and three-grid selected observers at RunPART-derived exact/bracketed common queries.", "gate": "source XML/receipt/control identity for all selected producers; native MassFluid/Dp and role counts; no asynchronous interpolation", "impact": "spatial differences exceed the registered position tolerance, so cross-grid error/truth is unresolved"},
    "F1-S2": {"next": "Decode only registered frames from existing coarse/middle/fine trees and bind actual RunPART brackets.", "gate": "terminal receipt/request/source joins plus exact saved-time brackets; a separate same-grid CFL/output pair for integration/output claims", "impact": "full-window runs exist, but saved rows do not identify a per-step integration error bound"},
    "F2-S1": {"next": "Keep branch limited; audit existing source products for owner/support/per-MK semantics before new CFD.", "gate": "source-supported continuous owner and per-MK mass/support proof, independent of the old native discrete mass", "impact": "18.876 kg continuous target and 21.114 kg native source are not interchangeable"},
    "F2-S2": {"next": "Run one exact-source GenCase ladder and initial support/mass audit for original/coarse/fine.", "gate": "CURRENT Def/XML/forcing/motion closure; generated Fluid/Bound support, native header MassFluid/MassBound/Dp, role counts and owner mass", "impact": "no primary generated support or source-matched run; F2-S1 owner target cannot be inherited"},
    "F3-S1": {"next": "Use the existing source-bound full-window anchor for a bounded selected native observer.", "gate": "CURRENT source/control/receipt join, native role/region fields, RunPART exact/bracketed queries and explicit no-flux scope", "impact": "labels and cost anchors do not prove continuous no-flux or numerical qualification"},
    "F3-S2": {"next": "Keep existing coarse/middle/fine diagnostics scoped; parent-reserve only the next source-bound observer if needed.", "gate": "support/mass/source BI4 closure, native lifecycle interpretation and exact control/window join", "impact": "native exclusions and asynchronous output differences have unknown physical fate and error meaning"},
    "F4-S1": {"next": "Use existing coarse/same/half/fine observers at actual RunPART times; compare output rows separately.", "gate": "exact common-time/bracket coverage plus independent dt/clamp and output-cadence fields", "impact": "brackets and SaveDt row counts do not identify field or integration error"},
    "F4-S2": {"next": "Guard one exact F4-S2 GenCase support/mass audit before any canary.", "gate": "CURRENT gap/offset/velocity/motion, generated support/overlap and source mass", "impact": "F4-S1 evidence cannot be transferred to S2"},
    "F5-S1": {"next": "Run the source-bound shape/support diagnostic and retain the official continuous-owner mass gate.", "gate": "all-shape Fluid/Bound assignment, clip/overlap semantics, owner volume and control/motion identity", "impact": "official clip candidates remain below the continuous mass target; no solver admission"},
    "F5-S2": {"next": "Prepare one exact F5-S2 GenCase support/mass audit with the 16 s physical window.", "gate": "transformed motion/bed/clip source, continuous owner, generated support/mass and effective control path", "impact": "F5-S1 does not establish S2 initial support or owner equivalence"},
    "F6-S1": {"next": "Bind explicit continuous-fluid owner and rigid COM/inertia in a source audit.", "gate": "F6 owner geometry, rigid body mass/inertia/COM, fluid/floater separation and exact motion", "impact": "256 kg SPH sample, 128 kg rigid body and any inherited owner target are distinct quantities"},
    "F6-S2": {"next": "Repeat the owner/rigid initial audit with S2-specific angular control and geometry.", "gate": "S2 source/body/motion identity and support, independently of S1", "impact": "S1 ambiguity cannot be promoted to an S2 matched reference"},
    "F7-S1": {"next": "Close exact source/motion/support and initial mass, then consider one canary only.", "gate": "CURRENT source/motion, generated support/mass and parent storage estimate", "impact": "F7-S2 runs do not cover S1"},
    "F7-S2": {"next": "Keep same20/half17 as local output diagnostics; request only unique missing neighbor frames if needed.", "gate": "exact missing brackets and lifecycle identity; no neighboring-grid truth or interpolation", "impact": "half-CFL missing neighbors/endpoints remain UNKNOWN and asynchronous differences are not pure integration error"},
}


CALIBRATION_ROWS: dict[str, dict[str, Any]] = {
    "F2-S2": {
        "request_kind": "CPU_GENCASE_INITIAL_SUPPORT_QA",
        "source_contract": "stage2_f2_s2_source_control_ladder_audit_v4.json plus exact CURRENT Def/XML/forcing/motion paths",
        "runtime_request_contract": {
            "source_prepared_kind": "gencase",
            "parent_normalization_required": True,
            "execution_allowed_in_this_artifact": False,
            "cpu_threads": 1,
            "wall_seconds_upper_bound": 900,
            "memory_bytes_upper_bound": 4 * 1024**3,
            "gpu": False,
            "solver_launch": False,
            "input_roles": [
                "CURRENT candidate Def/XML and exact source geometry/control files",
                "official GenCase binary, DsphConfig.xml, and template/source code",
                "forcing and motion auxiliary files, including any >10 MiB deferred source",
            ],
            "output_roles": [
                "generated.xml",
                "generated_Fluid.vtk",
                "generated_Bound.vtk",
                "generated.bi4",
            ],
            "hash_and_stat_policy": "Parent establishes all dynamic output SHA/stat after reservation; staged auxiliary files are copied inside the attempt and checked against the exact source SHA/stat before GenCase. A large forcing file remains deferred until that parent and is never treated as a small metadata read.",
            "argv_cwd_policy": "Parent binds a fresh attempt-contained input directory and the official GenCase stem/threads:1 invocation; relative motion/forcing paths must resolve inside that directory.",
        },
        "parent_sequence": ["GenCase original/coarse/fine", "small XML/control audit", "guarded Fluid/Bound/native-header verifier"],
        "measurements": ["native MassFluid/MassBound/Dp", "Idp role counts", "Fluid/Bound finite and support bounds", "continuous-owner volume/mass separately"],
        "spatial_gate": "all three rungs use the same continuous source geometry/control; dp/count are resolution fields",
        "integration_gate": "not run in this parent; requires a later same-grid CFL pair",
        "output_gate": "not run in this parent; output cadence is not inferred from XML",
        "status_if_missing": "UNKNOWN_OR_SOURCE_BLOCKED",
    },
    "F3-S1": {
        "request_kind": "BOUNDED_SELECTED_NATIVE_OBSERVER_AUDIT",
        "source_contract": "F3-S1 anchor/phase proof records and exact CURRENT source/control/receipt",
        "runtime_request_contract": {
            "source_prepared_kind": "audit",
            "parent_normalization_required": True,
            "execution_allowed_in_this_artifact": False,
            "cpu_threads": 1,
            "wall_seconds_upper_bound": 1800,
            "memory_bytes_upper_bound": 4 * 1024**3,
            "gpu": False,
            "solver_launch": False,
            "input_roles": [
                "terminal producer request/receipt/proof and exact CURRENT source/control closure",
                "selected native frame paths with parent-established pre/immediate-post SHA/stat",
                "RunPARTs/actual time metadata for each selected query or bracket",
                "decoder/observer source closure and literal virtualenv/config records",
            ],
            "output_roles": ["bounded compact observer report", "source/frame manifest", "independent join record"],
            "hash_and_stat_policy": "Selected native files are deferred payloads: parent reserves first, then the worker records stable pre/decode/post stat and SHA. Unknown historical SHA is reported as first-established-in-parent and never backfilled from XML.",
            "query_policy": "Use exact saved rows where present; retain lower/upper RunPART brackets with their real times and never interpolate or call the bracket a field error bound.",
        },
        "parent_sequence": ["selected RunPART-derived frames", "native role/MK/header observer", "small compact report and independent join"],
        "measurements": ["native MassFluid/MassBound/Dp", "fluid-only weighted COM/velocity/KE", "role/region identity", "exact or bracketed times"],
        "spatial_gate": "cross-grid comparisons are diagnostic only and never use a neighboring grid as truth",
        "integration_gate": "requires same source/grid/output and an actual CFL-only pair with dt/clamp evidence",
        "output_gate": "requires same source/grid/CFL with a declared output-cadence-only change",
        "status_if_missing": "UNKNOWN_WITH_LOCAL_FIELDS_ONLY",
    },
    "F5-S1": {
        "request_kind": "SOURCE_BOUND_GEOMETRY_DIAGNOSTIC",
        "source_contract": "ROOT091/109/110/114 proof metadata plus CURRENT q123 producer/receipt/control paths",
        "runtime_request_contract": {
            "source_prepared_kind": "audit",
            "parent_normalization_required": True,
            "execution_allowed_in_this_artifact": False,
            "cpu_threads": 1,
            "wall_seconds_upper_bound": 900,
            "memory_bytes_upper_bound": 2 * 1024**3,
            "gpu": False,
            "solver_launch": False,
            "input_roles": [
                "q123 request/terminal receipt/generated XML and exact source control closure",
                "Fluid and Bound VTK paths with parent-established SHA/stat",
                "official clip-plane source/binary evidence and continuous-owner definition",
            ],
            "output_roles": ["small geometry/support summary", "per-MK role/count/inside-outside report", "mass-gate decision"],
            "hash_and_stat_policy": "Generated XML may be joined as a small input; Fluid/Bound arrays remain deferred and are read only after parent reservation with stable pre/decode/post source records. No XML mass fallback, mass rescale, or deletion of out-of-owner points.",
            "admission_policy": "A solver request remains blocked while clip/overlap/owner support is unresolved or the frozen continuous-mass gate is hard-failed.",
        },
        "parent_sequence": ["source/receipt XML join", "Fluid/Bound all-shape support audit", "clip/overlap/owner mass decision"],
        "measurements": ["native role counts/header where present", "Fluid/Bound inside/outside/overlap", "clip-plane assignment", "continuous owner volume/mass"],
        "spatial_gate": "only source-preserving geometry variants; no mass rescale or sample-relative normalization",
        "integration_gate": "not admitted while initial owner/support gate is unresolved",
        "output_gate": "not admitted while initial owner/support gate is unresolved",
        "status_if_missing": "HARDFAIL_OR_UNKNOWN_SOURCE_BRANCH",
    },
}


def _readiness(status: dict[str, Any], dimensions: dict[str, Any], graph: dict[str, Any], source_records: dict[str, Any]) -> dict[str, Any]:
    status_rows = {row["sentinel_id"]: row for row in status.get("sentinels", []) if isinstance(row, dict)}
    dim_rows = {row["sentinel_id"]: row for row in dimensions.get("sentinels", []) if isinstance(row, dict)}
    graph_rows = {row["sentinel_id"]: row for row in graph.get("sentinels", []) if isinstance(row, dict)}
    if set(status_rows) != set(SENTINELS):
        raise ReadinessFailure("v4 evidence registry does not contain exactly fourteen sentinel IDs")
    entries: list[dict[str, Any]] = []
    for sid in SENTINELS:
        row = status_rows[sid]
        dims = dim_rows.get(sid, {}).get("dimensions", {})
        dimension_summary = {}
        for name, value in dims.items():
            if not isinstance(value, dict):
                continue
            evidence = value.get("evidence") if isinstance(value.get("evidence"), list) else []
            dimension_summary[name] = {
                "status": value.get("status", "UNKNOWN"),
                "actual_evidence_count": int(value.get("actual_evidence_count", 0)),
                "evidence_ids": [item.get("evidence_id") for item in evidence if isinstance(item, dict)],
                "scope_notes": [item.get("note") for item in evidence if isinstance(item, dict) and item.get("note")],
                "scientific_credit": False,
            }
        next_task = row.get("next_guarded_task") if isinstance(row.get("next_guarded_task"), dict) else {}
        graph_row = graph_rows.get(sid, {})
        evidence = [_proof_ref(item) for item in row.get("evidence", []) if isinstance(item, dict)]
        minimum = MINIMUMS[sid]
        entries.append({
            "sentinel_id": sid,
            "family_id": row.get("family_id"),
            "physical_case_id": row.get("physical_case_id"),
            "terminal_state": row.get("terminal_state"),
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "actual_evidence": evidence,
            "actual_evidence_count": len(evidence),
            "dimension_readiness": dimension_summary,
            "next_parent": {
                "kind": next_task.get("kind", graph_row.get("next_action")),
                "action": next_task.get("action", graph_row.get("next_action")),
                "source_prerequisite": next_task.get("source_prerequisite"),
                "success_condition": next_task.get("success_condition"),
                "payload_read": next_task.get("payload_read", "deferred until parent reservation"),
                "solver_launch": bool(next_task.get("solver_launch", False)),
                "resource_estimate": _cost_for(str(next_task.get("kind", ""))),
            },
            "minimum_new_evidence": minimum["gate"],
            "next_scientific_action": minimum["next"],
            "unknown_impact": minimum["impact"],
            "recovery_if_gate_fails": "Preserve the failed/partial report with exact reason; keep QI/QN/QE UNKNOWN and do not promote a neighboring sentinel or grid.",
            "request_graph_reference": graph_row.get("next_action"),
        })
    return {
        "schema": READINESS_SCHEMA,
        "status": "ADDITIVE_ACTUAL_EVIDENCE_READINESS_NO_SCIENTIFIC_QUALIFICATION",
        "scope": "fourteen sentinel source/proof metadata; no production payload read by this generator",
        "source_inputs": source_records,
        "sentinel_count": len(entries),
        "sentinels": entries,
        "global_policy": {
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "no_neighbor_grid_truth": True, "no_interpolation": True,
            "bracketed_time_is_not_exact_time": True,
            "mass_source": "native decoder/header or source-supported owner contract; never XML fallback for native claims",
            "frozen_gates": status.get("frozen_gates", {}),
            "scientific_credit": 0,
        },
        "actual_vs_plan": "actual_evidence lists are completed diagnostic proof metadata; next_parent entries are plans and have no parent receipt cost",
    }


def _calibration(source_records: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    evidence_by_sid = {row["sentinel_id"]: row["actual_evidence"] for row in readiness["sentinels"]}
    rows = []
    for sid in ("F2-S2", "F3-S1", "F5-S1"):
        row = dict(CALIBRATION_ROWS[sid])
        row.update({"sentinel_id": sid, "evidence_refs": evidence_by_sid[sid],
                    "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
                    "launch_disabled_in_source_contract": True, "payload_read_by_builder": False,
                    "parent_must_bind_actual_request_receipt_proof": True})
        rows.append(row)
    return {
        "schema": CALIBRATION_SCHEMA,
        "status": "SOURCE_PREREGISTERED_THREE_SENTINEL_DIAGNOSTICS_NO_SCIENTIFIC_QUALIFICATION",
        "source_inputs": source_records,
        "sentinels": rows,
        "comparison_separation": {
            "spatial": {"observable": "fluid-only native weighted COM/velocity/KE, role counts, support", "condition": "same owner/control/window; three spatial resolutions", "truth_policy": "diagnostic only; no finest/neighbour truth"},
            "integration": {"observable": "native field at exact saved times plus actual dt/clamp trace", "condition": "same grid/source/output cadence; CFL-only change", "truth_policy": "requires actual same-time pair; async brackets stay UNKNOWN"},
            "output_sampling": {"observable": "same native fields at exact saved rows and selected missing-row brackets", "condition": "same grid/source/CFL/window; output cadence-only change", "truth_policy": "no interpolation or cadence-to-field error inference"},
            "native_header": {"observable": "MassFluid/MassBound/Dp/Idp and typed role counts", "condition": "decoder-produced native metadata joined to exact producer receipt", "truth_policy": "no XML mass fallback; missing fields UNKNOWN"},
        },
        "frozen_tolerances_before_results": {
            "position": "2% registered L; 5% near event",
            "velocity_ke": "5% of registered nonzero scale",
            "regional_mass": "3 percentage points of whole initial fluid mass",
            "event_time": "1% registered characteristic time",
            "time_output": "each <= one quarter of its registered task gate",
            "whole_initial_mass": "preferred <=1%; 1-2% marginal diagnostic; >2% hard fail",
        },
        "unknown_policy": "A missing source join, field, exact time, or owner contract yields UNKNOWN for that subtask and does not block independent fields.",
        "scientific_credit": 0,
    }


def build(output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    status, status_record = _small_json(STATUS_V4, "v4 evidence registry")
    dimensions, dimensions_record = _small_json(DIMENSIONS_V2, "v2 dimension inventory")
    graph, graph_record = _small_json(REQUEST_GRAPH_V5, "v5 request graph")
    _, registry_record = _small_json(REGISTRY_CORRECTION, "registry scope correction")
    source_records = {"status_v4": status_record, "dimensions_v2": dimensions_record,
                      "request_graph_v5": graph_record, "registry_scope_correction_v1": registry_record}
    readiness = _readiness(status, dimensions, graph, source_records)
    calibration = _calibration(source_records, readiness)
    readiness_path = output_dir / "stage2_fourteen_actual_evidence_readiness_v6.json"
    calibration_path = output_dir / "stage2_three_sentinel_calibration_preregister_v1.json"
    for path, value in ((readiness_path, readiness), (calibration_path, calibration)):
        if path.exists() or path.is_symlink():
            raise ReadinessFailure(f"refusing to overwrite immutable output: {path}")
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    return {"readiness": str(readiness_path), "calibration": str(calibration_path),
            "sentinel_count": len(readiness["sentinels"]), "source_records": source_records,
            "scientific_credit": 0, "payload_read": False}


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="fourteen-readiness-v6-") as td:
        result = build(Path(td))
        readiness = json.loads(Path(result["readiness"]).read_text())
        calibration = json.loads(Path(result["calibration"]).read_text())
        if readiness["sentinel_count"] != 14 or len(readiness["sentinels"]) != 14:
            raise AssertionError("readiness does not contain exactly fourteen IDs")
        if {row["sentinel_id"] for row in readiness["sentinels"]} != set(SENTINELS):
            raise AssertionError("readiness ID set is not exact")
        if [row["sentinel_id"] for row in calibration["sentinels"]] != ["F2-S2", "F3-S1", "F5-S1"]:
            raise AssertionError("calibration does not contain the three requested sentinels")
        if any(row["scientific_qualification"] != {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"} for row in readiness["sentinels"]):
            raise AssertionError("readiness granted an unintended qualification")
        if any(row["launch_disabled_in_source_contract"] is not True for row in calibration["sentinels"]):
            raise AssertionError("calibration source contract is launch-enabled")
        if readiness["source_inputs"]["status_v4"]["sha256"] != status_sha_from_file():
            raise AssertionError("status registry source SHA is not stable")
    print("PASS_FOURTEEN_ACTUAL_EVIDENCE_READINESS_V6_AND_THREE_SENTINEL_CALIBRATION_SELFTEST")


def status_sha_from_file() -> str:
    return hashlib.sha256(STATUS_V4.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test()
        else:
            if args.output_dir is None:
                parser.error("--output-dir is required unless --self-test is used")
            print(json.dumps(build(args.output_dir), sort_keys=True))
    except (ReadinessFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_ACTUAL_EVIDENCE_READINESS_V6: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
