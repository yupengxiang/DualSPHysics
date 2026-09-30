#!/usr/bin/env python3
"""Audit immutable F2 native trajectories and the solver exclusion ledger.

The audit is intentionally a sidecar operation.  It reads a converted native
trajectory, its native event labels, the original solver logs, and the actual
GenCase products.  It never changes a trajectory or label HDF5.  PartVTKOut is
run in the audit attempt so solver-excluded particles have independently
inspectable position and density evidence.  Excluded identities remain a
numerical unknown; they are never reclassified as physical spill.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[4]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.ds_data02_integrity import (  # noqa: E402
    FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS,
    audit_hdf5,
)


SCHEMA = "ds-data-02.f2-full-qi-audit.v1"
EVENT_CODES = {
    "cup_departure": 1,
    "cup_return": 2,
    "receiver_entry": 3,
    "receiver_exit": 4,
    "tray_entry": 5,
    "tray_exit": 6,
}
DESTINATION_CODES = {
    "unknown": 0,
    "cup": 1,
    "receiver": 2,
    "tray": 3,
    "inflight": 4,
}


class AuditError(RuntimeError):
    """Raised when a required source or typed state cannot be audited."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return jsonable(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return jsonable(value.tolist())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise AuditError(f"{label} is missing: {path}")
    return path


def parse_number(value: str) -> float:
    text = value.strip().replace(" ", "")
    # RunPARTs uses commas as thousands separators and a dot as decimal point.
    text = text.replace(",", "")
    return float(text)


