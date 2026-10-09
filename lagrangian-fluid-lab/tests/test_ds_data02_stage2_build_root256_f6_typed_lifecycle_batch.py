from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_build_root256_f6_typed_lifecycle_batch.py"
PLAN = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT253_PENDING_V4.json"
OVERLAY = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT250_ACTUAL_OVERLAY_V6.json"

ROOT245 = {
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0875_YAWP06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1125_YAWP12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1375_YAWP18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1625_YAWM18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0375_YAWM12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0625_YAWM06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0875_YAWP06_DP025",
}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_root256_self_test_is_source_only() -> None:
    result = _run("self-test")
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["family_id"] == "F6"
    assert payload["group_id"] == "F6-typed-lifecycle-continuation-000"
    assert payload["launch_allowed"] is False
    assert payload["payload_content_opened"] is False


def test_root256_prepare_selects_exact_pending_f6_group_without_payload(tmp_path: Path) -> None:
    output_root = tmp_path / "root256"
    result = _run("prepare", "--output-root", str(output_root))
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "READY_NOTRUN_SOURCE_ONLY"
    assert payload["family_id"] == "F6"
    assert payload["group_id"] == "F6-typed-lifecycle-continuation-000"
    assert len(payload["case_ids"]) == 7
    assert payload["selected_source_bytes"] == 19_553_749_230
    assert payload["launch_allowed"] is False
    assert payload["payload_content_opened"] is False

    request = json.loads(Path(payload["request"]).read_text(encoding="utf-8"))
    followup = json.loads(Path(payload["native_followup"]).read_text(encoding="utf-8"))
    assert request["family_id"] == "F6"
    assert request["physical_case_ids"] == payload["case_ids"]
    assert request["launch_allowed"] is False
    assert request["execution_allowed"] is False
    assert request["request_submitted"] is False
    assert request["continuation_group"]["group_id"] == payload["group_id"]
    assert set(request["continuation_group"]["root245_cases_excluded"]) == ROOT245
    assert not (set(payload["case_ids"]) & ROOT245)
    assert followup["status"] == "WAITING_FOR_ROOT256_TERMINAL_PROOF"
    assert followup["case_ids"] == payload["case_ids"]
    assert followup["launch_allowed"] is False
    assert followup["payload_content_opened"] is False
    assert followup["current_catalog"]["sha256"] == "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"

    forbidden_suffixes = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}
    assert not any(Path(path).suffix.lower() in forbidden_suffixes for path in request["input_files"])
    assert request["source_closure"]["current_catalog"]["sha256"] == "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
    assert request["source_closure"]["scientific_audit"]["sha256"] == "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    selected = set(payload["case_ids"])
    group = next(item for item in plan["groups"] if item["group_id"] == payload["group_id"])
    assert selected == set(group["case_ids"])
    assert set(selected).issubset(set(group["case_ids"]))
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    assert selected.issubset(set(overlay["remaining_cause_not_located_case_ids"]) - ROOT245)
