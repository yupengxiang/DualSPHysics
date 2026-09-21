#!/usr/bin/env python3
"""Prepare a read-only, one-time F2 slow-duration horizon-extension canary.

This module starts from the completed q=1.0, 5 s slow-duration DBC canary.
It changes only the registered observation horizon from 5 s to 10 s, together
with the necessary motion-file hold and XML TimeMax representation.  The
prescribed rotation still reaches -105 degrees at 1.70 s and holds there.
It performs CPU GenCase/native preflight and writes an unsubmitted proposal
and job spec.  It never runs the solver, submits to the central queue, or
writes a ledger.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_qualification as f2q

SCHEMA = "core.f2.dbc_slow_duration_horizon_extension.preparation.v1"
JOB_SCHEMA = "core.cfd.job.v1"
FAMILY = "F2"
BASE_SCOPE_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_x_v1"
SCOPE_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_horizon_extension_x_v1"
REVISION_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_horizon_extension10s_v1"
CASE_ID = "CORE_F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_q1p00000000_extension10s_canary"
JOB_ID = "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-slow-duration-extension10s-canary-v1-001"
Q = 1.0
DP_M = 0.0075
ROTATION_DURATION_S = 1.20
BASELINE_ROTATION_DURATION_S = 0.85
MOTION_START_S = 0.50
ANGLE_DEGREES = -105.0
BASELINE_HORIZON_S = 5.0
EXTENDED_HORIZON_S = 10.0
OUTPUT_INTERVAL_S = 0.01
SETTLE_SPEED_M_S = 0.10
SETTLE_KE_FRACTION = 0.05
SETTLE_HOLD_S = 0.20
POST_SETTLE_OBSERVATION_S = 0.35

BASE_PREPARED_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_q1p0_v1/prepared.json"
)
BASE_EVIDENCE_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-slow-duration-q1p0-terminal-root-v1/terminal-evidence-v2.json"
)
PARAMETER_CARD_RELATIVE = Path("campaigns/core-v1/cfd/f2-dbc-duration-qualification-parameter-card-v1.json")
OUTPUT_RELATIVE = Path(
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_extension10s_v1"
)
PROPOSAL_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-slow-duration-extension10s-canary-proposal-v1.json"
)
JOB_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-slow-duration-extension10s-canary-job-v1.json"
)
PREFLIGHT_RELATIVE = Path(
    "campaigns/core-v1/cfd/f2-dbc-slow-duration-extension10s-preflight-v1.json"
)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def ref(path: Path, lab: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path),
        "relative_to_lab": str(path.relative_to(lab.resolve())),
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def set_parameter(root: ET.Element, key: str, value: str | int | float) -> None:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        parameters = root.find(".//execution/parameters")
        if parameters is None:
            raise ValueError(f"definition has no execution parameters for {key}")
        node = ET.SubElement(parameters, "parameter", {"key": key})
    node.set("value", str(value))


def motion_angle(time_s: float) -> float:
    return f2q.motion_angle(float(time_s), ROTATION_DURATION_S, ANGLE_DEGREES)


def write_motion(path: Path) -> None:
    rows = ["#Time;Degrees"]
    times = np.arange(0.0, EXTENDED_HORIZON_S + OUTPUT_INTERVAL_S * 0.1, OUTPUT_INTERVAL_S)
    for time_s in times:
        rows.append(f"{float(time_s):.6f};{motion_angle(float(time_s)):.9f}")
    path.write_text("\n".join(rows) + "\n")


def motion_proof(definition: Path, motion: Path) -> dict[str, Any]:
    root = ET.parse(definition).getroot()
    mvrots = root.findall(".//mvrotfile")
    if not mvrots:
        raise ValueError("definition has no mvrotfile")
    if any(node.find("file") is None for node in mvrots):
        raise ValueError("definition has malformed mvrotfile")
    rows = []
    for line in motion.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            time_text, angle_text = line.split(";", 1)
            rows.append((float(time_text), float(angle_text)))
    if not rows:
        raise ValueError("motion file is empty")
    target_indices = [i for i, (_, angle) in enumerate(rows) if abs(angle - ANGLE_DEGREES) <= 1e-8]
    target_time = MOTION_START_S + ROTATION_DURATION_S
    if not target_indices or abs(rows[target_indices[0]][0] - target_time) > OUTPUT_INTERVAL_S + 1e-7:
        raise ValueError("motion target completion time is not 1.70 s")
    if abs(rows[-1][1] - ANGLE_DEGREES) > 1e-8 or abs(rows[-1][0] - EXTENDED_HORIZON_S) > 1e-7:
        raise ValueError("motion file does not hold target through 10 s")
    filenames = {node.find("file").get("name") for node in mvrots}
    durations = {float(node.get("duration")) for node in mvrots}
    return {
        "mvrotfile_count": len(mvrots),
        "definition_mvrotfile_durations_s": sorted(durations),
        "definition_motion_filenames": sorted(filenames),
        "motion_file_first_time_s": rows[0][0],
        "motion_file_first_angle_degrees": rows[0][1],
        "requested_rotation_duration_s": ROTATION_DURATION_S,
        "expected_target_time_s": target_time,
        "first_target_time_s": rows[target_indices[0]][0],
        "first_target_angle_degrees": rows[target_indices[0]][1],
        "last_time_s": rows[-1][0],
        "last_angle_degrees": rows[-1][1],
        "target_hold_present": True,
        "pass": bool(
            durations == {EXTENDED_HORIZON_S}
            and filenames == {motion.name}
            and abs(rows[target_indices[0]][0] - target_time) <= OUTPUT_INTERVAL_S + 1e-7
        ),
    }


def controls(definition: Path) -> dict[str, Any]:
    root = ET.parse(definition).getroot()
    cfl = root.find(".//cflnumber")
    if cfl is None:
        raise ValueError("definition has no cflnumber")
    params = {node.get("key"): node.get("value") for node in root.findall(".//execution/parameters/parameter")}
    required = ("Boundary", "SlipMode", "ViscoTreatment", "Visco", "DtIni", "DtMin", "DtFixed", "TimeMax", "TimeOut")
    if any(key not in params for key in required):
        raise ValueError("definition misses a required solver control")
    begins = root.findall(".//begin")
    return {
        "cflnumber": float(cfl.get("value")),
        "Boundary": int(params["Boundary"]),
        "SlipMode": int(params["SlipMode"]),
        "ViscoTreatment": int(params["ViscoTreatment"]),
        "Visco": float(params["Visco"]),
        "DtIni": float(params["DtIni"]),
        "DtMin": float(params["DtMin"]),
        "DtFixed": float(params["DtFixed"]),
        "TimeMax": float(params["TimeMax"]),
        "TimeOut": float(params["TimeOut"]),
        "begin_finish_s": sorted({float(node.get("finish")) for node in begins}),
    }


def domain(definition: Path) -> dict[str, list[float]]:
    root = ET.parse(definition).getroot()
    return f2q._runtime_domain_from_xml(root)


def decode_arrays(prefix: Path, decoder: Path) -> tuple[Any, ...]:
    with tempfile.TemporaryDirectory(prefix="f2-horizon-native-") as folder:
        return core_cfd.native_frame(prefix.with_suffix(".bi4"), Path(folder) / "native", decoder)[:5]


def native_equivalence(base_prefix: Path, extension_prefix: Path, decoder: Path) -> dict[str, Any]:
    left = decode_arrays(base_prefix, decoder)
    right = decode_arrays(extension_prefix, decoder)
    arrays_equal = [bool(np.array_equal(left[index], right[index])) for index in range(4)]
    metadata_diff = {
        str(key): [left[4].get(key), right[4].get(key)]
        for key in set(left[4]) | set(right[4])
        if left[4].get(key) != right[4].get(key)
    }
    return {
        "ids_equal": arrays_equal[0],
        "positions_equal": arrays_equal[1],
        "velocities_equal": arrays_equal[2],
        "density_equal": arrays_equal[3],
        "metadata_differences": metadata_diff,
        "only_case_name_metadata_changed": set(metadata_diff) <= {"CaseName"},
        "pass": bool(all(arrays_equal) and set(metadata_diff) <= {"CaseName"}),
        "base_fluid_count": int(left[4].get("CaseNfluid", -1)),
        "extension_fluid_count": int(right[4].get("CaseNfluid", -1)),
    }


def observed_basis(evidence: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    times = np.asarray(observations["time_s"], dtype=float)
    speed = np.asarray(observations["speed_p95_m_s"], dtype=float)
    kinetic = np.asarray(observations["kinetic_energy_over_initial_potential"], dtype=float)
    post = times >= (MOTION_START_S + ROTATION_DURATION_S)
    both = post & (speed <= SETTLE_SPEED_M_S) & (kinetic <= SETTLE_KE_FRACTION)
    return {
        "source_terminal_evidence": evidence.get("schema"),
        "source_horizon_s": BASELINE_HORIZON_S,
        "source_requested_horizon_reached": evidence["audit"]["requested_horizon_reached"],
        "source_hard_integrity_pass": evidence["audit"]["hard_integrity_pass"],
        "source_event_window_complete": evidence["audit"]["event_window_complete"],
        "source_qualified": evidence["audit"]["qualified"],
        "motion_complete_s": MOTION_START_S + ROTATION_DURATION_S,
        "sampled_frame_count": int(len(times)),
        "last_time_s": float(times[-1]),
        "post_motion_min_speed_p95_m_s": float(np.min(speed[post])),
        "post_motion_final_speed_p95_m_s": float(speed[-1]),
        "post_motion_min_kinetic_fraction": float(np.min(kinetic[post])),
        "post_motion_final_kinetic_fraction": float(kinetic[-1]),
        "settle_speed_threshold_m_s": SETTLE_SPEED_M_S,
        "settle_kinetic_threshold_fraction": SETTLE_KE_FRACTION,
        "simultaneous_settle_frames": int(np.sum(both)),
        "settled_event_time_s": observations.get("event_times_s", {}).get("settled"),
        "interpretation": "KE crossed its threshold but speed-p95 did not; the required conjunction was never observed by 5 s",
    }


def make_definition(base_prepared: dict[str, Any], output: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    base_def = Path(base_prepared["definition_audit"]["definition"]).resolve()
    if not base_def.is_file():
        raise FileNotFoundError(base_def)
    case_def = output / f"{CASE_ID}_Def.xml"
    case_motion = output / f"{CASE_ID}_motion.dat"
    tree = ET.parse(base_def)
    root = tree.getroot()
    for mvrot in root.findall(".//mvrotfile"):
        mvrot.set("duration", f"{EXTENDED_HORIZON_S:.17g}")
        file_node = mvrot.find("file")
        if file_node is None:
            raise ValueError("baseline mvrotfile has no file")
        file_node.set("name", case_motion.name)
    for begin in root.findall(".//begin"):
        begin.set("finish", f"{EXTENDED_HORIZON_S:.17g}")
    set_parameter(root, "TimeMax", EXTENDED_HORIZON_S)
    set_parameter(root, "TimeOut", OUTPUT_INTERVAL_S)
    # No geometry, domain, boundary, material, initial state, CFL or Dt field is touched.
    ET.indent(tree, space="    ")
    tree.write(case_def, encoding="utf-8", xml_declaration=True)
    write_motion(case_motion)
    return case_def, case_motion, controls(case_def), motion_proof(case_def, case_motion)


def prepare(lab: Path, output: Path, proposal_path: Path) -> dict[str, Any]:
    lab, output, proposal_path = Path(lab).resolve(), Path(output).resolve(), Path(proposal_path).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"prepared output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    base_path = lab / BASE_PREPARED_RELATIVE
    evidence_path = lab / BASE_EVIDENCE_RELATIVE
    card_path = lab / PARAMETER_CARD_RELATIVE
    base = json.loads(base_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    observations_path = lab / "campaigns/core-v1/cfd/f2-dbc-slow-duration-q1p0-terminal-root-v1/product/observations.json"
    observations = json.loads(observations_path.read_text())
    basis = observed_basis(evidence, observations)
    if base.get("preflight_pass") is not True or base.get("qualification_only") is not True:
        raise ValueError("baseline prepared input is not a passing qualification-only canary")
    if base["config"].get("time_max_s") != BASELINE_HORIZON_S:
        raise ValueError("baseline prepared horizon is not 5 s")
    if evidence["scientific_conclusion"]["event_window_complete"] is not False:
        raise ValueError("source terminal evidence is not the expected right-censored canary")
    if evidence["scientific_conclusion"]["hard_integrity_pass"] is not True:
        raise ValueError("source canary did not hard-pass; this extension basis is invalid")
    if not np.isclose(basis["post_motion_min_speed_p95_m_s"], 0.3504738636643466, atol=1e-9):
        raise ValueError("unexpected source observation; refuse to prepare from changed evidence")

    case_def, case_motion, new_controls, motion = make_definition(base, output)
    generated_dir = output / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    prefix = generated_dir / CASE_ID
    gencase = lab / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
    command = [str(gencase), str(case_def.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"GenCase failed; inspect {output / 'gencase.log'}")
    generated_xml = prefix.with_suffix(".xml")
    if not generated_xml.is_file() or not prefix.with_suffix(".bi4").is_file():
        raise ValueError("GenCase did not create generated XML and BI4")
    generated_controls = controls(generated_xml)
    generated_domain = domain(generated_xml)
    base_generated_xml = Path(base["generated_prefix"] + ".xml").resolve()
    base_domain = domain(base_generated_xml)
    if generated_domain != base_domain:
        raise ValueError("extension changed runtime domain")
    expected = {
        "cflnumber": 0.2, "Boundary": 1, "SlipMode": 1, "ViscoTreatment": 1,
        "Visco": 0.03, "DtIni": 0.0, "DtMin": 0.0, "DtFixed": 0.0,
        "TimeMax": EXTENDED_HORIZON_S, "TimeOut": OUTPUT_INTERVAL_S,
        "begin_finish_s": [EXTENDED_HORIZON_S],
    }
    if generated_controls != expected:
        raise ValueError(f"generated controls differ from extension contract: {generated_controls}")
    equivalence = native_equivalence(Path(base["generated_prefix"]), prefix, Path(base["decoder"]))
    if not equivalence["pass"]:
        raise ValueError(f"extension changed native initial arrays: {equivalence}")
    if not motion["pass"]:
        raise ValueError("extension motion proof failed")

    config = copy.deepcopy(base["config"])
    config.update({
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "stage": "horizon_extension_canary",
        "split": "qualification_only",
        "qualification_only": True,
        "qualified": False,
        "time_max_s": EXTENDED_HORIZON_S,
        "maximum_extended_time_s": EXTENDED_HORIZON_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "physical_case_id": "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_slow_duration_v1",
        "lineage_group_id": SCOPE_ID,
        "repair_candidate_id": "slow_duration_horizon_extension",
        "physical_geometry_changed": False,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "qualification_claim": "none; one-time horizon-extension canary only",
        "event_window": {
            **copy.deepcopy(config.get("event_window", {})),
            "registered_initial_window_s": EXTENDED_HORIZON_S,
            "maximum_extended_window_s": EXTENDED_HORIZON_S,
            "motion_source_file_duration_s": EXTENDED_HORIZON_S,
            "right_censor_policy": "10 s is the single one-time doubled horizon; a missing required event remains failed and no further horizon extension is permitted",
        },
        "control_semantics": "same centered cosine rotation; reaches -105 degrees at 1.70 s and holds; only the saved/solver horizon is doubled from 5 s to 10 s",
        "repair_hypothesis": {
            "id": "slow_duration_horizon_extension",
            "mechanism_class": "event_window_completeness",
            "single_scientific_change": "registered full-window horizon 5.0 -> 10.0 s by one-time 2x right-censor rule",
            "motion_representation_change": "extend the target-angle hold and mvrotfile/TimeMax representation to 10 s; angle, start, duration and solver physics unchanged",
            "all_physics_unchanged": True,
            "rationale": "the 5 s q=1.0 canary hard-passed and retained every native identity, but KE and speed-p95 did not satisfy the conjunction; the plan permits one 2x horizon extension before declaring right censoring",
            "no_extrapolated_qualification": True,
        },
        "definition_audit": {
            "source_definition": str(base["definition_audit"]["definition"]),
            "source_definition_sha256": digest(Path(base["definition_audit"]["definition"])),
            "definition": str(case_def),
            "definition_sha256": digest(case_def),
            "motion_file": str(case_motion),
            "motion_sha256": digest(case_motion),
            "baseline_generated_definition": str(base_generated_xml),
            "baseline_generated_definition_sha256": digest(base_generated_xml),
            "generated_definition": str(generated_xml),
            "generated_definition_sha256": digest(generated_xml),
            "changed_fields": [
                "TimeMax 5.0 -> 10.0 s",
                "mvrotfile duration and begin finish 5.0 -> 10.0 s",
                "motion-file target hold extends from 5.0 -> 10.0 s",
                "case/scope/revision/provenance metadata",
            ],
            "unchanged_fields": [
                "rotation duration 1.20 s, motion start 0.50 s, target -105 degrees",
                "native DBC Boundary=1, CFL=.20, dp=.0075 and all Dt controls",
                "full-cup/catchment geometry, runtime domain and initial native lattice",
                "gravity, EOS, viscosity, mass policy and all event thresholds",
                "output cadence TimeOut=.01 s",
            ],
            "generated_controls": generated_controls,
            "baseline_controls": controls(base_generated_xml),
            "motion_proof": motion,
            "native_equivalence_to_baseline": equivalence,
            "qualification_claim": "none",
        },
    })
    prepared = copy.deepcopy(base)
    prepared.update({
        "schema": "core.cfd.v1",
        "created_at": stamp(),
        "config": config,
        "generated_prefix": str(prefix),
        "source_template": str(base["definition_audit"]["definition"]),
        "source_template_sha256": digest(Path(base["definition_audit"]["definition"])),
        "qualification_only": True,
        "qualification_claim": "none; one-time F2 horizon-extension canary only",
        "extension_only": True,
        "extension_of_prepared": {"path": str(base_path), "sha256": digest(base_path)},
        "extension_of_terminal_evidence": {"path": str(evidence_path), "sha256": digest(evidence_path)},
        "definition_audit": copy.deepcopy(config["definition_audit"]),
        "horizon_extension_preflight": {
            "previous_horizon_s": BASELINE_HORIZON_S,
            "extended_horizon_s": EXTENDED_HORIZON_S,
            "rule": "one-time 2x extension after right-censored required event",
            "basis": basis,
            "motion_proof": motion,
            "generated_controls": generated_controls,
            "baseline_controls": controls(base_generated_xml),
            "runtime_domain_equal": generated_domain == base_domain,
            "native_equivalence_to_baseline": equivalence,
            "preflight_scope": "CPU GenCase/native input only; no solver evidence",
        },
        "resource_estimate": {
            "host_recommendation": "h200",
            "cpu_cores": 2,
            "ram_mib": 32768,
            "gpu_peak_mib": 12288,
            "timeout_seconds": 21600,
            "io_weight": 2,
            "trajectory_estimate_gib": 2.6,
            "basis": "same 54720-particle source and .01 s cadence; horizon doubled from 5 to 10 s, with 1.3 GiB source estimate scaled by frame count",
        },
    })
    # Bind every fresh prepared input; the runtime will not trust an unbound XML, BI4 or motion file.
    prepared["inputs"] = {
        str(path.resolve()): digest(path)
        for path in output.rglob("*")
        if path.is_file()
    }
    prepared["preflight_pass"] = bool(
        equivalence["pass"] and motion["pass"] and generated_domain == base_domain
        and generated_controls == expected and prepared["config"]["time_max_s"] == EXTENDED_HORIZON_S
    )
    write_json(output / "prepared.json", prepared)

    proposal = {
        "schema": "core.f2.dbc_slow_duration_horizon_extension.canary_proposal.v1",
        "created_at": stamp(),
        "family": FAMILY,
        "candidate_id": "F2_dbc_slow_rotation_duration_horizon_extension10s_canary",
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "status": "design_only_cpu_preflight_no_solver_no_queue",
        "qualification_only": True,
        "qualification_claim": "none; this canary cannot populate the 15-cell duration matrix or establish T1",
        "gpu_launch_by_subagent": False,
        "central_queue_mutation": 0,
        "registration_basis": {
            "previous_registered_horizon_s": BASELINE_HORIZON_S,
            "previous_canary_right_censored": True,
            "hard_integrity_pass": True,
            "one_time_extension_rule": "T_extension = 2 * T_previous",
            "derived_extension_horizon_s": EXTENDED_HORIZON_S,
            "post_extension_no_further_extension": True,
            "source_parameter_card": ref(card_path, lab, "existing F2 duration registration"),
            "basis_evidence": ref(evidence_path, lab, "completed q=1.0 5 s terminal evidence"),
            "observed_basis": basis,
        },
        "single_change": {
            "scientific_variable": "full event-window horizon",
            "previous_s": BASELINE_HORIZON_S,
            "candidate_s": EXTENDED_HORIZON_S,
            "implementation_fields": ["TimeMax", "mvrotfile duration", "begin finish", "motion-file hold endpoint"],
            "physical_motion_unchanged": {
                "rotation_duration_s": ROTATION_DURATION_S,
                "motion_start_s": MOTION_START_S,
                "target_angle_degrees": ANGLE_DEGREES,
                "target_reached_s": MOTION_START_S + ROTATION_DURATION_S,
            },
        },
        "fixed_contract": {
            "boundary_method": "native DBC Boundary=1",
            "cfl": 0.2,
            "dp_m": DP_M,
            "output_interval_s": OUTPUT_INTERVAL_S,
            "DtIni": 0.0,
            "DtMin": 0.0,
            "DtFixed": 0.0,
            "visco_treatment": 1,
            "visco": 0.03,
            "geometry": "same full-cup/catchment/receiver/tray and runtime domain",
            "initial_condition": "native initial arrays exactly equal to 5 s canary",
            "mass_policy": "native rho*dp^3; no rescaling",
            "event_thresholds": {
                "speed_p95_m_s_max": SETTLE_SPEED_M_S,
                "kinetic_fraction_max": SETTLE_KE_FRACTION,
                "settle_hold_s": SETTLE_HOLD_S,
                "post_settle_observation_s": POST_SETTLE_OBSERVATION_S,
                "receiver_fraction": 0.01,
                "spill_fraction": 0.01,
            },
        },
        "acceptance": {
            "must_reach_requested_horizon": True,
            "must_pass_hard_integrity": True,
            "must_observe_motion_complete_receiver_contact_and_settled": True,
            "must_save_post_settle_observation_s": POST_SETTLE_OBSERVATION_S,
            "failure_if_10s_right_censored": True,
            "failure_if_hard_integrity_fails": True,
            "no_threshold_relaxation": True,
            "no_future_truth_or_survivor_renormalization": True,
            "qualification_claim_on_pass": "still canary evidence only; root may separately review a fresh 13+2 matrix",
        },
        "artifacts": {
            "prepared": ref(output / "prepared.json", lab, "CPU-prepared extension manifest"),
            "proposal": {"path": str(proposal_path), "relative_to_lab": str(proposal_path.relative_to(lab)), "role": "this proposal"},
        },
        "submission": {
            "job_spec_path": str((lab / JOB_RELATIVE).resolve()),
            "status": "unsubmitted_root_review_required",
            "ledger_mutation": 0,
            "scheduler_job_id": None,
        },
    }
    write_json(proposal_path, proposal)
    return prepared


def make_job(lab: Path, prepared_path: Path, output: Path, proposal_path: Path) -> dict[str, Any]:
    lab, prepared_path, output, proposal_path = map(Path, (lab, prepared_path, output, proposal_path))
    lab, prepared_path, output, proposal_path = lab.resolve(), prepared_path.resolve(), output.resolve(), proposal_path.resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass") or not prepared.get("extension_only"):
        raise ValueError("prepared extension failed preflight")
    if prepared["config"].get("time_max_s") != EXTENDED_HORIZON_S:
        raise ValueError("prepared extension horizon mismatch")
    # The proposal is deliberately kept separate from the scheduler, but its
    # status must reflect that this local job spec now exists.  Update it
    # before binding the proposal hash into the job so the provenance remains
    # self-consistent and still records that no submission occurred.
    proposal = json.loads(proposal_path.read_text())
    proposal.setdefault("submission", {}).update({
        "status": "job_spec_created_unsubmitted_root_review_required",
        "ledger_mutation": 0,
        "scheduler_job_id": None,
    })
    write_json(proposal_path, proposal)
    inputs = [{"path": str(prepared_path), "sha256": digest(prepared_path), "role": "prepared extension manifest"}]
    for path, sha in sorted(prepared.get("inputs", {}).items()):
        p = Path(path)
        if digest(p) != sha:
            raise ValueError(f"prepared input changed: {p}")
        inputs.append({"path": str(p), "sha256": sha, "role": "prepared extension input"})
    for p, role in [
        (lab / "scripts/core_f2_qualification.py", "runtime runner"),
        (lab / "scripts/core_cfd.py", "runtime dependency"),
        (lab / "scripts/core_f2.py", "runtime dependency"),
        (lab / "scripts/finite_wall_audit.py", "runtime dependency"),
        (lab / "scripts/f2_dbc_slow_duration_extension_prepare.py", "extension preparation provenance"),
        (lab / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64", "pinned solver binary"),
        (lab / "campaigns/l1-resume/artifacts/bi4_dump", "pinned decoder"),
        (lab / BASE_EVIDENCE_RELATIVE, "source terminal evidence"),
        (lab / PARAMETER_CARD_RELATIVE, "duration parameter card"),
    ]:
        item = {"path": str(p.resolve()), "sha256": digest(p), "role": role}
        if not any(x["path"] == item["path"] for x in inputs):
            inputs.append(item)
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": JOB_ID,
        "logical_id": JOB_ID,
        "attempt_role": "f2_slow_duration_horizon_extension_canary",
        "category": "f2_dynamic_full_cup_closed_catchment_dbc_horizon_extension_canary",
        "host": "h200",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(lab / "scripts/core_f2_qualification.py"), "--lab-root", str(lab), "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 21600,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "split": "qualification_only",
        "qualification_status": "one-time horizon-extension development canary; not a duration matrix row and no T1 claim",
        "launch_recommendation": "root review/queue only; this preparation agent did not submit",
        "submission_status": "not_submitted_by_subagent",
        "input_files": inputs,
        "input_closure": {"all_hashes_verified_at_prepare": True, "prepared_manifest_path": str(prepared_path), "prepared_manifest_sha256": digest(prepared_path), "input_file_count": len(inputs), "runtime_source_snapshot_required": True, "solver_binary_hash_bound": True, "decoder_hash_bound": True, "no_live_lab_import_allowed": True},
        "prepared_case_id": prepared["config"]["case_id"],
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "family": FAMILY,
        "registered_window_s": EXTENDED_HORIZON_S,
        "maximum_extended_window_s": EXTENDED_HORIZON_S,
        "motion_start_s": MOTION_START_S,
        "rotation_duration_s": ROTATION_DURATION_S,
        "motion_complete_s": MOTION_START_S + ROTATION_DURATION_S,
        "angle_degrees": ANGLE_DEGREES,
        "boundary_method": "native DBC Boundary=1",
        "cfl": 0.2,
        "dp_m": DP_M,
        "physical_geometry_changed": False,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "horizon_extension_only": True,
        "observer_contract": prepared["config"]["wall_audit_contract"],
        "gate_policy": {"event_window_complete_required": True, "settle_speed_p95_m_s_max": SETTLE_SPEED_M_S, "settle_kinetic_fraction_max": SETTLE_KE_FRACTION, "settle_hold_s": SETTLE_HOLD_S, "post_settle_observation_s": POST_SETTLE_OBSERVATION_S, "no_threshold_relaxation": True, "no_further_horizon_extension": True},
        "provenance": {"proposal": {"path": str(proposal_path), "sha256": digest(proposal_path)}, "prepared": {"path": str(prepared_path), "sha256": digest(prepared_path)}},
    }
    write_json(output, spec)
    return spec


def review(lab: Path, prepared_path: Path, job_path: Path, proposal_path: Path, output: Path) -> dict[str, Any]:
    lab, prepared_path, job_path, proposal_path, output = [Path(x).resolve() for x in (lab, prepared_path, job_path, proposal_path, output)]
    prepared = json.loads(prepared_path.read_text())
    job = json.loads(job_path.read_text())
    proposal = json.loads(proposal_path.read_text())
    if job.get("submission_status") != "not_submitted_by_subagent":
        raise ValueError("job is no longer marked unsubmitted")
    bad = []
    for item in job["input_files"]:
        p = Path(item["path"])
        if not p.is_file():
            bad.append({"path": str(p), "reason": "missing"})
        elif digest(p) != item["sha256"]:
            bad.append({"path": str(p), "reason": "hash_mismatch", "expected": item["sha256"], "actual": digest(p)})
    if bad:
        raise ValueError(f"job input hash verification failed: {bad}")
    forbidden = [str(p.relative_to(prepared_path.parent)) for p in prepared_path.parent.iterdir() if p.name in {"result.json", "trajectory.h5", "audit.json", "observations.json"}]
    result = {
        "schema": "core.f2.dbc_slow_duration_horizon_extension.preflight.v1",
        "created_at": stamp(),
        "family": FAMILY,
        "candidate_id": proposal["candidate_id"],
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "qualification_claim": "none; CPU-prepared unsubmitted canary only",
        "proposal": ref(proposal_path, lab, "horizon-extension proposal"),
        "prepared": ref(prepared_path, lab, "CPU-prepared extension manifest"),
        "job": ref(job_path, lab, "unsubmitted root-review job spec"),
        "preflight_pass": bool(prepared.get("preflight_pass")),
        "extension_only": bool(prepared.get("extension_only")),
        "native_equivalence_to_baseline": prepared["horizon_extension_preflight"]["native_equivalence_to_baseline"],
        "motion_proof": prepared["horizon_extension_preflight"]["motion_proof"],
        "baseline_controls": prepared["horizon_extension_preflight"]["baseline_controls"],
        "generated_controls": prepared["horizon_extension_preflight"]["generated_controls"],
        "runtime_domain_equal": prepared["horizon_extension_preflight"]["runtime_domain_equal"],
        "job_input_hash_count": len(job["input_files"]),
        "job_input_hashes_pass": not bad,
        "solver_product_present": bool(forbidden),
        "unexpected_solver_product_files": forbidden,
        "execution_status": "CPU GenCase and native preflight complete; solver not invoked; central queue untouched; ledger not written",
        "submission_status": "not_submitted_by_subagent",
        "gate_policy": job["gate_policy"],
        "registration_basis": proposal["registration_basis"],
    }
    write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--output", type=Path, default=OUTPUT_RELATIVE)
    p.add_argument("--proposal", type=Path, default=PROPOSAL_RELATIVE)
    p = sub.add_parser("make-job")
    p.add_argument("--prepared", type=Path, default=OUTPUT_RELATIVE / "prepared.json")
    p.add_argument("--proposal", type=Path, default=PROPOSAL_RELATIVE)
    p.add_argument("--output", type=Path, default=JOB_RELATIVE)
    p = sub.add_parser("review")
    p.add_argument("--prepared", type=Path, default=OUTPUT_RELATIVE / "prepared.json")
    p.add_argument("--job", type=Path, default=JOB_RELATIVE)
    p.add_argument("--proposal", type=Path, default=PROPOSAL_RELATIVE)
    p.add_argument("--output", type=Path, default=PREFLIGHT_RELATIVE)
    args = parser.parse_args()
    lab = args.lab_root.resolve()
    def resolve(value: Path) -> Path:
        return value.resolve() if value.is_absolute() else (lab / value).resolve()
    if args.command == "prepare":
        p = prepare(lab, resolve(args.output), resolve(args.proposal))
        print(json.dumps({"preflight_pass": p["preflight_pass"], "extension_only": p["extension_only"], "horizon_s": p["config"]["time_max_s"], "native_equivalence": p["horizon_extension_preflight"]["native_equivalence_to_baseline"]}, indent=2, sort_keys=True))
    elif args.command == "make-job":
        j = make_job(lab, resolve(args.prepared), resolve(args.output), resolve(args.proposal))
        print(json.dumps({"job_id": j["job_id"], "submission_status": j["submission_status"], "input_file_count": len(j["input_files"]), "horizon_s": j["registered_window_s"]}, indent=2, sort_keys=True))
    else:
        r = review(lab, resolve(args.prepared), resolve(args.job), resolve(args.proposal), resolve(args.output))
        print(json.dumps({"schema": r["schema"], "preflight_pass": r["preflight_pass"], "job_input_hashes_pass": r["job_input_hashes_pass"], "solver_product_present": r["solver_product_present"], "submission_status": r["submission_status"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
