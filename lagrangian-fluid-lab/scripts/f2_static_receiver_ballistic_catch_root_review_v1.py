#!/usr/bin/env python3
"""Create and verify the F2 fresh-input root-review receipt.

This command is a read-only decision gate.  It binds the proposal and the
literal Definition writer, allocates one fresh CPU/native preflight namespace,
and explicitly closes solver, GPU, queue, ledger, registry, and matrix paths.
It never writes a Definition and never invokes a scientific executable.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.f2_static_receiver_ballistic_catch_definition_writer_v1 import (
    BASE, CASE_ID, DEFAULT_CONTRACT, DEFAULT_DEFINITION, sha256 as writer_sha256,
)
from scripts.f2_static_receiver_ballistic_catch_proposal_v1 import (
    PROPOSAL, validate_proposal,
)


ROOT_RECEIPT = BASE / "root-review-receipt-v1.json"
WRITER = LAB_ROOT / "scripts/f2_static_receiver_ballistic_catch_definition_writer_v1.py"
SCHEMA = "core.f2.static_receiver_ballistic_catch.root_review.v1"
CREATED_AT = "2026-09-21T00:00:00+00:00"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _assert_ref(item: dict[str, Any], label: str) -> Path:
    path = Path(item["path"]).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    if item.get("sha256") != sha256(path) or item.get("bytes") != path.stat().st_size:
        raise ValueError(f"{label}: content hash/size changed")
    return path


def build_receipt() -> dict[str, Any]:
    validate_proposal()
    if ROOT_RECEIPT.exists():
        raise FileExistsError(f"root-review receipt already exists: {ROOT_RECEIPT}")
    if not WRITER.is_file():
        raise FileNotFoundError(WRITER)
    # The proposal directory is deliberately the only namespace that is read;
    # no old generated/native output is accepted as a fresh input.
    receipt = {
        "schema": SCHEMA,
        "created_at": CREATED_AT,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "status": "authorized_one_fresh_cpu_native_preflight_only",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "proposal": ref(PROPOSAL, "F2 fresh mechanism proposal"),
        "writer": ref(WRITER, "literal fresh Definition writer"),
        "case": {
            "family": "F2",
            "scope_id": "F2_static_receiver_ballistic_catch_x_v1",
            "revision_id": "F2_static_receiver_ballistic_catch_v1",
            "case_id": CASE_ID,
            "q": 0.5,
            "dp_m": 0.0075,
            "definition": str(DEFAULT_DEFINITION.resolve()),
            "contract": str(DEFAULT_CONTRACT.resolve()),
            "generated_prefix": str((BASE / "preflight" / "generated" / CASE_ID).resolve()),
            "preflight_receipt": str((BASE / "preflight" / "preflight.json").resolve()),
        },
        "fresh_input": {
            "source_identity_changed": True,
            "source_reuse": False,
            "qualification_inheritance": False,
            "old_generated_input_reused": False,
            "old_native_output_reused": False,
            "old_trajectory_reused": False,
            "same_input_retry": False,
            "new_literal_definition_required": True,
        },
        "authorization": {
            "gencase_invocations": 1,
            "native_decode_invocations": 1,
            "solver_launch": False,
            "gpu_launch": False,
            "job_spec_creation": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_materialized": False,
            "matrix_submission": False,
        },
        "denominator": {
            "parent_scope_rows": 15,
            "executed": 0,
            "credit": 0,
            "same_input_retry": False,
            "survivor_renormalization": False,
            "event_censored_is_zero_credit": True,
        },
        "hard_gate_policy": {
            "native_ids_unique_and_contiguous": True,
            "all_decoded_arrays_finite": True,
            "source_mass_relative_error_max": 0.025,
            "closed_outer_wall_endpoint_count": 0,
            "receiver_wall_overlap_count": 0,
            "initial_source_outside_runtime_domain": 0,
            "event_observation_not_assessed": True,
        },
        "hash_bindings": {
            "proposal": ref(PROPOSAL, "proposal"),
            "writer": ref(WRITER, "writer"),
            "root_review_script": ref(Path(__file__).resolve(), "root-review implementation"),
        },
        "next_gate": "write literal Definition and contract, then run exactly one CPU/native preflight; any hard failure closes this input with zero credit",
    }
    return receipt


def write_receipt(output: Path = ROOT_RECEIPT) -> dict[str, Any]:
    output = Path(output).resolve()
    receipt = build_receipt()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    receipt["receipt"] = {"path": str(output), "sha256": sha256(output), "bytes": output.stat().st_size}
    return receipt


def verify_receipt(path: Path = ROOT_RECEIPT) -> dict[str, Any]:
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != SCHEMA or value.get("status") != "authorized_one_fresh_cpu_native_preflight_only":
        raise ValueError("root-review schema/status mismatch")
    if value.get("qualification_claim") != "none" or value.get("matrix_credit") != 0:
        raise ValueError("root-review credit is not closed")
    validate_proposal()
    for key in ("proposal", "writer", "root_review_script"):
        _assert_ref(value["hash_bindings"][key], key)
    if value["hash_bindings"]["root_review_script"]["path"] != str(Path(__file__).resolve()):
        raise ValueError("root-review implementation path changed")
    case = value["case"]
    if case["definition"] != str(DEFAULT_DEFINITION.resolve()) or case["contract"] != str(DEFAULT_CONTRACT.resolve()):
        raise ValueError("fresh input path changed")
    authorization = value["authorization"]
    if authorization["gencase_invocations"] != 1 or authorization["native_decode_invocations"] != 1:
        raise ValueError("CPU/native authorization count changed")
    for key in ("solver_launch", "gpu_launch", "job_spec_creation", "matrix_materialized", "matrix_submission"):
        if authorization[key] is not False:
            raise ValueError(f"authorization opened: {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation"):
        if authorization[key] != 0:
            raise ValueError(f"authorization opened: {key}")
    return {"status": "ok", "receipt": str(path), "case_id": case["case_id"],
            "gencase_invocations": 1, "native_decode_invocations": 1,
            "solver": False, "gpu": False, "queue": 0, "matrix_credit": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("write"); p.add_argument("--output", type=Path, default=ROOT_RECEIPT)
    p = sub.add_parser("verify"); p.add_argument("--receipt", type=Path, default=ROOT_RECEIPT)
    args = parser.parse_args()
    result = write_receipt(args.output) if args.command == "write" else verify_receipt(args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
