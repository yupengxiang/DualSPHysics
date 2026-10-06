#!/usr/bin/env python3
"""Validate the fresh120 metadata-only reconciliation sidecar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.sidecar.read_text(encoding="utf-8"))
    assert data["schema"] == "ds02.f3.fresh120.qual01-dependency-reconciliation.v1"
    assert data["safety"]["delete_performed"] is False
    assert data["safety"]["scientific_payload_opened"] is False
    assert data["safety"]["scientific_payload_hashed"] is False
    plan = data["cleanup_plan"]
    assert plan["intermediate_frame_count"] == 1786
    assert plan["preserve_first_frame"] == "Part_0000.bi4"
    assert plan["preserve_last_frame"] == "Part_1787.bi4"
    assert plan["current_qual01_frame_dependency"] is False
    assert plan["agent_delete_authorized"] is False
    assert data["rg_provenance"]["started_by_this_agent"] is False
    print("fresh120 sidecar validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
