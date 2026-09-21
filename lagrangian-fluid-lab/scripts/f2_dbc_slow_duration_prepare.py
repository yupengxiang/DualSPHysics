#!/usr/bin/env python3
"""CPU preparation for the single F2 q=1 slow-duration DBC canary.

The existing full-cup DBC GenCase implementation is reused only as a CPU
preparation helper.  This module changes the prescribed motion duration from
0.85 s to the already registered q=1 endpoint 1.20 s, then rewrites the
prepared metadata and creates a closed input manifest.  It never invokes the
solver, submits a job, or writes a campaign ledger.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_qualification as f2q
from scripts import f2_full_cup_closed_catchment_dbc as base


SCHEMA = "core.f2.dbc_slow_duration.preparation.v1"
JOB_SCHEMA = "core.cfd.job.v1"
SCOPE_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_x_v1"
REVISION_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_q1p0_v1"
CASE_ID = "CORE_F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_q1p00000000_dp0p007500000000_canary"
JOB_ID = "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-slow-duration-q1p0-canary-v1-001"
DP_M = 0.0075
Q = 1.0
ROTATION_DURATION_S = 1.20
BASELINE_ROTATION_DURATION_S = 0.85
ANGLE_DEGREES = -105.0
MOTION_START_S = 0.50
TIME_MAX_S = 5.0
OUTPUT_INTERVAL_S = 0.01
RUNTIME_DOMAIN = {
    "posmin": [-0.70, -0.65, -0.40],
    "posmax": [2.20, 0.80, 2.40],
    "baseline_zmax_m": 1.80,
    "changed_zmax_m": 2.40,
    "change_is_computational_only": True,
}
PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_q1p0_v1"
)
JOB_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-slow-duration-q1p0-canary-job-v1.json"
)
REVIEW_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-slow-duration-q1p0-preparation-review-v1.json"
)
EXTENSION_PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2_extension5s_v2/"
    "prepared.json"
)
EXTENSION_COMPLETION_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-extension5s-root-completion-v1.json"
)
EXTENSION_OBSERVER_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-extension5s-observer-v3-metadata-reaudit.json"
)
CANDIDATE_CARD_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-slow-duration-q1p0-canary-proposal-v1.json"
)
DYNAMICS_FORENSICS_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-extension5s-dynamics-forensics-v1.json"
)
STATIC_PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_canary_v3/prepared.json"
)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return core_cfd.digest(Path(path))


def _write_json(path: Path, value: dict) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _ref(path: Path, lab: Path, role: str) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "relative_to_lab": str(path.relative_to(lab.resolve())),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def _configure_base() -> None:
    """Set only the helper module's preparation constants."""
    base.SCOPE_ID = SCOPE_ID
    base.REVISION_ID = REVISION_ID
    base.CASE_ID = CASE_ID
    base.JOB_ID = JOB_ID
    base.Q = Q
    base.ROTATION_DURATION_S = ROTATION_DURATION_S
    base.TIME_MAX_S = TIME_MAX_S
    base.MAXIMUM_EXTENDED_TIME_S = TIME_MAX_S
    base.OUTPUT_INTERVAL_S = OUTPUT_INTERVAL_S
    base.ANGLE_DEGREES = ANGLE_DEGREES
    base._dynamic_motion = _dynamic_motion


def _dynamic_motion(path: Path) -> None:
    """Write the complete 5 s source file with the q=1.0 motion law."""
    lines = ["#Time;Degrees"]
    for time_s in np.arange(0.0, TIME_MAX_S + 0.0001, OUTPUT_INTERVAL_S):
        lines.append(f"{time_s:.6f};{f2q.motion_angle(float(time_s), ROTATION_DURATION_S, ANGLE_DEGREES):.9f}")
    Path(path).write_text("\n".join(lines) + "\n")


def _decode_native(path: Path, decoder: Path, label: str) -> tuple:
    with tempfile.TemporaryDirectory(prefix=f"f2-dbc-duration-{label}-") as folder:
        return core_cfd.native_frame(path, Path(folder) / label, decoder)[:5]


