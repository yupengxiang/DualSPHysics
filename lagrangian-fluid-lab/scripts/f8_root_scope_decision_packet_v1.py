#!/usr/bin/env python3
"""Build the explicit, non-executing F8 Core scope decision packet."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
    "root-scope-decision-v1/packet.json")
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"

INPUTS = {
    "plan": Path("../PLAN.md"),
    "candidate_card": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v2.json"),
    "static_bundle": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/static-review-bundle-v3/bundle.json"),
    "frontier_audit": Path(
        "campaigns/core-v1/evidence/core-third-t1-frontier-audit-20260922-v2.json"),
    "completion": Path("campaigns/core-v1/completion.json"),
}


def _resolve(relative: Path) -> Path:
    path = (LAB / relative).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(relative: Path, role: str) -> dict[str, Any]:
    path = _resolve(relative)
    return {"path": str(relative), "sha256": sha256(path),
            "bytes": path.stat().st_size, "role": role}


def build_packet() -> dict[str, Any]:
    for relative in INPUTS.values():
        _resolve(relative)
    return {
        "schema": "core.cfd.f8.root_scope_decision_packet.v1",
        "scope_id": SCOPE,
        "status": "awaiting_user_root_scope_ruling",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "question": (
            "Does PLAN Core accept a fully filled, non-free-surface "
            "body-force-driven oscillatory channel as the third mechanism family?"),
        "decision_options": {
            "mechanism_family_gate": {
                "label": "Accept by distinct mechanism family",
                "core_scope": "candidate eligible for the next independent root review",
                "does_not_grant": [
                    "T1 qualification", "Definition/control write", "CPU/native preflight",
                    "solver/GPU", "queue/registry/ledger mutation", "training",
                ],
                "next_step_after_explicit_yes": "prepare a new root review for Definition/control static hash closure",
            },
            "free_surface_gate": {
                "label": "Require a free-surface mechanism for Core",
                "core_scope": "F8 excluded from Core third-family denominator",
                "qualification_credit": 0,
                "next_step": "retain F8 as a post-Core extension candidate",
            },
        },
        "no_implicit_selection": True,
        "current_evidence_summary": {
            "candidate_status": "static_revision_pending_root_scope_ruling",
            "static_bundle_status": "static_review_bundle_v3_pending_root_decision",
            "startup_oracle": "continuum_reference_only",
            "observation_parser": "static_payload_parser_no_native_source",
            "three_t1_families_currently": ["F3", "F4"],
            "macro_t2_families_currently": [],
        },
        "execution_controls": {
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
        },
        "bindings": [
            binding(relative, role)
            for relative, role in (
                (INPUTS["plan"], "adopted Core plan"),
                (INPUTS["candidate_card"], "current F8 body-force candidate card v2"),
                (INPUTS["static_bundle"], "current F8 static review bundle v3"),
                (INPUTS["frontier_audit"], "current third-T1 frontier audit"),
                (INPUTS["completion"], "authoritative Core completion state"),
            )
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    packet = build_packet()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: packet[key] for key in
                      ("schema", "status", "qualification_credit", "execution_controls")},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
