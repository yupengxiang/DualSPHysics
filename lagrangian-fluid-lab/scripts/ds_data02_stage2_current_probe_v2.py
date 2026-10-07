#!/usr/bin/env python3
"""Bounded real-data probe for the Stage 2 CURRENT consumer interface.

This worker is deliberately limited to the four accepted F1 aliases plus one
F2 and one F3 row.  It verifies headers and reads one saved frame/identity per
row; it never materializes labels or scans a full trajectory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_consumers_v2 import (  # noqa: E402
    BindingError,
    build_prospective_split,
    load_current_catalog,
    read_case_window,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()

    catalog = load_current_catalog(args.catalog)
    aliases = [case for case in catalog.cases() if case.is_accepted_alias]
    if len(aliases) != 4:
        raise BindingError(f"expected four accepted aliases in CURRENT, found {len(aliases)}")
    selected = aliases[:]
    selected.extend(next(case for case in catalog.cases() if case.family_id == family)
                    for family in ("F2", "F3"))

    records = []
    for case in selected:
        if case.row["particles"] < 1 or case.row["frames"] < 1:
            raise BindingError(f"{case.physical_case_id}: empty trajectory")
        window = read_case_window(
            case,
            frame_start=0,
            frame_stop=1,
            particle_start=0,
            particle_stop=1,
            fields=("time", "particle_id", "particle_zone", "valid", "position"),
        )
        binding = window["binding"]
        manifest_identity = binding.get("manifest_identity") or {}
        records.append({
            "family_id": case.family_id,
            "physical_case_id": case.physical_case_id,
            "manifest_physical_case_id": binding.get("manifest_physical_case_id"),
            "accepted_alias": case.is_accepted_alias,
            "alias_scope_equality_claim": binding["physical_condition_scopes"]["equality_claim"],
            "manifest_schema": manifest_identity.get("schema"),
            "manifest_identity": manifest_identity.get("physical_case_id"),
            "frames": binding["frames"],
            "particles": binding["particles"],
            "time_window_s": binding["actual_time_window_s"],
            "first_saved_time_s": float(window["time"][0]),
            "identity_window": {
                "particle_id": int(window["particle_id"][0]),
                "particle_zone": int(window["particle_zone"][0]),
                "valid": bool(window["valid"][0, 0]),
                "position_finite": bool(np.isfinite(window["position"][0, 0]).all()),
            },
            "quality": binding["quality"],
        })

    split = build_prospective_split(catalog)
    print(json.dumps({
        "schema": "ds02.stage2.current-probe.v2",
        "current_manifest_sha256": catalog.sha256,
        "alias_count": len(aliases),
        "selected_count": len(records),
        "scope": "header plus one saved frame/identity; observation only",
        "prospective_split": {
            "split_safety": split["split_safety"],
            "lineage_group_count": split["lineage_group_count"],
        },
        "records": records,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
