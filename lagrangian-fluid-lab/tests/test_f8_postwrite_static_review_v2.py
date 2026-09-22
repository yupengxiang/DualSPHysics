from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f8_postwrite_static_review_v2 as review_module


ROOT = Path(__file__).resolve().parents[1]


def test_postwrite_review_passes_and_remains_zero_credit() -> None:
    review = review_module.build_review()
    assert review["status"] == "input_materialized_postwrite_static_verification_passed"
    assert review["static_constraint_gaps"] == []
    assert review["qualification_claim"] == "none"
    assert review["qualification_credit"] == 0
    assert review["input_materialization"]["verified"] is True
    assert review["cpu_preflight"]["authorized"] is False
    assert review["cpu_preflight"]["requires_separate_immutable_authorization"] is True
    assert review["execution_controls"]["solver_invoked"] is False
    assert review["execution_controls"]["queue_mutation"] == 0


def test_postwrite_review_rejects_any_input_or_parameter_tampering(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_module, "validate_csv", lambda gaps, values: gaps.append({"code": "CSV_SINE", "detail": "synthetic tamper"}))
    review = review_module.build_review()
    assert review["status"] == "input_materialized_postwrite_static_verification_failed"
    assert review["input_materialization"]["verified"] is False
    assert review["static_constraint_gaps"][-1]["code"] == "CSV_SINE"


def test_committed_review_is_hash_closed_and_immutable(tmp_path: Path) -> None:
    review = json.loads(review_module.OUTPUT.read_text(encoding="utf-8"))
    assert review["status"] == "input_materialized_postwrite_static_verification_passed"
    for item in review["bindings"]:
        # The active lifecycle test is intentionally not an evidence input:
        # it may evolve to test later fail-closed transitions without
        # rewriting this immutable post-write receipt.
        if item["path"] == "tests/test_f8_postwrite_static_review_v2.py":
            continue
        path = ROOT / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    target = tmp_path / "review.json"
    review_module.write_review(target)
    with pytest.raises(FileExistsError):
        review_module.write_review(target)
