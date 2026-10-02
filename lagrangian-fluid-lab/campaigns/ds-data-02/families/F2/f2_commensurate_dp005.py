#!/usr/bin/env python3
"""Register an additive DP=.005 numerical reference for the F2 mother cases.

The center and offset definitions remain the existing COMM4 physical mothers:
the finite cup, receiver, tray, prescribed motion, three disjoint source bands,
and continuous fluid volume are unchanged.  Only the numerical lattice phase,
``dp=.005``, repaired numerical domain, and fresh GenCase attempt identities
are introduced here.  This producer writes definitions and shared-runner CPU
requests; it never launches GenCase, DualSPHysics, or GPU work.

The parent physical case IDs stay ``F2_COMM4_CENTER_V1`` and
``F2_COMM4_OFFSET_V1``.  DP005 is a numerical view of those mothers and adds
zero independent physical cases to the campaign registry.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = FAMILY_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab")
RUNTIME_V2 = INTEGRATION_LAB / "scripts/ds_data02_runtime_v2.py"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
AUDIT_SCRIPT = FAMILY_ROOT / "f2_commensurate_audit.py"
FALLBACK_SCRIPT = FAMILY_ROOT / "f2_commensurate_fallback.py"
SCOPE_ID = "F2_SCOPE_COMMENSURATE_CELLCENTER_V4"
RECIPE_ID = "F2_COMMENSURATE_CELLCENTER_V5_DP005"
CASE_PREFIX = "F2_COMM4"
DP = 0.005
RESOLUTION = "dp005"
GRID_ORIGIN = (-0.8025, -0.805, -0.455)
DOMAIN_LOW = (-1.6, -1.4, -0.7)
DOMAIN_HIGH = (3.2, 1.4, 2.4)
FLUID_LOW = (0.0525, -0.12, 0.70)
FLUID_SIZE = (0.32, 0.24, 0.32)
SOURCE_BAND_COUNT = 3
SOURCE_BAND_WIDTH = 0.08
RHO0 = 1000.0
CONTINUOUS_VOLUME_M3 = FLUID_SIZE[0] * FLUID_SIZE[1] * FLUID_SIZE[2]
CONTINUOUS_MASS_KG = CONTINUOUS_VOLUME_M3 * RHO0
MASS_BUDGET = 1.0e-12
EXPECTED_CELLS = tuple(round(value / DP) for value in FLUID_SIZE)
EXPECTED_BAND_CELLS = (EXPECTED_CELLS[0], EXPECTED_CELLS[1] // SOURCE_BAND_COUNT, EXPECTED_CELLS[2])
EXPECTED_PER_BAND = EXPECTED_BAND_CELLS[0] * EXPECTED_BAND_CELLS[1] * EXPECTED_BAND_CELLS[2]
EXPECTED_TOTAL = EXPECTED_PER_BAND * SOURCE_BAND_COUNT


def load_fallback():
    spec = importlib.util.spec_from_file_location("f2_commensurate_fallback", FALLBACK_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {FALLBACK_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FALLBACK = load_fallback()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def q(value: float) -> str:
    return f"{float(value):.9f}".rstrip("0").rstrip(".") or "0"


def patch_domain(text: str) -> str:
    pattern = (
        r'(<simulationdomain>\s*<posmin\s+x=")[^"]+("\s+y=")[^"]+("\s+z=")[^"]+("\s*/>\s*'
        r'<posmax\s+x=")[^"]+("\s+y=")[^"]+("\s+z=")[^"]+("\s*/>\s*</simulationdomain>)'
    )
    values = [q(value) for value in (*DOMAIN_LOW, *DOMAIN_HIGH)]
    replacement = (
        r"\g<1>" + values[0] + r"\g<2>" + values[1] + r"\g<3>" + values[2] +
        r"\g<4>" + values[3] + r"\g<5>" + values[4] + r"\g<6>" + values[5] + r"\g<7>"
    )
    rewritten, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise ValueError("expected one execution simulationdomain")
    return rewritten


def source_paths(background: str) -> tuple[Path, Path]:
    source_xml = FAMILY_ROOT / "definitions" / f"F2_REF_{background}_NOMINAL_MEDIUM_Def.xml"
    source_motion = FAMILY_ROOT / "definitions" / f"F2_REF_{background}_NOMINAL_MEDIUM_motion.dat"
    if not source_xml.is_file() or not source_motion.is_file():
        raise FileNotFoundError((source_xml, source_motion))
    return source_xml, source_motion


def physical_descriptor(background: str, source_xml: Path, source_motion: Path) -> dict[str, Any]:
    # This is independent of DP, grid phase, save cadence, and repaired
    # numerical domain.  The source canonical hash preserves the finite
    # cup/receiver/tray geometry and the prescribed motion axis definition;
    # the explicit fluid descriptor binds the COMM4 continuous mother.
    return {
        "physical_mother_id": f"{CASE_PREFIX}_{background}_V1",
        "background": background.lower(),
        "source_geometry_control_hash": hashlib.sha256(
            FALLBACK.canonical_physical_xml(source_xml.read_text(encoding="utf-8")).encode("utf-8")
        ).hexdigest(),
        "source_motion_sha256": sha256(source_motion),
        "finite_geometry": "source XML cup mk0, receiver mk1, catch tray mk2; physical planes unchanged",
        "continuous_fluid_low_m": list(FLUID_LOW),
        "continuous_fluid_size_m": list(FLUID_SIZE),
        "continuous_fluid_volume_m3": CONTINUOUS_VOLUME_M3,
        "rho0_kg_m3": RHO0,
        "source_axis": "y",
        "source_band_count": SOURCE_BAND_COUNT,
        "source_band_width_m": SOURCE_BAND_WIDTH,
        "motion_window_s": [0.0, 4.0],
        "motion_control": "prescribed rotating finite cup about (0,-1,0.65) to (0,1,0.65), source bytes bound above",
    }


def materialize(background: str, definition_root: Path) -> dict[str, Any]:
    # Reuse the audited fallback transform without changing its tracked
    # coarse/medium/fine tables.  The wrapper supplies a private DP005 key.
    original_resolution = dict(FALLBACK.RESOLUTIONS)
    original_origins = dict(FALLBACK.GRID_ORIGINS)
    try:
        FALLBACK.RESOLUTIONS = {RESOLUTION: DP}
        FALLBACK.GRID_ORIGINS = {RESOLUTION: GRID_ORIGIN}
        short = FALLBACK.BACKGROUND_SHORT[background]
        case_id = f"{CASE_PREFIX}_{short}_V1_{RESOLUTION.upper()}"
        case_dir = definition_root / case_id
        metadata = FALLBACK.materialize_case(
            background,
            RESOLUTION,
            case_dir,
            scope_id=SCOPE_ID,
            case_prefix=CASE_PREFIX,
            physical_prefix=CASE_PREFIX,
            population_mode="drawbox_cellcenter",
        )
    finally:
        FALLBACK.RESOLUTIONS = original_resolution
        FALLBACK.GRID_ORIGINS = original_origins

    definition = Path(metadata["definition"]["path"])
    definition.write_text(patch_domain(definition.read_text(encoding="utf-8")), encoding="utf-8")
    source_xml, source_motion = source_paths(short)
    descriptor = physical_descriptor(short, source_xml, source_motion)
    expected = {
        "cells_xyz": list(EXPECTED_CELLS),
        "source_band_cells_xyz": list(EXPECTED_BAND_CELLS),
        "source_band_count": SOURCE_BAND_COUNT,
        "source_band_particle_count": EXPECTED_PER_BAND,
        "total_particle_count": EXPECTED_TOTAL,
        "continuous_volume_m3": CONTINUOUS_VOLUME_M3,
        "continuous_mass_kg": CONTINUOUS_MASS_KG,
        "lattice_volume_m3": EXPECTED_TOTAL * DP ** 3,
        "expected_lattice_mass_kg": EXPECTED_TOTAL * DP ** 3 * RHO0,
        "relative_mass_error": EXPECTED_TOTAL * DP ** 3 / CONTINUOUS_VOLUME_M3 - 1.0,
    }
    metadata.update({
        "schema": "ds-data-02.f2.commensurate-dp005.v1",
        "generator_version": "f2_commensurate_dp005.py:v1",
        "status": "new_numerical_view_definition_only_not_gencase_run",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "same_COMM4_physical_mother_numerical_view; zero_new_independent_physical_cases",
        "resolution": RESOLUTION,
        "dp_m": DP,
        "physical_case_id": f"{CASE_PREFIX}_{short}_V1",
        "parent_physical_case_id": f"{CASE_PREFIX}_{short}_V1",
        "same_physical_mother_as": [f"{CASE_PREFIX}_{short}_V1_COARSE", f"{CASE_PREFIX}_{short}_V1_MEDIUM", f"{CASE_PREFIX}_{short}_V1_FINE"],
        "physical_condition": descriptor,
        "physical_condition_hash": canonical_hash(descriptor),
        "numerical_recipe": {
            "recipe_id": RECIPE_ID,
            "dp_m": DP,
            "grid_origin_m": list(GRID_ORIGIN),
            "domain_low_m": list(DOMAIN_LOW),
            "domain_high_m": list(DOMAIN_HIGH),
            "population_mode": "drawbox_cellcenter",
            "save_interval_s": 0.001,
            "time_max_s": 4.0,
        },
        "numerical_recipe_hash": canonical_hash({
            "recipe_id": RECIPE_ID, "dp_m": DP, "grid_origin_m": list(GRID_ORIGIN),
            "domain_low_m": list(DOMAIN_LOW), "domain_high_m": list(DOMAIN_HIGH),
            "population_mode": "drawbox_cellcenter", "save_interval_s": 0.001, "time_max_s": 4.0,
        }),
        "domain_repair": {
            "id": "F2_NUM_DOMAIN_REPAIR01_PAD_0P20M",
            "low_m": list(DOMAIN_LOW),
            "high_m": list(DOMAIN_HIGH),
            "same_as_RV4": True,
            "physical_geometry_unchanged": True,
        },
        "geometry": {
            **metadata["geometry"],
            "continuous_fluid_low_m": list(FLUID_LOW),
            "continuous_fluid_size_m": list(FLUID_SIZE),
            "continuous_fluid_volume_m3": CONTINUOUS_VOLUME_M3,
            "continuous_fluid_mass_kg": CONTINUOUS_MASS_KG,
            "source_band_bounds_y_m": [[-0.12 + i * SOURCE_BAND_WIDTH, -0.12 + (i + 1) * SOURCE_BAND_WIDTH] for i in range(SOURCE_BAND_COUNT)],
            "numerical_grid_origin_m": list(GRID_ORIGIN),
            "numerical_domain_low_m": list(DOMAIN_LOW),
            "numerical_domain_high_m": list(DOMAIN_HIGH),
            "finite_faces": "cup bottom/left/right/front/back; receiver bottom/left/right/front/back; tray bottom; source XML geometry unchanged",
        },
        "expected_population": expected,
        "mass_error_budget_fraction": MASS_BUDGET,
    })
    metadata["definition"] = {"path": str(definition.resolve()), "sha256": sha256(definition)}
    metadata["source_definition"] = {"path": str(source_xml.resolve()), "sha256": sha256(source_xml)}
    metadata["source_motion"] = {"path": str(source_motion.resolve()), "sha256": sha256(source_motion)}
    # ``materialize_case`` returns an in-memory convenience binding that was
    # created after its own file write. It is stale after the DP005 metadata
    # update, so remove it before writing this file and bind the final file
    # externally below.
    metadata.pop("metadata", None)
    metadata_path = definition.with_name(f"{metadata['case_id']}.metadata.json")
    # Keep the file hash meaningful. A JSON file cannot contain its own final
    # SHA256, so the binding is returned to callers and written into the
    # request/manifest rather than recursively embedded in this file.
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    metadata["metadata"] = {"path": str(metadata_path.resolve()), "sha256": sha256(metadata_path)}
    return metadata


def make_gencase_request(metadata: dict[str, Any], output_root: Path, request_path: Path, attempt_id: str) -> dict[str, Any]:
    definition = Path(metadata["definition"]["path"])
    motion = Path(metadata["motion"]["path"])
    source_xml = Path(metadata["source_definition"]["path"])
    source_motion = Path(metadata["source_motion"]["path"])
    metadata_path = Path(metadata["metadata"]["path"])
    prefix = definition.with_suffix("")
    inputs = [FAMILY_ROOT / Path(__file__).name, FALLBACK_SCRIPT, source_xml, source_motion,
              definition, motion, metadata_path, RUNTIME_V2, GENCASE]
    inputs = [path.resolve() for path in inputs]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": metadata["case_id"],
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 4,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "command": [str(GENCASE), str(prefix), f"{{attempt_root}}/{metadata['case_id']}", "-save:all"],
        "cwd": str(definition.parent.resolve()),
        "raw_output_root": str((DATA_ROOT / "families/F2" / metadata["case_id"]).resolve()),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "scope_id": SCOPE_ID,
        "recipe_id": RECIPE_ID,
        "physical_case_id": metadata["physical_case_id"],
        "physical_condition_hash": metadata["physical_condition_hash"],
        "physical_geometry_control_hash": metadata["physical_condition"]["source_geometry_control_hash"],
        "numerical_recipe_hash": metadata["numerical_recipe_hash"],
        "resolution": RESOLUTION,
        "dp_m": DP,
        "domain_repair": metadata["domain_repair"],
        "expected_population": metadata["expected_population"],
        "source_binding": {
            "source_definition_sha256": metadata["source_definition"]["sha256"],
            "source_motion_sha256": metadata["source_motion"]["sha256"],
            "definition_sha256": metadata["definition"]["sha256"],
            "motion_sha256": metadata["motion"]["sha256"],
            "metadata_sha256": metadata["metadata"]["sha256"],
            "same_physical_mother_as": metadata["same_physical_mother_as"],
        },
        "gencase_prefix": str(prefix.resolve()),
        "gencase_artifacts": {
            "definition": metadata["definition"],
            "motion": metadata["motion"],
            "metadata": metadata["metadata"],
        },
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha256(path) for path in inputs},
        "generation_status": "new_same_physical_mother_dp005_cpu_preflight",
        "request_note": "Shared CPU GenCase only; DP005 is a numerical view of COMM4 physical mothers, zero new independent physical cases; no solver/GPU/Q-I/Q-N/production claim.",
    }
    write_json(request_path, request)
    return request


def make_audit_request(manifest_path: Path, request_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inputs: list[Path] = [AUDIT_SCRIPT, FAMILY_ROOT / Path(__file__).name, manifest_path, PARTVTK, RUNTIME_V2]
    for case in manifest["cases"]:
        request = json.loads(Path(case["request"]["path"]).read_text(encoding="utf-8"))
        receipt = DATA_ROOT / "families/F2" / case["case_id"] / request["attempt_id"] / "execution-receipt.json"
        inputs.extend([Path(case["definition"]["path"]), Path(case["metadata"]["path"]), Path(case["motion"]["path"]), Path(case["request"]["path"]), receipt])
    inputs = [path.resolve() for path in inputs]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": "F2_COMM4_DP005_INITIAL_AUDIT",
        "attempt_id": "audit-f2-comm4-dp005-initial-v1",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 8 * 1024**3,
        "command": ["/usr/bin/python3", str(AUDIT_SCRIPT.resolve()), "audit", "--manifest", str(manifest_path.resolve()), "--report-root", "{attempt_root}/report"],
        "cwd": str(FAMILY_ROOT.resolve()),
        "raw_output_root": str((DATA_ROOT / "families/F2/F2_COMM4_DP005_INITIAL_AUDIT").resolve()),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "solver_launch_forbidden": True,
        "scope_id": SCOPE_ID,
        "manifest_sha256": sha256(manifest_path),
        "input_files": [str(path) for path in inputs],
        "input_sha256": {str(path): sha256(path) for path in inputs},
        "request_note": "Shared CPU PartVTK initial-frame audit after two completed DP005 GenCase receipts; checks actual 3D counts, three source bands, native mass, typed IDs, initial cup occupancy, pose source binding, and finite wall faces. No solver/GPU/Q-I/Q-N/production claim.",
    }
    write_json(request_path, request)
    return request


def design(output_root: Path, *, output_subdir: str = "commensurate_cellcenter_dp005") -> dict[str, Any]:
    output_root = output_root.resolve()
    family_output = FAMILY_ROOT / output_subdir
    if family_output.exists() and any(family_output.iterdir()):
        raise ValueError(f"fresh output required: {family_output}")
    definitions = family_output / "definitions"
    requests = family_output / "requests"
    definitions.mkdir(parents=True, exist_ok=True)
    requests.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for background in ("center_catch", "offset_spill"):
        metadata = materialize(background, definitions)
        attempt_id = f"gencase-f2-{metadata['case_id'].lower().replace('_', '-')}-v1"
        request_path = requests / f"{metadata['case_id']}_request.json"
        request = make_gencase_request(metadata, output_root, request_path, attempt_id)
        cases.append({
            "case_id": metadata["case_id"],
            "physical_case_id": metadata["physical_case_id"],
            "background": background.lower(),
            "resolution": RESOLUTION,
            "definition": metadata["definition"],
            "motion": metadata["motion"],
            "metadata": metadata["metadata"],
            "request": {"path": str(request_path.resolve()), "sha256": sha256(request_path), "attempt_id": attempt_id},
            "expected_population": metadata["expected_population"],
            "physical_condition_hash": metadata["physical_condition_hash"],
            "numerical_recipe_hash": metadata["numerical_recipe_hash"],
        })
    manifest = {
        "schema": "ds-data-02.f2.commensurate-dp005-manifest.v1",
        "family_id": "F2",
        "scope_id": SCOPE_ID,
        "generator": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        "status": "same_physical_mother_cpu_gencase_requests_registered",
        "qualification_claim": "none",
        "production_claim": "none",
        "q_n_status": "pending actual 0.01 versus 0.005 full-window integration/save evidence",
        "registry_role": "same_COMM4_physical_mother_numerical_view; zero_new_independent_physical_cases",
        "new_independent_physical_case_count": 0,
        "physical_mother_ids": ["F2_COMM4_CENTER_V1", "F2_COMM4_OFFSET_V1"],
        "resolution": RESOLUTION,
        "dp_m": DP,
        "continuous_geometry": {"fluid_low_m": list(FLUID_LOW), "fluid_size_m": list(FLUID_SIZE), "volume_m3": CONTINUOUS_VOLUME_M3, "mass_kg": CONTINUOUS_MASS_KG, "rho0_kg_m3": RHO0, "source_band_count": SOURCE_BAND_COUNT, "source_band_width_m": SOURCE_BAND_WIDTH},
        "numerical_grid": {"origin_m": list(GRID_ORIGIN), "domain_low_m": list(DOMAIN_LOW), "domain_high_m": list(DOMAIN_HIGH), "population_rule": "point=continuous_low+dp/2; size=extent-dp; three disjoint y bands"},
        "cost_estimate": {"expected_fluid_particles": EXPECTED_TOTAL, "expected_gencase_total_particles": "measured by receipt; boundary support scales with dp^-2", "solver_fullstate_raw_formula": "4001 * actual_total_particles * at-least-64-bytes; cost review required before GPU", "solver_qualification": "root only; no GPU request emitted by this generator"},
        "cases": cases,
        "audit_request": {"materialize_after_gencase_receipts": "python f2_commensurate_dp005.py make-audit-request --manifest ..."},
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    manifest_path = family_output / "manifest.json"
    write_json(manifest_path, manifest)
    return {"manifest_path": str(manifest_path.resolve()), "manifest_sha256": sha256(manifest_path), "case_count": len(cases), "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_design = sub.add_parser("design")
    p_design.add_argument("--output-root", type=Path, default=DATA_ROOT / "families/F2/F2_COMM4_DP005")
    p_design.add_argument("--output-subdir", default="commensurate_cellcenter_dp005")
    p_manifest = sub.add_parser("make-audit-request")
    p_manifest.add_argument("--manifest", type=Path, required=True)
    p_manifest.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "design":
        print(json.dumps(design(args.output_root, output_subdir=args.output_subdir), ensure_ascii=False, indent=2))
        return 0
    request = make_audit_request(args.manifest.resolve(), args.request.resolve())
    print(json.dumps({"status": "written", "request": str(args.request.resolve()), "input_count": len(request["input_files"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
