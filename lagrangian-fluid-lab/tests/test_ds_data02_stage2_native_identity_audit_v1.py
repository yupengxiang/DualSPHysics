from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_native_identity_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("stage2_native_identity_audit_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_typed_block_assignment_preserves_mk_and_type() -> None:
    blocks, mass_fluid, mass_bound = MODULE._typed_blocks(
        {
            "typed_identity": {"blocks": [
                {"begin": 0, "count": 4, "mk": 17, "tag": "fixed", "type": 0},
                {"begin": 4, "count": 3, "mk": 1, "mkfluid": 0, "tag": "fluid", "type": 3},
            ]},
            "hash_scopes": {"numerical_parameters": {"decoder_header_constants": {
                "MassFluid": 0.125, "MassBound": 0.25,
            }}},
        },
        "fixture",
    )
    assert MODULE._find_block(blocks, 4, "fixture")["mk"] == 1
    assert MODULE._find_block(blocks, 6, "fixture")["type"] == 3
    assert mass_fluid == pytest.approx(0.125)
    assert mass_bound == pytest.approx(0.25)


def test_typed_block_overlap_is_rejected() -> None:
    with pytest.raises(MODULE.IdentityAuditError, match="ranges overlap"):
        MODULE._typed_blocks(
            {
                "typed_identity": {"blocks": [
                    {"begin": 0, "count": 4, "mk": 1, "type": 3},
                    {"begin": 3, "count": 2, "mk": 2, "type": 3},
                ]},
                "hash_scopes": {"numerical_parameters": {"decoder_header_constants": {
                    "MassFluid": 1.0, "MassBound": 1.0,
                }}},
            },
            "fixture",
        )


def test_partout_and_runparts_keep_native_motive_identity(tmp_path: Path) -> None:
    partout = tmp_path / "PartOut.csv"
    partout.write_text(
        "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3]\n"
        "1,2,3,7,1,4,0,0,0,1000\n",
        encoding="utf-8",
    )
    rows = MODULE.read_partout(partout, "fixture PartOut")
    assert rows[0]["idp"] == 4
    assert rows[0]["motive"] == "position"

    runparts = tmp_path / "RunPARTs.csv"
    runparts.write_text(
        "Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n"
        "0;0;0;0;0;0\n"
        "1;0.1;1;1;0;0\n",
        encoding="utf-8",
    )
    result = MODULE.read_runparts(runparts, "fixture RunPARTs")
    assert result["totals"] == {"NpOut": 1, "NpOutPos": 1, "NpOutRho": 0, "NpOutMov": 0}


def test_trajectory_and_part_frame_inputs_are_rejected(tmp_path: Path) -> None:
    trajectory = tmp_path / "trajectory.h5"
    trajectory.write_bytes(b"fixture")
    with pytest.raises(MODULE.IdentityAuditError, match="trajectory content"):
        MODULE.require_file(trajectory, "trajectory")
    part = tmp_path / "Part_0000.bi4"
    part.write_bytes(b"fixture")
    with pytest.raises(MODULE.IdentityAuditError, match="trajectory content"):
        MODULE.require_file(part, "part frame")


def test_receipt_hash_must_be_stable_at_launch_and_end(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")
    digest = MODULE.sha256(source)
    receipt = {
        "request": {"input_sha256": {str(source): digest}},
        "input_hashes_at_launch": {str(source): digest},
        "input_hashes_after_run": {str(source): "0" * 64},
    }
    with pytest.raises(MODULE.IdentityAuditError, match="launch/end input hash"):
        MODULE.receipt_input(receipt, source, "fixture")
