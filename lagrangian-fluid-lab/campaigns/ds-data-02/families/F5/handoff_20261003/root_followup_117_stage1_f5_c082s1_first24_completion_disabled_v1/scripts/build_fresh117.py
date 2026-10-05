#!/usr/bin/env python3
"""Build the F5 fresh117 first-24 source-only promotion pack.

The sixteen candidates preserve the C082S1 analytic closed bed and tank XML
and add a bounded 4-by-4 amplitude/time control grid that is disjoint from
A080/A120 and fresh110's six controls.  A registered CPU worker will
transform the 641-row motion table later.  This builder never opens or hashes
the source DAT, generated BI4, H5, CSV, VTK, or solver output.  Every motion,
GenCase, initial QA, short native, bed audit, and full native request is
disabled.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
FRESH109 = PKG.parent / "root_followup_109_stage1_f5_c082s1_actual_bed_full801_disabled_v1"
FRESH110 = PKG.parent / "root_followup_110_stage1_f5_c082s1_six_forcing_conditions_disabled_v1"
FRESH115 = PKG.parent / "root_followup_115_stage1_f5_c082s1_root575_full801_downstream_disabled_v1"
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
FAMILY = "F5"
BASE_DEFINITION = FRESH110 / "candidates/M100_T110/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M100_T110_Def.xml"
BASE_PHYSICAL = FRESH115 / "bindings/A080-full801-physical-binding.json"
BASE_BED = FRESH115 / "bindings/A080-full801-bed-audit-binding.json"
BASE_ATTESTATION = FRESH109 / "metadata/A080-actual-native-typed-attestation.json"
BASE_MOTION_WORKER = PKG / "workers/transform_motion.py"
GENCASE_WORKER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_native_source_preflight_tools_003/gencase.py"
)
RUNTIME = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
)
STRICT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"
)
PYTHON = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/.venv/bin/python"
)
ROOT230 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_native_home_floor_eight_solver_dispatch_230"
)
ROOT230_POLICY = ROOT230 / "root_native_home_floor_inventory_policy.py"
ROOT230_LAUNCH = ROOT230 / "launch.py"
RESOURCE = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"
)
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)

STATIC_SUFFIXES = {".json", ".py", ".xml", ".md", ".txt", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
ALLOWED_AMPLITUDES = (Decimal("0.8"), Decimal("1.0"), Decimal("1.2"))
ALLOWED_TIME_SCALES = (Decimal("0.9"), Decimal("1.1"))
FULL_TMAX = Decimal("26.0")
TOUT = Decimal("0.02")
FULL_FRAMES = 1301
SHORT_TMAX = Decimal("1.0")
SHORT_FRAMES = 51
PARENT_INVENTORY = PKG / "metadata/parent-condition-inventory.json"
BASE_MOTION = "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_coarse-clip-direction-fix-gencase-050/prepared/assets/f5_compact_packet_motion.dat"
BASE_MOTION_SHA = "51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a"
GENCASE_SHA = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
ROOT230_LAUNCH_SHA = "7f703fb94e17c2e2800873f4fcc021f9cd5f8201076afd8e10e3bc6a2d03396e"
ROOT230_RESERVATION_SHA = "46e62ea197862a833797556d09350126b3632b2e3b1d496d08816ee42f7abecf"

SPECS = tuple(
    (f"M{amp:03d}_T{time:03d}", Decimal(amp) / Decimal(100), Decimal(time) / Decimal(100))
    for amp in (85, 95, 105, 115)
    for time in (80, 90, 100, 120)
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    require(path.suffix.lower() in STATIC_SUFFIXES, f"source-only hash forbidden for {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def dec_text(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") if value % 1 else format(value, "f").split(".")[0]


def tag_to_candidate(tag: str) -> dict[str, Any]:
    amp = Decimal(tag[1:4]) / Decimal(100)
    time_scale = Decimal(tag[6:9]) / Decimal(100)
    motion_end = Decimal(16) * time_scale
    return {
        "tag": tag,
        "amplitude": amp,
        "time_scale": time_scale,
        "motion_end": motion_end,
        "candidate_id": f"C082S1_MOTION_{tag}",
        "condition_id": f"F5_RUNUP_DP020_C082S1_MOTION_{tag}_117",
        "physical_case_id": f"F5_COMPACT_RUNUP_RECOVERY_C082S1_{tag}",
        "control_recipe_id": f"F5_CTRL_COMPACT_PACKET_{tag}_TIME_SCALED_117",
        "motion_file": f"f5_c082s1_motion_{tag.lower()}.dat",
        "motion_attempt": f"root-stage1-f5-c082s1-{tag.lower()}-motion-transform-117",
        "gencase_attempt": f"root-stage1-f5-c082s1-{tag.lower()}-genuine-gencase-117",
        "qa_attempt": f"root-stage1-f5-c082s1-{tag.lower()}-initial-placement-mk50-117",
        "short_attempt": f"root-stage1-f5-c082s1-{tag.lower()}-short-native-qualification-117",
        "short_bed_attempt": f"root-stage1-f5-c082s1-{tag.lower()}-short-dynamic-bed-audit-117",
        "full_attempt": f"root-stage1-f5-c082s1-{tag.lower()}-full-native-qualification-117",
        "full_bed_attempt": f"root-stage1-f5-c082s1-{tag.lower()}-full-dynamic-bed-audit-117",
    }


def root230_metadata() -> dict[str, Any]:
    prior = load(FRESH109 / "requests/A080-full801-native-request.json")
    resource = load(RESOURCE)
    return {
        "root_inventory_policy_source": str(ROOT230_POLICY),
        "root_inventory_policy_source_sha256": ROOT230_POLICY_SHA,
        "root_actual_launch_source": str(ROOT230_LAUNCH),
        "root_actual_launch_source_sha256": ROOT230_LAUNCH_SHA,
        "root_effective_reservation_function_sha256": ROOT230_RESERVATION_SHA,
        "root_dataset_inventory_profile": prior.get("root_dataset_inventory_profile"),
        "root_gpu_selection_profile": prior.get("root_gpu_selection_profile"),
        "root_solver_concurrency_cap": prior.get("root_solver_concurrency_cap", 8),
        "root_live_uuid_inventory": None,
        "root_shared_gpu_lease": None,
        "root_full_launch_approval": None,
        "root_live_uuid_required_before_enable": True,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "resource_window": resource,
    }


def make_definition(spec: dict[str, Any]) -> tuple[Path, str]:
    tag = spec["tag"]
    text = BASE_DEFINITION.read_text(encoding="utf-8")
    text = text.replace("fresh110 C082S1_MOTION_M100_T110", f"fresh117 C082S1_MOTION_{tag}")
    text = text.replace("f5_c082s1_motion_m100_t110.dat", spec["motion_file"])
    motion_end = dec_text(spec["motion_end"])
    text = text.replace('finish="17.6"', f'finish="{motion_end}"')
    text = text.replace('duration="17.6"', f'duration="{motion_end}"')
    text = text.replace('end="24"', f'end="{dec_text(FULL_TMAX)}"')
    text = text.replace('value="24.0"', f'value="{dec_text(FULL_TMAX)}"')
    text = text.replace(
        "<!-- fresh117 C082S1_MOTION_M100_T110: only the prescribed motion asset is transformed at runtime; geometry and initial fill are unchanged. -->",
        f"<!-- fresh117 C082S1_MOTION_{tag}: same analytic bed/initial geometry; bounded amplitude/time motion asset is root-produced. -->",
    )
    text = text.replace("<motion>", f"<!-- motion table ends at {motion_end}s; full event window is 0..{dec_text(FULL_TMAX)}s. -->\n    <motion>")
    root = ET.fromstring(text)
    require(root.tag == "case", f"{tag}: DefXML root")
    path = PKG / "candidates" / tag / f"{CASE}_{tag}_Def.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, sha(path)


def make_owner(spec: dict[str, Any], definition: Path, definition_sha: str, base_physical: dict[str, Any]) -> tuple[Path, str, dict[str, Any]]:
    tag = spec["tag"]
    parameters = copy.deepcopy(base_physical["parameters"])
    parameters["piston_motion"].update({
        "amplitude_scale": float(spec["amplitude"]),
        "time_scale": float(spec["time_scale"]),
        "duration_s": float(spec["motion_end"]),
        "asset_relative_name": f"assets/{spec['motion_file']}",
        "transform_semantics": "global table-time scaling about t=0 plus x amplitude scaling; no interpolation by source preparation",
    })
    basis = {
        "schema": "ds02.f5.c082s1.first24-canonical-owner-basis.fresh117.v1",
        "candidate_id": spec["candidate_id"],
        "physical_case_id": spec["physical_case_id"],
        "condition_id": spec["condition_id"],
        "geometry_family_id": base_physical["geometry_family_id"],
        "geometry": copy.deepcopy(base_physical["geometry"]),
        "controls": copy.deepcopy(base_physical["controls"]),
        "parameters": parameters,
        "gravity_m_s2": copy.deepcopy(base_physical["gravity_m_s2"]),
        "density_kg_m3": base_physical["density_kg_m3"],
        "dp_m": 0.02,
        "dimension": 3,
        "amplitude_scale": float(spec["amplitude"]),
        "time_scale": float(spec["time_scale"]),
        "motion_rows": 641,
        "motion_source_endpoint_s": [0.0, 16.0],
        "motion_output_endpoint_s": [0.0, float(spec["motion_end"])],
        "full_event_window_s": [0.0, float(FULL_TMAX)],
        "tout_s": 0.02,
        "source_definition_sha256": definition_sha,
        "base_motion_sha256": BASE_MOTION_SHA,
    }
    physical_hash = json_sha(basis)
    owner = {
        "schema": "ds02.f5.c082s1.first24-canonical-owner.fresh117.v1",
        "family_id": FAMILY,
        "case_id": CASE,
        "candidate_id": spec["candidate_id"],
        "condition_id": spec["condition_id"],
        "physical_case_id": spec["physical_case_id"],
        "control_recipe_id": spec["control_recipe_id"],
        "amplitude_scale": float(spec["amplitude"]),
        "time_scale": float(spec["time_scale"]),
        "role": "new_time_amplitude_forcing_condition",
        "owner_semantics": "independent control condition over the C082S1 analytic closed bed and tank; no registry case or credit is created by source preparation",
        "geometry_source": "C082S1 solid-fluid recovery analytic closed bed, finite tank, and piston; DefXML geometry is byte-preserved except motion reference and event-window controls",
        "geometry_family_id": base_physical["geometry_family_id"],
        "mechanism_id": base_physical["mechanism_id"],
        "native_bed_mk": 50,
        "source_mkbound": 40,
        "solver_dimension": 3,
        "dp_m": 0.02,
        "density_kg_m3": 1000.0,
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "mass_rescale": False,
        "expected_counts": None,
        "counts_policy": "new GenCase producer fields are required; historical C082S1 counts are provenance only and are never copied as candidate expectations",
        "initial_state_policy": "same analytic source fluid box and closed Mk40-to-native-Mk50 bed mapping; fresh producer must independently prove UID/type/Mk/finite/3D/no-overlap/15-y-level placement",
        "source_definition": str(definition),
        "source_definition_sha256": definition_sha,
        "source_plan_physical_condition_sha256": definition_sha,
        "base_motion_path": BASE_MOTION,
        "base_motion_sha256": BASE_MOTION_SHA,
        "base_motion_sha256_provenance": "copied from prior registered C082S1 producer metadata; fresh117 source preparation did not read or rehash DAT",
        "motion_transform": {
            "worker": "workers/transform_motion.py",
            "amplitude_scale": float(spec["amplitude"]),
            "time_scale": float(spec["time_scale"]),
            "rows": 641,
            "source_time_window_s": [0.0, 16.0],
            "output_time_window_s": [0.0, float(spec["motion_end"])],
            "output_relative_name": f"assets/{spec['motion_file']}",
            "output_path": None,
            "output_sha256": None,
            "receipt": None,
        },
        "event_window": {
            "full_simulation_time_window_s": [0.0, float(FULL_TMAX)],
            "full_output_frames": FULL_FRAMES,
            "tout_s": 0.02,
            "forcing_end_s": float(spec["motion_end"]),
            "post_forcing_tail_s": float(FULL_TMAX - spec["motion_end"]),
            "reason": "full native window contains the entire transformed table and a post-forcing runup tail; this is a new simulation window, not a slice of old output",
        },
        "parameters": parameters,
        "canonical_hash_basis": basis,
        "physical_condition_sha256": physical_hash,
        "source_h5_scope": None,
        "legacy_h5_cross_resolution_claim": False,
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "source_only": True,
        "science_payloads_read_or_hashed_by_source_agent": False,
        "historical_precision_negative_retained": "Root314 exact-DP 1e-6 is preserved as numerical_precision and is not changed by this source pack",
        "historical_A_B_penetration_failures_retained": True,
    }
    path = PKG / "candidates" / tag / "owner.json"
    dump(path, owner)
    return path, sha(path), owner


def physical_binding(spec: dict[str, Any], owner_path: Path, owner_sha: str, owner: dict[str, Any], definition: Path, definition_sha: str) -> tuple[Path, str]:
    binding = copy.deepcopy(owner)
    binding.update({
        "schema": "ds-data-02.physical-binding.v1",
        "physical_binding_path": str(PKG / "bindings" / f"{spec['tag']}-physical-binding.json"),
        "physical_case_id": spec["physical_case_id"],
        "owner_source": str(owner_path),
        "owner_source_sha256": owner_sha,
        "source_definition": str(definition),
        "source_definition_sha256": definition_sha,
        "source_preparation": {
            "fresh117_source_only": True,
            "canonical_owner_and_source_plan_separate": True,
            "science_payloads_read_or_hashed": False,
            "source_only": True,
        },
    })
    path = PKG / "bindings" / f"{spec['tag']}-physical-binding.json"
    dump(path, binding)
    return path, sha(path)


def root_common() -> dict[str, Any]:
    resource = load(RESOURCE)
    resource_window = {
        "gpu_hours": resource["gpu_hours"],
        "cpu_core_hours": resource["cpu_core_hours"],
        "qualification_attempts": resource["qualification_attempts"],
        "production_attempts": resource["production_attempts"],
        "home_min_free_bytes": resource["new_limits"]["home_min_free_bytes"],
        "deadline_utc": resource["deadline_utc"],
        "launch_owner": "root",
    }
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": FAMILY,
        "case_id": CASE,
        "launch_owner": "root",
        "root_review_required": True,
        "root_dataset_inventory_profile": "root_home_floor_no_legacy_dataset_walk_native_v1",
        "root_inventory_policy_source": str(ROOT230_POLICY),
        "root_inventory_policy_source_sha256": ROOT230_POLICY_SHA,
        "root_actual_launch_source": str(ROOT230_LAUNCH),
        "root_actual_launch_source_sha256": ROOT230_LAUNCH_SHA,
        "root_effective_reservation_function_sha256": ROOT230_RESERVATION_SHA,
        "root_gpu_selection_profile": "root_live_all_idle_uuid_leased_eight_solver_v2",
        "root_solver_concurrency_cap": 8,
        "root_live_uuid_inventory": None,
        "root_shared_gpu_lease": None,
        "root_full_launch_approval": None,
        "root_live_uuid_required_before_enable": True,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "disabled": True,
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "solver_allowed": False,
        "conversion_allowed": False,
        "source_only": True,
        "arrays_allowed": False,
        "array_edit_allowed": False,
        "shared_registry_write_allowed": False,
        "production_approval": "none",
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "old_attempt_modification_forbidden": True,
        "root_review_required": True,
        "status": "disabled_until_root_review_and_actual_upstream_receipts",
        "future_output_hashes": {},
        "resource_window": resource_window,
    }


def static_closure(paths: list[str], producer_dat: bool = False) -> tuple[list[str], dict[str, str | None], dict[str, str]]:
    files: list[str] = []
    hashes: dict[str, str | None] = {}
    provenance: dict[str, str] = {}
    for raw in paths:
        if raw not in files:
            files.append(raw)
        if raw.startswith("<root-bind:"):
            hashes[raw] = None
            provenance[raw] = "Root binds this future producer input after an actual completed/0 upstream receipt"
            continue
        path = Path(raw)
        suffix = path.suffix.lower()
        if suffix == ".dat":
            require(raw == BASE_MOTION, f"unexpected DAT input {raw}")
            hashes[raw] = BASE_MOTION_SHA
            provenance[raw] = "registered prior C082S1 producer SHA; fresh117 source preparation did not read or rehash DAT"
            continue
        if suffix in SCIENCE_SUFFIXES:
            raise ValueError(f"science payload path not allowed in fresh117 static closure: {raw}")
        if suffix in STATIC_SUFFIXES:
            require(path.is_file(), f"missing static closure input {path}")
            hashes[raw] = sha(path)
            provenance[raw] = "JSON/XML/Python/text source metadata hashed by fresh117 source preparation"
        else:
            hashes[raw] = None
            provenance[raw] = "official executable or interpreter; fresh117 source preparation did not open or hash binary"
    return files, hashes, provenance


def package_sources(spec: dict[str, Any], owner_path: Path, physical_path: Path, definition: Path, binding_names: list[str]) -> list[str]:
    paths = [
        str(PYTHON), str(RUNTIME), str(STRICT), str(ROOT230_POLICY), str(ROOT230_LAUNCH), str(RESOURCE),
        str(definition), str(owner_path), str(physical_path), str(BASE_MOTION_WORKER),
    ]
    paths.extend(str(PKG / "bindings" / name) for name in binding_names)
    return paths


def write_motion_request(spec: dict[str, Any], owner_path: Path, owner_sha: str, definition: Path, definition_sha: str, physical_path: Path, physical_sha: str) -> None:
    common = root_common()
    attempt_root = "{attempt_root}"
    output = f"{attempt_root}/prepared/assets/{spec['motion_file']}"
    receipt = f"{attempt_root}/motion-transform-report.json"
    req = {
        **common,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "attempt_id": spec["motion_attempt"],
        "candidate_id": spec["candidate_id"],
        "condition_id": spec["condition_id"],
        "physical_case_id": spec["physical_case_id"],
        "physical_condition_sha256": load(physical_path)["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": definition_sha,
        "command": [str(PYTHON), str(BASE_MOTION_WORKER), "--base-motion", BASE_MOTION, "--output", output, "--receipt", receipt, "--amplitude-scale", dec_text(spec["amplitude"]), "--time-scale", dec_text(spec["time_scale"])],
        "cwd": str(PKG),
        "worker_kind": "fresh117_registered_motion_amplitude_and_time_transform",
        "base_motion_path": BASE_MOTION,
        "base_motion_sha256": BASE_MOTION_SHA,
        "base_motion_sha256_provenance": "registered prior C082S1 producer metadata; fresh117 source prep did not read/hash DAT",
        "motion_output_path": output,
        "motion_output_sha256": None,
        "motion_transform_receipt": receipt,
        "motion_rows": 641,
        "source_time_window_s": [0.0, 16.0],
        "output_time_window_s": [0.0, float(spec["motion_end"])],
        "amplitude_scale": float(spec["amplitude"]),
        "time_scale": float(spec["time_scale"]),
        "future_scaled_motion": {"path": None, "sha256": None, "receipt": None, "rows": None},
        "source_definition": str(definition),
        "source_definition_sha256": definition_sha,
        "source_owner": str(owner_path),
        "source_owner_sha256": owner_sha,
        "physical_binding": str(physical_path),
        "physical_binding_sha256": physical_sha,
        "future_output_hashes": {"motion_output_sha256": None, "motion_receipt_sha256": None},
        "full801_authorized": False,
        "q_n_granted": False,
        "independent_case_count_increment": 0,
        "estimated_storage_bytes": 67108864,
        "max_wall_seconds": 900,
        "input_files": [],
        "input_sha256": {},
        "input_sha256_provenance": {},
    }
    files, hashes, provenance = static_closure(package_sources(spec, owner_path, physical_path, definition, [] ) + [BASE_MOTION])
    req["input_files"], req["input_sha256"], req["input_sha256_provenance"] = files, hashes, provenance
    dump(PKG / "requests" / f"{spec['tag']}-motion-transform-request.json", req)


def make_gencase_binding(spec: dict[str, Any], owner_path: Path, owner_sha: str, physical_path: Path, physical_sha: str, definition: Path, definition_sha: str) -> tuple[Path, str]:
    binding = {
        "schema": "ds02.f5.c082s1.first24-gencase-binding.fresh117.v1",
        "attempt_id": spec["gencase_attempt"],
        "candidate_id": spec["candidate_id"],
        "case_id": CASE,
        "condition_id": spec["condition_id"],
        "family_id": FAMILY,
        "physical_case_id": spec["physical_case_id"],
        "physical_condition_sha256": load(physical_path)["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": definition_sha,
        "control_recipe_id": spec["control_recipe_id"],
        "definition": str(definition),
        "definition_sha256": definition_sha,
        "owner": str(owner_path),
        "owner_sha256": owner_sha,
        "gencase": str(GENCASE),
        "gencase_sha256": GENCASE_SHA,
        "threads": 2,
        "dp_m": 0.02,
        "solver_dimension_required": 3,
        "source_mkbound": 40,
        "native_bed_mk": 50,
        "expected_fluid": None,
        "actual_counts": None,
        "predictions": {"counts": "null until fresh producer", "native_geometry": "must be independently audited"},
        "geometry_unchanged_from": CASE,
        "initial_population_unchanged_expected": True,
        "mass_rescale": False,
        "motion_transform_attempt": spec["motion_attempt"],
        "motion_transform_receipt": "<root-bind:motion_transform_receipt>",
        "motion_asset": {"path": "<root-bind:scaled_motion_output>", "sha256": None, "producer_attempt_id": spec["motion_attempt"], "relative_name": f"assets/{spec['motion_file']}"},
        "assets": [{"source": "<root-bind:scaled_motion_output>", "sha256": None, "relative_name": f"assets/{spec['motion_file']}"}],
        "amplitude_scale": float(spec["amplitude"]),
        "time_scale": float(spec["time_scale"]),
        "motion_output_time_end_s": float(spec["motion_end"]),
        "full_event_window_s": [0.0, float(FULL_TMAX)],
        "execution_policy": {"launch_allowed": False, "solver_allowed": False, "arrays_allowed": False, "conversion_allowed": False, "root_only_launch": True, "genuine_gencase_required": True, "independent_case_count_increment": 0},
        "source_only": True,
    }
    path = PKG / "bindings" / f"{spec['tag']}-gencase-binding.json"
    dump(path, binding)
    return path, sha(path)


def write_gencase_request(spec: dict[str, Any], owner_path: Path, owner_sha: str, physical_path: Path, physical_sha: str, definition: Path, definition_sha: str, binding: Path, binding_sha: str) -> None:
    common = root_common()
    req = {
        **common,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 2,
        "attempt_id": spec["gencase_attempt"],
        "candidate_id": spec["candidate_id"],
        "condition_id": spec["condition_id"],
        "physical_case_id": spec["physical_case_id"],
        "physical_condition_sha256": load(physical_path)["physical_condition_sha256"],
        "source_plan_physical_condition_sha256": definition_sha,
        "command": [str(PYTHON), str(GENCASE_WORKER), "--binding", str(binding), "--output-dir", "{attempt_root}/prepared"],
        "cwd": str(GENCASE_WORKER.parent.parent.parent.parent.parent),
        "worktree_root": str(GENCASE_WORKER.parent.parent.parent.parent.parent),
        "binding": str(binding),
        "binding_sha256": binding_sha,
        "definition": str(definition),
        "definition_sha256": definition_sha,
        "owner": str(owner_path),
        "owner_sha256": owner_sha,
        "motion_transform_attempt": spec["motion_attempt"],
        "motion_transform_receipt": "<root-bind:motion_transform_receipt>",
        "motion_asset_path": "<root-bind:scaled_motion_output>",
        "motion_asset_sha256": None,
        "output_root": "<root-bind:gencase_output_root>",
        "generated_xml": None,
        "generated_bi4": None,
        "expected_counts": None,
        "expected_dimension": 3,
        "future_producer_fields": {"actual_total_particles": None, "actual_fixed_particles": None, "actual_moving_particles": None, "actual_floating_particles": None, "actual_fluid_particles": None, "generated_xml_sha256": None, "generated_bi4_sha256": None, "prepared_input_report_sha256": None, "receipt_sha256": None},
        "genuine_gencase": True,
        "genuine_gencase_required": True,
        "command_provenance": "Root003 official GenCase worker; source package does not execute it",
        "worker_kind": "official_gencase_wrapper_root003",
        "purpose": "fresh producer only after Root binds the completed motion transform; actual counts and generated hashes remain null",
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 5368709120,
        "future_output_hashes": {"generated_xml_sha256": None, "generated_bi4_sha256": None, "prepared_input_report_sha256": None, "receipt_sha256": None},
        "input_files": [], "input_sha256": {}, "input_sha256_provenance": {},
    }
    paths = package_sources(spec, owner_path, physical_path, definition, [binding.name]) + [str(GENCASE_WORKER), str(GENCASE)]
    paths += ["<root-bind:motion_transform_receipt>", "<root-bind:scaled_motion_output>"]
    files, hashes, provenance = static_closure(paths)
    # The wrapper will read the transformed DAT only after Root binds the real producer path.
    hashes[str(GENCASE)] = None
    provenance[str(GENCASE)] = "official GenCase binary; source preparation did not open or hash binary"
    req["input_files"], req["input_sha256"], req["input_sha256_provenance"] = files, hashes, provenance
    dump(PKG / "requests" / f"{spec['tag']}-gencase-request.json", req)


def make_stage_bindings(spec: dict[str, Any], owner_path: Path, owner_sha: str, physical_path: Path, physical_sha: str, definition: Path, definition_sha: str, gencase_binding: Path, gencase_binding_sha: str) -> dict[str, tuple[Path, str]]:
    tag = spec["tag"]
    base = {
        "candidate_id": spec["candidate_id"], "case_id": CASE, "condition_id": spec["condition_id"], "physical_case_id": spec["physical_case_id"],
        "physical_binding_path": str(physical_path), "physical_binding_sha256": physical_sha,
        "owner": str(owner_path), "owner_sha256": owner_sha, "source_definition": str(definition), "source_definition_sha256": definition_sha,
        "gencase_binding": str(gencase_binding), "gencase_binding_sha256": gencase_binding_sha, "gencase_attempt_id": spec["gencase_attempt"],
        "native_bed_marker_mk": 50, "source_bed_marker_mkbound": 40, "solver_dimension": 3, "dp_m": 0.02,
        "expected_counts": None, "actual_counts": None, "full801_authorized": False, "q_n_granted": False,
        "source_only": True, "science_payloads_read_or_hashed_by_source_agent": False,
    }
    out: dict[str, tuple[Path, str]] = {}
    qa = {**base, "schema": "ds02.f5.c082s1.initial-placement-mk50-binding.fresh117.v1", "gencase_receipt": "<root-bind:gencase_receipt>", "prepared_input_report": "<root-bind:prepared_input_report>", "generated_xml": "<root-bind:generated_xml>", "official_particle_csv": "<root-bind:official_particle_csv>", "required_transverse_y_levels": 15, "placement_gate": "basic placement/Mk50 only; exact DP 1e-6 remains an independent numerical diagnostic", "no_count_rescaling": True, "require_central_mk50_support": True, "fluid_below_profile_must_be_zero": True}
    bed = {**base, "schema": "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh117.v1", "typed_h5": "<root-bind:typed_h5>", "xdmf": "<root-bind:xdmf>", "short_solver_receipt": "<root-bind:short_solver_receipt>", "expected_frames": SHORT_FRAMES, "time_window_s": [0.0, 1.0], "penetration_bins_m": [0.02, 0.04], "bed_y_bounds_m": [-0.22, 0.22], "profile_x_bounds_m": [-0.2, 4.8], "diagnostic_only": True, "visual_review_required": True, "repair_success_not_inferred": True}
    fullbed = {**base, "schema": "ds02.f5.c082s1.full-dynamic-bed-audit-binding.fresh117.v1", "typed_h5": "<root-bind:full_typed_h5>", "xdmf": "<root-bind:full_xdmf>", "full_solver_receipt": "<root-bind:full_solver_receipt>", "expected_frames": FULL_FRAMES, "time_window_s": [0.0, float(FULL_TMAX)], "penetration_bins_m": [0.02, 0.04], "bed_y_bounds_m": [-0.22, 0.22], "profile_x_bounds_m": [-0.2, 4.8], "diagnostic_only": True, "visual_review_required": True, "full_event_window_not_a_slice": True}
    for kind, value in (("initial-qa-mk50-binding", qa), ("short-dynamic-bed-audit-binding", bed), ("full-dynamic-bed-audit-binding", fullbed)):
        path = PKG / "bindings" / f"{tag}-{kind}.json"
        dump(path, value)
        out[kind] = (path, sha(path))
    return out


def write_initial_qa_request(spec: dict[str, Any], owner_path: Path, owner_sha: str, physical_path: Path, physical_sha: str, definition: Path, definition_sha: str, stage: dict[str, tuple[Path, str]]) -> None:
    binding, binding_sha = stage["initial-qa-mk50-binding"]
    common = root_common()
    req = {
        **common, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2,
        "attempt_id": spec["qa_attempt"], "candidate_id": spec["candidate_id"], "condition_id": spec["condition_id"], "physical_case_id": spec["physical_case_id"],
        "physical_condition_sha256": load(physical_path)["physical_condition_sha256"], "source_plan_physical_condition_sha256": definition_sha,
        "command": [str(PYTHON), "<root-bind:initial_qa_worker>", "--binding", str(binding), "--output-dir", "{attempt_root}/audit-output"],
        "cwd": str(RUNTIME.parent), "binding": str(binding), "binding_sha256": binding_sha,
        "depends_on_attempt": spec["gencase_attempt"], "gencase_attempt_id": spec["gencase_attempt"], "gencase_receipt": "<root-bind:gencase_receipt>", "prepared_input_report": "<root-bind:prepared_input_report>", "generated_xml": "<root-bind:generated_xml>", "generated_bi4": "<root-bind:generated_bi4>", "official_particle_csv": "<root-bind:official_particle_csv>",
        "expected_counts": None, "expected_particles": None, "expected_fixed_particles": None, "expected_moving_particles": None, "expected_floating_particles": None, "expected_fluid_particles": None, "expected_dimension": 3,
        "native_bed_mk": 50, "source_mkbound": 40, "required_transverse_y_levels": 15, "placement_gate": "basic placement/Mk50 only; precision diagnostic remains separate", "binding_contract": {"actual_counts_must_be_copied_from_fresh_gencase": True, "require_central_mk50_support": True, "fluid_below_profile_must_be_zero": True, "no_count_rescaling": True, "no_precision_threshold_relaxation": True, "old_precision_negative_preserved": True},
        "worker_kind": "Root-owned producer-bound placement/Mk50 audit; worker must not infer candidate counts", "max_wall_seconds": 3600, "estimated_storage_bytes": 2147483648,
        "future_output_hashes": {"initial_qa_report_sha256": None, "receipt_sha256": None, "generated_xml_sha256": None, "generated_bi4_sha256": None, "prepared_input_report_sha256": None, "official_csv_sha256": None},
        "input_files": [], "input_sha256": {}, "input_sha256_provenance": {},
    }
    paths = package_sources(spec, owner_path, physical_path, definition, [binding.name]) + [str(RUNTIME), str(STRICT)] + ["<root-bind:initial_qa_worker>", "<root-bind:gencase_receipt>", "<root-bind:prepared_input_report>", "<root-bind:generated_xml>", "<root-bind:generated_bi4>", "<root-bind:official_particle_csv>"]
    files, hashes, provenance = static_closure(paths)
    req["input_files"], req["input_sha256"], req["input_sha256_provenance"] = files, hashes, provenance
    dump(PKG / "requests" / f"{spec['tag']}-initial-placement-mk50-request.json", req)


def write_native_request(spec: dict[str, Any], stage_name: str, owner_path: Path, owner_sha: str, physical_path: Path, physical_sha: str, definition: Path, definition_sha: str, stage: dict[str, tuple[Path, str]], full: bool) -> None:
    if full:
        attempt = spec["full_attempt"]
        tmax, frames, window = FULL_TMAX, FULL_FRAMES, [0.0, float(FULL_TMAX)]
        suffix = "full-native-qualification"
        command = [str(SOLVER), "<root-bind:gencase_prefix>", "{attempt_root}/solver_output", f"-tmax:{dec_text(FULL_TMAX)}", "-tout:0.02"]
        depends = spec["qa_attempt"]
        extra = {"full_event_window": {"forcing_end_s": float(spec["motion_end"]), "post_forcing_tail_s": float(FULL_TMAX - spec["motion_end"]), "not_a_slice_of_old_output": True}, "full_native_authorized": False, "upstream_visual_gate": "WAIT_existing_A080_A120_all801_bed_and_root_visual_review", "fresh117_full_enablement_requires_root574_complete_case_review": True}
    else:
        attempt = spec["short_attempt"]
        tmax, frames, window = SHORT_TMAX, SHORT_FRAMES, [0.0, 1.0]
        suffix = "short-native-qualification"
        command = [str(SOLVER), "<root-bind:gencase_prefix>", "{attempt_root}/solver_output", "-tmax:1.0", "-tout:0.02"]
        depends = spec["qa_attempt"]
        extra = {"short_right_censored": True, "full_native_authorized": False}
    common = root_common()
    req = {
        **common, "kind": "qualification", "cpu_task_kind": "solver", "cpu_threads": 2, "omp_threads": 2,
        "attempt_id": attempt, "candidate_id": spec["candidate_id"], "condition_id": spec["condition_id"], "physical_case_id": spec["physical_case_id"],
        "physical_condition_sha256": load(physical_path)["physical_condition_sha256"], "source_plan_physical_condition_sha256": definition_sha,
        "command": command, "cwd": "<root-bind:gencase_prepared_root>", "depends_on_attempt": depends, "gencase_attempt_id": spec["gencase_attempt"], "gencase_receipt": "<root-bind:gencase_receipt>", "gencase_prefix": "<root-bind:gencase_prefix>", "generated_xml": "<root-bind:generated_xml>", "generated_bi4": "<root-bind:generated_bi4>",
        "binding": str(stage["initial-qa-mk50-binding"][0]), "binding_sha256": stage["initial-qa-mk50-binding"][1], "actual_initial_qa_report": "<root-bind:actual_initial_qa_report>",
        "motion_asset_path": "<root-bind:scaled_motion_output>", "motion_asset_sha256": None, "amplitude_scale": float(spec["amplitude"]), "time_scale": float(spec["time_scale"]), "motion_end_s": float(spec["motion_end"]),
        "event_window_s": window, "tmax_s": float(tmax), "tout_s": 0.02, "save_interval_s": 0.02, "expected_frames": frames, "expected_dimension": 3,
        "expected_particles": None, "expected_fixed_particles": None, "expected_moving_particles": None, "expected_floating_particles": None, "expected_fluid_particles": None,
        "native_bed_mk": 50, "source_mkbound": 40, "solver_command_is_template_only": True, "stage1_gate": "fresh GenCase and producer-bound placement/Mk50 QA must pass before Root enablement",
        "estimated_peak_gpu_mib": 4096, "estimated_storage_bytes": 17179869184 if full else 10737418240, "max_wall_seconds": 10800 if full else 1800,
        "root230_gpu_protection_required_for_native_solver": True, "root230_entrypoint": str(ROOT230_LAUNCH), "root230_entrypoint_sha256": ROOT230_LAUNCH_SHA, "root230_policy_source": str(ROOT230_POLICY), "root230_policy_source_sha256": ROOT230_POLICY_SHA,
        "future_output_hashes": {"solver_receipt_sha256": None, "solver_stdout_sha256": None, "solver_data_manifest_sha256": None, "solver_part_count": None, "typed_receipt_sha256": None, "typed_h5_sha256": None, "xmf_manifest_sha256": None, "bed_audit_report_sha256": None},
        "future_candidate_counts_and_hashes_null": True, "production_approval": "none", "q_n_granted": False, "independent_case_count_increment": 0, "no_new_case_credit": True,
        "input_files": [], "input_sha256": {}, "input_sha256_provenance": {}, **extra,
    }
    paths = package_sources(spec, owner_path, physical_path, definition, [stage["initial-qa-mk50-binding"][0].name]) + [str(RUNTIME), str(STRICT), str(SOLVER), "<root-bind:gencase_prepared_root>", "<root-bind:gencase_receipt>", "<root-bind:gencase_prefix>", "<root-bind:generated_xml>", "<root-bind:generated_bi4>", "<root-bind:actual_initial_qa_report>", "<root-bind:scaled_motion_output>"]
    files, hashes, provenance = static_closure(paths)
    req["input_files"], req["input_sha256"], req["input_sha256_provenance"] = files, hashes, provenance
    dump(PKG / "requests" / f"{spec['tag']}-{stage_name}.json", req)


def write_bed_request(spec: dict[str, Any], owner_path: Path, owner_sha: str, physical_path: Path, physical_sha: str, definition: Path, definition_sha: str, stage: dict[str, tuple[Path, str]], full: bool) -> None:
    binding_key = "full-dynamic-bed-audit-binding" if full else "short-dynamic-bed-audit-binding"
    binding, binding_sha = stage[binding_key]
    attempt = spec["full_bed_attempt"] if full else spec["short_bed_attempt"]
    native_attempt = spec["full_attempt"] if full else spec["short_attempt"]
    frames = FULL_FRAMES if full else SHORT_FRAMES
    window = [0.0, float(FULL_TMAX)] if full else [0.0, 1.0]
    command = [str(PYTHON), "<root-bind:bed_audit_worker>", "--binding", str(binding), "--trajectory-h5", "<root-bind:typed_h5>", "--xdmf", "<root-bind:xdmf>", "--output-dir", "{attempt_root}/audit-output"]
    common = root_common()
    req = {
        **common, "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "attempt_id": attempt, "candidate_id": spec["candidate_id"], "condition_id": spec["condition_id"], "physical_case_id": spec["physical_case_id"],
        "physical_condition_sha256": load(physical_path)["physical_condition_sha256"], "source_plan_physical_condition_sha256": definition_sha,
        "command": command, "cwd": str(RUNTIME.parent), "binding": str(binding), "binding_sha256": binding_sha, "depends_on_attempt": native_attempt,
        "typed_receipt": "<root-bind:typed_receipt>", "typed_h5": "<root-bind:typed_h5>", "xmf_manifest": "<root-bind:xmf_manifest>", "short_solver_receipt": "<root-bind:short_solver_receipt>" if not full else None,
        "expected_frames": frames, "expected_particles": None, "expected_fluid_particles": None, "expected_dimension": 3, "time_window_s": window, "bed_x_bounds_m": [-0.2, 4.8], "bed_y_bounds_m": [-0.22, 0.22], "penetration_bins_m": [0.02, 0.04], "native_bed_marker_mk": 50, "source_bed_marker_mkbound": 40,
        "diagnostic_only": True, "dynamic_acceptance": "Root reviews every frame and visual output; worker cannot grant Q-N or full enablement", "visual_review_required": True, "repair_success_not_inferred": True, "full_event_window_not_a_slice": full,
        "future_output_hashes": {"audit_report_sha256": None, "typed_h5_sha256": None, "xmf_manifest_sha256": None, "receipt_sha256": None}, "full801_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0,
        "estimated_storage_bytes": 8589934592 if full else 3221225472, "max_wall_seconds": 7200 if full else 3600, "input_files": [], "input_sha256": {}, "input_sha256_provenance": {},
    }
    paths = package_sources(spec, owner_path, physical_path, definition, [binding.name]) + [str(RUNTIME), str(STRICT), "<root-bind:bed_audit_worker>", "<root-bind:typed_receipt>", "<root-bind:typed_h5>", "<root-bind:xdmf>", "<root-bind:xmf_manifest>", "<root-bind:short_solver_receipt>"]
    files, hashes, provenance = static_closure(paths)
    req["input_files"], req["input_sha256"], req["input_sha256_provenance"] = files, hashes, provenance
    dump(PKG / "requests" / f"{spec['tag']}-{'full' if full else 'short'}-dynamic-bed-audit-request.json", req)


def write_baseline(base_physical: dict[str, Any], base_attestation: dict[str, Any]) -> None:
    dump(PKG / "metadata/baseline-provenance.json", {
        "schema": "ds02.f5.c082s1.fresh117-baseline-provenance.v1",
        "source_geometry": "C082S1 analytic closed bed/tank/piston source from fresh110 M100_T110 DefXML and fresh115 A080/A120 review metadata",
        "source_mkbound": 40,
        "native_bed_mk": 50,
        "dp_m": 0.02,
        "dimension": 3,
        "historical_actual_initial_counts": base_attestation["native"]["actual_counts"],
        "historical_counts_are_not_new_candidate_expectations": True,
        "historical_actual_short_bed": "fresh109 Root509 A080/A120 reports had 51 frames, max 1DP/2DP/missing/nonfinite/outside all zero; visual/full801 review remains Root-owned WAIT",
        "historical_exact_dp_negative": {"threshold": 1e-6, "status": "retained_as_numerical_precision_negative", "source": "Root314"},
        "historical_A_B_penetration_failures": {"A": "old C082S1 A repair short audit failed with severe below-bed penetration", "B": "old B071 short audit failed with severe below-bed penetration; no reclassification"},
        "root425_426_precedent": "Root425/426 actual motion transforms and GenCase producer metadata demonstrate the registered contract; fresh117 future candidates still require their own transform and GenCase receipts",
        "new_candidates_must_bind_actual_counts": True,
        "source_agent_did_not_read_or_hash_science_payloads": True,
        "full801_upstream_visual_gate": "WAIT; existing A080/A120 must pass complete all801 bed and root visual review before any fresh117 full enablement",
    })


def write_parent_inventory() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for tag in ("A080", "A120"):
        physical_path = FRESH115 / f"bindings/{tag}-full801-physical-binding.json"
        definition_path = FRESH115 / f"inputs/{tag}-Definition.xml"
        physical = load(physical_path)
        records.append({
            "tag": tag,
            "candidate_id": f"C082S1_MOTION_{tag}",
            "condition_id": None,
            "condition_id_source": "not present in retained physical binding; deduplication uses candidate/physical case/hash",
            "physical_case_id": physical.get("physical_case_id"),
            "amplitude_scale": physical.get("parameters", {}).get("piston_motion", {}).get("amplitude_scale"),
            "time_scale": 1.0,
            "source_package": str(FRESH115),
            "source_definition": str(definition_path),
            "source_definition_sha256": sha(definition_path),
            "physical_binding": str(physical_path),
            "physical_binding_sha256": sha(physical_path),
            "physical_condition_sha256": physical.get("physical_condition_sha256"),
            "status": "historical_parent_actual_native_or_typed_metadata; no new case credit",
        })
    plan = load(FRESH110 / "metadata/fresh110-source-plan.json")
    for item in plan.get("candidates", []):
        tag = item["tag"]
        physical_path = FRESH110 / f"bindings/{tag}-physical-binding.json"
        records.append({
            "tag": tag,
            "candidate_id": item.get("candidate_id"),
            "condition_id": item.get("condition_id"),
            "physical_case_id": item.get("physical_case_id"),
            "amplitude_scale": item.get("amplitude_scale"),
            "time_scale": item.get("time_scale"),
            "source_package": str(FRESH110),
            "source_definition": str(FRESH110 / f"candidates/{tag}/{CASE}_{tag}_Def.xml"),
            "source_definition_sha256": item.get("source_definition_sha256"),
            "physical_binding": str(physical_path),
            "physical_binding_sha256": sha(physical_path),
            "physical_condition_sha256": item.get("physical_condition_sha256"),
            "status": "fresh110_disabled_parent_condition; no new case credit",
        })
    require(len(records) == 8, "parent condition inventory must contain A080/A120 plus six fresh110 conditions")
    require(len({record.get("candidate_id") for record in records}) == 8, "parent candidate IDs must be unique")
    require(len({record.get("physical_condition_sha256") for record in records}) == 8, "parent physical conditions must be unique")
    inventory = {
        "schema": "ds02.f5.c082s1.first24-parent-condition-inventory.fresh117.v1",
        "status": "eight_existing_conditions_a080_a120_plus_fresh110_six_retained_for_deduplication",
        "parent_count": len(records),
        "parents": records,
        "source_agent_did_not_read_or_hash_science_payloads": True,
        "new_candidate_counts_are_null": True,
        "new_case_credit": 0,
    }
    dump(PARENT_INVENTORY, inventory)
    return inventory


def write_plan(specs: list[dict[str, Any]], owner_info: dict[str, dict[str, Any]]) -> None:
    candidates = []
    for spec in specs:
        candidates.append({
            "tag": spec["tag"], "candidate_id": spec["candidate_id"], "condition_id": spec["condition_id"], "physical_case_id": spec["physical_case_id"],
            "amplitude_scale": float(spec["amplitude"]), "time_scale": float(spec["time_scale"]), "motion_end_s": float(spec["motion_end"]), "full_event_window_s": [0.0, float(FULL_TMAX)], "full_output_frames": FULL_FRAMES,
            "physical_condition_sha256": owner_info[spec["tag"]]["physical_condition_sha256"], "owner_sha256": owner_info[spec["tag"]]["owner_sha256"], "physical_binding_sha256": owner_info[spec["tag"]]["physical_binding_sha256"], "source_definition_sha256": owner_info[spec["tag"]]["definition_sha256"], "expected_counts": None, "future_output_hashes": None,
            "motion_transform": "disabled; Root must register transform worker and bind actual output receipt", "gencase": "disabled; actual producer counts required", "initial_qa": "disabled; actual CSV/BI4 producer required", "short_native": "disabled; 1s/51-frame right-censored qualification", "full_native": f"disabled; {dec_text(FULL_TMAX)}s/{FULL_FRAMES}-frame event window", "full801_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0,
        })
    dump(PKG / "metadata/fresh117-source-plan.json", {
        "schema": "ds02.f5.c082s1.fresh117-source-plan.v1", "status": "sixteen_unique_amplitude_time_conditions_all_disabled", "candidate_count": len(candidates), "candidates": candidates,
        "amplitude_set": sorted({float(spec["amplitude"]) for spec in specs}), "time_scale_set": sorted({float(spec["time_scale"]) for spec in specs}), "cartesian_product_complete": True, "existing_A080_A120_and_fresh110_inventory_retained": True,
        "full_event_window": {"tmax_s": float(FULL_TMAX), "tout_s": 0.02, "frames": FULL_FRAMES, "reason": "contains the slowest transformed forcing endpoint 19.2s plus a 6.8s post-forcing runup tail; not an old-output slice"},
        "short_window": {"tmax_s": 1.0, "tout_s": 0.02, "frames": SHORT_FRAMES, "right_censored": True},
        "expected_counts": None, "future_hashes": None, "full801_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0,
        "exact_dp_negative_retained": True, "historical_A_B_failures_retained": True, "root230_live_uuid_lease_required": True, "root_review_required": True,
        "parent_condition_inventory": str(PARENT_INVENTORY), "first24_parent_count": 8, "first24_new_count": len(candidates), "first24_total_count": 8 + len(candidates),
        "upstream_full_native_gate": {"status": "WAIT", "required_current_cases": ["A080", "A120"], "requires_actual_all801_bed_audit": True, "requires_root_visual_pass": True, "short_window_native_approval_insufficient": True, "new_full_native_enablement": False},
        "source_only": True, "science_payloads_read_or_hashed_by_source_builder": False, "jobs_started": False, "shared_state_modified": False,
    })


def write_readme(specs: list[dict[str, Any]], owner_info: dict[str, dict[str, Any]]) -> None:
    lines = [
        "# F5 fresh117: sixteen additions completing the first 24-condition source batch",
        "",
        "This pack keeps the C082S1 analytic closed bed, finite tank, source Mk40 to native Mk50 mapping, and three-dimensional source definition. It adds sixteen distinct forcing owners from amplitude {0.85, 0.95, 1.05, 1.15} crossed with time scale {0.80, 0.90, 1.00, 1.20}. The set is disjoint from A080/A120 and fresh110's six M/T conditions. The slowest transformed table ends at 19.2 s; each full native template runs 0..26 s at .02 s (1301 states), leaving a 6.8 s post-forcing runup tail.",
        "",
        "All requests are source-only and disabled. The motion worker is registered for future Root CPU execution; it reads the base DAT only at execution time. GenCase, initial placement/Mk50 QA, 1 s/51-state native qualification, dynamic bed audits, and 26 s full native templates require fresh producer receipts. Counts remain null until each candidate's own GenCase report.",
        "",
        "The historical C082S1 counts and fresh109 A080/A120 short-bed evidence are provenance only. They are not copied as new-candidate expectations. Root314's exact-DP 1e-6 negative and the earlier A/B severe penetration failures remain preserved. Existing A080/A120 full native typed results still await complete all801 bed and root visual review; no fresh117 full run is approved by this package.",
        "",
        "| Candidate | amplitude | time scale | transformed table end | full window | canonical condition SHA | owner source SHA |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for spec in specs:
        lines.append(f"| `{spec['tag']}` | {spec['amplitude']} | {spec['time_scale']} | {spec['motion_end']} s | 0..{dec_text(FULL_TMAX)} s / {FULL_FRAMES} | `{owner_info[spec['tag']]['physical_condition_sha256']}` | `{owner_info[spec['tag']]['owner_sha256']}` |")
    lines.extend([
        "",
        "Root next entries are the `requests/*-motion-transform-request.json` files, followed by each matching GenCase and initial QA request only after the actual transform receipt is bound. The short native/bed and full native/bed requests stay disabled until Root review and Root230 live UUID/lease protection are supplied.",
        "",
        "Source preparation did not read or hash DAT, BI4, H5, CSV, VTK, or solver payloads and did not start a job or modify shared state.",
    ])
    (PKG / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest() -> None:
    files: dict[str, str] = {}
    report = PKG / "metadata/fresh117-validator-report.json"
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json" or path == report:
            continue
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science file in source package: {path}")
        require(path.suffix.lower() in STATIC_SUFFIXES, f"unsupported package file: {path}")
        files[str(path.relative_to(PKG))] = sha(path)
    dump(PKG / "manifest.json", {"schema": "ds02.f5.c082s1.fresh117-source-manifest.v1", "status": "sixteen_unique_amplitude_time_conditions_all_disabled", "files": files, "validator_report_excluded_from_manifest": True, "full801_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0, "science_payloads_read_or_hashed_by_source_builder": False, "jobs_started": False, "shared_state_modified": False})


def main() -> int:
    base_physical = load(BASE_PHYSICAL)
    base_attestation = load(BASE_ATTESTATION)
    specs = [tag_to_candidate(tag) for tag, _, _ in SPECS]
    require(len({s["candidate_id"] for s in specs}) == 16, "candidate IDs must be unique")
    require(not {s["candidate_id"] for s in specs} & {"C082S1_MOTION_A080", "C082S1_MOTION_A120"}, "fresh117 may not duplicate A080/A120")
    owner_info: dict[str, dict[str, Any]] = {}
    parent_inventory = write_parent_inventory()
    parent_ids = {record["candidate_id"] for record in parent_inventory["parents"]}
    require(not {s["candidate_id"] for s in specs} & parent_ids, "fresh117 candidate duplicates an existing parent condition")
    for spec in specs:
        definition, definition_sha = make_definition(spec)
        owner_path, owner_sha, owner = make_owner(spec, definition, definition_sha, base_physical)
        physical_path, physical_sha = physical_binding(spec, owner_path, owner_sha, owner, definition, definition_sha)
        gencase_binding, gencase_binding_sha = make_gencase_binding(spec, owner_path, owner_sha, physical_path, physical_sha, definition, definition_sha)
        stage = make_stage_bindings(spec, owner_path, owner_sha, physical_path, physical_sha, definition, definition_sha, gencase_binding, gencase_binding_sha)
        write_motion_request(spec, owner_path, owner_sha, definition, definition_sha, physical_path, physical_sha)
        write_gencase_request(spec, owner_path, owner_sha, physical_path, physical_sha, definition, definition_sha, gencase_binding, gencase_binding_sha)
        write_initial_qa_request(spec, owner_path, owner_sha, physical_path, physical_sha, definition, definition_sha, stage)
        write_native_request(spec, "short-native-qualification-request", owner_path, owner_sha, physical_path, physical_sha, definition, definition_sha, stage, False)
        write_native_request(spec, "full-native-qualification-request", owner_path, owner_sha, physical_path, physical_sha, definition, definition_sha, stage, True)
        write_bed_request(spec, owner_path, owner_sha, physical_path, physical_sha, definition, definition_sha, stage, False)
        write_bed_request(spec, owner_path, owner_sha, physical_path, physical_sha, definition, definition_sha, stage, True)
        owner_info[spec["tag"]] = {"physical_condition_sha256": owner["physical_condition_sha256"], "definition_sha256": definition_sha, "owner_sha256": owner_sha, "physical_binding_sha256": physical_sha}
    write_baseline(base_physical, base_attestation)
    write_plan(specs, owner_info)
    write_readme(specs, owner_info)
    write_manifest()
    print(json.dumps({"status": "built", "candidate_count": 16, "full_event_window_s": [0.0, float(FULL_TMAX)], "full_frames": FULL_FRAMES, "all_disabled": True, "science_payloads_read_or_hashed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
