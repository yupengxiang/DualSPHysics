"""F5 Spatial Replication of Surface-First Boundary Discretization at Coarse and Medium Resolutions.

Adheres strictly to Root Continuation 016:
- Starts from ORIGINAL matched continuous cellcenter mother defs (commensurate DP005 and phase-exact DP025).
- SAME physical fluid bounds: [-0.9, 3.3] x [-0.7, 0.7] x [0.02, 0.42], volume 2.352 m^3, mass 2352.0 kg.
- Inherits exact gridphase from each original mother def.
- Applies exact same 4 surface-first commands from ROOT root_surface_first_boundary_preservation_024/{runup,weir}.
- Does not clone fine and naively change DP.
- Generates strict GenCase CPU requests (launch_allowed=False).
- Prepares prospective root solid coverage v5, generalized native 3D fluid mass QA v2,
  and generalized actual native lineage v3 audit requests (launch_allowed=False).
- No GPU until all actual QA passes. Zero fabricated receipts or counts.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
import xml.etree.ElementTree as ET

# Worktree root paths
ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
ROOTLAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON_BIN = ROOTLAB / ".venv/bin/python"

OFFICIAL_BIN = ROOTLAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
GENCASE = OFFICIAL_BIN / "GenCase_linux64"
PARTVTK = OFFICIAL_BIN / "PartVTK_linux64"
SOLVER = OFFICIAL_BIN / "DualSPHysics5.4_linux64"

# Source fine reference from ROOT 024
FINE_REF_XML = ROOTLAB / "campaigns/ds-data-02/families/F5/handoff_20261003/root_surface_first_boundary_preservation_024/runup/F5_REF_RUNUP_DP010_SURFACE_FIRST_SUPPORT_024.xml"
RUNNER_V2 = ROOTLAB / "scripts/ds_data02_runtime_v2.py"
DISPATCH_V1 = ROOTLAB / "scripts/ds_data02_strict_dispatch_v1.py"
COVERAGE_V5_SCRIPT = ROOTLAB / "scripts/ds_data02_f5_root_solid_coverage_v5.py"
LINEAGE_V3_SCRIPT = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_f5_surface_lineage_v3.py"
MASS_QA_V2_SCRIPT = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_f5_initial_mass_qa_v2.py"

# Target handoff scope
SCOPE_NAME = "f5_surface_first_coarse_medium_028"
TARGET_SCOPE = ROOT / f"lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/{SCOPE_NAME}"
MANIFEST_PATH = TARGET_SCOPE / "manifest.json"
BINDINGS_PATH = TARGET_SCOPE / "bindings.json"

SCHEMA_REQUEST = "ds02.runner-request.v2"
SCHEMA_MANIFEST = "ds02.f5.surface-first-spatial-replication-manifest.v1"
SCHEMA_BINDINGS = "ds02.f5.surface-first-spatial-replication-bindings.v1"

# Theoretical fluid continuum parameters
FLUID_LOW = [-0.9, -0.7, 0.02]
FLUID_HIGH = [3.3, 0.7, 0.42]
FLUID_SIZE = [4.2, 1.4, 0.40]
FLUID_VOLUME_M3 = 2.352
FLUID_MASS_KG = 2352.0

CASE_SPECS: dict[str, dict[str, Any]] = {
    "runup_dp050": {
        "case_id": "F5_REF_RUNUP_DP050_SURFACE_FIRST_SUPPORT_028",
        "dp_m": 0.05,
        "dp_str": "050",
        "resolution": "coarse",
        "mechanism": "runup",
        "expected_fluid_particles": 18816,
        "expected_fluid_mass_kg": 2352.0,
        "mother_dir": ROOTLAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_010/runup_dp005",
        "mother_xml": ROOTLAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_010/runup_dp005/F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010.xml",
        "piston_file": "piston_f91973457a049db5_regular_piston.dat",
        "mother_receipt": DATA_ROOT / "families/F5/F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-runup_return-dp005-cellcentre-commensurate-010/execution-receipt.json",
        "mother_prefix": DATA_ROOT / "families/F5/F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-runup_return-dp005-cellcentre-commensurate-010/F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010",
        "mother_moving_particles": 3128,
        "mother_total_particles": 94790,
        "gencase_storage_bytes": 1073741824,
    },
    "weir_dp050": {
        "case_id": "F5_REF_WEIR_DP050_SURFACE_FIRST_SUPPORT_028",
        "dp_m": 0.05,
        "dp_str": "050",
        "resolution": "coarse",
        "mechanism": "weir",
        "expected_fluid_particles": 18816,
        "expected_fluid_mass_kg": 2352.0,
        "mother_dir": ROOTLAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_010/weir_dp005",
        "mother_xml": ROOTLAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_010/weir_dp005/F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010.xml",
        "piston_file": "piston_4c73cd98b7230035_regular_piston.dat",
        "mother_receipt": DATA_ROOT / "families/F5/F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-weir_pair-dp005-cellcentre-commensurate-010/execution-receipt.json",
        "mother_prefix": DATA_ROOT / "families/F5/F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010/gencase-f5-weir_pair-dp005-cellcentre-commensurate-010/F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010",
        "mother_moving_particles": 3128,
        "mother_total_particles": 96558,
        "gencase_storage_bytes": 1073741824,
    },
    "runup_dp025": {
        "case_id": "F5_REF_RUNUP_DP025_SURFACE_FIRST_SUPPORT_028",
        "dp_m": 0.025,
        "dp_str": "025",
        "resolution": "medium",
        "mechanism": "runup",
        "expected_fluid_particles": 150528,
        "expected_fluid_mass_kg": 2352.0,
        "mother_dir": ROOTLAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007/runup_return",
        "mother_xml": ROOTLAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007/runup_return/F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007.xml",
        "piston_file": "piston_f91973457a049db5_regular_piston.dat",
        "mother_receipt": DATA_ROOT / "families/F5/F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/gencase-f5-runup_return-cellcentre-phase-exact-dp025-007/execution-receipt.json",
        "mother_prefix": DATA_ROOT / "families/F5/F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/gencase-f5-runup_return-cellcentre-phase-exact-dp025-007/F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "mother_moving_particles": 15947,
        "mother_total_particles": 627286,
        "gencase_storage_bytes": 4294967296,
    },
    "weir_dp025": {
        "case_id": "F5_REF_WEIR_DP025_SURFACE_FIRST_SUPPORT_028",
        "dp_m": 0.025,
        "dp_str": "025",
        "resolution": "medium",
        "mechanism": "weir",
        "expected_fluid_particles": 150528,
        "expected_fluid_mass_kg": 2352.0,
        "mother_dir": ROOTLAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007/weir_pair",
        "mother_xml": ROOTLAB / "campaigns/ds-data-02/families/F5/initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007/weir_pair/F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007.xml",
        "piston_file": "piston_4c73cd98b7230035_regular_piston.dat",
        "mother_receipt": DATA_ROOT / "families/F5/F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/gencase-f5-weir_pair-cellcentre-phase-exact-dp025-007/execution-receipt.json",
        "mother_prefix": DATA_ROOT / "families/F5/F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007/gencase-f5-weir_pair-cellcentre-phase-exact-dp025-007/F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_PHASE_EXACT_007",
        "mother_moving_particles": 15947,
        "mother_total_particles": 633705,
        "gencase_storage_bytes": 4294967296,
    },
}


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def projection(node: ET.Element) -> list[Any]:
    return [
        node.tag,
        sorted(node.attrib.items()),
        (node.text or "").strip(),
        [projection(child) for child in node],
    ]


def _extract_support_nodes_from_fine_ref() -> list[ET.Element]:
    tree = ET.parse(FINE_REF_XML)
    main = tree.find(".//geometry/commands/mainlist")
    if main is None:
        raise ValueError(f"mainlist missing in fine ref: {FINE_REF_XML}")
    nodes = [n for n in main if n.get("cmt", "").startswith("root_numeric_bed_surface_support")]
    if len(nodes) != 4:
        raise ValueError(f"expected 4 support nodes, found {len(nodes)} in {FINE_REF_XML}")
    return [copy.deepcopy(n) for n in nodes]


def prepare() -> dict[str, Any]:
    TARGET_SCOPE.mkdir(parents=True, exist_ok=True)
    support_nodes = _extract_support_nodes_from_fine_ref()

    cases_manifest: dict[str, Any] = {}
    bindings: dict[str, Any] = {
        "schema": SCHEMA_BINDINGS,
        "cases": {},
    }

    for case_key, spec in CASE_SPECS.items():
        case_id = spec["case_id"]
        dp_m = spec["dp_m"]
        dp_str = spec["dp_str"]
        mechanism = spec["mechanism"]
        mother_dir = spec["mother_dir"]
        mother_xml = spec["mother_xml"]
        piston_file = spec["piston_file"]
        mother_receipt = spec["mother_receipt"]
        mother_prefix = spec["mother_prefix"]
        expected_fluid = spec["expected_fluid_particles"]
        expected_mass = spec["expected_fluid_mass_kg"]

        case_dir = TARGET_SCOPE / case_key
        assets_dir = case_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy Bed STL
        src_bed_stl = mother_dir / "assets/f5_continuous_bed_profile_slope_0p280.stl"
        dst_bed_stl = assets_dir / "f5_continuous_bed_profile_slope_0p280.stl"
        dst_bed_stl.write_bytes(src_bed_stl.read_bytes())

        # 2. Copy Piston DAT
        src_piston = mother_dir / piston_file
        dst_piston = case_dir / piston_file
        dst_piston.write_bytes(src_piston.read_bytes())

        # 3. Create modified XML by inserting the 4 surface-first commands
        mother_tree = ET.parse(mother_xml)
        new_tree = ET.parse(mother_xml)
        main = new_tree.find(".//geometry/commands/mainlist")
        if main is None:
            raise ValueError(f"mainlist missing in {mother_xml}")

        # Find insert index: immediately after <setdrawmode mode="solid" />
        insert_idx = -1
        for i, child in enumerate(main):
            if child.tag == "setdrawmode" and child.get("mode") == "solid":
                insert_idx = i
                break
        if insert_idx == -1:
            raise ValueError(f"could not find setdrawmode solid in {mother_xml}")

        for offset, node in enumerate(support_nodes):
            main.insert(insert_idx + 1 + offset, copy.deepcopy(node))

        new_xml_path = case_dir / f"{case_id}.xml"
        new_tree.write(new_xml_path, encoding="utf-8", xml_declaration=True)

        # 4. Verify XML Projection Equivalence (after removing the 4 support nodes)
        verify_tree = ET.parse(new_xml_path)
        verify_main = verify_tree.find(".//geometry/commands/mainlist")
        to_remove = [n for n in verify_main if n.get("cmt", "").startswith("root_numeric_bed_surface_support")]
        for r in to_remove:
            verify_main.remove(r)
        orig_proj = projection(mother_tree.getroot())
        mod_proj = projection(verify_tree.getroot())
        if orig_proj != mod_proj:
            raise ValueError(f"projection equivalence failed for {case_id}")

        # 5. GenCase CPU Runner Request (Strict Shared Runner)
        gencase_attempt_id = f"root-{mechanism}-dp{dp_str}-surface-first-gencase-028"
        gencase_req_path = case_dir / "gencase-request.json"
        gencase_input_files = [
            str(mother_xml.resolve()),
            str(new_xml_path.resolve()),
            str(dst_bed_stl.resolve()),
            str(dst_piston.resolve()),
            str(GENCASE.resolve()),
            str(RUNNER_V2.resolve()),
            str(DISPATCH_V1.resolve()),
        ]
        gencase_input_hashes = {p: sha256_file(p) for p in gencase_input_files if Path(p).is_file()}
        gencase_request = {
            "schema": SCHEMA_REQUEST,
            "family_id": "F5",
            "case_id": case_id,
            "attempt_id": gencase_attempt_id,
            "kind": "cpu",
            "cpu_task_kind": "gencase",
            "cpu_threads": 4,
            "max_wall_seconds": 1800,
            "estimated_storage_bytes": spec["gencase_storage_bytes"],
            "cwd": str(case_dir.resolve()),
            "worktree_root": str(ROOT.resolve()),
            "command": [
                str(GENCASE.resolve()),
                str((case_dir / case_id).resolve()),
                f"{{attempt_root}}/{case_id}",
                "-save:all",
                "-threads:4",
            ],
            "input_files": gencase_input_files,
            "input_sha256": gencase_input_hashes,
            "launch_allowed": False,
            "root_review_required": True,
            "q_n_granted": False,
            "production_granted": False,
            "root_repair_review": {
                "replication_iteration": "028_coarse_medium_spatial_replication",
                "cause": "Spatial replication of accepted surface-first 60-triangle boundary discretization at DP 0.05 and DP 0.025",
                "method": "Draw complete original mesh surface first, then execute original unchanged physical geometry and fluid. Preserves exact original cellcenter gridphase.",
                "physical_geometry_and_control_unchanged": True,
                "original_tolerance_unchanged": True,
                "must_verify": f"Exact native {expected_fluid} fluid particles (M={expected_mass} kg); exact {spec['mother_moving_particles']} piston coordinates; full coverage v5; no GPU before actual QA",
            },
            "purpose": (
                f"Strict GenCase CPU request for {case_id} (DP={dp_m} m): "
                f"inherits exact cellcenter gridphase from mother def; surface-first 60-triangle bed support; "
                f"expected fluid {expected_fluid} particles; root review & dispatch only; launch_allowed=false."
            ),
        }
        gencase_req_path.write_text(json.dumps(gencase_request, indent=2) + "\n", encoding="utf-8")

        # 6. Prospective Solid Coverage v5 Input & Request
        expected_gencase_out = DATA_ROOT / f"families/F5/{case_id}/{gencase_attempt_id}"
        expected_gencase_prefix = expected_gencase_out / case_id
        expected_gencase_receipt = expected_gencase_out / "execution-receipt.json"

        coverage_input_path = case_dir / "coverage-input.json"
        coverage_input = {
            "case_id": case_id,
            "input_prefix": str(expected_gencase_prefix),
            "geometry_asset_root": str(case_dir.resolve()),
        }
        coverage_input_path.write_text(json.dumps(coverage_input, indent=2) + "\n", encoding="utf-8")

        coverage_attempt_id = f"root-{mechanism}-dp{dp_str}-surface-first-coverage-028"
        coverage_req_path = case_dir / "coverage-request.json"
        coverage_input_files = [
            str(PYTHON_BIN),
            str(COVERAGE_V5_SCRIPT.resolve()),
            str(coverage_input_path.resolve()),
            str(new_xml_path.resolve()),
            str(dst_bed_stl.resolve()),
            str(dst_piston.resolve()),
            str(RUNNER_V2.resolve()),
            str(DISPATCH_V1.resolve()),
        ]
        coverage_request = {
            "schema": SCHEMA_REQUEST,
            "family_id": "F5",
            "case_id": case_id,
            "attempt_id": coverage_attempt_id,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 4,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": 268435456,
            "cwd": str(ROOTLAB.resolve()),
            "worktree_root": str(ROOT.resolve()),
            "command": [
                str(PYTHON_BIN),
                str(COVERAGE_V5_SCRIPT.resolve()),
                "--request",
                str(coverage_input_path.resolve()),
                "--output",
                "{attempt_root}/solid-coverage.json",
            ],
            "input_files": coverage_input_files,
            "input_sha256": {p: sha256_file(p) for p in coverage_input_files if Path(p).is_file()},
            "launch_allowed": False,
            "root_review_required": True,
            "q_n_granted": False,
            "production_granted": False,
            "purpose": f"Prospective root solid coverage v5 request for {case_id} after actual GenCase exists.",
        }
        coverage_req_path.write_text(json.dumps(coverage_request, indent=2) + "\n", encoding="utf-8")

        # 7. Prospective Generalized Lineage v3 Manifest & Request
        lineage_manifest_path = case_dir / "lineage-manifest.json"
        lineage_manifest = {
            "case_id": case_id,
            "dp_m": dp_m,
            "expected_fluid_particles": expected_fluid,
            "expected_fluid_mass_kg": expected_mass,
            "old_prefix": str(mother_prefix),
            "new_prefix": str(expected_gencase_prefix),
            "old_receipt": str(mother_receipt),
            "new_receipt": str(expected_gencase_receipt),
            "old_definition": str(mother_xml.resolve()),
            "new_definition": str(new_xml_path.resolve()),
            "old_bed": str(src_bed_stl.resolve()),
            "new_bed": str(dst_bed_stl.resolve()),
            "old_motion": str(src_piston.resolve()),
            "new_motion": str(dst_piston.resolve()),
        }
        lineage_manifest_path.write_text(json.dumps(lineage_manifest, indent=2) + "\n", encoding="utf-8")

        lineage_attempt_id = f"root-{mechanism}-dp{dp_str}-surface-first-lineage-028"
        lineage_req_path = case_dir / "lineage-request.json"
        lineage_input_files = [
            str(PYTHON_BIN),
            str(LINEAGE_V3_SCRIPT.resolve()),
            str(lineage_manifest_path.resolve()),
            str(mother_xml.resolve()),
            str(new_xml_path.resolve()),
            str(src_bed_stl.resolve()),
            str(dst_bed_stl.resolve()),
            str(src_piston.resolve()),
            str(dst_piston.resolve()),
            str(mother_receipt.resolve()),
            str(RUNNER_V2.resolve()),
            str(DISPATCH_V1.resolve()),
        ]
        lineage_request = {
            "schema": SCHEMA_REQUEST,
            "family_id": "F5",
            "case_id": case_id,
            "attempt_id": lineage_attempt_id,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 4,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": 268435456,
            "cwd": str(ROOTLAB.resolve()),
            "worktree_root": str(ROOT.resolve()),
            "command": [
                str(PYTHON_BIN),
                str(LINEAGE_V3_SCRIPT.resolve()),
                "--manifest",
                str(lineage_manifest_path.resolve()),
                "--output",
                "{attempt_root}/surface-lineage.json",
            ],
            "input_files": lineage_input_files,
            "input_sha256": {p: sha256_file(p) for p in lineage_input_files if Path(p).is_file()},
            "launch_allowed": False,
            "root_review_required": True,
            "q_n_granted": False,
            "production_granted": False,
            "purpose": f"Prospective generalized lineage v3 audit request for {case_id} after actual GenCase exists.",
        }
        lineage_req_path.write_text(json.dumps(lineage_request, indent=2) + "\n", encoding="utf-8")

        # 8. Prospective Generalized Native 3D Fluid Mass QA Manifest & Request
        initial_manifest_path = case_dir / "initial-manifest.json"
        initial_manifest = {
            "case_id": case_id,
            "dp_m": dp_m,
            "expected_fluid_particles": expected_fluid,
            "expected_fluid_mass_kg": expected_mass,
            "generated_prefix": str(expected_gencase_prefix),
            "gencase_receipt": str(expected_gencase_receipt),
            "gencase_receipt_sha256": "pending_actual_gencase_execution",
        }
        initial_manifest_path.write_text(json.dumps(initial_manifest, indent=2) + "\n", encoding="utf-8")

        initial_attempt_id = f"root-{mechanism}-dp{dp_str}-surface-first-initial-028"
        initial_req_path = case_dir / "initial-request.json"
        initial_input_files = [
            str(PYTHON_BIN),
            str(MASS_QA_V2_SCRIPT.resolve()),
            str(PARTVTK.resolve()),
            str(initial_manifest_path.resolve()),
            str(new_xml_path.resolve()),
            str(dst_bed_stl.resolve()),
            str(dst_piston.resolve()),
            str(RUNNER_V2.resolve()),
            str(DISPATCH_V1.resolve()),
        ]
        initial_request = {
            "schema": SCHEMA_REQUEST,
            "family_id": "F5",
            "case_id": case_id,
            "attempt_id": initial_attempt_id,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 4,
            "max_wall_seconds": 3600,
            "estimated_storage_bytes": spec["gencase_storage_bytes"],
            "cwd": str(ROOTLAB.resolve()),
            "worktree_root": str(ROOT.resolve()),
            "command": [
                str(PYTHON_BIN),
                str(MASS_QA_V2_SCRIPT.resolve()),
                "--manifest",
                str(initial_manifest_path.resolve()),
                "--output-dir",
                "{attempt_root}",
            ],
            "input_files": initial_input_files,
            "input_sha256": {p: sha256_file(p) for p in initial_input_files if Path(p).is_file()},
            "launch_allowed": False,
            "root_review_required": True,
            "q_n_granted": False,
            "production_granted": False,
            "purpose": f"Prospective native 3D fluid mass QA request for {case_id} after actual GenCase exists.",
        }
        initial_req_path.write_text(json.dumps(initial_request, indent=2) + "\n", encoding="utf-8")

        # Record bindings
        bindings["cases"][case_key] = {
            "case_id": case_id,
            "dp_m": dp_m,
            "mechanism": mechanism,
            "expected_fluid_particles": expected_fluid,
            "expected_fluid_mass_kg": expected_mass,
            "definition_xml": str(new_xml_path.resolve()),
            "definition_xml_sha256": sha256_file(new_xml_path),
            "bed_stl": str(dst_bed_stl.resolve()),
            "bed_stl_sha256": sha256_file(dst_bed_stl),
            "piston_dat": str(dst_piston.resolve()),
            "piston_dat_sha256": sha256_file(dst_piston),
            "mother_source": {
                "xml": str(mother_xml.resolve()),
                "xml_sha256": sha256_file(mother_xml),
                "receipt": str(mother_receipt.resolve()),
                "receipt_sha256": sha256_file(mother_receipt),
            },
            "requests": {
                "gencase": str(gencase_req_path.resolve()),
                "coverage": str(coverage_req_path.resolve()),
                "lineage": str(lineage_req_path.resolve()),
                "initial_mass_qa": str(initial_req_path.resolve()),
            },
            "projection_invariant_proven": True,
        }

        cases_manifest[case_key] = {
            "case_id": case_id,
            "dp_m": dp_m,
            "resolution": spec["resolution"],
            "mechanism": mechanism,
            "expected_fluid_particles": expected_fluid,
            "expected_fluid_mass_kg": expected_mass,
            "directory": str(case_dir.resolve()),
            "definition_xml": str(new_xml_path.resolve()),
            "gencase_request": str(gencase_req_path.resolve()),
            "coverage_request": str(coverage_req_path.resolve()),
            "lineage_request": str(lineage_req_path.resolve()),
            "initial_mass_qa_request": str(initial_req_path.resolve()),
        }

    BINDINGS_PATH.write_text(json.dumps(bindings, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema": SCHEMA_MANIFEST,
        "scope_name": SCOPE_NAME,
        "family_id": "F5",
        "description": (
            "Spatial replication of already accepted full surface-first boundary discretization "
            "at coarser matched resolutions (DP 0.05 coarse and DP 0.025 medium). "
            "Inherits exact cellcenter gridphase from original mother defs. "
            "Strict GenCase CPU requests and prospective QA requests generated; launch_allowed=false."
        ),
        "physical_continuum_fluid": {
            "bounds_xyz_m": [FLUID_LOW, FLUID_HIGH],
            "size_xyz_m": FLUID_SIZE,
            "volume_m3": FLUID_VOLUME_M3,
            "fluid_density_kg_m3": 1000.0,
            "continuous_fluid_mass_kg": FLUID_MASS_KG,
        },
        "bindings_path": str(BINDINGS_PATH.resolve()),
        "bindings_sha256": sha256_file(BINDINGS_PATH),
        "cases": cases_manifest,
        "execution_rules": {
            "launch_allowed": False,
            "root_review_required": True,
            "no_gpu_until_actual_qa_passes": True,
            "macro_operator_tolerance": "frozen 5% relative RMSE",
            "gauge_window": "gauge only to 15.98s, no extrapolation to 16.0s",
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "status": "prepared",
        "manifest": str(MANIFEST_PATH.resolve()),
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "bindings": str(BINDINGS_PATH.resolve()),
        "cases": list(cases_manifest.keys()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("prepare")
    args = parser.parse_args(argv)

    if args.action == "prepare":
        res = prepare()
        print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
