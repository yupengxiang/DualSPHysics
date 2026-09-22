#!/usr/bin/env python3
"""Build a renamed, static-only F8 candidate card without rewriting v1."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
SOURCE = LAB / (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v1.json")
OUTPUT = LAB / (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v2.json")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(relative: str, role: str) -> dict[str, Any]:
    path = LAB / relative
    return {"path": relative, "sha256": sha256(path),
            "bytes": path.stat().st_size, "role": role}


def build_card() -> dict[str, Any]:
    value = json.loads(SOURCE.read_text(encoding="utf-8"))
    value = copy.deepcopy(value)
    value["schema"] = "core.cfd.f8_oscillatory_body_force_channel_candidate.v2"
    value["revision"] = "r002"
    value["status"] = "static_revision_pending_root_scope_ruling"
    value["scientific_status"] = "not_executed_not_admitted_zero_credit"
    value["qualification_credit"] = 0
    value["mechanism"]["name"] = "body-force-driven oscillatory viscous channel"
    value["mechanism"]["description"] = (
        "Fully filled single-phase viscous fluid in a channel periodic in x/y, "
        "with fixed no-slip walls at z=+/-H and uniform body acceleration "
        "ax(t)=A sin(omega t).")
    value["mechanism"]["analytical_reference"] = (
        "Womersley harmonic and zero-initial-velocity startup response of "
        "du/dt = ax(t) + nu*d2u/dz2")
    value["independence_review"]["boundary_interpretation"] = (
        "Static evidence supports a distinct mechanism family; root must decide "
        "whether a fully filled non-free-surface family is admissible for Core.")
    value["static_contract"]["must_have"].append(
        "body-force-driven naming and explicit constant-density pressure-equivalence statement")
    value["static_contract"]["reference_oracle"] = {
        "steady_contract": "reference-oracle-v1/contract.json",
        "startup_contract": "reference-oracle-v2/contract.json",
        "observation_parser_contract": "observation-parser-v1/contract.json",
        "startup_is_continuum_reference_not_weakly_compressible_evidence": True,
    }
    value["root_decision"] = {
        "status": "pending_formal_root_scope_ruling",
        "question": "Does PLAN Core accept a fully filled non-free-surface mechanism as the third family?",
        "option_if_mechanism_family_gate": {
            "admissible_candidate": True,
            "qualification_credit": 0,
            "next_action_after_root_yes": "new root review for Definition/control static hash closure",
        },
        "option_if_free_surface_gate": {
            "admissible_candidate": False,
            "qualification_credit": 0,
            "next_action": "retain as post-Core extension candidate",
        },
        "no_implicit_selection": True,
    }
    value["supersedes_for_current_static_review"] = {
        "path": str(SOURCE.relative_to(LAB)),
        "sha256": sha256(SOURCE),
        "role": "immutable historical v1 candidate card",
    }
    value["current_static_evidence"] = [
        ref("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/static-review-bundle-v2/bundle.json",
            "current F8 static review bundle v2"),
        ref("scripts/f8_candidate_card_v2.py", "v2 card builder"),
    ]
    value["execution_controls"] = {
        "definition_written": False,
        "control_written": False,
        "gencase_invoked": False,
        "native_decode_invoked": False,
        "solver_invoked": False,
        "gpu_started": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "training_started": False,
    }
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = build_card()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("schema", "status", "qualification_credit", "execution_controls")},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
