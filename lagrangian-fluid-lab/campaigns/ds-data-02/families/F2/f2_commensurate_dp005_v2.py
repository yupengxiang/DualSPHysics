#!/usr/bin/env python3
"""Register the first evidence-based DP005 lattice-phase repair.

The completed DP005 v1 CENTER GenCase showed 63 rather than 64 x-cell
centres in each source band.  Its source bytes and receipt stay immutable.
The cause is a half-cell phase mismatch between ``pointmin`` and the explicit
cell-centre points.  This additive recipe keeps the COMM4 physical mother,
fluid extent, finite geometry, motion control, and repaired solver domain,
while choosing a pointmin phase aligned on all three axes.  It only writes
new v2 definitions and bounded CPU GenCase requests; it never launches a
solver or GPU job.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from typing import Any


FAMILY_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
V1_SCRIPT = FAMILY_ROOT / "f2_commensurate_dp005.py"
SCOPE_ID = "F2_SCOPE_COMMENSURATE_CELLCENTER_V4"
RECIPE_ID = "F2_COMMENSURATE_CELLCENTER_V5_DP005_GRIDALIGNED_V2"
GRID_ORIGIN = (-0.805, -0.8075, -0.4575)
OUTPUT_SUBDIR = "commensurate_cellcenter_dp005_v2"
ATTEMPT_SUFFIX = "gridaligned-v2"


def load_v1():
    spec = importlib.util.spec_from_file_location("f2_commensurate_dp005_v1", V1_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {V1_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = load_v1()


def sha256(path: Path) -> str:
    return V1.sha256(path)


def write_json(path: Path, value: Any) -> None:
    V1.write_json(path, value)


def canonical_hash(value: Any) -> str:
    return V1.canonical_hash(value)


def materialize(background: str, definitions: Path) -> dict[str, Any]:
    old_origin = V1.GRID_ORIGIN
    old_recipe = V1.RECIPE_ID
    try:
        V1.GRID_ORIGIN = GRID_ORIGIN
        V1.RECIPE_ID = RECIPE_ID
        metadata = V1.materialize(background, definitions)
    finally:
        V1.GRID_ORIGIN = old_origin
        V1.RECIPE_ID = old_recipe
    metadata["generator_version"] = "f2_commensurate_dp005_v2.py:v1; repair01_gridphase"
    metadata["status"] = "repair01_same_physical_mother_definition_only_not_gencase_run"
    metadata["repair"] = {
        "repair_id": "F2_DP005_REPAIR01_GRID_PHASE_ALIGNMENT",
        "root_cause": "explicit fluid cell-centre point was half a dp off the GenCase pointmin lattice on x/y/z",
        "evidence": "DP005 CENTER v1 receipt: 64512 fluid per band versus 65536 expected; coarse/medium/fine COMM4 views use aligned pointmin phases",
        "changed_fields": ["numerical_grid_origin_m"],
        "physical_geometry_control_unchanged": True,
        "same_physical_mother": True,
    }
    metadata["numerical_recipe"]["grid_origin_m"] = list(GRID_ORIGIN)
    metadata["numerical_recipe_hash"] = canonical_hash(metadata["numerical_recipe"])
    metadata["geometry"]["numerical_grid_origin_m"] = list(GRID_ORIGIN)
    metadata["metadata"] = None
    metadata_path = Path(metadata["definition"]["path"]).with_name(f"{metadata['case_id']}.metadata.json")
    metadata.pop("metadata", None)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    metadata["metadata"] = {"path": str(metadata_path.resolve()), "sha256": sha256(metadata_path)}
    return metadata


def make_request(metadata: dict[str, Any], request_path: Path, attempt_id: str) -> dict[str, Any]:
    request = V1.make_gencase_request(
        metadata, DATA_ROOT / "families/F2" / f"{metadata['case_id']}_DP005_V2", request_path, attempt_id,
    )
    request["input_files"].append(str(Path(__file__).resolve()))
    request["input_sha256"][str(Path(__file__).resolve())] = sha256(Path(__file__))
    request.update({
        "scope_id": SCOPE_ID,
        "recipe_id": RECIPE_ID,
        "raw_output_root": str((DATA_ROOT / "families/F2" / f"{metadata['case_id']}_DP005_REPAIR01").resolve()),
        "generation_status": "repair01_same_physical_mother_dp005_gridaligned_cpu_preflight",
        "repair_id": "F2_DP005_REPAIR01_GRID_PHASE_ALIGNMENT",
        "request_note": "Shared CPU GenCase only; additive repair01 aligns pointmin to explicit DP005 cell centres. v1 failure remains preserved; zero new independent physical cases; no solver/GPU/Q-I/Q-N/production claim.",
    })
    write_json(request_path, request)
    return request


def design(output_root: Path) -> dict[str, Any]:
    output = FAMILY_ROOT / OUTPUT_SUBDIR
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"fresh output required: {output}")
    definitions = output / "definitions"
    requests = output / "requests"
    definitions.mkdir(parents=True, exist_ok=True)
    requests.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for background in ("center_catch", "offset_spill"):
        metadata = materialize(background, definitions)
        attempt_id = f"gencase-f2-{metadata['case_id'].lower().replace('_', '-')}-{ATTEMPT_SUFFIX}"
        request_path = requests / f"{metadata['case_id']}_repair01_request.json"
        request = make_request(metadata, request_path, attempt_id)
        cases.append({
            "case_id": metadata["case_id"],
            "physical_case_id": metadata["physical_case_id"],
            "background": background,
            "resolution": V1.RESOLUTION,
            "definition": metadata["definition"],
            "motion": metadata["motion"],
            "metadata": metadata["metadata"],
            "request": {"path": str(request_path.resolve()), "sha256": sha256(request_path), "attempt_id": attempt_id},
            "expected_population": metadata["expected_population"],
            "physical_condition_hash": metadata["physical_condition_hash"],
            "numerical_recipe_hash": metadata["numerical_recipe_hash"],
        })
    manifest = {
        "schema": "ds-data-02.f2.commensurate-dp005-repair01-manifest.v1",
        "family_id": "F2", "scope_id": SCOPE_ID,
        "generator": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        "helper_generator": {"path": str(V1_SCRIPT.resolve()), "sha256": sha256(V1_SCRIPT)},
        "status": "repair01_same_physical_mother_cpu_gencase_requests_registered",
        "qualification_claim": "none", "production_claim": "none",
        "q_n_status": "pending actual full-window integration/save and v1-v2 diagnostics",
        "registry_role": "same_COMM4_physical_mother_numerical_view; zero_new_independent_physical_cases",
        "new_independent_physical_case_count": 0,
        "repair": {"id": "F2_DP005_REPAIR01_GRID_PHASE_ALIGNMENT", "grid_origin_m": list(GRID_ORIGIN), "same_domain_as_RV4": True},
        "physical_mother_ids": ["F2_COMM4_CENTER_V1", "F2_COMM4_OFFSET_V1"],
        "resolution": V1.RESOLUTION, "dp_m": V1.DP,
        "continuous_geometry": {"fluid_low_m": list(V1.FLUID_LOW), "fluid_size_m": list(V1.FLUID_SIZE), "volume_m3": V1.CONTINUOUS_VOLUME_M3, "mass_kg": V1.CONTINUOUS_MASS_KG, "rho0_kg_m3": V1.RHO0, "source_band_count": V1.SOURCE_BAND_COUNT, "source_band_width_m": V1.SOURCE_BAND_WIDTH},
        "numerical_grid": {"origin_m": list(GRID_ORIGIN), "domain_low_m": list(V1.DOMAIN_LOW), "domain_high_m": list(V1.DOMAIN_HIGH), "population_rule": "point=continuous_low+dp/2; size=extent-dp; pointmin-to-point alignment verified as integer indices"},
        "cost_estimate": {"expected_fluid_particles": V1.EXPECTED_TOTAL, "expected_gencase_total_particles": "measured by receipt", "solver_fullstate_raw_formula": "4001 * actual_total_particles * at-least-64-bytes; root cost review required before GPU", "solver_qualification": "root only; no GPU request emitted"},
        "cases": cases,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    manifest_path = output / "manifest.json"
    write_json(manifest_path, manifest)
    return {"manifest_path": str(manifest_path.resolve()), "manifest_sha256": sha256(manifest_path), "case_count": len(cases), "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DATA_ROOT / "families/F2/F2_COMM4_DP005_REPAIR01")
    args = parser.parse_args()
    print(json.dumps(design(args.output_root.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
