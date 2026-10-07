#!/usr/bin/env python3
"""Prepare v3 bounded same-origin bounded coarse GenCase probes for F2-S1.

The exact CURRENT336 Def/motion pair is copied byte-for-byte for geometry, fill,
motion, controls, and source coordinates.  Only the declared particle spacing
and the generated motion filename are changed.  The probes test whether a
nearby spacing yields an initial fluid sample mass within the pre-registered
gate after actual GenCase generation; they do not alter continuous geometry,
start the solver, or claim a lattice-phase match before the generated XML is
audited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.gencase-coarse-phase-probe.v3"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
TEMPLATE_DEF = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_FIRST48_REMAINING24_SOURCE_ROOT801/"
    "root-stage1-f2-first48-remaining24-registered-source-generation-root801/source/source/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml"
)
TEMPLATE_MOTION = TEMPLATE_DEF.with_name(TEMPLATE_DEF.name.replace("_Def.xml", "_motion.dat"))
INPUT_ROOT = Path(__file__).with_name("f2_s1_coarse_phase_probe_inputs_v3")
REQUEST_DIR = Path(__file__).resolve().parents[1] / "requests/f2-s1-coarse-phase-probe-v3"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
TARGET_DP = 0.01
TARGET_PARTICLES = 418104
DP_CANDIDATES: tuple[float, ...] = (0.01290, 0.01300, 0.01310, 0.01320)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def candidate_id(dp: float) -> str:
    return f"F2_S1_COARSE_PHASE_PROBE_V3_DP{int(round(dp * 100000)):05d}"


def derive_case(dp: float) -> dict[str, Any]:
    if not TEMPLATE_DEF.is_file() or not TEMPLATE_MOTION.is_file():
        raise FileNotFoundError("CURRENT F2-S1 Def/motion template is unavailable")
    label = f"dp{dp:.5f}".replace(".", "p")
    case_id = candidate_id(dp)
    case_dir = INPUT_ROOT / label
    case_dir.mkdir(parents=True, exist_ok=True)
    def_path = case_dir / f"{case_id}_Def.xml"
    motion_name = f"{case_id}_motion.dat"
    motion_path = case_dir / motion_name
    source = TEMPLATE_DEF.read_text(encoding="utf-8")
    marker = '<definition dp="0.01">'
    if source.count(marker) != 1:
        raise ValueError("template definition dp marker is not unique")
    source = source.replace(marker, f'<definition dp="{dp:g}">', 1)
    motion_marker = '<file name="F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat" />'
    if source.count(motion_marker) != 1:
        raise ValueError("template motion filename marker is not unique")
    source = source.replace(motion_marker, f'<file name="{motion_name}" />', 1)
    source = source.replace("resolution=coarse_dp010", f"resolution={label}", 1)
    if def_path.exists() or motion_path.exists():
        raise FileExistsError(f"refuse to overwrite derived input: {case_dir}")
    def_path.write_text(source, encoding="utf-8")
    motion_path.write_bytes(TEMPLATE_MOTION.read_bytes())
    expected_particles = int(round(TARGET_PARTICLES * (TARGET_DP / dp) ** 3))
    return {
        "case_id": case_id,
        "label": label,
        "physical_case_id": PHYSICAL_CASE_ID,
        "dp_m": dp,
        "cfl": 0.2,
        "phase_policy": "same CURRENT336 source coordinate origin and unchanged draw/fill/motion geometry; no phase equivalence is claimed until generated XML is audited",
        "source_template": {"definition": file_record(TEMPLATE_DEF), "motion": file_record(TEMPLATE_MOTION)},
        "derived_inputs": {"definition": file_record(def_path), "motion": file_record(motion_path)},
        "expected_particle_count_estimate": expected_particles,
        "estimated_native_output_bytes": max(16 * 1024 * 1024, int(math.ceil(18398632 * (TARGET_DP / dp) ** 3 * 1.5))),
        "estimate_policy": "bounded GenCase-only estimate from current dp0 Part_0000; actual generated XML controls particle count and mass gate",
    }


def prepare() -> dict[str, Any]:
    records = [derive_case(dp) for dp in DP_CANDIDATES]
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_INPUTS_NOT_RUN",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source_template": {"definition": file_record(TEMPLATE_DEF), "motion": file_record(TEMPLATE_MOTION)},
        "continuous_recipe_rule": "copy CURRENT336 geometry draw/fill, receiver/open-rim coordinates, motion axis/duration, gravity and controls; vary only dp and the referenced motion filename",
        "mass_gate": {
            "reference_target_initial_fluid_sample_mass_kg": 21.114,
            "pass_relative_tolerance": 0.01,
            "hard_upper_relative_tolerance": 0.02,
            "rule": "sum generated fluid count × generated massfluid; >2% is a hard failure and cannot enter the matched reference grid",
        },
        "cases": records,
        "solver_started": False,
        "gencase_started": False,
    }
    atomic_json(INPUT_ROOT / "manifest.json", manifest)
    return manifest


def request_for(record: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    definition = Path(record["derived_inputs"]["definition"]["path"]).resolve()
    motion = Path(record["derived_inputs"]["motion"]["path"]).resolve()
    manifest = (INPUT_ROOT / "manifest.json").resolve()
    request_path = output_dir / f"{record['case_id'].lower()}.json"
    inputs = [
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(),
        GENCASE.resolve(),
        definition,
        motion,
        manifest,
    ]
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": "F2",
        "case_id": record["case_id"],
        "attempt_id": f"{record['case_id'].lower()}-001",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 2,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": int(record["estimated_native_output_bytes"]),
        "worktree_root": str(REPO),
        "cwd": str(definition.parent),
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "input_files": [str(path) for path in inputs],
        "input_hashes": {str(path): sha256_file(path) for path in inputs},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 2 * 300 / 3600,
            "estimated_new_storage_bytes": int(record["estimated_native_output_bytes"]),
        },
        "scope": {
            "physical_case_id": PHYSICAL_CASE_ID,
            "continuous_recipe_source": "CURRENT336 F2-S1 exact Def/motion template",
            "dp_m": record["dp_m"],
            "same_origin_phase_probe": True,
            "gencase_only": True,
            "solver_started": False,
            "full_time_hdf5_read": False,
            "gpu_uuid_lease": "none",
        },
    }


def emit_requests(manifest: dict[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    requests = []
    for record in manifest["cases"]:
        request = request_for(record, output_dir)
        atomic_json(output_dir / f"{record['case_id'].lower()}.json", request)
        requests.append(request)
    return requests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--emit-requests-dir", type=Path)
    parser.add_argument("--input-root", type=Path, default=INPUT_ROOT)
    args = parser.parse_args()
    if not args.prepare and args.emit_requests_dir is None:
        raise SystemExit("choose --prepare and/or --emit-requests-dir")
    manifest = prepare() if args.prepare else json.loads((args.input_root / "manifest.json").read_text(encoding="utf-8"))
    if args.emit_requests_dir is None:
        print(json.dumps({"status": "PASS", "manifest": str(INPUT_ROOT / 'manifest.json'), "cases": len(manifest['cases'])}, ensure_ascii=False))
        return 0
    requests = emit_requests(manifest, args.emit_requests_dir)
    print(json.dumps({"status": "PASS", "requests": len(requests), "output_dir": str(args.emit_requests_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
