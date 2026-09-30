#!/usr/bin/env python3
"""Run the registered F4 observation operator over completed direct HDF5s."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.ds_data02_f4_observations import audit_observations
except ModuleNotFoundError:  # direct execution from the lab/scripts directory
    from ds_data02_f4_observations import audit_observations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--particle-chunk", type=int, default=65536)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    entries = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise SystemExit("F4 observation manifest must be a JSON array")
    results: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry["artifact_id"])
        attempt_root = args.output_root / name
        report = audit_observations(
            h5_path=Path(entry["h5"]),
            metadata_path=Path(entry["metadata"]),
            operators_path=Path(entry["operators"]),
            output=attempt_root / "f4-observation-report.json",
            labels_output=attempt_root / "source-regions.json",
            preview_output=attempt_root / "preview.json",
            timeseries_output=attempt_root / "macro-timeseries.csv",
            conversion_report_path=Path(entry["conversion_report"]),
            particle_chunk=args.particle_chunk,
        )
        results.append({
            "artifact_id": name,
            "case_id": entry["case_id"],
            "attempt_id": entry["attempt_id"],
            "report": str(attempt_root / "f4-observation-report.json"),
            "frames": report["shape"]["frames"],
            "particles": report["shape"]["particles"],
            "physical_binding_sha256": report["physical_binding_sha256"],
            "q_i_status": report["q_i_status"],
            "q_n_status": report["q_n_status"],
        })
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "batch-report.json").write_text(json.dumps({"schema": "ds02.f4.observation-batch.v1", "results": results, "q_n_status": "not_assessed"}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"artifacts": len(results), "output_root": str(args.output_root), "q_n_status": "not_assessed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
