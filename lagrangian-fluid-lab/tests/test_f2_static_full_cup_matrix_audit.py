from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f2_static_full_cup_matrix_audit import audit_matrix


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_matrix_audit_rechecks_fixed_denominator_and_no_solver_claims(tmp_path: Path) -> None:
    cells = []
    denominator = []
    for index in range(15):
        cell = tmp_path / "cells" / f"{index:02d}"
        cell.mkdir(parents=True)
        preflight = cell / "preflight.json"
        prepared = cell / "prepared.json"
        preflight.write_text(json.dumps({
            "preflight_pass": True,
            "trajectory_or_solver_checked": False,
        }))
        prepared.write_text(json.dumps({
            "preflight_pass": True,
            "solver_invoked": False,
            "hash_closure_pass": True,
        }))
        row = {
            "index": index, "case_id": f"case-{index}", "q": index / 14,
            "dp_m": .0075, "status": "prepared", "preflight_pass": True,
            "mass_error_relative": 0., "prepared": str(prepared),
            "prepared_sha256": _digest(prepared), "preflight": str(preflight),
            "preflight_sha256": _digest(preflight),
        }
        cells.append(row)
        denominator.append({"index": index, "status": "prepared"})
    report = tmp_path / "matrix-preparation.json"
    report.write_text(json.dumps({
        "schema": "core.f2.static_full_cup.matrix_preparation.v1",
        "status": "prepared", "registered_cell_count": 15,
        "prepared_cell_count": 15, "failed_cell_count": 0,
        "unattempted_cell_count": 0, "candidate_id": "candidate",
        "scope_id": "scope", "cells": cells,
        "failure_denominator": {"rows": denominator},
        "execution_controls": {
            "solver_invoked": False, "gpu_invoked": False,
            "queue_mutation": 0, "ledger_mutation": 0,
            "registry_mutation": 0, "matrix_jobs_materialized": False,
            "qualification_claim_allowed": False,
        },
        "candidate_matrix_jobs_materialized": False,
    }))
    output = tmp_path / "audit.json"
    result = audit_matrix(report, output)
    assert result["prepared_cell_count"] == 15
    assert result["T1_numerical"] is False
    assert result["fixed_failure_denominator"] is True
    assert json.loads(output.read_text())["read_only_audit"] is True

