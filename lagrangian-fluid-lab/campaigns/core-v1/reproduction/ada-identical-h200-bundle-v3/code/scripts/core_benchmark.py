#!/usr/bin/env python3
"""Portable Core entrypoint: import, verify, inspect, train, rollout, evaluate, reproduce."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import platform
import sys
import time

# Executable both by absolute script path and python -m scripts.core_benchmark.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.core_contract import updater_oracle
from scripts.core_dataset import CoreDataset, import_f3_manifest
from scripts.core_runtime import atomic_json, digest


def inspect_dataset(manifest, data_root):
    with CoreDataset(manifest, data_root) as data:
        cases = []
        for case in data.case_ids():
            state = data.read_state(case, 0)
            times = data.times(case)
            record = data.record(case)
            cases.append({"case_id": case, "family": record["family"], "split": record["split"],
                          "particles": state.count, "frames": len(times), "time_start_s": float(times[0]),
                          "time_end_s": float(times[-1]), "velocity_semantics": "native saved numerical velocity"})
        return {"schema": "core.inspection.v1", "manifest_sha256": digest(manifest), "case_count": len(cases),
                "families": dict(Counter(c["family"] for c in cases)),
                "splits": dict(Counter(c["split"] for c in cases)), "cases": cases,
                "scientific_status": "source_claims_only; inspection does not qualify data"}


def verify_dataset(manifest, data_root, *, case_ids=None, full_scan=False):
    started = time.monotonic()
    records = []
    with CoreDataset(manifest, data_root) as data:
        cases = case_ids or data.case_ids()
        for case in cases:
            hashes = data.verify_sources([case])
            # File integrity alone cannot validate the reconstructed public
            # inputs: also check their semantic contract hash.
            data.known_inputs(case)
            n = len(data.times(case))
            indices = range(n - 1) if full_scan else sorted({0, (n - 1) // 2, n - 2})
            oracles = [data.oracle(case, i) for i in indices]
            passed = all(o["position_max_abs_error"] < 1e-10 and o["native_velocity_max_abs_error"] < 1e-10 for o in oracles)
            records.append({"case_id": case, "sha256": hashes[case], "full_particle_axis": True,
                            "transition_count": len(oracles), "passed": passed, "oracles": oracles})
    return {"schema": "core.verification.v1", "passed": all(c["passed"] for c in records),
            "full_temporal_scan": full_scan, "case_count": len(records), "cases": records,
            "wall_seconds": time.monotonic() - started, "host": platform.node(),
            "manifest_sha256": digest(manifest), "qualification_inferred": False}


def reproduce(manifest, data_root, case_ids=None, source_host=None):
    root = Path(data_root).resolve()
    result = verify_dataset(manifest, root, case_ids=case_ids)
    # Source assets come exclusively from the supplied root; known inputs are embedded.
    with CoreDataset(manifest, root) as data:
        for case in case_ids or data.case_ids():
            row = data.record(case)
            (root / row["hdf5"]).resolve().relative_to(root)
    return {"schema": "core.reader_reproduction.v1", "passed": result["passed"],
            "source_host": source_host, "reproduction_host": platform.node(), "data_root": str(root),
            "verification": result, "scope": "reader, full-axis oracle, hashes; GPU model reproduction is separate",
            "full_product_reproduction": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import-f3")
    p.add_argument("--source-manifest", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--inline-v1", action="store_true", help="legacy diagnostic only: embeds large control arrays")
    p.add_argument("--asset-dir", type=Path)
    for command in ("inspect", "verify", "reproduce"):
        p = sub.add_parser(command)
        p.add_argument("--manifest", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--output", type=Path)
        if command != "inspect":
            p.add_argument("--case-id", action="append")
        if command == "verify":
            p.add_argument("--full-scan", action="store_true")
        if command == "reproduce":
            p.add_argument("--source-host")
    # Delegate without silently swallowing unsupported flags.
    for command in ("train", "profile", "rollout", "evaluate", "evaluate-checkpoints"):
        sub.add_parser(command, add_help=False).add_argument("args", nargs=argparse.REMAINDER)
    if len(sys.argv) > 1 and sys.argv[1] in ("train", "profile", "rollout", "evaluate", "evaluate-checkpoints"):
        from scripts import core_learning
        sys.argv[0] = "core_learning"
        return core_learning.main()
    args = parser.parse_args()
    if args.command == "import-f3":
        result = import_f3_manifest(args.source_manifest, args.data_root, compact=not args.inline_v1,
                                    asset_dir=args.asset_dir)
    elif args.command == "inspect":
        result = inspect_dataset(args.manifest, args.data_root)
    elif args.command == "verify":
        result = verify_dataset(args.manifest, args.data_root, case_ids=args.case_id, full_scan=args.full_scan)
    else:
        result = reproduce(args.manifest, args.data_root, args.case_id, args.source_host)
    if args.output:
        atomic_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key not in ("cases", "verification")}, indent=2))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
