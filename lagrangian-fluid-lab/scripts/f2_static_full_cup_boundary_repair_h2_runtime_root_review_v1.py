#!/usr/bin/env python3
"""Build and verify the one-cell H2 solver-canary root review.

The CPU/native H2 preflight is intentionally a zero-credit result.  This
module only records a second, explicit authorization for one fresh solver
canary at q=0, dp=0.010 m.  It never submits a job, changes the registry, or
launches a solver.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parents[1]
PREFLIGHT = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/preflight.json"
WRITER = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/input/writer-receipt.json"
INPUT_DEFINITION = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/input/CORE_F2_static_full_cup_volume_supportclearance_h2_q0p00000000_dp0p010000000000_canary_Def.xml"
PREFLIGHT_REVIEW = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-root-review-v1.json"
PROPOSAL = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-proposal-v1.json"
PRIOR_NEGATIVE = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h1-negative-evidence-v1.json"
OUTPUT = LAB / "campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-runtime-root-review-v1.json"

SCHEMA = "core.f2.static_full_cup.boundary_repair_h2.runtime_root_review.v1"
REPAIR_ID = "F2_static_full_cup_initial_support_clearance_h2_v1"
SCOPE_ID = "F2_static_full_cup_volume_hold_x_v1"
CASE_ID = "CORE_F2_static_full_cup_volume_supportclearance_h2_q0p00000000_dp0p010000000000_canary"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        relative = path.relative_to(LAB.resolve()).as_posix()
    except ValueError:
        relative = str(path)
    return {"path": relative, "sha256": digest(path), "bytes": path.stat().st_size, "role": role}


def _bind(item: dict[str, Any], path: Path, label: str) -> None:
    if item.get("sha256") != digest(path):
        raise ValueError(f"{label} hash mismatch")
    if int(item.get("bytes", -1)) != path.stat().st_size:
        raise ValueError(f"{label} byte count mismatch")


def build_contract() -> dict[str, Any]:
    preflight = load(PREFLIGHT)
    writer = load(WRITER)
    prior_review = load(PREFLIGHT_REVIEW)
    proposal = load(PROPOSAL)
    if preflight.get("status") != "cpu_native_preflight_pass" or preflight.get("preflight_pass") is not True:
        raise ValueError("H2 CPU/native preflight is not a passed input gate")
    for key in ("qualified", "T1_numerical"):
        if preflight.get(key) is not False:
            raise ValueError("H2 preflight carries a qualification claim")
    if preflight.get("matrix_credit") != 0 or preflight.get("registry_mutated") is not False:
        raise ValueError("H2 preflight has nonzero credit or registry mutation")
    if writer.get("case_id") != CASE_ID or writer.get("revision_id") != REPAIR_ID.replace("initial_", ""):
        # The writer revision is the public H2 revision, not the repair id.
        if writer.get("case_id") != CASE_ID or writer.get("revision_id") != "F2_static_full_cup_support_clearance_h2_v1":
            raise ValueError("H2 writer identity mismatch")
    if prior_review.get("status") != "approved_for_one_fresh_cpu_native_preflight":
        raise ValueError("the input root review is not closed")
    if proposal.get("matrix_credit") != 0:
        raise ValueError("proposal credit changed")
    checks = preflight.get("checks", {})
    required_checks = ("native_fluid_count", "native_ids_unique", "native_arrays_finite",
                       "fluid_inside_cup", "support_clearance", "no_initial_endpoint",
                       "zero_boundnor", "mass_relative_gate")
    if any(checks.get(name) is not True for name in required_checks):
        raise ValueError("H2 preflight hard gates are incomplete")
    now = stamp()
    return {
        "schema": SCHEMA,
        "review_id": "f2-static-full-cup-boundary-repair-h2-runtime-root-review-v1",
        "created_at_utc": now,
        "family": "F2",
        "scope_id": SCOPE_ID,
        "repair_id": REPAIR_ID,
        "status": "approved_for_one_solver_canary",
        "decision": "approved_for_one_solver_canary",
        "authorized_cell_indices": [0],
        "hypothesis_class": "H2_initial_fluid_support_clearance",
        "hypothesis": "retain Boundary=2 mDBC/explicit normals and the fixed cup, but use the fresh source lattice whose minimum distance to the cup bottom and four closed sides is c(dp)=3*hdp*dp",
        "case_id": CASE_ID,
        "revision_id": "F2_static_full_cup_support_clearance_h2_v1",
        "preflight": ref(PREFLIGHT, "passed H2 CPU/native input preflight"),
        "writer_receipt": ref(WRITER, "fresh H2 Definition writer receipt"),
        "definition": ref(INPUT_DEFINITION, "fresh H2 Definition"),
        "preflight_root_review": ref(PREFLIGHT_REVIEW, "input-only H2 root review"),
        "proposal": ref(PROPOSAL, "H2 proposal-only contract"),
        "prior_negative": ref(PRIOR_NEGATIVE, "immutable H1 runtime negative"),
        "authorization": {
            "solver_launch": True,
            "gpu_launch": True,
            "job_spec_creation": True,
            "queue_mutation": True,
            "ledger_mutation": True,
            "registry_mutation": False,
            "material_training": False,
            "model_training": False,
            "qualification_credit": 0,
        },
        "execution_controls": {
            "read_only_review": True,
            "solver_now": False,
            "gpu_launch_now": False,
            "job_spec_creation_now": False,
            "queue_mutation_now": 0,
            "ledger_mutation_now": 0,
            "registry_mutation_now": 0,
        },
        "execution_policy": {
            "exactly_one_solver_canary": True,
            "selected_cell_is_fixed": True,
            "host_preference": "ada; use a card with measured headroom and avoid H200 disk pressure",
            "registered_window_s": 0.60,
            "output_interval_s": 0.02,
            "same_input_retry": False,
            "infrastructure_retry": "at most one explicitly logged infrastructure recovery; no scientific retry",
            "matrix_expansion": False,
            "scope_registration": False,
            "failure_denominator": {"planned": 15, "executed": 1, "future_unattempted": 14, "survivor_renormalization": False},
        },
        "hard_gates": {
            "cpu_native_preflight_pass": True,
            "fresh_definition_and_generated_bi4": True,
            "support_clearance_m": 0.039,
            "mass_relative_error_max": 0.03,
            "no_initial_endpoint": True,
            "no_zero_boundnor": True,
            "static_hold_event_window_and_wall_audit_required": True,
        },
        "postconditions": [
            "one solver execution receipt and complete native conversion",
            "full 0.60 s window or an explicit infrastructure/scientific failure receipt",
            "wall endpoint, saved-chord, missing-frame, finite-state and mass audits",
            "preserve the fixed 15-cell denominator and the H2 input preflight",
            "do not mutate registry, do not claim T1/T2, do not launch matrix rows",
        ],
        "qualification_claim": "none; one H2 solver canary only",
        "scientific_status": "solver_execution_authorized_but_not_started",
        "registry_mutation": 0,
        "implementation": ref(Path(__file__), "runtime root-review implementation"),
    }


def write(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    checks = {
        "schema": value.get("schema") == SCHEMA,
        "status": value.get("status") == "approved_for_one_solver_canary",
        "one_cell": value.get("authorized_cell_indices") == [0],
        "qualification_closed": value.get("qualification_claim", "").startswith("none;"),
        "solver_now_closed": value.get("execution_controls", {}).get("solver_now") is False,
        "gpu_now_closed": value.get("execution_controls", {}).get("gpu_launch_now") is False,
        "registry_closed": value.get("authorization", {}).get("registry_mutation") is False and value.get("registry_mutation") == 0,
        "same_input_retry_closed": value.get("execution_policy", {}).get("same_input_retry") is False,
        "matrix_closed": value.get("execution_policy", {}).get("matrix_expansion") is False,
        "zero_credit": value.get("authorization", {}).get("qualification_credit") == 0,
    }
    for key in ("preflight", "writer_receipt", "definition", "preflight_root_review", "proposal", "prior_negative"):
        item = value.get(key, {})
        path_value = item.get("path")
        if not isinstance(path_value, str):
            checks[f"{key}_present"] = False
            continue
        resolved = LAB / path_value if not Path(path_value).is_absolute() else Path(path_value)
        checks[f"{key}_present"] = resolved.is_file()
        if resolved.is_file():
            try:
                _bind(item, resolved, key)
            except (OSError, ValueError, TypeError):
                checks[f"{key}_hash"] = False
            else:
                checks[f"{key}_hash"] = True
    return {"ok": all(checks.values()), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if args.command == "build":
        value = build_contract()
        write(args.output, value)
        print(json.dumps({"status": value["status"], "output": str(args.output)}, ensure_ascii=False))
        return 0
    result = verify(args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