def _native_equivalence(left_prefix: Path, right_prefix: Path, decoder: Path) -> dict:
    left = _decode_native(left_prefix.with_suffix(".bi4"), decoder, "left")
    right = _decode_native(right_prefix.with_suffix(".bi4"), decoder, "right")
    arrays_equal = all(np.array_equal(left[index], right[index]) for index in range(4))
    metadata_diff = {
        key: [left[4].get(key), right[4].get(key)]
        for key in set(left[4]) | set(right[4])
        if left[4].get(key) != right[4].get(key)
    }
    return {
        "decoded_ids_positions_velocities_density_equal": bool(arrays_equal),
        "metadata_differences": metadata_diff,
        "only_case_name_metadata_changed": set(metadata_diff) <= {"CaseName"},
        "pass": bool(arrays_equal and set(metadata_diff) <= {"CaseName"}),
    }


def _motion_proof(definition: Path, motion: Path) -> dict:
    root = ET.parse(definition).getroot()
    node = root.find(".//mvrotfile")
    if node is None or node.find("file") is None:
        raise ValueError("generated Definition.xml has no mvrotfile")
    if node.find("file").get("name") != motion.name:
        raise ValueError("Definition.xml motion filename does not match prepared motion asset")
    rows = []
    for line in motion.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        time_text, angle_text = line.split(";", 1)
        rows.append((float(time_text), float(angle_text)))
    if not rows:
        raise ValueError("motion file is empty")
    target = float(ANGLE_DEGREES)
    target_indices = [i for i, (_, angle) in enumerate(rows) if abs(angle - target) <= 1e-8]
    if not target_indices:
        raise ValueError("motion file never reaches the requested final angle")
    first_target = rows[target_indices[0]]
    last_row = rows[-1]
    expected_complete = MOTION_START_S + ROTATION_DURATION_S
    if abs(first_target[0] - expected_complete) > OUTPUT_INTERVAL_S + 1e-7:
        raise ValueError(f"motion target begins at {first_target[0]} instead of {expected_complete}")
    if abs(last_row[1] - target) > 1e-8:
        raise ValueError("motion file does not hold the target angle at the end")
    return {
        "definition_mvrotfile_duration_s": float(node.get("duration")),
        "definition_motion_filename": node.find("file").get("name"),
        "motion_file_first_time_s": rows[0][0],
        "motion_file_first_angle_degrees": rows[0][1],
        "requested_rotation_duration_s": ROTATION_DURATION_S,
        "expected_target_time_s": expected_complete,
        "first_target_time_s": first_target[0],
        "first_target_angle_degrees": first_target[1],
        "last_time_s": last_row[0],
        "last_angle_degrees": last_row[1],
        "target_hold_present": True,
        "pass": True,
    }


def _solver_control_proof(definition: Path) -> dict:
    root = ET.parse(definition).getroot()
    cfl_node = root.find(".//cflnumber")
    if cfl_node is None:
        raise ValueError("generated Definition.xml has no cflnumber")
    parameters = {
        node.get("key"): node.get("value")
        for node in root.findall(".//execution/parameters/parameter")
    }
    expected = {
        "cflnumber": 0.2,
        "Boundary": 1,
        "ViscoTreatment": 1,
        "Visco": 0.03,
        "DtIni": 0.0,
        "DtMin": 0.0,
        "DtFixed": 0.0,
        "TimeMax": 5.0,
        "TimeOut": 0.01,
    }
    actual = {
        "cflnumber": float(cfl_node.get("value")),
        "Boundary": int(parameters["Boundary"]),
        "ViscoTreatment": int(parameters["ViscoTreatment"]),
        "Visco": float(parameters["Visco"]),
        "DtIni": float(parameters["DtIni"]),
        "DtMin": float(parameters["DtMin"]),
        "DtFixed": float(parameters["DtFixed"]),
        "TimeMax": float(parameters["TimeMax"]),
        "TimeOut": float(parameters["TimeOut"]),
    }
    if any(actual[key] != expected[key] for key in expected):
        raise ValueError(f"frozen F2 DBC controls changed: {actual}")
    return {"expected": expected, "actual": actual, "pass": True}


