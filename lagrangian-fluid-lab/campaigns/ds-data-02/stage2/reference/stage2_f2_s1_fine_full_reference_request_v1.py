#!/usr/bin/env python3
"""Prepare the F2-S1 dp=0.00855 full-window reference request.

This is a forward-only amendment to the consumed three-case canary request.
It keeps the exact generated candidate XML/BI4/GenCase receipt and motion
dependency, corrects the solver CLI ``tmax`` to the registered full-window
float (rather than a shortened decimal), and adds a source/material closure
sidecar.  The sidecar reports total and per-MK initial sample mass without
rescaling particles and keeps all scientific qualification UNKNOWN.

The builder reads small XML/JSON metadata and reuses already recorded input
hashes from the predecessor request.  It does not read HDF5, native solver
frames, or launch a solver.
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


SCHEMA = "ds02.stage2.f2-s1-fine-full-reference-request.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
BASE_REQUEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-full-window-canary-v1/f2_s1_fine_dp000855_same_cfl_dense.json"
SOURCE_REQUEST_BUILDER = REFERENCE / "stage2_full_window_canary_request_v1.py"
CURRENT = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
CANONICAL = REFERENCE / "f2_s1_effective_condition_canonical_v2.json"
MATERIAL_SIDECAR = REFERENCE / "f2_s1_full401_effective_condition_material_sidecar_v3.json"
CONTROL_SIDECAR = REFERENCE / "f2_s1_full_cfd_canary_control_semantics_v3.json"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
GRAPH = REFERENCE / "stage2_minimal14_study_graph_v2.json"
SOLVER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64")
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
OUTPUT_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f2-s1-fine-full-reference-v1"
REQUEST_PATH = OUTPUT_DIR / "f2_s1_fine_dp00855_same_cfl_dense_t4.json"
CLOSURE_PATH = REFERENCE / "f2_s1_fine_dp00855_source_material_closure_v1.json"
REPORT_PATH = REFERENCE / "stage2_f2_s1_fine_full_reference_binding_v1.json"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
SENTINEL_ID = "F2-S1"
TMAX = 4.000007783879406
TOUT = 0.005
EXPECTED_FRAMES = 802
SOURCE_SAMPLE_MASS_KG = 21.114
WHOLE_INITIAL_MATERIAL_FRACTION = 0.03
TARGET_MASS_FRACTION = 0.01
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
    value: dict[str, Any] = {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
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
    definition = root.find(".//geometry/definition")
    constants = root.find(".//constants")
    particles = root.find(".//particles")
    fluid_blocks: list[dict[str, Any]] = []
    if particles is not None:
        for node in particles:
            if node.tag.rsplit("}", 1)[-1].lower() != "fluid" or node.get("mkfluid") is None:
                continue
            fluid_blocks.append({
                "mkfluid": int(node.get("mkfluid", "-1")),
                "begin": int(node.get("begin", "-1")),
                "count": int(node.get("count", "-1")),
            })
    massfluid = None
    h_m = None
    if constants is not None and constants.find("massfluid") is not None:
        massfluid = float(constants.find("massfluid").get("value", "nan"))
    if constants is not None and constants.find("h") is not None:
        h_m = float(constants.find("h").get("value", "nan"))
    parameters: dict[str, Any] = {}
    for node in root.findall(".//parameters/parameter"):
        key, value = node.get("key"), node.get("value")
        if key and value is not None:
            try:
                parameters[key] = float(value)
            except ValueError:
                parameters[key] = value
    cfl = root.find(".//constants/cflnumber")
    return {
        "file": record(path),
        "dp_m": float(definition.get("dp")) if definition is not None and definition.get("dp") else None,
        "cfl": float(cfl.get("value")) if cfl is not None and cfl.get("value") else None,
        "parameters": parameters,
        "particles": int(particles.get("np")) if particles is not None and particles.get("np") else None,
        "fluid_blocks": fluid_blocks,
        "fluid_particle_count": sum(int(item["count"]) for item in fluid_blocks),
        "massfluid_kg": massfluid,
        "h_m": h_m,
        "sample_mass_kg": (sum(int(item["count"]) for item in fluid_blocks) * massfluid
                           if massfluid is not None else None),
    }


def canonical_sections(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    commands = root.find(".//geometry/commands")
    motion = root.find(".//casedef/motion")
    if commands is None or motion is None:
        raise ValueError(f"XML lacks geometry commands or casedef motion: {path}")
    motion_copy = ET.fromstring(ET.tostring(motion, encoding="unicode"))
    for node in motion_copy.iter():
        if node.tag.rsplit("}", 1)[-1].lower() == "file":
            node.attrib.pop("name", None)
    controls: dict[str, Any] = {}
    for key in ("gravity", "rhop0", "gamma", "coefsound", "cflnumber"):
        node = root.find(f".//constantsdef/{key}")
        if node is not None:
            controls[f"constantsdef:{key}"] = dict(sorted(node.attrib.items()))
    for key in ("Boundary", "SlipMode", "StepAlgorithm", "Kernel", "ViscoTreatment",
                "Visco", "ViscoBoundFactor", "DensityDT", "DensityDTvalue", "RigidAlgorithm"):
        node = next((n for n in root.findall(".//parameters/parameter") if n.get("key") == key), None)
        if node is not None:
            controls[f"parameter:{key}"] = node.get("value")
    return {
        "geometry_commands": ET.tostring(commands, encoding="unicode"),
        "motion_without_file_name": ET.tostring(motion_copy, encoding="unicode"),
        "physical_controls": controls,
    }


def _fluid_rows(source: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    source_by_mk = {item["mkfluid"]: item for item in source["fluid_blocks"]}
    candidate_by_mk = {item["mkfluid"]: item for item in candidate["fluid_blocks"]}
    if set(source_by_mk) != set(candidate_by_mk):
        raise ValueError(f"source/candidate mkfluid sets differ: {set(source_by_mk)} vs {set(candidate_by_mk)}")
    source_mass_per = float(source["massfluid_kg"])
    candidate_mass_per = float(candidate["massfluid_kg"])
    rows: list[dict[str, Any]] = []
    for mk in sorted(source_by_mk):
        source_mass = int(source_by_mk[mk]["count"]) * source_mass_per
        candidate_mass = int(candidate_by_mk[mk]["count"]) * candidate_mass_per
        delta = candidate_mass - source_mass
        local_pct = delta / source_mass * 100.0 if source_mass else None
        whole_fraction = abs(delta) / SOURCE_SAMPLE_MASS_KG
        rows.append({
            "mkfluid": mk,
            "source": {"count": source_by_mk[mk]["count"], "mass_kg": source_mass},
            "candidate": {"count": candidate_by_mk[mk]["count"], "mass_kg": candidate_mass},
            "delta_kg": delta,
            "relative_to_source_mk_pct": local_pct,
            "absolute_delta_fraction_of_source_whole_initial": whole_fraction,
            "absolute_delta_percentage_points_of_source_whole_initial": whole_fraction * 100.0,
            "whole_initial_3pct_status": "PASS" if whole_fraction <= WHOLE_INITIAL_MATERIAL_FRACTION else "HARD_FAIL",
            "local_mk_percentage_status": "DIAGNOSTIC_ONLY",
        })
    return rows


def build_closure(base: dict[str, Any]) -> dict[str, Any]:
    source_xml_path = Path(base["source_binding"]["identity"]["current_source_xml"]["file"]["path"])
    candidate = base["source_binding"]["candidate_gencase"]
    candidate_xml_path = Path(candidate["generated_xml"]["file"]["path"])
    candidate_motion_path = Path(candidate["motion"]["path"])
    source = xml_metadata(source_xml_path)
    candidate_meta = xml_metadata(candidate_xml_path)
    source_sections = canonical_sections(source_xml_path)
    candidate_sections = canonical_sections(candidate_xml_path)
    motion_sha = sha256_file(candidate_motion_path)
    canonical = load_json(CANONICAL)
    canonical_payload_sha = canonical.get("canonical_payload_sha256")
    if not isinstance(canonical_payload_sha, str) or len(canonical_payload_sha) != 64:
        raise ValueError("canonical condition sidecar has no payload SHA")
    per_mk = _fluid_rows(source, candidate_meta)
    total_delta = float(candidate_meta["sample_mass_kg"] - source["sample_mass_kg"])
    total_fraction = abs(total_delta) / float(source["sample_mass_kg"])
    controls_equal = source_sections["physical_controls"] == candidate_sections["physical_controls"]
    geometry_equal = source_sections["geometry_commands"] == candidate_sections["geometry_commands"]
    motion_equal = source_sections["motion_without_file_name"] == candidate_sections["motion_without_file_name"]
    expected_motion_sha = canonical["canonical_payload"]["motion_control"]["motion_sha256"]
    return {
        "schema": "ds02.stage2.f2-s1-fine-source-material-closure.v1",
        "status": "PREPARED_METADATA_ONLY_SCIENTIFIC_UNKNOWN",
        "identity": {
            "sentinel_id": SENTINEL_ID,
            "family_id": "F2",
            "physical_case_id": PHYSICAL_CASE_ID,
            "candidate_case_id": base["case_id"],
            "candidate_attempt_id": base["attempt_id"],
        },
        "source": {
            "current_xml": record(source_xml_path),
            "candidate_generated_xml": record(candidate_xml_path),
            "candidate_generated_bi4": {
                **record(Path(candidate["generated_bi4"]["path"]), content_hash=False),
                "producer_declared_sha256": candidate["generated_bi4"].get("sha256"),
                "hash_policy": "predecessor request/GenCase receipt hash; this preparation did not reread BI4 payload",
            },
            "candidate_gencase_receipt": record(Path(base["candidate_gencase_receipt"])),
            "candidate_motion": record(candidate_motion_path),
            "canonical_condition": record(CANONICAL),
            "material_sidecar": record(MATERIAL_SIDECAR),
            "control_semantics_sidecar": record(CONTROL_SIDECAR),
        },
        "continuous_geometry_control_closure": {
            "geometry_commands_equal": geometry_equal,
            "motion_xml_semantics_equal_ignoring_file_name": motion_equal,
            "physical_solver_control_values_equal": controls_equal,
            "motion_sha256_candidate": motion_sha,
            "motion_sha256_canonical_expected": expected_motion_sha,
            "motion_sha_equal_canonical": motion_sha == expected_motion_sha,
            "status": "PASS_SOURCE_BOUND_METADATA" if geometry_equal and motion_equal and controls_equal and motion_sha == expected_motion_sha else "UNKNOWN_OR_FAIL",
            "limitations": [
                "generated particle lattice phase/positions are not proven equivalent by XML alone",
                "candidate particle count, dp, h, massfluid, and block counts are intentional numerical-resolution fields",
                "full solver output/observer calibration remains pending",
            ],
        },
        "intentional_resolution_variations": {
            "source_dp_m": source["dp_m"],
            "candidate_dp_m": candidate_meta["dp_m"],
            "source_h_m": source["h_m"],
            "candidate_h_m": candidate_meta["h_m"],
            "source_massfluid_kg": source["massfluid_kg"],
            "candidate_massfluid_kg": candidate_meta["massfluid_kg"],
            "source_fluid_particle_count": source["fluid_particle_count"],
            "candidate_fluid_particle_count": candidate_meta["fluid_particle_count"],
            "particle_mass_rescale": False,
            "continuous_geometry_or_motion_mutation": False,
        },
        "mass_audit": {
            "source_whole_initial_sample_mass_kg": source["sample_mass_kg"],
            "candidate_whole_initial_sample_mass_kg": candidate_meta["sample_mass_kg"],
            "delta_kg": total_delta,
            "absolute_relative_difference": total_fraction,
            "absolute_relative_difference_pct": total_fraction * 100.0,
            "total_1pct_gate": "PASS_TARGET_1PCT_DIAGNOSTIC_ONLY" if total_fraction <= TARGET_MASS_FRACTION else "HARD_FAIL",
            "per_mkfluid": per_mk,
            "whole_initial_material_budget": {
                "denominator_kg": SOURCE_SAMPLE_MASS_KG,
                "threshold_fraction": WHOLE_INITIAL_MATERIAL_FRACTION,
                "unit": "fraction of exact source whole initial mass; percentage_points=fraction*100",
                "status": "PASS_DIAGNOSTIC_ONLY" if all(item["whole_initial_3pct_status"] == "PASS" for item in per_mk) else "HARD_FAIL_DIAGNOSTIC",
                "scientific_qualification": "UNKNOWN",
            },
            "local_per_mk_relative_values": "diagnostic only; not an alternate acceptance gate",
            "no_mass_rescale": True,
        },
        "canonical_condition": {
            "payload_sha256": canonical_payload_sha,
            "numerical_recipe_sha256": canonical.get("numerical_recipe_sha256"),
            "observation_window_s": canonical.get("observation_scope", {}).get("time_window_s"),
            "condition_hash_excludes": canonical.get("identity_scope", {}).get("excluded_from_condition_hash"),
        },
        "scope": {
            "reads_hdf5": False,
            "reads_native_solver_payload": False,
            "solver_started": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }


def add_inputs(base: dict[str, Any], closure_path: Path) -> tuple[list[str], dict[str, str]]:
    paths = [Path(item).resolve() for item in base.get("input_files", [])]
    hashes = {str(Path(key).resolve()): value for key, value in base.get("input_hashes", {}).items()}
    additions = [
        Path(__file__).resolve(),
        BASE_REQUEST.resolve(),
        SOURCE_REQUEST_BUILDER.resolve(),
        CANONICAL.resolve(),
        MATERIAL_SIDECAR.resolve(),
        CONTROL_SIDECAR.resolve(),
        CURRENT.resolve(),
        QUALITY.resolve(),
        GRAPH.resolve(),
        closure_path.resolve(),
        DISPATCH.resolve(),
        STRICT.resolve(),
        RUNTIME.resolve(),
        RUNTIME_V2.resolve(),
        SOLVER.resolve(),
    ]
    seen = {str(path) for path in paths}
    for path in additions:
        if not path.is_file():
            raise FileNotFoundError(path)
        if str(path) not in seen:
            paths.append(path)
            seen.add(str(path))
        hashes[str(path)] = sha256_file(path)
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        if str(path) not in hashes:
            raise ValueError(f"missing predecessor hash for {path}")
    return [str(path) for path in paths], hashes


def build() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    base = load_json(BASE_REQUEST)
    if base.get("family_id") != "F2" or base.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("predecessor request has wrong F2 identity")
    candidate_xml = Path(base["source_binding"]["candidate_gencase"]["generated_xml"]["file"]["path"])
    candidate_bi4 = Path(base["source_binding"]["candidate_gencase"]["generated_bi4"]["path"])
    candidate_receipt = Path(base["candidate_gencase_receipt"])
    for path in (candidate_xml, candidate_bi4, candidate_receipt):
        if not path.is_file():
            raise FileNotFoundError(path)
    receipt = load_json(candidate_receipt)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError("candidate GenCase receipt is not a successful immutable terminal receipt")
    closure = build_closure(base)
    atomic_json(CLOSURE_PATH, closure)
    input_files, input_hashes = add_inputs(base, CLOSURE_PATH)
    launch_commit = git_head()
    prefix = candidate_xml.with_suffix("")
    command = [str(SOLVER), str(prefix), "{attempt_root}/solver_output",
               f"-tmax:{TMAX:.15f}", f"-tout:{TOUT:.15f}"]
    candidate_meta = xml_metadata(candidate_xml)
    source_meta = xml_metadata(Path(base["source_binding"]["identity"]["current_source_xml"]["file"]["path"]))
    graph_cost = base.get("source_binding", {}).get("cost", {}).get("graph_row", {})
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F2",
        "case_id": "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE",
        "physical_case_id": PHYSICAL_CASE_ID,
        "attempt_id": "f2-s1-fine-full-reference-dp00855-t4-same-cfl-dense-root-001",
        "kind": "qualification",
        "qualification_stage": "stage2_source_bound_fine_full_window_reference_pending_primary_gpu_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": 7200,
        "estimated_storage_bytes": 34 * 1024**3,
        "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(REPO),
        "cwd": str(candidate_xml.parent),
        "command": command,
        "candidate_gencase_receipt": str(candidate_receipt),
        "candidate_gencase_receipt_sha256": sha256_file(candidate_receipt),
        "expected_particles": int(candidate_meta["particles"]),
        "expected_fluid_particles": int(candidate_meta["fluid_particle_count"]),
        "expected_dimension": 3,
        "expected_native_frames": EXPECTED_FRAMES,
        "physical_window_s": [0.0, TMAX],
        "save_interval_s": TOUT,
        "source_binding": {
            "schema": "ds02.stage2.f2-s1-fine-full-reference-binding.v1",
            "sentinel_id": SENTINEL_ID,
            "family_id": "F2",
            "physical_case_id": PHYSICAL_CASE_ID,
            "source_identity": {
                "current_source_xml": base["source_binding"]["identity"]["current_source_xml"],
                "current_source_solver_receipt": base["source_binding"]["identity"]["source_solver_receipt"],
                "current_discrete_sample_mass_kg": source_meta["sample_mass_kg"],
                "current_continuous_region_mass_kg": 18.876,
                "current_mass_semantics": "discrete Stage1 sample target and continuous box mass remain separate",
            },
            "candidate_gencase": base["source_binding"]["candidate_gencase"],
            "source_material_closure": record(CLOSURE_PATH),
            "canonical_condition": record(CANONICAL),
            "material_budget_sidecar": record(MATERIAL_SIDECAR),
            "control_semantics_sidecar": record(CONTROL_SIDECAR),
            "motion_binding": {
                "sha256": closure["continuous_geometry_control_closure"]["motion_sha256_candidate"],
                "control_window_s": [0.0, 4.0],
                "initial_hold_s": [0.0, 0.5],
                "rotation_s": [0.5, 1.4],
                "rotation_duration_s": 0.9,
                "rotation_final_angle_deg": -105.0,
                "post_rotation_hold_s": [1.4, 4.0],
                "label_policy": "ROT090 is a historical case label; do not interpret as 90 degrees",
            },
            "continuous_geometry_control": closure["continuous_geometry_control_closure"],
            "intentional_resolution_fields": closure["intentional_resolution_variations"],
            "mass_audit": closure["mass_audit"],
            "physical_qualification": "UNKNOWN until parent solver receipt, actual dt/clamp evidence, field observer and consumer calibration",
        },
        "controls": {
            "source_candidate_xml": candidate_meta["parameters"],
            "xml_cfl": candidate_meta["cfl"],
            "xml_timemax_s": candidate_meta["parameters"].get("TimeMax"),
            "xml_timeout_s": candidate_meta["parameters"].get("TimeOut"),
            "xml_dt_min_s": candidate_meta["parameters"].get("DtMin"),
            "xml_dt_fixed_s": candidate_meta["parameters"].get("DtFixed"),
            "effective_cli_tmax_s": TMAX,
            "effective_cli_tout_s": TOUT,
            "actual_dt_sequence": "UNKNOWN_UNTIL_PARENT_GUARDED_SOLVER",
            "dt_clamp_events": "UNKNOWN_UNTIL_PARENT_GUARDED_SOLVER",
            "savedt_or_dtallinfo": "NOT_REQUESTED_IN_THIS_REFERENCE_RUN; no dt sequence inferred from CFL or saved output",
        },
        "output_plan": {
            "native_raw": "retain every native Part frame over exact [0,4.000007783879406] s window",
            "native_source_role": "immutable primary scientific arrays; no deletion or favorable-subset pruning",
            "dense_output_cadence_s": TOUT,
            "typed_query_anchors": {"times_s": [0.0, 1.0, 2.0, 3.0, 4.0], "status": "DEFERRED_AFTER_TERMINAL_RAW_RECEIPT"},
            "full_typed_h5": "DEFERRED_SEPARATE_REQUEST; not created by this solver request",
            "lossless_archive": "DEFERRED_FULL_WINDOW_ROUNDTRIP; two-frame ratio is diagnostic only",
            "actual_time_policy": "consumer uses RunPARTs/typed time axis; no frame-number hardcoding or endpoint extrapolation",
        },
        "cost": {
            "predecessor_graph_row": graph_cost,
            "source_scaled_runtime_proxy": "from predecessor request only; not a wall upper bound",
            "raw_reserved_bytes_from_predecessor": base.get("estimated_storage_bytes"),
            "request_storage_reservation_bytes": 34 * 1024**3,
            "typed_full_h5": "not included in this run",
            "source_output_protection": "new attempt only; all existing source/consumer bytes immutable",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "consumed_runtime": str(RUNTIME_V2),
            "launch_commit": launch_commit,
            "cpu_parent_binding": "required",
            "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER",
            "protected_external_gpu": PROTECTED_GPU,
            "solver_launch": "root only; preparation cannot launch",
            "estimated_gpu_hours": "UNKNOWN_UNTIL_GUARDED_RECEIPT; predecessor scaling is planning proxy only",
        },
        "scope": {
            "grid": "fine dp=0.00855",
            "cfl_mode": "same_cfl source cfl=0.2",
            "full_physical_window_retained": True,
            "initial_mass_gate": "PASS_TARGET_1PCT_DIAGNOSTIC_ONLY",
            "whole_initial_material_budget": closure["mass_audit"]["whole_initial_material_budget"],
            "continuous_geometry_control_status": closure["continuous_geometry_control_closure"]["status"],
            "solver_started": False,
            "full_time_hdf5_read_in_preparation": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        "launch_commit": launch_commit,
        "launch_disabled": True,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "primary_gpu_dispatch_required": True,
        "dispatch_status": "PENDING_PRIMARY_RESOURCE_AND_SCIENTIFIC_REVIEW",
        "do_not_execute_from_preparation_worktree": True,
        "foreign_process_protection_required": True,
    }
    report = {
        "schema": SCHEMA,
        "status": "PREPARED_LAUNCH_DISABLED_NOT_RUN",
        "current_head": launch_commit,
        "request": {"path": str(REQUEST_PATH.resolve()), "case_id": request["case_id"], "attempt_id": request["attempt_id"]},
        "closure": record(CLOSURE_PATH),
        "candidate": {
            "generated_xml": record(candidate_xml),
            "generated_bi4": {
                **record(candidate_bi4, content_hash=False),
                "producer_declared_sha256": base["source_binding"]["candidate_gencase"]["generated_bi4"].get("sha256"),
                "hash_policy": "predecessor request/GenCase receipt hash; no new BI4 reread",
            },
            "gencase_receipt": record(candidate_receipt),
            "sample_mass_kg": candidate_meta["sample_mass_kg"],
            "fluid_particles": candidate_meta["fluid_particle_count"],
        },
        "full_window": {"start_s": 0.0, "end_s": TMAX, "cadence_s": TOUT, "expected_frames": EXPECTED_FRAMES},
        "resource": {"estimated_storage_bytes": request["estimated_storage_bytes"], "max_wall_seconds": request["max_wall_seconds"], "solver_started": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    return request, closure, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        raise SystemExit("use --prepare; generated outputs refuse overwrite")
    request, _closure, report = build()
    atomic_json(REQUEST_PATH, request)
    atomic_json(REPORT_PATH, report)
    print(json.dumps({"status": report["status"], "request": str(REQUEST_PATH), "closure": str(CLOSURE_PATH), "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
