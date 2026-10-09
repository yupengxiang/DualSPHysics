from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/ds_data02_stage2_f3_s2_fine_native_motive_audit_v1.py"
spec = importlib.util.spec_from_file_location("f3_s2_fine_native_motive_v1", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)


def _runparts(tmp_path: Path, *, rows: str | None = None) -> Path:
    path = tmp_path / "RunPARTs.csv"
    path.write_text(
        rows
        or "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
        "0;0.0;0;0;0;0\n"
        "1;0.5;1;1;0;0\n"
        "2;1.0;1;1;0;0\n",
        encoding="utf-8",
    )
    return path


def _csv(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "PartOut.csv"
    path.write_text(
        text
        or "Idp,PartOut,Motive,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n"
        "42,1,1,1,2,3,1000\n",
        encoding="utf-8",
    )
    return path


def test_native_motive_is_joined_to_saved_bracket_and_event_time_stays_unknown(tmp_path: Path) -> None:
    runparts = MODULE.parse_runparts(_runparts(tmp_path))
    rows = MODULE.parse_native_csv(_csv(tmp_path), [{"begin": 0, "count": 100, "mkfluid": 1, "mk": 1}])
    MODULE.attach_saved_brackets(rows, runparts)
    assert rows[0]["saved_record_time_s"] == 0.5
    assert rows[0]["saved_record_bracket_s"] == [0.0, 0.5]
    assert rows[0]["continuous_event_time_s"] == "UNKNOWN"


def test_duplicate_id_is_rejected_instead_of_making_synthetic_lifecycle_rows(tmp_path: Path) -> None:
    path = _csv(
        tmp_path,
        "Idp,PartOut,Motive,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n"
        "42,1,1,1,2,3,1000\n"
        "42,2,1,1,2,3,1000\n",
    )
    with pytest.raises(MODULE.FineMotiveError, match="invalid Idp"):
        MODULE.parse_native_csv(path, [{"begin": 0, "count": 100, "mkfluid": 1, "mk": 1}])


def test_aggregate_counter_without_corresponding_saved_part_is_rejected(tmp_path: Path) -> None:
    runparts = MODULE.parse_runparts(_runparts(tmp_path, rows=(
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
        "0;0.0;0;0;0;0\n"
    )))
    rows = MODULE.parse_native_csv(_csv(tmp_path), [{"begin": 0, "count": 100, "mkfluid": 1, "mk": 1}])
    with pytest.raises(MODULE.FineMotiveError, match="absent from RunPARTs"):
        MODULE.attach_saved_brackets(rows, runparts)


def test_pending_manifest_cannot_be_used_as_terminal_audit(tmp_path: Path) -> None:
    manifest = tmp_path / "pending.json"
    manifest.write_text(
        '{"schema": "ds02.stage2.f3.s2.fine-native-motive.manifest.v1", '
        '"status": "WAITING_FOR_ROOT170_TERMINAL_BINDING"}',
        encoding="utf-8",
    )
    with pytest.raises(MODULE.FineMotiveError, match="still pending ROOT170 terminal"):
        MODULE._validate_final_manifest(manifest)


def test_source_payload_is_forbidden_during_prepare_ref_validation(tmp_path: Path) -> None:
    payload = tmp_path / "Part_0000.bi4"
    payload.write_bytes(b"fixture")
    with pytest.raises(MODULE.FineMotiveError, match="forbidden native payload"):
        MODULE.require_file(payload, "fixture payload")
