"""Manufactured source/CLI tests for the ROOT245 native intake.

No production H5, JSONL, BI4/OBI4, PartOut, or RunPARTs file is opened here.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f6_root245_native_cause_intake_v1.py"
SPEC = importlib.util.spec_from_file_location("root245_native_intake", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


def _ref(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev, "st_ino": stat.st_ino, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture_contract(tmp_path: Path, *, empty_native: bool = False) -> Path:
    records = tmp_path / "records.jsonl"
    records.write_text(
        json.dumps({"record_fields": "one row per static (Zone, Idp); saved-frame lifecycle only"})
        + "\n"
        + json.dumps({"zone": 0, "idp": 42, "initial_role": "fluid", "first_disappeared_frame": 1, "first_disappeared_time_s": 0.5, "first_disappeared_bracket_s": [0.0, 1.0]})
        + "\n",
        encoding="utf-8",
    )
    partout = tmp_path / "PartOut.csv"
    if empty_native:
        partout.write_text("Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Rhop [kg/m^3]\n", encoding="utf-8")
    else:
        partout.write_text("Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Rhop [kg/m^3]\n0.1,0.2,0.3,0,1,42,998.0\n", encoding="utf-8")
    runparts = tmp_path / "RunPARTs.csv"
    values = {column: "0" for column in WORKER.RUNPARTS_COLUMNS}
    values.update({"Part": "0", "TimeStep [s]": "0.0", "NpSave": "1"})
    with runparts.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(WORKER.RUNPARTS_COLUMNS)
        writer.writerow([values[column] for column in WORKER.RUNPARTS_COLUMNS])
        values["TimeStep [s]"] = "1.0"
        writer.writerow([values[column] for column in WORKER.RUNPARTS_COLUMNS])
    contract = {
        "schema": WORKER.CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_NATIVE_AUDIT_NOT_LAUNCHED",
        "physical_case_id": WORKER.EXPECTED_CASES[0],
        "family_id": "F6",
        "deferred_inputs": {"typed_records": _ref(records), "partout_csv": _ref(partout), "runparts_csv": _ref(runparts)},
    }
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path


def test_self_test_is_explicitly_nonlaunchable() -> None:
    completed = subprocess.run([sys.executable, str(SCRIPT), "self-test", "--json"], check=False, capture_output=True, text=True)
    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["case_count"] == 7
    assert result["launch_allowed"] is False
    assert result["payload_opened"] is False


def test_manufactured_cli_joins_identity_motive_and_saved_bracket(tmp_path: Path) -> None:
    contract = _fixture_contract(tmp_path)
    output = tmp_path / "report.json"
    completed = subprocess.run([sys.executable, str(SCRIPT), "audit", "--contract", str(contract), "--output", str(output)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "COMPLETED_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY"
    assert result["counts"] == {"typed_targets": 1, "native_rows": 1, "joined": 1}
    row = result["rows"][0]
    assert row["identity_key"] == [0, 42]
    assert row["native_exit_cause"] == "NUMERICAL_POSITION_EXCLUSION"
    assert row["physical_fate"] == "UNKNOWN"


def test_empty_native_target_is_rejected(tmp_path: Path) -> None:
    contract = _fixture_contract(tmp_path, empty_native=True)
    completed = subprocess.run([sys.executable, str(SCRIPT), "audit", "--contract", str(contract), "--output", str(tmp_path / "report.json")], check=False, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "target identity set differs" in completed.stdout


def test_wrong_case_contract_is_rejected_without_payload_read(tmp_path: Path) -> None:
    contract = json.loads(_fixture_contract(tmp_path).read_text(encoding="utf-8"))
    contract["physical_case_id"] = "F4_WRONG_CASE"
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(SCRIPT), "audit", "--contract", str(path), "--output", str(tmp_path / "wrong-report.json")], check=False, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "case/family differs" in completed.stdout


def test_typed_header_must_be_exact(tmp_path: Path) -> None:
    contract = _fixture_contract(tmp_path)
    records = tmp_path / "records.jsonl"
    records.write_text(json.dumps({"record_fields": "not the producer contract"}) + "\n", encoding="utf-8")
    contract_value = json.loads(contract.read_text(encoding="utf-8"))
    contract_value["deferred_inputs"]["typed_records"] = _ref(records)
    contract.write_text(json.dumps(contract_value), encoding="utf-8")
    completed = subprocess.run([sys.executable, str(SCRIPT), "audit", "--contract", str(contract), "--output", str(tmp_path / "bad-header.json")], check=False, capture_output=True, text=True)
    assert completed.returncode != 0
    assert "record_fields header differs" in completed.stdout
