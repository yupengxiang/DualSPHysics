#!/usr/bin/env python3
"""Validate fresh102 source-only metadata without touching scientific payloads."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))

def main():
    inv = load("inventory/existing-physical-condition-inventory.json")
    plan = load("source-plan.json")
    idx = load("requests/index.json")
    proposed = [r["physical_case_id"] for r in plan["rows"]]
    assert len(proposed) == 24 and len(set(proposed)) == 24
    assert inv["current_exact24"]["count"] == 24
    assert inv["historical_internal8"]["count"] == 8
    assert inv["set_relations"]["internal8_intersects_current24"] == []
    assert inv["set_relations"]["internal8_intersects_proposed24"] == []
    assert inv["set_relations"]["current24_intersects_proposed24"] == []
    assert inv["set_relations"]["registry_intersects_proposed24"] == []
    assert len(idx["rows"]) == 24 and idx["launch_allowed"] is False
    for row in idx["rows"]:
        req = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        assert req["disabled"] and not req["launch_allowed"] and not req["execution_allowed"]
        assert req["source_only"] and not req["jobs_started_by_source"] and not req["arrays_read_by_source"]
        assert req["expected"]["total_particles_from_gencase"] is None
        assert req["expected"]["fluid_particles_from_gencase"] is None
        assert req["expected"]["generated_bi4_sha256"] is None
        assert req["output_contract"]["future_sha256"] is None
    print("fresh102 source contract: PASS (24 prospective rows, 0 overlaps, 24 disabled GenCase requests)")

if __name__ == "__main__":
    main()
