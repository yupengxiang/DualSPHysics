#!/usr/bin/env python3
"""Build the isolated F2 cell-centred commensurate mother-case fallback.

The original 48-case F2 registry remains immutable.  This fallback defines a
new scope and physical mothers with the same finite rotating cup, receiver,
tray and prescribed motion, while replacing the old inclusive ``drawbox
solid`` fluid construction with three disjoint cell-centred fluid blocks.
The blocks partition the physical transverse width 0.24 m into 3 x 0.08 m
source bands.  The liquid box is 0.32 x 0.24 x 0.32 m, so the intended fluid
population is exactly ``32 x 24 x 32`` cells at dp=0.01, with the analogous
integer populations at dp=0.02 and 0.04.

This module only writes new definitions, metadata, manifests, and bounded
CPU GenCase requests.  It never launches GenCase, DualSPHysics, or GPU work.
Actual particle counts, source-band IDs, wall face coverage, non-overlap, and
mass must be audited from the resulting GenCase BI4 through the shared
runtime before any solver request is considered.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping


SCHEMA = "ds-data-02.f2.commensurate-fallback.v1"
FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_COMMENSURATE_CELLCENTER_V1"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
WORKTREE = Path(__file__).resolve().parents[5]
LAB_ROOT = Path(__file__).resolve().parents[4]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_ROOT = FAMILY_ROOT / "definitions"

RESOLUTIONS: dict[str, float] = {"coarse": 0.04, "medium": 0.02, "fine": 0.01}
BACKGROUND_SOURCE = {
    "center_catch": SOURCE_ROOT / "F2_REF_CENTER_NOMINAL_MEDIUM_Def.xml",
    "offset_spill": SOURCE_ROOT / "F2_REF_OFFSET_NOMINAL_MEDIUM_Def.xml",
}
BACKGROUND_MOTION = {
    "center_catch": SOURCE_ROOT / "F2_REF_CENTER_NOMINAL_MEDIUM_motion.dat",
    "offset_spill": SOURCE_ROOT / "F2_REF_OFFSET_NOMINAL_MEDIUM_motion.dat",
}
BACKGROUND_SHORT = {"center_catch": "CENTER", "offset_spill": "OFFSET"}

# Continuous physical liquid domain.  The y width is partitioned into three
# non-overlapping source bands; the z extent is the common liquid level.
FLUID_LOW = (0.0525, -0.12, 0.70)
FLUID_SIZE = (0.32, 0.24, 0.32)
SOURCE_BAND_COUNT = 3
SOURCE_BAND_WIDTH = 0.08
LIQUID_VOLUME_M3 = FLUID_SIZE[0] * FLUID_SIZE[1] * FLUID_SIZE[2]
RHO0 = 1000.0
MASS_BUDGET_FRACTION = 1.0e-12

FLUID_REGION_RE = re.compile(
    r'(?P<indent>[ \t]*)<setmkfluid mk="0" />\s*'
    r'<drawbox>\s*<boxfill>solid</boxfill>\s*'
    r'<point\s+[^>]*/>\s*<size\s+[^>]*/>\s*</drawbox>\s*'
    r'<setmkfluid mk="1" />\s*'
    r'<drawbox>\s*<boxfill>solid</boxfill>\s*'
    r'<point\s+[^>]*/>\s*<size\s+[^>]*/>\s*</drawbox>\s*'
    r'<setmkfluid mk="2" />\s*'
    r'<drawbox>\s*<boxfill>solid</boxfill>\s*'
    r'<point\s+[^>]*/>\s*<size\s+[^>]*/>\s*</drawbox>',
    re.DOTALL,
)


def q(value: float) -> str:
    return f"{float(value):.9f}".rstrip("0").rstrip(".") or "0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def git_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(WORKTREE), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"


def expected_population(dp: float) -> dict[str, Any]:
    counts = [int(round(length / dp)) for length in FLUID_SIZE]
    if any(abs(count * dp - length) > 1e-12 for count, length in zip(counts, FLUID_SIZE)):
        raise ValueError(f"fluid extent is not commensurate with dp={dp}")
    band_counts = [counts[0], counts[1] // SOURCE_BAND_COUNT, counts[2]]
    if counts[1] % SOURCE_BAND_COUNT:
        raise ValueError(f"transverse width is not divisible into {SOURCE_BAND_COUNT} bands at dp={dp}")
    per_band = band_counts[0] * band_counts[1] * band_counts[2]
    total = per_band * SOURCE_BAND_COUNT
    return {
        "cells_xyz": counts,
        "source_band_cells_xyz": band_counts,
        "source_band_count": SOURCE_BAND_COUNT,
        "source_band_particle_count": per_band,
        "total_particle_count": total,
        "lattice_volume_m3": total * dp**3,
        "continuous_volume_m3": LIQUID_VOLUME_M3,
        "continuous_mass_kg": LIQUID_VOLUME_M3 * RHO0,
        "expected_lattice_mass_kg": total * dp**3 * RHO0,
        "relative_mass_error": (total * dp**3 / LIQUID_VOLUME_M3) - 1.0,
    }


def canonical_physical_xml(text: str) -> str:
    """Normalize numerical grid and case-name tokens for cross-view binding."""
    text = re.sub(r'<definition dp="[^"]+"', '<definition dp="{DP}"', text, count=1)
    text = re.sub(r'<file name="[^"]+_motion\.dat"\s*/>', '<file name="{MOTION}" />', text)
    text = re.sub(r'physical_case_id=[^;]+;', 'physical_case_id={PHYSICAL};', text)
    text = re.sub(r'resolution=[^\s-]+ -->', 'resolution={RESOLUTION} -->', text)
    text = re.sub(r'CaseName=\"[^\"]+\"', 'CaseName="{CASE}"', text)
    text = re.sub(r'<setmkfluid mk="[012]" />\s*<fillbox x="[^"]+" y="[^"]+" z="[^"]+">', '<setmkfluid mk="{MK}" /><fillbox>', text)
    return text


def fluid_commands(dp: float) -> str:
    x_low, y_low, z_low = FLUID_LOW
    x_size, y_size, z_size = FLUID_SIZE
    lines: list[str] = []
    for mk in range(SOURCE_BAND_COUNT):
        band_low_y = y_low + mk * SOURCE_BAND_WIDTH
        point = (x_low + dp / 2.0, band_low_y + dp / 2.0, z_low + dp / 2.0)
        size = (x_size - dp, SOURCE_BAND_WIDTH - dp, z_size - dp)
        lines.extend(
            [
                f'          <setmkfluid mk="{mk}" />',
                f'          <fillbox x="{q(dp)}" y="{q(dp)}" z="{q(dp)}">',
                '            <modefill>fluid</modefill>',
                f'            <point x="{q(point[0])}" y="{q(point[1])}" z="{q(point[2])}" />',
                f'            <size x="{q(size[0])}" y="{q(size[1])}" z="{q(size[2])}" />',
                '          </fillbox>',
            ]
        )
    return "\n".join(lines)


def materialize_case(background: str, resolution: str, output_dir: Path) -> dict[str, Any]:
    if background not in BACKGROUND_SOURCE:
        raise ValueError(f"unknown background {background}")
    if resolution not in RESOLUTIONS:
        raise ValueError(f"unknown resolution {resolution}")
    source_xml = BACKGROUND_SOURCE[background].resolve()
    source_motion = BACKGROUND_MOTION[background].resolve()
    source_text = source_xml.read_text(encoding="utf-8")
    if len(FLUID_REGION_RE.findall(source_text)) != 1:
        raise ValueError(f"expected one three-band fluid region in {source_xml}")
    dp = RESOLUTIONS[resolution]
    expected = expected_population(dp)
    short = BACKGROUND_SHORT[background]
    case_id = f"F2_COMM_{short}_V1_{resolution.upper()}"
    physical_case_id = f"F2_COMM_{short}_V1"
    motion_name = f"{case_id}_motion.dat"
    transformed = re.sub(r'<definition dp="[^"]+"', f'<definition dp="{q(dp)}"', source_text, count=1)
    transformed = transformed.replace(source_motion.name, motion_name)
    transformed = transformed.replace(
        '<!-- mechanism=' + ("center_catch" if background == "center_catch" else "offset_spill") + '; physical_case_id=F2_REF_' + ("CENTER" if background == "center_catch" else "OFFSET") + '_NOMINAL; resolution=' + resolution + ' -->',
        f'<!-- mechanism={background}; physical_case_id={physical_case_id}; resolution={resolution}; scope={SCOPE_ID} -->',
    )
    transformed, replacements = FLUID_REGION_RE.subn(fluid_commands(dp), transformed, count=1)
    if replacements != 1:
        raise ValueError(f"fluid region was not replaced for {case_id}")
    y_low = FLUID_LOW[1]
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    definition_path = output_dir / f"{case_id}_Def.xml"
    motion_path = output_dir / motion_name
    definition_path.write_text(transformed, encoding="utf-8")
    shutil.copyfile(source_motion, motion_path)
    metadata = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "scope_id": SCOPE_ID,
        "status": "new_scope_definition_only_not_gencase_run",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "new_scope_new_physical_mothers_outside_original_F2_48_registry",
        "background": background,
        "resolution": resolution,
        "dp_m": dp,
        "case_id": case_id,
        "physical_case_id": physical_case_id,
        "paired_physical_case_id": "F2_COMM_CENTER_V1" if background == "offset_spill" else "F2_COMM_OFFSET_V1",
        "source_definition": {"path": str(source_xml), "sha256": sha256(source_xml)},
        "source_motion": {"path": str(source_motion), "sha256": sha256(source_motion)},
        "definition": {"path": str(definition_path), "sha256": sha256(definition_path)},
        "motion": {"path": str(motion_path), "sha256": sha256(motion_path)},
        "geometry": {
            "continuous_fluid_low_m": list(FLUID_LOW),
            "continuous_fluid_size_m": list(FLUID_SIZE),
            "continuous_fluid_volume_m3": LIQUID_VOLUME_M3,
            "fluid_source_axis": "y",
            "source_band_count": SOURCE_BAND_COUNT,
            "source_band_width_m": SOURCE_BAND_WIDTH,
            "source_band_bounds_y_m": [[y_low + i * SOURCE_BAND_WIDTH, y_low + (i + 1) * SOURCE_BAND_WIDTH] for i in range(SOURCE_BAND_COUNT)],
            "cell_center_rule": "point=continuous_low+dp/2; size=continuous_extent-dp; generated centers span low+dp/2 through high-dp/2",
            "cup_receiver_tray": "copied from the corresponding historical F2 source definition; only new commensurate fluid population and new case/scope identity are changed",
            "fluid_wall_clearance_m": {"x_low": 0.0525, "x_high": 0.0525, "y_low": 0.03, "y_high": 0.03, "z_low": 0.05, "z_high": 0.08},
        },
        "motion_and_solver": {
            "motion_copied_from_source_without_byte_change": True,
            "solver_parameters_copied_from_source_without_change": True,
            "control_amplitude_deg": -105.0,
            "event_window_s": 4.0,
        },
        "expected_population": expected,
        "mass_error_budget_fraction": MASS_BUDGET_FRACTION,
        "physical_grid_hash_scope": "canonical source geometry/control XML with dp, case, motion filename, and source-band fill spacing normalized; continuous fluid point/size values retained",
        "physical_grid_hash": hashlib.sha256(canonical_physical_xml(transformed).encode("utf-8")).hexdigest(),
        "source_geometry_control_hash": hashlib.sha256(canonical_physical_xml(source_text).encode("utf-8")).hexdigest(),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    metadata_path = output_dir / f"{case_id}.metadata.json"
    write_json(metadata_path, metadata)
    metadata["metadata"] = {"path": str(metadata_path), "sha256": sha256(metadata_path)}
    return metadata


def runner_request(metadata: Mapping[str, Any], output_root: Path, attempt_id: str) -> dict[str, Any]:
    definition = Path(metadata["definition"]["path"]).resolve()
    motion = Path(metadata["motion"]["path"]).resolve()
    source_xml = Path(metadata["source_definition"]["path"]).resolve()
    source_motion = Path(metadata["source_motion"]["path"]).resolve()
    metadata_path = definition.with_name(f"{metadata['case_id']}.metadata.json")
    case_id = str(metadata["case_id"])
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 4,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "command": [str(GENCASE), str(definition.with_suffix("")), f"{{attempt_root}}/{case_id}", "-save:all"],
        "cwd": str(definition.parent),
        "raw_output_root": str(output_root.resolve()),
        "worktree_root": str(WORKTREE),
        "solver_launch_forbidden": True,
        "generation_status": "new_scope_commensurate_definition_written_not_gencase_run",
        "registry_role": "new_scope_new_physical_mothers_outside_original_F2_48_registry",
        "scope_id": SCOPE_ID,
        "input_files": [str(Path(__file__).resolve()), str(source_xml), str(source_motion), str(definition), str(motion), str(metadata_path)],
        "source_definition_sha256": metadata["source_definition"]["sha256"],
        "source_motion_sha256": metadata["source_motion"]["sha256"],
        "definition_sha256": metadata["definition"]["sha256"],
        "motion_sha256": metadata["motion"]["sha256"],
        "metadata_sha256": sha256(metadata_path),
        "expected_population": metadata["expected_population"],
        "request_note": "Shared CPU GenCase only; new F2 fallback scope; do not infer qualification or production before independent PartVTK audit.",
    }
    return request


def design(output_root: Path) -> dict[str, Any]:
    definition_root = FAMILY_ROOT / "commensurate_cellcenter" / "definitions"
    request_root = FAMILY_ROOT / "commensurate_cellcenter" / "requests"
    manifest_cases: list[dict[str, Any]] = []
    for background in ("center_catch", "offset_spill"):
        for resolution in ("coarse", "medium", "fine"):
            case_dir = definition_root / f"F2_COMM_{BACKGROUND_SHORT[background]}_V1_{resolution.upper()}"
            metadata = materialize_case(background, resolution, case_dir)
            attempt_id = f"gencase-f2-comm-{BACKGROUND_SHORT[background].lower()}-{resolution}-v1"
            request = runner_request(metadata, output_root / metadata["case_id"], attempt_id)
            request_path = request_root / f"{metadata['case_id']}_request.json"
            write_json(request_path, request)
            manifest_cases.append({
                "case_id": metadata["case_id"],
                "physical_case_id": metadata["physical_case_id"],
                "background": background,
                "resolution": resolution,
                "definition": metadata["definition"],
                "metadata": {"path": str(case_dir / f"{metadata['case_id']}.metadata.json"), "sha256": sha256(case_dir / f"{metadata['case_id']}.metadata.json")},
                "request": {"path": str(request_path), "sha256": sha256(request_path), "attempt_id": attempt_id},
                "expected_population": metadata["expected_population"],
            })
    manifest = {
        "schema": "ds-data-02.f2.commensurate-fallback-manifest.v1",
        "family_id": FAMILY_ID,
        "scope_id": SCOPE_ID,
        "status": "new_scope_gencase_requests_registered_not_run",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "new_scope_new_physical_mothers_outside_original_F2_48_registry",
        "physical_geometry": {"fluid_low_m": list(FLUID_LOW), "fluid_size_m": list(FLUID_SIZE), "fluid_volume_m3": LIQUID_VOLUME_M3, "source_axis": "y", "source_band_width_m": SOURCE_BAND_WIDTH},
        "resolution_rule": "same continuous physical mother and background geometry; only numerical dp and cell-centre spacing change",
        "mass_budget_fraction": MASS_BUDGET_FRACTION,
        "cases": manifest_cases,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_commit": git_commit(),
    }
    manifest_path = FAMILY_ROOT / "commensurate_cellcenter" / "manifest.json"
    write_json(manifest_path, manifest)
    return {"manifest_path": str(manifest_path), "manifest_sha256": sha256(manifest_path), "case_count": len(manifest_cases), "cases": manifest_cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("design")
    p.add_argument("--output-root", type=Path, default=DATA_ROOT / "families/F2/F2_COMMENSURATE_CELLCENTER")
    args = parser.parse_args()
    if args.command == "design":
        result = design(args.output_root)
        print(json.dumps({"status": "designed", **result}, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
