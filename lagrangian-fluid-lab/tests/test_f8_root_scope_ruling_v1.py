from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.f8_root_scope_ruling_v1 import OUTPUT, build_receipt, write_receipt


ROOT = Path(__file__).resolve().parents[1]


def test_explicit_scope_ruling_opens_only_static_review() -> None:
    receipt = build_receipt()
    assert receipt["status"] == "accepted_as_distinct_mechanism_family_static_review_only"
    assert receipt["user_ruling"]["selection"] == "mechanism_family_gate"
    assert receipt["user_ruling"]["inferred"] is False
    assert receipt["scope_effect"]["eligible_for_core_third_family_denominator"] is False
    assert receipt["qualification_claim"] == "none"
    assert receipt["qualification_credit"] == 0
    assert all(value is False for value in receipt["execution_controls"].values() if isinstance(value, bool))
    assert all(value == 0 for key, value in receipt["execution_controls"].items() if key.endswith("_mutation"))


def test_committed_ruling_is_hash_closed_and_immutable(tmp_path: Path) -> None:
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    for binding in payload["bindings"]:
        path = ROOT / binding["path"]
        assert path.is_file()
        assert path.stat().st_size == binding["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == binding["sha256"]
    target = tmp_path / "receipt.json"
    write_receipt(target)
    with pytest.raises(FileExistsError):
        write_receipt(target)
