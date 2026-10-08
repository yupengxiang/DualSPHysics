#!/usr/bin/env python3
"""Build the bounded F1 dp=.0025 half-CFL Idp identity audit request."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1.owner-removed-identity-audit-request-builder.v1"
REPO = Path(__file__).resolve().parents[5]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CASE = DATA / "families/F1/f1-s1-owner-dp0025-half_cfl-savedt-nvme-v2/f1-s1-owner-dp0025-half_cfl-savedt-v5-root-041-001"
RECEIPT = CASE / "execution-receipt.json"
OUTPUT_ROOT = Path("/var/tmp/ds02-stage2/F1/F1_S1_OWNER_DP0025_HALF_CFL_NVME_SAVEDT_V2/f1-s1-owner-dp0025-half_cfl-savedt-v5-root-041-001")
RUNPARTS = OUTPUT_ROOT / "solver_output/RunPARTs.csv"
RAW_ROOT = OUTPUT_ROOT / "solver_output/data"
INPUT_PREFIX = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_S1_OWNER_DP0025_BI4_COPY_V3/f1-s1-owner-dp0025-bi4-copy-v3-root-039-001-root-forward-030-001/solver-inputs/half_cfl/F1_S1_OWNER_DP0025_half_cfl_SAVEDT")
XML = INPUT_PREFIX.with_suffix(".xml")
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_owner_removed_identity_audit_v1.py"
REQUEST_BUILDER = Path(__file__).resolve()
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
DECODER_SOURCE = REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py")
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v8.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v8.py"
PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_DP0025_HALF_CFL_ACTUAL_EXTERNAL_V5_SOLVER_ROOT_VERIFICATION_041.json")


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
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(path)
    return value


def rows_count_and_final_time(path: Path) -> tuple[int, float]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    header, *body = lines
    columns = [value.strip() for value in header.split(";")]
    part_index = columns.index("Part")
    time_index = columns.index("TimeStep [s]")
    rows: list[tuple[int, float]] = []
    for line in body:
        values = [value.strip() for value in line.split(";")]
        if len(values) <= max(part_index, time_index):
            continue
        part = values[part_index].split()[0]
        time = values[time_index].split()[0]
        if not part.isdigit():
            continue
        rows.append((int(part), float(time)))
    if not rows or [part for part, _ in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs rows are not contiguous: {path}")
    return len(rows), rows[-1][1]


def atomic(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def build(output: Path) -> dict[str, Any]:
    receipt = load(RECEIPT)
    if receipt.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN" or receipt.get("cfd_invoked") is not True:
        raise ValueError("bound F1 receipt is not a completed CFD development run")
    for path in (REQUEST_BUILDER, WORKER, RECEIPT, RUNPARTS, XML, DECODER, DECODER_SOURCE, DISPATCH, STRICT, RUNTIME, PROOF):
        if not path.is_file():
            raise FileNotFoundError(path)
    rows, final_time = rows_count_and_final_time(RUNPARTS)
    output_name = "f1_s1_owner_dp0025_half_removed_identity_audit_v1.json"
    case_id = "F1_S1_OWNER_DP0025_HALF_REMOVED_IDENTITY_AUDIT_V1"
    attempt_id = "f1-s1-owner-dp0025-half-removed-identity-audit-v1-root-forward-001"
    output_root = DATA / "families/F1" / case_id / attempt_id
    if output_root.exists():
        raise FileExistsError(output_root)
    static = [REQUEST_BUILDER, WORKER, RECEIPT, RUNPARTS, XML, DECODER, DECODER_SOURCE, DISPATCH, STRICT, RUNTIME, PROOF]
    static = list(dict.fromkeys(path.expanduser().resolve() for path in static))
    input_hashes = {str(path): sha256(path) for path in static}
    request = {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "audit",
        "family_id": "F1", "sentinel_id": "F1-S1", "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": case_id, "attempt_id": attempt_id,
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(WORKER.resolve()),
            "--raw-root", str(RAW_ROOT), "--runparts", str(RUNPARTS), "--generated-xml", str(XML),
            "--receipt", str(RECEIPT), "--decoder", str(DECODER), "--scratch-root", "{attempt_root}/scratch/removed-id",
            "--expected-frame-count", str(rows), "--expected-final-time-s", repr(final_time), "--final-time-tolerance-s", "1e-12",
            "--output", f"{{attempt_root}}/report/{output_name}",
        ],
        "cwd": str(REPO), "worktree_root": str(REPO), "input_files": [str(path) for path in static],
        "input_hashes": input_hashes, "deferred_input_files": [str(RAW_ROOT), str(RAW_ROOT / "Part_0000.bi4"), str(RAW_ROOT / f"Part_{rows - 1:04d}.bi4")],
        "deferred_hash_policy": {
            "selected_frames_only": [0, rows - 1], "pre_post_complete_stat_and_sha": "required around each decoder invocation",
            "full_raw_tree_hash": "NOT_COMPUTED_BY_WORKER", "full_tree_copy": "FORBIDDEN", "positions_read": False,
            "velocities_read": False, "density_read": False,
        },
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800,
        "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_FIRST_AND_TERMINAL_PART_BYTES",
        "estimated_storage_bytes": 2 * (1 << 30), "estimated_peak_memory_bytes": 2 * (1 << 30),
        "output": {"path": f"{{attempt_root}}/report/{output_name}", "atomic": True, "refuse_overwrite": True},
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "hdf5_read": False, "bi4_decode": True,
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "source_output_protection": "read-only source; two deferred Part files only"},
        "source_binding": {"schema": SCHEMA, "terminal_solver_receipt": record(RECEIPT), "runparts": record(RUNPARTS), "solver_input_xml": record(XML), "root_solver_proof": record(PROOF), "raw_root": str(RAW_ROOT), "first_frame": 0, "terminal_frame": rows - 1, "expected_removed_count": 1, "identity_basis": "Idp set difference classified against XML execution/particles typed ranges"},
        "qualification_stage": "stage2_f1_owner_removed_identity_diagnostic_pending_parent_v8_cpu_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "two-frame Idp identity diagnostic only"},
    }
    atomic(output, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.output)
    print(json.dumps({"status": "PASS_REQUEST_BUILT", "output": str(args.output.resolve()), "frames": value["deferred_input_files"][-2:]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
