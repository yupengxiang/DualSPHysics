"""Metadata and manufactured tests for the ROOT245 native extractor.

The production test exercises only the immutable request, plan, 118-case
inventory, executable binding, and file statistics.  It never opens an
OBI4/BI4/H5/JSONL/PartOut/RunPARTs payload and never invokes ``audit``.
The remaining tests use tiny temporary JSON fixtures for the strict source
identity gates.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f6_root245_native_extract_v1.py"
SPEC = importlib.util.spec_from_file_location("f6_root245_native_extract_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)

INVENTORY = WORKER.INVENTORY_DEFAULT
PLAN = WORKER.PLAN_DEFAULT
ROOT245_REQUEST = Path("/tmp/ds02-root245-f6-prepared-20261010-b/typed-lifecycle-batch-v1-f6-root-forward-245-001.json")


def test_self_test_is_explicitly_nonlaunchable() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "self-test"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema"] == WORKER.MANIFEST_SCHEMA
    assert result["case_count"] == 7
    assert result["launch_allowed"] is False
    assert result["payload_opened"] is False


@pytest.mark.skipif(not ROOT245_REQUEST.is_file(), reason="ROOT245 source request is not present in this checkout")
def test_prepare_binds_actual_inventory_and_defers_all_native_payloads(tmp_path: Path) -> None:
    output_root = tmp_path / "root245-native-extract"
    request_output = tmp_path / "root245-native-extract-request.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--root245-request",
            str(ROOT245_REQUEST),
            "--inventory",
            str(INVENTORY),
            "--plan",
            str(PLAN),
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
    assert result["case_ids"] == list(WORKER.ROOT245_CASES)
    assert result["terminal_proof_bound"] is False
    assert result["launch_allowed"] is False
    assert result["payload_content_opened"] is False

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["case_count"] == 7
    assert manifest["launch_allowed"] is False
    assert manifest["read_policy"] == {
        "prepare_opened_bi4": False,
        "prepare_opened_h5": False,
        "prepare_opened_jsonl": False,
        "prepare_opened_obi4": False,
        "prepare_opened_partout_csv": False,
        "prepare_opened_runparts": False,
        "solver_started": False,
    }
    assert manifest["official_sources"]["partvtkout"]["sha256"] == WORKER.PARTVTKOUT_SHA

    first_contract = json.loads(Path(manifest["cases"][0]["path"]).read_text(encoding="utf-8"))
    native = first_contract["native_deferred"]
    assert native["partout_obi4"]["content_opened_by_preparer"] is False
    assert native["partout_obi4"]["sha256"] == "PARENT_GUARD_COMPUTED"
    assert native["runparts_csv"]["content_opened_by_preparer"] is False
    assert native["runparts_csv"]["sha256"] == "PARENT_GUARD_COMPUTED"
    assert first_contract["claim_boundary"]["physical_fate"] == "UNKNOWN"
    assert first_contract["claim_boundary"]["QI"] == "UNKNOWN"

    request = json.loads(request_output.read_text(encoding="utf-8"))
    assert len(request["physical_case_ids"]) == 7
    assert len(request["deferred_input_files"]) == 42
    contract_paths = [entry["path"] for entry in manifest["cases"]]
    assert set(contract_paths).issubset(set(request["input_files"]))
    assert all(path in request["input_sha256"] for path in contract_paths)
    assert request["launch_allowed"] is False
    assert request["execution_allowed"] is False


def test_inventory_schema_is_strict(tmp_path: Path) -> None:
    malformed = tmp_path / "inventory.json"
    malformed.write_text(json.dumps({"schema": "wrong", "rows": []}), encoding="utf-8")
    with pytest.raises(WORKER.ExtractError, match="inventory schema differs"):
        WORKER._load_inventory(malformed)


def test_missing_terminal_proof_never_becomes_launchable() -> None:
    assert WORKER._self_test()["launch_allowed"] is False
    assert WORKER._self_test()["payload_opened"] is False
