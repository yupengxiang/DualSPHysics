#!/usr/bin/env python3
"""Build a hash-bound, non-authorizing F9 root-admission proposal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
PLAN = Path("/home/jade/Projects/DualSPHysics/PLAN.md")
ROOT = LAB / "campaigns/core-v1/cfd/f9-gravity-film-nusselt-r001"
CARD = ROOT / "candidate-card-v1.json"
CONTRACT = ROOT / "definition-contract-v1.json"
DEFINITION = ROOT / "input/F9_GRAVITY_FILM_NUSSELT_R001_Def.xml"
REVIEW = ROOT / "root-review/terra-high-definition-review-v3.json"
OUTPUT = ROOT / "root-review/root-admission-proposal-v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.relative_to(LAB)) if path.is_relative_to(LAB) else str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def build_proposal() -> dict[str, Any]:
    card = json.loads(CARD.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert card["scope_id"] == "F9_GRAVITY_FILM_NUSSELT_R001"
    assert card["family"] == "F9"
    assert card["admission_granted"] is False
    assert card["qualification_credit"] == 0
    assert contract["admission_granted"] is False
    assert contract["qualification_credit"] == 0
    assert review["decision"] == "CONDITIONAL-GO"
    assert review["admission_granted"] is False
    assert review["credit"] == 0

    controls = {
        "definition_candidate_materialized": True,
        "definition_write_authorization": False,
        "native_preflight": False,
        "gencase": False,
        "bi4": False,
        "solver": False,
        "gpu": False,
        "queue": False,
        "registry": False,
        "ledger": False,
        "denominator": False,
        "t1_registration": False,
        "formal_training_admission": False,
    }
    evidence = [
        bind(PLAN, "Core plan governing admission and execution boundaries"),
        bind(CARD, "F9 candidate card"),
        bind(CONTRACT, "F9 static Definition contract"),
        bind(DEFINITION, "F9 static Definition XML"),
        bind(REVIEW, "Terra High corrected Definition review v3"),
    ]
    return {
        "schema": "core.cfd.f9.root_admission_proposal.v1",
        "status": "proposal_only_waiting_for_root_decision",
        "scope_id": "F9_GRAVITY_FILM_NUSSELT_R001",
        "family": "F9",
        "revision": "r001",
        "third_t1_family_candidate": True,
        "requested_root_decision": "admit F9 for target-specific native semantic preflight only, or reject with a recorded reason",
        "admission_granted": False,
        "qualification_credit": 0,
        "current_scientific_status": "static_definition_conditionally_reviewed_not_t1_qualified",
        "terra_high_decision": review["decision"],
        "required_before_any_qualification": [
            "formal root admission explicitly authorizes target-specific native semantic preflight",
            "native preflight verifies BI4 geometry and MapRealSize.x=0.24 m",
            "a fresh T1 qualification matrix is separately admitted and executed",
            "only after T1 qualification, register the fixed 32-case production batch",
        ],
        "forbidden_until_separate_root_authorization": [
            "GenCase or BI4 generation",
            "solver or GPU execution",
            "13+2 qualification matrix execution",
            "32-case production generation or execution",
            "T1 registration",
            "formal training admission",
            "registry, ledger, readiness, completion, denominator mutation",
        ],
        "execution_controls": controls,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_proposal()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("schema", "status", "scope_id", "admission_granted", "execution_controls")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
