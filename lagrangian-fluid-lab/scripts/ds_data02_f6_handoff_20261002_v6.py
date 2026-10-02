#!/usr/bin/env python3
"""PartVTK-002 and solver-request wrapper for the commensurate F6 mother.

The first additive PartVTK request was rejected by the shared runtime before
execution because it listed a ``__Actual.vtk`` name that GenCase does not
produce with ``-save:all``.  This wrapper leaves that request intact and emits
new request/manifest bytes with only the actual native files as inputs.  It
also binds the later root-only solver requests to the new PartVTK attempt.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve()
V5 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v5.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_20261002_v5", V5)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load commensurate mother generator: {V5}")
MODULE_V5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE_V5)
MODULE = MODULE_V5.MODULE
ORIGINAL_ROOT = MODULE.FAMILY_ROOT
MODULE.FAMILY_ROOT = ORIGINAL_ROOT / "partvtk_002"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.commensurate_mother.partvtk_002.v1"

_BASE_INPUT_FILES = MODULE._request_input_files


def _request_input_files_with_v5(*paths: Path) -> list[str]:
    values = [value for value in _BASE_INPUT_FILES(*paths) if Path(value).is_file()]
    for path in (V5,):
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files_with_v5

_BASE_PARTVTK_REQUESTS = MODULE.make_partvtk_requests


def make_partvtk_requests() -> dict[str, object]:
    # Use a fresh additive root so the original _001 request remains
    # reviewable.  Case definitions and GenCase receipts still point to the
    # immutable commensurate mother and raw data roots.
    source_manifest = MODULE.read_json(ORIGINAL_ROOT / "manifest.json")
    MODULE.FAMILY_ROOT.mkdir(parents=True, exist_ok=True)
    MODULE.write_json(MODULE.FAMILY_ROOT / "manifest.json", source_manifest)
    result = _BASE_PARTVTK_REQUESTS()
    rows: list[dict[str, object]] = []
    for row in result["requests"]:
        old_path = Path(row["request"]["path"])
        request = MODULE.read_json(old_path)
        cid = str(request["case_id"])
        old_attempt = str(request["attempt_id"])
        new_attempt = old_attempt.replace("_PARTVTK_001", "_PARTVTK_002")
        request["attempt_id"] = new_attempt
        request["generator_version"] = MODULE.VERSION
        request["input_files"] = [value for value in request["input_files"] if Path(value).is_file()]
        v5_value = str(V5.resolve())
        if v5_value not in request["input_files"]:
            request["input_files"].append(v5_value)
        request["lineage"] = {
            "source_commensurate_manifest": str((ORIGINAL_ROOT / "manifest.json").resolve()),
            "source_commensurate_manifest_sha256": MODULE.sha256(ORIGINAL_ROOT / "manifest.json"),
            "supersedes_request": str(old_path.resolve()),
            "supersedes_request_sha256": MODULE.sha256(old_path),
            "missing_input_excluded": "__Actual.vtk is not emitted by GenCase -save:all; existing All/Fluid native files are retained",
        }
        new_path = MODULE.FAMILY_ROOT / "execution_requests" / f"{cid}_partvtk_002.json"
        MODULE.write_json(new_path, request)
        rows.append({
            "case_id": cid,
            "request": {"path": str(new_path.resolve()), "sha256": MODULE.sha256(new_path), "attempt_id": new_attempt},
            "gencase_receipt": str(Path(request["gencase_receipt"]).resolve()),
            "output_csv": str((MODULE._attempt_root(cid, new_attempt) / f"{cid}_initial_all.csv").resolve()),
        })
    result = {
        "schema": MODULE.SCHEMA + ".partvtk_requests",
        "created_at": MODULE.now(),
        "status": "ready_for_shared_runtime_partvtk",
        "supersedes_manifest": str((ORIGINAL_ROOT / "partvtk_request_manifest.json").resolve()),
        "requests": rows,
    }
    MODULE.write_json(MODULE.FAMILY_ROOT / "partvtk_request_manifest.json", result)
    return result


_BASE_SOLVER_REQUEST = MODULE._solver_request


def _solver_request(case, audit_row):
    request = _BASE_SOLVER_REQUEST(case, audit_row)
    cid = str(case["case_id"])
    old_token = f"{cid}_PARTVTK_001"
    new_token = f"{cid}_PARTVTK_002"
    old_receipt = MODULE._receipt(cid, old_token)
    new_receipt = MODULE._receipt(cid, new_token)
    new_csv = MODULE._attempt_root(cid, new_token) / f"{cid}_initial_all.csv"
    request["partvtk_receipt"] = str(new_receipt.resolve())
    request["partvtk_receipt_sha256"] = MODULE.sha256(new_receipt)
    request["input_files"] = [value for value in request["input_files"] if old_token not in value]
    for path in (new_receipt, new_csv):
        value = str(path.resolve())
        if value not in request["input_files"]:
            request["input_files"].append(value)
    request["generator_version"] = MODULE.VERSION
    request["partvtk_lineage"] = {
        "request_manifest": str((MODULE.FAMILY_ROOT / "partvtk_request_manifest.json").resolve()),
        "request_manifest_sha256": MODULE.sha256(MODULE.FAMILY_ROOT / "partvtk_request_manifest.json"),
        "supersedes_attempt": old_token,
        "superseded_attempt_receipt_exists": old_receipt.is_file(),
    }
    return request


MODULE.make_partvtk_requests = make_partvtk_requests
MODULE._solver_request = _solver_request


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["make-partvtk-requests", "audit", "make-solver-requests"])
    args = parser.parse_args()
    if args.action == "make-partvtk-requests":
        result = make_partvtk_requests()
    elif args.action == "audit":
        result = MODULE.audit()
    else:
        result = MODULE.make_solver_requests()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
