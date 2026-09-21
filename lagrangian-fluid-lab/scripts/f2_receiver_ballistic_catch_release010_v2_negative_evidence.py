#!/usr/bin/env python3
"""Freeze the failed F2 release-speed-v2 CPU/native preflight as evidence.

The preflight is an input-closure check only.  This writer deliberately does
not open a trajectory, launch a solver, or alter the Core registry/ledger or
any qualification denominator.  It turns the observed hard gate failure into
an immutable, zero-credit route decision so a later worker cannot silently
retry the same input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
BASE = LAB / "campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-release010-v2"
PREFLIGHT = BASE / "preflight-v2/preflight-v2.json"
OUTPUT = BASE / "preflight-v2/negative-evidence-v2.json"
SCHEMA = "core.f2.receiver_ballistic_catch.cpu_native_negative_evidence.v2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def reference(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def build_evidence(preflight_path: Path = PREFLIGHT) -> dict[str, Any]:
    preflight_path = Path(preflight_path).resolve()
    preflight = load(preflight_path)
    if preflight.get("schema") != "core.f2.receiver_ballistic_catch.cpu_native_preflight.v2":
        raise ValueError("unexpected preflight schema")
    if preflight.get("status") != "cpu_native_preflight_failed_hard_audit":
        raise ValueError("the selected preflight is not a recorded hard failure")
    if preflight.get("qualification_claim") != "none" or preflight.get("matrix_credit") != 0:
        raise ValueError("preflight opened qualification credit")
    controls = preflight.get("execution_controls", {})
    for key in ("solver_invoked", "gpu_invoked"):
        if controls.get(key) is not False:
            raise ValueError(f"protected execution was opened: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "T1_denominator_mutation", "T2_denominator_mutation", "qualification_credit"):
        if controls.get(key) != 0:
            raise ValueError(f"central mutation was recorded: {key}")
    audit = preflight.get("native_audit", {})
    hard = audit.get("hard_gates", {})
    endpoint = hard.get("outer_wall_endpoints", {})
    count = int(endpoint.get("count", 0))
    if endpoint.get("pass") is not False or count <= 0:
        raise ValueError("expected the outer-wall endpoint hard failure")
    if hard.get("ids", {}).get("pass") is not True:
        raise ValueError("identity gate should be retained as a pass")
    if hard.get("finite", {}).get("pass") is not True:
        raise ValueError("finite-value gate should be retained as a pass")
    if hard.get("mass", {}).get("pass") is not True:
        raise ValueError("mass gate should be retained as a pass")
    if hard.get("receiver_surface_overlap", {}).get("pass") is not True:
        raise ValueError("receiver-overlap gate should be retained as a pass")
    if hard.get("runtime_domain", {}).get("pass") is not True:
        raise ValueError("runtime-domain gate should be retained as a pass")
    if not (preflight.get("denominator", {}).get("same_input_retry") is False):
        raise ValueError("same-input retry must remain forbidden")
    return {
        "schema": SCHEMA,
        "record_id": "F2_receiver_ballistic_catch_release010_v2_cpu_native_negative_20260921",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "candidate_closed_after_cpu_native_scientific_hard_failure",
        "family": "F2",
        "scope_id": preflight["scope_id"],
        "revision_id": preflight["revision_id"],
        "case_id": preflight["case_id"],
        "qualification_claim": "none",
        "T1_numerical": False,
        "matrix_credit": 0,
        "failure": {
            "category": "scientific_hard_gate_failure",
            "gate": "outer_wall_endpoint_count_zero",
            "observed_count": count,
            "tolerance_m": endpoint.get("tolerance_m"),
            "interpretation": "fresh input closure is scientifically invalid at the endpoint contract; no protected solver can be admitted for this candidate",
            "same_input_retry_allowed": False,
            "threshold_relaxation_allowed": False,
        },
        "retained_passes": {
            "ids": hard.get("ids"),
            "finite": hard.get("finite"),
            "mass": hard.get("mass"),
            "receiver_surface_overlap": hard.get("receiver_surface_overlap"),
            "runtime_domain": hard.get("runtime_domain"),
        },
        "denominator": {
            "candidate_rows": 15,
            "executed_rows": 0,
            "preflight_attempts": 1,
            "scientific_failures": 1,
            "unattempted_rows": 15,
            "credit": 0,
            "parent_denominator_changed": False,
            "failed_rows_dropped": False,
        },
        "execution_controls": {
            "cpu_gencase_invoked": controls.get("cpu_gencase_invoked"),
            "cpu_native_decode_invoked": controls.get("cpu_native_decode_invoked"),
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "next_gate": "close_candidate_and_select_a_distinct_physical_hypothesis_before_any_new_F2_definition",
        "input_evidence": {
            "preflight": reference(preflight_path, "fresh v2 CPU/native preflight receipt"),
        },
    }


def write_evidence(output: Path = OUTPUT, preflight_path: Path = PREFLIGHT) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"immutable evidence already exists: {output}")
    value = build_evidence(preflight_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, default=PREFLIGHT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = write_evidence(args.output, args.preflight)
    print(json.dumps({"status": result["status"], "gate": result["failure"]["gate"], "observed_count": result["failure"]["observed_count"], "credit": result["matrix_credit"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
