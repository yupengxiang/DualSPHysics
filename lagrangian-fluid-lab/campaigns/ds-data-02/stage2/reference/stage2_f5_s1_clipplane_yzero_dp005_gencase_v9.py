#!/usr/bin/env python3
"""Prepare the forward F5-S1 dp=.005 Y=0 GenCase request.

The consumed V5 request and q107 Y-half Def are immutable.  This additive
builder creates a new Def whose only source-byte change from q107 is the
global ``pointref.y`` phase (0.0025 -> 0.0000), plus a byte-identical motion
asset beside it so the official GenCase command can run from the new input
directory.  ``pointref`` is a global GenCase lattice origin: it affects fluid,
boundary, and forcing/shape representations.  The request therefore keeps
the mass/support gate and requires a later worker to compare all generated
Fluid/Bound geometry and forcing semantics.  This builder never invokes
GenCase, reads BI4/VTK/HDF5, or changes q107/source files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f5-s1.clipplane-yzero-gencase.v9"
REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
STAGE2_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"


def repo_file(relative: str) -> Path:
    local = REPO / relative
    if local.is_file():
        return local
    primary = PRIMARY_REPO / relative
    return primary if primary.is_file() else local


TEMPLATE = repo_file("doc/xml_format/GenCase_CaseTemplate.xml")
CHANGES = repo_file("CHANGES.txt")
DISPATCH = repo_file("lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py")
STRICT = repo_file("lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py")
RUNTIME = repo_file("lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py")
SOURCE_DEF = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/"
    "handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/"
    "candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml"
)
SOURCE_MOTION = DATA_ROOT / (
    "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-motion-transform-117-root630/prepared/assets/"
    "f5_c082s1_motion_m095_t090.dat"
)
Q107_REQUEST = REPO / STAGE2_REL / "requests/f5-s1-yhalf-dp005-gencase-v5-root-forward-107-001.json"
Q107_RECEIPT = DATA_ROOT / (
    "families/F5/F5_S1_CLIPPLANE_YHALF_DP005_GENCASE_ROOT_107/"
    "f5-s1-yhalf-dp005-gencase-v5-root-107-001-root-forward-030-001/execution-receipt.json"
)
Q107_DEF = REPO / REFERENCE_REL / (
    "stage2_f5_s1_clipplane_repair_v5_inputs/F5_S1/dp005/"
    "F5_S1_CLIPPLANE_YHALF_LATTICE_DP005_Def.xml"
)
Q107_MOTION = REPO / REFERENCE_REL / (
    "stage2_f5_s1_clipplane_repair_v5_inputs/F5_S1/dp005/assets/"
    "f5_c082s1_motion_m095_t090.dat"
)
CLIP_EVIDENCE = REPO / REFERENCE_REL / "stage2_f5_s1_clipplane_official_evidence_audit_v2.json"
INPUT_ROOT = REPO / REFERENCE_REL / "stage2_f5_s1_clipplane_repair_v9_inputs/F5_S1/dp005"
CANDIDATE_DEF = INPUT_ROOT / "F5_S1_CLIPPLANE_YZERO_LATTICE_DP005_Def.xml"
CANDIDATE_MOTION = INPUT_ROOT / "assets/f5_c082s1_motion_m095_t090.dat"
OUTPUT_DIR = REPO / STAGE2_REL / "requests/f5-s1-clipplane-yzero-dp005-gencase-v9"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_SAMPLE_MASS_KG = 254.4779834119572
GENCASE_BYTES = 5_809_384
GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str, *, scope: str = "small_input_hashed_by_builder_and_parent_v8") -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path), "label": label, "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev), "st_ino": int(stat.st_ino),
        "sha256": sha256(path), "content_scope": scope,
    }


def write_new(path: Path, data: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable new artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"refuse to reuse temporary artifact: {temporary}")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    write_new(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def normalized_def(data: bytes) -> bytes:
    data, n = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+(")', rb"\1<DP>\2", data, count=1)
    if n != 1:
        raise ValueError("Def has no unique definition@dp")
    data, n = re.subn(rb'<pointref\s+x="[^"]+"\s+y="[^"]+"\s+z="[^"]+"\s*/>', b'<pointref x="<X>" y="<Y>" z="<Z>" />', data, count=1)
    if n != 1:
        raise ValueError("Def has no unique pointref")
    return data


def facts(data: bytes) -> tuple[float, tuple[float, float, float]]:
    dp = re.search(rb'<definition\b[^>]*\bdp="([^"]+)"', data)
    point = re.search(rb'<pointref\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"\s*/>', data)
    if not dp or not point:
        raise ValueError("cannot parse Def dp/pointref")
    return float(dp.group(1)), tuple(float(point.group(i)) for i in range(1, 4))


def prepare_inputs() -> dict[str, Any]:
    q107 = regular(Q107_DEF, "q107 Y-half Def")
    motion = regular(Q107_MOTION, "q107 motion")
    data = q107.read_bytes()
    old = b'<pointref x="0.0125" y="0.0025" z="0.0125" />'
    new = b'<pointref x="0.0125" y="0.0000" z="0.0125" />'
    if data.count(old) != 1:
        raise ValueError("q107 Def does not contain exactly one expected Y-half pointref")
    candidate_data = data.replace(old, new, 1)
    if CANDIDATE_DEF.exists() or CANDIDATE_DEF.is_symlink():
        if CANDIDATE_DEF.is_symlink() or CANDIDATE_DEF.read_bytes() != candidate_data:
            raise FileExistsError(f"existing Y-zero Def is not the expected immutable bytes: {CANDIDATE_DEF}")
    else:
        write_new(CANDIDATE_DEF, candidate_data)
    if CANDIDATE_MOTION.exists() or CANDIDATE_MOTION.is_symlink():
        if CANDIDATE_MOTION.is_symlink() or CANDIDATE_MOTION.read_bytes() != motion.read_bytes():
            raise FileExistsError(f"existing Y-zero motion is not the expected immutable bytes: {CANDIDATE_MOTION}")
    else:
        write_new(CANDIDATE_MOTION, motion.read_bytes())
    dp, point = facts(candidate_data)
    if abs(dp - 0.005) > 1e-12 or point != (0.0125, 0.0, 0.0125):
        raise AssertionError((dp, point))
    if normalized_def(candidate_data) != normalized_def(data):
        raise AssertionError("Y-zero candidate changed more than global dp/pointref fields")
    if CANDIDATE_MOTION.read_bytes() != motion.read_bytes():
        raise AssertionError("candidate motion is not byte-identical to q107 motion")
    return {
        "candidate_def": record(CANDIDATE_DEF, "F5 Y-zero candidate Def"),
        "candidate_motion": record(CANDIDATE_MOTION, "F5 Y-zero candidate motion"),
        "q107_def": record(q107, "q107 Y-half Def provenance"),
        "q107_motion": record(motion, "q107 motion provenance"),
        "q107_normalized_def_sha256": hashlib.sha256(normalized_def(data)).hexdigest(),
        "candidate_normalized_def_sha256": hashlib.sha256(normalized_def(candidate_data)).hexdigest(),
        "pointref_change": {"from_m": [0.0125, 0.0025, 0.0125], "to_m": [0.0125, 0.0, 0.0125]},
    }


def official_binary_record() -> dict[str, Any]:
    return {"path": str(GENCASE.resolve()), "bytes": GENCASE_BYTES, "sha256": GENCASE_SHA256, "content_scope": "PARENT_V8_AFTER_RESERVATION_HASH", "hash_source": "official_binary_verification_earlier_stage2"}


def build_request(args: argparse.Namespace) -> dict[str, Any]:
    prepared = prepare_inputs()
    static = [
        (CANDIDATE_DEF, "F5 Y-zero candidate Def"), (CANDIDATE_MOTION, "F5 Y-zero candidate motion"),
        (Q107_DEF, "q107 Y-half Def provenance"), (Q107_MOTION, "q107 motion provenance"),
        (Q107_REQUEST, "q107 GenCase request provenance"), (Q107_RECEIPT, "q107 GenCase receipt provenance"),
        (SOURCE_DEF, "F5 source Def"), (SOURCE_MOTION, "F5 source motion"), (CLIP_EVIDENCE, "F5 official clip evidence"),
        (Path(__file__).resolve(), "F5 Y-zero GenCase request builder"),
        (GENCASE_CONFIG, "official GenCase config"), (TEMPLATE, "GenCase template"), (CHANGES, "GenCase changes"),
        (DISPATCH, "parent v8 dispatch"), (STRICT, "parent v8 strict dispatch"), (RUNTIME, "parent v8 runtime"),
        (PYTHON, "stage2 interpreter"),
    ]
    records = {str(path.expanduser().resolve()): record(path, label) for path, label in static}
    records[str(GENCASE.resolve())] = official_binary_record()
    input_files = sorted(records)
    case_id = "F5_S1_CLIPPLANE_YZERO_DP005_GENCASE_ROOT_123"
    attempt_id = "f5-s1-yzero-dp005-gencase-v9-root-123-001"
    output_root = DATA_ROOT / "families/F5" / case_id / attempt_id
    command = [str(GENCASE), str(CANDIDATE_DEF.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "gencase",
        "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": case_id, "attempt_id": attempt_id, "launch_commit": args.launch_commit,
        "command": command, "cwd": str(CANDIDATE_DEF.parent), "worktree_root": str(REPO),
        "input_files": input_files, "input_hashes": {path: records[path]["sha256"] for path in input_files}, "input_records": records,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
        "max_memory_bytes": 2 * 1024**3, "estimated_storage_bytes": 4 * 1024**3, "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_input_read_bytes": sum(int(row["bytes"]) for row in records.values()), "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0, "execution_allowed": True,
        "launch_disabled": False, "solver_started": False, "gencase_launch": True, "solver_launch": False,
        "hdf5_read": False, "bi4_read": False, "output_root": str(output_root),
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
        "source_binding": {
            "schema": SCHEMA, "grid": "dp005", "dp_m": 0.005, "pointref_m": [0.0125, 0.0, 0.0125],
            "source_def": records[str(SOURCE_DEF.resolve())], "candidate_def": records[str(CANDIDATE_DEF.resolve())],
            "q107_def_provenance": records[str(Q107_DEF.resolve())], "q107_request_provenance": records[str(Q107_REQUEST.resolve())],
            "q107_receipt_provenance": records[str(Q107_RECEIPT.resolve())], "source_motion": records[str(SOURCE_MOTION.resolve())],
            "candidate_motion": records[str(CANDIDATE_MOTION.resolve())],
            "candidate_normalized_def_sha256": prepared["candidate_normalized_def_sha256"],
            "source_normalized_def_sha256": hashlib.sha256(normalized_def(SOURCE_DEF.read_bytes())).hexdigest(),
            "q107_normalized_def_sha256": prepared["q107_normalized_def_sha256"],
            "continuous_region_mass_kg": CONTINUOUS_MASS_KG, "old_sample_mass_kg": OLD_SAMPLE_MASS_KG,
            "continuous_box_and_clip_unchanged": True, "controls_and_motion_unchanged": True, "mass_rescale": False,
            "phase_change_relative_to_q107": "pointref.y 0.0025 -> 0.0000 only",
            "global_lattice_phase_change": True,
            "pointref_scope": "global GenCase lattice origin; fluid, boundary, forcing/shape representation all require comparison",
            "fluid_selector_unchanged": True, "boundary_selector_unchanged": True, "forcing_motion_content_unchanged": True,
            "boundary_geometry_audit_required": True, "support_mass_qa_required_before_solver": True,
            "preferred_mass_gate": "whole continuous-owner mass error <=1%; >2% hard failure; no rescale",
            "scientific_qualification": "UNKNOWN until terminal XML plus Fluid/Bound support and global-shape comparison",
        },
        "provenance": {
            "parent_q107_case_id": "F5_S1_CLIPPLANE_YHALF_DP005_GENCASE_ROOT_107",
            "parent_q107_is_immutable": True, "new_identity": True,
            "old_yhalf_mass_and_geometry_reports_are_diagnostic_only": True,
        },
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "source_pre_post_hash_required": True},
        "qualification_stage": "stage2_f5_s1_source_preserving_yzero_gencase_only_v9_pending_parent_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "global pointref phase can change all shapes; terminal support/geometry/control audit is required before any solver"},
        "status": "READY_FOR_PARENT_V8_CPU_GENCASE_REVIEW",
    }
    request["sha256"] = hashlib.sha256(json.dumps({key: value for key, value in request.items() if key != "sha256"}, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return request


def self_test() -> dict[str, Any]:
    if GENCASE_BYTES != 5_809_384 or GENCASE_SHA256 != "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226":
        raise AssertionError("official GenCase record changed")
    prepared = prepare_inputs()
    assert prepared["pointref_change"]["to_m"] == [0.0125, 0.0, 0.0125]
    assert prepared["candidate_normalized_def_sha256"] == prepared["q107_normalized_def_sha256"]
    return {"status": "PASS", "schema": SCHEMA, "candidate": prepared["candidate_def"], "global_lattice_phase_change": True, "all_shape_audit_required": True, "solver_started": False, "bi4_read": False, "vtk_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--prepare-inputs", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--launch-commit")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    prepared = prepare_inputs()
    if args.prepare_inputs:
        print(json.dumps({"status": "PREPARED_SOURCE_ONLY_INPUTS", "schema": SCHEMA, **prepared}, ensure_ascii=False, indent=2)); return 0
    if not args.launch_commit or args.output is None:
        parser.error("--build-request requires --launch-commit and --output")
    request = build_request(args)
    write_json(args.output, request)
    print(json.dumps({"status": request["status"], "schema": SCHEMA, "request": str(args.output.expanduser().resolve()), "candidate": str(CANDIDATE_DEF), "command": request["command"], "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
