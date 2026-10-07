#!/usr/bin/env python3
"""Materialize native transport labels for F2 Stage 8 production cases."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_native_labels import materialize, digest

DATA_F2 = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")
CONFIG_CENTER = REPO / "campaigns/ds-data-02/families/F2/labels/center_catch_event_config.json"
CONFIG_OFFSET = REPO / "campaigns/ds-data-02/families/F2/labels/offset_spill_event_config.json"
SUMMARY_PATH = REPO / "campaigns/ds-data-02/families/F2/stage8_labels_summary.json"

CENTER_CASES = [
    "F2_CENTER_P01",
    "F2_CENTER_P02",
    "F2_CENTER_P03",
    "F2_CENTER_P04",
]

OFFSET_CASES = [
    "F2_OFFSET_P01",
    "F2_OFFSET_P02",
    "F2_OFFSET_P03",
    "F2_OFFSET_P04",
]

STAGE8_CASES = CENTER_CASES + OFFSET_CASES


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_case(case_id: str, is_center: bool, overwrite: bool = False) -> dict:
    case_dir = DATA_F2 / case_id
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Case directory {case_dir} not found")

    trajs = sorted(case_dir.glob("full-typed-native-conversion-*/trajectory.h5"))
    if not trajs:
        raise FileNotFoundError(f"No trajectory.h5 found for {case_id}")
    source_h5 = trajs[-1]

    config_path = CONFIG_CENTER if is_center else CONFIG_OFFSET
    config = json.loads(config_path.read_text(encoding="utf-8"))

    attempt_dir = case_dir / "native-transport-labels-001"
    output_h5 = attempt_dir / "native-labels.h5"
    receipt_path = attempt_dir / "execution-receipt.json"

    if output_h5.exists() and not overwrite:
        print(f"[{now_str()}] Case {case_id} labels already exist: {output_h5}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
        return {"case_id": case_id, "status": "already_exists", "output": str(output_h5), "receipt": receipt}

    attempt_dir.mkdir(parents=True, exist_ok=True)
    if overwrite:
        for p in (output_h5, receipt_path):
            if p.exists():
                p.unlink()

    print(f"[{now_str()}] Starting label extraction for {case_id}...")
    start_time = time.monotonic()

    res = materialize(source_h5, output_h5, config, particle_chunk=65536)
    elapsed = time.monotonic() - start_time

    receipt = {
        "schema": "ds02.f2.labels-receipt.v1",
        "case_id": case_id,
        "attempt_id": "native-transport-labels-001",
        "source_trajectory": str(source_h5),
        "source_trajectory_sha256": digest(source_h5),
        "config_path": str(config_path),
        "output_path": str(output_h5),
        "output_sha256": res["sha256"],
        "initial_fluid_mass_kg": res["initial_fluid_mass_kg"],
        "frames": res["frames"],
        "identities": res["identities"],
        "elapsed_seconds": elapsed,
        "created_at_utc": now_str(),
        "status": "completed",
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Completed {case_id} in {elapsed:.1f}s (sha256: {res['sha256'][:12]}...)")
    return {
        "case_id": case_id,
        "status": "completed",
        "output": str(output_h5),
        "receipt": receipt,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", help="Specific cases to run")
    parser.add_argument("--group", choices=["center", "offset", "all"], default="all")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.cases:
        target_cases = [(cid, "CENTER" in cid) for cid in args.cases]
    elif args.group == "center":
        target_cases = [(cid, True) for cid in CENTER_CASES]
    elif args.group == "offset":
        target_cases = [(cid, False) for cid in OFFSET_CASES]
    else:
        target_cases = [(cid, "CENTER" in cid) for cid in STAGE8_CASES]

    results = []
    for cid, is_center in target_cases:
        try:
            res = process_case(cid, is_center, overwrite=args.overwrite)
            results.append(res)
        except Exception as e:
            print(f"[{now_str()}] Error processing {cid}: {e}", file=sys.stderr)
            results.append({"case_id": cid, "status": "failed", "error": str(e)})

    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Summary written to {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
