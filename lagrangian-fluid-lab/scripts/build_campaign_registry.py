#!/usr/bin/env python3
"""Build the authoritative v0.1-candidate registry from planned case sources."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns" / "v0.1-candidate"
OUTPUT = CAMPAIGN / "case-registry.json"


def simulation_dimension(run_out: Path):
    if not run_out.is_file():
        return "unknown"
    text = run_out.read_text(errors="replace")
    match = re.search(r"\*\*(2D|3D)-Simulation parameters", text)
    return match.group(1) if match else "unknown"


def main():
    custom = json.loads((ROOT / "cases" / "manifest.json").read_text())["cases"]
    official = json.loads((ROOT / "reports" / "runtime" / "official-prepare-summary.json").read_text())["cases"]
    records = []
    for record in custom:
        records.append({
            "id": record["id"], "origin": "custom", "family": record["family"],
            "mechanism": record["mechanism"], "dimension": "3D",
            "lineage_group_id": record["id"], "campaign_role": "development/evaluation",
            "expected_outcome": "usable_probe", "reference_level": "mechanism_probe",
            "planned": True,
        })
    for record in official:
        lineage = "O5_wave_runup" if record["id"].startswith("O5_wave_runup") else record["id"]
        records.append({
            "id": record["id"], "origin": "official", "family": record["family"],
            "mechanism": record["mechanism"],
            "dimension": simulation_dimension(ROOT / "runs-official" / record["id"] / "Run.out"),
            "lineage_group_id": lineage, "campaign_role": "development/evaluation",
            "expected_outcome": "quality_failed" if record["id"] == "O5_wave_runup" else "usable_probe",
            "reference_level": "interface_probe",
            "planned": True,
        })
    records.sort(key=lambda item: item["id"])
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    output = {
        "schema_version": 1,
        "campaign_id": "v0.1-candidate",
        "baseline_commit": "0329009f469e7778cdbf6fe1fd09df2d5a13ea69",
        "data_class": "development_only",
        "formal_test_data": False,
        "case_count": len(records),
        "cases": records,
    }
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n")
    print(f"wrote {len(records)} planned cases to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
