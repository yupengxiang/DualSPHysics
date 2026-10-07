#!/usr/bin/env python3
"""Materialize native transport labels for F5 Stage 8 production cases."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from ds_data02_f5_native import audit_transport, get_case_spec, sha256

DATA_F5 = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
FAMILY_DIR = REPO / "campaigns/ds-data-02/families/F5"
EVENT_DEFINITIONS = FAMILY_DIR / "event_definitions.json"
QUALITY_CONTRACT = FAMILY_DIR / "quality_contract.json"
SUMMARY_PATH = FAMILY_DIR / "stage8_labels_summary.json"

STAGE8_CASES = [
    "F5_RUNUP_00",
    "F5_WEIR_00",
    "F5_RUNUP_01",
    "F5_WEIR_01",
    "F5_RUNUP_02",
    "F5_WEIR_02",
    "F5_RUNUP_03",
    "F5_WEIR_03",
]


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_case(case_id: str, overwrite: bool = False) -> dict:
    case_dir = DATA_F5 / case_id
    if not case_dir.is_dir():
        raise FileNotFoundError(f"Case directory {case_dir} not found")

    trajs = sorted(case_dir.glob("full-typed-native-conversion-*/trajectory.h5"))
    if not trajs:
        raise FileNotFoundError(f"No trajectory.h5 found for {case_id}")
    source_h5 = trajs[-1]

    # Owner metadata
    owner_path = FAMILY_DIR / f"production/owner_metadata/{case_id}.owner.json"
    if not owner_path.is_file():
        raise FileNotFoundError(f"Missing owner metadata for {case_id}: {owner_path}")

    # Metadata & motion path
    meta_path = FAMILY_DIR / f"production/definitions/{case_id}.metadata.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Missing case definition metadata for {case_id}: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    motion_path = Path(meta["motion_path"])
    if not motion_path.is_file():
        raise FileNotFoundError(f"Missing motion file {motion_path}")

    # Solver output
    solver_dir = case_dir / f"{case_id}_QUALIFICATION_004/solver"
    if not solver_dir.is_dir():
        # Fallback to any completed qualification solver
        quals = sorted(case_dir.glob(f"{case_id}_QUALIFICATION_*/solver"))
        if not quals:
            raise FileNotFoundError(f"No solver directory found for {case_id}")
        solver_dir = quals[-1]

    attempt_dir = case_dir / "native-transport-labels-001"
    output_h5 = attempt_dir / "native-labels.h5"
    transport_h5 = attempt_dir / "transport-labels.h5"
    audit_path = attempt_dir / "transport-audit.json"
    preview_path = attempt_dir / "preview.json"
    receipt_path = attempt_dir / "execution-receipt.json"

    if output_h5.exists() and not overwrite:
        print(f"[{now_str()}] Case {case_id} labels already exist: {output_h5}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
        return {"case_id": case_id, "status": "already_exists", "output": str(output_h5), "receipt": receipt}

    attempt_dir.mkdir(parents=True, exist_ok=True)
    if overwrite:
        for p in (output_h5, transport_h5, audit_path, preview_path, receipt_path):
            if p.exists() or p.is_symlink():
                p.unlink()

    print(f"[{now_str()}] Starting native transport label extraction for {case_id}...")
    start_time = time.monotonic()

    audit_result = audit_transport(
        case_id=case_id,
        hdf5_path=source_h5,
        owner_path=owner_path,
        motion_path=motion_path,
        solver_output=solver_dir,
        event_path=EVENT_DEFINITIONS,
        quality_path=QUALITY_CONTRACT,
        output=audit_path,
        preview=preview_path,
        labels_path=output_h5,
    )
    elapsed = time.monotonic() - start_time

    # Also symlink transport-labels.h5 -> native-labels.h5 for F5 consistency
    if not transport_h5.exists():
        try:
            transport_h5.symlink_to(output_h5.name)
        except Exception:
            pass

    out_hash = audit_result.get("transport_labels", {}).get("sha256") or sha256(output_h5)
    source_hash = audit_result.get("native", {}).get("hdf5_sha256") or sha256(source_h5)

    receipt = {
        "schema": "ds02.f5.labels-receipt.v1",
        "case_id": case_id,
        "attempt_id": "native-transport-labels-001",
        "source_trajectory": str(source_h5),
        "source_trajectory_sha256": source_hash,
        "config_path": str(EVENT_DEFINITIONS),
        "output_path": str(output_h5),
        "output_sha256": out_hash,
        "initial_fluid_mass_kg": audit_result["native"]["fluid_initial_mass_kg"],
        "frames": audit_result["native"]["frames"],
        "identities": audit_result["native"]["particle_count"],
        "fluid_particles": audit_result["native"]["fluid_particles"],
        "moving_particles": audit_result["native"]["moving_particles"],
        "fixed_particles": audit_result["native"]["fixed_particles"],
        "elapsed_seconds": elapsed,
        "created_at_utc": now_str(),
        "status": "completed",
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[{now_str()}] Completed {case_id} in {elapsed:.1f}s (sha256: {out_hash[:12]}...)")
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
    parser.add_argument("--group", choices=["runup", "weir", "all"], default="all", help="Subset to run")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing labels")
    args = parser.parse_args()

    runup_cases = [c for c in STAGE8_CASES if "RUNUP" in c]
    weir_cases = [c for c in STAGE8_CASES if "WEIR" in c]

    targets = []
    if args.cases:
        targets = args.cases
    else:
        if args.group in ("runup", "all"):
            targets.extend(runup_cases)
        if args.group in ("weir", "all"):
            targets.extend(weir_cases)

    results = []
    existing_summary = {}
    if SUMMARY_PATH.exists():
        try:
            existing_summary = {r["case_id"]: r for r in json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))}
        except Exception:
            pass

    for cid in targets:
        try:
            res = process_case(cid, overwrite=args.overwrite)
            results.append(res)
            existing_summary[cid] = res
        except Exception as e:
            print(f"[{now_str()}] ERROR processing {cid}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            res = {"case_id": cid, "status": "failed", "error": str(e)}
            results.append(res)
            existing_summary[cid] = res

        # Update summary incrementally
        SUMMARY_PATH.write_text(json.dumps(list(existing_summary.values()), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"[{now_str()}] Finished processing {len(targets)} cases. Summary written to {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
