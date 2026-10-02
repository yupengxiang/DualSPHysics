#!/usr/bin/env python3
"""Build the isolated F2 Gem-backed cell-centred commensurate mother cases.

The original 48-case F2 registry remains immutable.  This fallback defines a
new scope and physical mothers with the same finite rotating cup, receiver,
tray and prescribed motion, while replacing the old inclusive ``drawbox
solid`` fluid construction with three disjoint cell-centred fluid blocks.
The blocks partition the physical transverse width 0.24 m into 3 x 0.08 m
source bands.  The liquid box is 0.32 x 0.24 x 0.32 m, so the intended fluid
population is exactly ``32 x 24 x 32`` cells at dp=0.01, with the analogous
integer populations at dp=0.02 and 0.04.

The source XML and motion bytes are frozen copies of the current integration
Gem P01 definitions under ``handoff_20261002/source_assets``.  The old
consumed XML/H5/reports and the original 48-case registry are never edited.

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


SCHEMA = "ds-data-02.f2.gem-handoff-20261002.v2"
FAMILY_ID = "F2"
SCOPE_ID = "F2_SCOPE_GEM_COMMENSURATE_CELLCENTER_20261002_V2"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
WORKTREE = Path(__file__).resolve().parents[5]
LAB_ROOT = Path(__file__).resolve().parents[4]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F2"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
HANDOFF_ROOT = FAMILY_ROOT / "handoff_20261002"
SOURCE_ROOT = HANDOFF_ROOT / "source_assets"

RESOLUTIONS: dict[str, float] = {"coarse": 0.04, "medium": 0.02, "fine": 0.01}
# Numerical grid phases for the cell-centre scope. Each origin is just below
# the historical domain minimum and makes low+dp/2 an exact lattice node.
# Continuous wall/source coordinates remain those of the source XML.
GRID_ORIGINS: dict[str, tuple[float, float, float]] = {
    "coarse": (-1.4075, -1.22, -0.56),
    "medium": (-1.4175, -1.21, -0.55),
    "fine": (-1.4025, -1.205, -0.555),
}
BACKGROUND_SOURCE = {
    "center_catch": SOURCE_ROOT / "F2_GEM_CENTER_P01_Def.xml",
    "offset_spill": SOURCE_ROOT / "F2_GEM_OFFSET_P01_Def.xml",
}
BACKGROUND_MOTION = {
    "center_catch": SOURCE_ROOT / "F2_GEM_CENTER_P01_motion.dat",
    "offset_spill": SOURCE_ROOT / "F2_GEM_OFFSET_P01_motion.dat",
}
INTEGRATION_SOURCE = {
    "center_catch": {
        "definition": Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/production/definitions/F2_CENTER_P01_Def.xml"),
        "motion": Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/production/definitions/F2_CENTER_P01_motion.dat"),
    },
    "offset_spill": {
        "definition": Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/production/definitions/F2_OFFSET_P01_Def.xml"),
        "motion": Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/production/definitions/F2_OFFSET_P01_motion.dat"),
    },
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


def verify_frozen_source(background: str) -> dict[str, Any]:
    """Bind the handoff copy to the integration Gem bytes without editing them."""
    source_xml = BACKGROUND_SOURCE[background].resolve()
    source_motion = BACKGROUND_MOTION[background].resolve()
    if not source_xml.is_file() or not source_motion.is_file():
        raise FileNotFoundError(f"handoff source asset missing for {background}")
    original = INTEGRATION_SOURCE[background]
    original_xml = original["definition"].resolve()
    original_motion = original["motion"].resolve()
    result = {
        "frozen_definition": {"path": str(source_xml), "sha256": sha256(source_xml)},
        "frozen_motion": {"path": str(source_motion), "sha256": sha256(source_motion)},
        "integration_definition": {"path": str(original_xml), "sha256": sha256(original_xml) if original_xml.is_file() else None},
        "integration_motion": {"path": str(original_motion), "sha256": sha256(original_motion) if original_motion.is_file() else None},
    }
    if result["frozen_definition"]["sha256"] != result["integration_definition"]["sha256"]:
        raise ValueError(f"frozen Gem definition differs from integration source: {background}")
    if result["frozen_motion"]["sha256"] != result["integration_motion"]["sha256"]:
        raise ValueError(f"frozen Gem motion differs from integration source: {background}")
    return result


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
    """Canonicalize the physical geometry/control contract only.

    The fluid population, numerical ``dp`` and lattice ``pointmin`` are
    removed from this digest.  This keeps the same Gem cup/receiver/tray and
    prescribed motion bound across the three numerical views while leaving
    the full XML available for the separate recipe digest.
    """
    text = FLUID_REGION_RE.sub('<!-- FROZEN_FLUID_POPULATION -->', text, count=1)
    text = re.sub(r'<definition dp="[^"]+"', '<definition dp="{DP}"', text, count=1)
    text = re.sub(r'<pointmin x="[^"]+" y="[^"]+" z="[^"]+"\s*/>', '<pointmin x="{GRID_X}" y="{GRID_Y}" z="{GRID_Z}" />', text, count=1)
    text = re.sub(r'<file name="[^"]+_motion\.dat"\s*/>', '<file name="{MOTION}" />', text)
    text = re.sub(r'physical_case_id=[^;]+;', 'physical_case_id={PHYSICAL};', text)
    text = re.sub(r'resolution=[^\s-]+(?:; scope=[^>]+)? -->', 'resolution={RESOLUTION}; scope={SCOPE} -->', text)
    return text


def canonical_numeric_xml(text: str) -> str:
    """Canonicalize a complete numerical recipe while removing case names."""
    text = re.sub(r'<file name="[^"]+_motion\.dat"\s*/>', '<file name="{MOTION}" />', text)
    text = re.sub(r'physical_case_id=[^;]+;', 'physical_case_id={PHYSICAL};', text)
    text = re.sub(r'resolution=[^\s-]+(?:; scope=[^>]+)? -->', 'resolution={RESOLUTION}; scope={SCOPE} -->', text)
    text = re.sub(r'F2_(?:GEM_)?(?:CENTER|OFFSET)_P01_motion\.dat', '{MOTION}', text)
    text = re.sub(r'F2H10_[A-Z]+_V1_(?:COARSE|MEDIUM|FINE)', '{CASE}', text)
    return text


def fluid_commands(dp: float, population_mode: str = "fluid_direct") -> str:
    """Return the three disjoint fluid source commands.

    ``fluid_direct`` is retained only for the already-consumed V1 definitions.
    GenCase 5.4 accepts ``fillbox`` as a flood-fill operation, so the new V2
    scope uses the documented ``modefill=void`` form with ``mkbound=0``.  The
    two modes are deliberately explicit in generated metadata and requests;
    a completed GenCase receipt never silently changes meaning when this
    generator evolves.
    """
    if population_mode not in {"fluid_direct", "void_mkbound", "drawbox_commensurate", "drawbox_cellcenter"}:
        raise ValueError(f"unknown population mode {population_mode}")
    x_low, y_low, z_low = FLUID_LOW
    x_size, y_size, z_size = FLUID_SIZE
    lines: list[str] = []
    for mk in range(SOURCE_BAND_COUNT):
        band_low_y = y_low + mk * SOURCE_BAND_WIDTH
        # The cell-centre mode supplies low+dp/2 directly. Its pointmin phase
        # is aligned per resolution before GenCase runs, so no endpoint is
        # rounded out and no interface source is duplicated.
        point = (
            x_low if population_mode == "drawbox_commensurate" else x_low + dp / 2.0,
            band_low_y if population_mode == "drawbox_commensurate" else band_low_y + dp / 2.0,
            z_low if population_mode == "drawbox_commensurate" else z_low + dp / 2.0,
        )
        size = (x_size - dp, SOURCE_BAND_WIDTH - dp, z_size - dp)
        lines.append(f'          <setmkfluid mk="{mk}" />')
        if population_mode in {"drawbox_commensurate", "drawbox_cellcenter"}:
            lines.extend(
                [
                    '          <drawbox>',
                    '            <boxfill>solid</boxfill>',
                    f'            <point x="{q(point[0])}" y="{q(point[1])}" z="{q(point[2])}" />',
                    f'            <size x="{q(size[0])}" y="{q(size[1])}" z="{q(size[2])}" />',
                    '          </drawbox>',
                ]
            )
        else:
            fillbox = (
                f'          <fillbox x="{q(dp)}" y="{q(dp)}" z="{q(dp)}" mkbound="0">'
                if population_mode == "void_mkbound"
                else f'          <fillbox x="{q(dp)}" y="{q(dp)}" z="{q(dp)}">'
            )
            lines.extend(
                [
                    fillbox,
                    (
                        '            <modefill>void</modefill>'
                        if population_mode == "void_mkbound"
                        else '            <modefill>fluid</modefill>'
                    ),
                    f'            <point x="{q(point[0])}" y="{q(point[1])}" z="{q(point[2])}" />',
                    f'            <size x="{q(size[0])}" y="{q(size[1])}" z="{q(size[2])}" />',
                    '          </fillbox>',
                ]
            )
    return "\n".join(lines)


def materialize_case(
    background: str,
    resolution: str,
    output_dir: Path,
    *,
    scope_id: str = SCOPE_ID,
    case_prefix: str = "F2_COMM",
    physical_prefix: str = "F2_COMM",
    population_mode: str = "drawbox_cellcenter",
) -> dict[str, Any]:
    if background not in BACKGROUND_SOURCE:
        raise ValueError(f"unknown background {background}")
    if resolution not in RESOLUTIONS:
        raise ValueError(f"unknown resolution {resolution}")
    source_xml = BACKGROUND_SOURCE[background].resolve()
    source_motion = BACKGROUND_MOTION[background].resolve()
    source_binding = verify_frozen_source(background)
    source_text = source_xml.read_text(encoding="utf-8")
    if len(FLUID_REGION_RE.findall(source_text)) != 1:
        raise ValueError(f"expected one three-band fluid region in {source_xml}")
    dp = RESOLUTIONS[resolution]
    expected = expected_population(dp)
    short = BACKGROUND_SHORT[background]
    case_id = f"{case_prefix}_{short}_V1_{resolution.upper()}"
    physical_case_id = f"{physical_prefix}_{short}_V1"
    motion_name = f"{case_id}_motion.dat"
    transformed = re.sub(r'<definition dp="[^"]+"', f'<definition dp="{q(dp)}"', source_text, count=1)
    if population_mode == "drawbox_cellcenter":
        origin = GRID_ORIGINS[resolution]
        transformed = re.sub(
            r'<pointmin x="[^"]+" y="[^"]+" z="[^"]+"\s*/>',
            f'<pointmin x="{q(origin[0])}" y="{q(origin[1])}" z="{q(origin[2])}" />',
            transformed,
            count=1,
        )
    # Gem P01 XML names the original control file (F2_CENTER/offset_P01).
    # Bind the copied control under the new case name so GenCase cannot
    # accidentally resolve an old working-tree file.
    transformed = re.sub(r'<file name="[^"]+_motion\.dat"\s*/>', f'<file name="{motion_name}" />', transformed, count=1)
    transformed = re.sub(
        r'<!-- mechanism=[^>]+ -->',
        f'<!-- mechanism={background}; physical_case_id={physical_case_id}; resolution={resolution}; scope={scope_id} -->',
        transformed,
        count=1,
    )
    transformed, replacements = FLUID_REGION_RE.subn(fluid_commands(dp, population_mode), transformed, count=1)
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
        "scope_id": scope_id,
        "status": "new_scope_definition_only_not_gencase_run",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "new_scope_new_physical_mothers_outside_original_F2_48_registry",
        "background": background,
        "resolution": resolution,
        "dp_m": dp,
        "case_id": case_id,
        "physical_case_id": physical_case_id,
        "paired_physical_case_id": f"{physical_prefix}_CENTER_V1" if background == "offset_spill" else f"{physical_prefix}_OFFSET_V1",
        "source_definition": {"path": str(source_xml), "sha256": sha256(source_xml)},
        "source_motion": {"path": str(source_motion), "sha256": sha256(source_motion)},
        "source_binding": source_binding,
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
            "numerical_grid_origin_m": list(GRID_ORIGINS[resolution]) if population_mode == "drawbox_cellcenter" else None,
            "grid_origin_semantics": "pointmin is a numerical lattice phase selected per dp; continuous wall planes and source geometry remain source XML coordinates",
            "cup_receiver_tray": "copied byte-for-byte from the current integration Gem P01 source; only new commensurate fluid population, numerical grid phase, and case/scope identity are changed",
            "fluid_wall_clearance_m": {"x_low": 0.0525, "x_high": 0.0525, "y_low": 0.03, "y_high": 0.03, "z_low": 0.05, "z_high": 0.08},
        },
        "motion_and_solver": {
            "motion_copied_from_source_without_byte_change": True,
            "solver_parameters_copied_from_source_without_change": True,
            "control_amplitude_deg": -105.0,
            "event_window_s": 4.0,
        },
        "population_construction": {
            "mode": population_mode,
            "source_axis": "y",
            "source_band_interfaces_are_disjoint": True,
            "fluid_command_contract": {
                "fluid_direct": "fillbox modefill=fluid; point is low+dp/2 and size is extent-dp",
                "void_mkbound": "fillbox modefill=void mkbound=0; point is low+dp/2 and size is extent-dp",
                "drawbox_commensurate": "drawbox solid; point is continuous low edge and size is extent-dp, yielding centres low+dp/2 through high-dp/2",
                "drawbox_cellcenter": "drawbox solid; point is low+dp/2 and size is extent-dp on the aligned numerical grid, yielding centres low+dp/2 through high-dp/2",
            }[population_mode],
        },
        "expected_population": expected,
        "mass_error_budget_fraction": MASS_BUDGET_FRACTION,
        "physical_geometry_control_hash_scope": "canonical Gem cup/receiver/tray finite-face geometry, motion axis/file content, and solver control XML; dp, pointmin, fluid population, case names, and motion filename normalized or removed",
        "physical_geometry_control_hash": hashlib.sha256(canonical_physical_xml(transformed).encode("utf-8")).hexdigest(),
        "source_geometry_control_hash": hashlib.sha256(canonical_physical_xml(source_text).encode("utf-8")).hexdigest(),
        "numerical_recipe_hash_scope": "complete generated XML including dp, pointmin, cell-centre commands, solver parameters, and 4 s save window; case tokens normalized",
        "numerical_recipe_hash": hashlib.sha256(canonical_numeric_xml(transformed).encode("utf-8")).hexdigest(),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    metadata_path = output_dir / f"{case_id}.metadata.json"
    write_json(metadata_path, metadata)
    metadata["metadata"] = {"path": str(metadata_path), "sha256": sha256(metadata_path)}
    return metadata


def runner_request(
    metadata: Mapping[str, Any],
    output_root: Path,
    attempt_id: str,
    *,
    scope_id: str = SCOPE_ID,
) -> dict[str, Any]:
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
        "generation_status": "new_scope_gem_backed_definition_written_not_gencase_run",
        "registry_role": "new_scope_new_physical_mothers_outside_original_F2_48_registry",
        "scope_id": scope_id,
        "input_files": [str(Path(__file__).resolve()), str(source_xml), str(source_motion), str(definition), str(motion), str(metadata_path)],
        "source_definition_sha256": metadata["source_definition"]["sha256"],
        "source_motion_sha256": metadata["source_motion"]["sha256"],
        "definition_sha256": metadata["definition"]["sha256"],
        "motion_sha256": metadata["motion"]["sha256"],
        "metadata_sha256": sha256(metadata_path),
        "expected_population": metadata["expected_population"],
        "request_note": "Shared v2 CPU GenCase only; new Gem-backed F2 scope; do not infer qualification or production before independent PartVTK audit.",
    }
    return request


def design(
    output_root: Path,
    *,
    scope_id: str = SCOPE_ID,
    case_prefix: str = "F2_COMM",
    physical_prefix: str = "F2_COMM",
    population_mode: str = "drawbox_cellcenter",
    output_subdir: str = "handoff_20261002/gridphase_v2",
    attempt_suffix: str = "20261002-002",
) -> dict[str, Any]:
    definition_root = FAMILY_ROOT / output_subdir / "definitions"
    request_root = FAMILY_ROOT / output_subdir / "requests"
    manifest_cases: list[dict[str, Any]] = []
    for background in ("center_catch", "offset_spill"):
        for resolution in ("coarse", "medium", "fine"):
            case_dir = definition_root / f"{case_prefix}_{BACKGROUND_SHORT[background]}_V1_{resolution.upper()}"
            metadata = materialize_case(
                background,
                resolution,
                case_dir,
                scope_id=scope_id,
                case_prefix=case_prefix,
                physical_prefix=physical_prefix,
                population_mode=population_mode,
            )
            attempt_id = f"gencase-f2-{case_prefix.lower().replace('_', '-')}-{BACKGROUND_SHORT[background].lower()}-{resolution}-{attempt_suffix}"
            request = runner_request(metadata, output_root / metadata["case_id"], attempt_id, scope_id=scope_id)
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
        "schema": "ds-data-02.f2.gem-handoff-20261002-manifest.v1",
        "family_id": FAMILY_ID,
        "scope_id": scope_id,
        "status": "new_scope_gencase_requests_registered_not_run",
        "qualification_claim": "none",
        "production_claim": "none",
        "registry_role": "new_scope_new_physical_mothers_outside_original_F2_48_registry",
        "physical_geometry": {"fluid_low_m": list(FLUID_LOW), "fluid_size_m": list(FLUID_SIZE), "fluid_volume_m3": LIQUID_VOLUME_M3, "source_axis": "y", "source_band_width_m": SOURCE_BAND_WIDTH, "finite_outer_geometry": "Gem P01 cup/receiver/tray copied unchanged per background"},
        "resolution_rule": "same continuous physical mother and background geometry; only numerical dp and cell-centre spacing change",
        "mass_budget_fraction": MASS_BUDGET_FRACTION,
        "cases": manifest_cases,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_commit": git_commit(),
        "population_mode": population_mode,
        "case_prefix": case_prefix,
        "physical_prefix": physical_prefix,
    }
    manifest_path = FAMILY_ROOT / output_subdir / "manifest.json"
    write_json(manifest_path, manifest)
    return {"manifest_path": str(manifest_path), "manifest_sha256": sha256(manifest_path), "case_count": len(manifest_cases), "cases": manifest_cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("design")
    p.add_argument("--output-root", type=Path, default=DATA_ROOT / "families/F2/F2H10_GEM_COMMENSURATE_V2")
    p.add_argument("--scope-id", default=SCOPE_ID)
    p.add_argument("--case-prefix", default="F2H10V2")
    p.add_argument("--physical-prefix", default="F2H10V2")
    p.add_argument("--population-mode", choices=("fluid_direct", "void_mkbound", "drawbox_commensurate", "drawbox_cellcenter"), default="drawbox_cellcenter")
    p.add_argument("--output-subdir", default="handoff_20261002/gridphase_v2")
    p.add_argument("--attempt-suffix", default="20261002-002")
    args = parser.parse_args()
    if args.command == "design":
        result = design(
            args.output_root,
            scope_id=args.scope_id,
            case_prefix=args.case_prefix,
            physical_prefix=args.physical_prefix,
            population_mode=args.population_mode,
            output_subdir=args.output_subdir,
            attempt_suffix=args.attempt_suffix,
        )
        print(json.dumps({"status": "designed", **result}, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
