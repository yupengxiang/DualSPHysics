#!/usr/bin/env python3
"""Audit the F6 v10 13+2 design before fresh native preflight.

This is a read-only root boundary.  It validates the frozen design and its
hash bindings, then writes an admission observation that authorizes only
future per-cell Definition/XML/BI4 materialization and native preflight.  It
does not invoke GenCase, a solver, CUDA, the runtime queue, registry, ledger,
or qualification matrix.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
DESIGN_DIR = LAB / (
    "campaigns/core-v1/cfd/"
    "f6-fluid-rigid-body-physical-anchor-observation-axis-v10-"
    "qualification-design-20260921"
)
OUTPUT = DESIGN_DIR / "root-admission.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object required: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    return {
        "path": str(path.relative_to(LAB.resolve()).as_posix()),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def build(design_dir: Path = DESIGN_DIR) -> dict[str, Any]:
    design_dir = design_dir.resolve()
    design_path = design_dir / "design.json"
    matrix_path = design_dir / "matrix.json"
    card_path = design_dir / "candidate-card.json"
    design = load(design_path)
    matrix = load(matrix_path)
    card = load(card_path)
    issues: list[str] = []

    if design.get("status") != "root_review_only_not_submitted":
        issues.append("design is not root-review-only")
    if design.get("matrix_cell_count") != 15 or len(design.get("cells", [])) != 15:
        issues.append("design does not contain exactly 15 cells")
    if design.get("spatial_cell_count") != 13 or design.get("time_output_comparison_count") != 2:
        issues.append("13+2 partition is not fixed")
    if design.get("qualification_claim") != "none" or design.get("qualification_credit") != 0 or design.get("T1") is not False:
        issues.append("design has qualification credit")
    if matrix.get("submitted") is not False or matrix.get("qualification_credit") != 0:
        issues.append("matrix is submitted or carries credit")
    if card.get("status") != design.get("status") or card.get("qualification_claim") != "none" or card.get("T1") is not False:
        issues.append("candidate card is not bound to the nonqualifying design")
    if matrix.get("design_ref", {}).get("sha256") != sha256(design_path):
        issues.append("matrix design hash mismatch")

    cell_ids = [cell.get("cell_id") for cell in design.get("cells", [])]
    if len(cell_ids) != len(set(cell_ids)) or any(not isinstance(item, str) for item in cell_ids):
        issues.append("cell identities are not unique")
    for cell in design.get("cells", []):
        if cell.get("qualification_only") is not True or cell.get("split") != "qualification_only":
            issues.append(f"cell {cell.get('cell_id')} is not qualification-only")
        if cell.get("qualification_claim") != "none" or cell.get("qualification_credit") != 0 or cell.get("T1") is not False:
            issues.append(f"cell {cell.get('cell_id')} carries science credit")
        controls = cell.get("execution_policy", {})
        for key in ("queue_submission", "registry_mutation", "ledger_mutation"):
            if controls.get(key) not in (False, 0):
                issues.append(f"cell {cell.get('cell_id')} opens {key}")
        if controls.get("matrix_credit") != 0:
            issues.append(f"cell {cell.get('cell_id')} opens matrix credit")
        fresh = cell.get("fresh_input_contract", {})
        for key in ("fresh_definition_required", "fresh_generated_xml_required", "fresh_generated_bi4_required"):
            if fresh.get(key) is not True:
                issues.append(f"cell {cell.get('cell_id')} lacks {key}")
        if fresh.get("old_v10_canary_used_as_input") is not False:
            issues.append(f"cell {cell.get('cell_id')} permits canary input reuse")

    source_bindings = design.get("source_bindings", {})
    source_paths = {
        "fresh_v10_definition_contract": LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-root-review-20260921/definition-contract.json",
        "fresh_v10_preflight": LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-cpu-native-preflight-20260921/preflight.json",
        "fresh_v10_solver_canary": LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-solver-canary-20260921/attempt-001/execution-receipt.json",
    }
    for name, path in source_paths.items():
        binding = source_bindings.get(name, {})
        if binding.get("sha256") != sha256(path) or binding.get("hash_only") is not True:
            issues.append(f"source binding {name} is stale or not hash-only")

    execution_controls = {
        "definition_written": False,
        "gencase_invoked": False,
        "native_decode_invoked": False,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_submission": False,
    }
    return {
        "schema": "core.f6.observation_axis.qualification_admission.v1",
        "record_id": "F6_observation_axis_v10_qualification_admission_v4_20260921",
        "created_at_utc": stamp(),
        "status": "admitted_for_fresh_native_preflight_only" if not issues else "blocked_static_design_review",
        "family": design.get("family"),
        "scope_id": design.get("scope_id"),
        "revision_id": design.get("revision_id"),
        "design_status": design.get("status"),
        "cell_count": len(design.get("cells", [])),
        "cell_ids": cell_ids,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "static_review_pass": not issues,
        "issues": issues,
        "bindings": {
            "design": ref(design_path, "frozen 13+2 design"),
            "matrix": ref(matrix_path, "non-submitted 15-cell matrix"),
            "candidate_card": ref(card_path, "nonqualifying candidate card"),
            **{name: ref(path, "hash-only v10 context") for name, path in source_paths.items()},
        },
        "execution_controls": execution_controls,
        "admission": {
            "allowed_next_step": "materialize_each_cell_fresh_definition_xml_bi4_then_native_preflight",
            "all_15_cells_require_independent_preflight": True,
            "old_canary_input_reuse": False,
            "solver_authorized": False,
            "gpu_authorized": False,
            "queue_authorized": False,
            "registry_authorized": False,
            "ledger_authorized": False,
            "matrix_authorized": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design-dir", type=Path, default=DESIGN_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = build(args.design_dir)
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "cell_count": result["cell_count"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0 if result["static_review_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
