#!/usr/bin/env python3
"""Prepare source-bound, launch-disabled full-window canary requests.

This is a request builder for parent GPU review.  It reads small XML/JSON
metadata and hashes the already completed GenCase artifacts, but never opens a
trajectory HDF5, starts a solver, or creates a native output tree.  The three
requests cover the first useful mass-compatible candidates:

* F2-S1 fine dp=0.00855, dense same-CFL output at 0.005 s;
* F4-S1 coarse dp=0.01230, dense same-CFL output at 0.0005 s;
* F7-S1 fine dp=0.01656, dense same-CFL output at 0.01 s.

The current native output is the immutable complete scientific source.  A
single streaming observer pass and selected typed query anchors are planned as
derived artifacts.  The full-time lossless-compression ratio is deliberately
left unknown: the earlier two-frame ratio is not used as a whole-window
storage guarantee.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.full-window-canary-request.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
GRAPH = REFERENCE / "stage2_minimal14_study_graph_v2.json"
OUTPUT_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-full-window-canary-v1"
BINDING_OUTPUT = REFERENCE / "stage2_full_window_canary_binding_v1.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
PARENT_PID = 1055602
PROTECTED_GPU = {
    "index": 6,
    "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689,
    "action": "do_not_touch",
}
QUERY_TIMES = [0.0, 1.0, 2.0, 3.0, 4.0]


SPECS: tuple[dict[str, Any], ...] = (
    {
        "sentinel_id": "F2-S1",
        "family_id": "F2",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "grid": "fine",
        "dp_m": 0.00855,
        "candidate_case_id": "F2_S1_MASSFIT_V4_NEAR_DP0p008550",
        "candidate_attempt_id": "f2_s1_massfit_v4_near_dp0p008550-001",
        "candidate_request": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f2-mass-fit-probe-v4/f2_s1_massfit_v4_near_dp0p008550.json",
        "source_xml_key": "F2-S1",
        "dense_cadence_s": 0.005,
        "query_times_s": QUERY_TIMES,
        "postrun_output_case": "F2_S1_FULL_WINDOW_CANARY_FINE_DP00855_T4",
    },
    {
        "sentinel_id": "F4-S1",
        "family_id": "F4",
        "physical_case_id": "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
        "grid": "coarse",
        "dp_m": 0.01230,
        "candidate_case_id": "F4_S1_MASSFIT_V3_COARSE_DP0p012300",
        "candidate_attempt_id": "f4_s1_massfit_v3_coarse_dp0p012300-001",
        "candidate_request": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-mass-fit-probe-v3/f4_s1_massfit_v3_coarse_dp0p012300.json",
        "source_xml_key": "F4-S1",
        "dense_cadence_s": 0.0005,
        "query_times_s": [0.0, 0.3, 0.6, 0.9, 1.2],
        "postrun_output_case": "F4_S1_FULL_WINDOW_CANARY_COARSE_DP01230_T1P2",
    },
    {
        "sentinel_id": "F7-S1",
        "family_id": "F7",
        "physical_case_id": "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1",
        "grid": "fine",
        "dp_m": 0.01656,
        "candidate_case_id": "F7_S1_MASSFIT_V3_FINE_DP0p016560",
        "candidate_attempt_id": "f7_s1_massfit_v3_fine_dp0p016560-001",
        "candidate_request": REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-mass-fit-probe-v3/f7_s1_massfit_v3_fine_dp0p016560.json",
        "source_xml_key": "F7-S1",
        "dense_cadence_s": 0.01,
        "query_times_s": [0.0, 3.0, 6.0, 9.0, 12.0],
        "postrun_output_case": "F7_S1_FULL_WINDOW_CANARY_FINE_DP01656_T12",
    },
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def source_xml_info(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    values: dict[str, str] = {}
    for node in root.findall(".//parameters/parameter"):
        if node.get("key") is not None and node.get("value") is not None:
            values[node.get("key")] = node.get("value")
    cfl = root.find(".//constants/cflnumber")
    cfl_value = float(cfl.get("value")) if cfl is not None and cfl.get("value") is not None else None
    definition = root.find(".//definition")
    dp = float(definition.get("dp")) if definition is not None and definition.get("dp") is not None else None
    particles = root.find(".//particles")
    total_particles = int(particles.get("np")) if particles is not None and particles.get("np") else None
    fluid_nodes = [n for n in root.findall(".//fluid") if n.get("mkfluid") is not None and n.get("count") is not None]
    fluid_count = sum(int(n.get("count")) for n in fluid_nodes)
    mass_node = root.find(".//constants/massfluid")
    massfluid = float(mass_node.get("value")) if mass_node is not None and mass_node.get("value") else None
    return {
        "file": record(path),
        "dp_m": dp,
        "cfl": cfl_value,
        "parameters": values,
        "particles": total_particles,
        "fluid_particle_count": fluid_count,
        "massfluid_kg": massfluid,
        "sample_mass_kg": fluid_count * massfluid if massfluid is not None else None,
    }


def find_cost_row(graph: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    rows = [
        row
        for row in graph["cost_rows"]
        if row.get("sentinel_id") == spec["sentinel_id"]
        and row.get("grid") == spec["grid"]
        and row.get("requested_dp_m") == spec["dp_m"]
        and row.get("cfl_mode") == "same_cfl"
        and row.get("cadence_kind") == "dense"
    ]
    if len(rows) != 1:
        raise ValueError(f"expected one graph cost row for {spec['sentinel_id']} {spec['dp_m']}: {len(rows)}")
    return rows[0]


def find_sentinel(graph: dict[str, Any], sentinel_id: str) -> dict[str, Any]:
    rows = [row for row in graph["sentinels"] if row.get("sentinel_id") == sentinel_id]
    if len(rows) != 1:
        raise ValueError(f"expected one sentinel graph row: {sentinel_id}")
    return rows[0]


def candidate_paths(spec: dict[str, Any], request: dict[str, Any]) -> dict[str, Path | None]:
    root = DATA_ROOT / "families" / spec["family_id"] / spec["candidate_case_id"] / spec["candidate_attempt_id"]
    generated_xml = root / "generated.xml"
    generated_bi4 = root / "generated.bi4"
    motion = None
    for child in sorted(root.iterdir()):
        if child.name.endswith(".dat"):
            motion = child
            break
    # The derived Def is the input file ending in _Def.xml.  It is retained as
    # provenance, while generated.xml/bi4 are the actual solver input pair.
    definition = None
    for value in request.get("input_files", []):
        path = Path(value)
        if path.name.endswith("_Def.xml"):
            definition = path
            break
    return {
        "root": root,
        "generated_xml": generated_xml,
        "generated_bi4": generated_bi4,
        "motion": motion,
        "definition": definition,
        "receipt": root / "execution-receipt.json",
    }


def file_inputs(paths: list[Path | None]) -> tuple[list[str], dict[str, str]]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if path is None:
            continue
        path = require_file(path, "request input")
        resolved = path.resolve()
        if str(resolved) not in seen:
            seen.add(str(resolved))
            unique.append(resolved)
    return [str(path) for path in unique], {str(path): sha256_file(path) for path in unique}


def build_case(spec: dict[str, Any], graph: dict[str, Any], commit: str) -> tuple[dict[str, Any], dict[str, Any]]:
    sentinel = find_sentinel(graph, spec["sentinel_id"])
    cost = find_cost_row(graph, spec)
    candidate_request_path = require_file(spec["candidate_request"], "historical candidate request")
    candidate_request = load_json(candidate_request_path)
    candidate = candidate_paths(spec, candidate_request)
    for label, path in candidate.items():
        if label != "motion" and path is None:
            raise FileNotFoundError(f"candidate {spec['sentinel_id']} missing {label}")
    receipt = load_json(candidate["receipt"])
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"candidate GenCase is not a successful terminal receipt: {candidate['receipt']}")
    source_xml_path = Path(sentinel["source_xml"]["path"])
    source_receipt_path = Path(sentinel["source_solver_controls"]["receipt_runtime"]["path"])
    source_xml = source_xml_info(require_file(source_xml_path, "CURRENT source XML"))
    candidate_xml = source_xml_info(require_file(candidate["generated_xml"], "candidate generated XML"))
    if candidate_xml["particles"] != receipt.get("total_particles") or candidate_xml["fluid_particle_count"] != receipt.get("fluid_particles"):
        raise ValueError(f"candidate XML/receipt counts disagree: {spec['sentinel_id']}")
    if spec["sentinel_id"] == "F7-S1" and candidate_request.get("scope", {}).get("physical_case_id") != spec["physical_case_id"]:
        historical_identity_status = "HISTORICAL_REQUEST_ALIAS_MISMATCH_REBOUND_TO_EXACT_CURRENT_ID"
    else:
        historical_identity_status = "HISTORICAL_REQUEST_ID_MATCHES_CURRENT_ID"

    source_frames = int(sentinel["frames_in_current_catalog"])
    source_gpu_seconds = float(sentinel["source_solver_controls"]["receipt_runtime"]["gpu_seconds"])
    particle_scale = float(cost["particle_scale_vs_current_source"])
    frame_scale = float(cost["planned_frames"]) / source_frames
    runtime_proxy = source_gpu_seconds * particle_scale * frame_scale
    anchor_frame_bytes = int(cost["estimated_part_bytes"])
    anchor_typed_bytes = int(math.ceil(len(spec["query_times_s"]) * anchor_frame_bytes * 2.0 * 1.2))
    observer_reserved_bytes = 512 * 1024 * 1024
    request_reservation = int(math.ceil(cost["raw_native_reserved_bytes"] + anchor_typed_bytes + observer_reserved_bytes + 512 * 1024 * 1024))
    # Keep the reservation practical while retaining the explicit raw safety
    # margin.  The parent guard's terminal receipt remains authoritative.
    request_reservation = max(request_reservation, 8 * 1024**3 if spec["family_id"] != "F2" else 32 * 1024**3)
    tmax = float(cost["full_physical_window_s"][1])
    tout = float(spec["dense_cadence_s"])
    output_case = spec["postrun_output_case"]
    output_attempt = output_case.lower().replace("_", "-") + "-root-001"
    candidate_root = Path(candidate["root"])
    command = [str(SOLVER), str(candidate_root / "generated"), "{attempt_root}/solver_output", f"-tmax:{tmax:g}", f"-tout:{tout:g}"]
    input_paths = [
        DISPATCH,
        STRICT,
        RUNTIME,
        SOLVER,
        candidate_request_path,
        candidate["receipt"],
        candidate["generated_xml"],
        candidate["generated_bi4"],
        candidate["motion"],
        candidate["definition"],
        source_xml_path,
        source_receipt_path,
    ]
    input_files, input_hashes = file_inputs(input_paths)
    controls = {
        "cfl_mode": "same_cfl",
        "xml_cfl": candidate_xml["cfl"],
        "xml_dt_min_s": float(candidate_xml["parameters"].get("DtMin", "nan")),
        "xml_dt_fixed_s": float(candidate_xml["parameters"].get("DtFixed", "nan")),
        "xml_timemax_s": float(candidate_xml["parameters"].get("TimeMax", "nan")),
        "xml_timeout_s": float(candidate_xml["parameters"].get("TimeOut", "nan")),
        "effective_cli_tmax_s": tmax,
        "effective_cli_tout_s": tout,
        "actual_dt_sequence": "UNKNOWN_UNTIL_PARENT_GUARDED_SOLVER",
        "dt_clamp_events": "UNKNOWN_UNTIL_PARENT_GUARDED_SOLVER",
        "savedt_or_dtallinfo": "UNKNOWN; official v5.4 CLI/source audit found no -svdt option and RunPARTs summary is not a complete per-step trace",
    }
    binding = {
        "schema": "ds02.stage2.full-window-canary-binding.v1",
        "sentinel_id": spec["sentinel_id"],
        "family_id": spec["family_id"],
        "physical_case_id": spec["physical_case_id"],
        "grid": spec["grid"],
        "candidate_dp_m": spec["dp_m"],
        "identity": {
            "current_row_status": sentinel["current_row_identity_status"],
            "historical_candidate_request_status": historical_identity_status,
            "historical_candidate_request_scope_physical_case_id": candidate_request.get("scope", {}).get("physical_case_id"),
            "current_source_xml": source_xml,
            "source_solver_receipt": record(require_file(source_receipt_path, "CURRENT source solver receipt")),
            "source_h5_producer_metadata": sentinel["current_binding"]["trajectory"],
            "h5_hash_scope": "producer_declared_sha256_only; no H5 read or recompute in this preparation",
        },
        "candidate_gencase": {
            "historical_request": record(candidate_request_path),
            "terminal_receipt": record(candidate["receipt"]),
            "generated_xml": candidate_xml,
            "generated_bi4": record(candidate["generated_bi4"]),
            "motion": record(candidate["motion"]) if candidate["motion"] else None,
            "definition": record(candidate["definition"]) if candidate["definition"] else None,
            "mass_gate": {
                "source_sample_mass_kg": source_xml["sample_mass_kg"],
                "candidate_sample_mass_kg": candidate_xml["sample_mass_kg"],
                "relative_error_pct": (candidate_xml["sample_mass_kg"] - source_xml["sample_mass_kg"]) / source_xml["sample_mass_kg"] * 100.0,
                "status": "PASS_TARGET_1PCT_DIAGNOSTIC_ONLY",
                "scientific_qualification": "UNKNOWN",
            },
        },
        "controls": controls,
        "cost": {
            "graph_row": cost,
            "source_solver_gpu_seconds": source_gpu_seconds,
            "particle_scale_vs_current_source": particle_scale,
            "frame_scale_vs_current_source": frame_scale,
            "gpu_seconds_proxy": runtime_proxy,
            "gpu_hours_proxy": runtime_proxy / 3600.0,
            "proxy_warning": "scaled source receipt only; not a wall-time upper bound; parent lease/terminal receipt is authoritative",
            "raw_native_full_window_bytes_unreserved": cost["raw_native_unreserved_bytes"],
            "raw_native_full_window_bytes_reserved": cost["raw_native_reserved_bytes"],
            "typed_full_h5": "NOT_PLANNED_IN_THIS_CANARY; use selected query anchors to avoid a second full copy",
            "typed_anchor_query_times_s": spec["query_times_s"],
            "typed_anchor_bytes_proxy": anchor_typed_bytes,
            "stream_observer_reserved_bytes": observer_reserved_bytes,
            "full_time_lossless_bytes": "UNKNOWN_UNTIL_FULL_WINDOW_ROUNDTRIP_CANARY",
            "two_frame_archive_ratio": cost["archive_ratio_measured_pair"],
            "two_frame_ratio_use": "diagnostic context only; excluded from full-window reservation",
            "request_storage_reservation_bytes": request_reservation,
        },
        "output_plan": {
            "native_raw": "{attempt_root}/solver_output/data/Part_*.bi4; retain every saved frame for the complete physical window",
            "native_source_role": "immutable primary scientific array source; no deletion, replacement, or favorable-subset pruning",
            "stream_observer": {
                "mode": "one sequential pass over complete native frames",
                "output": "{attempt_root}/observer/stream-observables.jsonl",
                "scope": "pre-registered observables only; does not replace native arrays",
                "status": "PENDING_CONSUMER_CALIBRATION",
            },
            "typed": {
                "mode": "selected query-time replay anchors only",
                "query_times_s": spec["query_times_s"],
                "output": "{attempt_root}/typed/query-anchors/",
                "time_policy": "EXACT/BRACKETED using actual saved times; no frame-number hardcoding or extrapolation",
                "full_h5": "deferred separate request; native arrays remain accessible through decoder/reader contract",
            },
            "lossless_archive": {
                "mode": "deferred full-window roundtrip benchmark",
                "output": "{attempt_root}/archive/full-window-lossless/",
                "required_proof": ["every source frame included", "compressed bytes", "decompressed byte-for-byte SHA", "complete array decoder access"],
                "status": "PENDING_FULL_WINDOW_CANARY",
                "ratio": "UNKNOWN",
            },
            "downsample": "derived only after retaining complete raw; no solver replacement",
            "overwrite_policy": "all output paths must be new and absent",
        },
        "launch_policy": {
            "launch_disabled": True,
            "execution_allowed": False,
            "solver_launch_owner": "root",
            "primary_gpu_dispatch_required": True,
            "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER",
            "protected_external_gpu": PROTECTED_GPU,
            "parent_pid_binding": PARENT_PID,
        },
    }
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": spec["family_id"],
        "case_id": output_case,
        "physical_case_id": spec["physical_case_id"],
        "attempt_id": output_attempt,
        "kind": "qualification",
        "qualification_stage": "stage2_source_bound_full_window_canary_pending_primary_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": request_reservation,
        "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(REPO),
        "cwd": str(candidate_root),
        "command": command,
        "candidate_gencase_receipt": str(candidate["receipt"].resolve()),
        "candidate_gencase_receipt_sha256": sha256_file(candidate["receipt"]),
        "expected_particles": candidate_xml["particles"],
        "expected_fluid_particles": candidate_xml["fluid_particle_count"],
        "expected_native_frames": cost["planned_frames"],
        "expected_dimension": 3,
        "physical_window_s": cost["full_physical_window_s"],
        "save_interval_s": tout,
        "source_binding": binding,
        "input_files": input_files,
        "input_hashes": input_hashes,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "launch_commit": commit,
            "cpu_parent_binding": "required",
            "gpu": "primary root dispatch only",
            "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER",
            "protected_external_gpu": PROTECTED_GPU,
            "estimated_cpu_core_hours": "UNKNOWN_UNTIL_GUARDED_SOLVER",
            "estimated_gpu_hours_proxy": runtime_proxy / 3600.0,
            "estimated_new_storage_bytes": request_reservation,
            "solver_launch_owner": "root",
        },
        "scope": {
            "sentinel_id": spec["sentinel_id"],
            "physical_case_id": spec["physical_case_id"],
            "grid": spec["grid"],
            "requested_dp_m": spec["dp_m"],
            "cfl_mode": "same_cfl",
            "dense_output_cadence_s": tout,
            "full_physical_window_s": cost["full_physical_window_s"],
            "continuous_geometry_control": "source-bound candidate input; solver/domain equivalence remains UNKNOWN",
            "gencase_mass_compatibility": "PASS_TARGET_1PCT_DIAGNOSTIC_ONLY",
            "native_complete_window_required": True,
            "typed_full_h5": "deferred",
            "full_time_hdf5_read": False,
            "solver_started": False,
            "gpu_uuid_lease": "none_until_primary_dispatch",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "launch_disabled": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "primary_gpu_dispatch_required": True,
        "dispatch_status": "PENDING_PRIMARY_RESOURCE_AND_SCIENTIFIC_REVIEW",
        "do_not_execute_from_preparation_worktree": True,
        "foreign_process_protection_required": True,
    }
    return binding, request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        raise SystemExit("use --prepare; outputs are immutable and refuse overwrite")
    graph = load_json(require_file(GRAPH, "minimal14 study graph"))
    commit = git_commit()
    cases = []
    requests = []
    # Build bindings before writing them so every request can hash the single
    # canonical binding manifest after it exists.
    for spec in SPECS:
        binding, request = build_case(spec, graph, commit)
        cases.append(binding)
        requests.append((spec, request))
    manifest = {
        "schema": "ds02.stage2.full-window-canary-binding-set.v1",
        "status": "PREPARED_LAUNCH_DISABLED_PRIMARY_REVIEW",
        "generated_at_commit": commit,
        "scope": "three source-bound mass-compatible candidate full-window same-CFL dense requests; no solver/H5 read or launch",
        "storage_contract": {
            "native_raw": "retain complete uncompressed scientific arrays",
            "stream_observer": "one pass derived observables only",
            "typed": "selected query anchors only; no duplicate complete H5 in this canary",
            "lossless": "full-window roundtrip canary required; two-frame ratio not used as upper bound",
            "source_immutable": True,
        },
        "protected_external_gpu": PROTECTED_GPU,
        "cases": cases,
    }
    atomic_json(BINDING_OUTPUT, manifest)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for spec, request in requests:
        binding_path = BINDING_OUTPUT.resolve()
        request["input_files"].append(str(binding_path))
        request["input_hashes"][str(binding_path)] = sha256_file(binding_path)
        request_path = OUTPUT_DIR / f"{spec['sentinel_id'].lower().replace('-', '_')}_{spec['grid']}_dp{str(spec['dp_m']).replace('.', '')}_same_cfl_dense.json"
        atomic_json(request_path, request)
    postrun = {
        "schema": "ds02.stage2.full-window-postrun-plan.v1",
        "status": "PREPARED_DEFERRED_UNTIL_PRIMARY_CANARY_TERMINAL_RECEIPTS",
        "binding_manifest": str(BINDING_OUTPUT.resolve()),
        "source_role": "complete native Part_*.bi4 remains immutable primary source",
        "tasks": [
            {
                "task": "single_stream_observer_pass",
                "input": "{canary_attempt_root}/solver_output/data/Part_*.bi4",
                "output": "{canary_attempt_root}/observer/stream-observables.jsonl",
                "contract": "one sequential pass; pre-registered observables; no array deletion",
                "status": "DEFERRED",
            },
            {
                "task": "typed_query_anchor_replay",
                "input": "complete native Part_*.bi4 at registered physical query times",
                "output": "{canary_attempt_root}/typed/query-anchors/",
                "contract": "actual-time bracket metadata and all selected fields; full native remains accessible",
                "status": "DEFERRED",
            },
            {
                "task": "full_window_lossless_roundtrip_canary",
                "input": "complete native Part_*.bi4",
                "output": "{canary_attempt_root}/archive/full-window-lossless/",
                "contract": "include every frame, byte-for-byte decompression SHA, complete decoder access, compressed bytes and CPU time",
                "ratio": "UNKNOWN_UNTIL_MEASURED",
                "status": "DEFERRED",
            },
        ],
        "no_solver_launch": True,
        "no_h5_read": True,
    }
    postrun_path = REFERENCE / "stage2_full_window_postrun_plan_v1.json"
    atomic_json(postrun_path, postrun)
    print(json.dumps({"status": "PASS", "commit": commit, "binding": str(BINDING_OUTPUT), "requests": len(requests), "postrun_plan": str(postrun_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
