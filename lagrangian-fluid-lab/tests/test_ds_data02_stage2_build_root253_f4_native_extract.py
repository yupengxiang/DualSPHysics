"""Source-only checks for the ROOT253 F4 native extractor handoff."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_build_root253_f4_native_extract.py"
ROOT253_REQUEST = Path("/tmp/ds02-root253-f4-v1-1791565225772571551/typed-lifecycle-batch-v1-f4-root-forward-253-001.json")


def _module():
    spec = importlib.util.spec_from_file_location("root253_f4_native_extract_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_self_test_is_source_only() -> None:
    completed = subprocess.run([sys.executable, str(SCRIPT), "self-test"], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["launch_allowed"] is False
    assert result["payload_opened"] is False


def test_terminal_proof_accepts_actual_string_summary_and_stat_dict_records(tmp_path: Path) -> None:
    module = _module()
    summary = tmp_path / "typed-lifecycle-v4-summary.json"
    records = tmp_path / "typed-lifecycle-v4-records.jsonl"
    summary.write_text("{}\n", encoding="utf-8")
    records.write_text('{"record_fields":"fixture"}\n', encoding="utf-8")
    row = {
        "summary": str(summary),
        "summary_sha256": module._digest(summary, "fixture summary"),
        "records_stat_only": {
            "path": str(records),
            "sha256": module._digest(records, "fixture records"),
            "bytes": records.stat().st_size,
            "rows": 1,
            "mtime_ns": records.stat().st_mtime_ns,
            "ctime_ns": records.stat().st_ctime_ns,
            "st_dev": records.stat().st_dev,
            "st_ino": records.stat().st_ino,
        },
    }
    summary_ref = module._normalize_typed_edge(row, "fixture-case", "summary")
    records_ref = module._normalize_typed_edge(row, "fixture-case", "records_stat_only")
    assert summary_ref["source_shape"] == "string"
    assert records_ref["source_shape"] == "stat_dict"
    assert summary_ref["content_opened_by_preparer"] is False
    assert records_ref["content_opened_by_preparer"] is False


def test_terminal_proof_rejects_missing_or_wrong_records_shape(tmp_path: Path) -> None:
    module = _module()
    summary = tmp_path / "summary.json"
    summary.write_text("{}\n", encoding="utf-8")
    row = {"summary": str(summary), "summary_sha256": module._digest(summary, "summary")}
    with pytest.raises(module.ExtractError, match="records_stat_only"):
        module._normalize_typed_edge({**row, "records_stat_only": str(summary)}, "case", "records_stat_only")
    with pytest.raises(module.ExtractError, match="path"):
        module._normalize_typed_edge({**row, "records_stat_only": {"sha256": "0" * 64, "bytes": 1, "rows": 1}}, "case", "records_stat_only")


@pytest.mark.skipif(not ROOT253_REQUEST.is_file(), reason="ROOT253 lifecycle request is not present")
def test_prepare_binds_eight_f4_cases_without_payload_open(tmp_path: Path) -> None:
    output_root = tmp_path / "native-extract"
    request_out = tmp_path / "root253-native-request.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--root253-request",
            str(ROOT253_REQUEST),
            "--output-root",
            str(output_root),
            "--request-output",
            str(request_out),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["case_ids"] and len(result["case_ids"]) == 8
    assert result["terminal_proof_bound"] is False
    assert result["launch_allowed"] is False
    request = json.loads(request_out.read_text(encoding="utf-8"))
    assert request["physical_case_ids"] == result["case_ids"]
    assert request["launch_allowed"] is False
    assert request["official_tool"]["sha256"] == "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
    assert all("PartOut_000.obi4" not in path for path in request["input_files"])
    assert all(record["deferred"] is True for record in request["deferred_input_records"])
