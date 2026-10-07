#!/usr/bin/env python3
"""Materialize native transport labels for F6 Stage 8 production cases."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_native_labels import materialize, digest

DATA_F6 = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6")
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F6"
CONFIG_SIMPLE = FAMILY_DIR / "labels/simple_free_response_event_config.json"
CONFIG_WAVE = FAMILY_DIR / "labels/wave_no_contact_event_config.json"
SUMMARY_PATH = FAMILY_DIR / "stage8_labels_summary.json"

SIMPLE_CASES = [
    "F6_000_simple_free_response",
    "F6_002_simple_free_response",
    "F6_004_simple_free_response",
    "F6_006_simple_free_response",
]

WAVE_CASES = [
    "F6_001_wave_no_contact",
    "F6_003_wave_no_contact",
    "F6_005_wave_no_contact",
    "F6_007_wave_no_contact",
]

STAGE8_CASES = [
    "F6_000_simple_free_response",
    "F6_001_wave_no_contact",
    "F6_002_simple_free_response",
    "F6_003_wave_no_contact",
    "F6_004_simple_free_response",
    "F6_005_wave_no_contact",
    "F6_006_simple_free_response",
    "F6_007_wave_no_contact",
]


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_case(case_id: str, is_simple: bool, *, overwrite: bool = False, source_trajectory: Path | None = None) -> dict[str, Any]:
    case_dir = DATA_F6 / case_id

    if source_trajectory and Path(source_trajectory).is_file():
        source_h5 = Path(source_trajectory).resolve()
        attempt_dir = source_h5.parent
    else:
        if not case_dir.is_dir():
            raise FileNotFoundError(f"Case directory {case_dir} not found")

        # Find latest conversion trajectory
        trajs = sorted(case_dir.glob("full-typed-native-conversion-*/trajectory.h5"))
        if not trajs:
            raise FileNotFoundError(f"No trajectory.h5 found for {case_id}")
        source_h5 = trajs[-1]
        attempt_dir = case_dir / "native-transport-labels-001"

    config_path = CONFIG_SIMPLE if is_simple else CONFIG_WAVE
    config = json.loads(config_path.read_text(encoding="utf-8"))

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
        "schema": "ds02.f6.labels-receipt.v1",
        "case_id": case_id,
        "family_id": "F6",
        "mechanism_id": "simple_free_response" if is_simple else "wave_no_contact",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="*", default=None, help="Specific case IDs to run")
    parser.add_argument("--trajectory", type=Path, help="Direct trajectory file to run")
    parser.add_argument("--group", choices=["simple", "wave", "all"], default="all", help="Subset of cases to run")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing labels")
    args = parser.parse_args()

    if args.trajectory:
        traj_path = Path(args.trajectory).resolve()
        cid = traj_path.parent.parent.name
        is_simple = "wave" not in cid.lower()
        res = process_case(cid, is_simple, overwrite=args.overwrite, source_trajectory=traj_path)
        print(f"Label generation complete: {res['output']}")
        return 0

    targets = []
    if args.cases:
        for c in args.cases:
            targets.append((c, c in SIMPLE_CASES or "wave" not in c.lower()))
    else:
        if args.group in ("simple", "all"):
            targets.extend([(c, True) for c in SIMPLE_CASES])
        if args.group in ("wave", "all"):
            targets.extend([(c, False) for c in WAVE_CASES])

    results = []
    existing_summary = {}
    if SUMMARY_PATH.exists():
        try:
            existing_summary = {r["case_id"]: r for r in json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))}
        except Exception:
            pass

    for cid, is_simple in targets:
        try:
            res = process_case(cid, is_simple, overwrite=args.overwrite)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
