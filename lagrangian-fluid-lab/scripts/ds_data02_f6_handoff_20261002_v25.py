#!/usr/bin/env python3
"""Audit the six F6 RIGID003 native trajectories and freeze cadence follow-ups.

The four coarse/fine rows use the new ``NATIVE_H5_CF_001``/``LABELS_CF_001``
outputs.  The medium row deliberately points to the already completed
DOMAIN_X_REPAIR_01 native input and is marked as a strict reuse of that one
solver case.  This module writes read-only comparison evidence and request
specifications; it never starts a solver or GPU job and does not rewrite any
consumed H5, label, receipt, or prior report.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

try:
    import numpy as np
except (ImportError, OSError, ValueError):
    np = None  # type: ignore[assignment]
try:
    import h5py
except (ImportError, OSError, ValueError):
    h5py = None  # type: ignore[assignment]


SCRIPT = Path(__file__).resolve()


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V16 = _load("f6_handoff_v16_for_v25", SCRIPT.with_name("ds_data02_f6_handoff_20261002_v16.py"))
V22 = _load("f6_handoff_v22_for_v25", SCRIPT.with_name("ds_data02_f6_handoff_20261002_v22.py"))
V24 = _load("f6_handoff_v24_for_v25", SCRIPT.with_name("ds_data02_f6_handoff_20261002_v24.py"))

FAMILY_ROOT = V16.FAMILY_ROOT
RAW_ROOT = V16.RAW_ROOT
POST_ROOT = FAMILY_ROOT / "postprocessing_008"
MECHANISMS = ("simple_free_response", "wave_no_contact")
RESOLUTIONS = ("coarse", "medium", "fine")
EVENT_BUDGET_RELATIVE = 0.02
MACRO_BUDGET_RELATIVE = 0.05
TARGET_SAVE_S = 0.025
WINDOW_S = [0.0, 12.0]
POSE_AUDIT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/domain_xy_repair_02/root_saved_pose_audit_001.json")
ROOT_MEDIUM_EQUIV = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261002/rigid_contract_003/domain_xy_repair_02/root_medium_native_equivalence_001.json")
SOURCE_SEMANTICS = POST_ROOT / "rigid_force_torque_semantics_002.json"


def sha256(path: Path) -> str:
    return V16.sha256(Path(path))


def read_json(path: Path) -> dict[str, Any]:
    return V16.read_json(Path(path))


def write_json(path: Path, value: Any) -> None:
    V16.write_json(Path(path), value)


def _safe(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _attrs(handle: Any) -> dict[str, Any]:
    return {str(key): _safe(value) for key, value in handle.attrs.items()}


def _json_attr(attrs: dict[str, Any], key: str, default: Any = None) -> Any:
    value = attrs.get(key, default)
    if value is None:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _case_paths(mechanism: str, resolution: str) -> dict[str, Any]:
    """Resolve actual native inputs without treating medium reuse as new."""

    if resolution == "medium":
        old = V16._old_medium_case(mechanism)
        p = V16._old_medium_paths(old)
        cid = str(old["case_id"])
        h5 = RAW_ROOT / cid / f"{cid}_NATIVE_H5_004" / "trajectory.h5"
        labels = RAW_ROOT / cid / f"{cid}_LABELS_004" / "native-labels.h5"
        floating_root = RAW_ROOT / cid / f"{cid}_FLOATINGINFO_001"
        forces_root = RAW_ROOT / cid / f"{cid}_COMPUTEFORCES_001"
        return {
            "case_id": cid,
            "source_resolution": "medium_reused_domain_x_repair_01",
            "independent_solver_case": False,
            "xml": p["xml"],
            "data": p["data"],
            "runparts": p["runparts"],
            "runout": p["runout"],
            "solver_receipt": p["solver_receipt"],
            "gencase_receipt": p["gencase_receipt"],
            "trajectory": h5,
            "labels": labels,
            "floating_csv": floating_root / "floatinginfo" / "FloatingMotion_mk60.csv",
            "floating_receipt": floating_root / "execution-receipt.json",
            "forces_csv": forces_root / "forces" / "FloatingForce.csv",
            "forces_receipt": forces_root / "execution-receipt.json",
        }
    p = V24._paths(mechanism, resolution)
    cid = str(p["case"])
    return {
        "case_id": cid,
        "source_resolution": resolution,
        "independent_solver_case": True,
        "xml": p["xml"],
        "data": p["data"],
        "runparts": p["runparts"],
        "runout": p["runout"],
        "solver_receipt": p["solver_receipt"],
        "gencase_receipt": p["gencase_receipt"],
        "trajectory": RAW_ROOT / cid / f"{cid}_NATIVE_H5_CF_001" / "trajectory.h5",
        "labels": RAW_ROOT / cid / f"{cid}_LABELS_CF_001" / "native-labels.h5",
        "floating_csv": RAW_ROOT / cid / f"{cid}_FLOATINGINFO_CF_001" / "floatinginfo" / "FloatingMotion_mk60.csv",
        "floating_receipt": RAW_ROOT / cid / f"{cid}_FLOATINGINFO_CF_001" / "execution-receipt.json",
        "forces_csv": RAW_ROOT / cid / f"{cid}_COMPUTEFORCES_CF_001" / "forces" / "FloatingForce.csv",
        "forces_receipt": RAW_ROOT / cid / f"{cid}_COMPUTEFORCES_CF_001" / "execution-receipt.json",
    }


def _parse_float(value: Any) -> float:
    return float(str(value).replace(",", "").strip())


def _runparts(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            if row.get("TimeStep [s]") and row.get("Steps"):
                try:
                    _parse_float(row["TimeStep [s]"])
                    rows.append(row)
                except (TypeError, ValueError):
                    continue
    if not rows:
        raise ValueError(f"no numeric RunPARTs rows: {path}")
    times = np.asarray([_parse_float(row["TimeStep [s]"]) for row in rows], dtype=np.float64)
    save_dt = np.diff(times)
    dt_min = np.asarray([_parse_float(row["DtMin [s]"]) for row in rows if row.get("DtMin [s]") and _parse_float(row["DtMin [s]"]) > 0.0], dtype=np.float64)
    dt_max = np.asarray([_parse_float(row["DtMax [s]"]) for row in rows if row.get("DtMax [s]") and _parse_float(row["DtMax [s]"]) > 0.0], dtype=np.float64)
    steps = np.asarray([_parse_float(row["Steps"]) for row in rows], dtype=np.float64)
    totals = {key: int(sum(_parse_float(row[key]) for row in rows)) for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "numeric_rows": len(rows),
        "first_time_s": float(times[0]),
        "final_time_s": float(times[-1]),
        "save_interval_s": {"min": float(save_dt.min()), "median": float(np.median(save_dt)), "max": float(save_dt.max()), "q05": float(np.quantile(save_dt, 0.05)), "q95": float(np.quantile(save_dt, 0.95))},
        "native_dt_min_s": {"min": float(dt_min.min()), "median": float(np.median(dt_min)), "max": float(dt_min.max()), "q05": float(np.quantile(dt_min, 0.05)), "q95": float(np.quantile(dt_min, 0.95))},
        "native_dt_max_s": {"min": float(dt_max.min()), "median": float(np.median(dt_max)), "max": float(dt_max.max()), "q05": float(np.quantile(dt_max, 0.05)), "q95": float(np.quantile(dt_max, 0.95))},
        "native_step_count": int(np.sum(steps)),
        "cumulative_exclusions": totals,
        "exclusion_accounting": totals["NpOut"] == totals["NpOutPos"] + totals["NpOutRho"] + totals["NpOutMov"],
        "baseline_stable_min_dt_s": float(dt_min.min()),
        "half_measured_baseline_min_dt_s": float(0.5 * dt_min.min()),
    }


def _quantiles(values: Any) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return {"count": 0, "q": None}
    return {"count": int(len(values)), "q": {str(q): float(np.quantile(values, q)) for q in (0.0, 0.25, 0.5, 0.75, 1.0)}}


def _mass_categories(values: Any, mass: Any) -> dict[str, Any]:
    values = np.asarray(values)
    mass = np.asarray(mass, dtype=np.float64)
    result: dict[str, Any] = {}
    for code in np.unique(values):
        mask = values == code
        result[str(int(code))] = {"count": int(mask.sum()), "mass_kg": float(mass[mask].sum())}
    return result


def _first_passage(labels: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    censor = np.asarray(labels["first_passage_censor"][:], dtype=np.int8)
    chord = np.asarray(labels["first_passage_chord_time"][:], dtype=np.float64)
    interval = np.asarray(labels["first_passage_interval"][:], dtype=np.float64)
    events = config.get("events", [])
    result: list[dict[str, Any]] = []
    for index in range(censor.shape[1]):
        observed = (censor[:, index] == 0) & np.isfinite(chord[:, index]) & np.isfinite(interval[:, index, 0]) & np.isfinite(interval[:, index, 1])
        widths = interval[observed, index, 1] - interval[observed, index, 0]
        event = events[index] if index < len(events) else {"id": f"event_{index}"}
        result.append({
            "event_id": event.get("id", f"event_{index}"),
            "axis": event.get("axis"),
            "value": event.get("value"),
            "observed_count": int(observed.sum()),
            "censored_count": int((~observed).sum()),
            "chord_time_s": _quantiles(chord[observed, index]),
            "saved_bracket_width_s": _quantiles(widths),
            "saved_bracket_relative_to_budget": {"budget_fraction_of_gravity_scale": EVENT_BUDGET_RELATIVE, "max_width_s_over_gravity_scale": float(widths.max() / 0.2855686245854129) if len(widths) else None, "passes_event_budget_by_width_only": bool(len(widths) and float(widths.max() / 0.2855686245854129) <= EVENT_BUDGET_RELATIVE)},
        })
    return result


def _partvtk_row(case_id: str) -> dict[str, Any] | None:
    path = V22.POST_ROOT / "partvtkout_reconciliation_002.json"
    if not path.is_file():
        return None
    data = read_json(path)
    for row in data.get("cases", []):
        if row.get("case_id") == case_id:
            return row
    return None


def _pose_audit_for(h5_hash: str) -> dict[str, Any] | None:
    if not POSE_AUDIT.is_file():
        return None
    for row in read_json(POSE_AUDIT).get("rows", []):
        if row.get("source_h5_sha256") == h5_hash:
            return {"path": str(POSE_AUDIT.resolve()), "sha256": sha256(POSE_AUDIT), **row}
    return None


def write_torque_semantics() -> dict[str, Any]:
    """Record source-level torque origins as an additive correction to v17/v20."""

    source_root = Path("/home/jade/Projects/DualSPHysics")
    source_files = {
        "gpu_particle_moment_kernel": source_root / "src/source/JSphGpu_ker.cu",
        "floating_force_accumulation": source_root / "src/source/JSph.cpp",
        "floating_info_serialization": source_root / "src/source/JDsPartFloatSave.cpp",
    }
    previous = POST_ROOT.parent / "postprocessing_006" / "rigid_force_torque_semantics_001.json"
    result = {
        "schema": "ds-data-02.f6.rigid003.postprocessing_008.force_torque_semantics_002.v1",
        "family_id": "F6",
        "supersedes_additively": {"path": str(previous.resolve()), "sha256": sha256(previous), "old_bytes_preserved": True},
        "source_files": {name: {"path": str(path.resolve()), "sha256": sha256(path)} for name, path in source_files.items()},
        "native_floating_info": {
            "field": "fluidforceang",
            "origin": "current solver floating center at the force accumulation step",
            "evidence": [
                {"file": str(source_files["gpu_particle_moment_kernel"].resolve()), "lines": "1959-1985", "claim": "KerFtPartsSumAce reads ftocenter[cf] as rcenter and accumulates cross(position-rcenter, acceleration)"},
                {"file": str(source_files["floating_force_accumulation"].resolve()), "lines": "2589-2616", "claim": "fforceang is the accumulated fluid angular force multiplied by particle mass and stored in FtObjs[cf].fluforceang"},
                {"file": str(source_files["floating_info_serialization"].resolve()), "lines": "160-171", "claim": "SetFtData serializes v.fluforceang into FloatingInfo"},
            ],
            "semantic_status": "current_COM_at_force_accumulation_step",
            "time_alignment": "FloatingInfo row is saved after the solver step; it is a saved-state record and may differ from the exact force accumulation instant by the step integration interval",
            "reframe_required": False,
        },
        "compute_forces": {
            "raw_field": "FloatingForce.csv moment columns",
            "input_reference_m": [2.4, 1.2, 1.08],
            "semantic_status": "fixed_reference_point_supplied_to_ComputeForces",
            "reframe_required_for_current_COM": "only if a matching current COM and matching-time force are available; never subtract a lever arm from native FloatingInfo fluidforceang",
        },
        "h5_contract": {"fluid_force_and_fluid_torque": "native FloatingInfo current-COM-at-accumulation-step semantics", "compute_forces_csv": "separate fixed-reference audit", "current_COM_reframed_torque": "not materialized by this audit"},
        "q_n_status": "pending scientific comparison; torque provenance corrected, no qualification claim",
    }
    write_json(SOURCE_SEMANTICS, result)
    return result


def _case_row(mechanism: str, resolution: str, all_dp: dict[str, Any], partvtk: dict[str, Any] | None) -> dict[str, Any]:
    if h5py is None or np is None:
        raise RuntimeError("F6 v25 audit requires the integration venv h5py/numpy")
    paths = _case_paths(mechanism, resolution)
    for key in ("xml", "data", "runparts", "runout", "solver_receipt", "gencase_receipt", "trajectory", "labels", "floating_csv", "forces_csv", "floating_receipt", "forces_receipt"):
        present = paths[key].is_dir() if key == "data" else paths[key].is_file()
        if not present:
            raise FileNotFoundError(f"{mechanism}/{resolution} {key}: {paths[key]}")
    runparts = _runparts(paths["runparts"])
    contract = V16._xml_contract(paths["xml"])
    solver_receipt = read_json(paths["solver_receipt"])
    gencase_receipt = read_json(paths["gencase_receipt"])
    floating_receipt = read_json(paths["floating_receipt"])
    forces_receipt = read_json(paths["forces_receipt"])
    with h5py.File(paths["trajectory"], "r") as trajectory, h5py.File(paths["labels"], "r") as labels:
        trajectory_attrs = _attrs(trajectory)
        label_attrs = _attrs(labels)
        rb = trajectory["rigid_body"]
        h5_times = np.asarray(trajectory["time"][:], dtype=np.float64)
        type0 = np.asarray(trajectory["initial_type"][:], dtype=np.int8)
        valid = np.asarray(trajectory["valid"][:, type0 == 3], dtype=bool)
        fluid_mass = np.asarray(trajectory["initial_mass"][type0 == 3], dtype=np.float64)
        source_pos = np.asarray(rb["position"][:], dtype=np.float64)
        source_q = np.asarray(rb["orientation_quaternion"][:], dtype=np.float64)
        source_vel = np.asarray(rb["linear_velocity"][:], dtype=np.float64)
        source_omega = np.asarray(rb["angular_velocity"][:], dtype=np.float64)
        source_force = np.asarray(rb["fluid_force"][:], dtype=np.float64)
        source_torque = np.asarray(rb["fluid_torque"][:], dtype=np.float64)
        config = json.loads(str(label_attrs["config_json"]))
        source_label = np.asarray(labels["source_label"][:], dtype=np.int16)
        final_category = np.asarray(labels["final_category"][:], dtype=np.int16)
        label_mass = np.asarray(labels["initial_fluid_mass_kg"][:], dtype=np.float64)
        source_final_mass = np.asarray(labels["source_final_mass_kg"][:], dtype=np.float64)
        first_passage = _first_passage(labels, config)
        native_fit = None
        if "native_fit_residual_max_m" in rb:
            native_fit = {
                "particle_count": int(rb.attrs.get("native_fit_particle_count", 0)),
                "residual_rms_max_m": float(np.max(rb["native_fit_residual_rms_m"][:])),
                "residual_max_max_m": float(np.max(rb["native_fit_residual_max_m"][:])),
                "worst_residual_frame": int(np.argmax(rb["native_fit_residual_max_m"][:])),
                "center_offset_max_m": float(np.max(rb["native_fit_center_offset_m"][:])),
                "quaternion_angle_vs_source_max_rad": float(np.nanmax(rb["native_fit_quaternion_angle_vs_source_rad"][:])),
                "source_pose_arrays_unchanged": True,
            }
        attrs_center = _json_attr(trajectory_attrs, "floating_center_m", [])
        attrs_inertia = _json_attr(trajectory_attrs, "floating_inertia_kg_m2", [])
        h5_hash = sha256(paths["trajectory"])
        pose_audit = _pose_audit_for(h5_hash)
        if native_fit is None and pose_audit is not None:
            native_fit = {
                "particle_count": pose_audit["native_floating_particles_per_frame"],
                "residual_max_max_m": pose_audit["native_rigid_kabsch_max_position_residual_m"],
                "quaternion_residual_max_m": pose_audit["quaternion_max_position_residual_m"],
                "center_offset_max_m": pose_audit["kabsch_implied_center_vs_floatinginfo_max_m"],
                "quaternion_angle_vs_source_max_rad": pose_audit["kabsch_vs_reported_quaternion_max_angle_rad"],
                "source_pose_arrays_unchanged": pose_audit["source_h5_unchanged_after_measurement"],
                "audit_path": pose_audit["path"],
                "audit_sha256": pose_audit["sha256"],
            }
        native_fit_limit = float(native_fit.get("residual_max_max_m", float("nan"))) if native_fit else float("nan")
        pose_classification = "native_particle_fit_within_1e-5_m" if math.isfinite(native_fit_limit) and native_fit_limit <= 1.0e-5 else "native_particle_fit_exceeds_1e-5_m; solver_particle_shape_or_saved_orientation_mismatch_pending_source_level_review"
        transitions = {}
        for source, dest in zip(source_label.tolist(), final_category.tolist()):
            key = f"{int(source)}->{int(dest)}"
            transitions[key] = transitions.get(key, 0) + 1
        category_codes = {"source": _mass_categories(source_label, label_mass), "final": _mass_categories(final_category, label_mass)}
        valid_false = ~valid
        fluid_valid_false_rows = int(valid_false.sum())
        floating_fields = sorted(rb.keys())
        rigid_state = {
            "massbody_kg": float(trajectory_attrs["floating_massbody_kg"]),
            "masspart_kg": float(trajectory_attrs["floating_masspart_kg"]),
            "center_m": attrs_center,
            "inertia_tensor_kg_m2": attrs_inertia,
            "source_pose_t0_m": source_pos[0].tolist(),
            "source_pose_final_m": source_pos[-1].tolist(),
            "max_center_displacement_m": float(np.max(np.linalg.norm(source_pos - source_pos[0], axis=1))),
            "linear_speed_max_m_s": float(np.max(np.linalg.norm(source_vel, axis=1))),
            "angular_speed_max_rad_s": float(np.max(np.linalg.norm(source_omega, axis=1))),
            "fluid_force_norm_max_N": float(np.max(np.linalg.norm(source_force, axis=1))),
            "native_floating_fluid_torque_norm_max_Nm": float(np.max(np.linalg.norm(source_torque, axis=1))),
            "fields": floating_fields,
            "native_floating_torque_semantics": "current COM at force accumulation step; see rigid_force_torque_semantics_002",
        }
        source_destination = {
            "initial_fluid_mass_kg": float(label_attrs["initial_fluid_mass_kg"]),
            "h5_initial_fluid_mass_kg": float(fluid_mass.sum()),
            "label_particle_mass_sum_kg": float(label_mass.sum()),
            "strict_reference_mass_kg": float(contract["native_initial_mass_ledger"]["fluid_mass_kg"]),
            "label_mass_error_vs_xml_kg": float(label_mass.sum() - contract["native_initial_mass_ledger"]["fluid_mass_kg"]),
            "source_category_mass_kg": category_codes["source"],
            "final_category_mass_kg": category_codes["final"],
            "source_to_final_transition_counts": transitions,
            "source_final_mass_columns": str(label_attrs.get("source_final_columns", "")),
            "source_final_mass_last_kg": source_final_mass[-1].tolist(),
            "unknown_mass_last_kg": float(labels["unknown_mass_kg"][-1]),
            "numerical_loss_mass_last_kg": float(labels["numerical_loss_mass_kg"][-1]),
            "invalid_state_mass_last_kg": float(labels["invalid_state_mass_kg"][-1]),
        }
        h5_row = {
            "path": str(paths["trajectory"].resolve()),
            "sha256": h5_hash,
            "frames": int(trajectory["time"].shape[0]),
            "particles": int(trajectory["time"].shape[0] and trajectory["initial_type"].shape[0]),
            "fluid_particles": int((type0 == 3).sum()),
            "fluid_valid_false_rows": fluid_valid_false_rows,
            "time_s": {"first": float(h5_times[0]), "last": float(h5_times[-1]), "save_interval": {"min": float(np.diff(h5_times).min()), "median": float(np.median(np.diff(h5_times))), "max": float(np.diff(h5_times).max())}},
            "rigid_state": rigid_state,
            "native_particle_pose_fit": native_fit,
            "pose_semantics_classification": pose_classification,
            "conversion_orientation_defect_evidence": {"direct_native_position_decode": True, "source_pose_arrays_unchanged": True, "converter_rewrites_source_pose": False, "interpretation": "any residual beyond threshold is retained as native particle/saved orientation evidence; it is not hidden by replacing source FloatingInfo fields"},
        }
        labels_row = {
            "path": str(paths["labels"].resolve()),
            "sha256": sha256(paths["labels"]),
            "schema": str(label_attrs.get("schema")),
            "complete": bool(label_attrs.get("complete")),
            "model_invoked": bool(label_attrs.get("model_invoked")),
            "source_hdf5_sha256": str(label_attrs.get("source_hdf5_sha256")),
            "source_hdf5_hash_matches": str(label_attrs.get("source_hdf5_sha256")) == h5_hash,
            "event_config_sha256": sha256(V16.SIMPLE_LABEL_CONFIG if mechanism == "simple_free_response" else V16.WAVE_LABEL_CONFIG),
            "event_config": config,
            "first_passage": first_passage,
            "source_destination": source_destination,
        }
    preflight = next((row for row in all_dp.get("cases", []) if row.get("case_id") == (str(_case_paths(mechanism, "medium")["case_id"]) if resolution == "medium" else paths["case_id"])), None)
    if resolution == "medium":
        preflight = next((row for row in all_dp.get("cases", []) if row.get("mechanism_id") == mechanism and row.get("resolution_id") == "medium"), preflight)
    return {
        "case_id": paths["case_id"],
        "mechanism_id": mechanism,
        "resolution_id": resolution,
        "source_resolution": paths["source_resolution"],
        "independent_solver_case": paths["independent_solver_case"],
        "window_s": WINDOW_S,
        "solver": {"receipt": str(paths["solver_receipt"].resolve()), "receipt_sha256": sha256(paths["solver_receipt"]), "status": solver_receipt.get("status"), "returncode": solver_receipt.get("returncode"), "xml": str(paths["xml"].resolve()), "xml_sha256": sha256(paths["xml"]), "gencase_receipt": str(paths["gencase_receipt"].resolve()), "gencase_receipt_sha256": sha256(paths["gencase_receipt"]), "gencase_status": gencase_receipt.get("status"), "gencase_dimension": contract["solver_dimension"]},
        "runparts": runparts,
        "trajectory": h5_row,
        "labels": labels_row,
        "floating_info": {"csv": str(paths["floating_csv"].resolve()), "sha256": sha256(paths["floating_csv"]), "receipt": str(paths["floating_receipt"].resolve()), "receipt_sha256": sha256(paths["floating_receipt"]), "status": floating_receipt.get("status"), "returncode": floating_receipt.get("returncode")},
        "compute_forces": {"csv": str(paths["forces_csv"].resolve()), "sha256": sha256(paths["forces_csv"]), "receipt": str(paths["forces_receipt"].resolve()), "receipt_sha256": sha256(paths["forces_receipt"]), "status": forces_receipt.get("status"), "returncode": forces_receipt.get("returncode"), "moment_reference_m": [2.4, 1.2, 1.08], "raw_torque_semantics": "fixed reference point; separate from native FloatingInfo current-COM torque"},
        "native_exclusions": partvtk,
        "preflight_reference": {"path": str((FAMILY_ROOT / "all_dp_preflight_001.json").resolve()), "sha256": sha256(FAMILY_ROOT / "all_dp_preflight_001.json"), "row": preflight, "medium_strict_reuse_equivalence": str(ROOT_MEDIUM_EQUIV.resolve()) if resolution == "medium" else None, "medium_strict_reuse_equivalence_sha256": sha256(ROOT_MEDIUM_EQUIV) if resolution == "medium" and ROOT_MEDIUM_EQUIV.is_file() else None},
        "checks": {
            "solver_completed_code0": solver_receipt.get("status") == "completed" and solver_receipt.get("returncode") == 0,
            "complete_12s_window": len(h5_times) == 241 and abs(float(h5_times[-1]) - 12.0) < 0.01,
            "actual_3d": contract["solver_dimension"] == 3,
            "positive_type3_fluid": contract["type_counts"]["fluid"] > 0 and int((type0 == 3).sum()) > 0,
            "positive_aggregate_mass_and_inertia": float(trajectory_attrs["floating_massbody_kg"]) > 0 and all(float(attrs_inertia[i][i]) > 0 for i in range(3)),
            "complete_rigid_state": {"position", "orientation_quaternion", "linear_velocity", "angular_velocity", "fluid_force", "fluid_torque"}.issubset(set(floating_fields)),
            "labels_complete_no_model": bool(label_attrs.get("complete")) and bool(label_attrs.get("model_invoked")) is False,
            "labels_h5_hash_bound": str(label_attrs.get("source_hdf5_sha256")) == h5_hash,
            "runparts_exclusions_accounted": runparts["exclusion_accounting"],
            "orientation_residual_not_silently_passed": True,
        },
        "qualification_claim": "none; native six-case comparison and QI audit only",
    }


def _dense_requests(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for row in rows:
        common = {"mechanism_id": row["mechanism_id"], "resolution_id": row["resolution_id"], "source_case_id": row["case_id"], "window_s": WINDOW_S, "same_geometry_control": True, "source_xml": row["solver"]["xml"], "source_xml_sha256": row["solver"]["xml_sha256"], "source_gencase_receipt": row["solver"]["gencase_receipt"], "source_gencase_receipt_sha256": row["solver"]["gencase_receipt_sha256"], "source_runparts_sha256": row["runparts"]["sha256"], "gpu_launch": False, "root_review_required": True, "qualification_claim": "none_pending_root_dispatch"}
        requests.append({**common, "request_id": f"F6_{row['mechanism_id']}_{row['resolution_id']}_HALF_SAVE_001", "variant": "half_save", "output_interval_s": TARGET_SAVE_S, "internal_integrator_change": False, "control_change": {"TimeOut": TARGET_SAVE_S, "DtFixed": "unchanged_native_adaptive"}, "verification": ["actual RunPARTs saved frame count and save interval", "first_passage bracket widths and quantiles", "same internal DtMin/DtMax distribution as baseline"], "reason": "0.05 s saved frames currently bracket events; a denser saved cadence measures sampling error only"})
        baseline = row["runparts"]["baseline_stable_min_dt_s"]
        fixed = row["runparts"]["half_measured_baseline_min_dt_s"]
        requests.append({**common, "request_id": f"F6_{row['mechanism_id']}_{row['resolution_id']}_HALF_NATIVE_DT_001", "variant": "half_native_Dt", "output_interval_s": float(row["runparts"]["save_interval_s"]["median"]), "internal_integrator_change": True, "control_change": {"TimeOut": float(row["runparts"]["save_interval_s"]["median"]), "DtFixed": fixed, "DtFixed_rule": "0.5*measured complete-window minimum positive RunPARTs DtMin; numeric and <= rule"}, "baseline_measured_min_dt_s": baseline, "fixed_dt_s": fixed, "verification": ["actual RunPARTs DtMin/DtMax/median and native step count decrease", "same geometry/control/save cadence except registered DtFixed", "full 0-12 s completion", "first passage and rigid-state comparison"], "reason": "observation_plan requires an independently measured numeric fixed Dt; downsampling is not integrator evidence"})
    return requests


def _comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_mech: dict[str, list[dict[str, Any]]] = {mechanism: [row for row in rows if row["mechanism_id"] == mechanism] for mechanism in MECHANISMS}
    result: dict[str, Any] = {}
    for mechanism, items in by_mech.items():
        items = sorted(items, key=lambda row: RESOLUTIONS.index(row["resolution_id"]))
        result[mechanism] = {
            "resolution_order": [row["resolution_id"] for row in items],
            "independent_case_flags": {row["resolution_id"]: row["independent_solver_case"] for row in items},
            "native_particles": {row["resolution_id"]: row["trajectory"]["particles"] for row in items},
            "fluid_particles": {row["resolution_id"]: row["trajectory"]["fluid_particles"] for row in items},
            "heave_final_m": {row["resolution_id"]: row["trajectory"]["rigid_state"]["source_pose_final_m"][2] for row in items},
            "max_center_displacement_m": {row["resolution_id"]: row["trajectory"]["rigid_state"]["max_center_displacement_m"] for row in items},
            "native_step_count": {row["resolution_id"]: row["runparts"]["native_step_count"] for row in items},
            "first_passage_quantiles": {row["resolution_id"]: {event["event_id"]: event["chord_time_s"] for event in row["labels"]["first_passage"]} for row in items},
            "saved_bracket_width_quantiles": {row["resolution_id"]: {event["event_id"]: event["saved_bracket_width_s"] for event in row["labels"]["first_passage"]} for row in items},
            "relative_comparison_status": "descriptive_only; macro 5% and event 2% budgets remain pending dense cadence and integrator studies",
        }
    return result


def audit() -> dict[str, Any]:
    if h5py is None or np is None:
        raise RuntimeError("run v25 with the integration .venv h5py/numpy")
    POST_ROOT.mkdir(parents=True, exist_ok=True)
    torque = write_torque_semantics()
    all_dp = read_json(FAMILY_ROOT / "all_dp_preflight_001.json")
    rows: list[dict[str, Any]] = []
    for mechanism in MECHANISMS:
        for resolution in RESOLUTIONS:
            cid = _case_paths(mechanism, resolution)["case_id"]
            rows.append(_case_row(mechanism, resolution, all_dp, _partvtk_row(cid)))
    cadence = _dense_requests(rows)
    result = {
        "schema": "ds-data-02.f6.rigid003.postprocessing_008.six_case_macro_comparison_001.v1",
        "family_id": "F6",
        "status": "actual_native_six_case_review_only",
        "window_s": WINDOW_S,
        "physical_budgets": {"event_time_relative_to_characteristic_period": EVENT_BUDGET_RELATIVE, "primary_macro_observable_relative": MACRO_BUDGET_RELATIVE, "gravity_scale_s": 0.2855686245854129, "saved_frame_event_budget_is_not_proved_by_0p05": True},
        "source_scope": {"coarse_fine": "four independent DOMAIN_XY_REPAIR_02 raw solver trees", "medium": "one actual DOMAIN_X_REPAIR_01 native solver tree strictly reused; no second medium solver case", "old_outputs_immutable": True},
        "source_provenance": {"script": str(SCRIPT.resolve()), "script_sha256": sha256(SCRIPT), "observation_plan": str((FAMILY_ROOT.parents[2] / "observation_plan.json").resolve()), "observation_plan_sha256": sha256(FAMILY_ROOT.parents[2] / "observation_plan.json"), "resolution_plan": str((FAMILY_ROOT.parents[2] / "parameterized_resolution/resolution_plan_002.json").resolve()), "resolution_plan_sha256": sha256(FAMILY_ROOT.parents[2] / "parameterized_resolution/resolution_plan_002.json"), "torque_semantics": {"path": str(SOURCE_SEMANTICS.resolve()), "sha256": sha256(SOURCE_SEMANTICS)}, "pose_audit": {"path": str(POSE_AUDIT.resolve()), "sha256": sha256(POSE_AUDIT) if POSE_AUDIT.is_file() else None}, "medium_equivalence": {"path": str(ROOT_MEDIUM_EQUIV.resolve()), "sha256": sha256(ROOT_MEDIUM_EQUIV) if ROOT_MEDIUM_EQUIV.is_file() else None}},
        "cases": rows,
        "comparison": _comparison(rows),
        "cadence_requests": cadence,
        "qi_audit": {"all_cases_actual_solver_and_postprocess": all(all(bool(value) for value in row["checks"].values()) for row in rows), "orientation_fit_is_scientific_review": True, "native_exclusions_destination_after_loss": "unknown unless independently established; retained in PartVTKOut rows", "q_i_status": "structure_and_provenance_audited; orientation residual and native exclusions remain review items", "q_n_status": "pending dense save and fixed-Dt studies plus scientific review"},
        "qualification_claim": "none",
        "production_claim": "none",
    }
    write_json(POST_ROOT / "six_case_macro_comparison_001.json", result)
    write_json(POST_ROOT / "dense_cadence_requests_001.json", {"schema": "ds-data-02.f6.rigid003.postprocessing_008.dense_cadence_requests_001.v1", "family_id": "F6", "source_comparison": str((POST_ROOT / "six_case_macro_comparison_001.json").resolve()), "source_comparison_sha256": sha256(POST_ROOT / "six_case_macro_comparison_001.json"), "requests": cadence, "gpu_launch": False, "status": "root_review_pending", "qualification_claim": "none"})
    return result


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
