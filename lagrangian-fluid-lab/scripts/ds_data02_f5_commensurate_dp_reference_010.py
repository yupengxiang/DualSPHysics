#!/usr/bin/env python3
"""F5 additive commensurate DP=.05/.0125 GenCase and finite-input audits.

This scope keeps the registered F5 continuous fluid box, density, piston
files, bed STL, finite walls, weir and event window byte-bound to the existing
medium physical mothers.  It creates two numerical resolution views from each
background by replacing only the void fluid fill with an explicit cell-centre
drawbox and setting the corresponding ``definition dp``/point reference.

The module only prepares definitions, shared-runtime CPU requests, and
read-only audits.  It never starts GenCase, PartVTK, DualSPHysics, or a GPU.
Every generated product is outside the worktree under the DS-DATA-02 data
root, and every later audit is bound to the immutable GenCase receipt and
generated XML/BI4 hashes.
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
import xml.etree.ElementTree as ET
from typing import Any, Mapping


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
WORKTREE_ROOT = SCRIPT.parents[2]
FAMILY_ROOT = LAB_ROOT / "campaigns/ds-data-02/families/F5"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
RAW_OUTPUT_ROOT = DATA_ROOT / "case/attempt"
RUNNER_V2 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
)
PYTHON_VENV = RUNNER_V2.parents[1] / ".venv/bin/python"
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
PARTVTK = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
)

SCOPE = "F5_CONTINUOUS_CELL_CENTRE_COMMENSURATE_DP005_DP00125_010"
REPAIR_ROOT = FAMILY_ROOT / "initialization_repairs" / SCOPE
RHO0 = 1000.0
FLUID_LOW = (-0.90, -0.70, 0.02)
FLUID_SIZE = (4.20, 1.40, 0.40)
CONTINUUM_VOLUME = math.prod(FLUID_SIZE)
CONTINUUM_MASS = CONTINUUM_VOLUME * RHO0
MASS_BUDGET_FRACTION = 0.01
EVENT_WINDOW_S = 16.0
INDEX_TOLERANCE_M = 2.0e-7

DP_SPECS: dict[str, dict[str, Any]] = {
    "dp005": {"label": "DP005", "dp_m": 0.05, "max_wall_seconds": 600},
    "dp00125": {"label": "DP00125", "dp_m": 0.0125, "max_wall_seconds": 5400},
}
CASE_SPECS: dict[str, dict[str, Any]] = {
    "runup_dp005": {
        "mechanism_id": "runup_return",
        "resolution_id": "dp005",
        "source_definition": "F5_REF_RUNUP_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_RUNUP_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_f91973457a049db5_regular_piston.dat",
        "case_id": "F5_REF_RUNUP_NOMINAL_DP005_CELL_CENTRE_010",
    },
    "weir_dp005": {
        "mechanism_id": "weir_pair",
        "resolution_id": "dp005",
        "source_definition": "F5_REF_WEIR_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_WEIR_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_4c73cd98b7230035_regular_piston.dat",
        "case_id": "F5_REF_WEIR_NOMINAL_DP005_CELL_CENTRE_010",
    },
    "runup_dp00125": {
        "mechanism_id": "runup_return",
        "resolution_id": "dp00125",
        "source_definition": "F5_REF_RUNUP_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_RUNUP_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_f91973457a049db5_regular_piston.dat",
        "case_id": "F5_REF_RUNUP_NOMINAL_DP00125_CELL_CENTRE_010",
    },
    "weir_dp00125": {
        "mechanism_id": "weir_pair",
        "resolution_id": "dp00125",
        "source_definition": "F5_REF_WEIR_NOMINAL_MEDIUM.xml",
        "source_metadata": "F5_REF_WEIR_NOMINAL_MEDIUM.metadata.json",
        "motion": "piston_4c73cd98b7230035_regular_piston.dat",
        "case_id": "F5_REF_WEIR_NOMINAL_DP00125_CELL_CENTRE_010",
    },
}

SOURCE_BED = FAMILY_ROOT / "definitions/assets/f5_continuous_bed_profile_slope_0p280.stl"
QUALITY_CONTRACT = FAMILY_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = FAMILY_ROOT / "event_definitions.json"
SAVE_PLAN = FAMILY_ROOT / "integration_save_plan.json"
FAMILY_CARD = FAMILY_ROOT / "family_card.json"
REFERENCE_MATRIX = FAMILY_ROOT / "definitions/reference_matrix.json"
HISTORY_REUSE = FAMILY_ROOT / "history_reuse_inventory.json"
FAMILY_HANDOFF = FAMILY_ROOT / "FAMILY_HANDOFF.md"
V7_SCOPE = FAMILY_ROOT / "initialization_repairs/F5_CONTINUOUS_CELL_CENTRE_PHASE_EXACT_DP025_007"

OLD_FILL = re.compile(
    r'<fillbox x="2" y="0\.18" z="0\.10">\s*'
    r'<modefill>void</modefill>\s*'
    r'<point x="-0\.90" y="-0\.70" z="0\.02" />\s*'
    r'<size x="4\.20" y="1\.40" z="0\.4" />\s*'
    r'</fillbox>',
    re.DOTALL,
)
NEW_FILL = re.compile(
    r'<drawbox cmt="initial_fluid_cell_centres_commensurate_[^"]+">\s*'
    r'<boxfill>solid</boxfill>\s*<point [^>]*/>\s*<size [^>]*/>\s*'
    r'</drawbox>',
    re.DOTALL,
)
POINTREF = re.compile(r'<pointref x="[^"]+" y="[^"]+" z="[^"]+"\s*/>')
DEFINITION_DP = re.compile(r'(<definition\s+dp=")[^"]+("\s*>)')


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
    if path.exists():
        raise FileExistsError(f"refusing to overwrite additive F5 artifact: {path}")
    partial = path.with_name(path.name + f".{os.getpid()}.partial")
    partial.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def git_head() -> str:
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
    return f"{float(value):.12f}".rstrip("0").rstrip(".") or "0"


def _source(spec: Mapping[str, Any]) -> dict[str, Path]:
    return {
        "definition": FAMILY_ROOT / "definitions" / str(spec["source_definition"]),
        "metadata": FAMILY_ROOT / "definitions" / str(spec["source_metadata"]),
        "motion": FAMILY_ROOT / "definitions" / str(spec["motion"]),
    }


def lattice(dp: float) -> dict[str, Any]:
    dp = float(dp)
    counts = tuple(int(round(size / dp)) for size in FLUID_SIZE)
    if any(not math.isclose(size, count * dp, rel_tol=0.0, abs_tol=1.0e-12) for size, count in zip(FLUID_SIZE, counts)):
        raise ValueError(f"uncommensurate registered box for dp={dp}")
    first = tuple(low + dp / 2.0 for low in FLUID_LOW)
    last = tuple(first[axis] + (counts[axis] - 1) * dp for axis in range(3))
    # GenCase pointref is an arbitrary lattice origin.  Use the positive
    # residue of the requested first center so every center is an integer
    # multiple of dp away from that origin, including the z=.02 plane.
    pointref = tuple(
        (center - math.floor(center / dp) * dp) % dp for center in first
    )
    pointref = tuple(0.0 if math.isclose(value, dp, abs_tol=1.0e-12) else value for value in pointref)
    draw_size = tuple((count - 1) * dp for count in counts)
    particle_count = math.prod(counts)
    lattice_volume = particle_count * dp**3
    return {
        "rule": "explicit solid cell-centre lattice; first=low+dp/2; integer index=(center-pointref)/dp",
        "dp_m": dp,
        "counts_xyz": list(counts),
        "particle_count": particle_count,
        "continuous_low_m": list(FLUID_LOW),
        "continuous_size_m": list(FLUID_SIZE),
        "continuous_high_m": [FLUID_LOW[i] + FLUID_SIZE[i] for i in range(3)],
        "first_center_m": list(first),
        "last_center_m": list(last),
        "pointref_m": list(pointref),
        "draw_size_m": list(draw_size),
        "continuous_volume_m3": CONTINUUM_VOLUME,
        "lattice_volume_m3": lattice_volume,
        "continuous_mass_kg": CONTINUUM_MASS,
        "native_lattice_mass_kg": lattice_volume * RHO0,
        "particle_mass_kg": RHO0 * dp**3,
        "relative_mass_error": lattice_volume / CONTINUUM_VOLUME - 1.0,
        "mass_budget_fraction": MASS_BUDGET_FRACTION,
        "mass_budget_pass": abs(lattice_volume / CONTINUUM_VOLUME - 1.0) <= MASS_BUDGET_FRACTION,
        "mass_rescaling": False,
        "phase_formula": "low + 0.5*dp + index*dp",
        "pointref_formula": "positive residue of first_center modulo dp",
    }


def _fluid_block(dp: float, label: str) -> str:
    data = lattice(dp)
    p = data["first_center_m"]
    size = data["draw_size_m"]
    return "\n".join(
        [
            f'          <drawbox cmt="initial_fluid_cell_centres_commensurate_{label}">',
            "            <boxfill>solid</boxfill>",
            f'            <point x="{q(p[0])}" y="{q(p[1])}" z="{q(p[2])}" />',
            f'            <size x="{q(size[0])}" y="{q(size[1])}" z="{q(size[2])}" />',
            "          </drawbox>",
        ]
    )


def _pointref_block(dp: float) -> str:
    p = lattice(dp)["pointref_m"]
    return f'<pointref x="{q(p[0])}" y="{q(p[1])}" z="{q(p[2])}" />'


def canonical_source(text: str) -> str:
    """Normalize only the intended numerical fluid edits for equivalence."""
    text = DEFINITION_DP.sub(r'\1<F5_DP>\2', text, count=1)
    text = OLD_FILL.sub("<F5_INITIAL_FLUID_PRIMITIVE>", text, count=1)
    text = NEW_FILL.sub("<F5_INITIAL_FLUID_PRIMITIVE>", text, count=1)
    text = POINTREF.sub("<F5_INITIAL_POINTREF />", text, count=1)
    text = re.sub(r"[ \t]*<F5_INITIAL_FLUID_PRIMITIVE>", "<F5_INITIAL_FLUID_PRIMITIVE>", text)
    text = re.sub(r"[ \t]*<F5_INITIAL_POINTREF\s*/>", "<F5_INITIAL_POINTREF />", text)
    return text


def rewrite_definition(source: Path, target: Path, dp: float, label: str) -> dict[str, Any]:
    source = Path(source).resolve()
    original = source.read_text(encoding="utf-8")
    if len(DEFINITION_DP.findall(original)) != 1:
        raise ValueError(f"expected one definition dp in {source}")
    if len(OLD_FILL.findall(original)) != 1:
        raise ValueError(f"expected one registered void fillbox in {source}")
    if len(POINTREF.findall(original)) != 1:
        raise ValueError(f"expected one pointref in {source}")
    repaired = DEFINITION_DP.sub(lambda m: f'{m.group(1)}{q(dp)}{m.group(2)}', original, count=1)
    repaired = OLD_FILL.sub(lambda _m: _fluid_block(dp, label), repaired, count=1)
    repaired = POINTREF.sub(lambda _m: _pointref_block(dp), repaired, count=1)
    ET.fromstring(repaired)
    if canonical_source(original) != canonical_source(repaired):
        raise AssertionError("DP reference rewrite changed geometry/control outside registered fluid edits")
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)
    target.write_text(repaired, encoding="utf-8")
    return {
        "source": bind(source, "immutable F5 medium physical mother XML"),
        "repair": bind(target, "new commensurate cell-centre definition"),
        "replacement_count": 1,
        "pointref_replacement_count": 1,
        "definition_dp_replacement_count": 1,
        "canonical_source_equivalence": True,
        "semantic_change": "only definition dp, pointref lattice origin, and void fluid primitive changed; physical geometry/control/domain remain source-equivalent",
    }


def _case_dir(key: str) -> Path:
    return REPAIR_ROOT / key


def _source_inputs() -> list[Path]:
    return [
        SCRIPT,
        RUNNER_V2,
        FAMILY_HANDOFF,
        FAMILY_CARD,
        HISTORY_REUSE,
        REFERENCE_MATRIX,
        QUALITY_CONTRACT,
        EVENT_DEFINITIONS,
        SAVE_PLAN,
        SOURCE_BED,
        FAMILY_ROOT / "definitions/control_regular_piston.dat",
        FAMILY_ROOT / "definitions/control_single_packet.dat",
        V7_SCOPE / "actual_preflight_evidence_007.json",
        V7_SCOPE / "native_reference_009/native_reference_preflight_009.json",
    ]


def _write_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256(source) != sha256(target):
            raise FileExistsError(f"existing staged copy differs: {target}")
        return
    shutil.copy2(source, target)


def prepare() -> dict[str, Any]:
    REPAIR_ROOT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for key, spec in CASE_SPECS.items():
        source = _source(spec)
        dp_spec = DP_SPECS[str(spec["resolution_id"])]
        dp = float(dp_spec["dp_m"])
        case_dir = _case_dir(key)
        assets = case_dir / "assets"
        definition = case_dir / f'{spec["case_id"]}.xml'
        staged_motion = case_dir / str(spec["motion"])
        staged_bed = assets / SOURCE_BED.name
        rewrite = rewrite_definition(source["definition"], definition, dp, str(dp_spec["label"]))
        _write_copy(source["motion"], staged_motion)
        _write_copy(SOURCE_BED, staged_bed)
        data = lattice(dp)
        source_text = source["definition"].read_text(encoding="utf-8")
        repair_text = definition.read_text(encoding="utf-8")
        metadata = {
            "schema": "ds-data-02.f5.commensurate-dp-reference-metadata.v1",
            "family_id": "F5",
            "scope": SCOPE,
            "case_key": key,
            "case_id": spec["case_id"],
            "mechanism_id": spec["mechanism_id"],
            "resolution_id": spec["resolution_id"],
            "producer_script": bind(SCRIPT, "committed additive DP producer"),
            "producer_git_commit": git_head(),
            "source_definition": bind(source["definition"], "immutable physical mother XML"),
            "source_metadata": bind(source["metadata"], "immutable physical mother metadata"),
            "source_motion": bind(source["motion"], "immutable piston control"),
            "source_bed": bind(SOURCE_BED, "immutable finite bed STL"),
            "repair_definition": bind(definition, "new DP cell-centre XML"),
            "repair_motion": bind(staged_motion, "co-located byte-identical piston control"),
            "repair_bed": bind(staged_bed, "co-located byte-identical finite bed STL"),
            "lattice": data,
            "physical_contract": {
                "continuous_low_m": list(FLUID_LOW),
                "continuous_size_m": list(FLUID_SIZE),
                "continuous_high_m": data["continuous_high_m"],
                "density_kg_m3": RHO0,
                "continuum_mass_kg": CONTINUUM_MASS,
                "mass_denominator_unchanged": True,
                "finite_bed_walls_weir_and_piston_unchanged": True,
                "controls_unchanged": True,
                "event_window_s": EVENT_WINDOW_S,
                "mass_rescaling": False,
            },
            "source_equivalence": {
                "canonical_source_sha256": hashlib.sha256(canonical_source(source_text).encode()).hexdigest(),
                "canonical_repair_sha256": hashlib.sha256(canonical_source(repair_text).encode()).hexdigest(),
                "canonical_equal": canonical_source(source_text) == canonical_source(repair_text),
                "allowed_changes": ["definition dp", "pointref lattice origin", "void fluid primitive"],
                "geometry_control_domain_preserved": True,
                "motion_bytes_preserved": sha256(source["motion"]) == sha256(staged_motion),
                "bed_bytes_preserved": sha256(SOURCE_BED) == sha256(staged_bed),
            },
            "rewrite": rewrite,
            "quality_status": "pending_shared_v2_gencase_and_finite_partvtk_qa",
            "qualification_claim": "none",
            "production_claim": "none",
            "created_at_utc": utc_now(),
        }
        metadata_path = case_dir / "commensurate-dp-metadata-010.json"
        if not metadata_path.exists():
            write_json(metadata_path, metadata)
        preflight = {
            "schema": "ds-data-02.f5.commensurate-dp-static-preflight.v1",
            "family_id": "F5",
            "scope": SCOPE,
            "case_key": key,
            "case_id": spec["case_id"],
            "mechanism_id": spec["mechanism_id"],
            "resolution_id": spec["resolution_id"],
            "status": "static_pass_pending_actual_gencase",
            "producer_script": bind(SCRIPT, "committed additive DP producer"),
            "source_hashes": {
                "definition": bind(source["definition"], "immutable physical mother XML"),
                "metadata": bind(source["metadata"], "immutable physical mother metadata"),
                "motion": bind(source["motion"], "immutable control"),
                "bed": bind(SOURCE_BED, "immutable finite bed STL"),
            },
            "static_checks": {
                "repair_xml_well_formed": ET.parse(definition).getroot().tag == "case",
                "source_canonical_equivalence": metadata["source_equivalence"]["canonical_equal"],
                "only_registered_dp_fluid_pointref_changes": True,
                "exact_commensurate_counts": data["particle_count"] == math.prod(int(round(size / dp)) for size in FLUID_SIZE),
                "expected_3d": all(count > 1 for count in data["counts_xyz"]),
                "exact_continuum_mass_without_rescaling": abs(data["native_lattice_mass_kg"] - CONTINUUM_MASS) < 1.0e-9,
                "one_percent_mass_budget": data["mass_budget_pass"],
                "fluid_centres_strictly_inside_continuum": all(
                    FLUID_LOW[i] < data["first_center_m"][i] <= data["last_center_m"][i] < data["continuous_high_m"][i]
                    for i in range(3)
                ),
                "finite_source_markers_present": all(
                    marker in source_text
                    for marker in ("tank_floor", "finite_sidewall_left", "finite_sidewall_right", "prescribed_piston", "drawfilestl")
                ),
                "weir_source_preserved_for_weir": spec["mechanism_id"] != "weir_pair" or all(
                    marker in source_text for marker in ("weir_left_side_segment", "weir_right_side_segment")
                ),
                "motion_and_bed_staged_byte_identical": metadata["source_equivalence"]["motion_bytes_preserved"] and metadata["source_equivalence"]["bed_bytes_preserved"],
                "same_event_window": EVENT_WINDOW_S == 16.0,
                "no_solver_or_gpu": True,
            },
            "expected_lattice": data,
            "finite_qa_required": [
                "actual GenCase receipt total/fluid counts and solver dimension",
                "generated XML massfluid and physical marker preservation",
                "official PartVTK type=3 grid/mass/bounds and fixed/moving finite-face ledger",
                "bed STL and weir union coverage where boundary markers overlap",
            ],
            "qualification_claim": "none",
            "production_claim": "none",
        }
        preflight_path = case_dir / "commensurate-dp-static-preflight-010.json"
        if not preflight_path.exists():
            write_json(preflight_path, preflight)
        results[key] = {
            "case_dir": str(case_dir),
            "definition": str(definition),
            "metadata": str(metadata_path),
            "preflight": str(preflight_path),
            "lattice": data,
        }
    return {"schema": "ds-data-02.f5.commensurate-dp-prepare.v1", "scope": SCOPE, "cases": results, "git_commit": git_head()}


def _request_inputs(key: str, spec: Mapping[str, Any], definition: Path, motion: Path, bed: Path, metadata: Path, preflight: Path) -> list[str]:
    source = _source(spec)
    paths = _source_inputs() + [source["definition"], source["metadata"], source["motion"], definition, motion, bed, metadata, preflight]
    return [str(Path(path).resolve()) for path in paths]


def write_gencase_requests() -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for key, spec in CASE_SPECS.items():
        source = _source(spec)
        dp_spec = DP_SPECS[str(spec["resolution_id"])]
        case_dir = _case_dir(key)
        definition = case_dir / f'{spec["case_id"]}.xml'
        motion = case_dir / str(spec["motion"])
        bed = case_dir / "assets" / SOURCE_BED.name
        metadata = case_dir / "commensurate-dp-metadata-010.json"
        preflight = case_dir / "commensurate-dp-static-preflight-010.json"
        required = [source["definition"], source["metadata"], source["motion"], definition, motion, bed, metadata, preflight]
        if not all(path.is_file() for path in required):
            missing = next(path for path in required if not path.is_file())
            raise FileNotFoundError(missing)
        data = lattice(float(dp_spec["dp_m"]))
        particle_count = int(data["particle_count"])
        estimated_storage = max(512 * 1024 * 1024, particle_count * 256 + 512 * 1024 * 1024)
        request = {
            "schema": "ds-data-02.runner.request.v2",
            "family_id": "F5",
            "case_id": spec["case_id"],
            "attempt_id": f'gencase-f5-{spec["mechanism_id"]}-{dp_spec["label"].lower()}-cellcentre-commensurate-010',
            "kind": "cpu",
            "cpu_task_kind": "gencase",
            "command": [str(GENCASE), str(definition.with_suffix("")), f'{{attempt_root}}/{spec["case_id"]}', "-save:all"],
            "cwd": str(case_dir),
            "max_wall_seconds": int(dp_spec["max_wall_seconds"]),
            "cpu_threads": 4,
            "estimated_storage_bytes": estimated_storage,
            "input_files": _request_inputs(key, spec, definition, motion, bed, metadata, preflight),
            "worktree_root": str(WORKTREE_ROOT),
            "launch_commit": git_head(),
            "runner_v2": bind(RUNNER_V2, "shared CPU runner v2"),
            "source_definition_hash_bound": bind(source["definition"], "immutable physical mother XML"),
            "source_metadata_hash_bound": bind(source["metadata"], "immutable physical mother metadata"),
            "source_motion_hash_bound": bind(source["motion"], "immutable piston control"),
            "source_bed_hash_bound": bind(SOURCE_BED, "immutable finite bed STL"),
            "repair_definition_hash_bound": bind(definition, "new commensurate DP definition"),
            "repair_motion_hash_bound": bind(motion, "co-located byte-identical piston control"),
            "repair_bed_hash_bound": bind(bed, "co-located byte-identical finite bed STL"),
            "source_mother": spec["mechanism_id"],
            "resolution_id": spec["resolution_id"],
            "scope": SCOPE,
            "registered_continuum": {
                "low_m": list(FLUID_LOW),
                "size_m": list(FLUID_SIZE),
                "density_kg_m3": RHO0,
                "mass_kg": CONTINUUM_MASS,
                "denominator_unchanged": True,
            },
            "expected_cell_centre_lattice": data,
            "event_window_s": EVENT_WINDOW_S,
            "generation_status": "new_commensurate_DP_preflight_pending_shared_v2_gencase",
            "solver_launch_forbidden": True,
            "q_n_status": "pending_actual_gencase_and_finite_partvtk_qa; no qualification claim",
            "qualification_claim": "none",
            "production_claim": "none",
            "raw_output_root": str(RAW_OUTPUT_ROOT),
            "request_note": "CPU GenCase only through ds_data02_runtime_v2.py; no solver or GPU launch; preserve all source bytes and continuous mass denominator.",
        }
        path = case_dir / "gencase-request-010.json"
        if not path.exists():
            write_json(path, request)
        request["path"] = str(path)
        request["sha256"] = sha256(path)
        requests.append(request)
    return requests


def _receipt_contract(receipt_path: Path, key: str) -> dict[str, Any]:
    receipt_path = Path(receipt_path).resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "completed" or int(receipt.get("returncode", 1)) != 0:
        raise ValueError(f"GenCase receipt is not successful: {receipt_path}")
    spec = CASE_SPECS[key]
    data = lattice(float(DP_SPECS[str(spec["resolution_id"])] ["dp_m"]))
    if int(receipt.get("fluid_particles", 0)) != data["particle_count"]:
        raise ValueError(f"fluid particle count mismatch in {receipt_path}: {receipt.get('fluid_particles')} != {data['particle_count']}")
    if int(receipt.get("solver_dimension_from_gencase", 0)) != 3:
        raise ValueError(f"GenCase is not 3-D: {receipt_path}")
    output_root = Path(str(receipt["output_root"])).resolve()
    prefix = output_root / str(spec["case_id"])
    generated_xml = prefix.with_suffix(".xml")
    generated_bi4 = prefix.with_suffix(".bi4")
    if not generated_xml.is_file() or not generated_bi4.is_file():
        raise FileNotFoundError(f"generated prefix incomplete: {prefix}")
    return {
        "receipt": receipt,
        "receipt_path": str(receipt_path),
        "generated_xml": str(generated_xml),
        "generated_bi4": str(generated_bi4),
        "expected_lattice": data,
    }


def audit_gencase(receipts: Mapping[str, Path], output: Path) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for key, receipt_path in receipts.items():
        info = _receipt_contract(Path(receipt_path), key)
        xml_path = Path(info["generated_xml"])
        root = ET.parse(xml_path).getroot()
        constants = root.find(".//constants")
        mass_node = constants.find("massfluid") if constants is not None else None
        massfluid = float(mass_node.attrib["value"]) if mass_node is not None else None
        data = info["expected_lattice"]
        text = xml_path.read_text(encoding="utf-8", errors="replace")
        checks = {
            "receipt_completed": True,
            "positive_3d_fluid": int(info["receipt"].get("fluid_particles", 0)) > 0,
            "exact_fluid_count": int(info["receipt"].get("fluid_particles", 0)) == data["particle_count"],
            "solver_dimension_3": int(info["receipt"].get("solver_dimension_from_gencase", 0)) == 3,
            "generated_xml_well_formed": root.tag == "case",
            "generated_xml_data2d_false": (root.find(".//constants/data2d") is not None and root.find(".//constants/data2d").attrib.get("value", "true").lower() == "false"),
            "generated_massfluid_matches_rho_dp3": massfluid is not None and math.isclose(massfluid, data["particle_mass_kg"], rel_tol=0.0, abs_tol=1.0e-10),
            "fluid_mass_contract": math.isclose(data["native_lattice_mass_kg"], CONTINUUM_MASS, rel_tol=0.0, abs_tol=1.0e-9),
            "finite_geometry_markers_present": all(marker in text for marker in ("tank_floor", "finite_sidewall_left", "finite_sidewall_right", "prescribed_piston", "drawfilestl")),
            "weir_markers_present": "weir_pair" not in key or all(marker in text for marker in ("weir_left_side_segment", "weir_right_side_segment")),
            "generated_bi4_positive": Path(info["generated_bi4"]).stat().st_size > 0,
        }
        rows[key] = {
            "case_id": CASE_SPECS[key]["case_id"],
            "resolution_id": CASE_SPECS[key]["resolution_id"],
            "receipt": bind(Path(info["receipt_path"]), "actual shared-v2 GenCase receipt"),
            "generated_xml": bind(xml_path, "actual generated XML"),
            "generated_bi4": bind(Path(info["generated_bi4"]), "actual generated BI4"),
            "actual_receipt_fields": {k: info["receipt"].get(k) for k in ("status", "returncode", "total_particles", "fluid_particles", "solver_dimension_from_gencase", "output_root")},
            "massfluid_kg": massfluid,
            "expected_lattice": data,
            "checks": checks,
            "actual_gencase_pass": all(checks.values()),
            "q_n_status": "pending_actual_partvtk_finite_face_and_stl_union_audit",
            "qualification_claim": "none",
            "production_claim": "none",
        }
    report = {
        "schema": "ds-data-02.f5.commensurate-dp-gencase-audit.v1",
        "created_at_utc": utc_now(),
        "family_id": "F5",
        "scope": SCOPE,
        "producer_script": bind(SCRIPT, "committed additive DP producer"),
        "cases": rows,
        "all_actual_gencase_checks_pass": bool(rows) and all(row["actual_gencase_pass"] for row in rows.values()),
        "qualification_claim": "none",
        "production_claim": "none",
    }
    write_json(Path(output), report)
    return report


def write_partvtk_requests(receipts: Mapping[str, Path]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for key, receipt_path in receipts.items():
        info = _receipt_contract(Path(receipt_path), key)
        spec = CASE_SPECS[key]
        case_dir = _case_dir(key)
        metadata = case_dir / "commensurate-dp-metadata-010.json"
        preflight = case_dir / "commensurate-dp-static-preflight-010.json"
        gencase_request = case_dir / "gencase-request-010.json"
        output = case_dir / "partvtk-audit-request-010.json"
        request = {
            "schema": "ds-data-02.runner.request.v2",
            "family_id": "F5",
            "case_id": spec["case_id"],
            "attempt_id": f'audit-f5-{spec["mechanism_id"]}-{DP_SPECS[str(spec["resolution_id"])] ["label"].lower()}-cellcentre-010',
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "command": [
                str(PYTHON_VENV), str(SCRIPT), "audit-partvtk",
                "--generated-bi4", info["generated_bi4"],
                "--generated-xml", info["generated_xml"],
                "--output", "{attempt_root}/partvtk-audit-010.json",
                "--csv-output", "{attempt_root}/partvtk-initial-010.csv",
            ],
            "cwd": str(case_dir),
            "max_wall_seconds": 1800 if spec["resolution_id"] == "dp005" else 5400,
            "cpu_threads": 4,
            "estimated_storage_bytes": 2 * 1024**3 if spec["resolution_id"] == "dp005" else 6 * 1024**3,
            "input_files": [
                str(path.resolve()) for path in (
                    _source_inputs()
                    + [_source(spec)["definition"], _source(spec)["metadata"], _source(spec)["motion"],
                       case_dir / f'{spec["case_id"]}.xml', case_dir / str(spec["motion"]), case_dir / "assets" / SOURCE_BED.name,
                       metadata, preflight, gencase_request, Path(info["receipt_path"]), Path(info["generated_xml"]), Path(info["generated_bi4"])]
                )
            ],
            "worktree_root": str(WORKTREE_ROOT),
            "launch_commit": git_head(),
            "runner_v2": bind(RUNNER_V2, "shared CPU runner v2"),
            "gencase_receipt": bind(Path(info["receipt_path"]), "actual completed GenCase receipt"),
            "gencase_receipt_sha256": sha256(Path(info["receipt_path"])),
            "generated_xml_sha256": sha256(Path(info["generated_xml"])),
            "generated_bi4_sha256": sha256(Path(info["generated_bi4"])),
            "audit_scope": "official PartVTK initial frame; type=3 exact commensurate grid/mass/bounds; fixed/moving typed IDs; finite floor/walls/piston/weir and bed union evidence",
            "solver_launch_forbidden": True,
            "q_n_status": "pending_root_review; initial state and finite geometry evidence only",
            "qualification_claim": "none",
            "production_claim": "none",
            "request_note": "CPU PartVTK/finite audit only through shared v2; no solver/GPU.",
        }
        if not output.exists():
            write_json(output, request)
        request["path"] = str(output)
        request["sha256"] = sha256(output)
        requests.append(request)
    return requests


def _parse_partvtk_csv(path: Path, dp: float) -> dict[str, Any]:
    type_counts: dict[str, int] = {}
    mk_counts: dict[str, int] = {}
    fluid_count = 0
    fluid_mass = 0.0
    min_xyz = [math.inf, math.inf, math.inf]
    max_xyz = [-math.inf, -math.inf, -math.inf]
    observed: set[tuple[int, int, int]] = set()
    invalid = 0
    max_residual = [0.0, 0.0, 0.0]
    with Path(path).open(newline="", encoding="utf-8", errors="replace") as stream:
        reader = csv.reader(stream)
        header: list[str] | None = None
        for row in reader:
            if row and row[0].strip() == "Pos.x [m]":
                header = [item.strip() for item in row]
                break
        if header is None:
            raise ValueError(f"PartVTK header missing: {path}")
        wanted = {name: header.index(name) for name in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Mass [kg]", "Type", "Mk")}
        counts = [int(round(size / dp)) for size in FLUID_SIZE]
        for row in reader:
            if len(row) <= max(wanted.values()):
                continue
            try:
                xyz = [float(row[wanted[f"Pos.{axis} [m]"]]) for axis in "xyz"]
                mass = float(row[wanted["Mass [kg]"]])
                particle_type = int(float(row[wanted["Type"]]))
                mk = int(float(row[wanted["Mk"]]))
            except (TypeError, ValueError):
                continue
            type_counts[str(particle_type)] = type_counts.get(str(particle_type), 0) + 1
            mk_counts[str(mk)] = mk_counts.get(str(mk), 0) + 1
            if particle_type != 3:
                continue
            fluid_count += 1
            fluid_mass += mass
            for axis in range(3):
                min_xyz[axis] = min(min_xyz[axis], xyz[axis])
                max_xyz[axis] = max(max_xyz[axis], xyz[axis])
            index_tuple: list[int] = []
            okay = True
            for axis in range(3):
                raw = (xyz[axis] - FLUID_LOW[axis]) / dp - 0.5
                index = int(round(raw))
                expected = FLUID_LOW[axis] + dp / 2.0 + index * dp
                residual = abs(xyz[axis] - expected)
                max_residual[axis] = max(max_residual[axis], residual)
                if index < 0 or index >= counts[axis] or residual > INDEX_TOLERANCE_M:
                    okay = False
                index_tuple.append(index)
            if okay:
                observed.add(tuple(index_tuple))
            else:
                invalid += 1
    expected_count = math.prod(counts)
    expected_indices = {(ix, iy, iz) for ix in range(counts[0]) for iy in range(counts[1]) for iz in range(counts[2])}
    return {
        "type_counts": type_counts,
        "mk_counts": mk_counts,
        "fluid_count": fluid_count,
        "fluid_mass_kg": fluid_mass,
        "fluid_bounds_m": {"min": min_xyz, "max": max_xyz},
        "observed_grid_count": len(observed),
        "expected_grid_count": expected_count,
        "grid_missing_count": len(expected_indices - observed),
        "grid_extra_count": max(0, len(observed - expected_indices) + fluid_count - len(observed)),
        "invalid_fluid_coordinate_count": invalid,
        "max_center_residual_m_xyz": max_residual,
        "expected_axis_counts_xyz": counts,
    }


def audit_partvtk(generated_bi4: Path, generated_xml: Path, output: Path, csv_output: Path) -> dict[str, Any]:
    generated_bi4 = Path(generated_bi4).resolve()
    generated_xml = Path(generated_xml).resolve()
    output = Path(output).resolve()
    csv_output = Path(csv_output).resolve()
    if output.exists() or csv_output.exists():
        raise FileExistsError("refusing to overwrite additive PartVTK audit output")
    root = ET.parse(generated_xml).getroot()
    definition = root.find(".//definition")
    if definition is None:
        raise ValueError("generated XML has no definition")
    dp = float(definition.attrib["dp"])
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(PARTVTK.parent) + ":" + env.get("LD_LIBRARY_PATH", "")
    command = [str(PARTVTK), "-filedata", str(generated_bi4), "-filexml", str(generated_xml), "-threads:4", "-savecsv", str(csv_output), "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1"]
    process = subprocess.run(command, cwd=generated_bi4.parent, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5400, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"official PartVTK failed ({process.returncode}): {process.stdout[-2000:]}")
    parsed = _parse_partvtk_csv(csv_output, dp)
    expected = lattice(dp)
    text = generated_xml.read_text(encoding="utf-8", errors="replace")
    markers = {name: marker in text for name, marker in {
        "tank_floor": "tank_floor",
        "finite_sidewall_left": "finite_sidewall_left",
        "finite_sidewall_right": "finite_sidewall_right",
        "prescribed_piston": "prescribed_piston",
        "finite_bed_stl": 'drawfilestl file="assets/f5_continuous_bed_profile_slope_0p280.stl"',
    }.items()}
    if "weir" in generated_xml.stem.lower():
        markers["weir_left_side_segment"] = "weir_left_side_segment" in text
        markers["weir_right_side_segment"] = "weir_right_side_segment" in text
    constants = root.find(".//constants")
    mass_node = constants.find("massfluid") if constants is not None else None
    massfluid = float(mass_node.attrib["value"]) if mass_node is not None else None
    checks = {
        "official_partvtk_completed": True,
        "positive_fluid": parsed["fluid_count"] > 0,
        "exact_fluid_count": parsed["fluid_count"] == expected["particle_count"],
        "exact_axis_counts": parsed["expected_axis_counts_xyz"] == expected["counts_xyz"],
        "full_registered_grid": parsed["grid_missing_count"] == 0 and parsed["grid_extra_count"] == 0 and parsed["invalid_fluid_coordinate_count"] == 0,
        "center_residual_within_tolerance": max(parsed["max_center_residual_m_xyz"]) <= INDEX_TOLERANCE_M,
        "fluid_inside_continuum": all(FLUID_LOW[i] < parsed["fluid_bounds_m"]["min"][i] <= parsed["fluid_bounds_m"]["max"][i] < expected["continuous_high_m"][i] for i in range(3)),
        "massfluid_rho_dp3": massfluid is not None and math.isclose(massfluid, expected["particle_mass_kg"], rel_tol=0.0, abs_tol=1.0e-10),
        "fluid_mass_continuum": math.isclose(parsed["fluid_mass_kg"], CONTINUUM_MASS, rel_tol=0.0, abs_tol=1.0e-5),
        "finite_geometry_markers": all(markers.values()),
        "typed_fluid_fixed": parsed["type_counts"].get("3", 0) > 0 and parsed["type_counts"].get("0", 0) > 0,
        "actual_3d_xml": root.find(".//constants/data2d") is not None and root.find(".//constants/data2d").attrib.get("value", "true").lower() == "false",
    }
    report = {
        "schema": "ds-data-02.f5.commensurate-dp-partvtk-audit.v1",
        "created_at_utc": utc_now(),
        "family_id": "F5",
        "scope": SCOPE,
        "generated_bi4": bind(generated_bi4, "actual GenCase BI4"),
        "generated_xml": bind(generated_xml, "actual GenCase XML"),
        "partvtk_csv": bind(csv_output, "official PartVTK initial frame CSV"),
        "dp_m": dp,
        "expected_lattice": expected,
        "observed": parsed,
        "finite_geometry_markers": markers,
        "generated_massfluid_kg": massfluid,
        "checks": checks,
        "all_actual_checks_pass": all(checks.values()),
        "q_n_status": "pending_root_review; initial finite audit only",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    sub.add_parser("gencase-requests")
    audit_gc = sub.add_parser("audit-gencase")
    audit_gc.add_argument("--receipts", nargs="+", required=True, help="key=receipt.json entries")
    audit_gc.add_argument("--output", type=Path, required=True)
    req_pv = sub.add_parser("partvtk-requests")
    req_pv.add_argument("--receipts", nargs="+", required=True, help="key=receipt.json entries")
    audit_pv = sub.add_parser("audit-partvtk")
    audit_pv.add_argument("--generated-bi4", type=Path, required=True)
    audit_pv.add_argument("--generated-xml", type=Path, required=True)
    audit_pv.add_argument("--output", type=Path, required=True)
    audit_pv.add_argument("--csv-output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare()
    elif args.command == "gencase-requests":
        result = write_gencase_requests()
    elif args.command in {"audit-gencase", "partvtk-requests"}:
        receipts: dict[str, Path] = {}
        for item in args.receipts:
            key, sep, value = item.partition("=")
            if not sep or key not in CASE_SPECS:
                raise SystemExit(f"receipt must be CASE_KEY=PATH, known keys: {', '.join(CASE_SPECS)}")
            receipts[key] = Path(value)
        result = audit_gencase(receipts, args.output) if args.command == "audit-gencase" else write_partvtk_requests(receipts)
    else:
        result = audit_partvtk(args.generated_bi4, args.generated_xml, args.output, args.csv_output)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
