#!/usr/bin/env python3
"""Generate direct conversion requests for F1 Stage 8 production cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_f1 import FAMILY_DIR, sha256_file
FAMILY_ID = "F1"

DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
BIN_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = BIN_ROOT / "PartVTK_linux64"
CONVERT_PY = REPO / "scripts/ds_data02_direct_convert.py"

STAGE8_CASES = [
    ("F1_ECC_P01_FINE", "eccentric_obstacle", 160),
    ("F1_ECC_P02_FINE", "eccentric_obstacle", 160),
    ("F1_ECC_P03_FINE", "eccentric_obstacle", 160),
    ("F1_ECC_P04_FINE", "eccentric_obstacle", 160),
    ("F1_DUAL_P01_FINE", "asymmetric_dual_channel", 600),
    ("F1_DUAL_P02_FINE", "asymmetric_dual_channel", 600),
    ("F1_DUAL_P03_FINE", "asymmetric_dual_channel", 600),
    ("F1_DUAL_P04_FINE", "asymmetric_dual_channel", 600),
]


def emit_f1_stage8_conversion_request(case_id: str, mech: str, last_frame: int, family_dir: Path = FAMILY_DIR) -> Path:
    family_dir = Path(family_dir).resolve()
    metadata_path = family_dir / f"production/definitions/{case_id}.metadata.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"missing metadata: {metadata_path}")

    case_data_dir = DATA_ROOT / "families/F1" / case_id

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

    for p in (data_root, generated_xml, gencase_bi4, solver_log, solver_receipt, gencase_receipt, part_0000, part_last, DECODER, PARTVTK, CONVERT_PY):
        if not p.exists():
            raise FileNotFoundError(f"missing conversion prerequisite: {p}")

    is_dual = mech == "asymmetric_dual_channel"
    storage_est = 35 * 1024**3 if is_dual else 2 * 1024**3
    wall_sec = 5400 if is_dual else 600

    # Determine attempt_id: find next available or unused attempt
    case_dir = DATA_ROOT / "families/F1" / case_id
    existing_attempts = sorted(case_dir.glob("full-typed-native-conversion-*"))
    attempt_num = 1
    for ea in existing_attempts:
        try:
            num = int(ea.name.split("-")[-1])
            attempt_num = max(attempt_num, num + 1)
        except ValueError:
            pass
    # If the latest existing attempt directory actually has a completed trajectory.h5, keep it
    # Otherwise next available attempt_id
    attempt_id = f"full-typed-native-conversion-{attempt_num:03d}"
    if not existing_attempts:
        attempt_id = "full-typed-native-conversion-001"

    command = [
        str(sys.executable),
        str(CONVERT_PY),
        "--data-root", str(data_root),
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
        "family_id": "F1",
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
            req_path = emit_f1_stage8_conversion_request(cid, mech, last_f)
            print(f"Emitted: {req_path.name}")
            emitted.append(req_path)
        except Exception as e:
            print(f"Skipping {cid}: {e}")

    print(f"Successfully generated {len(emitted)} F1 conversion requests.")


if __name__ == "__main__":
    main()
