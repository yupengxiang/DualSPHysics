#!/usr/bin/env python3
"""Bind the current F8 v2 candidate card into a new static review bundle."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts import f8_static_review_bundle_v2 as _legacy


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / (
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/"
    "static-review-bundle-v3/bundle.json")
SCHEMA = "core.cfd.f8.static_review_bundle.v3"
CURRENT_CARD = Path(
    "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001/candidate-card-v2.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_bundle() -> dict[str, Any]:
    bundle = copy.deepcopy(_legacy.build_bundle())
    current = LAB / CURRENT_CARD
    if not current.is_file():
        raise FileNotFoundError(current)
    card = json.loads(current.read_text(encoding="utf-8"))
    if card["schema"] != "core.cfd.f8_oscillatory_body_force_channel_candidate.v2":
        raise ValueError("current F8 candidate card is not the body-force v2 card")
    if card["qualification_credit"] != 0 or card["status"] != "static_revision_pending_root_scope_ruling":
        raise ValueError("current F8 candidate card is not static-only and pending root ruling")
    bundle["schema"] = SCHEMA
    bundle["status"] = "static_review_bundle_v3_pending_root_decision"
    bundle["bindings"].append({
        "path": str(CURRENT_CARD),
        "sha256": sha256(current),
        "bytes": current.stat().st_size,
        "role": "current F8 body-force candidate card v2",
    })
    bundle["current_candidate_card"] = {
        "path": str(CURRENT_CARD),
        "schema": card["schema"],
        "mechanism_name": card["mechanism"]["name"],
        "root_scope_decision": card["root_decision"]["status"],
    }
    bundle["execution_controls"]["definition_written"] = False
    bundle["execution_controls"]["control_written"] = False
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = build_bundle()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("schema", "status", "qualification_credit", "execution_controls")},
                     indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
