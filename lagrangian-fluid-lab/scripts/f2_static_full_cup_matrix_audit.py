#!/usr/bin/env python3
"""Independently audit a prepared F2 matrix without running a solver.

The preparation command creates fresh CPU inputs, but its report is still a
worker-produced artifact.  This read-only auditor re-hashes every registered
cell artifact, checks the fixed 15-row denominator and verifies that no
solver/job/ledger/registry claim slipped into a preparation result.  It never
updates the Core registry and never treats a prepared input as T1 evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "core.f2.static_full_cup.matrix_preparation_audit.v1"
EXPECTED_CELLS = 15


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            value.update(block)
    return value.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError("matrix preparation report must be a JSON object")
    return payload


def _under(path: Path, root: Path) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"matrix artifact escapes its output root: {path}") from error
    return resolved


def _verify_ref(ref: dict[str, Any], root: Path, *, label: str) -> dict[str, Any]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise ValueError(f"{label} is missing a path reference")
    path = _under(Path(ref["path"]), root)
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = digest(path)
    if actual != ref.get("sha256"):
        raise ValueError(f"{label} hash mismatch: {path}")
    if int(ref.get("bytes", -1)) != path.stat().st_size:
        raise ValueError(f"{label} byte count mismatch: {path}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def audit_matrix(report_path: str | Path, output: str | Path | None = None) -> dict[str, Any]:
    report_path = Path(report_path).resolve()
    report = _load(report_path)
    if report.get("schema") != "core.f2.static_full_cup.matrix_preparation.v1":
        raise ValueError("unexpected matrix preparation schema")
    root = report_path.parent.resolve()
    if report.get("status") != "prepared":
        raise ValueError("matrix preparation is not complete; failed rows remain in denominator")
    if report.get("registered_cell_count") != EXPECTED_CELLS:
        raise ValueError("registered F2 matrix denominator is not 15")
    if report.get("prepared_cell_count") != EXPECTED_CELLS or report.get("failed_cell_count") != 0:
        raise ValueError("matrix preparation counts are incomplete")
    if report.get("unattempted_cell_count") != 0:
        raise ValueError("matrix preparation has unattempted cells")
    controls = report.get("execution_controls", {})
    forbidden = {
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "ledger_mutation": 0,
        "registry_mutation": 0,
        "matrix_jobs_materialized": False,
        "qualification_claim_allowed": False,
    }
    for key, expected in forbidden.items():
        if controls.get(key) != expected:
            raise ValueError(f"forbidden execution control changed: {key}")
    if report.get("candidate_matrix_jobs_materialized") is not False:
        raise ValueError("preparation report claims matrix jobs")

    rows = report.get("cells")
    denominator = report.get("failure_denominator", {}).get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_CELLS:
        raise ValueError("prepared cell rows do not close the 15-cell matrix")
    if not isinstance(denominator, list) or len(denominator) != EXPECTED_CELLS:
        raise ValueError("failure denominator is not fixed at 15 rows")
    indexes = [int(row.get("index", -1)) for row in rows]
    if indexes != list(range(EXPECTED_CELLS)):
        raise ValueError("prepared rows are missing or reordered")
    denominator_indexes = [int(row.get("index", -1)) for row in denominator]
    if denominator_indexes != indexes:
        raise ValueError("failure denominator does not match prepared rows")

    checked_cells = []
    for row in rows:
        if row.get("status") != "prepared" or row.get("preflight_pass") is not True:
            raise ValueError(f"cell {row.get('index')} is not a passed CPU preflight")
        prepared = _verify_ref(
            {"path": row.get("prepared"), "sha256": row.get("prepared_sha256"),
             "bytes": Path(row["prepared"]).stat().st_size if Path(row.get("prepared", "")).is_file() else -1},
            root, label=f"cell {row.get('index')} prepared",
        )
        preflight = _verify_ref(
            {"path": row.get("preflight"), "sha256": row.get("preflight_sha256"),
             "bytes": Path(row["preflight"]).stat().st_size if Path(row.get("preflight", "")).is_file() else -1},
            root, label=f"cell {row.get('index')} preflight",
        )
        prepared_payload = _load(Path(prepared["path"]))
        preflight_payload = _load(Path(preflight["path"]))
        if prepared_payload.get("preflight_pass") is not True or prepared_payload.get("solver_invoked") is not False:
            raise ValueError(f"cell {row.get('index')} prepared contract is invalid")
        if preflight_payload.get("preflight_pass") is not True or preflight_payload.get("trajectory_or_solver_checked") is not False:
            raise ValueError(f"cell {row.get('index')} preflight contract is invalid")
        if prepared_payload.get("hash_closure_pass") is not True:
            raise ValueError(f"cell {row.get('index')} hash closure is not marked passed")
        checked_cells.append({
            "index": int(row["index"]), "case_id": row["case_id"],
            "q": float(row["q"]), "dp_m": float(row["dp_m"]),
            "prepared": prepared, "preflight": preflight,
            "mass_error_relative": float(row["mass_error_relative"]),
        })

    audit = {
        "schema": SCHEMA,
        "source_report": {
            "path": str(report_path), "sha256": digest(report_path),
            "bytes": report_path.stat().st_size,
        },
        "family": "F2",
        "candidate_id": report.get("candidate_id"),
        "scope_id": report.get("scope_id"),
        "registered_cell_count": EXPECTED_CELLS,
        "prepared_cell_count": len(checked_cells),
        "failed_cell_count": 0,
        "fixed_failure_denominator": True,
        "cells": checked_cells,
        "execution_controls": {
            "cpu_prepare_and_decode": True,
            "solver_invoked": False,
            "gpu_invoked": False,
            "matrix_jobs_materialized": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
        },
        "T1_numerical": False,
        "qualification_claim": "none; CPU input closure only; static F2 T1 still requires solver matrix and scientific gates",
        "scientific_results_present": False,
        "read_only_audit": True,
    }
    if output is not None:
        output_path = Path(output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise FileExistsError(output_path)
        output_path.write_text(json.dumps(audit, indent=2, allow_nan=False) + "\n")
        audit["audit_artifact"] = {
            "path": str(output_path), "sha256": digest(output_path),
            "bytes": output_path.stat().st_size,
        }
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit_matrix(args.report, args.output)
    print(json.dumps({
        "schema": result["schema"], "prepared_cell_count": result["prepared_cell_count"],
        "T1_numerical": result["T1_numerical"],
        "qualification_claim": result["qualification_claim"],
        "audit_artifact": result.get("audit_artifact"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
