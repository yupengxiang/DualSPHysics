"""Focused tests for the guarded ROOT238 F4 native-evidence worker."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f4_unlocated_native_evidence_v1.py"
SPEC = importlib.util.spec_from_file_location("f4_unlocated_native_evidence_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


def _runparts_header() -> list[str]:
    return list(WORKER.RUNPARTS_COLUMNS)


def _runparts_row(*, bad_integer_count: bool = False) -> list[str]:
    values = {column: "0" for column in _runparts_header()}
    values.update(
        {
            "Part": "0",
            "TimeStep [s]": "0.0",
            "Steps": "0",
            "NpSave": "1",
            "NpSim": "1",
            "NpOut": "1",
            "NpAlloc [X]": "1.000307",
            "NctAlloc [X]": "2.000000",
            "NpOutPos": "1",
            "NpAlloc": "1.000307" if bad_integer_count else "1,234",
            "NctAlloc": "0",
        }
    )
    return [values[column] for column in _runparts_header()]


def _write_fixture(tmp_path: Path, *, duplicate_partout: bool = False, bad_integer_count: bool = False) -> Path:
    partout = tmp_path / "PartOut.csv"
    partout.write_text(
        "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Rhop [kg/m^3]\n"
        "0.1,0.2,0.3,0,1,42,998.0\n"
        + ("0.1,0.2,0.3,0,1,42,998.0\n" if duplicate_partout else ""),
        encoding="utf-8",
    )
    runparts = tmp_path / "RunPARTs.csv"
    with runparts.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\n")
        writer.writerow(_runparts_header())
        writer.writerow(_runparts_row(bad_integer_count=bad_integer_count))
        stream.write("# parser fixture footer\n")
    manifest = tmp_path / "fixture.json"
    manifest.write_text(json.dumps({"fixture": True, "partout": str(partout), "runparts": str(runparts)}), encoding="utf-8")
    return manifest


def test_root232_exact_intersection_and_root235_reuse_are_explicit() -> None:
    current, rows, selected, excluded, root235 = WORKER._validate_metadata(
        WORKER.CURRENT_DEFAULT,
        WORKER.INVENTORY_DEFAULT,
        WORKER.OVERLAY_DEFAULT,
        WORKER.HISTORICAL_DEFAULT,
        WORKER.ROOT232_MANIFEST_DEFAULT,
        WORKER.ROOT235_DEFAULT_PROOF,
    )
    assert current["schema"] == WORKER.CURRENT_SCHEMA
    assert len(rows) == 118
    assert len(selected) == 5
    assert len(excluded) == 3
    assert len(root235) == 3
    root232 = set(WORKER._root232_ids(WORKER._read_json(WORKER.ROOT232_MANIFEST_DEFAULT, "ROOT232")))
    assert set(selected).issubset(root232)
    assert set(selected).isdisjoint(root235)


def test_runparts_accepts_float_allocation_ratios_and_thousands_counts(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    runparts = Path(json.loads(manifest.read_text())["runparts"])
    result = WORKER._runparts(runparts, {"timeline": {"time_s": [0.0]}})
    assert result["rows"] == 1
    assert result["totals"]["NpOut"] == 1


def test_runparts_rejects_ratio_in_integer_count_column(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path, bad_integer_count=True)
    runparts = Path(json.loads(manifest.read_text())["runparts"])
    with pytest.raises(WORKER.EvidenceError, match="not numeric"):
        WORKER._runparts(runparts, {"timeline": {"time_s": [0.0]}})


def test_partout_rejects_duplicate_identity(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path, duplicate_partout=True)
    partout = Path(json.loads(manifest.read_text())["partout"])
    with pytest.raises(WORKER.EvidenceError, match="duplicate identity"):
        WORKER._partout_csv(partout)


def test_real_fixture_cli_has_no_scientific_credit(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "fixture", "--manifest", str(manifest)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "FIXTURE_PARSER_PASS_NO_SCIENTIFIC_CREDIT"
    assert result["scientific_credit"] is False


def test_real_fixture_cli_rejects_bad_integer_count(tmp_path: Path) -> None:
    manifest = _write_fixture(tmp_path, bad_integer_count=True)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "fixture", "--manifest", str(manifest)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "not numeric" in completed.stdout
