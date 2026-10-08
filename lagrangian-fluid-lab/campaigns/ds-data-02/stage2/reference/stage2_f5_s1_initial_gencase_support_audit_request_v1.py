#!/usr/bin/env python3
"""Build the guarded ROOT068 F5-S1 XML/VTK support-audit request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = STAGE2 / "reference/stage2_f5_s1_initial_gencase_support_audit_v1.py"
REQUEST_BUILDER = Path(__file__).resolve()
REQUEST_PATH = STAGE2 / "requests/f5-s1-initial-gencase-support-audit-v1-root-forward-069.json"
CASE_ID = "F5_S1_FINE_INITIAL_GENCASE_SUPPORT_AUDIT_ROOT_069"
ATTEMPT_ID = "f5-s1-fine-initial-gencase-support-audit-v1-root-forward-069-001"
ROOT068 = DATA_ROOT / "families/F5/F5_S1_FINE_INITIAL_GENCASE_CANARY_ROOT_068/f5-s1-fine-initial-gencase-canary-root-068-001-root-forward-030-001"
GENERATED_XML = ROOT068 / "generated.xml"
FLUID_VTK = ROOT068 / "generated_Fluid.vtk"
BOUND_VTK = ROOT068 / "generated_Bound.vtk"
RECEIPT = ROOT068 / "execution-receipt.json"
SOURCE_XML = DATA_ROOT / (
    "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-genuine-gencase-118-root640/prepared/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1.xml"
)
SOURCE_DEF = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/"
    "handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/"
    "candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml"
)
CANDIDATE_DEF = STAGE2 / "reference/stage2_mass_fit_probe_inputs_v2/F5_S1/fine/fine_Def.xml"
SOURCE_MOTION = DATA_ROOT / (
    "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-motion-transform-117-root630/prepared/assets/"
    "f5_c082s1_motion_m095_t090.dat"
)
CANDIDATE_MOTION = CANDIDATE_DEF.parent / "assets/f5_c082s1_motion_m095_t090.dat"
OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/"
    "handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/"
    "candidates/M095_T090/owner.json"
)
SOURCE_SAMPLE_CONTRACT = STAGE2 / "reference/stage2_f5_s1_observer_calibration_contract_v1.json"
EFFECTIVE_CONTROL = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F5_EFFECTIVE_CONTROL_INDEPENDENT_VERIFICATION_001.json"
SOURCE_SOLVER_RECEIPT = DATA_ROOT / (
    "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-full801-native-release-131-root808/execution-receipt.json"
)
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
    }


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
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


def build() -> dict[str, Any]:
    paths = [
        REQUEST_BUILDER, WORKER, GENERATED_XML, FLUID_VTK, BOUND_VTK, RECEIPT,
        SOURCE_XML, SOURCE_DEF, CANDIDATE_DEF, SOURCE_MOTION, CANDIDATE_MOTION,
        OWNER, SOURCE_SAMPLE_CONTRACT, EFFECTIVE_CONTROL, SOURCE_SOLVER_RECEIPT,
        DISPATCH, STRICT, RUNTIME, PYTHON,
    ]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    # Keep the list explicit and string-valued.  The v8 parent guard hashes
    # every item in input_files; deferred_input_files are deliberately absent.
    unique = list(dict.fromkeys(path.expanduser().resolve() for path in paths))
    records = {str(path): record(path) for path in unique}
    git_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    output_name = "f5_s1_initial_gencase_support_audit_v1.json"
    output_path = f"{{attempt_root}}/report/{output_name}"
    expected = {
        "candidate_def": records[str(CANDIDATE_DEF.resolve())]["sha256"],
        "source_def": records[str(SOURCE_DEF.resolve())]["sha256"],
        "candidate_motion": records[str(CANDIDATE_MOTION.resolve())]["sha256"],
        "source_motion": records[str(SOURCE_MOTION.resolve())]["sha256"],
        "source_xml": records[str(SOURCE_XML.resolve())]["sha256"],
        "owner": records[str(OWNER.resolve())]["sha256"],
        "source_sample_contract": records[str(SOURCE_SAMPLE_CONTRACT.resolve())]["sha256"],
        "effective_control": records[str(EFFECTIVE_CONTROL.resolve())]["sha256"],
        "source_solver_receipt": records[str(SOURCE_SOLVER_RECEIPT.resolve())]["sha256"],
    }
    command = [
        str(PYTHON), str(WORKER),
        "--generated-xml", str(GENERATED_XML), "--fluid-vtk", str(FLUID_VTK),
        "--bound-vtk", str(BOUND_VTK), "--receipt", str(RECEIPT),
        "--candidate-def", str(CANDIDATE_DEF), "--source-def", str(SOURCE_DEF),
        "--candidate-motion", str(CANDIDATE_MOTION), "--source-motion", str(SOURCE_MOTION),
        "--source-xml", str(SOURCE_XML), "--owner", str(OWNER),
        "--source-sample-contract", str(SOURCE_SAMPLE_CONTRACT),
        "--effective-control", str(EFFECTIVE_CONTROL), "--source-solver-receipt", str(SOURCE_SOLVER_RECEIPT),
        "--expected-candidate-def-sha", expected["candidate_def"],
        "--expected-source-def-sha", expected["source_def"],
        "--expected-candidate-motion-sha", expected["candidate_motion"],
        "--expected-source-motion-sha", expected["source_motion"],
        "--expected-source-xml-sha", expected["source_xml"],
        "--expected-owner-sha", expected["owner"],
        "--expected-source-sample-contract-sha", expected["source_sample_contract"],
        "--expected-effective-control-sha", expected["effective_control"],
        "--expected-source-solver-receipt-sha", expected["source_solver_receipt"],
        "--output", output_path,
    ]
    return {
        "schema": "ds02.request.v1",
        "family_id": "F5", "sentinel_id": "F5-S1",
        "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090",
        "case_id": CASE_ID, "attempt_id": ATTEMPT_ID,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 1200, "max_memory_bytes": 1 << 30, "max_storage_bytes": 256 << 20,
        "worktree_root": str(REPO), "cwd": str(REPO), "command": command,
        "input_files": list(records),
        "input_hashes": {path: value["sha256"] for path, value in records.items()},
        "input_sha256": {path: value["sha256"] for path, value in records.items()},
        "estimated_input_read_bytes": sum(value["bytes"] for value in records.values()),
        "estimated_geometry_read_bytes": records[str(FLUID_VTK.resolve())]["bytes"] + records[str(BOUND_VTK.resolve())]["bytes"],
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "estimated_storage_bytes": 256 << 20,
        "estimated_peak_memory_bytes": 512 << 20,
        "execution_allowed": True, "launch_disabled": False,
        "solver_started": False, "gencase_launch": False, "hdf5_read": False, "bi4_read": False,
        "output": {"atomic": True, "refuse_overwrite": True, "path": output_path},
        "guard_policy": {
            "input_files_are_full_strings": True,
            "parent_after_reserve_pre_post_sha_stat": "required for every input_files item; generated XML/Fluid.vtk/Bound.vtk/receipt are actual ROOT068 outputs",
            "deferred_input_files": "not used; v8 does not consume deferred fields for launch hashes",
            "worker_reads": "generated XML, Fluid.vtk, Bound.vtk, receipt, source Def/XML/motion/owner/control records only",
            "bi4_read": False, "hdf5_read": False, "solver_launch": False,
            "continuous_owner_mass": "UNKNOWN_UNSPECIFIED_BY_OWNER_CONTRACT; box envelope is diagnostic only",
        },
        "source_binding": {
            "schema": "ds02.stage2.f5-s1.initial-gencase-support-binding.v1",
            "root068_generated_xml": records[str(GENERATED_XML.resolve())],
            "root068_generated_fluid_vtk": records[str(FLUID_VTK.resolve())],
            "root068_generated_bound_vtk": records[str(BOUND_VTK.resolve())],
            "root068_execution_receipt": records[str(RECEIPT.resolve())],
            "source_xml": records[str(SOURCE_XML.resolve())],
            "source_definition": records[str(SOURCE_DEF.resolve())],
            "candidate_definition": records[str(CANDIDATE_DEF.resolve())],
            "source_motion": records[str(SOURCE_MOTION.resolve())],
            "candidate_motion": records[str(CANDIDATE_MOTION.resolve())],
            "owner_contract": records[str(OWNER.resolve())],
            "source_sample_contract": records[str(SOURCE_SAMPLE_CONTRACT.resolve())],
            "effective_control": records[str(EFFECTIVE_CONTROL.resolve())],
            "source_solver_receipt": records[str(SOURCE_SOLVER_RECEIPT.resolve())],
            "source_discrete_sample_mass_kg": 253.264,
            "source_discrete_sample_mass_is_not_continuous_owner_mass": True,
            "launch_commit": git_head,
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME),
            "launch_commit": git_head, "cpu_parent_binding": "required", "gpu": "none", "gencase_launch": False, "solver_launch": False,
            "estimated_cpu_core_hours": 0.35, "estimated_new_storage_bytes": 256 << 20,
            "source_output_read_only": True, "parent_uuid_or_cpu_lease": "required",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "initial XML/VTK support/control audit; GenCase sample mass is a discrete diagnostic only"},
        "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    if args.check == args.emit:
        parser.error("choose exactly one of --check or --emit")
    request = build()
    if args.emit:
        write_new(REQUEST_PATH, request)
    print(json.dumps({"status": "PASS_REQUEST_BUILT", "request": str(REQUEST_PATH.resolve()), "emitted": args.emit, "input_count": len(request["input_files"]), "estimated_geometry_read_bytes": request["estimated_geometry_read_bytes"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
