#!/usr/bin/env python3
"""F5 native BI4 conversion, Q-I audit, and transport preview.

This is the F5 owner entry point for the two already completed coarse native
runs.  ``register`` writes two hash-bound, CPU-only conversion requests.  The
shared DS-DATA-02 runner executes ``convert``; this module then invokes the
copied mature BI4 adapter, which keeps the complete typed initial identity
axis, streams every native frame into immutable HDF5, and checks three real
PartVTK exports.  The owner-side audit adds moving-piston control, finite
source/destination transport labels, gauges, RunPARTs, and preview facts.

No solver, GPU, model, tracer, Q-N gate, or production mutation is performed
here.  The raw solver and BI4 trees are read-only and are never overwritten.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping

import h5py
import numpy as np

SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
WORKTREE_ROOT = SCRIPT.parents[2]
FAMILY = LAB_ROOT / "campaigns/ds-data-02/families/F5"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
OFFICIAL_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
DECODER = OFFICIAL_LAB / "campaigns/l1-resume/artifacts/bi4_dump"
PARTVTK = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
PYTHON = OFFICIAL_LAB / ".venv/bin/python"
EVENT_DEFINITIONS = FAMILY / "event_definitions.json"
QUALITY_CONTRACT = FAMILY / "quality_contract.json"
CONVERTER = LAB_ROOT / "scripts/ds_data02_f5_bi4.py"
CONVERSION_VERSION = "ds-data-02.f5.native-conversion.v1"
EVENT_VERSION = "ds-data-02.f5.native-transport-events.v1"
TMAX = 16.0
EXPECTED_FRAMES = 801
RHO0 = 1000.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


CASE_SPECS: dict[str, dict[str, Any]] = {
    "F5_REF_RUNUP_NOMINAL_COARSE": {
        "mechanism_id": "runup_return",
        "case_root": DATA_ROOT / "F5_REF_RUNUP_NOMINAL_COARSE",
        "attempt_id": "qualification-f5-runup-domain-repair-001",
        "gencase_attempt": "gencase-f5-runup-domain-repair-001",
        "solver_attempt": "qualification-f5-runup-domain-repair-001",
        "generated_xml_name": "F5_REF_RUNUP_NOMINAL_COARSE.xml",
        "motion_name": "piston_f91973457a049db5_regular_piston.dat",
        "metadata": FAMILY / "definitions/F5_REF_RUNUP_NOMINAL_COARSE.metadata.json",
        "background": "runup_return",
        "weir": False,
        "weir_x0": None,
        "weir_x1": None,
        "weir_base_z": None,
        "weir_crest_z": None,
    },
    "F5_REF_WEIR_NOMINAL_COARSE": {
        "mechanism_id": "weir_pair",
        "case_root": DATA_ROOT / "F5_REF_WEIR_NOMINAL_COARSE",
        "attempt_id": "qualification-f5-weir-domain-repair-001",
        "gencase_attempt": "gencase-f5-weir-domain-repair-001",
        "solver_attempt": "qualification-f5-weir-domain-repair-001",
        "generated_xml_name": "F5_REF_WEIR_NOMINAL_COARSE.xml",
        "motion_name": "piston_4c73cd98b7230035_regular_piston.dat",
        "metadata": FAMILY / "definitions/F5_REF_WEIR_NOMINAL_COARSE.metadata.json",
        "background": "weir_pair",
        "weir": True,
        "weir_x0": 4.96,
        "weir_x1": 5.20,
        "weir_base_z": 0.3648,
        "weir_crest_z": 0.4748,
    },
}


def spec_paths(case_id: str) -> dict[str, Path]:
    if case_id not in CASE_SPECS:
        raise ValueError(f"unknown F5 case: {case_id}")
    spec = CASE_SPECS[case_id]
    root = Path(spec["case_root"])
    gencase_root = root / str(spec["gencase_attempt"])
    solver_root = root / str(spec["solver_attempt"])
    data_root = solver_root / "solver_output/data"
    return {
        "case_root": root,
        "gencase_root": gencase_root,
        "solver_root": solver_root,
        "data_root": data_root,
        "generated_xml": gencase_root / str(spec["generated_xml_name"]),
        "generated_bi4": gencase_root / f"{case_id}.bi4",
        "gencase_receipt": gencase_root / "execution-receipt.json",
        "solver_receipt": solver_root / "execution-receipt.json",
        "solver_output": solver_root / "solver_output",
        "run_out": solver_root / "solver_output/Run.out",
        "run_parts": solver_root / "solver_output/RunPARTs.csv",
        "run_csv": solver_root / "solver_output/Run.csv",
        "motion": gencase_root / str(spec["motion_name"]),
        "source_motion": FAMILY / "definitions" / str(spec["motion_name"]),
        # GenCase consumes the STL but does not copy it beside the generated
        # BI4.  Bind the byte-identical F5-owned source asset explicitly.
        "bed": FAMILY / "definitions/assets/f5_continuous_bed_profile_slope_0p280.stl",
    }


def _require_raw(spec: Mapping[str, Any]) -> dict[str, Path]:
    paths = spec_paths(str(spec["case_id"]))
    required = [
        "data_root", "generated_xml", "generated_bi4", "gencase_receipt",
        "solver_receipt", "run_out", "run_parts", "run_csv", "motion",
    ]
    for key in required:
        path = paths[key]
        if not path.exists():
            raise FileNotFoundError(f"F5 raw input missing: {path}")
    frames = sorted(paths["data_root"].glob("Part_*.bi4"))
    if len(frames) != EXPECTED_FRAMES:
        raise ValueError(f"{spec['case_id']} expected {EXPECTED_FRAMES} BI4 frames, got {len(frames)}")
    return paths


def _read_metadata(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("family_id") != "F5":
        raise ValueError(f"invalid F5 metadata: {path}")
    return value


def _physical_binding(spec: Mapping[str, Any], metadata: Mapping[str, Any]) -> dict[str, Any]:
    geometry = metadata.get("geometry", {})
    box = geometry.get("initial_fluid_box", {})
    low = [float(box["x_min_m"]), float(box["y_min_m"]), float(box["z_min_m"])]
    size = [float(box["x_max_m"]) - low[0], float(box["y_max_m"]) - low[1], float(box["z_max_m"]) - low[2]]
    return {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": "F5",
        "physical_case_id": metadata.get("physical_case_id"),
        "lineage_group_id": metadata.get("lineage_group_id"),
        "paired_background_id": metadata.get("paired_background_id"),
        "mechanism_id": spec["mechanism_id"],
        "geometry_family_id": metadata.get("geometry_family_id"),
        "control_family_id": metadata.get("control_family_id"),
        "geometry": {
            "initial_fluid": {"low_m": low, "size_m": size, "mkfluid": 0, "label": "initial continuous fluid box"},
            "finite_tank": {"low_m": [-1.10, -0.80, -0.25], "size_m": [11.90, 1.60, 1.45], "mkfluid": None, "label": "finite solver tank envelope"},
            "continuous_bed": {"low_m": [-1.10, -0.72, -0.25], "size_m": [11.95, 1.44, 1.09], "mkfluid": None, "label": "closed continuous bed STL bounding box"},
            "return_region": {"low_m": [7.15, -0.72, 0.08], "size_m": [3.70, 1.44, 0.40], "mkfluid": 0, "label": "finite downstream return destination"},
        },
        "initial_state": {
            "source_regions": ["initial_fluid"],
            "source_labels": ["upstream_reservoir"],
            "velocities_m_per_s": [[0.0, 0.0, 0.0]],
            "continuum_mass_by_source_kg": [float(np.prod(size) * 1000.0)],
            "initial_mass_total_kg": float(np.prod(size) * 1000.0),
            "mass_policy": "native header MassFluid times native fluid cohort; no rescaling",
        },
        "controls": {
            "step_algorithm": 2,
            "kernel": 2,
            "viscosity": 0.01,
            "density_dt": 2,
            "density_dt_value": 0.1,
            "boundary": "finite DBC floor, finite sidewalls, finite prescribed piston, no periodic y",
        },
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "density_kg_m3": 1000.0,
        "parameters": {
            "initial_depth_m": metadata.get("initial_depth_m"),
            "slope_ratio": metadata.get("slope_ratio"),
            "coordinate_components": 3,
            "finite_source": "upstream_reservoir",
            "finite_destination": "downstream return region and lateral notch for weir_pair",
        },
        "event_window": {
            "time_start_s": 0.0,
            "time_end_s": 16.0,
            "sequence": ["toe_first_arrival", "runup_or_crest_first_passage", "return_crossing", "terminal_destination"],
            "expected_first_contact_range_s": [0.0, 16.0],
            "right_censor_policy": "unseen events at 16 s remain censored and retain initial-mass denominator",
        },
        "open_inlet": False,
        "periodic_boundary": False,
        "mass_policy": "native per-particle mass from BI4 header; type-aware ledger",
    }


def _owner_metadata(case_id: str, paths: Mapping[str, Path]) -> dict[str, Any]:
    spec = CASE_SPECS[case_id]
    metadata = _read_metadata(Path(spec["metadata"]))
    owner = {
        "schema": "ds-data-02.f5.native-owner-metadata.v1",
        "family_id": "F5",
        "case_id": case_id,
        "mechanism_id": spec["mechanism_id"],
        "resolution": "coarse",
        "background": spec["background"],
        "physical_case_id": metadata.get("physical_case_id"),
        "lineage_group_id": metadata.get("lineage_group_id"),
        "paired_background_id": metadata.get("paired_background_id"),
        "geometry_family_id": metadata.get("geometry_family_id"),
        "control_family_id": metadata.get("control_family_id"),
        "recipe_id": metadata.get("recipe_id"),
        "physical_binding": _physical_binding(spec, metadata),
        "source_contract": {
            "finite_source": "initial upstream fluid box x=-0.90..3.30, y=-0.70..0.70, z=0.02..0.42",
            "finite_destinations": ["upstream", "slope_crest", "downstream_return", "weir_notch" if spec["weir"] else "runup_return"],
            "no_posthoc_destination_assignment": True,
            "solver_dimension_required": 3,
            "domain_repair_semantics": "common numerical domain extension only; physical bed, sidewalls, source and control remain bound to fresh F5 XML",
        },
        "source_bindings": {key: bind(path, key) for key, path in {
            "generated_xml": paths["generated_xml"],
            "generated_bi4": paths["generated_bi4"],
            "gencase_receipt": paths["gencase_receipt"],
            "solver_receipt": paths["solver_receipt"],
            "motion_copied_by_gencase": paths["motion"],
            "motion_source": paths["source_motion"],
            "metadata": Path(spec["metadata"]),
            "event_definitions": EVENT_DEFINITIONS,
            "quality_contract": QUALITY_CONTRACT,
        }.items()},
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "written_at_utc": now(),
    }
    return owner


def _all_input_files(case_id: str, owner_path: Path) -> list[Path]:
    paths = spec_paths(case_id)
    spec = CASE_SPECS[case_id]
    values: list[Path] = [
        SCRIPT, CONVERTER, PYTHON, owner_path, EVENT_DEFINITIONS, QUALITY_CONTRACT,
        Path(spec["metadata"]), paths["generated_xml"], paths["generated_bi4"],
        paths["gencase_receipt"], paths["solver_receipt"], paths["run_out"],
        paths["run_parts"], paths["run_csv"], paths["motion"], paths["source_motion"],
        paths["bed"], DECODER, PARTVTK,
    ]
    values.extend(sorted(paths["data_root"].glob("Part_*.bi4")))
    values.extend(sorted(paths["solver_output"].glob("GaugesSWL_*.csv")))
    unique: list[Path] = []
    seen: set[str] = set()
    for value in values:
        value = Path(value).resolve()
        if str(value) not in seen:
            if not value.is_file():
                raise FileNotFoundError(f"conversion input missing: {value}")
            seen.add(str(value))
            unique.append(value)
    return unique


def _conversion_request(case_id: str, owner_path: Path, launch_commit: str) -> dict[str, Any]:
    spec = CASE_SPECS[case_id]
    paths = spec_paths(case_id)
    inputs = _all_input_files(case_id, owner_path)
    attempt = f"native-conversion-{case_id.lower().replace('_', '-')}-001"
    output = "{attempt_root}/native"
    command = [
        str(PYTHON), str(SCRIPT), "convert",
        "--case-id", case_id,
        "--data-root", str(paths["data_root"]),
        "--generated-xml", str(paths["generated_xml"]),
        "--solver-receipt", str(paths["solver_receipt"]),
        "--gencase-receipt", str(paths["gencase_receipt"]),
        "--owner-metadata", str(owner_path),
        "--decoder", str(DECODER),
        "--partvtk", str(PARTVTK),
        "--motion", str(paths["motion"]),
        "--solver-output", str(paths["solver_output"]),
        "--event-definitions", str(EVENT_DEFINITIONS),
        "--quality-contract", str(QUALITY_CONTRACT),
        "--output", output + "/native_all_types.h5",
        "--report", output + "/conversion-report.json",
        "--validation-dir", output + "/partvtk-validation",
        "--audit", output + "/transport-audit.json",
        "--preview", output + "/preview.json",
    ]
    return {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F5",
        "case_id": case_id,
        "attempt_id": attempt,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "command": command,
        "cwd": str(LAB_ROOT),
        "max_wall_seconds": 1800,
        "cpu_threads": 4,
        "estimated_storage_bytes": 25 * 1024 ** 3,
        "input_files": [str(path) for path in inputs],
        "worktree_root": str(WORKTREE_ROOT),
        "launch_commit": launch_commit,
        "conversion_version": CONVERSION_VERSION,
        "input_binding": {
            "mode": "all raw Part_*.bi4 plus solver/gencase/control/source/tool files",
            "file_count": len(inputs),
            "raw_frame_count": EXPECTED_FRAMES,
            "raw_tree_read_only": True,
        },
        "actual_source": {
            "solver_attempt": str(paths["solver_root"]),
            "generated_prefix": str(paths["generated_xml"].with_suffix("")),
            "gencase_receipt": str(paths["gencase_receipt"]),
            "solver_receipt": str(paths["solver_receipt"]),
            "solver_dimension": 3,
            "event_window_s": [0.0, 16.0],
        },
        "resource_review": {
            "estimated_h5_and_sidecars_bytes": 25 * 1024 ** 3,
            "reason": "801 complete typed frames; dense fixed identity axis includes fixed, moving and fluid states",
            "max_concurrent_conversion_requests": 2,
        },
        "qualification_claim": "none",
        "q_i_status": "conversion evidence pending root review",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }


def register(launch_commit: str) -> dict[str, Any]:
    registration_dir = FAMILY / "native_conversion"
    registration_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for case_id in CASE_SPECS:
        paths = _require_raw({**CASE_SPECS[case_id], "case_id": case_id})
        owner_path = registration_dir / f"{case_id}.owner-metadata.json"
        if owner_path.exists():
            raise FileExistsError(f"refusing to overwrite owner metadata: {owner_path}")
        write_json(owner_path, _owner_metadata(case_id, paths))
        request = _conversion_request(case_id, owner_path, launch_commit)
        request_path = registration_dir / f"{case_id}.conversion-request.json"
        if request_path.exists():
            raise FileExistsError(f"refusing to overwrite conversion request: {request_path}")
        write_json(request_path, request)
        rows.append({
            "case_id": case_id,
            "owner_metadata": bind(owner_path, "F5 conversion owner metadata"),
            "request": bind(request_path, "shared CPU conversion request"),
            "input_file_count": len(request["input_files"]),
            "raw_frame_count": EXPECTED_FRAMES,
            "raw_total_bytes": sum(Path(path).stat().st_size for path in request["input_files"] if Path(path).name.startswith("Part_")),
            "estimated_storage_bytes": request["estimated_storage_bytes"],
            "status": "registered_pending_shared_runner",
        })
    index = {
        "schema": "ds-data-02.f5.native-conversion-registration.v1",
        "family_id": "F5",
        "conversion_version": CONVERSION_VERSION,
        "registered_at_utc": now(),
        "launch_commit": launch_commit,
        "requests": rows,
        "concurrency": {"max_simultaneous": 2, "runner_required": True},
        "raw_solver_reuse": "read_only_complete_801_frame_outputs; no solver rerun",
        "q_i_status": "pending_conversion_and_root_review",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
    }
    index_path = registration_dir / "registration-index.json"
    if index_path.exists():
        raise FileExistsError(index_path)
    write_json(index_path, index)
    index["index_binding"] = bind(index_path, "F5 conversion registration index")
    return index


def _parse_motion(path: Path) -> tuple[np.ndarray, np.ndarray]:
    values: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        try:
            values.append((float(fields[0]), float(fields[1])))
        except ValueError:
            continue
    if len(values) < 2:
        raise ValueError(f"motion control has fewer than two samples: {path}")
    array = np.asarray(values, dtype=np.float64)
    if not np.isfinite(array).all() or np.any(np.diff(array[:, 0]) <= 0):
        raise ValueError(f"motion control is not finite and increasing: {path}")
    return array[:, 0], array[:, 1]


def _run_summary(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Excluded particles\.*:\s*([0-9,]+)", text)
    case_np = re.search(r"CaseNp=([0-9,]+)", text)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "finished_code_zero": "Finished execution (code=0)" in text,
        "solver_dimension_3d": bool(re.search(r"\*\*3D-Simulation parameters", text)),
        "excluded_particles": int(match.group(1).replace(",", "")) if match else None,
        "case_np": int(case_np.group(1).replace(",", "")) if case_np else None,
    }


def _runparts_summary(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader((line for line in handle if not line.startswith("#")), delimiter=";")
        for row in reader:
            if row.get("Part", "").isdigit():
                rows.append(row)
    if not rows:
        raise ValueError(f"RunPARTs has no data rows: {path}")
    def f(row: Mapping[str, str], key: str) -> float | None:
        value = row.get(key)
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None
    final = rows[-1]
    np_out = [int(float(row.get("NpOut", "0").replace(",", ""))) for row in rows]
    return {
        "path": str(path),
        "sha256": sha256(path),
        "parts": len(rows),
        "first_time_s": f(rows[0], "TimeStep [s]"),
        "last_time_s": f(final, "TimeStep [s]"),
        "max_np_out": max(np_out),
        "sum_np_out": sum(np_out),
        "max_np_out_pos": max(int(float(row.get("NpOutPos", "0"))) for row in rows),
        "max_np_out_rho": max(int(float(row.get("NpOutRho", "0"))) for row in rows),
        "max_np_out_mov": max(int(float(row.get("NpOutMov", "0"))) for row in rows),
        "min_dt_s": min(f(row, "DtMin [s]") or math.inf for row in rows[1:]),
        "max_dt_s": max(f(row, "DtMax [s]") or -math.inf for row in rows[1:]),
        "no_excluded_particles": all(value == 0 for value in np_out),
    }


def _gauge_summary(solver_output: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in sorted(solver_output.glob("GaugesSWL_*.csv")):
        rows: list[tuple[float, float]] = []
        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            for row in reader:
                try:
                    rows.append((float(row["time [s]"]), float(row["swlz [m]"])))
                except (KeyError, TypeError, ValueError):
                    continue
        if rows:
            time_values = np.asarray([row[0] for row in rows], dtype=np.float64)
            z_values = np.asarray([row[1] for row in rows], dtype=np.float64)
            result[path.stem.removeprefix("GaugesSWL_")] = {
                "path": str(path),
                "sha256": sha256(path),
                "rows": len(rows),
                "time_start_s": float(time_values[0]),
                "time_end_s": float(time_values[-1]),
                "z_min_m": float(z_values.min()),
                "z_max_m": float(z_values.max()),
                "dynamic": bool(np.ptp(z_values) > 1.0e-6),
            }
    return result


def _linear_cross(prev: np.ndarray, cur: np.ndarray, threshold: float, positive: bool) -> tuple[np.ndarray, np.ndarray]:
    if positive:
        hit = (prev < threshold) & (cur >= threshold)
    else:
        hit = (prev > threshold) & (cur <= threshold)
    denom = cur - prev
    alpha = np.zeros(prev.shape, dtype=np.float64)
    np.divide(threshold - prev, denom, out=alpha, where=np.abs(denom) > 1.0e-15)
    return hit, np.clip(alpha, 0.0, 1.0)


def _first_set(first: np.ndarray, mask: np.ndarray, values: np.ndarray) -> None:
    selected = mask & ~np.isfinite(first)
    first[selected] = values[selected]


def _region_code(position: np.ndarray, *, weir: bool) -> np.ndarray:
    x, y, z = position[:, 0], position[:, 1], position[:, 2]
    code = np.full(x.shape, "unknown", dtype="U24")
    code[x < 3.55] = "upstream_source"
    code[(x >= 3.55) & (x < 7.15)] = "slope_crest"
    code[x >= 7.15] = "downstream_return"
    if weir:
        notch = (x >= 4.96) & (x <= 5.20) & (y >= 0.25) & (y <= 0.50) & (z >= 0.3648)
        code[notch] = "weir_notch"
    return code


def _mass_for_event(first_times: np.ndarray, mass: np.ndarray) -> dict[str, Any]:
    observed = np.isfinite(first_times)
    return {
        "observed_particles": int(observed.sum()),
        "observed_mass_kg": float(mass[observed].sum(dtype=np.float64)),
        "observed_mass_fraction_initial": float(mass[observed].sum(dtype=np.float64) / max(float(mass.sum(dtype=np.float64)), 1.0e-30)),
        "right_censored_particles": int((~observed).sum()),
        "right_censored_mass_kg": float(mass[~observed].sum(dtype=np.float64)),
    }


def audit_transport(*, case_id: str, hdf5_path: Path, owner_path: Path, motion_path: Path, solver_output: Path, event_path: Path, quality_path: Path, output: Path, preview: Path, labels_path: Path | None = None) -> dict[str, Any]:
    spec = CASE_SPECS[case_id]
    events_declared = json.loads(event_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    motion_t, motion_x = _parse_motion(motion_path)
    run = _run_summary(solver_output / "Run.out")
    runparts = _runparts_summary(solver_output / "RunPARTs.csv")
    gauges = _gauge_summary(solver_output)
    with h5py.File(hdf5_path, "r") as h:
        required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk", "initial_type", "initial_mk", "initial_mass"}
        missing = sorted(required - set(h.keys()))
        if missing:
            raise ValueError(f"converted H5 lacks required typed datasets: {missing}")
        times = np.asarray(h["time"][:], dtype=np.float64)
        ids = np.asarray(h["particle_id"][:], dtype=np.uint32)
        initial_type = np.asarray(h["initial_type"][:], dtype=np.int8)
        initial_mk = np.asarray(h["initial_mk"][:], dtype=np.int16)
        initial_mass = np.asarray(h["initial_mass"][:], dtype=np.float64)
        if len(times) != EXPECTED_FRAMES or not np.all(np.diff(times) > 0) or times[-1] < 15.99:
            raise ValueError(f"native time axis is incomplete: frames={len(times)} last={times[-1] if len(times) else None}")
        if len(np.unique(ids)) != len(ids):
            raise ValueError("converted typed identity axis contains duplicate Idp")
        fluid_index = np.flatnonzero(initial_type == 3)
        moving_index = np.flatnonzero(initial_type == 1)
        fixed_index = np.flatnonzero(initial_type == 0)
        if not len(fluid_index) or not len(moving_index) or not len(fixed_index):
            raise ValueError("converted native type ledger lacks fixed/moving/fluid cohort")
        fluid_mass = initial_mass[fluid_index]
        moving_initial = np.asarray(h["position"][0, moving_index], dtype=np.float64)
        moving_x0 = float(moving_initial[:, 0].mean())
        moving_rows: list[dict[str, Any]] = []
        event_names = ["toe_first_arrival", "runup_first_crossing", "toe_return_crossing"]
        if spec["weir"]:
            event_names = ["toe_first_arrival", "crest_first_passage", "notch_first_passage", "return_crossing"]
        first: dict[str, np.ndarray] = {name: np.full(len(fluid_index), np.nan, dtype=np.float64) for name in event_names}
        residence = {name: np.zeros(len(fluid_index), dtype=np.float64) for name in ("upstream_source", "slope_crest", "downstream_return", "weir_notch", "unknown")}
        final_position = np.full((len(fluid_index), 3), np.nan, dtype=np.float64)
        all_fluid_valid = np.ones(len(fluid_index), dtype=bool)
        previous_position = None
        previous_time = None
        max_z = -math.inf
        max_z_time = None
        typed_counts: dict[str, dict[str, int]] = {}
        finite_active = True
        for frame_index, time_s in enumerate(times):
            positions = np.asarray(h["position"][frame_index, :], dtype=np.float64)
            velocities = np.asarray(h["velocity"][frame_index, :], dtype=np.float64)
            valid = np.asarray(h["valid"][frame_index, :], dtype=bool)
            types = np.asarray(h["type"][frame_index, :], dtype=np.int8)
            finite_active = finite_active and bool(np.isfinite(positions[valid]).all() and np.isfinite(velocities[valid]).all())
            typed_counts[str(frame_index)] = {str(kind): int(np.sum(types == kind)) for kind in sorted(set(initial_type.tolist()))}
            fluid_pos = positions[fluid_index]
            fluid_vel = velocities[fluid_index]
            fluid_valid = valid[fluid_index]
            all_fluid_valid &= fluid_valid
            if fluid_valid.any():
                current_valid_pos = fluid_pos[fluid_valid]
                local_max = float(np.max(current_valid_pos[:, 2]))
                if local_max > max_z:
                    max_z = local_max
                    max_z_time = float(time_s)
            if previous_position is not None and previous_time is not None:
                dt = float(time_s - previous_time)
                prev = previous_position
                cur = fluid_pos
                both = fluid_valid
                if np.any(both):
                    previous_x = prev[:, 0]
                    current_x = cur[:, 0]
                    # Residence is a saved-frame integral; it is deliberately
                    # separate from event crossing interpolation.
                    regions = _region_code(cur, weir=bool(spec["weir"]))
                    for region in residence:
                        residence[region] += dt * (both & (regions == region))
                    hit, alpha = _linear_cross(previous_x, current_x, 3.55, True)
                    values = previous_time + alpha * dt
                    _first_set(first["toe_first_arrival"], hit & both, values)
                    if spec["weir"]:
                        hit_return, alpha_return = _linear_cross(previous_x, current_x, 3.55, False)
                        _first_set(first["return_crossing"], hit_return & both & np.isfinite(first["toe_first_arrival"]), previous_time + alpha_return * dt)
                        hit_weir, alpha_weir = _linear_cross(previous_x, current_x, float(spec["weir_x1"]), True)
                        z_at = prev[:, 2] + alpha_weir * (cur[:, 2] - prev[:, 2])
                        y_at = prev[:, 1] + alpha_weir * (cur[:, 1] - prev[:, 1])
                        _first_set(first["crest_first_passage"], hit_weir & (z_at >= float(spec["weir_crest_z"])) & both, previous_time + alpha_weir * dt)
                        _first_set(first["notch_first_passage"], hit_weir & (z_at >= float(spec["weir_base_z"])) & (y_at >= 0.25) & (y_at <= 0.50) & both, previous_time + alpha_weir * dt)
                    else:
                        hit_runup, alpha_runup = _linear_cross(previous_x, current_x, 6.70, True)
                        z_runup = prev[:, 2] + alpha_runup * (cur[:, 2] - prev[:, 2])
                        _first_set(first["runup_first_crossing"], hit_runup & (z_runup >= 0.84) & both, previous_time + alpha_runup * dt)
                        hit_return, alpha_return = _linear_cross(previous_x, current_x, 3.55, False)
                        _first_set(first["toe_return_crossing"], hit_return & both & np.isfinite(first["toe_first_arrival"]), previous_time + alpha_return * dt)
            previous_position = fluid_pos.copy()
            previous_time = float(time_s)
            final_position = fluid_pos.copy()
            moving_position = np.asarray(h["position"][frame_index, moving_index], dtype=np.float64)
            moving_velocity = np.asarray(h["velocity"][frame_index, moving_index], dtype=np.float64)
            moving_rows.append({
                "frame": frame_index,
                "time_s": float(time_s),
                "moving_particles": int(len(moving_index)),
                "mean_position_m": moving_position.mean(axis=0).tolist(),
                "mean_velocity_m_s": moving_velocity.mean(axis=0).tolist(),
            })
        expected_motion = np.interp(times, motion_t, motion_x)
        actual_displacement = np.asarray([row["mean_position_m"][0] - moving_x0 for row in moving_rows], dtype=np.float64)
        control_error = actual_displacement - expected_motion
        moving_control = {
            "moving_type": 1,
            "moving_mk_values": sorted(set(initial_mk[moving_index].tolist())),
            "particle_count": int(len(moving_index)),
            "initial_mean_position_m": moving_initial.mean(axis=0).tolist(),
            "final_mean_position_m": moving_rows[-1]["mean_position_m"],
            "expected_control_source": str(motion_path),
            "expected_control_sha256": sha256(motion_path),
            "max_abs_mean_x_displacement_error_m": float(np.max(np.abs(control_error))),
            "rmse_mean_x_displacement_error_m": float(np.sqrt(np.mean(control_error ** 2))),
            "actual_state_samples": [moving_rows[i] for i in sorted(set((0, 1, len(moving_rows)//2, len(moving_rows)-1)))],
            "control_coverage_start_end_s": [float(motion_t[0]), float(motion_t[-1])],
        }
        destinations = _region_code(final_position, weir=bool(spec["weir"]))
        destination = {}
        for name in residence:
            selected = destinations == name
            destination[name] = {
                "particles": int(selected.sum()),
                "mass_kg": float(fluid_mass[selected].sum(dtype=np.float64)),
            }
        first_summary = {name: _mass_for_event(values, fluid_mass) for name, values in first.items()}
        if spec["weir"]:
            overtop = first_summary["crest_first_passage"]["observed_particles"] > 0
            overtop_status = "observed_overtopping" if overtop else "right_censored_no_crest_event"
        else:
            overtop_status = "not_applicable"
        mass_total = float(fluid_mass.sum(dtype=np.float64))
        terminal_unknown = float(destination.get("unknown", {}).get("mass_kg", 0.0))
        type_initial = {str(kind): int(np.sum(initial_type == kind)) for kind in sorted(set(initial_type.tolist()))}
        type_final = {str(kind): int(np.sum(np.asarray(h["type"][-1], dtype=np.int8) == kind)) for kind in sorted(set(initial_type.tolist()))}
        audit = {
            "schema": EVENT_VERSION,
            "case_id": case_id,
            "mechanism_id": spec["mechanism_id"],
            "status": "native_conversion_audit_complete_pending_root_review",
            "qualification_claim": "none",
            "q_n_status": "not_assessed",
            "production_eligibility": "not_evaluated",
            "native": {
                "hdf5": str(hdf5_path),
                "hdf5_sha256": sha256(hdf5_path),
                "frames": int(len(times)),
                "time_start_s": float(times[0]),
                "time_end_s": float(times[-1]),
                "particle_count": int(len(ids)),
                "initial_type_counts": type_initial,
                "final_type_counts": type_final,
                "initial_mk_counts": {str(mk): int(np.sum(initial_mk == mk)) for mk in sorted(set(initial_mk.tolist()))},
                "fixed_particles": int(len(fixed_index)),
                "moving_particles": int(len(moving_index)),
                "fluid_particles": int(len(fluid_index)),
                "fluid_initial_mass_kg": mass_total,
                "finite_active_values": finite_active,
            },
            "source_and_solver_contract": {
                "owner_metadata": bind(owner_path, "F5 physical source/control owner contract"),
                "event_definitions": bind(event_path, "pre-registered F5 event definitions"),
                "quality_contract": bind(quality_path, "pre-registered F5 quality contract"),
                "run_summary": run,
                "runparts_summary": runparts,
                "raw_gauges": gauges,
                "finite_source": owner["source_contract"]["finite_source"],
                "finite_destinations": owner["source_contract"]["finite_destinations"],
                "domain_repair_semantics": owner["source_contract"]["domain_repair_semantics"],
            },
            "moving_piston": moving_control,
            "transport_events": {
                "declared_event_schema": events_declared.get("schema"),
                "first_passage_rules": "saved-frame signed crossings with linear interpolation; repeated crossings are not relabeled as first passage",
                "events": first_summary,
                "overtop_or_no_overtop": overtop_status,
                "peak_fluid_z_m": None if not math.isfinite(max_z) else float(max_z),
                "peak_fluid_z_time_s": max_z_time,
                "residence_time_s_by_source_destination": {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in residence.items()},
                "terminal_destination": destination,
                "unknown_mass_kg": terminal_unknown,
                "unknown_mass_fraction_initial": terminal_unknown / max(mass_total, 1.0e-30),
            },
            "error_budget_registration": quality.get("q_n", {}),
            "integrity": {
                "complete_window": bool(len(times) == EXPECTED_FRAMES and times[-1] >= 15.99),
                "type_axis_fixed": True,
                "mass_rescaling": False,
                "native_partvtk_qi": "see conversion-report.json partvtk_validation; three real frames required",
            },
            "written_at_utc": now(),
        }
        preview_value = {
            "schema": "ds-data-02.f5.preview.v1",
            "case_id": case_id,
            "qualification_claim": "none",
            "sample_frames": [moving_rows[i] | {"fluid_z_max_m": float(np.nanmax(np.asarray(h["position"][i, fluid_index, 2], dtype=np.float64)))} for i in sorted(set((0, 1, len(times)//4, len(times)//2, 3*len(times)//4, len(times)-1)))],
            "gauge_preview": gauges,
            "event_preview": {key: {k: value[k] for k in ("observed_particles", "observed_mass_kg", "observed_mass_fraction_initial", "right_censored_particles")} for key, value in first_summary.items()},
            "moving_piston_preview": moving_control,
            "source_hdf5": {"path": str(hdf5_path), "sha256": sha256(hdf5_path)},
            "window_s": [float(times[0]), float(times[-1])],
            "actual_preview": True,
            "written_at_utc": now(),
        }
        if labels_path is not None:
            labels_path = Path(labels_path).resolve()
            if labels_path.exists():
                raise FileExistsError(f"refusing to overwrite transport labels: {labels_path}")
            labels_path.parent.mkdir(parents=True, exist_ok=True)
            label_partial = labels_path.with_suffix(labels_path.suffix + ".partial")
            string_dtype = h5py.string_dtype(encoding="utf-8", length=32)
            with h5py.File(label_partial, "w") as labels_h5:
                labels_h5.attrs["schema"] = "ds-data-02.f5.transport-labels.v1"
                labels_h5.attrs["source_hdf5"] = str(hdf5_path)
                labels_h5.attrs["source_hdf5_sha256"] = sha256(hdf5_path)
                labels_h5.attrs["identity_key"] = "(Zone,Idp)"
                labels_h5.attrs["initial_source_semantics"] = "initial type=3 fluid cohort; source label is upstream_reservoir"
                labels_h5.attrs["event_semantics"] = "first saved-frame signed crossing with linear interpolation; unseen events are NaN/right-censored"
                labels_h5.attrs["residence_semantics"] = "sum of native saved-frame intervals by finite source/destination region"
                labels_h5.attrs["qualification_claim"] = "none"
                labels_h5.attrs["q_n_status"] = "not_assessed"
                labels_h5.create_dataset("particle_id", data=ids[fluid_index], dtype="u4")
                labels_h5.create_dataset("particle_zone", data=np.asarray(h["particle_zone"][fluid_index], dtype=np.int16), dtype="i2")
                labels_h5.create_dataset("initial_mk", data=initial_mk[fluid_index], dtype="i2")
                labels_h5.create_dataset("mass_kg", data=fluid_mass.astype(np.float32), dtype="f4")
                labels_h5.create_dataset(
                    "initial_source_label",
                    data=np.asarray(["upstream_reservoir"] * len(fluid_index), dtype=string_dtype),
                    dtype=string_dtype,
                )
                for event_name, values in first.items():
                    labels_h5.create_dataset(f"first_{event_name}_time_s", data=values.astype(np.float64), dtype="f8")
                for region, values in residence.items():
                    labels_h5.create_dataset(f"residence_{region}_s", data=values.astype(np.float64), dtype="f8")
                labels_h5.create_dataset("terminal_destination", data=np.asarray(destinations, dtype=string_dtype), dtype=string_dtype)
                labels_h5.create_dataset("valid_all_frames", data=all_fluid_valid, dtype="bool")
                labels_h5.attrs["complete"] = True
            label_partial.replace(labels_path)
            audit_labels = {"path": str(labels_path), "sha256": sha256(labels_path), "bytes": labels_path.stat().st_size, "particles": int(len(fluid_index)), "schema": "ds-data-02.f5.transport-labels.v1"}
            audit["transport_labels"] = audit_labels
            preview_value["transport_labels"] = audit_labels
    write_json(output, audit)
    write_json(preview, preview_value)
    return audit


def convert(args: argparse.Namespace) -> dict[str, Any]:
    if str(args.case_id) not in CASE_SPECS:
        raise ValueError(f"unknown F5 case: {args.case_id}")
    if args.output.exists() or args.report.exists() or args.audit.exists() or args.preview.exists():
        raise FileExistsError("conversion outputs must be fresh; refusing overwrite")
    if not args.data_root.is_dir() or not args.generated_xml.is_file():
        raise FileNotFoundError("raw BI4 data or generated XML missing")
    sys.path.insert(0, str(LAB_ROOT))
    from scripts import ds_data02_f5_bi4 as adapter
    report = adapter.convert_direct(
        data_root=args.data_root.resolve(),
        generated_xml=args.generated_xml.resolve(),
        output=args.output.resolve(),
        report_path=args.report.resolve(),
        decoder=args.decoder.resolve(),
        partvtk=args.partvtk.resolve(),
        validation_dir=args.validation_dir.resolve(),
        solver_log=(args.solver_output / "Run.out").resolve(),
        solver_receipt=args.solver_receipt.resolve(),
        gencase_receipt=args.gencase_receipt.resolve(),
        owner_metadata=args.owner_metadata.resolve(),
        run_partvtk=True,
        keep_validation_csv=True,
    )
    audit = audit_transport(
        case_id=args.case_id,
        hdf5_path=args.output.resolve(),
        owner_path=args.owner_metadata.resolve(),
        motion_path=args.motion.resolve(),
        solver_output=args.solver_output.resolve(),
        event_path=args.event_definitions.resolve(),
        quality_path=args.quality_contract.resolve(),
        output=args.audit.resolve(),
        preview=args.preview.resolve(),
    )
    print(json.dumps({
        "status": audit["status"],
        "case_id": args.case_id,
        "frames": report["frames"],
        "particles": report["particles"],
        "partvtk_all_passed": report["partvtk_validation"]["all_passed"],
        "fluid_particles": audit["native"]["fluid_particles"],
        "moving_particles": audit["native"]["moving_particles"],
        "q_n_status": "not_assessed",
    }, sort_keys=True))
    return audit


def label_only(args: argparse.Namespace) -> dict[str, Any]:
    paths = [args.hdf5, args.owner_metadata, args.motion, args.solver_output / "Run.out", args.solver_output / "RunPARTs.csv", args.event_definitions, args.quality_contract]
    if any(not Path(path).exists() for path in paths):
        raise FileNotFoundError("label-only input is missing")
    if args.output.exists() or args.preview.exists() or args.labels.exists():
        raise FileExistsError("label-only outputs must be fresh; refusing overwrite")
    result = audit_transport(
        case_id=args.case_id,
        hdf5_path=args.hdf5.resolve(),
        owner_path=args.owner_metadata.resolve(),
        motion_path=args.motion.resolve(),
        solver_output=args.solver_output.resolve(),
        event_path=args.event_definitions.resolve(),
        quality_path=args.quality_contract.resolve(),
        output=args.output.resolve(),
        preview=args.preview.resolve(),
        labels_path=args.labels.resolve(),
    )
    print(json.dumps({"status": result["status"], "case_id": args.case_id, "labels": result.get("transport_labels"), "q_n_status": "not_assessed"}, sort_keys=True))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--launch-commit", required=True)
    con = sub.add_parser("convert")
    con.add_argument("--case-id", required=True)
    con.add_argument("--data-root", type=Path, required=True)
    con.add_argument("--generated-xml", type=Path, required=True)
    con.add_argument("--solver-receipt", type=Path, required=True)
    con.add_argument("--gencase-receipt", type=Path, required=True)
    con.add_argument("--owner-metadata", type=Path, required=True)
    con.add_argument("--decoder", type=Path, required=True)
    con.add_argument("--partvtk", type=Path, required=True)
    con.add_argument("--motion", type=Path, required=True)
    con.add_argument("--solver-output", type=Path, required=True)
    con.add_argument("--event-definitions", type=Path, required=True)
    con.add_argument("--quality-contract", type=Path, required=True)
    con.add_argument("--output", type=Path, required=True)
    con.add_argument("--report", type=Path, required=True)
    con.add_argument("--validation-dir", type=Path, required=True)
    con.add_argument("--audit", type=Path, required=True)
    con.add_argument("--preview", type=Path, required=True)
    lab = sub.add_parser("label")
    lab.add_argument("--case-id", required=True)
    lab.add_argument("--hdf5", type=Path, required=True)
    lab.add_argument("--owner-metadata", type=Path, required=True)
    lab.add_argument("--motion", type=Path, required=True)
    lab.add_argument("--solver-output", type=Path, required=True)
    lab.add_argument("--event-definitions", type=Path, required=True)
    lab.add_argument("--quality-contract", type=Path, required=True)
    lab.add_argument("--output", type=Path, required=True)
    lab.add_argument("--preview", type=Path, required=True)
    lab.add_argument("--labels", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "register":
        print(json.dumps(register(args.launch_commit), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "label":
        label_only(args)
        return 0
    convert(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
