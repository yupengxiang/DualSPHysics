#!/usr/bin/env python3
"""Generate owner metadata and direct conversion requests for F7 Stage 8 production cases."""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_f7 import FAMILY_DIR, sha256_file
FAMILY_ID = "F7"
from ds_data02_direct_convert import _validate_physical_binding

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
BIN_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = BIN_ROOT / "PartVTK_linux64"
CONVERT_PY = REPO / "scripts/ds_data02_direct_convert.py"

STAGE8_CASES = [
    "F7_PUMP_P00_FINE",
    "F7_PUMP_P01_FINE",
    "F7_PUMP_P02_FINE",
    "F7_PUMP_P03_FINE",
    "F7_OBSTACLE_P00_FINE",
    "F7_OBSTACLE_P01_FINE",
    "F7_OBSTACLE_P02_FINE",
    "F7_OBSTACLE_P03_FINE",
]


def make_f7_stage8_owner(case_id: str, family_dir: Path = FAMILY_DIR) -> Path:
    family_dir = Path(family_dir).resolve()
    manifest_path = family_dir / f"production/case_manifests/{case_id}.json"
    manifest = json.loads(manifest_path.read_text())
    
    physical_case_id = manifest["physical_parent_id"]
    mech = manifest["mechanism"]
    recipe = manifest["recipe"]
    params = manifest["physical_parameters"]

    case_data_dir = DATA_ROOT / "families/F7" / case_id
    solver_receipt_path = case_data_dir / f"{case_id}_QUALIFICATION_001/execution-receipt.json"
    gencase_receipt_path = case_data_dir / f"{case_id}_GENCASE_01/execution-receipt.json"

    if not solver_receipt_path.is_file():
        raise FileNotFoundError(f"missing solver receipt for {case_id}: {solver_receipt_path}")
    if not gencase_receipt_path.is_file():
        raise FileNotFoundError(f"missing gencase receipt for {case_id}: {gencase_receipt_path}")

    if mech == "moving_obstacle_exchange":
        geom_audit = recipe["continuous_geometry_audit"]
        motion = recipe["motion"]
        offset = float(params["offset_m"])
        mass = float(geom_audit["continuous_initial_fluid_mass_kg"])
        amp = float(motion.get("amplitude_deg", 45.0))
        freq = float(motion["frequency_hz"])

        physical_binding = {
            "schema": "ds-data-02.physical-binding.v1",
            "family_id": "F7",
            "physical_case_id": physical_case_id,
            "mechanism_id": "moving_obstacle_exchange",
            "geometry_family_id": "obstacle_exchange_tank_blade_v1",
            "control_family_id": f"obstacle_sinusoidal_rotation_{int(amp)}deg_{freq}hz",
            "geometry": {
                "tank": {
                    "low_m": [-0.6, -0.4, 0.0],
                    "size_m": [1.2, 0.8, 0.6],
                    "label": "Closed rectangular tank container"
                },
                "blade": {
                    "low_m": [round(-0.07 + offset + 0.04, 4), -0.24, 0.05],
                    "size_m": [0.06, 0.48, 0.48],
                    "label": "Rotating obstacle blade"
                },
                "fluid_left": {
                    "low_m": [-0.55, -0.35, 0.05],
                    "size_m": [0.51, 0.70, 0.432],
                    "mkfluid": 1,
                    "label": "Left fluid chamber"
                },
                "fluid_right": {
                    "low_m": [-0.01, -0.35, 0.05],
                    "size_m": [0.55, 0.70, 0.432],
                    "mkfluid": 1,
                    "label": "Right fluid chamber"
                }
            },
            "initial_state": {
                "source_regions": [
                    "initial left chamber fluid",
                    "initial right chamber fluid"
                ],
                "velocities_m_per_s": [[0.0, 0.0, 0.0]],
                "mass_policy": f"Actual native initial mass retained; continuous fluid mass {mass:.4f} kg"
            },
            "controls": {},
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "density_kg_m3": 1000.0,
            "parameters": {
                "motion_csv": f"{case_id}_motion.csv",
                "amplitude_deg": amp,
                "frequency_hz": freq,
                "axis_p1_m": motion["axis_p1_m"],
                "axis_p2_m": motion["axis_p2_m"]
            },
            "event_window": {
                "time_start_s": 0.0,
                "time_end_s": 12.0
            }
        }
        owner = {
            "schema": "ds02.f7.full-native-owner.v1",
            "family_id": "F7",
            "case_id": case_id,
            "physical_case_id": physical_case_id,
            "resolution": "fine",
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
    elif mech == "pump_recirculation":
        motion = recipe["motion"]
        vel = float(motion["forward_velocity_deg_s"])
        acc = float(motion["forward_acceleration_deg_s2"])

        ref_owner = json.loads((family_dir / "native_product_001/F7_PUMP_REFERENCE_BASE_FINE.owner.json").read_text())
        physical_binding = dict(ref_owner["physical_binding"])
        physical_binding["physical_case_id"] = physical_case_id
        physical_binding["control_family_id"] = f"pump_reciprocal_{int(vel)}degps_{int(acc)}degps2_5s"
        physical_binding["parameters"] = dict(physical_binding["parameters"])
        physical_binding["parameters"]["motion_csv"] = f"{case_id}_motion.csv"

        owner = {
            "schema": "ds02.f7.full-native-owner.v1",
            "family_id": "F7",
            "case_id": case_id,
            "physical_case_id": physical_case_id,
            "resolution": "fine",
            "physical_binding": physical_binding,
            "geometry_assets": ref_owner.get("geometry_assets", []),
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
    else:
        raise ValueError(f"unknown mechanism: {mech}")

    # Validate physical binding contract
    _validate_physical_binding(owner["physical_binding"])

    owner_dir = family_dir / "production/owner_metadata"
    owner_dir.mkdir(parents=True, exist_ok=True)
    owner_path = owner_dir / f"{case_id}.owner.json"
    owner_path.write_text(json.dumps(owner, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return owner_path


def emit_f7_stage8_conversion_request(case_id: str, family_dir: Path = FAMILY_DIR, attempt_id: str = "full-typed-native-conversion-001") -> Path:
    family_dir = Path(family_dir).resolve()
    owner_path = make_f7_stage8_owner(case_id, family_dir)

    case_data_dir = DATA_ROOT / "families/F7" / case_id
    solver_dir = case_data_dir / f"{case_id}_QUALIFICATION_001/solver"
    gencase_dir = case_data_dir / f"{case_id}_GENCASE_01"

    data_root = solver_dir / "data"
    generated_xml = gencase_dir / f"{case_id}.xml"
    gencase_bi4 = gencase_dir / f"{case_id}.bi4"
    solver_log = solver_dir / "Run.out"
    solver_receipt = case_data_dir / f"{case_id}_QUALIFICATION_001/execution-receipt.json"
    gencase_receipt = gencase_dir / "execution-receipt.json"
    part_0000 = data_root / "Part_0000.bi4"
    part_0600 = data_root / "Part_0600.bi4"

    for p in (data_root, generated_xml, gencase_bi4, solver_log, solver_receipt, gencase_receipt, part_0000, part_0600, DECODER, PARTVTK, CONVERT_PY):
        if not p.exists():
            raise FileNotFoundError(f"missing conversion prerequisite: {p}")

    is_pump = "PUMP" in case_id
    storage_est = 2 * 1024**3 if is_pump else 4 * 1024**3

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
        str(part_0600),
    ]

    req = {
        "schema": "ds02.request.v1",
        "family_id": "F7",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": storage_est,
        "worktree_root": str(REPO.parent),
        "cwd": str(REPO),
        "command": command,
        "input_files": input_files,
    }

    requests_dir = family_dir / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)
    req_path = requests_dir / f"{case_id}-conversion.json"
    req_path.write_text(json.dumps(req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return req_path


def main():
    requests = []
    for cid in STAGE8_CASES:
        req_path = emit_f7_stage8_conversion_request(cid)
        print(f"Emitted: {req_path}")
        requests.append(req_path)
    print(f"Successfully prepared all {len(requests)} F7 Stage 8 conversion requests.")


if __name__ == "__main__":
    main()
