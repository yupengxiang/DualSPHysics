from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f8_static_review_bundle_v3 import CURRENT_CARD, OUTPUT, build_bundle


ROOT = Path(__file__).resolve().parents[1]


def test_v3_bundle_binds_current_body_force_card_without_admission() -> None:
    bundle = build_bundle()
    assert bundle["schema"] == "core.cfd.f8.static_review_bundle.v3"
    assert bundle["status"] == "static_review_bundle_v3_pending_root_decision"
    assert bundle["qualification_credit"] == 0
    assert bundle["current_candidate_card"]["schema"].endswith("candidate.v2")
    assert bundle["current_candidate_card"]["mechanism_name"] == (
        "body-force-driven oscillatory viscous channel")
    assert bundle["current_candidate_card"]["root_scope_decision"] == (
        "pending_formal_root_scope_ruling")
    assert bundle["execution_controls"]["definition_written"] is False
    assert bundle["execution_controls"]["solver_invoked"] is False
    assert bundle["execution_controls"]["registry_mutation"] == 0
    assert len(bundle["bindings"]) == 14


def test_committed_v3_bundle_hash_closes_current_candidate() -> None:
    assert OUTPUT.is_file()
    bundle = json.loads(OUTPUT.read_text(encoding="utf-8"))
    row = next(item for item in bundle["bindings"] if item["path"] == str(CURRENT_CARD))
    path = ROOT / row["path"]
    assert path.stat().st_size == row["bytes"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
