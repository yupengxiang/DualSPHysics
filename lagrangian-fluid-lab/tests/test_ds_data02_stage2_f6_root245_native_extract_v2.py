"""Tests for the ROOT245 proof-shape-compatible native extractor v2."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f6_root245_native_extract_v2.py"
ROOT245_REQUEST = Path(__file__).parents[1] / "campaigns/ds-data-02/stage2/requests/typed-lifecycle-batch-v1-f6-root-forward-245-002.json"
ROOT245_PROOF = Path(__file__).parents[1] / "campaigns/ds-data-02/stage2/checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_245.json"


def _module():
    spec = importlib.util.spec_from_file_location("f6_root245_native_extract_v2_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_self_test_binds_actual_batch_proof_shape() -> None:
    completed = subprocess.run([sys.executable, str(SCRIPT), "self-test"], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema"] == "ds02.stage2.f6-root245-native-extract.v2"
    assert result["launch_allowed"] is False
    assert "batch_summary_string_and_sha" in result["checks"]


@pytest.mark.skipif(not ROOT245_REQUEST.is_file() or not ROOT245_PROOF.is_file(), reason="ROOT245 request/proof is not present")
def test_actual_root245_proof_is_source_bound_without_records_content_read(tmp_path: Path) -> None:
    output_root = tmp_path / "root245-native-v2"
    request_output = tmp_path / "root245-native-v2-request.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--root245-request",
            str(ROOT245_REQUEST),
            "--terminal-proof",
            str(ROOT245_PROOF),
            "--output-root",
            str(output_root),
            "--request-output",
            str(request_output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["terminal_proof_bound"] is True
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["batch_proof_edges"]["batch_summary"]["source_shape"] == "string"
    assert manifest["batch_proof_edges"]["report"]["source_shape"] == "string"
    contract = json.loads(Path(manifest["cases"][0]["path"]).read_text(encoding="utf-8"))
    records = contract["typed_deferred"]["records"]
    assert records["bytes"] > 100 * 1024 * 1024
    assert records["content_opened_by_preparer"] is False
    assert records["sha256"] != "PARENT_GUARD_COMPUTED"
    request = json.loads(request_output.read_text(encoding="utf-8"))
    assert request["case_id"] == "ROOT245_F6_NATIVE_EXTRACT_V2"
    assert request["launch_allowed"] is True
    assert request["batch_proof_edges"]["batch_summary"]["path"] in request["input_files"]
    assert request["batch_proof_edges"]["report"]["path"] in request["input_files"]
    assert records["path"] in request["deferred_input_files"]


def test_case_proof_requires_stat_dictionary_and_no_default_path(tmp_path: Path) -> None:
    module = _module()
    summary = tmp_path / "summary.json"
    summary.write_text("{}\n", encoding="utf-8")
    digest = module._digest(summary, "summary")
    with pytest.raises(module.ExtractError, match="records_stat_only"):
        module._proof_case_edge(
            {"records_stat_only": str(summary)},
            "fixture",
            "records_stat_only",
        )
    with pytest.raises(module.ExtractError, match="batch_summary_sha256"):
        module._proof_output_ref(
            {"batch_summary": str(summary)},
            "batch_summary",
            "batch_summary_sha256",
        )
    ref = module._proof_case_edge(
        {
            "summary": str(summary),
            "summary_sha256": digest,
        },
        "fixture",
        "summary",
        "summary_sha256",
    )
    assert ref["source_shape"] == "string"
