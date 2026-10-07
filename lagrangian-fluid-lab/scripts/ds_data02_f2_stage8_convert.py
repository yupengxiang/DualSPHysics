#!/usr/bin/env python3
"""Trajectory conversion and request generator for Family F2 Stage 8 production cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

FAMILY_ID = "F2"
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F2"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
BIN_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = BIN_ROOT / "PartVTK_linux64"
CONVERT_PY = REPO / "scripts/ds_data02_direct_convert.py"

STAGE8_CASES = [
    ("F2_CENTER_P01", "center_catch", 400),
    ("F2_OFFSET_P01", "offset_spill", 400),
    ("F2_CENTER_P02", "center_catch", 400),
    ("F2_OFFSET_P02", "offset_spill", 400),
    ("F2_CENTER_P03", "center_catch", 400),
    ("F2_OFFSET_P03", "offset_spill", 400),
    ("F2_CENTER_P04", "center_catch", 400),
    ("F2_OFFSET_P04", "offset_spill", 400),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def emit_f2_stage8_conversion_request(case_id: str, mech: str, last_frame: int = 400) -> Path:
    case_data_dir = DATA_ROOT / "families/F2" / case_id

    # Find latest completed qualification run
    qual_dirs = sorted(case_data_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_receipt = None
    solver_dir = None
    for qd in reversed(qual_dirs):
        rec = qd / "execution-receipt.json"
        if rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0:
                    solver_receipt = rec
                    solver_dir = qd / "solver"
                    break
            except Exception:
                pass
    if not solver_receipt or not solver_dir:
        raise FileNotFoundError(f"missing completed solver receipt for {case_id}")

    # Find latest completed GenCase run
    gencase_dirs = sorted(case_data_dir.glob(f"{case_id}_GENCASE_*"))
    gencase_receipt = None
    gencase_dir = None
    for gd in reversed(gencase_dirs):
        rec = gd / "execution-receipt.json"
        if rec.is_file():
            try:
                data = json.loads(rec.read_text())
                if data.get("status") == "completed" and data.get("returncode") == 0 and data.get("fluid_particles", 0) > 0:
                    gencase_receipt = rec
                    gencase_dir = gd
                    break
            except Exception:
                pass
    if not gencase_receipt or not gencase_dir:
        raise FileNotFoundError(f"missing completed gencase receipt for {case_id}")

    generated_xml = gencase_dir / f"{case_id}.xml"
    gencase_bi4 = gencase_dir / f"{case_id}.bi4"
    solver_log = solver_dir / "Run.out"
    data_root = solver_dir / "data"

    part_0000 = data_root / "Part_0000.bi4"
    part_last = data_root / f"Part_{last_frame:04d}.bi4"

    owner_metadata = FAMILY_DIR / f"production/owner_metadata/{case_id}.owner.json"

    for p in (data_root, generated_xml, gencase_bi4, solver_log, solver_receipt, gencase_receipt, part_0000, part_last, DECODER, PARTVTK, CONVERT_PY, owner_metadata):
        if not p.exists():
            raise FileNotFoundError(f"missing conversion prerequisite for {case_id}: {p}")

    attempt_id = "full-typed-native-conversion-001"
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 4,
        "max_wall_seconds": 1200,
        "estimated_storage_bytes": 2 * 1024**3,
        "worktree_root": str(REPO.parent),
        "cwd": str(REPO),
        "command": [
            str(REPO / ".venv/bin/python"),
            str(CONVERT_PY),
            "--data-root", str(data_root),
            "--generated-xml", str(generated_xml),
            "--solver-log", str(solver_log),
            "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/conversion-report.json",
            "--solver-receipt", str(solver_receipt),
            "--gencase-receipt", str(gencase_receipt),
            "--owner-metadata", str(owner_metadata),
            "--decoder", str(DECODER),
            "--partvtk", str(PARTVTK),
            "--validation-dir", "{attempt_root}/partvtk-validation",
            "--keep-validation-csv",
        ],
        "input_files": [
            str(CONVERT_PY),
            str(owner_metadata),
            str(gencase_receipt),
            str(solver_receipt),
            str(generated_xml),
            str(solver_log),
            str(DECODER),
            str(PARTVTK),
            str(gencase_bi4),
            str(part_0000),
            str(part_last),
        ],
    }

    req_dir = FAMILY_DIR / "requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    req_path = req_dir / f"{case_id}-conversion.json"
    req_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return req_path


def run_direct_conversion(case_id: str, mech: str, last_frame: int = 400) -> dict:
    case_dir = DATA_ROOT / "families/F2" / case_id
    attempt_dir = case_dir / "full-typed-native-conversion-001"
    traj_file = attempt_dir / "trajectory.h5"
    report_file = attempt_dir / "conversion-report.json"

    if traj_file.is_file() and report_file.is_file():
        print(f"Case {case_id} already converted: {traj_file}")
        return {"case_id": case_id, "status": "already_exists", "path": str(traj_file)}

    attempt_dir.mkdir(parents=True, exist_ok=True)

    case_data_dir = DATA_ROOT / "families/F2" / case_id
    qual_dirs = sorted(case_data_dir.glob(f"{case_id}_QUALIFICATION_*"))
    solver_receipt = next(qd / "execution-receipt.json" for qd in reversed(qual_dirs) if (qd / "execution-receipt.json").is_file())
    solver_dir = solver_receipt.parent / "solver"

    gencase_dirs = sorted(case_data_dir.glob(f"{case_id}_GENCASE_*"))
    gencase_receipt = next(gd / "execution-receipt.json" for gd in reversed(gencase_dirs) if (gd / "execution-receipt.json").is_file())
    gencase_dir = gencase_receipt.parent

    generated_xml = gencase_dir / f"{case_id}.xml"
    solver_log = solver_dir / "Run.out"
    data_root = solver_dir / "data"
    owner_metadata = FAMILY_DIR / f"production/owner_metadata/{case_id}.owner.json"

    cmd = [
        str(REPO / ".venv/bin/python"),
        str(CONVERT_PY),
        "--data-root", str(data_root),
        "--generated-xml", str(generated_xml),
        "--solver-log", str(solver_log),
        "--output", str(traj_file),
        "--report", str(report_file),
        "--solver-receipt", str(solver_receipt),
        "--gencase-receipt", str(gencase_receipt),
        "--owner-metadata", str(owner_metadata),
        "--decoder", str(DECODER),
        "--partvtk", str(PARTVTK),
        "--validation-dir", str(attempt_dir / "partvtk-validation"),
        "--keep-validation-csv",
    ]

    print(f"Converting {case_id}...")
    t0 = time.monotonic()
    res = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    elapsed = time.monotonic() - t0

    if res.returncode != 0:
        print(f"FAILED {case_id} (code {res.returncode}):\n{res.stderr[-500:]}")
        return {"case_id": case_id, "status": "failed", "error": res.stderr}

    print(f"Completed {case_id} conversion in {elapsed:.1f}s")
    return {"case_id": case_id, "status": "completed", "path": str(traj_file), "elapsed_seconds": elapsed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-only", action="store_true", help="Only emit request JSONs")
    parser.add_argument("--run-direct", action="store_true", help="Run conversion directly in process")
    parser.add_argument("--cases", nargs="*", help="Specific cases to convert")
    args = parser.parse_args()

    cases = STAGE8_CASES
    if args.cases:
        cases = [c for c in cases if c[0] in args.cases]

    results = []
    for cid, mech, lf in cases:
        req_path = emit_f2_stage8_conversion_request(cid, mech, lf)
        print(f"Emitted conversion request: {req_path}")
        if args.run_direct:
            res = run_direct_conversion(cid, mech, lf)
            results.append(res)

    if results:
        summary_path = FAMILY_DIR / "stage8_conversion_summary.json"
        summary_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote conversion summary to {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
