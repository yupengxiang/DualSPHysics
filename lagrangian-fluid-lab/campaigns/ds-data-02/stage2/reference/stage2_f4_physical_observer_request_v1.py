#!/usr/bin/env python3
"""Prepare a launch-disabled F4 physical-field observer request.

The older F4 stream observer records only native bytes and saved-time
brackets.  This request binds a bounded nine-frame decode of the completed
F4-S1 original-grid, same-CFL SaveDt run.  The worker will use ``bi4_dump``
to calculate particle-field observables for the exact query brackets.  It
does not create HDF5 and it never replaces the immutable native source.

Selected interior Part files are deliberately recorded as deferred payload
inputs: preparation records their path/statistics without rereading their
bytes.  The parent v4 guard must content-hash those files before dispatch;
the worker also reports the selected-frame hashes after decoding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f4-physical-observer-request.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F4_SOURCE = DATA_ROOT / "families/F4/F4_DROP_CENTERED_REFERENCE_001_DP010/gencase-centered-reference-002"
F4_ATTEMPT = DATA_ROOT / "families/F4/F4_S1_DP0_SAVEDT_SAME_CFL_DENSE_T1P2/f4-s1-dp0-savedt-same_cfl-primary-001"
RAW_ROOT = F4_ATTEMPT / "solver_output/data"
RUNPARTS = F4_ATTEMPT / "solver_output/RunPARTs.csv"
RUNOUT = F4_ATTEMPT / "solver_output/Run.out"
RECEIPT = F4_ATTEMPT / "execution-receipt.json"
DTALL = F4_ATTEMPT / "solver_output/DtAllInfo.csv"
DTINFO = F4_ATTEMPT / "solver_output/DtInfo.csv"
PAIR_REQUEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-dp0-savedt-pair-v1/same_cfl.json"
PAIR_AUDIT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_savedt_row_count_semantics_v2.json"
GENCASE_RECEIPT = F4_SOURCE / "execution-receipt.json"
GENERATED_XML = F4_SOURCE / "F4_DROP_CENTERED_REFERENCE_001_DP010.xml"
GENERATED_BI4 = F4_SOURCE / "F4_DROP_CENTERED_REFERENCE_001_DP010.bi4"
OVERLAY_XML = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_dp0_savedt_pair_inputs_v1/same_cfl/F4_DROP_CENTERED_REFERENCE_001_DP010_same_cfl_savedt.xml"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_CPP = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_physical_observer_v1.py"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OUTPUT_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f4-physical-observer-v1"
REQUEST_PATH = OUTPUT_DIR / "f4_s1_dp0_same_cfl_selected_physical_observer.json"
REPORT_PATH = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f4_physical_observer_binding_v1.json"

QUERY_TIMES = [0.0, 0.3, 0.6, 0.9, 1.2]
SELECTED_FRAMES = [0, 599, 600, 1199, 1200, 1799, 1800, 2399, 2400]
EXPECTED_FRAME_COUNT = 2401
EXPECTED_FINAL_TIME = 1.200084396929538
EXPECTED_PARTICLE_COUNT = 83233
EXPECTED_FLUID_COUNT = 59072
EXPECTED_RAW_BYTES_BY_STAT = 0  # filled from the completed request/receipt only when known; never used as a full-tree claim
PROTECTED_GPU = {
    "index": 6,
    "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689,
    "action": "do_not_touch",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path, *, content_hash: bool = True) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    value: dict[str, Any] = {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if content_hash:
        value["sha256"] = sha256_file(path)
    return value


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
                          capture_output=True, text=True).stdout.strip()


def xml_metadata(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    parameters: dict[str, Any] = {}
    for node in root.findall(".//parameters/parameter"):
        key = node.get("key")
        value = node.get("value")
        if key and value is not None:
            try:
                parameters[key] = float(value)
            except ValueError:
                parameters[key] = value
    definition = root.find(".//geometry/definition")
    constants = root.find(".//constants")
    particles = root.find(".//particles")
    fluid = []
    if particles is not None:
        for node in particles:
            if node.tag.rsplit("}", 1)[-1].lower() == "fluid" and node.get("mkfluid") is not None:
                fluid.append({
                    "mkfluid": int(node.get("mkfluid", "-1")),
                    "begin": int(node.get("begin", "-1")),
                    "count": int(node.get("count", "-1")),
                })
    massfluid = None
    if constants is not None and constants.find("massfluid") is not None:
        massfluid = float(constants.find("massfluid").get("value", "nan"))
    cfl = root.find(".//constants/cflnumber")
    return {
        "file": record(path),
        "dp_m": float(definition.get("dp")) if definition is not None and definition.get("dp") else None,
        "cfl": float(cfl.get("value")) if cfl is not None and cfl.get("value") else None,
        "parameters": parameters,
        "particles": int(particles.get("np")) if particles is not None and particles.get("np") else None,
        "fluid_blocks": fluid,
        "fluid_particle_count": sum(int(item["count"]) for item in fluid),
        "massfluid_kg": massfluid,
        "sample_mass_kg": (sum(int(item["count"]) for item in fluid) * massfluid
                           if massfluid is not None else None),
    }


def canonical_geometry_and_motion(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    geometry = root.find(".//geometry/commands")
    motion = root.find(".//casedef/motion")
    if geometry is None:
        raise ValueError(f"source XML lacks geometry commands: {path}")
    if motion is None:
        # F4-S1 is a fixed-boundary/drop source with no motion node.  Preserve
        # that fact explicitly; an absent motion declaration is not equivalent
        # to an invented empty control file.
        motion_text = "ABSENT_IN_SOURCE_XML"
    else:
        motion_copy = ET.fromstring(ET.tostring(motion, encoding="unicode"))
        for node in motion_copy.iter():
            if node.tag.rsplit("}", 1)[-1].lower() == "file":
                node.attrib.pop("name", None)
        motion_text = ET.tostring(motion_copy, encoding="unicode")
    physical_parameters = {}
    for key in ("gravity", "rhop0", "gamma", "coefsound", "cflnumber"):
        node = root.find(f".//constantsdef/{key}")
        if node is not None:
            physical_parameters[key] = dict(sorted(node.attrib.items()))
    for key in ("Boundary", "SlipMode", "StepAlgorithm", "Kernel", "ViscoTreatment",
                "Visco", "ViscoBoundFactor", "DensityDT", "DensityDTvalue", "RigidAlgorithm"):
        node = next((n for n in root.findall(".//parameters/parameter") if n.get("key") == key), None)
        if node is not None:
            physical_parameters[f"parameter:{key}"] = node.get("value")
    return {
        "geometry_commands": ET.tostring(geometry, encoding="unicode"),
        "motion_without_file_name": motion_text,
        "physical_parameters": physical_parameters,
    }


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def selected_part_stats() -> list[dict[str, Any]]:
    values = []
    for frame in SELECTED_FRAMES:
        path = RAW_ROOT / f"Part_{frame:04d}.bi4"
        # Stat only: preparation must not read the native payload.  The parent
        # v4 guard hashes these deferred files before running the worker.
        values.append({
            "frame": frame,
            "path": str(path.resolve()),
            "exists": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else None,
            "mtime_ns": path.stat().st_mtime_ns if path.is_file() else None,
            "sha256": "PARENT_V4_GUARD_REQUIRED_BEFORE_DISPATCH",
        })
    return values


def path_list(base_request: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    # Preserve the exact input closure and hashes already consumed by the
    # source-bound SaveDt request.  New metadata/code are content-hashed here;
    # selected Part payloads are explicitly deferred to the parent guard.
    paths = [Path(value).resolve() for value in base_request.get("input_files", [])]
    hashes = {str(Path(key).resolve()): value for key, value in base_request.get("input_hashes", {}).items()}
    additions = [
        WORKER.resolve(),
        DECODER_CPP.resolve(),
        PYTHON.resolve(),
        PAIR_REQUEST.resolve(),
        PAIR_AUDIT.resolve(),
        RECEIPT.resolve(),
        RUNPARTS.resolve(),
        RUNOUT.resolve(),
        OVERLAY_XML.resolve(),
        DTALL.resolve(),
        DTINFO.resolve(),
        RAW_ROOT / "PartInfo.ibi4",
        RAW_ROOT / "PartOut_000.obi4",
        DECODER.resolve(),
    ]
    seen = {str(path) for path in paths}
    for path in additions:
        path = path.resolve()
        if str(path) not in seen:
            paths.append(path)
            seen.add(str(path))
        hashes[str(path)] = sha256_file(path)
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        if str(path) not in hashes:
            raise ValueError(f"base request has no input hash for {path}")
    return [str(path) for path in paths], hashes


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    base = load_json(PAIR_REQUEST)
    receipt = load_json(RECEIPT)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("F4 same-CFL source receipt is not completed")
    if base.get("physical_case_id") != "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000":
        raise ValueError("unexpected F4 physical identity in predecessor request")
    actual_xml = xml_metadata(OVERLAY_XML)
    source_xml = xml_metadata(GENERATED_XML)
    if actual_xml["particles"] != EXPECTED_PARTICLE_COUNT or actual_xml["fluid_particle_count"] != EXPECTED_FLUID_COUNT:
        raise ValueError("F4 effective XML counts do not match source-bound request")
    if actual_xml["dp_m"] != source_xml["dp_m"] or actual_xml["massfluid_kg"] != source_xml["massfluid_kg"]:
        raise ValueError("SaveDt overlay changed particle resolution or mass")
    geometry = canonical_geometry_and_motion(GENERATED_XML)
    overlay_geometry = canonical_geometry_and_motion(OVERLAY_XML)
    if geometry != overlay_geometry:
        raise ValueError("SaveDt overlay changed physical geometry/motion/control semantics")
    input_files, input_hashes = path_list(base)
    launch_commit = git_head()
    command = [
        str(PYTHON), str(WORKER),
        "--raw-root", str(RAW_ROOT),
        "--runparts", str(RUNPARTS),
        "--generated-xml", str(OVERLAY_XML),
        "--decoder", str(DECODER),
        "--output", "{attempt_root}/observer/f4_s1_dp0_selected_physical_observer.json",
        "--scratch-root", "{attempt_root}/scratch/bi4_decode",
        "--expected-frame-count", str(EXPECTED_FRAME_COUNT),
        "--expected-final-time-s", repr(EXPECTED_FINAL_TIME),
        "--final-time-tolerance-s", "1e-12",
        "--frames", *(str(value) for value in SELECTED_FRAMES),
        "--query-times", *(repr(value) for value in QUERY_TIMES),
    ]
    selected_stats = selected_part_stats()
    selected_bytes = sum(int(item["bytes"] or 0) for item in selected_stats)
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F4",
        "case_id": "F4_S1_DP0_SAME_CFL_SELECTED_PHYSICAL_OBSERVER",
        "physical_case_id": base["physical_case_id"],
        "attempt_id": "f4-s1-dp0-same-cfl-selected-physical-observer-root-001",
        "kind": "cpu",
        "qualification_stage": "stage2_selected_native_field_observer_pending_parent_cpu_guard",
        "cpu_task_kind": "conversion",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "estimated_peak_memory_bytes": 384 * 1024 * 1024,
        "worktree_root": str(REPO),
        "cwd": str(REPO),
        "command": command,
        "candidate_solver_receipt": str(RECEIPT),
        "candidate_solver_receipt_sha256": sha256_file(RECEIPT),
        "source_binding": {
            "schema": "ds02.stage2.f4-physical-observer-binding.v1",
            "sentinel_id": "F4-S1",
            "family_id": "F4",
            "physical_case_id": base["physical_case_id"],
            "grid": "original_dp0p010000",
            "cfl_mode": "same_cfl",
            "source_role": "completed F4-S1 original-grid same-CFL SaveDt native run",
            "effective_solver_xml": record(OVERLAY_XML),
            "physical_source_xml": record(GENERATED_XML),
            "source_gencase_receipt": record(GENCASE_RECEIPT),
            "source_gencase_bi4": record(GENERATED_BI4),
            "solver_receipt": record(RECEIPT),
            "runparts": record(RUNPARTS),
            "runout": record(RUNOUT),
            "source_window_s": [0.0, EXPECTED_FINAL_TIME],
            "nominal_cli_tmax_s": EXPECTED_FINAL_TIME,
            "frame_count": EXPECTED_FRAME_COUNT,
            "particle_count": EXPECTED_PARTICLE_COUNT,
            "fluid_particle_count": EXPECTED_FLUID_COUNT,
            "particle_type_semantics": "worker reads exact XML begin/count blocks; no F2 type/schema reuse",
            "mass_semantics": {
                "fluid": "native fluid sample mass = count * XML massfluid",
                "boundary": "native boundary sample mass = count * XML massbound when declared",
                "continuum": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
                "rigid_body": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SUM",
                "xml_rigid_declarations": actual_xml,
            },
            "save_dt_metadata": {
                "dtall": record(DTALL),
                "dtinfo": record(DTINFO),
                "row_semantics": "text-only source audit; DtAllInfo is not a full field trace",
            },
            "physical_geometry_motion_overlay_identity": {
                "source_geometry_hash": hash_text(geometry["geometry_commands"]),
                "overlay_geometry_hash": hash_text(overlay_geometry["geometry_commands"]),
                "source_motion_hash": hash_text(geometry["motion_without_file_name"]),
                "overlay_motion_hash": hash_text(overlay_geometry["motion_without_file_name"]),
                "status": "PASS_ONLY_LOGGING_SAVEDT_OVERLAY",
            },
        },
        "observer_scope": {
            "selected_frames": SELECTED_FRAMES,
            "query_times_s": QUERY_TIMES,
            "query_policy": "derive exact/bracketed status from RunPARTs actual saved times; no frame-index assumptions or extrapolation",
            "decoded_fields": ["Idp", "Pos/Posd", "Vel", "Rhop"],
            "observables": ["identity", "position", "velocity", "density", "sample mass", "fluid centroid", "fluid mean velocity", "fluid kinetic energy"],
            "raw_field_digest": "worker computes selected decoded-array digest; full native tree digest is not claimed",
            "typed_conversion": "NOT_PERFORMED",
            "hdf5": "NOT_READ_OR_CREATED",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "selected_payload_inputs": {
            "records": selected_stats,
            "bytes_estimate": selected_bytes,
            "hash_policy": "parent v4 guard must content-hash selected Part files before dispatch; preparation did stat only",
            "worker_sha_policy": "worker records per-selected-Part SHA after read",
            "full_tree_hash": "NOT_COMPUTED_BY_PREPARATION_OR_WORKER",
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "consumed_runtime": str(RUNTIME_V2),
            "launch_commit": launch_commit,
            "cpu_parent_binding": "required",
            "cpu_only": True,
            "gpu_uuid": "NONE",
            "gpu_uuid_authorization": "none",
            "protected_external_gpu": PROTECTED_GPU,
            "storage_reservation_basis": "selected decoder scratch plus JSON; immutable source remains in place",
            "estimated_raw_payload_read_bytes": selected_bytes,
            "estimated_cpu_core_hours": 1 * 1800 / 3600.0,
            "solver_launch": "forbidden",
        },
        "scope": {
            "sentinel_id": "F4-S1",
            "physical_case_id": base["physical_case_id"],
            "matched_grid": "original dp=0.01 source grid",
            "full_physical_window_retained_in_source": True,
            "selected_field_observer_only": True,
            "solver_started_by_preparation": False,
            "full_time_hdf5_read": False,
            "source_deleted": False,
            "scientific_qualification": "UNKNOWN",
        },
        "launch_commit": launch_commit,
        "launch_disabled": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "primary_gpu_dispatch_required": False,
        "dispatch_status": "PENDING_PARENT_CPU_GUARD_REVIEW",
        "do_not_execute_from_preparation_worktree": True,
        "foreign_process_protection_required": True,
    }
    report = {
        "schema": SCHEMA,
        "status": "PREPARED_LAUNCH_DISABLED_NOT_RUN",
        "current_head": launch_commit,
        "request": {"path": str(REQUEST_PATH.resolve()), "case_id": request["case_id"], "attempt_id": request["attempt_id"]},
        "source": {
            "physical_xml": record(GENERATED_XML),
            "effective_xml": record(OVERLAY_XML),
            "solver_receipt": record(RECEIPT),
            "runparts": record(RUNPARTS),
            "runout": record(RUNOUT),
            "frame_count": EXPECTED_FRAME_COUNT,
            "particle_count": EXPECTED_PARTICLE_COUNT,
            "fluid_particle_count": EXPECTED_FLUID_COUNT,
        },
        "selected_frames": selected_stats,
        "planned_queries_s": QUERY_TIMES,
        "planned_fields": ["Idp", "Pos/Posd", "Vel", "Rhop"],
        "planned_cost": {
            "selected_payload_bytes_stat_only": selected_bytes,
            "estimated_storage_bytes": request["estimated_storage_bytes"],
            "cpu_threads": request["cpu_threads"],
            "max_wall_seconds": request["max_wall_seconds"],
            "hdf5_read": False,
            "solver_started": False,
        },
        "unknown_until_worker": ["decoded field values", "query bracket observer values", "physical/scientific qualification"],
    }
    return request, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        raise SystemExit("use --prepare; outputs refuse overwrite")
    request, report = build()
    atomic_json(REQUEST_PATH, request)
    atomic_json(REPORT_PATH, report)
    print(json.dumps({"status": report["status"], "request": str(REQUEST_PATH), "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
