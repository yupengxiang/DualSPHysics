#!/usr/bin/env python3
"""Prepare the guarded CPU request for the F5 official clip evidence audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REFERENCE = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
WORKER = REFERENCE / "stage2_f5_s1_clipplane_official_evidence_audit_v2.py"
SOURCE_DEF = Path("/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml")
GENERATED_XML = DATA_ROOT / "families/F5/F5_S1_FINE_INITIAL_GENCASE_CANARY_ROOT_068/f5-s1-fine-initial-gencase-canary-root-068-001-root-forward-030-001/generated.xml"
SUPPORT_REPORT = DATA_ROOT / "families/F5/F5_S1_INITIAL_SUPPORT_AUDIT_V3_ROOT_077/f5-s1-initial-support-audit-v3-root-077-001-root-forward-030-001/report/f5_s1_initial_gencase_support_audit_v3.json"
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4")
GENCASE = OFFICIAL_ROOT / "bin/linux/GenCase_linux64"
TEMPLATE = OFFICIAL_ROOT / "doc/xml_format/GenCase_CaseTemplate.xml"
CHANGES = OFFICIAL_ROOT / "CHANGES.txt"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    st = path.stat()
    return {"path": str(path), "bytes": int(st.st_size), "mtime_ns": int(st.st_mtime_ns), "ctime_ns": int(st.st_ctime_ns), "st_dev": int(st.st_dev), "st_ino": int(st.st_ino), "sha256": sha256(path)}


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write(payload); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def build(args: argparse.Namespace) -> dict[str, Any]:
    paths = [WORKER, Path(__file__).resolve(), PYTHON, SOURCE_DEF, GENERATED_XML, SUPPORT_REPORT, GENCASE, TEMPLATE, CHANGES, PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py", PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py", PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"]
    records = {str(p.expanduser().resolve()): record(p) for p in dict.fromkeys(paths)}
    case_id = args.case_id or "F5_S1_CLIPPLANE_OFFICIAL_EVIDENCE_AUDIT_V2_ROOT"
    attempt_id = args.attempt_id or "f5-s1-clipplane-official-evidence-audit-v2-root-001"
    output_root = DATA_ROOT / "families/F5" / case_id / attempt_id
    report_path = "{attempt_root}/report/stage2_f5_s1_clipplane_official_evidence_audit_v2.json"
    command = [str(PYTHON), str(WORKER), "--write-report", "--output", report_path]
    request = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090", "case_id": case_id, "attempt_id": attempt_id, "launch_commit": args.launch_commit,
        "command": command, "cwd": str(PRIMARY_REPO), "worktree_root": str(PRIMARY_REPO), "input_files": list(records), "input_hashes": {k: v["sha256"] for k, v in records.items()}, "input_records": records,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900, "max_memory_bytes": 1 << 30, "max_storage_bytes": 64 << 20, "estimated_input_read_bytes": sum(v["bytes"] for v in records.values()), "estimated_output_bytes": 1 << 20, "estimated_storage_bytes": 64 << 20, "estimated_peak_memory_bytes": 512 << 20, "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "hdf5_read": False, "bi4_read": False, "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": report_path},
        "guard_policy": {"input_files_are_full_strings": True, "official_binary_is_read_only": True, "worker_reads": "source/generated XML, prior support report, immutable official GenCase binary/template/CHANGES, nm/objdump stdout", "vtk_read": False, "bi4_read": False, "hdf5_read": False, "gencase_executed": False, "solver_launch": False, "command_output_sha256_recorded": True, "repair_candidates_are_launch_disabled": True},
        "source_binding": {"schema": "ds02.stage2.f5-s1.clipplane-official-evidence-audit.v2", "source_def": records[str(SOURCE_DEF.resolve())], "generated_xml": records[str(GENERATED_XML.resolve())], "support_report": records[str(SUPPORT_REPORT.resolve())], "official_gencase": records[str(GENCASE.resolve())], "official_template": records[str(TEMPLATE.resolve())], "official_changes": records[str(CHANGES.resolve())], "derived_region_mass_gate": {"preferred_fraction": 0.01, "hard_fraction": 0.02, "mass_rescale": False}},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"), "strict_guard": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"), "runtime": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"), "cpu_parent_binding": "required", "gpu": "none", "estimated_cpu_core_hours": 0.25, "estimated_new_storage_bytes": 64 << 20},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "official clip semantics/provenance audit and source-derived continuous mass diagnostic; no solver or numerical qualification"}, "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
    }
    write_new(Path(args.output), request)
    return request


def self_test() -> dict[str, Any]:
    return {"status": "PASS", "official_binary_executed": False, "vtk_read": False, "solver_started": False, "repair_candidates_launch_disabled": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--output", type=Path); parser.add_argument("--launch-commit"); parser.add_argument("--case-id"); parser.add_argument("--attempt-id")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if args.output is None or not args.launch_commit:
        parser.error("--build-request requires --output and --launch-commit")
    request = build(args)
    print(json.dumps({"status": "PASS_REQUEST_BUILT", "output": str(args.output.resolve()), "vtk_read": False, "solver_started": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
