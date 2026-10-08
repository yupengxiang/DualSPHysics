#!/usr/bin/env python3
"""Prepare independent F2-S1 owner-centered middle/fine GenCase requests.

ROOT080 showed that the dp=.0088 cell-selector representation produced the
registered 37 x 25 x 10 per-layer lattice, 27,750 fluid particles, 18.910848
kg sample mass, and all-fluid support inside the frozen 18.876 kg owner boxes.
This forward builder registers two independent commensurate representations:
dp=.0044 (74 x 50 x 20 per layer) and dp=.0022 (148 x 100 x 40 per layer).

The continuous owner boxes and all boundary/motion/execution XML remain byte
preserved.  Only dp, pointref, shape mode, and fluid selector extents change.
The counts/masses below are forecasts until the parent runs GenCase and a
separate XML/VTK support audit.  This module never runs GenCase and never
reads BI4/VTK/HDF5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"
TEMPLATE = PRIMARY_REPO / "doc/xml_format/GenCase_CaseTemplate.xml"
SOURCE_DEF = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-gencase-source801-root804/prepared/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml")
SOURCE_MOTION = SOURCE_DEF.with_name(SOURCE_DEF.name.replace("_Def.xml", "_motion.dat"))
OWNER_CLOSURE = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_continuum_owner_closure_v1.json"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME_V8 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
RUNTIME_V6 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
RUNTIME_V2 = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
REFERENCE = Path(__file__).resolve().parent
INPUT_ROOT = REFERENCE / "stage2_f2_s1_owner_centered_cell_selector_ladder_v1_inputs/F2_S1"
SCRIPT = Path(__file__).resolve()

OWNER_LAYER_LOWS = ((0.05, -0.11, 0.700), (0.05, -0.11, 0.788), (0.05, -0.11, 0.876))
OWNER_SIZE = (0.325, 0.22, 0.088)
OWNER_MASS_KG = 18.876
RHO0 = 1000.0

LADDER = (
    {
        "name": "middle",
        "label": "DP0P0044",
        "dp_m": 0.0044,
        "pointref_m": (0.0035, 0.0022, 0.0026),
        "counts_per_layer": (74, 50, 20),
        "case_id": "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0044_ROOT_081",
        "attempt_id": "f2-s1-owner-centered-cell-selector-dp0044-gencase-root-081-001",
        "max_storage_bytes": 384 * 1024**2,
        "estimated_storage_bytes": 384 * 1024**2,
    },
    {
        "name": "fine",
        "label": "DP0P0022",
        "dp_m": 0.0022,
        "pointref_m": (0.0002, 0.0011, 0.0015),
        "counts_per_layer": (148, 100, 40),
        "case_id": "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0022_ROOT_082",
        "attempt_id": "f2-s1-owner-centered-cell-selector-dp0022-gencase-root-082-001",
        "max_storage_bytes": 2 * 1024**3,
        "estimated_storage_bytes": 2 * 1024**3,
    },
)


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino), "sha256": sha256(path)}


def atomic_bytes(path: Path, payload: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise FileExistsError(f"refuse overwrite immutable input: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def selector_geometry(spec: dict[str, Any]) -> tuple[list[list[float]], list[float]]:
    dp = float(spec["dp_m"])
    counts = tuple(int(v) for v in spec["counts_per_layer"])
    size = [(counts[axis] - 1) * dp for axis in range(3)]
    lows = []
    for layer_low in OWNER_LAYER_LOWS:
        center = [layer_low[axis] + OWNER_SIZE[axis] / 2.0 for axis in range(3)]
        lows.append([center[axis] - size[axis] / 2.0 for axis in range(3)])
    return lows, size


def derive_candidate(spec: dict[str, Any]) -> tuple[Path, Path, dict[str, Any]]:
    source = regular(SOURCE_DEF).read_text(encoding="utf-8")
    if source.count('<definition dp="0.01">') != 1 or source.count('<setshapemode>dp | bound</setshapemode>') != 1 or source.count('<setmkfluid mk="') != 3:
        raise ValueError("unexpected immutable F2 source definition shape")
    lows, size = selector_geometry(spec)
    dp = float(spec["dp_m"])
    pointref = tuple(float(value) for value in spec["pointref_m"])
    derived = source.replace('<definition dp="0.01">', f'<definition dp="{dp:g}">\n        <pointref x="{pointref[0]:.4f}" y="{pointref[1]:.4f}" z="{pointref[2]:.4f}" />', 1)
    derived = derived.replace('<setshapemode>dp | bound</setshapemode>', '<setshapemode>dp | actual | bound</setshapemode>', 1)
    old_boxes = (
        '<point x="0.05" y="-0.11" z="0.70" />\n            <size x="0.325" y="0.22" z="0.088" />',
        '<point x="0.05" y="-0.11" z="0.788" />\n            <size x="0.325" y="0.22" z="0.088" />',
        '<point x="0.05" y="-0.11" z="0.876" />\n            <size x="0.325" y="0.22" z="0.088" />',
    )
    new_boxes = tuple(
        f'<point x="{low[0]:.4f}" y="{low[1]:.4f}" z="{low[2]:.4f}" />\n'
        f'            <size x="{size[0]:.4f}" y="{size[1]:.4f}" z="{size[2]:.4f}" />'
        for low in lows
    )
    for old, new in zip(old_boxes, new_boxes):
        if derived.count(old) != 1:
            raise ValueError(f"source fluid selector not found exactly once: {old}")
        derived = derived.replace(old, new, 1)
    if derived == source or derived.count('<setshapemode>dp | actual | bound</setshapemode>') != 1:
        raise ValueError("representation edits were not applied")
    input_dir = INPUT_ROOT / spec["name"]
    candidate = input_dir / f"F2_S1_OWNER_CENTERED_CELL_SELECTOR_{spec['label']}_Def.xml"
    motion = input_dir / SOURCE_MOTION.name
    atomic_bytes(candidate, derived.encode("utf-8"))
    atomic_bytes(motion, regular(SOURCE_MOTION).read_bytes())
    forecast_count = int(counts_product(spec["counts_per_layer"]) * 3)
    sample_mass = forecast_count * RHO0 * dp**3
    manifest = {
        "schema": "ds02.stage2.f2-s1.owner-centered-cell-selector-ladder.v1",
        "status": "PREPARED_GENCASE_ONLY_FORECAST",
        "family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "grid_name": spec["name"], "dp_m": dp, "pointref_m": list(pointref),
        "counts_per_layer": list(spec["counts_per_layer"]), "forecast_fluid_count": forecast_count,
        "forecast_sample_mass_kg": sample_mass, "relative_to_frozen_owner_fraction": sample_mass / OWNER_MASS_KG - 1.0,
        "selector_low_m": lows, "selector_size_m": size,
        "continuous_owner": {"layer_low_m": [list(v) for v in OWNER_LAYER_LOWS], "layer_size_m": list(OWNER_SIZE), "volume_m3": 0.018876, "mass_kg": OWNER_MASS_KG, "authority": "frozen CURRENT source drawboxes; unchanged"},
        "source_control": "all source boundary/motion/execution XML bytes preserved; only dp/pointref/shape mode/fluid selectors changed",
        "source_def": record(SOURCE_DEF), "source_motion": record(SOURCE_MOTION),
        "candidate_def": record(candidate), "candidate_motion": record(motion),
        "official_gencase": {"binary": record(GENCASE), "config": record(GENCASE_CONFIG), "template": record(TEMPLATE)},
        "mass_gate": {"preferred_fraction": 0.01, "hard_fraction": 0.02, "mass_rescale": False, "status": "FORECAST_ONLY_UNTIL_GENERATED_XML_VTK_QA"},
    }
    manifest_path = input_dir / f"F2_S1_OWNER_CENTERED_CELL_SELECTOR_{spec['label']}_manifest.json"
    atomic_json(manifest_path, manifest)
    return candidate, motion, manifest


def counts_product(values: tuple[int, ...] | list[int]) -> int:
    result = 1
    for value in values:
        result *= int(value)
    return result


def build_request(spec: dict[str, Any], candidate: Path, motion: Path, manifest: dict[str, Any], launch_commit: str) -> tuple[Path, dict[str, Any]]:
    manifest_path = INPUT_ROOT / spec["name"] / f"F2_S1_OWNER_CENTERED_CELL_SELECTOR_{spec['label']}_manifest.json"
    static_paths = [SCRIPT, manifest_path, candidate, motion, SOURCE_DEF, SOURCE_MOTION, GENCASE, GENCASE_CONFIG, TEMPLATE, OWNER_CLOSURE, DISPATCH, STRICT, RUNTIME_V8, RUNTIME_V6, RUNTIME_V2]
    static_paths = list(dict.fromkeys(regular(path) for path in static_paths))
    records = {str(path): record(path) for path in static_paths}
    output_root = DATA_ROOT / "families/F2" / spec["case_id"] / spec["attempt_id"]
    request = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "gencase",
        "family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "case_id": spec["case_id"], "attempt_id": spec["attempt_id"], "launch_commit": launch_commit,
        "command": [str(GENCASE), str(candidate.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
        "cwd": str(candidate.parent), "worktree_root": str(PRIMARY_REPO),
        "input_files": list(records), "input_hashes": {key: value["sha256"] for key, value in records.items()}, "input_records": records,
        "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900,
        "max_memory_bytes": 2 * 1024**3, "max_storage_bytes": spec["max_storage_bytes"],
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()), "estimated_storage_bytes": spec["estimated_storage_bytes"],
        "estimated_peak_memory_bytes": 2 * 1024**3, "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": True, "solver_launch": False, "hdf5_read": False, "bi4_read": False,
        "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
        "source_binding": {
            "schema": "ds02.stage2.f2-s1.owner-centered-cell-selector-ladder-binding.v1",
            "grid_name": spec["name"], "source_def": records[str(SOURCE_DEF.resolve())], "source_motion": records[str(SOURCE_MOTION.resolve())],
            "candidate_def": records[str(candidate.resolve())], "candidate_motion": records[str(motion.resolve())], "manifest": records[str(manifest_path.resolve())],
            "official_gencase": {"binary": records[str(GENCASE.resolve())], "config": records[str(GENCASE_CONFIG.resolve())], "template": records[str(TEMPLATE.resolve())]},
            "owner_closure": records[str(OWNER_CLOSURE.resolve())], "representation": manifest,
            "post_gencase_required": ["generated.xml", "generated.bi4", "generated_Fluid.vtk", "generated_Bound.vtk", "execution-receipt.json"],
            "initial_native_qa_required": True, "mass_rescale": False,
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME_V8), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "output_tree_charge": "required; new attempt only"},
        "qualification_stage": "stage2_f2_s1_owner_centered_cell_selector_ladder_gencase_only_pending_actual_xml_vtk_qa",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "GenCase-only source representation; actual support/mass QA required before any solver"},
        "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
    }
    request_path = REFERENCE / f"stage2_f2_s1_owner_centered_cell_selector_{spec['name']}_request_v1.json"
    atomic_json(request_path, request)
    return request_path, request


def prepare(launch_commit: str | None, build_requests: bool) -> dict[str, Any]:
    results = []
    for spec in LADDER:
        candidate, motion, manifest = derive_candidate(spec)
        item: dict[str, Any] = {"grid": spec["name"], "candidate": record(candidate), "motion": record(motion), "manifest": manifest, "gencase_started": False}
        if build_requests:
            if not launch_commit:
                raise ValueError("--build-requests requires --launch-commit")
            request_path, request = build_request(spec, candidate, motion, manifest, launch_commit)
            item["request"] = str(request_path)
            item["request_sha256"] = sha256(request_path)
        results.append(item)
    return {"schema": "ds02.stage2.f2-s1.owner-centered-cell-selector-ladder.v1", "status": "PREPARED_TWO_GENCASE_ONLY_GRIDS", "launch_commit": launch_commit, "grids": results, "solver_started": False, "native_payload_read": False}


def self_test() -> dict[str, Any]:
    for spec in LADDER:
        low, size = selector_geometry(spec)
        count = counts_product(spec["counts_per_layer"]) * 3
        mass = count * RHO0 * float(spec["dp_m"]) ** 3
        if abs(mass - 18.910848) > 1e-10:
            raise AssertionError((spec["name"], mass))
        if len(low) != 3 or any(len(value) != 3 for value in low):
            raise AssertionError(low)
    return {"status": "PASS", "grids": [{"name": spec["name"], "dp_m": spec["dp_m"], "forecast_count": counts_product(spec["counts_per_layer"]) * 3, "forecast_mass_kg": 18.910848} for spec in LADDER], "gencase_started": False, "native_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--prepare-inputs", action="store_true")
    mode.add_argument("--build-requests", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test:
        value = self_test()
    else:
        value = prepare(args.launch_commit, args.build_requests)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