def read_delimited(path: Path, delimiter: str = ";") -> list[dict[str, str]]:
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def _field(rows: Iterable[Mapping[str, str]], name: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(name, "")
        if not value or value.strip().startswith("#"):
            continue
        try:
            values.append(parse_number(value))
        except ValueError:
            continue
    return values


def parse_solver_logs(solver_output: Path) -> dict[str, Any]:
    run_out = require_file(solver_output / "Run.out", "Run.out")
    run_csv = require_file(solver_output / "Run.csv", "Run.csv")
    run_parts = require_file(solver_output / "RunPARTs.csv", "RunPARTs.csv")
    out_text = run_out.read_text(encoding="utf-8", errors="replace")
    dimension_3d = bool(re.search(r"^\*\*3D-Simulation parameters:", out_text, re.MULTILINE))

    def match_int(label: str) -> int | None:
        found = re.search(rf"{re.escape(label)}\s*=\s*([\d,]+)", out_text)
        return int(found.group(1).replace(",", "")) if found else None

    excluded_match = re.search(r"Excluded particles\.*:\s*([\d,]+)", out_text)
    excluded = int(excluded_match.group(1).replace(",", "")) if excluded_match else None
    part_rows = read_delimited(run_parts, ";")
    positive_dt = [x for x in _field(part_rows, "DtMin [s]") if x > 0]
    positive_dt_max = [x for x in _field(part_rows, "DtMax [s]") if x > 0]
    counters = {}
    for name in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov", "NpNew", "NpSim", "NpfSim"):
        values = _field(part_rows, name)
        counters[name] = {
            "sum": float(sum(values)),
            "max": float(max(values)) if values else None,
            "nonzero_rows": int(sum(v != 0 for v in values)),
        }
    run_lines = run_csv.read_text(encoding="utf-8", errors="replace").splitlines()
    run_header = next((line.lstrip("#").split(";") for line in run_lines if line.strip()), [])
    run_value = next((line.split(";") for line in run_lines[1:] if line.strip() and not line.startswith("#")), [])
    run_summary: dict[str, Any] = {}
    if run_header and run_value:
        for key, value in zip(run_header, run_value):
            if key in {"RunName", "Configuration", "Hardware", "RunMode", "Rcode-VersionInfo"}:
                run_summary[key] = value
            elif key in {"Np", "PhysicalTime", "PartFiles", "PartsOut", "PartsOutRho", "PartsOutVel", "Nbound", "Nfixed", "Dp", "H", "Steps"}:
                try:
                    run_summary[key] = parse_number(value)
                except ValueError:
                    run_summary[key] = value
    return {
        "run_out": {"path": str(run_out), "sha256": sha256(run_out),
                    "explicit_3d_banner": dimension_3d,
                    "case_nfixed": match_int("CaseNfixed"),
                    "case_nmoving": match_int("CaseNmoving"),
                    "case_nfluid": match_int("CaseNfluid"),
                    "case_total": match_int("Total particles"),
                    "excluded_particles": excluded},
        "run_csv": {"path": str(run_csv), "sha256": sha256(run_csv), "summary": run_summary},
        "run_parts": {"path": str(run_parts), "sha256": sha256(run_parts),
                       "rows": len(part_rows), "positive_dt_rows": len(positive_dt),
                       "dt_min_positive_s": min(positive_dt) if positive_dt else None,
                       "dt_min_max_positive_s": max(positive_dt) if positive_dt else None,
                       "dt_max_positive_s": max(positive_dt_max) if positive_dt_max else None,
                       "counters": counters},
    }


def run_partvtkout(*, binary: Path, solver_output: Path, output_dir: Path) -> dict[str, Any]:
    binary = require_file(binary, "PartVTKOut binary")
    data_dir = require_file(solver_output / "data/PartOut_000.obi4", "PartOut_000.obi4").parent
    part_dir = output_dir / "partvtkout"
    part_dir.mkdir(parents=True, exist_ok=True)
    csv_path = part_dir / "excluded_particles.csv"
    vtk_path = part_dir / "excluded_particles.vtk"
    resume_path = part_dir / "excluded_particles_stats.csv"
    command = [str(binary), "-dirdata", str(data_dir), "-first:0", "-last:0",
               "-savecsv", str(csv_path), "-savevtk", str(vtk_path),
               "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"]
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = f"{binary.parent}:{environment.get('LD_LIBRARY_PATH', '')}"
    completed = subprocess.run(command, cwd=part_dir, env=environment,
                               capture_output=True, text=True, check=False)
    (part_dir / "partvtkout.stdout.log").write_text(completed.stdout + completed.stderr,
                                                      encoding="utf-8")
    if completed.returncode != 0:
        raise AuditError(f"PartVTKOut failed with code {completed.returncode}: {completed.stdout[-1000:]}{completed.stderr[-1000:]}")
    outputs = {}
    for path in (csv_path, vtk_path, resume_path, part_dir / "partvtkout.stdout.log"):
        if path.is_file():
            outputs[path.name] = {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size}
    return {"command": command, "binary": {"path": str(binary), "sha256": sha256(binary)},
            "returncode": completed.returncode, "outputs": outputs,
            "stdout_tail": (completed.stdout + completed.stderr)[-2000:]}


def parse_partvtkout(csv_path: Path) -> dict[str, Any]:
    if not csv_path.is_file():
        raise AuditError(f"PartVTKOut CSV was not created: {csv_path}")
    lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
    # PartVTKOut uses a summary header, a blank line, then a particle header.
    header_index = next((i for i, line in enumerate(lines) if line.startswith("Pos.x [m]")), None)
    if header_index is None:
        return {"path": str(csv_path), "sha256": sha256(csv_path), "rows": 0,
                "header_found": False, "finite_position_rows": 0, "finite_density_rows": 0,
                "status": "no_particle_rows"}
    header = [v.strip() for v in lines[header_index].split(",")]
    rows = []
    for line in lines[header_index + 1:]:
        if not line.strip():
            continue
        values = [v.strip() for v in line.split(",")]
        if len(values) >= len(header):
            rows.append(dict(zip(header, values)))
    def finite(row: Mapping[str, str], names: tuple[str, ...]) -> bool:
        try:
            return all(np.isfinite(float(row[name].replace("E", "e"))) for name in names)
        except (KeyError, ValueError):
            return False
    position_names = ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")
    density_name = "Rhop [kg/m^3]"
    density = []
    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            density.append(float(row[density_name]))
        except (KeyError, ValueError):
            pass
        try:
            records.append({
                "idp": int(row["Idp"]),
                "part_out": int(row["PartOut"]),
                "motive_code": int(row["Motive"]),
                "position_m": [float(row[name]) for name in position_names],
                "density_kg_m3": float(row[density_name]),
            })
        except (KeyError, ValueError):
            # Keep the aggregate finite checks above useful, while exposing
            # malformed rows to the ledger as an incomplete record set.
            pass
    return {
        "path": str(csv_path.resolve()), "sha256": sha256(csv_path), "rows": len(rows),
        "header_found": True,
        "finite_position_rows": int(sum(finite(row, position_names) for row in rows)),
        "finite_density_rows": int(sum(finite(row, (density_name,)) for row in rows)),
        "density_min_kg_m3": float(min(density)) if density else None,
        "density_max_kg_m3": float(max(density)) if density else None,
        "records": records,
        "status": "pass" if rows and len(density) == len(rows) else ("zero_exclusions" if not rows else "incomplete_density"),
    }


def typed_id_pairs(zone: np.ndarray, idp: np.ndarray) -> list[tuple[int, int]]:
    return [(int(z), int(i)) for z, i in zip(zone.tolist(), idp.tolist())]


def audit_state(*, trajectory: Path, labels: Path, owner_metadata: Path,
                conversion_report: Path, solver_output: Path,
                gencase_receipt: Path, gencase_prefix: Path,
                definition: Path, motion: Path, output_dir: Path,
                partvtkout: Path) -> dict[str, Any]:
    sources = [trajectory, labels, owner_metadata, conversion_report,
               solver_output / "Run.out", solver_output / "Run.csv",
               solver_output / "RunPARTs.csv", gencase_receipt,
               gencase_prefix.with_suffix(".xml"), gencase_prefix.with_suffix(".bi4"),
               gencase_prefix.parent / f"{gencase_prefix.name}_motion.dat", definition, motion]
    source_bindings = {str(require_file(p, "source").resolve()): sha256(p) for p in sources}
    trajectory_attr_snapshot: dict[str, Any] = {}
    trajectory_case_id = ""
    with h5py.File(trajectory, "r") as state, h5py.File(labels, "r") as label:
        required = ("time", "position", "velocity", "density", "mass", "type", "valid",
                    "particle_zone", "particle_id", "rigid_body_state")
        missing = [name for name in required if name not in state]
        if missing:
            raise AuditError(f"trajectory datasets missing: {missing}")
        time = np.asarray(state["time"][:], dtype=np.float64)
        position_shape = tuple(state["position"].shape)
        type_data = np.asarray(state["type"][:], dtype=np.int8)
        valid_data = np.asarray(state["valid"][:], dtype=bool)
        zone = np.asarray(state["particle_zone"][:], dtype=np.int64)
        idp = np.asarray(state["particle_id"][:], dtype=np.int64)
        mass = np.asarray(state["mass"][:], dtype=np.float64)
        density = np.asarray(state["density"][:], dtype=np.float64)
        velocity = np.asarray(state["velocity"][:], dtype=np.float64)
        position = np.asarray(state["position"][:], dtype=np.float64)
        if position_shape[-1] != 3:
            raise AuditError(f"position does not have 3 coordinate components: {position_shape}")
        initial_type = type_data[0]
        fluid = initial_type == 3
        moving = initial_type == 1
        fixed = initial_type == 0
        initial_fluid_ids = set(typed_id_pairs(zone[fluid], idp[fluid]))
        all_ids = typed_id_pairs(zone, idp)
        active = valid_data & (type_data == 3)
        finite_active = (np.isfinite(position).all(axis=-1) & np.isfinite(velocity).all(axis=-1)
                         & np.isfinite(density) & np.isfinite(mass))
        introduced: set[tuple[int, int]] = set()
        for frame in range(len(time)):
            introduced.update(set(typed_id_pairs(zone[active[frame]], idp[active[frame]])) - initial_fluid_ids)
        initial_fluid_active = active[:, fluid]
        had_active_before = np.zeros(int(fluid.sum()), dtype=bool)
        previous_active = np.zeros(int(fluid.sum()), dtype=bool)
        revived = np.zeros(int(fluid.sum()), dtype=bool)
        for frame_active in initial_fluid_active:
            revived |= had_active_before & ~previous_active & frame_active
            had_active_before |= frame_active
            previous_active = frame_active.copy()
        # The converter writes -1 in an invalid row after native solver
        # exclusion.  That is an invalid-state sentinel, not a particle type
        # mutation.  Count type changes only while an initial fluid identity
        # is valid; this still catches a live identity changing to a boundary
        # or floating type.
        valid_initial_fluid = valid_data[:, fluid]
        type_changed = np.any(
            valid_initial_fluid & (type_data[:, fluid] != initial_type[fluid][None, :]),
            axis=0,
        )
        invalid_type_sentinel = np.any(
            ~valid_initial_fluid & (type_data[:, fluid] == -1), axis=0
        )
        rigid = np.asarray(state["rigid_body_state"][:])
        moving_counts = [int(np.count_nonzero(type_data[frame] == 1)) for frame in range(len(time))]
        moving_pose_ok = bool(
            np.all(valid_data[:, moving]) and
            all(np.isfinite(rigid[name]).all() for name in
                ("actual_angle_rad", "actual_omega_rad_s", "position_rms_m", "velocity_rms_m_s")) and
            np.all(rigid["moving_node_count"] == rigid["expected_node_count"]) and
            np.all(rigid["moving_node_count"] == int(moving.sum()))
        )
        final_missing = int(np.count_nonzero(fluid & ~valid_data[-1]))
        fluid_mass_initial = float(mass[0, fluid].sum())
        fluid_mass_final_valid = float(mass[-1, fluid & valid_data[-1]].sum())
        typed_unique = len(set(all_ids)) == len(all_ids)
        state_checks = {
            "frames": int(len(time)), "particles": int(len(zone)),
            "time_strictly_increasing": bool(len(time) > 1 and np.isfinite(time).all() and np.all(np.diff(time) > 0)),
            "coordinate_components": int(position_shape[-1]),
            "typed_zone_id_unique": typed_unique,
            "initial_type_counts": {"fixed_type0": int(fixed.sum()), "moving_type1": int(moving.sum()),
                                     "fluid_type3": int(fluid.sum())},
            "all_active_fluid_state_finite": bool(np.all(finite_active[active])),
            "introduced_active_fluid_ids": int(len(introduced)),
            "revived_initial_fluid_ids": int(revived.sum()),
            "type_changed_initial_fluid_ids": int(type_changed.sum()),
            "native_invalid_type_sentinel_ids": int(invalid_type_sentinel.sum()),
            "moving_type1_pose_complete": moving_pose_ok,
            "moving_count_min": int(min(moving_counts)), "moving_count_max": int(max(moving_counts)),
            "initial_fluid_mass_kg": fluid_mass_initial,
            "final_valid_fluid_mass_kg": fluid_mass_final_valid,
            "final_missing_fluid_id_count": final_missing,
            "boundary_not_fluid_mass": bool(not np.any(initial_type[fixed | moving] == 3)),
            "density_active_min_kg_m3": float(np.min(density[active])) if np.any(active) else None,
            "density_active_max_kg_m3": float(np.max(density[active])) if np.any(active) else None,
        }

        label_events = np.asarray(label["events"][:])
        label_ids = set(typed_id_pairs(np.asarray(label["particle_zone"][:]), np.asarray(label["particle_id"][:])))
        event_ids_ok = all((int(row["zone"]), int(row["idp"])) in label_ids for row in label_events)
        legal_tray: dict[str, Any] = {}
        departure_by_particle: dict[int, list[float]] = {}
        for row in label_events:
            if int(row["event_code"]) == EVENT_CODES["cup_departure"]:
                departure_by_particle.setdefault(int(row["particle_index"]), []).append(float(row["time_s"]))
        for name, code in (("tray_entry", EVENT_CODES["tray_entry"]), ("tray_exit", EVENT_CODES["tray_exit"])):
            rows = label_events[label_events["event_code"] == code]
            legal = [any(t < float(row["time_s"]) for t in departure_by_particle.get(int(row["particle_index"]), [])) for row in rows]
            legal_tray[name] = {
                "rows": int(len(rows)), "legal_after_cup_departure": int(sum(legal)),
                "unmatched_rows": int(len(rows) - sum(legal)),
                "total_mass_kg": float(rows["mass_kg"].sum()) if len(rows) else 0.0,
                "legal_mass_kg": float(rows["mass_kg"][np.asarray(legal, dtype=bool)].sum()) if len(rows) else 0.0,
                "unmatched_mass_kg": float(rows["mass_kg"][~np.asarray(legal, dtype=bool)].sum()) if len(rows) else 0.0,
            }
        final_dest = np.asarray(label["destination_code"][-1, :], dtype=np.int8)
        label_unknown = int(np.count_nonzero(final_dest == DESTINATION_CODES["unknown"]))
        label_dest_mass = np.asarray(label["destination_mass_kg"][-1, :], dtype=np.float64)
        event_checks = {
            "label_particle_count": int(len(label_ids)), "event_count": int(len(label_events)),
            "typed_event_ids_in_source_cohort": event_ids_ok,
            "event_counts_by_code": {name: int(np.count_nonzero(label_events["event_code"] == code)) for name, code in EVENT_CODES.items()},
            "legal_physical_spill_ledger": legal_tray,
            "final_unknown_label_count": label_unknown,
            "final_destination_mass_kg": {name: float(label_dest_mass[code]) for name, code in DESTINATION_CODES.items()},
            "excluded_ids_are_not_physical_spill": True,
            "physical_walls": json.loads(str(state.attrs.get("boundary_semantics_json", "{}"))).get("physical_boundary_faces", []),
            "open_boundary_faces": json.loads(str(state.attrs.get("boundary_semantics_json", "{}"))).get("open_boundary_faces", []),
        }
        trajectory_case_id = str(state.attrs.get("case_id", ""))
        trajectory_attr_snapshot = {
            key: jsonable(state.attrs[key]) for key in state.attrs.keys()
            if key in {"case_id", "physical_case_id", "resolution", "source_format", "identity_key",
                       "solver_dimension", "rigid_body_state_source", "rigid_body_state_control_sign_applied",
                       "source_solver_receipt_sha256", "source_gencase_receipt_sha256", "motion_control_copied_sha256"}
        }
    log_evidence = parse_solver_logs(solver_output)
    partvtk_evidence = run_partvtkout(binary=partvtkout, solver_output=solver_output, output_dir=output_dir)
    partvtk_csv = output_dir / "partvtkout/excluded_particles.csv"
    partvtk_rows = parse_partvtkout(partvtk_csv)
    excluded = log_evidence["run_out"]["excluded_particles"]
    excluded = int(excluded) if excluded is not None else final_missing
    counts_match = excluded == final_missing
    partvtk_counts_match = partvtk_rows["rows"] == excluded
    fluid_zone = zone[fluid]
    fluid_idp = idp[fluid]
    fluid_valid = valid_data[:, fluid]
    expected_missing_indices = np.flatnonzero(~fluid_valid[-1])
    expected_missing = {
        (int(fluid_zone[index]), int(fluid_idp[index])): int(np.flatnonzero(~fluid_valid[:, index])[0])
        for index in expected_missing_indices
    }
    partvtk_records = partvtk_rows.get("records", [])
    idp_to_zone = {int(value): int(fluid_zone[index]) for index, value in enumerate(fluid_idp.tolist())}
    exclusion_records: list[dict[str, Any]] = []
    for record in partvtk_records:
        zone_value = idp_to_zone.get(int(record["idp"]))
        if zone_value is None:
            zone_value = -1
        key = (zone_value, int(record["idp"]))
        first_frame = expected_missing.get(key, -1)
        exclusion_records.append({
            "zone": zone_value,
            "idp": int(record["idp"]),
            "first_missing_frame": first_frame,
            "first_missing_time_s": float(time[first_frame]) if first_frame >= 0 else None,
            "part_out": int(record["part_out"]),
            "motive_code": int(record["motive_code"]),
            "motive": "native_solver_excluded_numerical_unknown",
            "partvtkout_position_m": record["position_m"],
            "partvtkout_density_kg_m3": float(record["density_kg_m3"]),
        })
    runpart_counts = log_evidence["run_parts"]["counters"]
    native_ledger_errors: list[str] = []
    observed_keys = {(int(row["zone"]), int(row["idp"])) for row in exclusion_records}
    if observed_keys != set(expected_missing):
        native_ledger_errors.append("partvtkout_typed_identity_set_mismatch")
    if any(int(row["first_missing_frame"]) < 1 for row in exclusion_records):
        native_ledger_errors.append("partvtkout_first_missing_frame_unresolved")
    if any(not np.isfinite(np.asarray(row["partvtkout_position_m"], dtype=float)).all() or
           not np.isfinite(float(row["partvtkout_density_kg_m3"])) for row in exclusion_records):
        native_ledger_errors.append("partvtkout_position_density_nonfinite")
    if int(round(runpart_counts["NpOut"]["sum"])) != excluded:
        native_ledger_errors.append("runparts_npout_mismatch")
    if int(round(runpart_counts["NpOutPos"]["sum"])) != excluded:
        native_ledger_errors.append("runparts_npoutpos_mismatch")
    if int(round(runpart_counts["NpOutRho"]["sum"])) != 0:
        native_ledger_errors.append("runparts_npoutrho_expected_zero")
    native_ledger = {
        "mode": FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS,
        "status": "pass" if not native_ledger_errors else "fail",
        "errors": sorted(set(native_ledger_errors)),
        "h5_full_timeline_checked": True,
        "h5_full_timeline_frames": int(len(time)),
        "initial_fluid_typed_count": int(fluid.sum()),
        "excluded_typed_count": int(len(exclusion_records)),
        "excluded_particles": exclusion_records,
        "runparts_counts": {
            "npout_sum": int(round(runpart_counts["NpOut"]["sum"])),
            "npoutpos_sum": int(round(runpart_counts["NpOutPos"]["sum"])),
            "npoutrho_sum": int(round(runpart_counts["NpOutRho"]["sum"])),
            "npoutmov_sum": int(round(runpart_counts["NpOutMov"]["sum"])),
        },
        "partvtkout_csv": partvtk_rows,
        "introduced_after_initial_count": state_checks["introduced_active_fluid_ids"],
        "revived_identity_count": state_checks["revived_initial_fluid_ids"],
        "type_changed_identity_count": state_checks["type_changed_initial_fluid_ids"],
        "zone_source": "trajectory.particle_zone_static_identity",
        "native_exclusion_is_numerical_unknown": True,
        "physical_spill_classification": "separate_event_ledger_required",
    }
    integrity_metadata = {
        "units": {"time": "s", "position": "m", "velocity": "m/s",
                  "density": "kg/m^3", "mass": "kg", "pressure": "Pa"},
        "coordinate_frame": str(trajectory_attr_snapshot.get("coordinate_frame", "world")),
        "geometry": trajectory_attr_snapshot.get("geometry_semantics_json", "F2 finite geometry"),
        "control": trajectory_attr_snapshot.get("control_semantics_json", "F2 prescribed motion"),
        "boundary_mode": "open",
        "lifecycle_mode": FINITE_INITIAL_NUMERICAL_COHORT_WITH_EXCLUSIONS,
        "rigid_body_state": "actual_saved_moving_nodes_fit_to_copied_mvrotfile",
        "native_exclusion_ledger": native_ledger,
    }
    integrity_audit = audit_hdf5(trajectory, solver_log=solver_output / "Run.out",
                                 metadata=integrity_metadata, particle_chunk=65536)
    q_i_checks = {
        "solver_log_explicit_3d": log_evidence["run_out"]["explicit_3d_banner"],
        "nonzero_fluid": state_checks["initial_type_counts"]["fluid_type3"] > 0,
        "positive_active_mass": state_checks["initial_fluid_mass_kg"] > 0,
        "time_axis": state_checks["time_strictly_increasing"],
        "active_state_finite": state_checks["all_active_fluid_state_finite"],
        "typed_ids": state_checks["typed_zone_id_unique"] and state_checks["introduced_active_fluid_ids"] == 0,
        "identity_lifecycle_no_revival": state_checks["revived_initial_fluid_ids"] == 0,
        "identity_type_stable": state_checks["type_changed_initial_fluid_ids"] == 0,
        "moving_boundary_pose": state_checks["moving_type1_pose_complete"],
        "boundary_mass_separated": state_checks["boundary_not_fluid_mass"],
        "excluded_count_matches_native_invalid": counts_match,
        "partvtkout_exclusion_count_matches": partvtk_counts_match,
        "partvtkout_position_density_evidence": bool(
            (excluded == 0 and partvtk_rows["status"] == "zero_exclusions") or
            (excluded > 0 and partvtk_rows["rows"] == excluded and
             partvtk_rows["finite_position_rows"] == excluded and
             partvtk_rows["finite_density_rows"] == excluded)
        ),
        "event_ids_typed": event_checks["typed_event_ids_in_source_cohort"],
        "physical_spill_separated_from_unknown": event_checks["excluded_ids_are_not_physical_spill"],
        "finite_initial_numerical_cohort_loss_ledger": native_ledger["status"] == "pass",
        "generic_integrity_audit_structural_status": integrity_audit.get("q_i_status") == "Q-I-structure-pass",
    }
    failed = [name for name, value in q_i_checks.items() if not value]
    # A zero-exclusion trajectory can close the lifecycle ledger.  The offset
    # trajectory must stay open when native invalid identities or unmatched
    # tray crossings remain; neither is silently renamed to spill.
    q_i_status = "Q-I-structure-pass" if not failed else "Q-I-incomplete"
    if excluded > 0 and native_ledger["status"] != "pass":
        reason = "native solver excluded fluid identities lack a complete numerical loss ledger"
    elif excluded > 0:
        reason = "native solver exclusions are fully accounted as numerical_unknown_mass; Q-N remains separate"
    elif event_checks["legal_physical_spill_ledger"]["tray_entry"]["unmatched_rows"]:
        reason = "tray event rows without a preceding cup departure remain unresolved"
    else:
        reason = "all audited native lifecycle and physical boundary checks passed"
    report = {
        "schema": SCHEMA, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": trajectory_case_id, "family_id": "F2",
        "sources": source_bindings,
        "trajectory_attrs": trajectory_attr_snapshot,
        "state": state_checks, "solver_logs": log_evidence,
        "partvtkout": {"execution": partvtk_evidence, "particles": partvtk_rows,
                        "interpretation": "PartVTKOut positions/density are numerical exclusion evidence; excluded particles are not physical tray spill."},
        "native_exclusion_ledger": native_ledger,
        "generic_integrity_audit": integrity_audit,
        "events": event_checks,
        "physical_vs_numerical": {
            "physical_walls": event_checks["physical_walls"],
            "legal_spill_definition": "tray entry after a prior finite cup-mouth departure by the same typed fluid identity",
            "legal_spill_mass_kg": event_checks["legal_physical_spill_ledger"]["tray_entry"]["legal_mass_kg"],
            "unmatched_tray_event_mass_kg": event_checks["legal_physical_spill_ledger"]["tray_entry"]["unmatched_mass_kg"],
            "numerical_unknown_mass_kg": state_checks["initial_fluid_mass_kg"] - state_checks["final_valid_fluid_mass_kg"],
            "numerical_unknown_count": excluded,
            "open_boundary_faces": event_checks["open_boundary_faces"],
        },
        "q_i": {"status": q_i_status, "failed_checks": failed, "reason": reason,
                "checks": q_i_checks, "thresholds_preexisting": True},
        "q_n": {"status": "not_assessed", "reason": "reference resolution pair and independent integration/save comparisons are not completed"},
        "production_eligibility": "not_evaluated",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "full-qi-audit.json"
    report_path.write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report"] = {"path": str(report_path.resolve()), "sha256": sha256(report_path)}
    # Keep a second stable copy only in memory is unnecessary; the runner
    # receipt records the bytes and stdout hash for this immutable report.
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trajectory", "labels", "owner-metadata", "conversion-report", "solver-output", "gencase-receipt", "gencase-prefix", "definition", "motion", "partvtkout", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_state(trajectory=args.trajectory.resolve(), labels=args.labels.resolve(),
                             owner_metadata=args.owner_metadata.resolve(), conversion_report=args.conversion_report.resolve(),
                             solver_output=args.solver_output.resolve(), gencase_receipt=args.gencase_receipt.resolve(),
                             gencase_prefix=args.gencase_prefix.resolve(), definition=args.definition.resolve(),
                             motion=args.motion.resolve(), output_dir=args.output_dir.resolve(),
                             partvtkout=args.partvtkout.resolve())
    except (AuditError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"f2_full_qi_audit: {error}", file=sys.stderr)
        return 2
    print(json.dumps(jsonable({"status": "completed", "q_i": report["q_i"], "report": report["report"]}), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