def _postprocess_prepared(lab: Path, output: Path) -> dict:
    prepared_path = output / "prepared.json"
    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    extension_path = (lab / EXTENSION_PREPARED_RELATIVE).resolve()
    extension = json.loads(extension_path.read_text())
    extension_prefix = Path(extension["generated_prefix"])
    generated_prefix = Path(prepared["generated_prefix"])
    decoder = Path(prepared["decoder"])
    definition_path = Path(prepared["definition_audit"]["definition"])
    motion_path = Path(prepared["definition_audit"]["motion_file"])
    motion_proof = _motion_proof(definition_path, motion_path)
    solver_control_proof = _solver_control_proof(definition_path)
    baseline_definition = Path(extension["definition_audit"]["definition"])
    baseline_solver_control_proof = _solver_control_proof(baseline_definition)
    if solver_control_proof["actual"] != baseline_solver_control_proof["actual"]:
        raise ValueError("q=1 candidate changed a frozen solver control relative to completed DBC")
    equivalence = _native_equivalence(extension_prefix, generated_prefix, decoder)
    if not equivalence["pass"]:
        raise ValueError(f"q=1 native state differs from completed DBC geometry: {equivalence}")

    candidate_path = (lab / CANDIDATE_CARD_RELATIVE).resolve()
    dynamics_path = (lab / DYNAMICS_FORENSICS_RELATIVE).resolve()
    completion_path = (lab / EXTENSION_COMPLETION_RELATIVE).resolve()
    observer_path = (lab / EXTENSION_OBSERVER_RELATIVE).resolve()
    static_path = (lab / STATIC_PREPARED_RELATIVE).resolve()
    config.update({
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "recipe_id": "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_v1",
        "recipe": "native_dbc",
        "stage": "repair_canary",
        "split": "qualification_only",
        "qualification_only": True,
        "qualified": False,
        "parameter": {
            "name": "rotation_duration_s",
            "q": Q,
            "value": ROTATION_DURATION_S,
            "candidate_range": [0.50, 1.20],
            "held_out": False,
        },
        "time_max_s": TIME_MAX_S,
        "maximum_extended_time_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "angle_degrees": ANGLE_DEGREES,
        "motion_start_s": MOTION_START_S,
        "physical_case_id": "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_v1",
        "lineage_group_id": SCOPE_ID,
        "control_semantics": "prescribed centered cosine rotation starts at 0.50 s; q=1.0 completes -105 degrees at 1.70 s and DBC uses native mvrotfile rigid-body motion",
        "repair_candidate_id": "slow_rotation_duration",
        "physical_geometry_changed": False,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "qualification_inheritance": "none; independent continuous-motion protocol canary; static anchor is prerequisite provenance only",
        "qualification_claim": "none; q=1.0 slow-duration DBC canary only",
        "observer_revision": "F2_geometry_aware_observer_v1",
        "event_window": {
            **copy.deepcopy(config.get("event_window", {})),
            "registered_initial_window_s": TIME_MAX_S,
            "maximum_extended_window_s": TIME_MAX_S,
            "motion_source_file_duration_s": TIME_MAX_S,
            "right_censor_policy": "5 s is the single registered canary window; a missing required event fails and no further extension is permitted",
        },
        "source_geometry_contract": {
            **copy.deepcopy(config.get("source_geometry_contract", {})),
            "motion": "prescribed centered rotation, y axis through z=0.65, q=1.0 duration 1.20 s, same cosine law and -105 degree target",
        },
        "repair_hypothesis": {
            "id": "slow_rotation_duration",
            "mechanism_class": "prescribed_continuous_motion_protocol",
            "single_variable_change": "rotation_duration_s 0.85 -> 1.20 at registered q=1 endpoint",
            "boundary_unchanged": "native DBC Boundary=1",
            "cfl_unchanged": 0.2,
            "dp_unchanged_m": DP_M,
            "rationale": "the completed 5 s DBC hard-passing trajectory retains a broad tray-floor residual velocity population; slowing the same smooth drive reduces prescribed angular rate/acceleration without changing wall or destination semantics",
            "negative_evidence_preserved": "the 0.85 s DBC 5 s event failure remains a separate completed negative result; no horizon or threshold change is included",
        },
        "definition_audit": {
            "source_definition": config["definition_audit"]["source_definition"],
            "source_definition_sha256": config["definition_audit"]["source_definition_sha256"],
            "definition": str(definition_path.resolve()),
            "definition_sha256": _sha256(definition_path),
            "motion_file": str(motion_path.resolve()),
            "motion_sha256": _sha256(motion_path),
            "baseline_definition": str(baseline_definition.resolve()),
            "baseline_definition_sha256": _sha256(baseline_definition),
            "changed_fields": [
                "parameter q 0.5 -> 1.0 and rotation_duration_s 0.85 -> 1.20",
                "motion file target completion 1.35 -> 1.70 s while preserving -105 degree final hold through 5.00 s",
                "case/revision/provenance metadata names",
            ],
            "unchanged_fields": [
                "Boundary=1 native DBC, CFL=.20, dp=.0075 and all Dt controls",
                "full-cup fluid continuum, native lattice and native rho*dp^3 mass",
                "cup, receiver, tray, catchment and runtime domain geometry",
                "5 s event window, observer thresholds and hard audit gates",
                "gravity, EOS, viscosity and no mass rescaling",
            ],
            "motion_proof": motion_proof,
            "solver_control_proof": solver_control_proof,
            "baseline_solver_control_proof": baseline_solver_control_proof,
            "definition_pair_controls_equal": True,
            "qualification_claim": "none",
        },
    })
    prepared["schema"] = "core.cfd.v1"
    prepared["config"] = config
    prepared["definition_audit"] = copy.deepcopy(config["definition_audit"])
    prepared["qualification_only"] = True
    prepared["qualification_claim"] = "none; q=1.0 slow-duration DBC canary only"
    prepared["extension_only"] = False
    prepared.pop("extension_of_prepared", None)
    prepared.pop("extension_of_prepared_sha256", None)
    prepared.pop("source_canary_product", None)
    prepared.pop("source_canary_product_sha256", None)
    prepared["slow_duration_preflight"] = {
        "candidate_q": Q,
        "baseline_rotation_duration_s": BASELINE_ROTATION_DURATION_S,
        "candidate_rotation_duration_s": ROTATION_DURATION_S,
        "motion_proof": motion_proof,
        "solver_control_proof": solver_control_proof,
        "baseline_solver_control_proof": baseline_solver_control_proof,
        "baseline_definition": {
            "path": str(baseline_definition.resolve()),
            "sha256": _sha256(baseline_definition),
        },
        "baseline_extension_prepared": {
            "path": str(extension_path),
            "sha256": _sha256(extension_path),
        },
        "native_equivalence_to_completed_dbc": equivalence,
        "native_equivalence_to_static_anchor": prepared["dynamic_canary_preflight"].get("native_sampling_matches_passed_static"),
        "geometry_asset_reuse_policy": "native BI4/geometry may be reused only because decoded arrays are equal; new XML and motion are independently hash-bound",
        "preflight_scope": "CPU GenCase/native input only; no solver evidence",
    }
    prepared["resource_estimate"] = {
        "host_recommendation": "h200",
        "cpu_cores": 2,
        "ram_mib": 32768,
        "gpu_peak_mib": 12288,
        "timeout_seconds": 14400,
        "io_weight": 2,
        "trajectory_estimate_gib": 1.3,
        "basis": "completed 54720-particle DBC 5 s product used 606 MiB sampled GPU and 1.17 GB trajectory; reservation remains conservative",
    }
    prepared["dynamic_canary_preflight"]["motion_duration_s"] = ROTATION_DURATION_S
    prepared["dynamic_canary_preflight"]["motion_complete_s"] = MOTION_START_S + ROTATION_DURATION_S
    prepared["dynamic_canary_preflight"]["native_equivalence_to_completed_dbc"] = equivalence
    prepared["dynamic_canary_preflight"]["extension_only"] = False
    prepared["provenance"] = {
        "candidate_card": _ref(candidate_path, lab, "reviewed q=1.0 proposal"),
        "dynamics_forensics": _ref(dynamics_path, lab, "read-only 5 s DBC dynamics evidence"),
        "completed_dbc_receipt": _ref(completion_path, lab, "baseline hard-passing but unsettled DBC receipt"),
        "observer_reaudit": _ref(observer_path, lab, "baseline physical-cup metadata correction"),
        "static_anchor_prepared": _ref(static_path, lab, "static prerequisite provenance"),
        "preparation_helper": _ref(Path(__file__).resolve(), lab, "CPU candidate preparation code"),
        "reused_geometry_helper": _ref(Path(base.__file__).resolve(), lab, "GenCase helper implementation"),
    }
    # Build the manifest after GenCase and before writing prepared.json.  The
    # prepared file itself is bound separately by the job spec.
    prepared["inputs"] = {
        str(path.resolve()): _sha256(path)
        for path in output.rglob("*")
        if path.is_file() and path.name != "prepared.json"
    }
    _write_json(prepared_path, prepared)
    return prepared


