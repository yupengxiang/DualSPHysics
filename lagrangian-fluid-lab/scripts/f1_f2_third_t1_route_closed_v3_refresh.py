#!/usr/bin/env python3
"""Create a versioned current snapshot of the closed F1/F2 route audit.

The v2 receipt is historical and intentionally immutable.  This refresh binds
the same negative route evidence to the current Core completion receipt without
changing any qualification, denominator, registry, ledger, or execution state.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import f1_f2_third_t1_route_closed_v2 as legacy


LAB = Path(__file__).resolve().parents[1]
CARD_OUTPUT = LAB / "campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v3.json"
RECEIPT_OUTPUT = LAB / (
    "campaigns/core-v1/evidence/f1-f2-third-t1-route-decision-receipt-v3.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def build() -> tuple[dict, dict]:
    card = legacy.build_card()
    card["schema"] = "core.third_t1.f1_f2_route_closed.candidate_card.v3"
    card["version"] = "v3"
    card["candidate_id"] = "F1_F2_third_t1_no_new_hypothesis_v3"
    card["execution_host"] = "Terra High"
    card["refresh"] = {
        "historical_source": "campaigns/core-v1/cfd/f1-f2-third-t1-route-closed-v2.json",
        "historical_receipt_preserved": True,
        "current_completion_bound": True,
    }
    card["evidence"]["implementation"] = {
        "path": str(Path(__file__).relative_to(LAB)),
        "sha256": sha256(Path(__file__)),
        "bytes": Path(__file__).stat().st_size,
        "role": "versioned current read-only closure refresh",
    }

    receipt = legacy.build_receipt(card)
    receipt["schema"] = "core.third_t1.f1_f2.route_decision_receipt.v3"
    receipt["version"] = "v3"
    receipt["execution_host"] = "Terra High"
    receipt["candidate_card"] = {
        "path": str(CARD_OUTPUT.relative_to(LAB)),
        "sha256": None,
        "bytes": None,
    }
    receipt["refresh"] = card["refresh"]
    return card, receipt


def main() -> None:
    card, receipt = build()
    write_json(CARD_OUTPUT, card)
    receipt["candidate_card"] = {
        "path": str(CARD_OUTPUT.relative_to(LAB)),
        "sha256": sha256(CARD_OUTPUT),
        "bytes": CARD_OUTPUT.stat().st_size,
    }
    write_json(RECEIPT_OUTPUT, receipt)
    print(
        json.dumps(
            {
                "status": card["status"],
                "candidate": card["candidate_id"],
                "qualification_credit": card["core_gate"]["qualification_credit_added"],
                "completion_sha256": card["evidence"]["core_completion"]["sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
