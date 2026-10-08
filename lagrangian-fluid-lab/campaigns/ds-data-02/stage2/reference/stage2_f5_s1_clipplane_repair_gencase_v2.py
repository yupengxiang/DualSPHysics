#!/usr/bin/env python3
"""Prepare two source-preserving F5 clip-plane GenCase canaries.

The current sample is 11.56% below the continuous region implied by the
verified source clip plane.  These are the only two forward representations
registered here: the same fluid box, clip plane, closed bed, boundaries,
motion and execution controls with a center-of-cell pointref at dp=.01 and
dp=.005.  The script only writes new Def/motion/manifest files and guarded
GenCase request JSON; it never runs GenCase or a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
SOURCE_DEF = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml")
MOTION = DATA_ROOT / "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-m095_t090-motion-transform-117-root630/prepared/assets/f5_c082s1_motion_m095_t090.dat"
EVIDENCE = STAGE2 / "reference/stage2_f5_s1_clipplane_official_evidence_audit_v2.json"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"
TEMPLATE = GENCASE.parents[2] / "doc/xml_format/GenCase_CaseTemplate.xml"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
OWNER_MASS_KG = 287.736
GRIDS = {
    "dp010": {"dp_m": 0.01, "pointref": (0.015, 0.0, 0.015), "label": "DP010", "case": "F5_S1_CLIPPLANE_CENTER_LATTICE_DP010_ROOT_085", "attempt": "f5-s1-clipplane-center-lattice-dp010-gencase-root-085-001"},
    "dp005": {"dp_m": 0.005, "pointref": (0.0125, 0.0, 0.0125), "label": "DP005", "case": "F5_S1_CLIPPLANE_CENTER_LATTICE_DP005_ROOT_086", "attempt": "f5-s1-clipplane-center-lattice-dp005-gencase-root-086-001"},
}


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with regular(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path); st = path.stat()
    return {"path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino), "sha256": sha256(path)}


def write_new(path: Path, data: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"immutable path differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            fd = -1; f.write(data); f.flush(); os.fsync(f.fileno())
    finally:
        if fd >= 0: os.close(fd)


def json_new(path: Path, value: Any) -> None:
    write_new(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def candidate_bytes(grid: str) -> bytes:
    spec = GRIDS[grid]
    data = regular(SOURCE_DEF).read_bytes()
    data, n_dp = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', lambda m: m.group(1) + f"{spec['dp_m']:.3f}".encode() + m.group(2), data, count=1)
    if n_dp != 1: raise ValueError("source definition dp replacement was not unique")
    point = f'<pointref x="{spec["pointref"][0]:.4f}" y="{spec["pointref"][1]:.4f}" z="{spec["pointref"][2]:.4f}" />'.encode()
    data, n_ref = re.subn(rb'<pointref\s+x="[^"]+"\s+y="[^"]+"\s+z="[^"]+"\s*/>', point, data, count=1)
    if n_ref != 1: raise ValueError("source pointref replacement was not unique")
    return data


def prepare_inputs(grid: str) -> dict[str, Any]:
    spec = GRIDS[grid]
    root = STAGE2 / "reference/stage2_f5_s1_clipplane_repair_v2_inputs/F5_S1" / grid
    candidate = root / f"F5_S1_CLIPPLANE_CENTER_LATTICE_{spec['label']}_Def.xml"
    motion = root / "assets/f5_c082s1_motion_m095_t090.dat"
    manifest = root / f"F5_S1_CLIPPLANE_CENTER_LATTICE_{spec['label']}_manifest.json"
    candidate_data = candidate_bytes(grid)
    source_data = regular(SOURCE_DEF).read_bytes()
    # Exact byte-level proof: only the registered definition dp and pointref
    # tokens may differ from the immutable source Def.
    normalized = re.sub(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', candidate_data, count=1)
    normalized = re.sub(rb'<pointref\s+x="[^"]+"\s+y="[^"]+"\s+z="[^"]+"\s*/>', b'<pointref x="<X>" y="<Y>" z="<Z>" />', normalized, count=1)
    source_normalized = re.sub(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb'\1<DP>\2', source_data, count=1)
    source_normalized = re.sub(rb'<pointref\s+x="[^"]+"\s+y="[^"]+"\s+z="[^"]+"\s*/>', b'<pointref x="<X>" y="<Y>" z="<Z>" />', source_normalized, count=1)
    if normalized != source_normalized: raise ValueError("candidate changes source bytes beyond dp/pointref")
    write_new(candidate, candidate_data)
    write_new(motion, regular(MOTION).read_bytes())
    manifest_value = {"schema": "ds02.stage2.f5-s1.clipplane-repair-input.v2", "grid": grid, "dp_m": spec["dp_m"], "pointref_m": list(spec["pointref"]), "source_def": record(SOURCE_DEF), "candidate_def": record(candidate), "source_motion": record(MOTION), "candidate_motion": record(motion), "official_clip_evidence": record(EVIDENCE), "continuous_region_mass_kg": OWNER_MASS_KG, "continuous_box_and_clip_unchanged": True, "controls_and_motion_unchanged": True, "mass_rescale": False, "gencase_started": False, "solver_started": False, "support_mass_qa_required_before_solver": True, "status": "PREPARED_GENCASE_ONLY_PENDING_PARENT_GUARD"}
    json_new(manifest, manifest_value)
    return {"grid": grid, "candidate": record(candidate), "motion": record(motion), "manifest": record(manifest), "input_root": str(root.resolve())}


def build_request(grid: str, launch_commit: str) -> tuple[Path, dict[str, Any]]:
    spec = GRIDS[grid]
    facts = prepare_inputs(grid)
    candidate = Path(facts["candidate"]["path"]); motion = Path(facts["motion"]["path"]); manifest = Path(facts["manifest"]["path"])
    paths = [Path(__file__).resolve(), SOURCE_DEF, MOTION, EVIDENCE, GENCASE, GENCASE_CONFIG, TEMPLATE, DISPATCH, STRICT, RUNTIME, candidate, motion, manifest]
    records = {str(p.resolve()): record(p) for p in dict.fromkeys(paths)}
    output_root = DATA_ROOT / "families/F5" / spec["case"] / spec["attempt"]
    # The .005 case is intentionally given a larger reservation; this is an
    # output-tree estimate, not a scientific result or a promise of wall time.
    storage = 512 * 1024**2 if grid == "dp010" else 4 * 1024**3
    wall = 900 if grid == "dp010" else 1800
    request = {"schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "gencase", "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090", "case_id": spec["case"], "attempt_id": spec["attempt"], "launch_commit": launch_commit, "command": [str(GENCASE), str(candidate.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"], "cwd": str(candidate.parent), "worktree_root": str(PRIMARY_REPO), "input_files": list(records), "input_hashes": {k: v["sha256"] for k, v in records.items()}, "input_sha256": {k: v["sha256"] for k, v in records.items()}, "input_records": records, "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": wall, "max_memory_bytes": 4 * 1024**3, "max_storage_bytes": storage, "estimated_input_read_bytes": sum(v["bytes"] for v in records.values()), "estimated_storage_bytes": storage, "estimated_peak_memory_bytes": 2 * 1024**3, "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": True, "solver_launch": False, "hdf5_read": False, "bi4_read": False, "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"}, "source_binding": {"schema": "ds02.stage2.f5-s1.clipplane-repair-gencase.v2", "grid": grid, "dp_m": spec["dp_m"], "pointref_m": list(spec["pointref"]), "source_def": records[str(SOURCE_DEF.resolve())], "candidate_def": records[str(candidate.resolve())], "source_motion": records[str(MOTION.resolve())], "candidate_motion": records[str(motion.resolve())], "manifest": records[str(manifest.resolve())], "official_clip_evidence": records[str(EVIDENCE.resolve())], "official_gencase": records[str(GENCASE.resolve())], "continuous_region_mass_kg": OWNER_MASS_KG, "continuous_box_and_clip_unchanged": True, "controls_and_motion_unchanged": True, "mass_rescale": False, "support_mass_qa_required_before_solver": True}, "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "estimated_cpu_core_hours": 0.5 if grid == "dp010" else 1.0, "estimated_new_storage_bytes": storage, "source_pre_post_hash_required": True}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "source-preserving GenCase-only clip-plane representation; actual support/mass QA required before any solver"}, "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW"}
    path = STAGE2 / "requests" / f"f5-s1-clipplane-repair-{grid}-gencase-v2.json"
    json_new(path, request)
    return path, request


def self_test() -> dict[str, Any]:
    for grid in GRIDS:
        data = candidate_bytes(grid)
        if b'<clipplane cmt="unchanged_profile_separator_for_initial_fluid">' not in data or b"TimeMax" not in data or b"f5_c082s1_motion_m095_t090.dat" not in data:
            raise AssertionError(f"{grid}: source controls/clip/motion missing")
    return {"status": "PASS", "grids": sorted(GRIDS), "source_control_changes": "dp_and_pointref_only", "solver_started": False, "gencase_started": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--prepare-inputs", action="store_true"); mode.add_argument("--build-requests", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if args.build_requests and not args.launch_commit:
        parser.error("--build-requests requires --launch-commit")
    results = []
    for grid in GRIDS:
        item = prepare_inputs(grid)
        if args.build_requests:
            path, request = build_request(grid, args.launch_commit)
            item["request"] = str(path.resolve()); item["request_sha256"] = sha256(path)
        results.append(item)
    print(json.dumps({"schema": "ds02.stage2.f5-s1.clipplane-repair-gencase.v2", "status": "PREPARED_TWO_GENCASE_ONLY_CANDIDATES", "launch_commit": args.launch_commit, "grids": results, "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
