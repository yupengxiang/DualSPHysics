from __future__ import annotations

import json

import pytest

from scripts import f8_r008_t1_metric_adapter_review_v1 as review


def test_adapter_review_archive_records_terra_high_pass_without_execution() -> None:
    value = review.build_receipt()
    assert value["reviewer"]["model"] == "gpt-5.6-terra"
    assert value["reviewer"]["reasoning_effort"] == "high"
    assert value["reviewer"]["verdict"] == "PASS"
    assert value["reviewer"]["reviewer_ran_pytest"] is True
    assert "same Terra High agent thread" in value["reviewer"]["review_thread_note"]
    assert value["reviewer_validation"]["adapter_tests"]["passed"] == 18
    assert value["reviewer_validation"]["archive_tests"]["passed"] == 4
    assert value["parent_validation"] == {
        "command": "PYTHONPATH=. .venv/bin/pytest -q tests/test_f8_r008_t1_metric_adapter_v1.py",
        "passed": 18,
        "failed": 0,
    }
    assert [item["verdict"] for item in value["findings"]] == ["PASS"] * 4
    assert value["disposition"]["static_adapter_accepted"] is True
    assert value["qualification_credit"] == 0
    assert all(value["execution_authority"][key] is False
               for key in ("solver", "gpu", "worker", "queue"))


def test_adapter_review_archive_binds_code_tests_and_trusted_anchor() -> None:
    value = review.build_receipt()
    by_role = {item["role"]: item for item in value["evidence"]}
    adapter_binding = by_role["reviewed static F8 R008 metric adapter"]
    test_binding = by_role["adapter identity, metric, provenance, and matrix tests"]
    assert adapter_binding["path"] == "scripts/f8_r008_t1_metric_adapter_v1.py"
    assert test_binding["path"] == "tests/test_f8_r008_t1_metric_adapter_v1.py"
    assert by_role["pinned zero-credit R008 CPU/native anchor receipt"]["sha256"] == review.adapter.FROZEN_INPUT_SHA256["anchor_preflight"]
    assert all(len(item["sha256"]) == 64 for item in value["evidence"])
    assert len(value["remaining_limitations"]) == 2


def test_review_archive_writer_is_immutable_and_verifier_recomputes(tmp_path) -> None:
    target = tmp_path / "review.json"
    assert review.write_receipt(target) == target
    assert json.loads(target.read_text(encoding="utf-8")) == review.verify_receipt(target)
    with pytest.raises(FileExistsError, match="immutable F8 R008 adapter review receipt"):
        review.write_receipt(target)


def test_review_archive_build_failure_leaves_no_target(tmp_path, monkeypatch) -> None:
    target = tmp_path / "review.json"

    def fail_build():
        raise ValueError("synthetic evidence drift")

    monkeypatch.setattr(review, "build_receipt", fail_build)
    with pytest.raises(ValueError, match="synthetic evidence drift"):
        review.write_receipt(target)
    assert not target.exists()
