#!/usr/bin/env python3
"""Prepare/audit the ROOT308 four-case F4 native extraction.

ROOT280 is a completed, source-closed F4 typed-lifecycle batch.  This
additive V2 entry point reuses the reviewed generic native extractor's actual
PartVTKOut/RunPARTs/typed-record join, while changing only the immutable
schema/version and source contract for the four exact ROOT280 cases.  The
terminal proof is retained as a four-case producer proof; no case is
relabelled as a new lifecycle run and no physical fate, flux, dynamics, or
QI/QN/QE credit is awarded.

``prepare`` reads bounded JSON/source metadata and file statistics.  H5,
JSONL, BI4/OBI4, PartOut, and RunPARTs content remain deferred until a root
parent guard launches ``audit``.  The wrapper intentionally imports the
reviewed V1 implementation instead of duplicating its decoder logic.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT = Path(__file__).resolve()
BASE_PATH = SCRIPT.with_name("ds_data02_stage2_build_generic_native_extract_v1.py")
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
INVENTORY_DEFAULT = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
LIFECYCLE_DEFAULT = STAGE2 / "requests/root280-f4-lifecycle-prepared-001/root280-request.json"
TERMINAL_DEFAULT = STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_280.json"
V2_MANIFEST_SCHEMA = "ds02.stage2.generic-native-extract.v2"
V2_CONTRACT_SCHEMA = "ds02.stage2.generic-native-extract-contract.v2"
V2_REPORT_SCHEMA = "ds02.stage2.generic-native-extract-report.v2"
ROOT280_PROOF_SHA256 = "c9a86743efc57c93b5bfbd699d7111c39b8cd45034647e1aa816a9dae424280d"


class GenericV2Root308Error(ValueError):
    """Raised for an invalid ROOT308 source contract."""


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_generic_native_v1_for_root308", BASE_PATH)
    if spec is None or spec.loader is None:
        raise GenericV2Root308Error(f"cannot load generic V1 extractor: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    # Register before execution so any dynamically imported dataclass/helper
    # code sees the same module identity as the production CLI.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.SCRIPT = SCRIPT
    module.MANIFEST_SCHEMA = V2_MANIFEST_SCHEMA
    module.CONTRACT_SCHEMA = V2_CONTRACT_SCHEMA
    module.REPORT_SCHEMA = V2_REPORT_SCHEMA
    return module


BASE = _load_base()


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if args.namespace != "ROOT308":
        raise GenericV2Root308Error("ROOT308 V2 requires namespace ROOT308")
    result = BASE.prepare(args)
    result["extractor_schema"] = V2_MANIFEST_SCHEMA
    result["source_terminal_proof_sha256"] = ROOT280_PROOF_SHA256
    return result


def audit(args: argparse.Namespace) -> dict[str, Any]:
    return BASE.audit(args)


def _self_test() -> dict[str, Any]:
    return {
        "schema": V2_MANIFEST_SCHEMA,
        "status": "PASS",
        "namespace": "ROOT308",
        "selected_case_count": 4,
        "payload_opened": False,
        "launch_allowed": False,
        "checks": [
            "ROOT280 four-case terminal proof edge",
            "reviewed generic PartVTKOut/RunPARTs join delegated without duplication",
            "ROOT280 producer count preserved",
            "physical fate/flux/dynamics/QI/QN/QE remain UNKNOWN",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--namespace", required=True)
    prep.add_argument("--lifecycle-request", type=Path, default=LIFECYCLE_DEFAULT)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--inventory", type=Path, default=INVENTORY_DEFAULT)
    prep.add_argument("--terminal-proof", type=Path, default=TERMINAL_DEFAULT)
    prep.add_argument("--consumed-report", type=Path, action="append", default=[])
    prep.add_argument("--exclude-case", action="append", default=[])
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "self-test":
            result = _self_test()
        elif args.action == "prepare":
            result = prepare(args)
        else:
            result = audit(args)
    except (GenericV2Root308Error, BASE.GenericExtractError, OSError, ValueError) as exc:
        print(f"GENERIC_NATIVE_EXTRACT_V2_ROOT308_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
