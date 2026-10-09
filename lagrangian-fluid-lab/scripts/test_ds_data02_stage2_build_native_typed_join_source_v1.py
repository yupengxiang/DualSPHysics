from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_native_typed_join_source_v1 as subject


BASE = Path(__file__).resolve().parents[1] / "campaigns" / "ds-data-02" / "stage2"


def _actual_args(output: Path):
    return [
        "build",
        "--inventory", str(BASE / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"),
        "--overlay", str(BASE / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"),
        "--root274-request", str(BASE / "requests/generic-native-extract-v1-root-forward-274-002.json"),
        "--root308-request", str(BASE / "requests/generic-native-extract-v2-root-forward-308-002.json"),
        "--root309-request", str(BASE / "requests/generic-native-extract-v1-root-forward-309-002.json"),
        "--root312-checkpoint", str(BASE / "checkpoints/ROOT312_F4_MULTI_PROOF_INTAKE_PENDING_V2.json"),
        "--output", str(output),
    ]


def test_real_v10_proof_set_reconstructs_47_and_future_pending_scope(tmp_path: Path) -> None:
    output = tmp_path / "join-source.json"
    completed = subprocess.run([sys.executable, str(subject.SCRIPT), *_actual_args(output)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["summary"]["actual_join_cases_from_v10_proofs"] == 47
    assert value["summary"]["future_exact_source_prepared_cases"] == 17
    assert value["summary"]["future_root312_selected_cases_without_ids"] == 7
    assert value["summary"]["native_cause_bound_without_precise_typed_native_join"] == 47
    assert value["read_policy"]["typed_jsonl_content_opened"] is False


def test_sentinel_hash_is_preserved_as_unverified_only_for_deferred_edge(tmp_path: Path) -> None:
    value = {"path": str(tmp_path / "records.jsonl"), "sha256": "PARENT_GUARD_COMPUTED", "bytes": 12}
    assert subject._edge(value, "deferred", allow_unverified_sha=True)["hash_status"] == "UNVERIFIED_SENTINEL_DECLARATION"
    with pytest.raises(subject.JoinSourceError, match="SHA is not"):
        subject._edge(value, "static")


def test_real_v10_overlay_duplicate_proof_reference_is_rejected(tmp_path: Path) -> None:
    overlay_path = BASE / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    overlay["actual_join_proofs"][1] = overlay["actual_join_proofs"][0]
    altered = tmp_path / "overlay.json"
    altered.write_text(json.dumps(overlay) + "\n", encoding="utf-8")
    args = _actual_args(tmp_path / "bad.json")
    args[args.index("--overlay") + 1] = str(altered)
    completed = subprocess.run([sys.executable, str(subject.SCRIPT), *args], capture_output=True, text=True, check=False)
    assert completed.returncode == 2
    assert "duplicate path" in completed.stdout


def test_source_only_cli_self_test() -> None:
    completed = subprocess.run([sys.executable, str(subject.SCRIPT), "self-test"], capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert '"status": "PASS"' in completed.stdout
