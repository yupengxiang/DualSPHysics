#!/usr/bin/env python3
"""F5 exact DP=.025 cell-centre initialization mother and bounded audits.

The two earlier coarse initialization repairs are retained as negative
evidence.  This scope is a new, commensurate medium mother: the registered
continuous reservoir is exactly ``4.20 x 1.40 x .40 m`` and a ``.025 m``
cell-centre lattice has ``168 x 56 x 16 = 150528`` particles, hence exactly
2352 kg at rho0=1000 kg/m3.  The source bed, finite walls, piston controls,
time window, and denominator are unchanged.  Only the void fill primitive is
replaced by an explicit cell-centre drawbox.

This module writes definitions and shared-runner CPU requests.  It never
launches GenCase, PartVTK, DualSPHysics, or a GPU.  ``partvtk-request`` and
``audit`` are deliberately separate from the GenCase request so every actual
receipt and generated prefix is hash-bound before the next CPU action.
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
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
WORKTREE_ROOT = SCRIPT.parents[2]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F5"
SCOPE = "F5_CONTINUOUS_CELL_CENTRE_EXACT_DP025_005"
REPAIR_ROOT = FAMILY_ROOT / f"initialization_repairs/{SCOPE}"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
RAW_OUTPUT_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/case/attempt")

RHO0 = 1000.0
DP = 0.025
FLUID_LOW = (-0.90, -0.70, 0.02)
FLUID_SIZE = (4.20, 1.40, 0.40)
MASS_BUDGET = 0.01
EVENT_WINDOW_S = 16.0
CASE_SPECS: dict[str, dict[str, str]] = {
    "runup_return": {
        "source_definition": "F5_REF_RUNUP_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_RUNUP_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_f91973457a049db5_regular_piston.dat",
        "case_id": "F5_REF_RUNUP_NOMINAL_MEDIUM_CELL_CENTRE_EXACT_005",
        "source_mother": "runup_return",
    },
    "weir_pair": {
        "source_definition": "F5_REF_WEIR_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_WEIR_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_4c73cd98b7230035_regular_piston.dat",
        "case_id": "F5_REF_WEIR_NOMINAL_MEDIUM_CELL_CENTRE_EXACT_005",
        "source_mother": "weir_pair",
    },
}
SOURCE_BED = FAMILY_ROOT / "definitions/assets/f5_continuous_bed_profile_slope_0p280.stl"
QUALITY_CONTRACT = FAMILY_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = FAMILY_ROOT / "event_definitions.json"
INTEGRATION_SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
OLD_VOLUME_AUDIT = FAMILY_ROOT / "native_conversion/initial-continuous-volume-audit-001.json"
OLD_REPAIR_001_COMPARISON = FAMILY_ROOT / "initialization_repairs/F5_RUNUP_NOMINAL_COARSE_CELL_CENTRE_001/initialization-repair-comparison-001.json"
OLD_REPAIR_002_AUDIT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/"
    "F5_SECOND_BOUNDED_INITIALIZATION_REPAIR_AND_BED_PRESERVATION_AUDIT.json"
)
PHASE_EVIDENCE_003 = FAMILY_ROOT / "initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_MEDIUM_003/actual_preflight_evidence_003.json"
OLD_REPAIR_004_EVIDENCE = FAMILY_ROOT / "initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_MEDIUM_004/actual_preflight_evidence_004.json"
OLD_REPAIR_004_LEDGER = FAMILY_ROOT / "initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_MEDIUM_004/previous_repair_failure_ledger_004.json"
FAILURE_LEDGER = REPAIR_ROOT / "previous_repair_failure_ledger_005.json"
RUNNER_V2 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
PYTHON_VENV = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")

# GenCase's pointref=(0,0,0) phase emits the first center at point+dp/2.
# The old 4.175 m request emitted 167 x layers and 4.20 m emitted 169.
# 4.19 m is a new explicitly registered numerical construction chosen to
# request the same 168 centers as the fixed continuous 4.20 m box without
# moving any physical wall, bed, piston, liquid level, or denominator.
REQUESTED_X_DRAW_SIZE = 4.19


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(WORKTREE_ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"


def q(value: float) -> str:
    return f"{float(value):.9f}".rstrip("0").rstrip(".") or "0"


def lattice() -> dict[str, Any]:
    counts = tuple(int(round(size / DP)) for size in FLUID_SIZE)
    point = tuple(low + DP / 2.0 for low in FLUID_LOW)
    # GenCase's pointref=(0,0,0) phase emits the first center at point+dp/2.
    # The old 4.175 m request emitted 167 x layers and 4.20 m emitted 169.
    # This separately registered numerical mother requests 4.19 m to target
    # the 168 centers of the unchanged 4.20 m continuous reservoir.
    draw_size = (REQUESTED_X_DRAW_SIZE, (counts[1] - 1) * DP, (counts[2] - 1) * DP)
    emitted_first = (-0.875, -0.675, 0.025)
    emitted_last = tuple(emitted_first[i] + (counts[i] - 1) * DP for i in range(3))
    continuous_volume = math.prod(FLUID_SIZE)
    lattice_volume = math.prod(counts) * DP**3
    high = tuple(low + size for low, size in zip(FLUID_LOW, FLUID_SIZE))
    return {
        "rule": "explicit solid cell-centre lattice: point=low+dp/2; GenCase phase-guarded drawbox",
        "dp_m": DP,
        "counts_xyz": list(counts),
        "particle_count": math.prod(counts),
        "continuous_low_m": list(FLUID_LOW),
        "continuous_size_m": list(FLUID_SIZE),
        "continuous_high_m": list(high),
        "point_m": list(point),
        "first_center_m": list(emitted_first),
        "last_center_m": list(emitted_last),
        "expected_generated_phase_first_m": list(emitted_first),
        "expected_generated_phase_last_m": list(emitted_last),
        "requested_x_draw_size_m": REQUESTED_X_DRAW_SIZE,
        "phase_guard": {
            "prior_request_003_x_m": 4.175,
            "prior_observed_003_x_layers": 167,
            "prior_request_004_x_m": 4.20,
            "prior_observed_004_x_layers": 169,
            "new_request_is_numerical_only": True,
        },
        "draw_size_m": list(draw_size),
        "continuous_volume_m3": continuous_volume,
        "lattice_volume_m3": lattice_volume,
        "continuous_mass_kg": continuous_volume * RHO0,
        "native_lattice_mass_kg": lattice_volume * RHO0,
        "relative_mass_error": lattice_volume / continuous_volume - 1.0,
        "mass_budget_fraction": MASS_BUDGET,
        "mass_budget_pass": abs(lattice_volume / continuous_volume - 1.0) <= MASS_BUDGET,
        "mass_rescaling": False,
    }


def _fluid_block() -> str:
    data = lattice()
    point = data["point_m"]
    size = data["draw_size_m"]
    return "\n".join(
        [
            '          <drawbox cmt="initial_fluid_cell_centres_exact_dp025_005">',
            "            <boxfill>solid</boxfill>",
            f'            <point x="{q(point[0])}" y="{q(point[1])}" z="{q(point[2])}" />',
            f'            <size x="{q(size[0])}" y="{q(size[1])}" z="{q(size[2])}" />',
            "          </drawbox>",
        ]
    )


OLD_FILL = re.compile(
    r'(?P<indent>[ \t]*)<fillbox x="2" y="0\.18" z="0\.10">\s*'
    r'<modefill>void</modefill>\s*'
    r'<point x="-0\.90" y="-0\.70" z="0\.02" />\s*'
    r'<size x="4\.20" y="1\.40" z="0\.4" />\s*'
    r'</fillbox>',
    re.DOTALL,
)
NEW_FILL = re.compile(
    r'<drawbox cmt="initial_fluid_cell_centres_exact_dp025_005">\s*'
    r'<boxfill>solid</boxfill>\s*<point [^>]*/>\s*<size [^>]*/>\s*'
    r'</drawbox>',
    re.DOTALL,
)


def canonical_source(text: str) -> str:
    text = OLD_FILL.sub("<F5_INITIAL_FLUID_PRIMITIVE>", text, count=1)
    text = NEW_FILL.sub("<F5_INITIAL_FLUID_PRIMITIVE>", text, count=1)
    text = re.sub(r"[ \t]*<F5_INITIAL_FLUID_PRIMITIVE>", "<F5_INITIAL_FLUID_PRIMITIVE>", text)
    return text


def rewrite_definition(source: Path, target: Path) -> dict[str, Any]:
    source = Path(source).resolve()
    text = source.read_text(encoding="utf-8")
    repaired, count = OLD_FILL.subn(lambda _match: _fluid_block(), text, count=1)
    if count != 1:
        raise ValueError(f"expected one registered void fillbox in {source}")
    ET.fromstring(repaired)
    if canonical_source(text) != canonical_source(repaired):
        raise AssertionError("repair changed XML outside the registered fluid primitive")
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(repaired, encoding="utf-8")
    return {
        "source": bind(source, "immutable F5 medium physical mother"),
        "repair": bind(target, "new DP=.025 cell-centre mother"),
        "replacement_count": count,
        "source_equivalence_after_fluid_token": True,
        "semantic_change": "void fill replaced by explicit commensurate cell-centre drawbox only",
    }


def previous_failure_ledger() -> dict[str, Any]:
    rows: dict[str, Any] = {
        "schema": "ds-data-02.f5.initialization-repair-failure-ledger.v2",
        "created_at_utc": utc_now(),
        "family_id": "F5",
        "scope": SCOPE,
        "old_repairs_are_immutable": True,
        "repair_001": {
            "scope": "F5_RUNUP_NOMINAL_COARSE_CELL_CENTRE_001",
            "mechanism": "fluid drawn after boundaries overwrote bed support",
            "fluid_particles": 86151,
            "native_mass_kg": 2326.077086,
            "continuum_mass_kg": 2352.0,
            "relative_mass_error": -0.011,
            "boundary_overlap_or_loss": "4004 old mk40 boundary coordinates were overwritten; fixed ledger fell by 4004",
            "evidence": bind(OLD_REPAIR_001_COMPARISON, "immutable repair-001 negative evidence"),
        },
        "repair_002": {
            "scope": "F5_RUNUP_NOMINAL_COARSE_CELL_CENTRE_002",
            "mechanism": "fluid first then boundaries preserved support but physical bed occupied the registered gross fill span",
            "fluid_particles": 68530,
            "native_mass_kg": 1850.31,
            "continuum_mass_kg": 2352.0,
            "relative_mass_error": -0.2133,
            "fixed_boundary_delta": 0,
            "exact_fluid_boundary_overlap": 0,
            "evidence": bind(OLD_REPAIR_002_AUDIT, "immutable integration audit for repair-002"),
        },
        "interpretation": {
            "repair_001_and_002_exhaust_old_coarse_scope": True,
            "new_scope_reason": "DP=.025 divides all registered reservoir spans exactly; same finite bed/wall/piston geometry is tested without changing denominator or particle mass",
            "mass_formula": "rho0*dp^3",
            "continuum_denominator_m3": math.prod(FLUID_SIZE),
            "no_mass_rescaling": True,
            "qualification_claim": "none",
        },
    }
    rows["repair_003_phase_evidence"] = {
        "scope": "F5_CONTINUOUS_CELL_CENTRE_MEDIUM_003",
        "fluid_particles": 149632,
        "native_mass_kg": 2338.0,
        "relative_mass_error": -0.005952380952380952,
        "fluid_axis_counts_xyz": [167, 56, 16],
        "exact_fluid_boundary_overlap": 0,
        "cause": "requested 4.175 m x drawbox was snapped by GenCase against pointref=(0,0,0), losing its upper x layer",
        "evidence": bind(PHASE_EVIDENCE_003, "immutable actual repair-003 phase evidence"),
    }
    rows["repair_004_phase_evidence"] = {
        "scope": "F5_CONTINUOUS_CELL_CENTRE_MEDIUM_004",
        "fluid_particles": 151424,
        "native_mass_kg": 2366.0,
        "relative_mass_error": 0.005952380952380952,
        "fluid_axis_counts_xyz": [169, 56, 16],
        "exact_fluid_boundary_overlap": 0,
        "fluid_bounds_m": {"min": [-0.875, -0.675, 0.025], "max": [3.325, 0.7, 0.4]},
        "cause": "requested 4.20 m x drawbox emitted an extra upper x layer at 3.325 m, outside the unchanged registered high x=3.30 m",
        "evidence": bind(OLD_REPAIR_004_EVIDENCE, "immutable actual repair-004 negative evidence"),
        "failure_ledger": bind(OLD_REPAIR_004_LEDGER, "immutable repair-004 ledger"),
    }
    return rows


def _source_paths(spec: Mapping[str, str]) -> dict[str, Path]:
    return {
        "definition": FAMILY_ROOT / "definitions" / spec["source_definition"],
        "metadata": FAMILY_ROOT / "definitions" / spec["source_metadata"],
        "motion": FAMILY_ROOT / "definitions" / spec["motion"],
    }


def _common_inputs() -> list[Path]:
    return [
        SCRIPT,
        RUNNER_V2,
        SOURCE_BED,
        QUALITY_CONTRACT,
        EVENT_DEFINITIONS,
        INTEGRATION_SAVE_PLAN,
        OLD_VOLUME_AUDIT,
        OLD_REPAIR_001_COMPARISON,
        PHASE_EVIDENCE_003,
        OLD_REPAIR_004_EVIDENCE,
        OLD_REPAIR_004_LEDGER,
        FAILURE_LEDGER,
    ]


def prepare(family_dir: Path = FAMILY_ROOT) -> dict[str, Any]:
    family_dir = Path(family_dir).resolve()
    repair_root = family_dir / f"initialization_repairs/{SCOPE}"
    repair_root.mkdir(parents=True, exist_ok=True)
    ledger_path = repair_root / "previous_repair_failure_ledger_005.json"
    write_json(ledger_path, previous_failure_ledger())
    results: dict[str, Any] = {}
    for mechanism, spec in CASE_SPECS.items():
        source = _source_paths(spec)
        case_dir = repair_root / mechanism
        assets = case_dir / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        definition = case_dir / f'{spec["case_id"]}.xml'
        rewrite = rewrite_definition(source["definition"], definition)
        motion = case_dir / source["motion"].name
        bed = assets / SOURCE_BED.name
        shutil.copy2(source["motion"], motion)
        shutil.copy2(SOURCE_BED, bed)
        metadata = {
            "schema": "ds-data-02.f5.initialization-repair-metadata.v2",
            "family_id": "F5",
            "repair_scope": SCOPE,
            "producer_script": bind(SCRIPT, "committed exact cell-centre producer"),
            "producer_git_commit": git_commit(),
            "case_id": spec["case_id"],
            "mechanism_id": mechanism,
            "source_mother": spec["source_mother"],
            "source_definition": bind(source["definition"], "immutable medium physical mother"),
            "repair_definition": bind(definition, "new DP=.025 definition"),
            "source_metadata": bind(source["metadata"], "immutable medium source metadata"),
            "source_motion": bind(source["motion"], "immutable piston source"),
            "repair_motion": bind(motion, "byte-identical colocated piston control"),
            "source_bed": bind(SOURCE_BED, "immutable finite bed STL"),
            "repair_bed": bind(bed, "byte-identical colocated finite bed STL"),
            "lattice": lattice(),
            "numerical_generation": {
                "method": "explicit_solid_drawbox_cell_centres",
                "scope_is_new_numerical_mother": True,
                "requested_drawbox_point_m": lattice()["point_m"],
                "requested_drawbox_size_m": lattice()["draw_size_m"],
                "continuous_box_is_unchanged": True,
                "phase_guard_is_not_physical_geometry": True,
                "mass_rescaling": False,
            },
            "physical_contract": {
                "continuum_low_m": list(FLUID_LOW),
                "continuum_size_m": list(FLUID_SIZE),
                "continuum_high_m": [FLUID_LOW[i] + FLUID_SIZE[i] for i in range(3)],
                "density_kg_m3": RHO0,
                "continuum_mass_kg": math.prod(FLUID_SIZE) * RHO0,
                "particle_mass_kg": RHO0 * DP**3,
                "finite_walls_bed_and_piston_unchanged": True,
                "mass_rescaling": False,
                "denominator_policy": "gross registered continuum box remains denominator; physical boundary overlap is measured, never subtracted by definition",
                "event_window_s": EVENT_WINDOW_S,
                "geometry_and_control_source_equivalence": "all source XML outside the fluid primitive, source piston bytes, finite bed bytes, quality/event/save contracts remain hash-bound",
                "rigid_body_contract": "not_applicable; F5 has no floating rigid body",
            },
            "previous_repairs": {
                "repair_001_and_002_preserved": True,
                "repair_003_and_004_preserved": True,
                "failure_ledger": bind(ledger_path, "additive sidecar for prior negative evidence"),
            },
            "rewrite_evidence": rewrite,
            "qualification_claim": "none",
            "production_claim": "none",
            "q_n_status": "pending_shared_gencase_and_partvtk_initial_frame; this is a new mother preflight",
            "created_at_utc": utc_now(),
        }
        metadata_path = case_dir / "initialization-repair-metadata-005.json"
        write_json(metadata_path, metadata)
        preflight = {
            "schema": "ds-data-02.f5.initialization-repair-preflight.v2",
            "created_at_utc": utc_now(),
            "family_id": "F5",
            "repair_scope": SCOPE,
            "case_id": spec["case_id"],
            "mechanism_id": mechanism,
            "producer_script": bind(SCRIPT, "committed exact cell-centre producer"),
            "producer_git_commit": git_commit(),
            "status": "static_pass_pending_actual_gencase_and_partvtk",
            "static_checks": {
                "source_is_medium_dp_025": f'dp="0.025"' in source["definition"].read_text(encoding="utf-8"),
                "source_void_fill_present": bool(OLD_FILL.search(source["definition"].read_text(encoding="utf-8"))),
                "repair_xml_well_formed": ET.parse(definition).getroot().tag == "case",
                "source_equivalence_outside_fluid_primitive": True,
                "exact_commensurate_count": lattice()["particle_count"] == 150528,
                "exact_continuum_mass_kg": abs(lattice()["native_lattice_mass_kg"] - 2352.0) < 1e-9,
                "mass_budget_pass": lattice()["mass_budget_pass"],
                "finite_bed_present": bed.is_file(),
                "motion_present": motion.is_file(),
                "physical_geometry_markers_in_source": all(marker in source["definition"].read_text(encoding="utf-8") for marker in ("tank_floor", "finite_sidewall_left", "finite_sidewall_right", "prescribed_piston", "drawfilestl")),
                "same_event_window_s": EVENT_WINDOW_S == 16.0,
                "no_rigid_body_is_expected_in_f5": True,
            },
            "lattice": lattice(),
            "physical_contract": metadata["physical_contract"],
            "root_review_required": ["actual GenCase dimension and typed counts", "PartVTK initial frame boundary ledger", "fluid mass against unchanged 2352 kg denominator"],
            "qualification_claim": "none",
            "production_claim": "none",
        }
        preflight_path = case_dir / "initialization-repair-preflight-005.json"
        write_json(preflight_path, preflight)
        results[mechanism] = {"definition": str(definition), "metadata": str(metadata_path), "preflight": str(preflight_path), "case_dir": str(case_dir)}
    return {"repair_root": str(repair_root), "failure_ledger": str(ledger_path), "cases": results, "git_commit": git_commit(), "lattice": lattice()}


def _request_inputs(case_dir: Path, source: Mapping[str, Path], definition: Path, motion: Path, bed: Path, metadata: Path, preflight: Path, ledger: Path) -> list[str]:
    paths = _common_inputs() + [source["definition"], source["metadata"], source["motion"], definition, motion, bed, metadata, preflight, ledger]
    return [str(Path(path).resolve()) for path in paths]


def write_gencase_requests(family_dir: Path = FAMILY_ROOT) -> list[dict[str, Any]]:
    family_dir = Path(family_dir).resolve()
    repair_root = family_dir / f"initialization_repairs/{SCOPE}"
    ledger = repair_root / "previous_repair_failure_ledger_005.json"
    if not ledger.is_file():
        raise FileNotFoundError("run prepare before gencase-requests")
    requests: list[dict[str, Any]] = []
    for mechanism, spec in CASE_SPECS.items():
        source = _source_paths(spec)
        case_dir = repair_root / mechanism
        definition = case_dir / f'{spec["case_id"]}.xml'
        motion = case_dir / source["motion"].name
        bed = case_dir / "assets" / SOURCE_BED.name
        metadata = case_dir / "initialization-repair-metadata-005.json"
        preflight = case_dir / "initialization-repair-preflight-005.json"
        required = [source["definition"], source["metadata"], source["motion"], definition, motion, bed, metadata, preflight]
        if not all(path.is_file() for path in required):
            raise FileNotFoundError(next(path for path in required if not path.is_file()))
        request = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F5",
            "case_id": spec["case_id"],
            "attempt_id": f'gencase-f5-{mechanism}-cellcentre-exact-dp025-005',
            "kind": "cpu",
            "cpu_task_kind": "gencase",
            "command": [str(GENCASE), str(definition.with_suffix("")), f'{{attempt_root}}/{spec["case_id"]}', "-save:all"],
            "cwd": str(case_dir),
            "max_wall_seconds": 300,
            "cpu_threads": 4,
            "estimated_storage_bytes": 512 * 1024 * 1024,
            "input_files": _request_inputs(case_dir, source, definition, motion, bed, metadata, preflight, ledger),
            "worktree_root": str(WORKTREE_ROOT),
            "launch_commit": git_commit(),
            "runner_v2": bind(RUNNER_V2, "shared CPU runner implementation"),
            "source_definition_hash_bound": bind(source["definition"], "immutable physical source XML"),
            "source_metadata_hash_bound": bind(source["metadata"], "immutable physical source metadata"),
            "source_motion_hash_bound": bind(source["motion"], "immutable piston control"),
            "source_bed_hash_bound": bind(SOURCE_BED, "immutable finite bed geometry"),
            "source_mother": spec["source_mother"],
            "repair_scope": SCOPE,
            "repair_reason": "new explicitly registered phase-guarded DP=.025 cell-centre mother after immutable 003/004 phase evidence; all physical geometry/control/domain and 2352 kg denominator stay fixed",
            "registered_continuum_box": {"low_m": list(FLUID_LOW), "size_m": list(FLUID_SIZE), "density_kg_m3": RHO0, "mass_kg": 2352.0},
            "expected_cell_centre_lattice": lattice(),
            "event_window_s": EVENT_WINDOW_S,
            "generation_status": "new_mother_committed_pending_shared_v2_gencase",
            "solver_launch_forbidden": True,
            "q_n_status": "pending_actual_gencase_and_partvtk; no qualification claim",
            "qualification_claim": "none",
            "production_claim": "none",
            "raw_output_root": str(RAW_OUTPUT_ROOT),
            "request_note": "CPU GenCase only through ds_data02_runtime_v2.py; never start solver/GPU from this request.",
        }
        path = case_dir / "gencase-request-005.json"
        write_json(path, request)
        request["path"] = str(path)
        request["sha256"] = sha256(path)
        requests.append(request)
    return requests


def _completed_receipt(receipt_path: Path) -> dict[str, Any]:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or int(receipt.get("returncode", 1)) != 0:
        raise ValueError(f"receipt is not successful: {receipt_path}")
    if int(receipt.get("fluid_particles", 0)) <= 0 or int(receipt.get("solver_dimension_from_gencase", 0)) != 3:
        raise ValueError("receipt does not prove positive 3-D fluid")
    return receipt


def write_partvtk_requests(receipt_paths: Mapping[str, Path], family_dir: Path = FAMILY_ROOT) -> list[dict[str, Any]]:
    family_dir = Path(family_dir).resolve()
    repair_root = family_dir / f"initialization_repairs/{SCOPE}"
    requests: list[dict[str, Any]] = []
    for mechanism, receipt_path in receipt_paths.items():
        if mechanism not in CASE_SPECS:
            raise ValueError(f"unknown mechanism {mechanism}")
        receipt_path = Path(receipt_path).resolve()
        receipt = _completed_receipt(receipt_path)
        case_id = CASE_SPECS[mechanism]["case_id"]
        case_dir = repair_root / mechanism
        output_root = Path(receipt["output_root"]).resolve()
        prefix = output_root / case_id
        generated_xml = prefix.with_suffix(".xml")
        generated_bi4 = prefix.with_suffix(".bi4")
        if not generated_xml.is_file() or not generated_bi4.is_file():
            raise FileNotFoundError(f"completed GenCase prefix missing XML/BI4: {prefix}")
        request = {
            "schema": "ds-data-02.runner.request.v1",
            "family_id": "F5",
            "case_id": case_id,
            "attempt_id": f'audit-f5-{mechanism}-cellcentre-exact-dp025-005',
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "command": [str(PYTHON_VENV), str(SCRIPT), "audit", "--generated-bi4", str(generated_bi4), "--generated-xml", str(generated_xml), "--output", "{attempt_root}/initialization-audit-005.json", "--csv-output", "{attempt_root}/partvtk-initial-005.csv"],
            "cwd": str(case_dir),
            "max_wall_seconds": 600,
            "cpu_threads": 4,
            "estimated_storage_bytes": 2 * 1024 * 1024 * 1024,
            "input_files": [
                str(path.resolve())
                for path in (
                    _common_inputs()
                    + [
                        _source_paths(CASE_SPECS[mechanism])["definition"],
                        _source_paths(CASE_SPECS[mechanism])["metadata"],
                        _source_paths(CASE_SPECS[mechanism])["motion"],
                        case_dir / "gencase-request-005.json",
                        case_dir / "initialization-repair-preflight-005.json",
                        case_dir / "initialization-repair-metadata-005.json",
                        case_dir / f"{case_id}.xml",
                        case_dir / _source_paths(CASE_SPECS[mechanism])["motion"].name,
                        case_dir / "assets" / SOURCE_BED.name,
                        receipt_path,
                        generated_xml,
                        generated_bi4,
                    ]
                )
            ],
            "worktree_root": str(WORKTREE_ROOT),
            "launch_commit": git_commit(),
            "gencase_receipt": str(receipt_path),
            "gencase_receipt_sha256": sha256(receipt_path),
            "generated_xml_sha256": sha256(generated_xml),
            "generated_bi4_sha256": sha256(generated_bi4),
            "runner_v2": bind(RUNNER_V2, "shared CPU runner implementation"),
            "audit_scope": "official PartVTK frame 0; fluid type=3 count/mass/lattice bounds; finite wall/moving type ledger; exact fluid-boundary coordinate overlap; actual 3-D XML",
            "solver_launch_forbidden": True,
            "q_n_status": "pending_root_review; initial mass and boundary evidence only",
            "qualification_claim": "none",
            "production_claim": "none",
            "request_note": "CPU PartVTK audit only, submitted via v2 runtime; no solver/GPU.",
        }
        path = case_dir / "partvtk-audit-request-005.json"
        write_json(path, request)
        request["path"] = str(path)
        request["sha256"] = sha256(path)
        requests.append(request)
    return requests


def parse_partvtk_csv(csv_path: Path) -> dict[str, Any]:
    fluid: set[tuple[float, float, float]] = set()
    boundary: set[tuple[float, float, float]] = set()
    type_counts: dict[str, int] = {}
    mk_counts: dict[str, int] = {}
    masses: list[float] = []
    points: list[tuple[float, float, float]] = []
    with Path(csv_path).open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.reader(stream)
        header: list[str] | None = None
        for row in reader:
            if row and row[0].strip() == "Pos.x [m]":
                header = [item.strip() for item in row]
                break
        if header is None:
            raise ValueError("PartVTK particle header not found")
        index = {name: header.index(name) for name in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Mass [kg]", "Type", "Mk")}
        for row in reader:
            if len(row) <= max(index.values()):
                continue
            try:
                point = tuple(round(float(row[index[f"Pos.{axis} [m]"]]), 7) for axis in "xyz")
                particle_type = int(float(row[index["Type"]]))
                mk = int(float(row[index["Mk"]]))
                mass = float(row[index["Mass [kg]"]])
            except (ValueError, TypeError):
                continue
            type_counts[str(particle_type)] = type_counts.get(str(particle_type), 0) + 1
            mk_counts[str(mk)] = mk_counts.get(str(mk), 0) + 1
            if particle_type == 3:
                fluid.add(point)
                points.append(point)
                masses.append(mass)
            else:
                boundary.add(point)
    if not fluid:
        raise ValueError("PartVTK CSV contains no type=3 particles")
    axes = [sorted({point[i] for point in fluid}) for i in range(3)]
    overlap = fluid.intersection(boundary)
    return {
        "total_rows": sum(type_counts.values()),
        "type_counts": type_counts,
        "mk_counts": mk_counts,
        "fluid_count": len(fluid),
        "fluid_mass_kg": sum(masses),
        "mass_per_particle_kg": sorted({round(value, 12) for value in masses}),
        "fluid_axis_counts_xyz": [len(axis) for axis in axes],
        "fluid_bounds_m": {"min": [min(point[i] for point in points) for i in range(3)], "max": [max(point[i] for point in points) for i in range(3)]},
        "exact_fluid_boundary_coordinate_overlap_count": len(overlap),
        "overlap_examples": [list(point) for point in sorted(overlap)[:12]],
    }


def _finite_boundary_contract(generated_xml: Path, case_id: str) -> dict[str, Any]:
    """Check the generated XML still contains every finite source component.

    The generated XML is the native GenCase product used by PartVTK.  These
    marker and typed-mk checks make the finite wall, bed, and prescribed
    piston evidence refer to the actual generated input rather than only the
    source definition.
    """
    text = Path(generated_xml).read_text(encoding="utf-8", errors="replace")
    markers = {
        "tank_floor": "tank_floor" in text,
        "finite_sidewall_left": "finite_sidewall_left" in text,
        "finite_sidewall_right": "finite_sidewall_right" in text,
        "prescribed_piston": "prescribed_piston" in text,
        "finite_bed_stl": "drawfilestl file=\"assets/f5_continuous_bed_profile_slope_0p280.stl\"" in text,
    }
    expected_mk = {1, 20, 40, 50}
    if "WEIR" in case_id:
        expected_mk.add(60)
    return {
        "required_markers": markers,
        "all_required_geometry_markers": all(markers.values()),
        "expected_generated_mk_ids": sorted(expected_mk),
    }


def audit(generated_bi4: Path, generated_xml: Path, output: Path, csv_output: Path) -> dict[str, Any]:
    generated_bi4 = Path(generated_bi4).resolve()
    generated_xml = Path(generated_xml).resolve()
    output = Path(output).resolve()
    csv_output = Path(csv_output).resolve()
    if output.exists() or csv_output.exists():
        raise FileExistsError("audit refuses to overwrite an existing output")
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(PARTVTK.parent) + ":" + env.get("LD_LIBRARY_PATH", "")
    command = [str(PARTVTK), "-filedata", str(generated_bi4), "-filexml", str(generated_xml), "-threads:4", "-savecsv", str(csv_output), "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1"]
    process = subprocess.run(command, cwd=generated_bi4.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=540, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"official PartVTK failed ({process.returncode}): {process.stdout[-2000:]}")
    parsed = parse_partvtk_csv(csv_output)
    root = ET.parse(generated_xml).getroot()
    data2d = root.find(".//constants/data2d")
    constants = root.find(".//constants")
    massfluid_node = constants.find("massfluid") if constants is not None else None
    massfluid = float(massfluid_node.attrib["value"]) if massfluid_node is not None else None
    fixed_nodes = root.findall(".//particles/fixed")
    moving_nodes = root.findall(".//particles/moving")
    expected = lattice()
    bound = parsed["fluid_bounds_m"]
    high = [FLUID_LOW[i] + FLUID_SIZE[i] for i in range(3)]
    inside = all(FLUID_LOW[i] - 1e-7 <= bound["min"][i] <= bound["max"][i] <= high[i] + 1e-7 for i in range(3))
    expected_phase = {
        "min": expected["expected_generated_phase_first_m"],
        "max": expected["expected_generated_phase_last_m"],
    }
    phase_bounds_match = all(
        abs(bound["min"][axis] - expected_phase["min"][axis]) <= 1e-7
        and abs(bound["max"][axis] - expected_phase["max"][axis]) <= 1e-7
        for axis in range(3)
    )
    boundary_contract = _finite_boundary_contract(generated_xml, generated_xml.stem)
    mk_ids = {int(value) for value, count in parsed["mk_counts"].items() if count > 0}
    typed_ids = all(parsed["type_counts"].get(str(value), 0) > 0 for value in (0, 1, 3))
    generated_fixed = [node for node in fixed_nodes if int(node.attrib.get("count", "0")) > 0]
    generated_moving = [node for node in moving_nodes if int(node.attrib.get("count", "0")) > 0]
    checks = {
        "official_partvtk_completed": True,
        "solver_dimension_3d": data2d is not None and data2d.attrib.get("value", "true").lower() == "false",
        "positive_fluid": parsed["fluid_count"] > 0,
        "exact_commensurate_fluid_count": parsed["fluid_count"] == expected["particle_count"],
        "exact_axis_counts": parsed["fluid_axis_counts_xyz"] == expected["counts_xyz"],
        "exact_phase_aligned_fluid_bounds": phase_bounds_match,
        "fluid_inside_registered_continuum_box": inside,
        "zero_fluid_boundary_overlap": parsed["exact_fluid_boundary_coordinate_overlap_count"] == 0,
        "typed_fixed_moving_fluid_ids": typed_ids,
        "finite_fixed_boundary": bool(generated_fixed),
        "finite_moving_control": bool(generated_moving),
        "complete_finite_geometry_markers": boundary_contract["all_required_geometry_markers"],
        "complete_finite_typed_mk_ids": set(boundary_contract["expected_generated_mk_ids"]).issubset(mk_ids),
        "native_mass_per_particle_is_rho_dp3": massfluid is not None and abs(massfluid - RHO0 * DP**3) < 1e-12,
        "frozen_one_percent_mass_budget": abs(parsed["fluid_mass_kg"] / 2352.0 - 1.0) <= MASS_BUDGET,
    }
    report = {
        "schema": "ds-data-02.f5.initialization-repair-partvtk-audit.v2",
        "created_at_utc": utc_now(),
        "family_id": "F5",
            "repair_scope": SCOPE,
        "status": "actual_partvtk_audit_complete_pending_root_review",
        "generated_bi4": bind(generated_bi4, "new completed GenCase BI4"),
        "generated_xml": bind(generated_xml, "new completed GenCase XML"),
        "partvtk_csv": bind(csv_output, "new official PartVTK initial frame"),
        "registered_continuum": {"low_m": list(FLUID_LOW), "size_m": list(FLUID_SIZE), "mass_kg": 2352.0, "rho0_kg_m3": RHO0},
        "expected_lattice": expected,
        "observed": parsed,
        "finite_boundary_contract": boundary_contract,
        "expected_phase_bounds_m": expected_phase,
        "generated_xml_massfluid_kg": massfluid,
        "checks": checks,
        "all_static_and_actual_checks": all(checks.values()),
        "q_n_status": "pending_root_review; this report is initial-state evidence only",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    write_json(output, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("gencase-requests")
    request = sub.add_parser("partvtk-requests")
    request.add_argument("--runup-receipt", type=Path, required=True)
    request.add_argument("--weir-receipt", type=Path, required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--generated-bi4", type=Path, required=True)
    audit_parser.add_argument("--generated-xml", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    audit_parser.add_argument("--csv-output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare()
    elif args.command == "gencase-requests":
        result = write_gencase_requests()
    elif args.command == "partvtk-requests":
        result = write_partvtk_requests({"runup_return": args.runup_receipt, "weir_pair": args.weir_receipt})
    else:
        result = audit(args.generated_bi4, args.generated_xml, args.output, args.csv_output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