def prepare(lab: Path, output: Path) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"prepared output must be fresh: {output}")
    _configure_base()
    output.mkdir(parents=True, exist_ok=True)
    prepared = base.prepare_canary(lab, output)
    return _postprocess_prepared(lab, output)


def _add_input(items: list[dict], path: Path, lab: Path, role: str) -> None:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    item = {"path": str(path), "sha256": _sha256(path), "role": role}
    if not any(existing["path"] == item["path"] for existing in items):
        items.append(item)


def make_job(lab: Path, prepared_path: Path, output: Path) -> dict:
    lab, prepared_path, output = Path(lab).resolve(), Path(prepared_path).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    config = prepared["config"]
    if not prepared.get("preflight_pass") or not prepared.get("qualification_only"):
        raise ValueError("q=1.0 prepared input failed CPU preflight or qualification-only contract")
    if config.get("scope_id") != SCOPE_ID or config.get("parameter", {}).get("q") != Q:
        raise ValueError("prepared input is not the q=1.0 slow-duration candidate")
    if abs(float(config["parameter"]["value"]) - ROTATION_DURATION_S) > 1e-12:
        raise ValueError("prepared duration is not 1.20 s")
    if config.get("boundary_method") != 1 or config.get("cfl") != 0.2 or config.get("dp_m") != DP_M:
        raise ValueError("q=1.0 candidate changed a frozen numerical control")
    if config.get("time_max_s") != TIME_MAX_S or config.get("output_interval_s") != OUTPUT_INTERVAL_S:
        raise ValueError("q=1.0 candidate has the wrong event window or output interval")
    output.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[dict] = []
    _add_input(inputs, prepared_path, lab, "prepared manifest")
    for path, digest in sorted(prepared.get("inputs", {}).items()):
        path = Path(path)
        actual = _sha256(path)
        if actual != digest:
            raise ValueError(f"prepared input hash changed: {path}")
        _add_input(inputs, path, lab, "prepared GenCase/input asset")
    source_files = [
        (lab / "scripts/core_f2_qualification.py", "runtime runner"),
        (lab / "scripts/core_cfd.py", "runtime runner dependency"),
        (lab / "scripts/core_f2.py", "runtime runner dependency"),
        (lab / "scripts/finite_wall_audit.py", "runtime audit dependency"),
        (lab / "scripts/f2_full_cup_closed_catchment_dbc.py", "frozen CPU preparation helper provenance"),
        (lab / "scripts/f2_dbc_slow_duration_prepare.py", "candidate preparation provenance"),
        (lab / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64", "pinned solver binary"),
        (lab / "campaigns/l1-resume/artifacts/bi4_dump", "pinned native decoder"),
        (lab / CANDIDATE_CARD_RELATIVE, "candidate card provenance"),
        (lab / DYNAMICS_FORENSICS_RELATIVE, "dynamics evidence provenance"),
    ]
    for path, role in source_files:
        _add_input(inputs, path, lab, role)
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": JOB_ID,
        "logical_id": JOB_ID,
        "attempt_role": "f2_dbc_slow_rotation_duration_canary",
        "category": "f2_dynamic_full_cup_closed_catchment_dbc_duration_canary",
        "host": "h200",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [
            str(lab / ".venv/bin/python"),
            str(lab / "scripts/core_f2_qualification.py"),
            "--lab-root", str(lab),
            "run", "--prepared", str(prepared_path),
            "--output", "{attempt_dir}/product",
        ],
        "required_outputs": [
            "product/result.json",
            "product/trajectory.h5",
            "product/audit.json",
            "product/observations.json",
        ],
        "resources": {
            "cpu_cores": 2,
            "ram_mib": 32768,
            "gpu_peak_mib": 12288,
            "io_weight": 2,
        },
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "split": "qualification_only",
        "qualification_status": "single q=1.0 development canary; no duration matrix or T1 claim",
        "launch_recommendation": "root review/queue only; this spec is not submitted by the preparation agent",
        "submission_status": "not_submitted_by_subagent",
        "input_files": inputs,
        "input_closure": {
            "all_hashes_verified_at_prepare": True,
            "prepared_manifest_path": str(prepared_path),
            "prepared_manifest_sha256": _sha256(prepared_path),
            "input_file_count": len(inputs),
            "runtime_source_snapshot_required": True,
            "solver_binary_hash_bound": True,
            "decoder_hash_bound": True,
            "no_live_lab_import_allowed": True,
        },
        "prepared_case_id": config["case_id"],
        "scope_id": config["scope_id"],
        "revision_id": config["revision_id"],
        "family": "F2",
        "registered_window_s": TIME_MAX_S,
        "maximum_extended_window_s": TIME_MAX_S,
        "motion_start_s": MOTION_START_S,
        "rotation_duration_s": ROTATION_DURATION_S,
        "motion_complete_s": MOTION_START_S + ROTATION_DURATION_S,
        "angle_degrees": ANGLE_DEGREES,
        "boundary_method": "native DBC Boundary=1",
        "cfl": 0.2,
        "dp_m": DP_M,
        "physical_geometry_changed": False,
        "motion_protocol_changed": True,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "viscosity_changed": False,
        "static_anchor_is_prerequisite_only": True,
        "observer_contract": config["wall_audit_contract"],
        "gate_policy": {
            "event_window_complete_required": True,
            "settle_speed_p95_m_s_max": 0.10,
            "settle_kinetic_fraction_max": 0.05,
            "settle_hold_s": 0.20,
            "post_settle_observation_s": 0.35,
            "no_missing_native_fluid_ids": True,
            "no_threshold_relaxation": True,
            "no_further_horizon_extension": True,
        },
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0; output is attempt_dir/product",
        "provenance": prepared["provenance"],
    }
    _write_json(output, spec)
    return spec


