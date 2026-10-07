#!/usr/bin/env python3
"""Build a source-bound, launch-disabled plan for the ten remaining sentinels.

This is a metadata-only bridge over the already reviewed CURRENT/source and
SaveDt pair manifests.  It reads small JSON/XML/receipt metadata and never
opens HDF5 or native Part payloads.  Existing request bytes and receipts are
copied into the report by reference; this script does not rewrite them.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.remaining-ten-study-priority.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
COST = REFERENCE / "stage2_original_cfl_pair_cost_manifest_v2.json"
SAVEDT = REFERENCE / "stage2_savedt_cfl_pair_binding_v1.json"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
MINIMAL = REFERENCE / "stage2_minimal14_study_graph_v2.json"
BUILDER = Path(__file__).resolve()
OUTPUT = REFERENCE / "stage2_remaining_ten_priority_v1.json"

REMAINING = [
    "F1-S1", "F1-S2", "F2-S2", "F3-S1", "F3-S2",
    "F4-S2", "F5-S1", "F5-S2", "F6-S2", "F7-S2",
]
PRIORITY = ["F1-S1", "F7-S2", "F3-S1", "F5-S1", "F4-S2",
            "F1-S2", "F6-S2", "F2-S2", "F3-S2", "F5-S2"]
MODES = ("same_cfl", "half_cfl")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          check=True, capture_output=True, text=True).stdout.strip()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def scalar(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return raw
    return int(value) if value.is_integer() else value


def xml_controls(path: Path) -> dict[str, Any]:
    """Extract strict source controls and physical declarations from one XML."""
    root = ET.parse(path).getroot()
    params: dict[str, Any] = {}
    for node in root.iter():
        if local_name(node.tag) == "parameter" and node.get("key"):
            params[node.get("key")] = scalar(node.get("value"))
    constants: dict[str, Any] = {}
    for node in root.iter():
        name = local_name(node.tag)
        if name in {"gravity", "rhop0", "gamma", "coefsound", "cflnumber"}:
            constants[name] = dict(node.attrib)

    rigid: dict[str, Any] = {
        "massbody_kg": None,
        "center_m": None,
        "inertia_kg_m2": None,
        "status": "UNKNOWN_NOT_DECLARED_IN_SOURCE_XML",
    }
    for node in root.iter():
        name = local_name(node.tag)
        if name == "massbody" and node.get("value") is not None:
            rigid["massbody_kg"] = float(node.get("value"))
        elif name == "center" and all(node.get(k) is not None for k in ("x", "y", "z")):
            rigid["center_m"] = [float(node.get(k)) for k in ("x", "y", "z")]
        elif name == "inertia" and all(node.get(k) is not None for k in ("x", "y", "z")):
            rigid["inertia_kg_m2"] = [float(node.get(k)) for k in ("x", "y", "z")]
    if any(rigid[key] is not None for key in ("massbody_kg", "center_m", "inertia_kg_m2")):
        rigid["status"] = "DECLARED_IN_SOURCE_XML_SEPARATE_FROM_SAMPLE_MASS"

    dependencies: list[dict[str, str]] = []
    for node in root.iter():
        name = local_name(node.tag)
        for key, value in node.attrib.items():
            if key.lower() in {"file", "name", "filename", "file1", "file2"} and value:
                if value not in {item["value"] for item in dependencies}:
                    dependencies.append({"kind": name, "value": value})
    return {
        "path": str(path.resolve()),
        "parameters": params,
        "constants": constants,
        "rigid_body": rigid,
        "declared_file_dependencies": dependencies,
    }


def source_dependency_hashes(source: dict[str, Any], source_bi4: str) -> dict[str, Any]:
    controls = source.get("source_solver_controls", {})
    launch_hashes = controls.get("input_hashes_at_launch", {})
    if not isinstance(launch_hashes, dict):
        launch_hashes = {}
    names = set(Path(source_bi4).name for _ in [0])
    for dependency in source.get("source_xml", {}).get("motion_refs", []):
        names.add(Path(str(dependency)).name)
    for dependency in source.get("source_xml", {}).get("file_dependencies", []):
        names.add(Path(str(dependency)).name)
    selected: dict[str, str] = {}
    for key, digest in launch_hashes.items():
        if (Path(key).name in names or Path(key).name.endswith("DualSPHysics5.4_linux64")
                or Path(key).name in {"CaseSloshingAccData.csv", "motion_obstacle_quintic.dat"}):
            selected[str(key)] = str(digest)
    if source_bi4 not in selected:
        selected[source_bi4] = str(launch_hashes.get(source_bi4, "UNKNOWN_NOT_IN_SOURCE_RECEIPT_HASH_MAP"))
    return {
        "selected_input_hashes": selected,
        "scope": "source receipt launch map filtered to BI4, solver binary, motion and acceleration dependencies",
        "complete_input_hash_map": "PRESERVED_IN_SOURCE_RECEIPT_NOT_COPIED_HERE",
    }


def trim_source(sid: str, source: dict[str, Any], cost_rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_xml = source["source_xml"]
    xml_path = Path(source_xml["path"])
    parsed = xml_controls(xml_path)
    source_bi4 = next((row.get("input_bi4") for row in cost_rows if row.get("input_bi4")), None)
    if not source_bi4:
        raise ValueError(f"{sid}: source BI4 missing from cost manifest")
    actual = source.get("source_solver_controls", {})
    source_xml = dict(source_xml)
    source_xml["parsed_controls_and_rigid"] = parsed
    source_xml["path_identity_status"] = "EXACT_SOURCE_XML_FROM_CURRENT_BINDING"
    gencase = source.get("current_row_binding", {})
    return {
        "sentinel_id": sid,
        "family_id": source["family_id"],
        "physical_case_id": source["physical_case_id"],
        "runtime_case_alias": source.get("runtime_case_alias"),
        "current_source": {
            "generated_xml": source_xml,
            "generated_bi4": {
                "path": str(Path(source_bi4).resolve()),
                "sha256": str(actual.get("input_hashes_at_launch", {}).get(source_bi4, "UNKNOWN_NOT_IN_SOURCE_RECEIPT_HASH_MAP")),
                "role": "exact source GenCase BI4; content unchanged by this report",
            },
            "gencase_receipt": gencase.get("gencase_receipt"),
            "solver_receipt": gencase.get("solver_receipt"),
            "source_solver_controls": {
                "status": actual.get("status"),
                "returncode": actual.get("returncode"),
                "termination_reason": actual.get("termination_reason"),
                "actual_command": actual.get("command"),
                "actual_tmax_s": actual.get("tmax_s"),
                "actual_tout_s": actual.get("tout_s"),
                "actual_terminal_time_s": source.get("window_end_s"),
                "actual_tree_bytes": actual.get("bytes"),
                "control_source": "completed CURRENT source solver receipt + exact XML parameters",
            },
            "dependency_hashes": source_dependency_hashes(source, source_bi4),
            "physical_window_s": source.get("effective_time_window_s"),
            "full_window_required": True,
            "cross_family_query_intersection_s": source.get("physical_query_scope", {}).get("cross_family_intersection_s"),
        },
        "spatial_readiness": [],
    }


def spatial_rows(sid: str, minimal: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for source in minimal["sentinels"]:
        if source["sentinel_id"] != sid:
            continue
        for row in source.get("spatial_ladder", []):
            result.append({
                "grid": row.get("label", row.get("grid")),
                "case_id": row.get("case_id"),
                "requested_dp_m": row.get("requested_dp_m"),
                "candidate_particles": row.get("candidate_particles"),
                "candidate_fluid_particles": row.get("candidate_fluid_particles"),
                "candidate_sample_mass_kg": row.get("candidate_sample_mass_kg", row.get("source_sample_mass_kg")),
                "whole_initial_mass_error_pct": row.get("whole_initial_mass_error_pct"),
                "whole_initial_mass_gate": row.get("whole_initial_mass_gate"),
                "identity_status": row.get("identity_status"),
                "continuous_geometry_control_status": row.get("continuous_geometry_control_status"),
                "scientific_qualification": "UNKNOWN_UNTIL_SOLVER_AND_OBSERVER",
            })
    return result


def pair_row(sid: str, mode: str, cost: dict[str, Any], savedt: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in savedt["requests"] if row["sentinel_id"] == sid and row["mode"] == mode]
    if len(rows) != 1:
        raise ValueError(f"{sid}/{mode}: expected one savedt request, found {len(rows)}")
    row = rows[0]
    graph = cost
    proof = row["xml_diff_proof"]
    if not row["launch_disabled"] or row["solver_started"] or row["hdf5_read"]:
        raise ValueError(f"{sid}/{mode}: existing pair request is not launch-disabled")
    return {
        "mode": mode,
        "request": row["request"],
        "request_path": row["request_path"],
        "overlay_xml": row["overlay_xml"],
        "overlay_bi4": row["overlay_bi4"],
        "overlay_manifest": row["overlay_manifest"],
        "xml_diff_proof": proof,
        "source_control_binding": {
            "source_cfl_values": proof.get("source_cfl_values"),
            "overlay_cfl_values": proof.get("overlay_cfl_values"),
            "cfl_replacements": proof.get("cfl_replacements"),
            "non_savedt_tree_equivalent": proof.get("parsed_non_savedt_tree_equivalent"),
            "declared_text_edits": proof.get("declared_text_edits"),
            "savedt_values": proof.get("savedt_values"),
        },
        "full_physical_window_s": row["requested_window_s"],
        "requested_output_cadence_s": row["requested_tout_s"],
        "requested_tmax_text": row["requested_tmax_text"],
        "planned_frames": row["planned_frames"],
        "estimated_storage_bytes": row["estimated_storage_bytes"],
        "cost_projection": {
            "candidate_particles": graph["candidate_particles"],
            "source_part0_bytes": graph["source_part0_bytes"],
            "raw_native_reserved_bytes": graph["raw_native_reserved_bytes"],
            "typed_reserved_bytes": graph["typed_reserved_bytes"],
            "archive_native_reserved_bytes": graph["archive_native_reserved_bytes"],
            "persistent_total_reserved_bytes": graph["persistent_total_reserved_bytes"],
            "temporary_peak_proxy_bytes": graph["temporary_peak_proxy_bytes"],
            "archive_ratio_scope": graph["archive_ratio_scope"],
            "cpu_wall_time": graph["cpu_wall_time"],
            "dt_sequence_and_clamp": graph["dt_sequence_and_clamp"],
        },
        "status": "PREPARED_SOURCE_BOUND_LAUNCH_DISABLED_NO_SOLVER",
    }


def build() -> dict[str, Any]:
    cost_manifest = load(COST)
    savedt_manifest = load(SAVEDT)
    quality = load(QUALITY)
    minimal = load(MINIMAL)
    sources = {row["sentinel_id"]: row for row in quality["sources"]}
    minimal_ids = {row["sentinel_id"] for row in minimal["sentinels"]}
    if set(REMAINING) - set(sources) or set(REMAINING) - minimal_ids:
        raise ValueError("remaining sentinel set is not closed over quality/minimal manifests")
    cost_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in cost_manifest["requests"]:
        if row["sentinel_id"] in REMAINING:
            cost_rows[(row["sentinel_id"], row["graph_cost"]["cfl_mode"])] = row
    records: list[dict[str, Any]] = []
    for sid in REMAINING:
        source_cost_rows = [row for (row_sid, _), row in cost_rows.items() if row_sid == sid]
        current = trim_source(sid, sources[sid], source_cost_rows)
        current["spatial_readiness"] = spatial_rows(sid, minimal)
        pairs = []
        for mode in MODES:
            cost_row = cost_rows.get((sid, mode))
            if not cost_row:
                raise ValueError(f"{sid}/{mode}: cost row missing")
            pairs.append(pair_row(sid, mode, cost_row["graph_cost"], savedt_manifest))
        pair_raw = sum(int(row["cost_projection"]["raw_native_reserved_bytes"]) for row in pairs)
        pair_persistent = sum(int(row["cost_projection"]["persistent_total_reserved_bytes"]) for row in pairs)
        pair_temporary = sum(int(row["cost_projection"]["temporary_peak_proxy_bytes"]) for row in pairs)
        records.append({
            **current,
            "calibration_request": {
                "same_cfl_dense": "REQUIRED_FULL_PHYSICAL_WINDOW",
                "half_cfl_dense": "REQUIRED_FULL_PHYSICAL_WINDOW",
                "dense_output_cadence_s": pairs[0]["requested_output_cadence_s"],
                "same_query_times": "common physical query times where within actual saved window; bracket metadata retained",
                "full_window": "retain each sentinel's actual terminal time and late-event/reference window; [0,1] is only cross-family intersection",
                "savedt": "alldt=1 overlay required; actual per-step sequence/clamp/terminal flush remains UNKNOWN until guarded receipt",
                "typed": "one bounded streaming observer first; no full HDF5/typed duplicate is required for this preparation",
                "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            },
            "pairs": pairs,
            "pair_cost_summary": {
                "same_plus_half_raw_native_reserved_bytes": pair_raw,
                "same_plus_half_persistent_projection_bytes": pair_persistent,
                "same_plus_half_temporary_peak_proxy_bytes": pair_temporary,
                "planning_only": True,
                "actual_guarded_terminal_storage_is_authoritative": True,
            },
            "status": "READY_FOR_PARENT_REVIEW_AND_SERIAL_DISPATCH; NO_SOLVER_STARTED",
        })
    records_by_id = {row["sentinel_id"]: row for row in records}
    priority_rows = []
    reasons = {
        "F1-S1": "lowest pair cost; F1 coarse mass diagnostic within 1%, fine remains marginal; first family calibration",
        "F7-S2": "low pair cost with explicit moving-obstacle control and late-event window; exact source motion dependency retained",
        "F3-S1": "first adaptive-acceleration family source; long 8.35 s window and acceleration dependency require actual dt/observer evidence",
        "F5-S1": "first corrected F5 effective-control source; actual CLI tmax=16 s versus XML TimeMax=26 s must remain explicit",
        "F4-S2": "second drop case after F4-S1; 1.2 s full window and dense output are comparatively bounded",
        "F1-S2": "F1 second geometry with 4 s endpoint; coarse mass hard-fail retained, no threshold widening",
        "F6-S2": "rigid-body angular release; body mass/center/inertia must stay separate from 5120 kg SPH sample mass",
        "F2-S2": "large 4 s offset open-rim source; high raw footprint, preserve source-only mass and motion semantics",
        "F3-S2": "second pitch/acceleration source; shares particle scale but not physical control identity with F3-S1",
        "F5-S2": "second F5 motion source; same exact source family geometry but distinct motion dependency and full 16 s window",
    }
    for rank, sid in enumerate(PRIORITY, 1):
        row = records_by_id[sid]
        priority_rows.append({
            "rank": rank,
            "sentinel_id": sid,
            "family_id": row["family_id"],
            "reason": reasons[sid],
            "pair_persistent_projection_gib": row["pair_cost_summary"]["same_plus_half_persistent_projection_bytes"] / (1024 ** 3),
            "pair_raw_reserved_gib": row["pair_cost_summary"]["same_plus_half_raw_native_reserved_bytes"] / (1024 ** 3),
            "dispatch_mode": "serial_one_pair_at_a_time; parent UUID/lease/ledger only",
        })
    resource = minimal.get("resource_snapshot", {})
    return {
        "schema": SCHEMA,
        "status": "PREPARED_SOURCE_BOUND_LAUNCH_DISABLED_NO_SOLVER",
        "generated_at_commit": git_head(),
        "source_manifests": {
            "cost": str(COST.resolve()),
            "savedt": str(SAVEDT.resolve()),
            "quality": str(QUALITY.resolve()),
            "minimal14": str(MINIMAL.resolve()),
            "builder": str(BUILDER.resolve()),
            "policy": "references existing immutable manifests; no request/receipt bytes rewritten",
        },
        "scope": {
            "remaining_sentinel_count": len(REMAINING),
            "sentinels": REMAINING,
            "modes": list(MODES),
            "full_physical_windows": True,
            "reads_hdf5": False,
            "reads_native_part_payloads": False,
            "solver_started": False,
            "gpu_started": False,
        },
        "frozen_error_budget": quality.get("error_budget_registration"),
        "priority_order": priority_rows,
        "resource_planning": {
            "manifest_home_snapshot": resource,
            "snapshot_is_not_live_authorization": True,
            "parent_must_recheck_home_floor_and_shared_ledger": True,
            "concurrency": "serial full pair; no simultaneous same/half pair reservations unless parent rebalances storage",
            "retention": "preserve raw native; streaming observer/selected typed anchors are separate; no deletion or overwrite",
            "cost_basis": "actual source Part_0000 bytes × actual requested frame count with manifest safety factors; archive ratio is two-frame canary only",
            "wall_and_gpu": "UNKNOWN_UNTIL_PARENT_GUARDED_SOLVER; source runtime is a reference proxy, not an upper bound",
        },
        "calibration_contract": {
            "same_cfl_and_half_cfl": "both required at original source dp for dt/time separation",
            "output_cadence": "dense cadence from each exact source recipe; downsampled output is a derived observer plan, not an additional CFD run",
            "common_time": "use physical query times and actual saved-time brackets; never pair frame indices across runs",
            "full_windows": "per-sentinel terminal/late-event windows remain required; common [0,1] only cross-family intersection",
            "actual_dt": "record RunPARTs saved-window min/max and DtAllInfo/alldt evidence; do not infer full per-step trace from CFL",
            "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "sentinels": records,
        "unknowns": [
            "all new same/half solver terminal bytes, wall time, actual dt sequence, clamps and final-step flush semantics",
            "physical observer values and event/window error after common-time calibration",
            "continuum/material equivalence beyond discrete initial sample mass and normalized input geometry checks",
            "parent live Home/ledger capacity at each dispatch",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        raise SystemExit("use --prepare; output refuses overwrite")
    value = build()
    atomic_json(OUTPUT, value)
    print(json.dumps({"status": value["status"], "output": str(OUTPUT), "sentinels": len(value["sentinels"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
