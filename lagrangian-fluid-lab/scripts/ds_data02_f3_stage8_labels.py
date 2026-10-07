#!/usr/bin/env python3
"""Materialize native transport labels for F3 Stage 8 production cases."""

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

DATA_F3 = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3")
CONFIG_DUAL = REPO / "campaigns/ds-data-02/families/F3/labels/dual_axis_event_config.json"
CONFIG_BAFFLE = REPO / "campaigns/ds-data-02/families/F3/labels/eccentric_baffle_event_config.json"
SUMMARY_PATH = REPO / "campaigns/ds-data-02/families/F3/stage8_labels_summary.json"

DUAL_CASES = [
    "F3_NEW_DUAL_AXIS_PHASE_00",
    "F3_NEW_DUAL_AXIS_PHASE_01",
    "F3_NEW_DUAL_AXIS_PHASE_02",
    "F3_NEW_DUAL_AXIS_PHASE_03",
]

BAFFLE_CASES = [
    "F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_00",
    "F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_01",
    "F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_02",
    "F3_NEW_ECCENTRIC_BAFFLE_EXCHANGE_03",
]

STAGE8_CASES = DUAL_CASES + BAFFLE_CASES


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_case(case_id: str, is_dual: bool, overwrite: bool = False) -> dict:
    case_dir = DATA_F3 / case_id
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Case directory {case_dir} not found")

    # Find latest conversion trajectory
    trajs = sorted(case_dir.glob("full-typed-native-conversion-*/trajectory.h5"))
    if not trajs:
        raise FileNotFoundError(f"No trajectory.h5 found for {case_id}")
    source_h5 = trajs[-1]

    config_path = CONFIG_DUAL if is_dual else CONFIG_BAFFLE
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

    # Materialize labels
    res = materialize(source_h5, output_h5, config, particle_chunk=65536)
    elapsed = time.monotonic() - start_time

    receipt = {
        "schema": "ds02.f3.labels-receipt.v1",
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
        "elapsed_seconds": elapsed,
        "output": str(output_h5),
        "receipt": receipt,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=None, help="Specific cases to run")
    parser.add_argument("--group", choices=["dual", "baffle", "all"], default="all", help="Subset to run")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing labels")
    args = parser.parse_args()

    targets = []
    if args.cases:
        for c in args.cases:
            targets.append((c, c in DUAL_CASES))
    else:
        if args.group in ("dual", "all"):
            targets.extend([(c, True) for c in DUAL_CASES])
        if args.group in ("baffle", "all"):
            targets.extend([(c, False) for c in BAFFLE_CASES])

    results = []
    existing_summary = {}
    if SUMMARY_PATH.exists():
        try:
            existing_summary = {r["case_id"]: r for r in json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))}
        except Exception:
            pass

    for cid, is_dual in targets:
        try:
            res = process_case(cid, is_dual, overwrite=args.overwrite)
            results.append(res)
            existing_summary[cid] = res
        except Exception as e:
            print(f"[{now_str()}] ERROR processing {cid}: {e}", file=sys.stderr)
            res = {"case_id": cid, "status": "failed", "error": str(e)}
            results.append(res)
            existing_summary[cid] = res

        # Update summary file incrementally
        SUMMARY_PATH.write_text(json.dumps(list(existing_summary.values()), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"[{now_str()}] Finished processing {len(targets)} cases. Summary written to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
