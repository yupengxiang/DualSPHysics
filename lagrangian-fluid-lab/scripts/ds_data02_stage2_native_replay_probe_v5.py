#!/usr/bin/env python3
"""Guard worker for the metadata-only F2-S1 native replay preparation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ds_data02_stage2_native_replay_v5 import (  # noqa: E402
    NATIVE_REPLAY_SCHEMA,
    _dump_json,
    build_native_replay_bundle,
    load_current_catalog,
    read_json,
    sha256,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    catalog = load_current_catalog(args.catalog)
    request = read_json(args.request)
    bundle = build_native_replay_bundle(catalog, request)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    bundle_path = output_root / "native-replay-bundle.json"
    _dump_json(bundle_path, bundle)
    report = {
        "schema": "ds02.stage2.native-replay-probe-report.v1",
        "bundle_schema": NATIVE_REPLAY_SCHEMA,
        "bundle_path": str(bundle_path),
        "bundle_sha256": sha256(bundle_path),
        "physical_case_id": bundle["physical_case_id"],
        "lineage_rows": bundle["lineage_audit"]["rows"],
        "lineage_split_safety": bundle["lineage_audit"]["split_safety"],
        "scientific_scan_status": bundle["bound_dependencies"]["scientific_scan"]["scan_status"],
        "native_exclusion_status": bundle["bound_dependencies"]["native_exclusion"]["status"],
        "initial_frame_read_status": bundle["initial_frame"]["read_status"],
        "read_scope_status": bundle["read_scope_status"],
        "model_invoked": False,
        "hidden_test": False,
        "quality": bundle["quality"],
        "qualification_status": bundle["qualification_status"],
    }
    _dump_json(output_root / "native-replay-probe-report.json", report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
