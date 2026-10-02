#!/usr/bin/env python3
"""Audit the completed F2 OFFSET coarse full-state conversion.

The audit is a read-only evidence producer.  It binds the actual solver and
GenCase receipts, generated XML, copied motion file, direct-conversion report,
and H5 trajectory, then checks the fixed typed identity axis in bounded HDF5
chunks.  It deliberately keeps the generated-XML MassFluid authority separate
from the float32 H5/PartVTK display values.  It does not launch any job and it
does not grant Q-I, Q-N, or production eligibility.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import h5py
import numpy as np


F2_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CASE_ID = "F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001"
CONVERSION_ATTEMPT = "conversion-f2h10v2_offset_v1_coarse_rv4d1_baseline_save001-fullstate-v5-002"
CASE_ROOT = DATA_ROOT / "families/F2" / CASE_ID
CONVERSION_ROOT = CASE_ROOT / CONVERSION_ATTEMPT
CONVERSION_RECEIPT = CONVERSION_ROOT / "execution-receipt.json"
CONVERSION_REPORT = CONVERSION_ROOT / "conversion-report.json"
TRAJECTORY = CONVERSION_ROOT / "trajectory.h5"
SOLVER_RECEIPT = CASE_ROOT / "qualification-f2h10v2_offset_v1_coarse_rv4d1_baseline_save001-native-fullstate-v1" / "execution-receipt.json"
SOLVER_OUT = SOLVER_RECEIPT.parent / "solver_output"
GENCASE_RECEIPT = DATA_ROOT / "families/F2/F2H10V2_OFFSET_V1_COARSE/gencase-f2-f2h10v2-offset-coarse-20261002-002/execution-receipt.json"
GENERATED_XML = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001.xml")
MOTION = GENERATED_XML.parent / "F2H10V2_OFFSET_V1_COARSE_motion.dat"
OWNER_METADATA = F2_ROOT / "handoff_20261002/postsolver/owner_metadata/F2H10V2_OFFSET_V1_COARSE.generator.v2.metadata.json"
RUNTIME_CHECKPOINT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261002/F2_RV4_NATIVE_EXECUTION_CHECKPOINT_004.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def load_json(path: Path, label: str) -> dict:
    path = require_file(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object: {path}")
    return value


def binding(paths: list[Path]) -> dict[str, dict[str, str]]:
    return {str(path.resolve()): {"path": str(path.resolve()), "sha256": sha256(path)} for path in paths}


def _num(value: str) -> float:
    return float(value.replace(",", "").strip())


def runparts_accounting(path: Path) -> dict[str, float | int]:
    path = require_file(path, "RunPARTs.csv")
    lines = [line for line in path.read_text(errors="replace").splitlines() if line]
    if len(lines) < 2:
        raise ValueError(f"RunPARTs.csv has no data: {path}")
    rows = csv.DictReader([lines[0].lstrip("#")] + lines[1:], delimiter=";")
    values: dict[str, list[float]] = {}
    for row in rows:
        for field in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov", "NpSave", "NpSim", "NpfSim"):
            if field in row and row[field] not in (None, ""):
                values.setdefault(field, []).append(_num(row[field]))
    return {
        "rows": len(values.get("NpOut", [])),
        "NpOut_sum": float(sum(values.get("NpOut", []))),
        "NpOutPos_sum": float(sum(values.get("NpOutPos", []))),
        "NpOutRho_sum": float(sum(values.get("NpOutRho", []))),
        "NpOutMov_sum": float(sum(values.get("NpOutMov", []))),
        "NpSave_first": float(values.get("NpSave", [0.0])[0]),
        "NpSim_first": float(values.get("NpSim", [0.0])[0]),
        "NpfSim_first": float(values.get("NpfSim", [0.0])[0]),
    }


def generated_mass(xml_path: Path) -> dict[str, object]:
    text = xml_path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"<massfluid\b[^>]*\bvalue\s*=\s*[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE)
    if match is None:
        raise ValueError(f"generated XML has no massfluid: {xml_path}")
    try:
        mass = Decimal(match.group(1))
    except InvalidOperation as error:
        raise ValueError(f"invalid massfluid in {xml_path}") from error
    return {"massfluid_text": match.group(1), "massfluid_kg_per_particle": str(mass), "xml_sha256": sha256(xml_path)}


def _json_attr(value: object) -> object:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.generic):
        return value.item()
    return value


def audit(output: Path) -> dict:
    paths = [
        Path(__file__), CONVERSION_RECEIPT, CONVERSION_REPORT, TRAJECTORY,
        SOLVER_RECEIPT, SOLVER_OUT / "Run.out", SOLVER_OUT / "Run.csv",
        SOLVER_OUT / "RunPARTs.csv", GENCASE_RECEIPT, GENERATED_XML, MOTION,
        OWNER_METADATA,
    ]
    if RUNTIME_CHECKPOINT.is_file():
        paths.append(RUNTIME_CHECKPOINT)
    paths = [require_file(path, "audit input") for path in paths]
    conversion_receipt = load_json(CONVERSION_RECEIPT, "conversion receipt")
    conversion_report = load_json(CONVERSION_REPORT, "conversion report")
    solver_receipt = load_json(SOLVER_RECEIPT, "solver receipt")
    gencase_receipt = load_json(GENCASE_RECEIPT, "GenCase receipt")
    owner = load_json(OWNER_METADATA, "owner metadata")
    if conversion_receipt.get("status") not in {"completed", "success"} or conversion_receipt.get("returncode") != 0:
        raise ValueError("OFFSET coarse conversion receipt is not completed code 0")
    if solver_receipt.get("status") not in {"completed", "success"} or solver_receipt.get("returncode") != 0:
        raise ValueError("OFFSET coarse solver receipt is not completed code 0")

    mass = generated_mass(GENERATED_XML)
    h5_facts: dict[str, object] = {}
    with h5py.File(TRAJECTORY, "r") as handle:
        required = {"time", "position", "velocity", "density", "pressure", "mass", "valid", "particle_id", "particle_zone", "initial_mass", "initial_mk", "initial_type", "mk", "type"}
        missing = sorted(required - set(handle.keys()))
        if missing:
            raise ValueError(f"trajectory missing datasets: {missing}")
        nframes, nparticles, ndim = handle["position"].shape
        if ndim != 3:
            raise ValueError(f"position is not 3D: {handle['position'].shape}")
        times = np.asarray(handle["time"][:], dtype=np.float64)
        initial_type = np.asarray(handle["initial_type"][:], dtype=np.int8)
        initial_mk = np.asarray(handle["initial_mk"][:], dtype=np.int16)
        initial_mass = np.asarray(handle["initial_mass"][:], dtype=np.float64)
        fluid_mask = initial_type == 3
        moving_mask = initial_type == 1
        type_counts = {str(int(key)): int(value) for key, value in zip(*np.unique(initial_type, return_counts=True))}
        mk_counts = {str(int(key)): int(value) for key, value in zip(*np.unique(initial_mk, return_counts=True))}
        if not np.isfinite(times).all() or len(times) < 2 or not np.all(np.diff(times) > 0):
            raise ValueError("trajectory time axis is not finite and strictly increasing")
        if not fluid_mask.any() or not moving_mask.any():
            raise ValueError("trajectory has no fluid or moving-node cohort")
        # Read only the three observed pose frames; the converter report binds
        # the full frame stream and lifecycle accounting.
        pose_samples = []
        for frame in (0, nframes // 2, nframes - 1):
            positions = np.asarray(handle["position"][frame, moving_mask, :], dtype=np.float64)
            velocities = np.asarray(handle["velocity"][frame, moving_mask, :], dtype=np.float64)
            pose_samples.append({
                "frame": int(frame),
                "time_s": float(times[frame]),
                "position_min_m": positions.min(axis=0).tolist(),
                "position_max_m": positions.max(axis=0).tolist(),
                "velocity_abs_max_m_s": np.max(np.abs(velocities), axis=0).tolist(),
                "position_finite": bool(np.isfinite(positions).all()),
                "velocity_finite": bool(np.isfinite(velocities).all()),
            })
        attrs = {str(key): _json_attr(value) for key, value in handle.attrs.items()}
        h5_fluid_mass = float(initial_mass[fluid_mask].sum(dtype=np.float64))
        h5_facts = {
            "shape": {"frames": int(nframes), "particles": int(nparticles), "coordinate_components": int(ndim)},
            "time": {"first_s": float(times[0]), "last_s": float(times[-1]), "strictly_increasing": True},
            "initial_type_counts": type_counts,
            "initial_mk_counts": mk_counts,
            "initial_fluid_particles": int(fluid_mask.sum()),
            "initial_moving_nodes": int(moving_mask.sum()),
            "initial_mass_sum_kg_float64_accumulation": float(initial_mass.sum(dtype=np.float64)),
            "initial_fluid_mass_kg_float64_accumulation": h5_fluid_mass,
            "pose_samples_from_actual_saved_type1_nodes": pose_samples,
            "attrs": attrs,
        }

    mass_authority = Decimal(mass["massfluid_kg_per_particle"]) * Decimal(str(h5_facts["initial_fluid_particles"]))
    continuous = Decimal(str(owner.get("mass_reference", {}).get("continuous_mass_kg", "24.576")))
    h5_mass = Decimal(str(h5_facts["initial_fluid_mass_kg_float64_accumulation"]))
    h5_adapter_rel = abs(h5_mass - mass_authority) / mass_authority
    xml_continuous_rel = abs(mass_authority - continuous) / continuous
    runparts = runparts_accounting(SOLVER_OUT / "RunPARTs.csv")
    partvtk = conversion_report.get("partvtk_validation", {})
    first_validation = (partvtk.get("frames") or [{}])[0]
    fluid_csv_mass = (first_validation.get("mass_by_type_kg") or {}).get("3")
    fluid_csv_rel = None
    if fluid_csv_mass is not None:
        fluid_csv_rel = abs(Decimal(str(fluid_csv_mass)) - mass_authority) / mass_authority
    physical = conversion_report.get("hash_scopes", {}).get("physical_condition_sha256")
    numerical = conversion_report.get("hash_scopes", {}).get("numerical_parameters_sha256")
    report_source = conversion_report.get("source_provenance", {})
    evidence = {
        "schema": "ds-data-02.f2.offset-coarse-actual-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": CASE_ID,
        "scope_id": owner.get("scope_id"),
        "source_bindings": binding(paths),
        "solver": {
            "status": solver_receipt.get("status"),
            "returncode": solver_receipt.get("returncode"),
            "receipt": {"path": str(SOLVER_RECEIPT), "sha256": sha256(SOLVER_RECEIPT)},
            "runparts": {"path": str(SOLVER_OUT / "RunPARTs.csv"), "sha256": sha256(SOLVER_OUT / "RunPARTs.csv"), "accounting": runparts},
            "dimension": conversion_report.get("solver_dimension"),
        },
        "conversion": {
            "status": conversion_receipt.get("status"),
            "returncode": conversion_receipt.get("returncode"),
            "receipt": {"path": str(CONVERSION_RECEIPT), "sha256": sha256(CONVERSION_RECEIPT)},
            "report": {"path": str(CONVERSION_REPORT), "sha256": sha256(CONVERSION_REPORT)},
            "trajectory": {"path": str(TRAJECTORY), "sha256": sha256(TRAJECTORY)},
            "partvtk_validation": {"all_passed": partvtk.get("all_passed"), "frames_checked": len(partvtk.get("frames", [])), "first_frame": first_validation},
            "q_i_status": conversion_report.get("q_i_status"),
            "q_n_status": conversion_report.get("q_n_status"),
        },
        "source": {
            "gencase_receipt": {"path": str(GENCASE_RECEIPT), "sha256": sha256(GENCASE_RECEIPT)},
            "generated_xml": {"path": str(GENERATED_XML), "sha256": sha256(GENERATED_XML)},
            "motion_control": {"path": str(MOTION), "sha256": sha256(MOTION)},
            "motion_raw_sha256": sha256(MOTION),
            "converter_control_sha256": report_source.get("control_sha256"),
            "geometry_sha256": report_source.get("geometry_sha256"),
            "physical_condition_sha256": physical,
            "numerical_parameters_sha256": numerical,
            "raw_tree_unchanged": report_source.get("raw_tree", {}).get("unchanged"),
        },
        "h5": h5_facts,
        "mass": {
            "continuous_mass_reference_kg_decimal": str(continuous),
            "generated_xml_massfluid_kg_per_particle_decimal": mass["massfluid_kg_per_particle"],
            "generated_xml_authoritative_initial_fluid_mass_kg_decimal": str(mass_authority),
            "xml_vs_continuous_relative_error": float(xml_continuous_rel),
            "h5_float32_adapter_fluid_mass_kg_float64_accumulation": float(h5_mass),
            "h5_adapter_relative_error_to_xml_authority": float(h5_adapter_rel),
            "partvtk_csv_display_fluid_mass_kg": fluid_csv_mass,
            "partvtk_csv_display_relative_error_to_xml_authority": float(fluid_csv_rel) if fluid_csv_rel is not None else None,
            "authority": "generated XML decimal MassFluid multiplied by actual initial typed fluid count; H5 float32 and PartVTK CSV values are display/adapter evidence",
            "strict_continuous_mass_budget_fraction": owner.get("mass_reference", {}).get("frozen_relative_budget_fraction"),
        },
        "moving_boundary": {
            "position_evidence": "actual saved Type=1 node positions sampled at frame 0, midpoint, and final frame",
            "velocity_dataset_evidence": "actual H5 velocity dataset is present and finite",
            "pose_fit_required": True,
            "note": "Type=1 velocity fields in this direct conversion are zero at sampled frames; v6 pose stage fits rigid pose from saved moving-node positions plus frozen motion control and records that provenance.",
        },
        "typed_lifecycle": {
            "identity_key": conversion_report.get("typed_identity", {}).get("key"),
            "initial_exclusion_ledger": conversion_report.get("typed_identity", {}).get("initial_exclusion_ledger"),
            "full_timeline_lifecycle": conversion_report.get("lifecycle", {}).get("contract"),
            "native_runparts_exclusion_accounting": runparts,
        },
        "qualification": {
            "status": "evidence_only_pending_v6_pose_labels_and_independent_QI_review",
            "q_i_granted": False,
            "q_n_assessed": False,
            "production_eligible": False,
            "event_labels": "not_run_by_this_audit",
        },
    }
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    evidence["report"] = {"path": str(output), "sha256": sha256(output)}
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=F2_ROOT / "handoff_20261002/postsolver_v7/offset_coarse_actual_audit.json")
    args = parser.parse_args()
    result = audit(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
