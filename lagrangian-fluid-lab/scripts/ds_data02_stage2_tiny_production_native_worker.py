#!/usr/bin/env python3
"""Run the reviewed native ``_audit_one`` on an isolated tiny fixture.

This is intentionally a test-only worker.  It does not replace any stage2
worker or alter production paths.  The fixture owns a tiny typed-record file,
an opaque OBI4 placeholder, and a tiny decoder executable.  The case report
is produced by the imported production worker and the batch report is written
through that worker's immutable writer.  No case report is supplied by the
fixture itself.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load worker: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"not an object: {path}")
    return value


def _worker_module(backend: str) -> Any:
    if backend == "generic-v1":
        return _load(SCRIPT_DIR / "ds_data02_stage2_build_generic_native_extract_v1.py", "tiny_prod_generic_v1")
    if backend == "generic-v3":
        return _load(SCRIPT_DIR / "ds_data02_stage2_build_f2_generic_native_extract_v3.py", "tiny_prod_generic_v3")
    if backend == "root312-v4":
        return _load(SCRIPT_DIR / "ds_data02_stage2_build_root312_f4_native_extract_v4.py", "tiny_prod_root312_v4")
    raise ValueError(f"unsupported tiny backend: {backend}")


def audit(manifest_path: Path, output_path: Path, backend: str) -> dict[str, Any]:
    worker = _worker_module(backend)
    manifest = _json(manifest_path)
    output_path = output_path.expanduser().resolve()
    if output_path.exists():
        raise ValueError(f"immutable output exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tool = Path(manifest["official_sources"]["partvtkout"]["path"]).expanduser().resolve()
    intake = worker.BASE._load_intake() if backend in {"generic-v3", "root312-v4"} else worker._load_intake()
    base = worker.BASE if backend in {"generic-v3", "root312-v4"} else worker
    results: list[dict[str, Any]] = []
    for entry in manifest["contracts"]:
        case_id = entry["physical_case_id"]
        contract = _json(Path(entry["path"]))
        report = base._audit_one(contract, output_path.parent, intake, tool, manifest["claim_boundary"])
        case_path = output_path.parent / "cases" / f"{case_id}.json"
        base._atomic(case_path, report, limit=getattr(base, "MAX_OUTPUT_BYTES", 8 * 1024 * 1024))
        results.append({"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_path), "joined": report["counts"]["joined"]})
    if backend == "root312-v4":
        # ROOT312 V4's production case path is the generic BASE._audit_one;
        # its historical batch constant is ``...extract-report.v2`` while
        # the V3/V5 consumer accepts the canonical v2 verifier alias.  Keep
        # this tiny consumer report on the accepted interface so the test
        # exercises the actual case producer rather than silently hand-writing
        # a case report.
        schema = "ds02.stage2.root312-f4-native-extract-v2-report"
        status = "COMPLETED_SELECTED_ORIGINAL118_NATIVE_DIAGNOSTIC_ONLY"
        extra = {"full_producer_proof_case_count": 1, "selected_original118_case_count": len(results), "producer_proof_merge": {"created": False}}
    else:
        schema = base.REPORT_SCHEMA
        status = "COMPLETED_ALL_CASES"
        extra = {}
    batch = {
        "schema": schema,
        "status": status,
        "family_id": manifest["family_id"],
        "case_results": results,
        "counts": {"requested": len(results), "completed": len(results), "failed": 0},
        **extra,
        "claim_boundary": manifest["claim_boundary"],
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }
    base._atomic(output_path, batch, limit=getattr(base, "MAX_OUTPUT_BYTES", 8 * 1024 * 1024))
    return {"status": status, "output": str(output_path), "completed": len(results), "failed": 0, "backend": backend}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--backend", choices=("generic-v1", "generic-v3", "root312-v4"), required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(audit(args.manifest, args.output, args.backend), sort_keys=True))
        return 0
    except Exception as exc:
        print(f"TINY_PRODUCTION_NATIVE_WORKER_ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
