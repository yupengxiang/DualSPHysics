#!/usr/bin/env python3
"""Reprocess immutable first-round CSV evidence through the campaign converter."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .postprocess_cases import normalize
except ImportError:  # Direct script execution.
    from postprocess_cases import normalize


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns" / "v0.1-candidate"
DATA_ROOT = CAMPAIGN / "data"
REPORT = CAMPAIGN / "w01-streaming-audits.json"
RUNTIME = ROOT / "reports" / "runtime"


def load(name):
    return json.loads((RUNTIME / name).read_text())


def csv_paths(run_root, case_id):
    return sorted((run_root / case_id / "csv").glob("Particles_[0-9][0-9][0-9][0-9].csv"))


def main():
    groups = [
        ("custom", ROOT / "runs", load("run-summary.json"), load("prepare-summary.json")),
        ("official", ROOT / "runs-official", load("official-run-summary.json"),
         load("official-prepare-summary.json")),
    ]
    results = []
    for origin, run_root, runs, prepared in groups:
        prepared_by_id = {case["id"]: case for case in prepared["cases"]}
        for run in runs["cases"]:
            if run["status"] != "completed":
                continue
            record = {**run, "shifting": prepared_by_id[run["id"]].get("shifting")}
            paths = csv_paths(run_root, run["id"])
            if not paths:
                raise RuntimeError(f"immutable CSV evidence is missing for {run['id']}")
            audit = normalize(record, paths, run_root=run_root, data_root=DATA_ROOT)
            audit["origin"] = origin
            results.append(audit)
            print(f"{run['id']:28s} frames={audit['frames']:2d} ids={audit['identity_keys']:6d}")
    results.sort(key=lambda case: case["id"])
    report = {"schema_version": 1, "converter_schema": 3, "case_count": len(results),
              "source_evidence": "immutable first-round PartVTK CSV", "cases": results}
    REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"converted={len(results)} report={REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
