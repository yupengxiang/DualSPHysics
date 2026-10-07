#!/usr/bin/env python3
"""Generate direct conversion requests for F3 Stage 8 production cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

FAMILY_ID = "F3"
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F3"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
BIN_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = BIN_ROOT / "PartVTK_linux64"
CONVERT_PY = REPO / "scripts/ds_data02_direct_convert.py"

STAGE8_CASES = [
    ("F3_NEW_DUAL_AXIS_PHASE_00", "dual_axis_phase", 4000),
    ("F3_NEW_DUAL_AXIS_PHASE_01", "dual_axis_phase", 4000),
    ("F3_NEW_DUAL_AXIS_PHASE_02", "dual_axis_phase", 4000),
    ("F3_NEW_DUAL_AXIS_PHASE_03", "dual_axis_phase", 4000),
    ("F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_00", "eccentric_baffle_exchange", 4000),
    ("F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_01", "eccentric_baffle_exchange", 4000),
    ("F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_02", "eccentric_baffle_exchange", 4000),
    ("F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_03", "eccentric_baffle_exchange", 4000),
]


def emit_f3_stage8_conversion_request(case_id: str, mech: str, last_frame: int, family_dir: Path = FAMILY_DIR) -> Path:
    family_dir = Path(family_dir).resolve()
    metadata_path = family_dir / f"production/owner_metadata/{case_id}.owner.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"missing owner metadata: {metadata_path}")

    case_data_dir = DATA_ROOT / "families/F3" / case_id

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

    # GenCase outputs
    gencase_dir = case_data_dir / f"{case_id}_GENCASE_01"
    gencase_receipt = gencase_dir / "execution-receipt.json"
    generated_xml = gencase_dir / f"{case_id}.xml"
    gencase_bi4 = gencase_dir / f"{case_id}.bi4"
    solver_log = solver_dir / "Run.out"

    for req_file in (gencase_receipt, generated_xml, gencase_bi4, solver_log):
        if not req_file.is_file():
            raise FileNotFoundError(f"missing required file for {case_id}: {req_file}")

    part_0000 = solver_dir / "data/Part_0000.bi4"
    part_last = solver_dir / f"data/Part_{last_frame:04d}.bi4"

    if not part_0000.is_file():
        raise FileNotFoundError(f"missing first part file for {case_id}: {part_0000}")
    if not part_last.is_file():
        # Fallback to the latest available Part_*.bi4
        part_files = sorted((solver_dir / "data").glob("Part_*.bi4"))
        if not part_files:
            raise FileNotFoundError(f"no Part_*.bi4 files found in {solver_dir / 'data'}")
        part_last = part_files[-1]

    attempt_id = "full-typed-native-conversion-004"
    storage_est = 8 * 1024 * 1024 * 1024  # 8 GiB for 4001 frames of 108k particles
    wall_sec = 3600

    command = [
        str(REPO / ".venv/bin/python"),
        str(CONVERT_PY),
        "--data-root", str(solver_dir / "data"),
        "--generated-xml", str(generated_xml),
        "--solver-log", str(solver_log),
        "--output", "{attempt_root}/trajectory.h5",
        "--report", "{attempt_root}/conversion-report.json",
        "--solver-receipt", str(solver_receipt),
        "--gencase-receipt", str(gencase_receipt),
        "--owner-metadata", str(metadata_path),
        "--decoder", str(DECODER),
        "--partvtk", str(PARTVTK),
        "--validation-dir", "{attempt_root}/partvtk-validation",
        "--keep-validation-csv",
    ]

    input_files = [
        str(CONVERT_PY),
        str(metadata_path),
        str(gencase_receipt),
        str(solver_receipt),
        str(generated_xml),
        str(solver_log),
        str(DECODER),
        str(PARTVTK),
        str(gencase_bi4),
        str(part_0000),
        str(part_last),
    ]

    req = {
        "schema": "ds02.request.v1",
        "family_id": "F3",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "cpu_threads": 4,
        "max_wall_seconds": wall_sec,
        "estimated_storage_bytes": storage_est,
        "worktree_root": str(REPO.parent),
        "cwd": str(REPO),
        "command": command,
        "input_files": input_files,
    }

    requests_dir = family_dir / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)
    req_path = requests_dir / f"{case_id}-conversion.json"
    req_path.write_text(json.dumps(req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return req_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=[c[0] for c in STAGE8_CASES])
    args = parser.parse_args()

    specs = {c[0]: (c[1], c[2]) for c in STAGE8_CASES}
    emitted = []
    for cid in args.cases:
        if cid not in specs:
            continue
        mech, last_f = specs[cid]
        try:
            req_path = emit_f3_stage8_conversion_request(cid, mech, last_f)
            print(f"Emitted: {req_path.name}")
            emitted.append(req_path)
        except Exception as e:
            print(f"Skipping {cid}: {e}")

    print(f"Successfully generated {len(emitted)} F3 conversion requests.")


if __name__ == "__main__":
    main()
