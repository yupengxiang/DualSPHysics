#!/usr/bin/env python3
"""Generate owner metadata and direct conversion requests for F5 Stage 8 production cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_direct_convert import _validate_physical_binding, sha256_file

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
FAMILY_ID = "F5"
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F5"
BIN_ROOT = REPO / "vendor/official/DualSPHysics_v5.4/bin/linux"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = BIN_ROOT / "PartVTK_linux64"
CONVERT_PY = REPO / "scripts/ds_data02_direct_convert.py"

STAGE8_CASES = [
    "F5_RUNUP_00",
    "F5_WEIR_00",
    "F5_RUNUP_01",
    "F5_WEIR_01",
    "F5_RUNUP_02",
    "F5_WEIR_02",
    "F5_RUNUP_03",
    "F5_WEIR_03",
]


def make_f5_stage8_owner(case_id: str, family_dir: Path = FAMILY_DIR) -> Path:
    family_dir = Path(family_dir).resolve()
    meta_path = family_dir / f"production/definitions/{case_id}.metadata.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"missing metadata: {meta_path}")
    metadata = json.loads(meta_path.read_text())

    case_data_dir = DATA_ROOT / "families/F5" / case_id

    # Find latest completed qualification solver run
    qual_dirs = sorted(case_data_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_receipt_path = None
    for qd in reversed(qual_dirs):
        rec = qd / "execution-receipt.json"
        if rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0:
                    solver_receipt_path = rec
                    break
            except Exception:
                pass
    if not solver_receipt_path:
        raise FileNotFoundError(f"missing completed solver receipt for {case_id}")

    # Find latest completed GenCase run
    gencase_dirs = sorted(case_data_dir.glob(f"{case_id}_GENCASE_*"))
    gencase_receipt_path = None
    for gd in reversed(gencase_dirs):
        rec = gd / "execution-receipt.json"
        if rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0 and data.get("fluid_particles", 0) > 0:
                    gencase_receipt_path = rec
                    break
            except Exception:
                pass
    if not gencase_receipt_path:
        raise FileNotFoundError(f"missing completed gencase receipt for {case_id}")

    depth = float(metadata["initial_depth_m"])
    slope = float(metadata["slope_ratio"])
    mass_total = round(4.2 * 1.4 * depth * 1000.0, 4)

    physical_binding = {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": "F5",
        "physical_case_id": metadata["physical_case_id"],
        "mechanism_id": metadata["mechanism_id"],
        "geometry_family_id": metadata["geometry_family_id"],
        "control_family_id": metadata["control_family_id"],
        "geometry": {
            "continuous_bed": {
                "label": "closed continuous bed STL bounding box",
                "low_m": [-1.1, -0.72, -0.25],
                "size_m": [11.95, 1.44, 1.09]
            },
            "finite_tank": {
                "label": "finite solver tank envelope",
                "low_m": [-1.1, -0.8, -0.25],
                "size_m": [11.9, 1.6, 1.45]
            },
            "initial_fluid": {
                "label": "initial continuous fluid box",
                "low_m": [-0.9, -0.7, 0.02],
                "size_m": [4.2, 1.4, depth]
            },
            "return_region": {
                "label": "finite downstream return destination",
                "low_m": [7.15, -0.72, 0.08],
                "size_m": [3.7, 1.44, 0.4]
            }
        },
        "initial_state": {
            "source_regions": ["initial_fluid"],
            "source_labels": ["upstream_reservoir"],
            "velocities_m_per_s": [[0.0, 0.0, 0.0]],
            "initial_mass_total_kg": mass_total,
            "continuum_mass_by_source_kg": [mass_total],
            "mass_policy": "native header MassFluid times native fluid cohort; no rescaling"
        },
        "controls": {
            "boundary": "finite DBC floor, finite sidewalls, finite prescribed piston, no periodic y",
            "density_dt": 2,
            "density_dt_value": 0.1,
            "kernel": 2,
            "step_algorithm": 2,
            "viscosity": 0.01
        },
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "density_kg_m3": 1000.0,
        "parameters": {
            "coordinate_components": 3,
            "finite_destination": "downstream return region and lateral notch for weir_pair",
            "finite_source": "upstream_reservoir",
            "initial_depth_m": depth,
            "slope_ratio": slope
        },
        "event_window": {
            "time_start_s": 0.0,
            "time_end_s": 16.0,
            "expected_first_contact_range_s": [0.0, 16.0],
            "right_censor_policy": "unseen events at 16 s remain censored and retain initial-mass denominator",
            "sequence": ["toe_first_arrival", "runup_or_crest_first_passage", "return_crossing", "terminal_destination"]
        },
        "lineage_group_id": metadata["lineage_group_id"],
        "paired_background_id": metadata["paired_background_id"],
        "open_inlet": False,
        "periodic_boundary": False,
        "mass_policy": "native per-particle mass from BI4 header; type-aware ledger"
    }

    _validate_physical_binding(physical_binding)

    owner = {
        "schema": "ds-data-02.f5.native-owner-metadata.v1",
        "family_id": "F5",
        "case_id": case_id,
        "physical_case_id": metadata["physical_case_id"],
        "resolution": "medium",
        "mechanism_id": metadata["mechanism_id"],
        "background": metadata["background"],
        "physical_binding": physical_binding,
        "source_solver_binding": {
            "path": str(solver_receipt_path),
            "sha256": sha256_file(solver_receipt_path)
        },
        "source_gencase_binding": {
            "path": str(gencase_receipt_path),
            "sha256": sha256_file(gencase_receipt_path)
        },
        "product_boundary": "Stage 8 production full native state"
    }

    owner_dir = family_dir / "production/owner_metadata"
    owner_dir.mkdir(parents=True, exist_ok=True)
    owner_path = owner_dir / f"{case_id}.owner.json"
    owner_path.write_text(json.dumps(owner, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return owner_path


def emit_f5_stage8_conversion_request(case_id: str, family_dir: Path = FAMILY_DIR, attempt_id: str = "full-typed-native-conversion-001") -> Path:
    family_dir = Path(family_dir).resolve()
    owner_path = make_f5_stage8_owner(case_id, family_dir)

    case_data_dir = DATA_ROOT / "families/F5" / case_id

    # Find latest completed qualification solver run
    qual_dirs = sorted(case_data_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_receipt = None
    solver_dir = None
    for qd in reversed(qual_dirs):
        rec = qd / "execution-receipt.json"
        if rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0:
                    solver_receipt = rec
                    solver_dir = qd / "solver"
                    break
            except Exception:
                pass

    gencase_dirs = sorted(case_data_dir.glob(f"{case_id}_GENCASE_*"))
    gencase_receipt = None
    gencase_dir = None
    for gd in reversed(gencase_dirs):
        rec = gd / "execution-receipt.json"
        if rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0 and data.get("fluid_particles", 0) > 0:
                    gencase_receipt = rec
                    gencase_dir = gd
                    break
            except Exception:
                pass

    if not solver_receipt or not solver_dir:
        raise FileNotFoundError(f"missing completed solver receipt for {case_id}")
    if not gencase_receipt or not gencase_dir:
        raise FileNotFoundError(f"missing completed gencase receipt for {case_id}")

    generated_xml = gencase_dir / f"{case_id}.xml"
    gencase_bi4 = gencase_dir / f"{case_id}.bi4"
    solver_log = solver_dir / "Run.out"
    data_root = solver_dir / "data"

    part_0000 = data_root / "Part_0000.bi4"
    part_0800 = data_root / "Part_0800.bi4"

    for p in (data_root, generated_xml, gencase_bi4, solver_log, solver_receipt, gencase_receipt, part_0000, part_0800, DECODER, PARTVTK, CONVERT_PY):
        if not p.exists():
            raise FileNotFoundError(f"missing conversion prerequisite: {p}")

    storage_est = 15 * 1024**3
    wall_sec = 1800

    command = [
        str(sys.executable),
        str(CONVERT_PY),
        "--data-root", str(data_root),
        "--generated-xml", str(generated_xml),
        "--solver-log", str(solver_log),
        "--output", "{attempt_root}/trajectory.h5",
        "--report", "{attempt_root}/conversion-report.json",
        "--solver-receipt", str(solver_receipt),
        "--gencase-receipt", str(gencase_receipt),
        "--owner-metadata", str(owner_path),
        "--decoder", str(DECODER),
        "--partvtk", str(PARTVTK),
        "--validation-dir", "{attempt_root}/partvtk-validation",
        "--keep-validation-csv",
    ]

    input_files = [
        str(CONVERT_PY),
        str(owner_path),
        str(gencase_receipt),
        str(solver_receipt),
        str(generated_xml),
        str(solver_log),
        str(DECODER),
        str(PARTVTK),
        str(gencase_bi4),
        str(part_0000),
        str(part_0800),
    ]

    req = {
        "schema": "ds02.request.v1",
        "family_id": "F5",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 4,
        "max_wall_seconds": wall_sec,
        "estimated_storage_bytes": storage_est,
        "command": command,
        "cwd": str(solver_dir),
        "input_files": input_files,
        "worktree_root": str(REPO.parent),
        "purpose": "production direct BI4 conversion with official PartVTK cross-validation",
    }

    requests_dir = family_dir / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)
    req_path = requests_dir / f"{case_id}-conversion.json"
    req_path.write_text(json.dumps(req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Emitted conversion request: {req_path}")
    return req_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=STAGE8_CASES, help="Case IDs to process")
    parser.add_argument("--emit-requests", action="store_true", help="Emit conversion requests")
    args = parser.parse_args()

    for cid in args.cases:
        if args.emit_requests:
            try:
                emit_f5_stage8_conversion_request(cid)
            except Exception as e:
                print(f"Skipping {cid}: {e}")


if __name__ == "__main__":
    main()
