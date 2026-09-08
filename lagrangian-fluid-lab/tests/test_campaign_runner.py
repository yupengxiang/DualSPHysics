from __future__ import annotations

import sys

import pytest

from scripts.campaign_runner import execute_attempt


def test_successful_attempt_is_unique_and_published(tmp_path):
    script = ("from pathlib import Path; import sys; "
              "p=Path(sys.argv[1]); (p/'data').mkdir(); "
              "(p/'data'/'Part_0000.bi4').write_bytes(b'ok'); print('Finished')")
    template = [sys.executable, "-c", script, "{output}"]
    first = execute_attempt("case-a", template, tmp_path, required_text="Finished")
    second = execute_attempt("case-a", template, tmp_path, required_text="Finished")
    assert first["status"] == second["status"] == "completed"
    assert first["attempt_id"] != second["attempt_id"]
    attempts = list((tmp_path / "case-a" / "attempts").glob("*.complete"))
    assert len(attempts) == 2
    assert not list((tmp_path / "case-a" / "attempts").glob("*.partial"))
    assert (tmp_path / "case-a" / "latest.json").is_file()


def test_failed_attempt_preserves_evidence_without_replacing_latest(tmp_path):
    template = [sys.executable, "-c", "print('not complete')", "{output}"]
    result = execute_attempt("case-b", template, tmp_path)
    assert result["status"] == "failed"
    assert list((tmp_path / "case-b" / "attempts").glob("*.failed"))
    assert not (tmp_path / "case-b" / "latest.json").exists()


def test_unsafe_case_id_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unsafe"):
        execute_attempt("../escape", ["true", "{output}"], tmp_path)


def test_timed_out_attempt_is_published_as_failed(tmp_path):
    template = [sys.executable, "-c", "import time; time.sleep(2)", "{output}"]
    result = execute_attempt("case-timeout", template, tmp_path, timeout_seconds=0.05)
    assert result["status"] == "failed"
    assert result["timed_out"] is True
    assert result["process_group_terminated"] is True
    assert result["returncode"] == -9
    assert list((tmp_path / "case-timeout" / "attempts").glob("*.failed"))
