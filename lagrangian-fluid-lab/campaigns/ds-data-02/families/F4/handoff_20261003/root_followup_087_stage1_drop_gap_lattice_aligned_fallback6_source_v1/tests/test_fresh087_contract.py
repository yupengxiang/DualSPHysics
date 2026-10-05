#!/usr/bin/env python3
"""Bounded source-only checks for fresh087."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_source_package() -> None:
    plan = json.loads((ROOT / "source-plan.json").read_text())
    assert plan["stage_contract"]["launch_allowed"] is False
    assert [round(float(row["gap_m"]), 5) for row in plan["endpoints"]] == [0.19, 0.2, 0.21, 0.23, 0.24, 0.25]
    assert all(row["source_definition_sha256"] for row in plan["endpoints"])
    for owner_path in (ROOT / "owners").glob("*.json"):
        owner = json.loads(owner_path.read_text())
        assert owner["source_only"] is True
        assert owner["launch_allowed"] is False
        assert owner["source_recipe"]["source_particle_counts"] is None
        assert owner["future_outputs"]["generated_bi4_producer_sha256"] is None
        assert owner["physical_binding"]["initial_state"]["initial_mass_by_source_kg"] is None
    worker = ROOT / "workers/run_f4_fallback_native_initial_qa_v1.py"
    ast.parse(worker.read_text(), filename=str(worker))
    text = worker.read_text()
    assert "content_rehashed_by_source" in text
    assert "Posd" in text and "Idp" in text
    assert "numpy" not in text and "memmap" not in text


if __name__ == "__main__":
    test_source_package()
    print("fresh087 source contract: PASS")
