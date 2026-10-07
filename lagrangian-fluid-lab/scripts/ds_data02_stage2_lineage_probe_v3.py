#!/usr/bin/env python3
"""Guarded end-to-end lineage-role check over real CURRENT manifests.

This worker reads only CURRENT plus small manifest JSONs.  It checks that two
F5 rows with the same manifest ``case_id`` retain one role even when their
physical-condition hashes and conversion/XML bindings differ.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_consumers_v3 import (  # noqa: E402
    BindingError,
    _lineage_evidence,
    build_prospective_split,
    load_current_catalog,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_current_catalog(args.catalog)
    split = build_prospective_split(catalog)
    f5 = [case for case in catalog.cases() if case.family_id == "F5"]
    by_case_id = {}
    for case in f5:
        evidence = _lineage_evidence(case)
        for token in evidence["tokens"]:
            if ":manifest:case_id:" in token:
                by_case_id.setdefault(token, []).append(case)
    candidates = [(token, cases) for token, cases in by_case_id.items() if len(cases) >= 2]
    if not candidates:
        raise BindingError("CURRENT has no two F5 rows with shared manifest case_id")
    token, cases = sorted(candidates, key=lambda item: item[0])[0]
    records = {row["physical_case_id"]: row for row in split["cases"]}
    roles = {case.physical_case_id: records[case.physical_case_id]["role"] for case in cases}
    groups = {case.physical_case_id: records[case.physical_case_id]["lineage_group"] for case in cases}
    if len(set(roles.values())) != 1 or len(set(groups.values())) != 1:
        raise BindingError(f"shared physical lineage split roles diverged: {roles}, groups={groups}")
    print(json.dumps({
        "schema": "ds02.stage2.lineage-role-probe.v3",
        "current_manifest_sha256": catalog.sha256,
        "shared_lineage_token": token,
        "cases": [case.physical_case_id for case in cases],
        "roles": roles,
        "lineage_groups": groups,
        "split_safety": split["split_safety"],
        "hidden_test": split["hidden_test"],
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "scope": "real CURRENT and small manifest provenance only; no HDF5 frame read",
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
