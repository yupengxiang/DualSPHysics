"""Source-only checks for the ROOT253 F4 continuation handoff."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_build_root253_f4_typed_lifecycle_batch.py"
PLAN = Path(__file__).parents[1] / "campaigns/ds-data-02/stage2/checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT245_PENDING_V4.json"
ROOT245_REQUEST = Path(__file__).parents[1] / "campaigns/ds-data-02/stage2/requests/typed-lifecycle-batch-v1-f6-root-forward-245-002.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("root253_f4_builder_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_self_test_is_metadata_only() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "self-test"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["launch_allowed"] is False
    assert result["trajectory_content_opened"] is False


@pytest.mark.skipif(not PLAN.is_file() or not ROOT245_REQUEST.is_file(), reason="ROOT245 source plan/request is not present")
def test_prepare_selects_f4_group_and_keeps_pending_boundary(tmp_path: Path) -> None:
    output_dir = tmp_path / "root253-f4"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--group-id",
            "F4-typed-lifecycle-continuation-000",
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["family_id"] == "F4"
    assert len(result["case_ids"]) == 8
    assert result["declared_source_bytes"] <= 20 * 1024 * 1024 * 1024
    assert result["excluded_case_count"] == 95
    assert result["trajectory_content_opened"] is False
    assert result["trajectory_content_hashed"] is False
    assert result["launch_allowed"] is False

    final = json.loads(Path(result["final_request"]).read_text(encoding="utf-8"))
    assert final["family_id"] == "F4"
    assert final["physical_case_ids"] == result["case_ids"]
    assert final["launch_allowed_by_helper"] is False
    assert final["execution_allowed_by_helper"] is False
    assert final["source_read_policy"]["h5_or_native_opened"] is False
    assert set(final["continuation_group"]["excluded_case_ids"]) >= set(
        json.loads(ROOT245_REQUEST.read_text(encoding="utf-8"))["physical_case_ids"]
    )


@pytest.mark.skipif(not ROOT245_REQUEST.is_file(), reason="ROOT245 request is not present")
def test_pending_request_must_bind_exact_seven_cases(tmp_path: Path) -> None:
    module = _load_module()
    value = json.loads(ROOT245_REQUEST.read_text(encoding="utf-8"))
    value["physical_case_ids"] = list(value["physical_case_ids"][:-1])
    malformed = tmp_path / "wrong-pending.json"
    malformed.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.Root253Error, match="exactly bind seven pending F6"):
        module._validate_root245_pending(malformed)