def make_review(lab: Path, prepared_path: Path, job_path: Path, output: Path) -> dict:
    lab, prepared_path, job_path, output = (
        Path(lab).resolve(), Path(prepared_path).resolve(), Path(job_path).resolve(), Path(output).resolve()
    )
    prepared = json.loads(prepared_path.read_text())
    job = json.loads(job_path.read_text())
    if not prepared.get("preflight_pass") or not prepared.get("slow_duration_preflight", {}).get("motion_proof", {}).get("pass"):
        raise ValueError("prepared q=1 input is not CPU-preflighted")
    if job.get("submission_status") != "not_submitted_by_subagent":
        raise ValueError("refuse review after job submission status changed")
    checked = []
    bad = []
    for item in job["input_files"]:
        path = Path(item["path"])
        if not path.is_file():
            bad.append({"path": str(path), "reason": "missing"})
            continue
        actual = _sha256(path)
        checked.append(str(path))
        if actual != item["sha256"]:
            bad.append({"path": str(path), "expected": item["sha256"], "actual": actual})
    if bad:
        raise ValueError(f"job input hash verification failed: {bad}")
    prepared_product = prepared_path.parent
    forbidden_outputs = [
        str(path.relative_to(prepared_product))
        for path in prepared_product.iterdir()
        if path.name in {"result.json", "trajectory.h5", "audit.json", "observations.json"}
    ]
    if forbidden_outputs:
        raise ValueError(f"prepared directory unexpectedly contains solver product: {forbidden_outputs}")
    result = {
        "schema": "core.f2.dbc_slow_duration.preparation_review.v1",
        "created_at": _stamp(),
        "family": "F2",
        "candidate_id": "F2_dbc_slow_rotation_duration_q1p0_canary",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualification_claim": "none; CPU prepared canary only",
        "prepared": _ref(prepared_path, lab, "q=1.0 prepared manifest"),
        "job": _ref(job_path, lab, "unsubmitted root-review job spec"),
        "candidate_card": _ref(lab / CANDIDATE_CARD_RELATIVE, lab, "candidate design card"),
        "dynamics_forensics": _ref(lab / DYNAMICS_FORENSICS_RELATIVE, lab, "baseline dynamics evidence"),
        "preflight": {
            "preflight_pass": bool(prepared["preflight_pass"]),
            "qualification_only": bool(prepared["qualification_only"]),
            "motion_proof": prepared["slow_duration_preflight"]["motion_proof"],
            "solver_control_proof": prepared["slow_duration_preflight"]["solver_control_proof"],
            "native_equivalence_to_completed_dbc": prepared["slow_duration_preflight"]["native_equivalence_to_completed_dbc"],
            "native_equivalence_to_static_anchor": prepared["slow_duration_preflight"]["native_equivalence_to_static_anchor"],
            "native_input_hash_count": len(prepared.get("inputs", {})),
            "job_input_hash_count": len(job.get("input_files", [])),
            "job_inputs_checked": len(checked),
            "job_input_hashes_pass": not bad,
        },
        "configuration_contract": {
            "boundary_method": prepared["config"]["boundary_method"],
            "cfl": prepared["config"]["cfl"],
            "dp_m": prepared["config"]["dp_m"],
            "visco_treatment": prepared["slow_duration_preflight"]["solver_control_proof"]["actual"]["ViscoTreatment"],
            "visco": prepared["slow_duration_preflight"]["solver_control_proof"]["actual"]["Visco"],
            "time_max_s": prepared["config"]["time_max_s"],
            "output_interval_s": prepared["config"]["output_interval_s"],
            "rotation_duration_s": prepared["config"]["parameter"]["value"],
            "motion_complete_s": MOTION_START_S + ROTATION_DURATION_S,
            "physical_geometry_changed": prepared["config"]["physical_geometry_changed"],
            "initial_condition_changed": prepared["config"]["initial_condition_changed"],
            "mass_rescaling": prepared["config"]["mass_rescaling"],
        },
        "resources": job["resources"],
        "required_outputs": job["required_outputs"],
        "execution_status": "CPU GenCase and native preflight complete; solver not invoked; GPU not submitted; ledger not written",
        "solver_product_present": False,
        "input_closure": job["input_closure"],
        "review_code": _ref(Path(__file__).resolve(), lab, "preparation and closure verifier"),
    }
    _write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--output", type=Path, default=PREPARED_RELATIVE)
    job_parser = sub.add_parser("make-job")
    job_parser.add_argument("--prepared", type=Path, default=PREPARED_RELATIVE / "prepared.json")
    job_parser.add_argument("--output", type=Path, default=JOB_RELATIVE)
    review_parser = sub.add_parser("review")
    review_parser.add_argument("--prepared", type=Path, default=PREPARED_RELATIVE / "prepared.json")
    review_parser.add_argument("--job", type=Path, default=JOB_RELATIVE)
    review_parser.add_argument("--output", type=Path, default=REVIEW_RELATIVE)
    args = parser.parse_args()
    lab = args.lab_root.resolve()
    if args.command == "prepare":
        result = prepare(lab, (lab / args.output).resolve() if not args.output.is_absolute() else args.output)
        print(json.dumps({
            "preflight_pass": result["preflight_pass"],
            "qualification_only": result["qualification_only"],
            "scope_id": result["config"]["scope_id"],
            "case_id": result["config"]["case_id"],
            "rotation_duration_s": result["config"]["parameter"]["value"],
            "motion_proof": result["slow_duration_preflight"]["motion_proof"],
            "native_equivalence_to_completed_dbc": result["slow_duration_preflight"]["native_equivalence_to_completed_dbc"],
        }, indent=2))
    elif args.command == "make-job":
        prepared = (lab / args.prepared).resolve() if not args.prepared.is_absolute() else args.prepared
        output = (lab / args.output).resolve() if not args.output.is_absolute() else args.output
        result = make_job(lab, prepared, output)
        print(json.dumps({
            "job_id": result["job_id"],
            "host": result["host"],
            "input_file_count": len(result["input_files"]),
            "submission_status": result["submission_status"],
            "resources": result["resources"],
            "required_outputs": result["required_outputs"],
        }, indent=2))
    else:
        prepared = (lab / args.prepared).resolve() if not args.prepared.is_absolute() else args.prepared
        job = (lab / args.job).resolve() if not args.job.is_absolute() else args.job
        output = (lab / args.output).resolve() if not args.output.is_absolute() else args.output
        result = make_review(lab, prepared, job, output)
        print(json.dumps({
            "schema": result["schema"],
            "prepared_sha256": result["prepared"]["sha256"],
            "job_sha256": result["job"]["sha256"],
            "job_input_hashes_pass": result["preflight"]["job_input_hashes_pass"],
            "solver_product_present": result["solver_product_present"],
            "execution_status": result["execution_status"],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
