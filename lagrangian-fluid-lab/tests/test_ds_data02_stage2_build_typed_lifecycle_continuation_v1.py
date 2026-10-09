"""Source-only tests for the generic typed-lifecycle continuation builder."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_build_typed_lifecycle_continuation_v1.py"
ROOT245_REQUEST = Path("/tmp/ds02-root245-f6-prepared-20261010-b/typed-lifecycle-batch-v1-f6-root-forward-245-001.json")


def test_self_test_is_metadata_only() -> None:
    completed = subprocess.run([sys.executable, str(SCRIPT), "self-test"], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["launch_allowed"] is False
    assert result["trajectory_content_opened"] is False
    assert result["trajectory_content_hashed"] is False


@pytest.mark.skipif(not ROOT245_REQUEST.is_file(), reason="pending ROOT245 request is not present")
def test_prepare_selects_exact_nonoverlap_group_without_h5_content(tmp_path: Path) -> None:
    output_dir = tmp_path / "generic-f1-group"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--group-id",
            "F1-typed-lifecycle-continuation-000",
            "--exclude-request",
            str(ROOT245_REQUEST),
            "--attempt-label",
            "fixture001",
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["family_id"] == "F1"
    assert result["group_id"] == "F1-typed-lifecycle-continuation-000"
    assert len(result["case_ids"]) == 8
    assert result["selected_source_bytes"] <= 20 * 1024 * 1024 * 1024
    assert result["excluded_case_count"] >= 95  # 87 completed + alias + pending ROOT245 F6 group
    assert result["launch_allowed"] is False
    assert result["trajectory_content_opened"] is False
    assert result["trajectory_content_hashed"] is False

    final = json.loads(Path(result["final_request"]).read_text(encoding="utf-8"))
    assert final["launch_allowed_by_helper"] is False
    assert final["execution_allowed_by_helper"] is False
    assert final["continuation_group"]["case_ids"] == result["case_ids"]
    assert final["continuation_group"]["pending_or_consumed_excluded_case_ids"]
    assert final["source_read_policy"]["h5_or_native_opened"] is False


@pytest.mark.skipif(not ROOT245_REQUEST.is_file(), reason="pending ROOT245 request is not present")
def test_prepare_rejects_pending_case_overlap_before_output(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--group-id",
            "F1-typed-lifecycle-continuation-000",
            "--exclude-request",
            str(ROOT245_REQUEST),
            "--exclude-case",
            "F1_ECC_HEAD_110_UNCHANGED_MOTHER_GEOMETRY_V1_INITIAL_VX010_MS_V1",
            "--attempt-label",
            "overlap001",
            "--output-dir",
            str(tmp_path / "should-not-be-created"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "selected group overlaps" in completed.stdout
    assert not (tmp_path / "should-not-be-created").exists()
