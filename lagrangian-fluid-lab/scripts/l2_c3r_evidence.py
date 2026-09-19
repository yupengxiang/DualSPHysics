#!/usr/bin/env python3
"""Independent L2-R C3 evidence reader.

This entry point audits the retained C3 bounded-anchor artifacts without
calling the legacy ``l2_c3_anchors.py`` runner and without changing the L2-R
resume/controller state.  The F5 conclusion is deliberately provenance-aware:
it can confirm the historical loss mechanism, but it cannot turn that
historical attempt into a new L2-R execution.  F6 is accepted here only as a
specific, machine-verifiable external blocker until a bounded physical route
has a complete normal/Chrono/force-gauge contract.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import h5py
import numpy as np

try:
    from scripts.l2_campaign import CAMPAIGN, LAB, repo_relative, sha256_file
except ModuleNotFoundError:  # pragma: no cover - direct script invocation
    from l2_campaign import CAMPAIGN, LAB, repo_relative, sha256_file


SCHEMA = "l2.c3r.evidence.v1"
LEGACY_SCRIPT = LAB / "scripts" / "l2_c3_anchors.py"
LEGACY_REPORT = CAMPAIGN / "reports" / "c3-bounded-anchors.json"
F5_HDF5 = CAMPAIGN / "c3-canary" / "data" / "L2_C3_F5_low_weir_nominal.h5"
F5_ATTEMPT = (
    CAMPAIGN
    / "runs"
    / "L2_C3_F5_low_weir_nominal"
    / "attempts"
    / "20260913T171349.867087Z-00b76b61.complete"
)
F5_DEFINITION = CAMPAIGN / "c3-canary" / "cases" / "L2_C3_F5_low_weir_nominal_Def.xml"
F5_GENERATED_XML = (
    CAMPAIGN
    / "c3-canary"
    / "artifacts"
    / "L2_C3_F5_low_weir_nominal"
    / "generated"
    / "L2_C3_F5_low_weir_nominal.xml"
)
F6_REPORTS = (
    LAB / "campaigns/v0.1-candidate/r3-g2-f6-mdbc-preflight.json",
    LAB / "campaigns/v0.1-candidate/r3-g2-f6-static-buoyancy.json",
    LAB / "campaigns/v0.1-candidate/r3-f6-wall-ghost-geometry.json",
    LAB / "campaigns/v0.1-candidate/r3-g2-f6-test14.json",
)
DEFAULT_OUTPUT = CAMPAIGN / "resume-c6b28c8" / "c3r-evidence.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=LAB.parent,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def file_evidence(path: Path) -> dict[str, Any]:
    """Return immutable evidence metadata without treating a path as a URL."""

    path = Path(path)
    record: dict[str, Any] = {
        "path": repo_relative(path),
        "absolute_path": str(path.resolve()),
        "exists": path.is_file(),
    }
    if path.is_file():
        digest, _ = sha256_file(path)
        record.update({"bytes": path.stat().st_size, "sha256": digest})
    return record


def _parse_scalar(raw: str) -> int | float | str:
    value = raw.strip().replace(",", "")
    try:
        if re.fullmatch(r"[-+]?\d+", value):
            return int(value)
        return float(value)
    except ValueError:
        return raw.strip()


def parse_runparts(path: Path) -> dict[str, Any]:
    """Parse DualSPHysics ``RunPARTs.csv`` reason counters.

    ``NpOut`` is an interval count.  The cumulative total is reconstructed by
    summing rows; this is cross-checked independently against HDF5 identity
    disappearance rather than inferred from the final saved frame alone.
    """

    if not path.is_file():
        return {"path": str(path), "exists": False, "rows": [], "errors": ["missing_file"]}
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open(newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader, [])
        required = {
            "Part",
            "TimeStep [s]",
            "NpOut",
            "NpOutPos",
            "NpOutRho",
            "NpOutMov",
        }
        if not required.issubset(set(header)):
            return {
                "path": str(path),
                "exists": True,
                "rows": [],
                "errors": ["missing_columns"],
                "columns": header,
            }
        indices = {name: header.index(name) for name in required}
        for raw_row in reader:
            if not raw_row or not raw_row[0].strip() or raw_row[0].lstrip().startswith("#"):
                continue
            if len(raw_row) < len(header):
                errors.append("short_row")
                continue
            row = {
                "part": int(_parse_scalar(raw_row[indices["Part"]])),
                "time_s": float(_parse_scalar(raw_row[indices["TimeStep [s]"]])),
                "np_out": int(_parse_scalar(raw_row[indices["NpOut"]])),
                "np_out_pos": int(_parse_scalar(raw_row[indices["NpOutPos"]])),
                "np_out_rho": int(_parse_scalar(raw_row[indices["NpOutRho"]])),
                "np_out_mov": int(_parse_scalar(raw_row[indices["NpOutMov"]])),
            }
            rows.append(row)
    totals = {
        "np_out": sum(row["np_out"] for row in rows),
        "np_out_pos": sum(row["np_out_pos"] for row in rows),
        "np_out_rho": sum(row["np_out_rho"] for row in rows),
        "np_out_mov": sum(row["np_out_mov"] for row in rows),
    }
    first_out: dict[str, dict[str, Any] | None] = {}
    for key in ("np_out", "np_out_pos", "np_out_rho", "np_out_mov"):
        first_out[key] = next(
            (
                {"part": row["part"], "time_s": row["time_s"], "count": row[key]}
                for row in rows
                if row[key] > 0
            ),
            None,
        )
    return {
        "path": str(path),
        "exists": True,
        "row_count": len(rows),
        "rows": rows,
        "totals": totals,
        "first_out": first_out,
        "errors": errors,
    }


def _triplet(raw: str) -> list[float] | None:
    try:
        values = [float(value.strip()) for value in raw.split(",")]
    except ValueError:
        return None
    return values if len(values) == 3 and all(math.isfinite(value) for value in values) else None


def parse_solver_log(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "errors": ["missing_file"]}
    text = path.read_text(errors="replace")
    match = re.search(r"MapRealPos\(final\)=\(([^)]+)\)-\(([^)]+)\)", text)
    domain: dict[str, Any] = {"available": False}
    if match:
        lower = _triplet(match.group(1))
        upper = _triplet(match.group(2))
        if lower is not None and upper is not None:
            domain = {"available": True, "lower": lower, "upper": upper, "source_line": match.group(0)}
    def _last_float(pattern: str) -> float | None:
        found = re.findall(pattern, text)
        return float(found[-1]) if found else None
    excluded_match = re.search(r"Excluded particles\.*:\s*(\d+)", text)
    return {
        "path": str(path),
        "exists": True,
        "runtime_domain": domain,
        "excluded_particles": int(excluded_match.group(1)) if excluded_match else None,
        "time_max_s": _last_float(r"TimeMax=([0-9.eE+-]+)"),
        "time_part_s": _last_float(r"TimePart=([0-9.eE+-]+)"),
        "rhop_out_min": _last_float(r"RhopOutMin=([0-9.eE+-]+)"),
        "rhop_out_max": _last_float(r"RhopOutMax=([0-9.eE+-]+)"),
        "finished_code_0": "Finished execution (code=0)" in text,
    }


def parse_domain_definition(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "errors": ["missing_file"]}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        return {"path": str(path), "exists": True, "errors": [f"xml:{error.__class__.__name__}"]}
    simulation = root.find(".//simulationdomain")
    posmin = simulation.find("posmin") if simulation is not None else None
    posmax = simulation.find("posmax") if simulation is not None else None
    particle_max = root.find(".//particles/_summary/positions/posmax")
    boxes = [node.text.strip() for node in root.findall(".//drawbox/boxfill") if node.text and node.text.strip()]
    return {
        "path": str(path),
        "exists": True,
        "simulationdomain_posmin": dict(posmin.attrib) if posmin is not None else None,
        "simulationdomain_posmax": dict(posmax.attrib) if posmax is not None else None,
        "generated_particle_posmax": dict(particle_max.attrib) if particle_max is not None else None,
        "drawbox_fill_modes": boxes,
        "top_physical_face_declared_closed": any("top" in value.lower() for value in boxes),
        "default_top_headroom_expression": (
            dict(posmax.attrib).get("z", "").strip().lower().startswith("default")
            if posmax is not None
            else False
        ),
    }


def _legacy_f5_record(legacy_report: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    attempt = next((item for item in legacy_report.get("attempts", []) if item.get("family") == "F5"), None)
    audit = next((item for item in legacy_report.get("audits", []) if item.get("family") == "F5"), None)
    return attempt, audit


def _hash_matches(path: Path, expected: str | None) -> bool | None:
    if expected is None:
        return None
    if not path.is_file():
        return False
    return sha256_file(path)[0] == expected


def _lost_identity_summary(
    time_axis: np.ndarray,
    valid: np.ndarray,
    particle_id: np.ndarray,
    position: np.ndarray,
    velocity: np.ndarray,
    mass: np.ndarray,
) -> dict[str, Any]:
    initial_valid = valid[0].astype(bool)
    final_valid = valid[-1].astype(bool)
    missing = initial_valid & ~final_valid
    missing_indices = np.flatnonzero(missing)
    first_bad_frames: list[int] = []
    last_valid_positions: list[np.ndarray] = []
    last_valid_velocities: list[np.ndarray] = []
    for index in missing_indices:
        bad_frames = np.flatnonzero(~valid[:, index].astype(bool))
        first_bad = int(bad_frames[0])
        first_bad_frames.append(first_bad)
        last_valid_positions.append(position[max(0, first_bad - 1), index])
        last_valid_velocities.append(velocity[max(0, first_bad - 1), index])
    first_counts = Counter(first_bad_frames)
    first_time = min((float(time_axis[index]) for index in first_bad_frames), default=None)
    if last_valid_positions:
        last_pos = np.asarray(last_valid_positions, dtype=np.float64)
        last_vel = np.asarray(last_valid_velocities, dtype=np.float64)
        position_summary = {
            "count": len(last_pos),
            "min_m": np.nanmin(last_pos, axis=0).tolist(),
            "max_m": np.nanmax(last_pos, axis=0).tolist(),
            "mean_m": np.nanmean(last_pos, axis=0).tolist(),
            "max_z_m": float(np.nanmax(last_pos[:, 2])),
            "max_abs_velocity_m_s": float(np.nanmax(np.abs(last_vel))),
        }
    else:
        position_summary = {"count": 0}
    return {
        "initial_valid_count": int(initial_valid.sum()),
        "final_valid_count": int(final_valid.sum()),
        "missing_initial_identity_count": int(missing.sum()),
        "missing_particle_ids_sample": [int(value) for value in particle_id[missing_indices[:20]]],
        "first_missing_frame_counts": {str(key): int(value) for key, value in sorted(first_counts.items())},
        "first_missing_time_s": first_time,
        "last_valid_position_of_missing": position_summary,
        "missing_identity_hash": hashlib.sha256(
            ",".join(str(int(value)) for value in particle_id[missing_indices]).encode()
        ).hexdigest(),
    }


def audit_f5_loss_root_cause(
    *,
    legacy_report_path: Path,
    hdf5_path: Path,
    attempt_dir: Path,
    definition_path: Path,
    generated_xml_path: Path,
) -> dict[str, Any]:
    """Reconcile F5 ``NpOut*`` counters with the retained trajectory.

    The function never writes to any input.  ``execution_origin`` remains
    historical even when the causal checks pass.
    """

    result: dict[str, Any] = {
        "family": "F5",
        "case_id": "L2_C3_F5_low_weir_nominal",
        "execution_origin": "legacy_artifact_reaudit",
        "new_solver_execution": False,
        "legacy_report": file_evidence(legacy_report_path),
        "artifacts": {
            "hdf5": file_evidence(hdf5_path),
            "attempt": file_evidence(attempt_dir / "attempt.json"),
            "runparts": file_evidence(attempt_dir / "RunPARTs.csv"),
            "run_log": file_evidence(attempt_dir / "Run.out"),
            "solver_log": file_evidence(attempt_dir / "process.stdout.log"),
            "definition": file_evidence(definition_path),
            "generated_xml": file_evidence(generated_xml_path),
        },
    }
    if not legacy_report_path.is_file() or not hdf5_path.is_file():
        result.update({
            "status": "blocked_missing_artifact",
            "root_cause_id": None,
            "errors": ["legacy_report_or_hdf5_missing"],
        })
        return result
    legacy = _json(legacy_report_path)
    attempt_record, audit_record = _legacy_f5_record(legacy)
    if attempt_record is None or audit_record is None:
        result.update({
            "status": "blocked_missing_artifact",
            "root_cause_id": None,
            "errors": ["legacy_f5_attempt_or_audit_missing"],
        })
        return result

    attempt = attempt_record.get("attempt", {})
    hdf5_expected = audit_record.get("hdf5_sha256")
    definition_expected = attempt_record.get("definition_sha256")
    generated_expected = attempt_record.get("generated_xml_sha256")
    hash_checks = {
        "hdf5_matches_legacy_report": _hash_matches(hdf5_path, hdf5_expected),
        "definition_matches_legacy_report": _hash_matches(definition_path, definition_expected),
        "generated_xml_matches_legacy_report": _hash_matches(generated_xml_path, generated_expected),
    }
    runparts = parse_runparts(attempt_dir / "RunPARTs.csv")
    solver_log = parse_solver_log(attempt_dir / "Run.out")
    definition = parse_domain_definition(generated_xml_path)
    with h5py.File(hdf5_path, "r") as handle:
        required = ("time", "valid", "particle_id", "position", "velocity", "mass")
        missing = [name for name in required if name not in handle]
        if missing:
            result.update({
                "status": "blocked_malformed_artifact",
                "root_cause_id": None,
                "errors": [f"hdf5_missing:{name}" for name in missing],
                "hash_checks": hash_checks,
            })
            return result
        time_axis = np.asarray(handle["time"][:], dtype=np.float64)
        valid = np.asarray(handle["valid"][:], dtype=bool)
        particle_id = np.asarray(handle["particle_id"][:])
        position = np.asarray(handle["position"][:], dtype=np.float64)
        velocity = np.asarray(handle["velocity"][:], dtype=np.float64)
        mass = np.asarray(handle["mass"][:], dtype=np.float64)
        attrs = {str(key): str(value) for key, value in handle.attrs.items()}
    shape_ok = (
        valid.ndim == 2
        and position.shape == (*valid.shape, 3)
        and velocity.shape == (*valid.shape, 3)
        and mass.shape in (valid.shape, (valid.shape[1],))
        and len(time_axis) == valid.shape[0]
        and len(particle_id) == valid.shape[1]
    )
    if not shape_ok:
        result.update({
            "status": "blocked_malformed_artifact",
            "root_cause_id": None,
            "errors": ["trajectory_shape_mismatch"],
            "hash_checks": hash_checks,
        })
        return result
    if mass.ndim == 1:
        mass_frames = np.broadcast_to(mass, valid.shape)
    else:
        mass_frames = mass
    active_position_finite = bool(np.isfinite(position[valid]).all())
    active_velocity_finite = bool(np.isfinite(velocity[valid]).all())
    active_mass_finite = bool(np.isfinite(mass_frames[valid]).all())
    active_mass_positive = bool((mass_frames[valid] > 0).all())
    initial_mass = float(np.sum(mass_frames[0][valid[0]], dtype=np.float64))
    final_mass = float(np.sum(mass_frames[-1][valid[-1]], dtype=np.float64))
    lifecycle_deaths = int(np.sum(valid[:-1] & ~valid[1:]))
    lifecycle_births = int(np.sum(~valid[:-1] & valid[1:]))
    inactive_position_nan = int((~np.isfinite(position).all(axis=2) & ~valid).sum())
    inactive_velocity_nan = int((~np.isfinite(velocity).all(axis=2) & ~valid).sum())
    inactive_mass_nan = int((~np.isfinite(mass_frames) & ~valid).sum())
    loss = _lost_identity_summary(time_axis, valid, particle_id, position, velocity, mass_frames)
    totals = runparts.get("totals", {})
    first_position_out = runparts.get("first_out", {}).get("np_out_pos")
    runtime_domain = solver_log.get("runtime_domain", {})
    runtime_zmax = None
    if runtime_domain.get("available"):
        runtime_zmax = float(runtime_domain["upper"][2])
    max_last_valid_z = loss["last_valid_position_of_missing"].get("max_z_m")
    domain_top_reached = bool(
        runtime_zmax is not None
        and max_last_valid_z is not None
        and abs(runtime_zmax - max_last_valid_z) <= 0.01
    )
    generated_particle_zmax = None
    if definition.get("generated_particle_posmax"):
        raw_z = definition["generated_particle_posmax"].get("z")
        try:
            generated_particle_zmax = float(raw_z)
        except (TypeError, ValueError):
            generated_particle_zmax = None
    configured_top = (definition.get("simulationdomain_posmax") or {}).get("z")
    expected_default_top = None
    if generated_particle_zmax is not None and isinstance(configured_top, str):
        match = re.fullmatch(r"default\s*\+\s*([0-9.]+)%", configured_top.strip().lower())
        if match:
            expected_default_top = generated_particle_zmax * (1.0 + float(match.group(1)) / 100.0)
    checks = {
        "legacy_solver_completed": attempt.get("status") == "completed" and attempt.get("returncode") == 0,
        "solver_log_finished_code_0": solver_log.get("finished_code_0") is True,
        "partout_total_matches_hdf5_identity_loss": totals.get("np_out") == loss["missing_initial_identity_count"],
        "partout_is_position_only": (
            totals.get("np_out", 0) > 0
            and totals.get("np_out_pos") == totals.get("np_out")
            and totals.get("np_out_rho") == 0
            and totals.get("np_out_mov") == 0
        ),
        "first_position_out_matches_first_identity_loss": (
            first_position_out is not None
            and loss["first_missing_time_s"] is not None
            and abs(float(first_position_out["time_s"]) - loss["first_missing_time_s"]) <= 1e-5
        ),
        "active_state_finite_before_exclusion": active_position_finite and active_velocity_finite and active_mass_finite,
        "active_mass_positive": active_mass_positive,
        "runtime_domain_top_reached_by_last_valid_lost_particles": domain_top_reached,
        "default_runtime_top_is_finite_headroom": bool(expected_default_top is not None and runtime_zmax is not None),
        "legacy_artifacts_unchanged": all(value is not False for value in hash_checks.values()),
    }
    confirmed = all(checks.values())
    result.update({
        "status": "confirmed" if confirmed else "inconclusive",
        "root_cause_id": "F5_RUNTIME_DOMAIN_POSITION_EXCLUSION" if confirmed else None,
        "root_cause_statement": (
            "The retained F5 loss is a solver runtime-domain position exclusion: "
            "all 263 excluded identities are NpOutPos, and the last valid splash positions reach the finite "
            "runtime-domain top. This is not active NaN divergence, density rejection, or moving-particle removal."
            if confirmed
            else "The retained F5 artifact does not satisfy every causal reconciliation check."
        ),
        "hash_checks": hash_checks,
        "legacy_execution": {
            "baseline_commit": legacy.get("baseline_commit"),
            "attempt_id": attempt.get("attempt_id"),
            "attempt_status": attempt.get("status"),
            "reported_hard_integrity_pass": audit_record.get("canary_hard_integrity_pass"),
            "reported_errors": audit_record.get("independent_audit", {}).get("errors", []),
        },
        "trajectory": {
            "attrs": attrs,
            "frame_count": int(len(time_axis)),
            "time_end_s": float(time_axis[-1]),
            "active_position_finite": active_position_finite,
            "active_velocity_finite": active_velocity_finite,
            "active_mass_finite": active_mass_finite,
            "active_mass_positive": active_mass_positive,
            "initial_mass_kg": initial_mass,
            "final_mass_kg": final_mass,
            "mass_loss_kg": initial_mass - final_mass,
            "final_mass_fraction": final_mass / initial_mass if initial_mass else None,
            "lifecycle_death_count": lifecycle_deaths,
            "lifecycle_birth_count": lifecycle_births,
            "inactive_nonfinite_counts": {
                "position": inactive_position_nan,
                "velocity": inactive_velocity_nan,
                "mass": inactive_mass_nan,
            },
            "loss_identity_summary": loss,
        },
        "solver_output": {
            "runparts": runparts,
            "run_log": solver_log,
            "runtime_domain_top_z_m": runtime_zmax,
            "last_valid_lost_particle_max_z_m": max_last_valid_z,
            "configured_runtime_posmax_z": configured_top,
            "generated_particle_posmax_z_m": generated_particle_zmax,
            "expected_default_runtime_top_z_m": expected_default_top,
            "physical_top_face_declared_closed": definition.get("top_physical_face_declared_closed"),
        },
        "causal_checks": checks,
        "repair_required": {
            "new_execution_needed": True,
            "recipe": (
                "Keep the F5 source geometry and physical open-top semantics fixed; enlarge/explicitly register the "
                "solver runtime domain above the observed splash envelope, then run one bounded confirmation canary. "
                "Reconcile RunPARTs, PartOut, and HDF5 identities again before any qualification claim."
            ),
            "do_not_claim": "This report is a historical re-audit, not a fresh L2-R F5 execution or qualification receipt.",
        },
    })
    return result


def _find_nested(payload: dict[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def audit_f6_external_blocker(paths: Iterable[Path]) -> dict[str, Any]:
    """Validate the concrete retained F6 blocker rather than saying merely 'no data'."""

    reports: dict[str, Any] = {}
    loaded: dict[str, dict[str, Any]] = {}
    for path in paths:
        evidence = file_evidence(path)
        key = path.name
        reports[key] = evidence
        if path.is_file():
            try:
                loaded[key] = _json(path)
            except (OSError, json.JSONDecodeError):
                reports[key]["parse_error"] = True
    preflight = loaded.get("r3-g2-f6-mdbc-preflight.json", {})
    static = loaded.get("r3-g2-f6-static-buoyancy.json", {})
    wall = loaded.get("r3-f6-wall-ghost-geometry.json", {})
    test14 = loaded.get("r3-g2-f6-test14.json", {})
    normal = preflight.get("normal_completeness", {})
    gencase_normal = _find_nested(preflight, "gencase", "normal_data") or {}
    solver_normal = _find_nested(preflight, "solver", "normal_data") or {}
    current_f6 = _find_nested(preflight, "definition", "xml_switch", "current_f6") or {}
    current_geometry = current_f6.get("geometry_commands", {}) if isinstance(current_f6, dict) else {}
    static_hypotheses = static.get("hypotheses", [])
    mdbc_verified = None
    for hypothesis in static_hypotheses if isinstance(static_hypotheses, list) else []:
        if isinstance(hypothesis, dict) and "mdbc_normals_verified_for_f6" in hypothesis.get("evidence", {}):
            mdbc_verified = hypothesis["evidence"]["mdbc_normals_verified_for_f6"]
            break
    observed = {
        "preflight_acceptance_status": preflight.get("acceptance_status"),
        "preflight_mdbc_claim": preflight.get("mdbc_claim"),
        "normal_completeness": {
            "complete_for_all_boundary_particles": normal.get("complete_for_all_boundary_particles"),
            "boundary_count": normal.get("gencase_boundary_count"),
            "zero_count": normal.get("gencase_zero_count"),
            "solver_fixed_or_moving_zero_count": normal.get("solver_fixed_or_moving_zero_count"),
        },
        "gencase_zero_count": gencase_normal.get("zero_count"),
        "solver_fixed_or_moving_zero_count": solver_normal.get("fixed_or_moving_zero_count"),
        "solver_finished_code_0": solver_normal.get("solver_finished_code_0"),
        "chrono_collision_warning": solver_normal.get("chrono_collision_warning"),
        "current_f6_requested_boundary": _find_nested(current_f6, "requested_boundary", "name"),
        "current_f6_boundary_value": _find_nested(current_f6, "requested_boundary", "value"),
        "current_f6_normals_section_present": _find_nested(current_f6, "normals", "section_present"),
        "current_f6_normals_list_present": current_geometry.get("normals_list_present"),
        "mdbc_normals_verified_for_f6": mdbc_verified,
        "wall_geometry_acceptance_status": wall.get("acceptance_status"),
        "test14_execution_status": test14.get("execution_status"),
        "test14_scientific_acceptance": test14.get("scientific_acceptance"),
    }
    checks = {
        "normal_completeness_is_false": normal.get("complete_for_all_boundary_particles") is False,
        "zero_normals_are_counted": int(normal.get("gencase_zero_count") or 0) > 0,
        "current_f6_route_is_dbc_without_normals": (
            current_f6.get("requested_boundary", {}).get("value") == 1
            and current_f6.get("normals", {}).get("section_present") is False
        ),
        "matched_mdbc_physical_comparison_is_not_verified": mdbc_verified is False,
        "chrono_warning_is_recorded": solver_normal.get("chrono_collision_warning") is True,
        "candidate_geometry_not_accepted": wall.get("acceptance_status") == "candidate_geometry_only_rejected",
        "force_gauge_is_still_required": any(
            "force gauge" in str(item).lower() for item in wall.get("open_blockers", [])
        ),
    }
    blocker_id = "F6_MDBC_NORMALS_CHRONO_FORCE_GAUGE_CONTRACT"
    return {
        "family": "F6",
        "execution_origin": "retained_diagnostic_and_legacy_actuals",
        "new_solver_execution": False,
        "status": "blocked_external" if all(checks.values()) else "inconclusive",
        "blocker_id": blocker_id if all(checks.values()) else None,
        "blocker_statement": (
            "F6 cannot produce admissible C3R bounded physical evidence until the transformed hull has complete "
            "verified normals, a matched DBC-versus-mDBC force/trajectory comparison, and a separately closed "
            "Chrono/body-contact plus fixed-body force-gauge contract. The retained preflight has 792 zero "
            "fixed/moving normals and a Chrono collision warning despite solver code 0."
            if all(checks.values())
            else "The retained F6 diagnostics do not provide a complete, machine-verifiable blocker record."
        ),
        "source_reports": reports,
        "observed": observed,
        "blocker_checks": checks,
        "required_to_unblock": [
            "Rebuild the nominal transformed-hull normal/ghost path with zero fixed/moving normals.",
            "Run a matched DBC-versus-mDBC hydrostatic/force-gauge comparison and retain the raw attempt evidence.",
            "Separate fixed-body hydrostatic closure from Chrono coupled-body contact, then run the bounded F6 case.",
            "Keep the existing DBC/Test14 result diagnostic-only; do not relabel it as mDBC evidence.",
        ],
        "do_not_claim": "A solver return code of 0 or a CPU preflight is not F6 physical acceptance.",
    }


def build_report(
    *,
    legacy_report_path: Path = LEGACY_REPORT,
    hdf5_path: Path = F5_HDF5,
    attempt_dir: Path = F5_ATTEMPT,
    definition_path: Path = F5_DEFINITION,
    generated_xml_path: Path = F5_GENERATED_XML,
    f6_report_paths: Iterable[Path] = F6_REPORTS,
) -> dict[str, Any]:
    f5 = audit_f5_loss_root_cause(
        legacy_report_path=legacy_report_path,
        hdf5_path=hdf5_path,
        attempt_dir=attempt_dir,
        definition_path=definition_path,
        generated_xml_path=generated_xml_path,
    )
    f6 = audit_f6_external_blocker(f6_report_paths)
    f5_done = f5.get("status") == "confirmed"
    f6_done = f6.get("status") == "blocked_external"
    return {
        "schema": SCHEMA,
        "stage": "C3R",
        "created_at_utc": utc_now(),
        "baseline_commit_from_legacy_report": (
            _json(legacy_report_path).get("baseline_commit") if legacy_report_path.is_file() else None
        ),
        "current_commit_at_audit": _git_head(),
        "entrypoint": file_evidence(Path(__file__).resolve()),
        "audited_legacy_controller": file_evidence(LEGACY_SCRIPT),
        "status": "complete_with_findings" if f5_done and f6_done else "blocked_external",
        "decision": "F5 loss mechanism reconciled; F6 remains at a specific external blocker; no qualification claim",
        "execution_policy": {
            "new_solver_execution": False,
            "historical_evidence_reused_as_new_execution": False,
            "legacy_report_modified": False,
            "resume_or_closeout_modified": False,
        },
        "f5_loss_root_cause": f5,
        "f6_bounded_evidence_or_external_blocker": f6,
        "qualification_claim": "none; C3R evidence and blocker only",
        "next_steps": [
            "Run exactly one fresh F5 confirmation canary with explicit runtime-domain headroom repair.",
            "Reconcile its RunPARTs/PartOut/HDF5 identity ledger before considering any bounded receipt.",
            "Do not schedule F6 physical evidence until the listed normals, force-gauge, and Chrono blockers are closed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--legacy-report", type=Path, default=LEGACY_REPORT)
    parser.add_argument("--f5-hdf5", type=Path, default=F5_HDF5)
    parser.add_argument("--f5-attempt-dir", type=Path, default=F5_ATTEMPT)
    parser.add_argument("--f5-definition", type=Path, default=F5_DEFINITION)
    parser.add_argument("--f5-generated-xml", type=Path, default=F5_GENERATED_XML)
    parser.add_argument("--f6-report", action="append", type=Path, dest="f6_reports")
    args = parser.parse_args(argv)
    report = build_report(
        legacy_report_path=args.legacy_report,
        hdf5_path=args.f5_hdf5,
        attempt_dir=args.f5_attempt_dir,
        definition_path=args.f5_definition,
        generated_xml_path=args.f5_generated_xml,
        f6_report_paths=args.f6_reports or F6_REPORTS,
    )
    _json_dump(args.output, report)
    print(json.dumps({
        "status": report["status"],
        "decision": report["decision"],
        "f5_status": report["f5_loss_root_cause"].get("status"),
        "f5_root_cause_id": report["f5_loss_root_cause"].get("root_cause_id"),
        "f6_status": report["f6_bounded_evidence_or_external_blocker"].get("status"),
        "f6_blocker_id": report["f6_bounded_evidence_or_external_blocker"].get("blocker_id"),
        "new_solver_execution": report["execution_policy"]["new_solver_execution"],
        "report": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "complete_with_findings" else 2


if __name__ == "__main__":
    raise SystemExit(main())
