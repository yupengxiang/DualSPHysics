#!/usr/bin/env python3
"""Run the frozen explicit inventory against the additive v2 catalog.

The implementation is intentionally delegated to the reviewed v1 inventory
worker after changing only its schema labels and metadata cap.  The catalog
validator, one-dimension-per-sentinel rule, small-proof read guard, and
UNKNOWN/zero-credit semantics therefore remain identical.  This wrapper does
not read production native/VTK/BI4/HDF5 data.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_fourteen_evidence_dimension_inventory_v1.py"
SPEC = importlib.util.spec_from_file_location("stage2_fourteen_dimension_inventory_v1_frozen", V1_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load frozen inventory v1: {V1_PATH}")
V1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V1)

SCHEMA = "ds02.stage2.fourteen-reference-evidence-dimension-inventory.v2"
CATALOG_SCHEMA = "ds02.stage2.fourteen-reference-evidence-dimension-catalog.v2"
V1.SCHEMA = SCHEMA
V1.CATALOG_SCHEMA = CATALOG_SCHEMA
V1.SMALL_CAP = 10 * 1024 * 1024


def _self_test() -> None:
    V1.self_test()
    print("PASS_FOURTEEN_EXPLICIT_EVIDENCE_DIMENSION_INVENTORY_V2_SELFTEST")


def build(catalog: Path, output: Path) -> dict[str, Any]:
    result = V1.build(catalog, output)
    # V1 writes the complete result already.  Additive provenance is a small
    # JSON rewrite and does not touch any evidence source.
    output = output.expanduser().absolute()
    value = json.loads(output.read_text(encoding="utf-8"))
    value["generated_by_v2_wrapper"] = {
        "path": str(Path(__file__).absolute()),
        "frozen_worker": str(V1_PATH.absolute()),
        "catalog_schema": CATALOG_SCHEMA,
        "metadata_cap_bytes": V1.SMALL_CAP,
    }
    output.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            _self_test()
        except Exception as exc:
            print(f"FAILED_FOURTEEN_EXPLICIT_EVIDENCE_DIMENSION_INVENTORY_V2_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.catalog is None or args.output is None:
        parser.error("--build requires --catalog and --output")
    try:
        value = build(args.catalog, args.output)
    except Exception as exc:
        print(f"FAILED_FOURTEEN_EXPLICIT_EVIDENCE_DIMENSION_INVENTORY_V2: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value["status"], "record_count": value["record_count"],
                      "output": str(args.output.expanduser().absolute()), "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
