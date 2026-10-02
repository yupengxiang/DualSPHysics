#!/usr/bin/env python3
"""Produce an evidence-only native exclusion ledger for one F2 trajectory.

The ledger uses the complete HDF5 timeline and treats ``RunPARTs.csv`` output
counts as per-save increments, summing every row.  An excluded identity is
matched to the actual PartVTKOut ``Idp``/``Motive``/position/density record
when the solver emitted ``PartOut_000.obi4``.  With zero solver exclusions the
absence of a PartOut file is recorded as not applicable; it is never silently
treated as a zero-length physical spill observation.

This script keeps native numerical unknowns separate from cup/receiver/tray
labels and never grants Q-I, Q-N, or production eligibility.
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
from typing import Any, Mapping

import h5py
import numpy as np


SCHEMA = "ds-data-02.f2.native-exclusion-ledger.v1"
MODE = "finite_initial_numerical_cohort_with_exclusions"


class LedgerError(RuntimeError):
    """Raised when native evidence is incomplete or contradictory."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise LedgerError(f"{label} is missing: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(require(path, label).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LedgerError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise LedgerError(f"{label} must be an object: {path}")
    return value


def parse_number(value: str) -> float:
    return float(value.strip().replace(",", ""))


def parse_runparts(path: Path) -> dict[str, Any]:
    rows = list(csv.DictReader(require(path, "RunPARTs.csv").open(encoding="utf-8", errors="replace", newline=""), delimiter=";"))
    counters: dict[str, dict[str, Any]] = {}
    for name in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov", "NpNew", "NpSim", "NpfSim", "NpNormal"):
        values: list[float] = []
        for row in rows:
            raw = row.get(name, "")
            if not raw or raw.strip().startswith("#"):
                continue
            try:
                values.append(parse_number(raw))
            except ValueError:
                continue
        counters[name] = {
            "rows": len(values),
            "sum": float(sum(values)),
            "max": float(max(values)) if values else None,
            "nonzero_rows": int(sum(value != 0 for value in values)),
        }
    times = []
    for row in rows:
        for key in ("TimeStep [s]", "PhysicalTime"):
            raw = row.get(key, "")
            if raw:
                try:
                    times.append(parse_number(raw))
                except ValueError:
                    pass
                break
    return {"path": str(path.resolve()), "sha256": sha256(path), "rows": len(rows), "counters": counters,
            "time_start_s": float(times[0]) if times else None, "time_end_s": float(times[-1]) if times else None}


def parse_runout(path: Path) -> dict[str, Any]:
    text = require(path, "Run.out").read_text(encoding="utf-8", errors="replace")

    def integer(pattern: str) -> int | None:
        match = re.search(pattern, text, re.I)
        return int(match.group(1).replace(",", "")) if match else None

    return {
        "path": str(path.resolve()), "sha256": sha256(path),
        "explicit_3d": bool(re.search(r"^\*\*3D-Simulation parameters:", text, re.M)),
        "case_nfluid": integer(r"CaseNfluid\s*=\s*([\d,]+)"),
        "case_nmoving": integer(r"CaseNmoving\s*=\s*([\d,]+)"),
        "case_nfixed": integer(r"CaseNfixed\s*=\s*([\d,]+)"),
        "total_particles": integer(r"Total particles:\s*([\d,]+)"),
        "excluded_particles": integer(r"Excluded particles[^:]*:\s*([\d,]+)"),
        "part_files": integer(r"PART files[^:]*:\s*([\d,]+)"),
        "steps": integer(r"Steps of simulation[^:]*:\s*([\d,]+)"),
    }


def _partvtk_csv_records(csv_path: Path) -> dict[str, Any]:
    path = require(csv_path, "PartVTKOut CSV")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header_index = next((i for i, line in enumerate(lines) if line.startswith("Pos.x [m]")), None)
    if header_index is None:
        return {"path": str(path), "sha256": sha256(path), "header_found": False, "rows": 0, "records": [], "status": "no_particle_rows"}
    header = [item.strip() for item in lines[header_index].split(",")]
    records: list[dict[str, Any]] = []
    for raw in lines[header_index + 1:]:
        if not raw.strip():
            continue
        values = [item.strip() for item in raw.split(",")]
        if len(values) < len(header):
            continue
        row = dict(zip(header, values))
        try:
            records.append({
                "idp": int(row["Idp"]),
                "part_out": int(row.get("PartOut", "0")),
                "motive_code": int(row.get("Motive", "-1")),
                "position_m": [float(row[key]) for key in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")],
                "density_kg_m3": float(row["Rhop [kg/m^3]"]),
            })
        except (KeyError, ValueError):
            continue
    finite_position = sum(bool(np.isfinite(np.asarray(item["position_m"], dtype=float)).all()) for item in records)
    finite_density = sum(bool(np.isfinite(item["density_kg_m3"])) for item in records)
    return {
        "path": str(path), "sha256": sha256(path), "header_found": True, "rows": len(records), "records": records,
        "finite_position_rows": int(finite_position), "finite_density_rows": int(finite_density),
        "status": "pass" if finite_position == len(records) and finite_density == len(records) else "incomplete",
    }


def run_partvtkout(*, binary: Path, solver_output: Path, output_dir: Path) -> dict[str, Any]:
    binary = require(binary, "PartVTKOut binary")
    data_dir = solver_output / "data"
    partout = sorted(data_dir.glob("PartOut_*.obi4"))
    if not partout:
        return {"status": "not_applicable_no_partout_artifact", "reason": "solver emitted no PartOut file"}
    part_dir = output_dir / "partvtkout"
    part_dir.mkdir(parents=True, exist_ok=True)
    csv_path = part_dir / "excluded_particles.csv"
    vtk_path = part_dir / "excluded_particles.vtk"
    resume_path = part_dir / "excluded_particles_stats.csv"
    command = [str(binary), "-dirdata", str(data_dir), "-first:0", "-last:0",
               "-savecsv", str(csv_path), "-savevtk", str(vtk_path),
               "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"]
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{binary.parent}:{env.get('LD_LIBRARY_PATH', '')}"
    completed = subprocess.run(command, cwd=part_dir, env=env, capture_output=True, text=True, check=False)
    (part_dir / "partvtkout.stdout.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise LedgerError(f"PartVTKOut failed with returncode={completed.returncode}: {(completed.stdout + completed.stderr)[-1000:]}")
    return {
        "status": "completed", "command": command,
        "binary": {"path": str(binary), "sha256": sha256(binary)},
        "csv": _partvtk_csv_records(csv_path),
        "outputs": {str(path.name): {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}
                    for path in (csv_path, vtk_path, resume_path, part_dir / "partvtkout.stdout.log") if path.is_file()},
    }


def audit(*, trajectory: Path, labels: Path, owner_metadata: Path, conversion_report: Path,
          solver_output: Path, gencase_prefix: Path, partvtkout: Path, output_dir: Path) -> dict[str, Any]:
    trajectory = require(trajectory, "trajectory HDF5")
    labels = require(labels, "native labels HDF5")
    owner_metadata = require(owner_metadata, "owner metadata")
    conversion_report = require(conversion_report, "conversion report")
    solver_output = solver_output.resolve()
    require(solver_output / "Run.out", "solver Run.out")
    require(solver_output / "Run.csv", "solver Run.csv")
    require(solver_output / "RunPARTs.csv", "solver RunPARTs.csv")
    prefix = gencase_prefix.resolve()
    source_files = [Path(str(prefix) + suffix) for suffix in (".xml", ".bi4")]
    source_files.append(prefix.parent / f"{prefix.name}_motion.dat")
    source_files.extend([solver_output / "Run.out", solver_output / "Run.csv", solver_output / "RunPARTs.csv"])
    for path in source_files:
        require(path, "native source binding")
    log = parse_runout(solver_output / "Run.out")
    parts = parse_runparts(solver_output / "RunPARTs.csv")
    with h5py.File(trajectory, "r") as state:
        required = ("time", "position", "velocity", "density", "mass", "type", "valid", "particle_zone", "particle_id", "rigid_body_state")
        missing = [name for name in required if name not in state]
        if missing:
            raise LedgerError(f"trajectory lacks required full-state datasets: {missing}")
        time = np.asarray(state["time"][:], dtype=np.float64)
        position = np.asarray(state["position"][:], dtype=np.float64)
        velocity = np.asarray(state["velocity"][:], dtype=np.float64)
        density = np.asarray(state["density"][:], dtype=np.float64)
        mass = np.asarray(state["mass"][:], dtype=np.float64)
        types = np.asarray(state["type"][:], dtype=np.int64)
        valid = np.asarray(state["valid"][:], dtype=bool)
        zone = np.asarray(state["particle_zone"][:], dtype=np.int64)
        idp = np.asarray(state["particle_id"][:], dtype=np.int64)
        rigid = np.asarray(state["rigid_body_state"][:])
        fluid = types[0] == 3
        if not np.any(fluid):
            raise LedgerError("trajectory has no initial Type=3 fluid cohort")
        fluid_indices = np.flatnonzero(fluid)
        fluid_valid = valid[:, fluid_indices]
        expected_missing = {}
        for local, index in enumerate(fluid_indices):
            missing_frames = np.flatnonzero(~valid[:, index])
            if len(missing_frames):
                first = int(missing_frames[0])
                expected_missing[(int(zone[index]), int(idp[index]))] = {
                    "first_missing_frame": first, "first_missing_time_s": float(time[first]),
                    "mass_kg": float(mass[0, index]),
                }
        structural = {
            "frames": int(len(time)), "particles": int(len(zone)),
            "time_strictly_increasing": bool(len(time) > 1 and np.isfinite(time).all() and np.all(np.diff(time) > 0)),
            "coordinate_components": int(position.shape[-1]),
            "explicit_3d_from_run_out": bool(log["explicit_3d"]),
            "initial_fluid_count": int(fluid.sum()), "case_nfluid": log["case_nfluid"],
            "initial_fluid_mass_kg": float(np.nansum(mass[0, fluid])),
            "positive_initial_fluid_mass": bool(np.all(np.isfinite(mass[0, fluid])) and np.all(mass[0, fluid] > 0)),
            "active_fluid_state_finite": bool(np.all(np.isfinite(position[valid & (types == 3)])) and np.all(np.isfinite(velocity[valid & (types == 3)])) and np.all(np.isfinite(density[valid & (types == 3)]))),
            "rigid_body_state_frame_aligned": bool(len(rigid) == len(time) and np.isfinite(rigid["actual_angle_rad"]).all()),
            "typed_identity_unique": bool(len(set(zip(zone.tolist(), idp.tolist()))) == len(zone)),
            "introduced_fluid_ids": int(np.count_nonzero((~fluid[None, :]) & valid & (types == 3))),
        }
    excluded = log["excluded_particles"]
    if excluded is None:
        excluded = len(expected_missing)
    partvtk = run_partvtkout(binary=partvtkout, solver_output=solver_output, output_dir=output_dir)
    records: list[dict[str, Any]] = []
    if partvtk.get("status") == "completed":
        for row in partvtk["csv"].get("records", []):
            typed_zone = next((z for (z, i) in expected_missing if i == int(row["idp"])), -1)
            identity = (int(typed_zone), int(row["idp"]))
            first = expected_missing.get(identity, {})
            records.append({
                "zone": int(typed_zone), "idp": int(row["idp"]),
                "first_missing_frame": first.get("first_missing_frame"), "first_missing_time_s": first.get("first_missing_time_s"),
                "mass_kg": first.get("mass_kg"), "part_out": int(row["part_out"]),
                "motive_code": int(row["motive_code"]), "motive": "native_solver_excluded_numerical_unknown",
                "position_m": row["position_m"], "density_kg_m3": row["density_kg_m3"],
            })
    observed = {(int(row["zone"]), int(row["idp"])) for row in records}
    expected = set(expected_missing)
    ledger_errors: list[str] = []
    if excluded > 0:
        if partvtk.get("status") != "completed":
            ledger_errors.append("nonzero_exclusions_without_partvtkout_artifact")
        if observed != expected:
            ledger_errors.append("partvtkout_typed_identity_set_mismatch")
        if len(records) != excluded:
            ledger_errors.append("partvtkout_count_mismatch")
    else:
        if expected:
            ledger_errors.append("h5_missing_identities_but_run_out_reports_zero_exclusions")
        if partvtk.get("status") not in {"not_applicable_no_partout_artifact", "completed"}:
            ledger_errors.append("unexpected_zero_exclusion_partvtkout_status")
    for row in records:
        if row["first_missing_frame"] is None or int(row["first_missing_frame"]) < 1:
            ledger_errors.append("first_missing_frame_unresolved")
        if not np.isfinite(np.asarray(row["position_m"], dtype=float)).all() or not np.isfinite(float(row["density_kg_m3"])):
            ledger_errors.append("partvtkout_position_density_nonfinite")
    sums = parts["counters"]
    if int(round(sums["NpOut"]["sum"])) != int(excluded):
        ledger_errors.append("runparts_npout_full_timeline_mismatch")
    if int(round(sums["NpOutPos"]["sum"])) != int(excluded):
        ledger_errors.append("runparts_npoutpos_full_timeline_mismatch")
    if int(round(sums["NpOutRho"]["sum"])) != 0:
        ledger_errors.append("runparts_npoutrho_nonzero")
    ledger = {
        "mode": MODE, "status": "pass" if not ledger_errors else "fail", "errors": sorted(set(ledger_errors)),
        "h5_full_timeline_checked": True, "h5_frames": int(len(time)), "initial_fluid_typed_count": int(fluid.sum()),
        "excluded_typed_count": int(len(records)), "excluded_particles_reported_by_run_out": int(excluded),
        "excluded_particles": records, "runparts_increment_semantics": "NpOut/NpOutPos are per-save increments; sums cover all RunPARTs rows",
        "runparts_counts": {name: value for name, value in sums.items() if name in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov", "NpSim", "NpfSim")},
        "partvtkout": partvtk, "native_exclusion_is_numerical_unknown": True,
        "physical_spill_classification": "separate event labels required; PartVTKOut exclusion is never spill",
    }
    checks = {
        **structural,
        "excluded_count_matches_h5_missing": int(excluded) == len(expected_missing),
        "runparts_npout_full_timeline_matches": int(round(sums["NpOut"]["sum"])) == int(excluded),
        "runparts_npoutpos_full_timeline_matches": int(round(sums["NpOutPos"]["sum"])) == int(excluded),
        "partvtkout_position_density_evidence": (excluded == 0 and partvtk.get("status") in {"not_applicable_no_partout_artifact", "completed"}) or (excluded > 0 and len(records) == excluded and partvtk.get("csv", {}).get("status") == "pass"),
        "native_ledger_complete": ledger["status"] == "pass",
    }
    report = {
        "schema": SCHEMA, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": load_json(owner_metadata, "owner metadata").get("case_id"), "family_id": "F2",
        "trajectory": {"path": str(trajectory), "sha256": sha256(trajectory)},
        "labels": {"path": str(labels), "sha256": sha256(labels)},
        "conversion_report": {"path": str(conversion_report), "sha256": sha256(conversion_report)},
        "owner_metadata": {"path": str(owner_metadata), "sha256": sha256(owner_metadata)},
        "source_bindings": {str(path): {"path": str(path), "sha256": sha256(path)} for path in source_files},
        "solver_logs": {"run_out": log, "run_parts": parts},
        "native_exclusion_ledger": ledger,
        "checks": checks,
        "q_i": {"status": "Q-I-structure-pass" if all(bool(value) for value in checks.values()) else "Q-I-incomplete", "checks": checks, "claim": "evidence-only; root adjudication required"},
        "q_n": {"status": "not_assessed", "reason": "requires independent resolution, internal-step, and save-cadence comparisons"},
        "production_eligibility": "not_evaluated",
    }
    output_dir = output_dir.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "native-exclusion-ledger.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["report"] = {"path": str(report_path), "sha256": sha256(report_path)}
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("trajectory", "labels", "owner-metadata", "conversion-report", "solver-output", "gencase-prefix", "partvtkout", "output-dir"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(trajectory=args.trajectory, labels=args.labels, owner_metadata=args.owner_metadata,
                       conversion_report=args.conversion_report, solver_output=args.solver_output,
                       gencase_prefix=args.gencase_prefix, partvtkout=args.partvtkout, output_dir=args.output_dir)
    except (LedgerError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"f2_handoff_20261002_native_ledger: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "completed", "q_i": result["q_i"], "report": result["report"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
