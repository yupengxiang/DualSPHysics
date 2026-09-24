#!/usr/bin/env python3
"""Write the no-execution root decision packet for F3 material row 30."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/material/evidence"
READINESS = EVIDENCE / "f3-material-t2-launch-readiness-v1/receipt.json"
QUALIFICATION = LAB / "campaigns/core-v1/evidence/f3-inherited-qualification.json"
OUTPUT = EVIDENCE / "f3-material-row30-root-decision-v1/packet.json"
READINESS_SCHEMA = "core.material.f3.t2.launch_readiness.v1"
QUALIFICATION_SCHEMA = "core.qualification.v1"


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path.relative_to(LAB)), "bytes": path.stat().st_size, "sha256": sha256(path), "role": role}


def _require_schema(value: dict[str, Any], expected: str, role: str) -> None:
    schema = value.get("schema")
    if type(schema) is not str or schema != expected:
        raise ValueError(f"{role} schema mismatch")


def build_packet() -> dict[str, Any]:
    readiness = json.loads(READINESS.read_text(encoding="utf-8"))
    _require_schema(readiness, READINESS_SCHEMA, "F3 readiness")
    qualification = json.loads(QUALIFICATION.read_text(encoding="utf-8"))
    _require_schema(qualification, QUALIFICATION_SCHEMA, "F3 qualification")
    candidate = readiness.get("next_executable_step", {})
    if not (
        candidate.get("candidate_configuration_id") == "F3-material-30"
        and candidate.get("candidate_matrix_row") == 30
        and candidate.get("status") == "authorization_required_before_execution"
        and qualification.get("T1_numerical") is True
        and qualification.get("T2_macro") is False
    ):
        raise ValueError("F3 row 30 readiness is not the expected zero-credit candidate")
    return {
        "schema": "core.material.f3.row30.root_decision_packet.v1",
        "status": "awaiting_user_root_decision_for_new_row30_attempt",
        "question": "May Core create a fresh, one-attempt CPU material diagnostic for F3-material-30 after a new resource/scheduler preflight?",
        "candidate": {
            "configuration_id": "F3-material-30",
            "matrix_row": 30,
            "q": 0.5,
            "resolution": "production",
            "seeds": 4096,
            "substeps": 4,
            "window": "full 8.35 s native source",
            "existing_s2_result": "noncanonical related diagnostic that failed the unknown gate; it cannot be reused as row 30",
        },
        "evidence": [ref(READINESS, "F3 material T2 launch-readiness audit"), ref(QUALIFICATION, "F3 T1 qualification")],
        "options": {
            "authorize_new_row30_attempt": {
                "effect": "permits only an immutable exact-input resource/scheduler authorization for one new CPU material attempt",
                "does_not_grant": ["immediate worker launch", "solver", "GPU", "queue mutation", "registry mutation", "ledger mutation", "T2 credit", "matrix expansion"],
                "required_next_gates": ["source hash and availability check", "fresh resource allocation", "new output namespace", "same-argv checkpoint/resume contract", "immutable positive-or-negative result receipt"],
                "qualification_credit": 0,
            },
            "defer_or_close_row30": {
                "effect": "preserves all old F3 material evidence and leaves row 30 absent from the accepted T2 matrix",
                "qualification_credit": 0,
            },
        },
        "invariants": {
            "existing_s2_output_reuse_forbidden": True,
            "unknown_and_right_censor_retained": True,
            "threshold_relaxation_forbidden": True,
            "T2_macro": False,
            "T2_path": False,
            "qualification_credit": 0,
        },
        "execution_controls": {"material_worker_started": False, "solver_started": False, "gpu_started": False, "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0, "matrix_mutation": 0},
        "no_implicit_selection": True,
    }


def write_packet(path: Path = OUTPUT) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable F3 row30 decision packet: {path}")
    packet = build_packet()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    packet = write_packet(args.output)
    print(json.dumps({key: packet[key] for key in ("status", "question")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
