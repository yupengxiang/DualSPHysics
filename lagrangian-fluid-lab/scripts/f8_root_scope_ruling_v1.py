#!/usr/bin/env python3
"""Record the explicit user ruling for the F8 Core-family boundary.

This writer records only the scope interpretation.  It does not materialize an
input, run GenCase, or grant numerical qualification.  The preceding decision
packet remains immutable evidence that the choice was not inferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
OUTPUT = LAB / (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
    "root-scope-ruling-v1/receipt.json"
)
INPUTS = {
    "decision_packet": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
        "root-scope-decision-v1/packet.json"
    ),
    "candidate_card": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
        "candidate-card-v2.json"
    ),
    "static_bundle": Path(
        "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
        "static-review-bundle-v3/bundle.json"
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(relative: Path, role: str) -> dict[str, Any]:
    path = (LAB / relative).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(relative),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "role": role,
    }


def build_receipt() -> dict[str, Any]:
    packet_path = LAB / INPUTS["decision_packet"]
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if packet.get("status") != "awaiting_user_root_scope_ruling":
        raise ValueError("the immutable decision packet no longer has its expected pending status")
    if packet.get("no_implicit_selection") is not True:
        raise ValueError("the preceding packet must prove that selection was explicit")
    if packet.get("scope_id") != SCOPE:
        raise ValueError("scope identity mismatch")

    return {
        "schema": "core.cfd.f8.root_scope_ruling.v1",
        "scope_id": SCOPE,
        "status": "accepted_as_distinct_mechanism_family_static_review_only",
        "user_ruling": {
            "selection": "mechanism_family_gate",
            "statement": (
                "Accept the fully filled, body-force-driven oscillatory channel "
                "as the third independent T1 mechanism family for Core."
            ),
            "free_surface_required_for_this_family": False,
            "inferred": False,
        },
        "scope_effect": {
            "eligible_for_next_step": "Definition/control static hash review",
            "eligible_for_core_third_family_denominator": False,
            "reason": "T1 qualification has not occurred; this is a scope ruling only.",
        },
        "next_required_action": "independent static review of a fresh Definition/control design",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "execution_controls": {
            "control_written": False,
            "definition_written": False,
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
            _binding(INPUTS["decision_packet"], "immutable pending decision packet"),
            _binding(INPUTS["candidate_card"], "current F8 candidate card"),
            _binding(INPUTS["static_bundle"], "current pre-ruling static bundle"),
            _binding(Path("scripts/f8_root_scope_ruling_v1.py"), "ruling receipt writer"),
        ],
    }


def write_receipt(path: Path) -> dict[str, Any]:
    target = path.resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable scope ruling: {target}")
    receipt = build_receipt()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    receipt = write_receipt(args.output)
    print(json.dumps({key: receipt[key] for key in (
        "schema", "status", "qualification_claim", "qualification_credit", "execution_controls"
    )}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
