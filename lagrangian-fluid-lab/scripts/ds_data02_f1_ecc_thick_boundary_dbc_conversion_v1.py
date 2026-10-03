#!/usr/bin/env python3
"""F1 ECC thick-boundary DBC direct converter bindings and request templates.

Builds immutable, resolution-specific owner metadata with valid physical_binding.v1
contracts and runner request templates for the three completed F1 resolutions:
  - Coarse (DP=0.010, 1601 frames, 181,836 particles, NpOut=0, fluid mass 80.4 kg)
  - Medium (DP=0.005, 1601 frames, 1,032,852 particles, NpOut=0, fluid mass 80.4 kg)
  - Fine   (DP=0.003333, 1601 frames, 3,035,772 particles, NpOut=179, fluid mass 80.4 kg)

All three cases bind:
  1. Child GenCase prefix and XML/BI4/receipt
  2. Completed native solver execution receipt and Run.out log
  3. Destination-verified native byte publication report (native-storage-publication.json)
  4. Completed CPU publication terminal receipt
  5. Exact physical binding (F1 eccentric obstacle DBC)
  6. Explicit launch_allowed=False / root_only_launch=True (review only)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Mapping

# Paths in accordance with campaign boundaries
ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = ROOT / "lagrangian-fluid-lab"
PYTHON_BIN = LAB / ".venv/bin/python"

INFRA_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
INFRA_LAB = INFRA_WORKTREE / "lagrangian-fluid-lab"

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")

# Binaries
OFFICIAL_BIN = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux"
)
PARTVTK = OFFICIAL_BIN / "PartVTK_linux64"
DECODER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump"
)

# Scripts
DIRECT_CONVERT = INFRA_LAB / "scripts/ds_data02_direct_convert.py"
RUNTIME_V2 = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH_V1 = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
NVME_CONVERT_V1 = LAB / "scripts/ds_data02_nvme_convert_v1.py"

# Target handoff directory
HANDOFF_ROOT = (
    INFRA_LAB
    / "campaigns/ds-data-02/families/F1/handoff_20261003/f1_ecc_thick_boundary_dbc_direct_conversion_001"
)
OWNER_METADATA_DIR = HANDOFF_ROOT / "owner_metadata"
REQUESTS_DIR = HANDOFF_ROOT / "requests"
MANIFEST_PATH = HANDOFF_ROOT / "manifest.json"
INVENTORY_PATH = HANDOFF_ROOT / "inventory.json"

SCHEMA_OWNER = "ds02.f1.direct-conversion-owner-metadata.v1"
SCHEMA_REQUEST = "ds02.runner.request.v2"
SCHEMA_MANIFEST = "ds02.f1.ecc-thick-boundary-dbc-conversion-manifest.v1"

# Shared frozen physical contract
PHYSICAL_CONTRACT = {
    "schema": "ds-data-02.physical-binding.v1",
    "family_id": "F1",
    "physical_case_id": "F1_ECCENTRIC_THICK_BOUNDARY_DBC",
    "mechanism_id": "eccentric_obstacle",
    "geometry_family_id": "F1_GEOM_ECCENTRIC_OBSTACLE_THICK_DBC_V1",
    "control_family_id": "F1_CONTROL_ECCENTRIC_OBSTACLE_DBC_V1",
    "lineage_group_id": "F1_eccentric_obstacle_thick_dbc",
    "paired_background_id": "F1_REF_ECC_NOMINAL",
    "geometry": {
        "fluid_reservoir": {
            "low_m": [0.0, 0.0, 0.0],
            "size_m": [0.4, 0.67, 0.3],
            "mkfluid": 1,
            "label": "finite initial fluid reservoir",
        },
        "tank": {
            "low_m": [0.0, 0.0, 0.0],
            "size_m": [1.6, 0.67, 0.4],
            "mkfluid": 0,
            "label": "continuous five-face tank envelope",
        },
        "obstacle": {
            "low_m": [0.9, 0.24, 0.0],
            "size_m": [0.12, 0.12, 0.45],
            "mkfluid": 0,
            "label": "finite eccentric obstacle solid",
        },
    },
    "initial_state": {
        "source_regions": ["fluid_reservoir"],
        "velocities_m_per_s": {"fluid_reservoir": [0.0, 0.0, 0.0]},
        "source_labels": {"fluid_reservoir": "type=3/mk=1"},
        "initial_mass_by_source_kg": {"fluid_reservoir": 80.4},
        "continuum_mass_by_source_kg": {"fluid_reservoir": 80.4},
        "initial_mass_total_kg": 80.4,
        "mass_policy": "native GenCase mass; no normalization or rescaling",
    },
    "controls": {
        "step_algorithm": 1,
        "kernel": 1,
        "viscosity": 0.1,
        "density_dt": 2,
        "density_dt_value": 0.1,
        "boundary": 1,
    },
    "gravity_m_s2": [0.0, 0.0, -9.81],
    "density_kg_m3": 1000.0,
    "parameters": {
        "reservoir_low_m": [0.0, 0.0, 0.0],
        "reservoir_size_m": [0.4, 0.67, 0.3],
        "tank_low_m": [0.0, 0.0, 0.0],
        "tank_size_m": [1.6, 0.67, 0.4],
        "obstacle_low_m": [0.9, 0.24, 0.0],
        "obstacle_size_m": [0.12, 0.12, 0.45],
        "open_top_free_surface": True,
        "fluid_volume_m3": 0.0804,
        "fluid_mass_kg": 80.4,
        "initial_velocity_m_s": [0.0, 0.0, 0.0],
        "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
    },
    "event_window": {
        "time_start_s": 0.0,
        "time_end_s": 1.6,
        "sequence": [
            "release",
            "dam_break_front_advance",
            "obstacle_impact",
            "bypass_split",
            "downstream_wall_impact",
            "return_wave",
        ],
        "expected_first_contact_range_s": [0.35, 0.55],
        "right_censor_policy": "finite closed initial cohort; open top is a free surface, not an inlet/birth zone; unobserved return is censored",
    },
    "open_inlet": False,
    "periodic_boundary": False,
    "mass_policy": "native mass only; no rescaling",
}

SOLVER_PARAMETERS = {
    "Boundary": 1,
    "BoundaryName": "DBC",
    "SavePosDouble": 1,
    "StepAlgorithm": 1,
    "VerletSteps": 40,
    "Kernel": 1,
    "ViscoTreatment": 1,
    "Visco": 0.1,
    "ViscoBoundFactor": 1,
    "DensityDT": 2,
    "DensityDTvalue": 0.1,
    "Shifting": 0,
    "RigidAlgorithm": 1,
    "DtIni": 0.0,
    "DtMin": 0.0,
    "DtFixed": 0.0,
    "TimeMax": 1.6,
    "TimeOut": 0.001,
    "NoPenetration": 0,
    "SlipMode": 1,
    "CoefDtMin": 0.05,
    "RhopOutMin": 700,
    "RhopOutMax": 1300,
}

CASES = {
    "coarse": {
        "role": "coarse",
        "case_id": "F1_ECC_THICK_BOUNDARY_DBC_DP010",
        "dp_m": 0.010,
        "h_m": 0.01732050807568877,
        "expected_particles": 181836,
        "expected_fixed": 101436,
        "expected_fluid": 80400,
        "fluid_mass_kg": 80.4,
        "particle_mass_kg": 0.001,
        "frames": 1601,
        "np_out_actual": 0,
        "native_attempt_id": "qualification-ecc-thick-boundary-dp010-full-20261003-001-root-nvme-003",
        "cpu_publication_attempt_id": "root-coarse-nvme-home-publication-002",
        "definition_xml": INFRA_LAB
        / "campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_002/definitions/F1_ECC_THICK_BOUNDARY_DBC_DP010/F1_ECC_THICK_BOUNDARY_DBC_DP010_Def.xml",
        "child_gencase_prefix": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_DP010/f1-ecc-thick-boundary-internal-dp010-preflight-002/F1_ECC_THICK_BOUNDARY_DBC_DP010/F1_ECC_THICK_BOUNDARY_DBC_DP010",
        "child_gencase_dir": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_DP010/f1-ecc-thick-boundary-internal-dp010-preflight-002/F1_ECC_THICK_BOUNDARY_DBC_DP010",
        "child_gencase_receipt": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_DP010/f1-ecc-thick-boundary-internal-dp010-preflight-002/F1_ECC_THICK_BOUNDARY_DBC_DP010/gencase-child-receipt.json",
        "native_output_root": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_DP010/qualification-ecc-thick-boundary-dp010-full-20261003-001-root-nvme-003",
        "cpu_publication_receipt": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_DP010/root-coarse-nvme-home-publication-002/execution-receipt.json",
        "typed_ranges": {
            "fixed_mk10": {"begin": 0, "count": 96468},
            "fixed_mk11": {"begin": 96468, "count": 4968},
            "fluid_mk1": {"begin": 101436, "count": 80400},
        },
        "max_wall_seconds": 10800,
        "planning_guard_gib": 25.0,
    },
    "medium": {
        "role": "medium",
        "case_id": "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005",
        "dp_m": 0.005,
        "h_m": 0.008660254037844385,
        "expected_particles": 1032852,
        "expected_fixed": 389652,
        "expected_fluid": 643200,
        "fluid_mass_kg": 80.4,
        "particle_mass_kg": 0.000125,
        "frames": 1601,
        "np_out_actual": 0,
        "native_attempt_id": "qualification-ecc-thick-boundary-v3-1-dp005-full-20261003-001-root-nvme-004",
        "cpu_publication_attempt_id": "root-medium-nvme-home-publication-001",
        "definition_xml": INFRA_LAB
        / "campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_003_domainfix001/definitions/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005_Def.xml",
        "child_gencase_prefix": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/f1-ecc-thick-boundary-v3-1-dp005-preflight-002/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005",
        "child_gencase_dir": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/f1-ecc-thick-boundary-v3-1-dp005-preflight-002/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005",
        "child_gencase_receipt": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/f1-ecc-thick-boundary-v3-1-dp005-preflight-002/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/gencase-child-receipt.json",
        "native_output_root": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/qualification-ecc-thick-boundary-v3-1-dp005-full-20261003-001-root-nvme-004",
        "cpu_publication_receipt": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP005/root-medium-nvme-home-publication-001/execution-receipt.json",
        "typed_ranges": {
            "fixed_mk10": {"begin": 0, "count": 366000},
            "fixed_mk11": {"begin": 366000, "count": 23652},
            "fluid_mk1": {"begin": 389652, "count": 643200},
        },
        "max_wall_seconds": 10800,
        "planning_guard_gib": 100.0,
    },
    "fine": {
        "role": "fine",
        "case_id": "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333",
        "dp_m": 0.0033333333333333335,
        "h_m": 0.005773502691896257,
        "expected_particles": 3035772,
        "expected_fixed": 864972,
        "expected_fluid": 2170800,
        "fluid_mass_kg": 80.4,
        "particle_mass_kg": 0.000037037037037,
        "frames": 1601,
        "np_out_actual": 179,
        "native_attempt_id": "qualification-ecc-thick-boundary-v3-2-dp003333333333333333-full-20261003-001-root-nvme-004",
        "cpu_publication_attempt_id": "root-fine-nvme-home-publication-001",
        "definition_xml": INFRA_LAB
        / "campaigns/ds-data-02/families/F1/handoff_20261003/eccentric_thick_boundary_fallback_003_domainfix001/definitions/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333_Def.xml",
        "child_gencase_prefix": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/f1-ecc-thick-boundary-v3-2-dp003333333333333333-preflight-003/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333",
        "child_gencase_dir": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/f1-ecc-thick-boundary-v3-2-dp003333333333333333-preflight-003/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333",
        "child_gencase_receipt": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/f1-ecc-thick-boundary-v3-2-dp003333333333333333-preflight-003/F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/gencase-child-receipt.json",
        "native_output_root": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/qualification-ecc-thick-boundary-v3-2-dp003333333333333333-full-20261003-001-root-nvme-004",
        "cpu_publication_receipt": DATA_ROOT
        / "F1_ECC_THICK_BOUNDARY_DBC_V3_1_DP003333333333333333/root-fine-nvme-home-publication-001/execution-receipt.json",
        "typed_ranges": {
            "fixed_mk10": {"begin": 0, "count": 808812},
            "fixed_mk11": {"begin": 808812, "count": 56160},
            "fluid_mk1": {"begin": 864972, "count": 2170800},
        },
        "max_wall_seconds": 21600,
        "planning_guard_gib": 300.0,
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_read(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _json_write(path: Path, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")


def build_owner_metadata(role: str) -> dict[str, Any]:
    c = CASES[role]
    case_id = c["case_id"]
    native_root = c["native_output_root"]
    solver_receipt = native_root / "execution-receipt.json"
    pub_report = native_root / "native-storage-publication.json"
    solver_log = native_root / "solver_output/Run.out"
    child_gencase_xml = c["child_gencase_prefix"].with_suffix(".xml")
    child_gencase_bi4 = c["child_gencase_prefix"].with_suffix(".bi4")

    metadata = {
        "schema": SCHEMA_OWNER,
        "family_id": "F1",
        "case_id": case_id,
        "physical_case_id": "F1_ECCENTRIC_THICK_BOUNDARY_DBC",
        "mechanism": "eccentric_obstacle",
        "resolution": role,
        "claim_boundary": (
            f"F1 {role} (DP={c['dp_m']}) immutable owner binding and conversion contract. "
            "Native execution completed 1601 frames (0.0 to 1.6s); byte publication completed on Home. "
            "Conversion template only; launch_allowed=False, Q-N not assessed."
        ),
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "physical_binding": dict(PHYSICAL_CONTRACT),
        "solver_parameters": dict(SOLVER_PARAMETERS),
        "numeric_binding": {
            "dp_m": c["dp_m"],
            "h_m": c["h_m"],
            "boundary": 1,
            "boundary_name": "DBC",
            "save_pos_double": 1,
            "time_max_s": 1.6,
            "time_out_s": 0.001,
            "expected_frames": c["frames"],
            "expected_particles": c["expected_particles"],
            "expected_fluid_particles": c["expected_fluid"],
            "expected_fixed_particles": c["expected_fixed"],
            "expected_fluid_mass_kg": c["fluid_mass_kg"],
            "dt_source": "actual solver Run.out; adaptive native DtIni/DtMin, no time-step qualification inferred",
        },
        "source_provenance": {
            "definition_source": str(c["definition_xml"].resolve()),
            "definition_sha256": sha256_file(c["definition_xml"]),
            "definition_source_sha256": sha256_file(c["definition_xml"]),
            "child_gencase_prefix": str(c["child_gencase_prefix"]),
            "child_gencase_xml": str(child_gencase_xml.resolve()),
            "child_gencase_xml_sha256": sha256_file(child_gencase_xml),
            "child_gencase_bi4": str(child_gencase_bi4.resolve()),
            "child_gencase_bi4_sha256": sha256_file(child_gencase_bi4),
            "gencase_receipt": str(c["child_gencase_receipt"].resolve()),
            "gencase_receipt_sha256": sha256_file(c["child_gencase_receipt"]),
            "solver_receipt": str(solver_receipt.resolve()),
            "solver_receipt_sha256": sha256_file(solver_receipt),
            "solver_log": str(solver_log.resolve()),
            "solver_log_sha256": sha256_file(solver_log),
            "native_storage_publication": str(pub_report.resolve()),
            "native_storage_publication_sha256": sha256_file(pub_report),
            "cpu_publication_receipt": str(c["cpu_publication_receipt"].resolve()),
            "cpu_publication_receipt_sha256": sha256_file(c["cpu_publication_receipt"]),
            "home_data_root": str(native_root / "solver_output/data"),
            "source_semantics": (
                "DBC=1 actual Run.out; generated input has data2d=false, no motion, "
                "no in/out/periodic/birth/adaptive tags"
            ),
        },
        "typed_contract": {
            "identity_key": "(Zone,Idp)",
            "zone_source": "native BI4 Piece",
            "types_preserved": [0, 1, 2, 3],
            "initial_typed_ranges": c["typed_ranges"],
            "transient_exclusions": {
                "observed_count": c["np_out_actual"],
                "policy": (
                    "fine 179 excluded particles preserved on initial axis with unknown state; "
                    "no false zero out; coarse/medium observed zero exclusions"
                    if c["np_out_actual"] > 0
                    else "zero exclusions observed; complete cohort retained"
                ),
            },
            "initial_particle_axis": (
                f"all generated np={c['expected_particles']} IDs retained; "
                "missing/revival/open birth rejected by converter"
            ),
        },
        "source_immutability": True,
        "converter_scope": (
            "Use direct upstream BI4 decoder one frame at a time; official PartVTK first/middle/final; "
            "HDF5 on NVMe attempt root; raw source tree hashed before/after by converter."
        ),
    }
    return metadata


def build_converter_request(
    role: str, owner_metadata_path: Path
) -> dict[str, Any]:
    c = CASES[role]
    case_id = c["case_id"]
    attempt_id = f"ds02-f1-ecc-thick-dbc-direct-convert-{role}-001"
    native_root = c["native_output_root"]
    data_root = native_root / "solver_output/data"
    solver_receipt = native_root / "execution-receipt.json"
    solver_log = native_root / "solver_output/Run.out"
    pub_report = native_root / "native-storage-publication.json"
    child_gencase_xml = c["child_gencase_prefix"].with_suffix(".xml")
    child_gencase_bi4 = c["child_gencase_prefix"].with_suffix(".bi4")

    # Read published file stats
    pub_data = _json_read(pub_report)
    pub_files = pub_data.get("files", [])
    raw_bytes = sum(f.get("bytes", 0) for f in pub_files)

    # 40 bytes per particle-frame dataset payload
    frame_dataset_bytes = c["expected_particles"] * c["frames"] * 40
    frame_dataset_gib = frame_dataset_bytes / (1024**3)
    planning_guard_gib = c["planning_guard_gib"]
    planning_guard_bytes = int(planning_guard_gib * (1024**3))

    inputs = [
        DIRECT_CONVERT,
        RUNTIME_V2,
        STRICT_DISPATCH_V1,
        NVME_CONVERT_V1,
        DECODER,
        PARTVTK,
        c["definition_xml"],
        child_gencase_xml,
        child_gencase_bi4,
        c["child_gencase_receipt"],
        solver_receipt,
        solver_log,
        pub_report,
        c["cpu_publication_receipt"],
        owner_metadata_path,
        data_root / "Part_0000.bi4",
        data_root / "Part_0800.bi4",
        data_root / "Part_1600.bi4",
        data_root / "Part_Head.ibi4",
        native_root / "solver_output/RunPARTs.csv",
    ]

    for p in inputs:
        if not p.is_file():
            raise FileNotFoundError(f"Missing required request input: {p}")

    input_files_str = [str(p.resolve()) for p in inputs]
    input_hashes = {p_str: sha256_file(Path(p_str)) for p_str in input_files_str}

    request = {
        "schema": SCHEMA_REQUEST,
        "family_id": "F1",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 4,
        "max_wall_seconds": c["max_wall_seconds"],
        "estimated_storage_bytes": planning_guard_bytes,
        "estimated_peak_gpu_mib": 0,
        "launch_allowed": False,
        "root_only_launch": True,
        "review_status": "root_review_only",
        "command": [
            str(PYTHON_BIN.resolve()),
            str(DIRECT_CONVERT.resolve()),
            "--data-root",
            str(data_root.resolve()),
            "--generated-xml",
            str(child_gencase_xml.resolve()),
            "--solver-log",
            str(solver_log.resolve()),
            "--solver-receipt",
            str(solver_receipt.resolve()),
            "--gencase-receipt",
            str(c["child_gencase_receipt"].resolve()),
            "--owner-metadata",
            str(owner_metadata_path.resolve()),
            "--decoder",
            str(DECODER.resolve()),
            "--partvtk",
            str(PARTVTK.resolve()),
            "--output",
            "{attempt_root}/trajectory.h5",
            "--report",
            "{attempt_root}/direct-conversion-report.json",
            "--validation-dir",
            "{attempt_root}/partvtk-validation",
            "--keep-validation-csv",
            "--particle-chunk",
            "65536",
        ],
        "cwd": str(LAB.resolve()),
        "worktree_root": str(ROOT.resolve()),
        "output_root": f"/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/{case_id}/{attempt_id}",
        "input_files": input_files_str,
        "input_hashes": input_hashes,
        "request_note": (
            f"F1 {role} direct BI4 streaming conversion template. "
            "Decodes all 1601 native BI4 frames, retains complete (Zone,Idp) axis and types 0/1/2/3, "
            "validates frames 0/800/1600 with official PartVTK, and hashes raw tree before/after. "
            "launch_allowed=False; root review only."
        ),
        "source_data": {
            "data_root": str(data_root.resolve()),
            "frame_count": c["frames"],
            "raw_bytes": raw_bytes,
            "raw_tree_full_hash_deferred_to_converter": True,
            "terminal_solver_receipt": str(solver_receipt.resolve()),
            "terminal_solver_receipt_sha256": sha256_file(solver_receipt),
            "native_storage_publication": str(pub_report.resolve()),
            "native_storage_publication_sha256": sha256_file(pub_report),
            "cpu_publication_receipt": str(c["cpu_publication_receipt"].resolve()),
            "cpu_publication_receipt_sha256": sha256_file(c["cpu_publication_receipt"]),
            "actual_boundary": "DBC",
            "actual_dimension": "3D",
            "actual_time_window_s": [0.0, 1.6],
            "actual_part_files": c["frames"],
            "actual_parts_out": c["np_out_actual"],
        },
        "typed_identity_contract": {
            "identity_key": "(Zone,Idp)",
            "generated_np": c["expected_particles"],
            "fixed": c["expected_fixed"],
            "fluid_type3": c["expected_fluid"],
            "initial_mass_kg": c["fluid_mass_kg"],
            "all_types_required": [0, 1, 2, 3],
            "fine_excluded_particles": c["np_out_actual"],
            "open_birth_adaptive_multi_piece": "reject, do not infer",
        },
        "hdf5_storage_estimate": {
            "raw_uncompressed_frame_datasets_bytes": frame_dataset_bytes,
            "raw_uncompressed_frame_datasets_gib": frame_dataset_gib,
            "planning_guard_bytes": planning_guard_bytes,
            "planning_guard_gib": planning_guard_gib,
            "basis": (
                "40 bytes per particle-frame for valid/position/velocity/density/mass/pressure/type/mk, "
                "plus HDF5 metadata, chunking, three retained PartVTK CSVs, report, decoder scratch, and margin; "
                "raw BI4 source is not copied by request."
            ),
            "approved_qualification_cap_gib": 320.0,
            "home_nvme_floor_bytes": 536870912000,
            "within_approved_cap": planning_guard_gib <= 320.0,
        },
        "root_only_launch": True,
        "conversion_claim": "not_launched; template and evidence registration only; launch_allowed=false",
        "q_i_status": "not_assessed",
        "q_n_status": "not_assessed",
        "production_claim": "none",
        "prelaunch_gates": [
            "root verifies request hash and all input hashes",
            "root verifies DBC Run.out/receipt and generated XML Boundary=1/data2d=false",
            "root reserves >= planning_guard_gib NVMe output margin without overwrite",
            "converter must report source tree before/after unchanged and complete all 1601 frames",
            "PartVTK frames 0/800/1600 must pass type/mk/Zone/Idp and field tolerances",
            "open birth/adaptive/multi-piece must reject explicitly",
            "fine 179 exclusions must be preserved as unknown state without false zeroing",
            "conversion output alone does not grant Q-N or production",
        ],
    }
    return request


def build_inventory() -> dict[str, Any]:
    inventory: dict[str, Any] = {
        "schema": "ds02.f1.ecc-thick-boundary-dbc-inventory.v1",
        "family_id": "F1",
        "status": "home_publication_verified",
        "resolutions": {},
    }
    for role, c in CASES.items():
        pub_report = c["native_output_root"] / "native-storage-publication.json"
        pub = _json_read(pub_report)
        files = pub.get("files", [])
        total_bytes = sum(f.get("bytes", 0) for f in files)
        data_root = c["native_output_root"] / "solver_output/data"

        # Verify sample files exist on Home
        samples_ok = True
        sample_details = {}
        for sample_rel in [
            "data/Part_0000.bi4",
            "data/Part_0800.bi4",
            "data/Part_1600.bi4",
            "data/Part_Head.ibi4",
            "RunPARTs.csv",
        ]:
            sample_path = c["native_output_root"] / "solver_output" / sample_rel
            if not sample_path.is_file():
                samples_ok = False
            sample_details[sample_rel] = {
                "exists": sample_path.is_file(),
                "bytes": sample_path.stat().st_size if sample_path.is_file() else None,
            }

        inventory["resolutions"][role] = {
            "case_id": c["case_id"],
            "dp_m": c["dp_m"],
            "native_attempt_id": c["native_attempt_id"],
            "cpu_publication_attempt_id": c["cpu_publication_attempt_id"],
            "home_solver_output": str(c["native_output_root"] / "solver_output"),
            "home_data_root": str(data_root),
            "published_file_count": len(files),
            "published_total_bytes": total_bytes,
            "published_total_gib": total_bytes / (1024**3),
            "publication_status": pub.get("status"),
            "publication_report": str(pub_report),
            "publication_report_sha256": sha256_file(pub_report),
            "sample_verification": {
                "all_samples_present": samples_ok,
                "details": sample_details,
            },
            "frames": c["frames"],
            "np_initial": c["expected_particles"],
            "np_out_sum": c["np_out_actual"],
        }
    return inventory


def prepare() -> dict[str, Any]:
    HANDOFF_ROOT.mkdir(parents=True, exist_ok=True)
    OWNER_METADATA_DIR.mkdir(parents=True, exist_ok=True)
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)

    owner_paths: dict[str, Path] = {}
    request_paths: dict[str, Path] = {}

    for role in CASES:
        owner_path = OWNER_METADATA_DIR / f"{role}-owner-metadata.json"
        owner_data = build_owner_metadata(role)
        _json_write(owner_path, owner_data)
        owner_paths[role] = owner_path

    for role in CASES:
        req_path = REQUESTS_DIR / f"{role}-converter-request.json"
        req_data = build_converter_request(role, owner_paths[role])
        _json_write(req_path, req_data)
        request_paths[role] = req_path

    inventory_data = build_inventory()
    _json_write(INVENTORY_PATH, inventory_data)

    manifest_data = {
        "schema": SCHEMA_MANIFEST,
        "family_id": "F1",
        "recipe_id": "F1_ECC_THICK_BOUNDARY_DBC_CONVERSION_001",
        "description": (
            "F1 eccentric obstacle thick-boundary DBC direct converter owner bindings "
            "and runner request templates across all three resolutions (coarse, medium, fine). "
            "All three cases completed native GPU run (1601 frames, 1.6s, M80.4 kg) and full Home publication. "
            "launch_allowed=False, root review only; Q-N not assessed."
        ),
        "launch_allowed": False,
        "root_only_launch": True,
        "review_status": "root_review_only",
        "solver_or_gpu_started": False,
        "conversion_started": False,
        "q_n_status": "not_assessed",
        "qualification_claim": "none",
        "production_claim": "none",
        "approved_caps": {
            "qualification_storage_cap_gib": 320.0,
            "home_free_floor_gib": 500.0,
        },
        "resolutions": {
            role: {
                "case_id": CASES[role]["case_id"],
                "dp_m": CASES[role]["dp_m"],
                "native_attempt_id": CASES[role]["native_attempt_id"],
                "cpu_publication_attempt_id": CASES[role]["cpu_publication_attempt_id"],
                "owner_metadata": str(owner_paths[role].resolve()),
                "owner_metadata_sha256": sha256_file(owner_paths[role]),
                "converter_request": str(request_paths[role].resolve()),
                "converter_request_sha256": sha256_file(request_paths[role]),
                "expected_particles": CASES[role]["expected_particles"],
                "fluid_particles": CASES[role]["expected_fluid"],
                "fixed_particles": CASES[role]["expected_fixed"],
                "fluid_mass_kg": CASES[role]["fluid_mass_kg"],
                "frames": CASES[role]["frames"],
                "np_out_actual": CASES[role]["np_out_actual"],
                "planning_guard_gib": CASES[role]["planning_guard_gib"],
            }
            for role in CASES
        },
        "inventory": str(INVENTORY_PATH.resolve()),
        "inventory_sha256": sha256_file(INVENTORY_PATH),
    }
    _json_write(MANIFEST_PATH, manifest_data)

    return {
        "status": "success",
        "handoff_root": str(HANDOFF_ROOT),
        "manifest": str(MANIFEST_PATH),
        "owner_metadata": {r: str(p) for r, p in owner_paths.items()},
        "requests": {r: str(p) for r, p in request_paths.items()},
    }


def audit() -> dict[str, Any]:
    # Import converter's physical binding validator to guarantee physical contract conformity
    sys.path.insert(0, str(INFRA_LAB / "scripts"))
    import ds_data02_direct_convert as dc

    manifest = _json_read(MANIFEST_PATH)
    checks: dict[str, bool] = {}

    checks["manifest_schema_matches"] = manifest.get("schema") == SCHEMA_MANIFEST
    checks["launch_allowed_is_false"] = manifest.get("launch_allowed") is False
    checks["root_only_launch_is_true"] = manifest.get("root_only_launch") is True
    checks["solver_or_gpu_started_is_false"] = (
        manifest.get("solver_or_gpu_started") is False
    )
    checks["conversion_started_is_false"] = (
        manifest.get("conversion_started") is False
    )
    checks["q_n_status_is_not_assessed"] = (
        manifest.get("q_n_status") == "not_assessed"
    )

    for role, item in manifest["resolutions"].items():
        c = CASES[role]
        owner = _json_read(Path(item["owner_metadata"]))
        req = _json_read(Path(item["converter_request"]))

        # Check physical binding against converter's actual validator
        validated_binding = dc._validate_physical_binding(owner["physical_binding"])
        checks[f"{role}_physical_binding_valid"] = isinstance(
            validated_binding, dict
        )
        checks[f"{role}_physical_fluid_mass_80_4"] = (
            validated_binding["parameters"]["fluid_mass_kg"] == 80.4
        )
        checks[f"{role}_boundary_is_dbc"] = (
            validated_binding["controls"]["boundary"] == 1
        )

        # Check request safety flags
        checks[f"{role}_request_launch_allowed_false"] = (
            req.get("launch_allowed") is False
        )
        checks[f"{role}_request_root_only_true"] = (
            req.get("root_only_launch") is True
        )
        checks[f"{role}_request_review_only"] = (
            req.get("review_status") == "root_review_only"
        )
        checks[f"{role}_request_cpu_threads_4"] = req.get("cpu_threads") == 4
        checks[f"{role}_planning_guard_le_320gib"] = (
            req["hdf5_storage_estimate"]["planning_guard_gib"] <= 320.0
        )
        checks[f"{role}_home_floor_500gib"] = (
            req["hdf5_storage_estimate"]["home_nvme_floor_bytes"]
            == 536870912000
        )

        # Check particle and frame counts
        checks[f"{role}_frame_count_1601"] = (
            req["source_data"]["frame_count"] == 1601
        )
        checks[f"{role}_particles_match"] = (
            req["typed_identity_contract"]["generated_np"]
            == c["expected_particles"]
        )
        checks[f"{role}_np_out_preserved"] = (
            req["typed_identity_contract"]["fine_excluded_particles"]
            == c["np_out_actual"]
        )

        # Verify all input files bound in request actually exist and match hashes
        for p_str, expected_hash in req["input_hashes"].items():
            p = Path(p_str)
            checks[f"{role}_input_exists_{p.name}"] = p.is_file()
            checks[f"{role}_input_hash_matches_{p.name}"] = (
                sha256_file(p) == expected_hash
            )

    all_passed = all(checks.values())
    return {"status": "pass" if all_passed else "fail", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["prepare", "audit"],
        nargs="?",
        default="prepare",
        help="Action to perform",
    )
    args = parser.parse_args()

    if args.action == "prepare":
        result = prepare()
        print(json.dumps(result, indent=2))
        audit_res = audit()
        print(f"Audit status: {audit_res['status']}")
        return 0 if audit_res["status"] == "pass" else 1
    elif args.action == "audit":
        audit_res = audit()
        print(json.dumps(audit_res, indent=2))
        return 0 if audit_res["status"] == "pass" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
