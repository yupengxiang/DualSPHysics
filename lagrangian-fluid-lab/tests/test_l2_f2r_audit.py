from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

import h5py
import numpy as np

from scripts.l2_f2r_audit import (
    AssetSpec,
    _capture_geometry_summary,
    _control_summary,
    _parse_definition,
    _trajectory_summary,
    audit_asset,
    build_report,
    main,
)


def _write_definition(path: Path, *, moving: bool = True, receiver: bool = True) -> Path:
    motion = """
    <motion><objreal ref="0"><mvrotfile id="1"><file name="motion.dat"/>
      <axisp1 x="0" y="-1" z="0"/><axisp2 x="0" y="1" z="0"/>
    </mvrotfile></objreal></motion>
    """ if moving else ""
    receiver_xml = """
      <setmkbound mk="1"/><drawbox><boxfill>bottom | left | right | front | back</boxfill>
        <point x="1" y="-0.3" z="0"/><size x="1" y="0.6" z="0.4"/></drawbox>
      <setmkbound mk="2"/><drawbox><boxfill>bottom</boxfill>
        <point x="-1" y="-1" z="-0.2"/><size x="3" y="2" z="0.1"/></drawbox>
    """ if receiver else ""
    path.write_text(
        f"""<case><casedef><geometry><definition dp="0.02"/><commands><mainlist>
      <setmkbound mk="0"/><drawbox><boxfill>bottom | left | right | front | back</boxfill>
        <point x="0" y="-0.2" z="0"/><size x="0.5" y="0.4" z="0.6"/></drawbox>
      {receiver_xml}
    </mainlist></commands></geometry>{motion}</casedef></case>"""
    )
    if moving:
        (path.parent / "motion.dat").write_text("#Time;Degrees\n0;0\n1;30\n")
    return path


def _write_h5(path: Path, *, with_transform: bool = True, inactive_nan: bool = True) -> Path:
    time = np.asarray([0.0, 0.5, 1.0])
    position = np.asarray(
        [
            [[0.10, 0.0, 0.20], [0.20, 0.0, 0.20]],
            [[0.11, 0.0, 0.20], [0.21, 0.0, 0.20]],
            [[0.12, 0.0, 0.20], [0.22, 0.0, 0.20]],
        ], dtype=np.float32,
    )
    velocity = np.zeros_like(position)
    mass = np.full((3, 2), 1.0, dtype=np.float32)
    valid = np.ones((3, 2), dtype=bool)
    particle_type = np.full((3, 2), 3, dtype=np.int8)
    if inactive_nan:
        # Add a padded inactive particle to exercise the active/inactive split.
        position = np.concatenate([position, np.full((3, 1, 3), np.nan, dtype=np.float32)], axis=1)
        velocity = np.concatenate([velocity, np.full((3, 1, 3), np.nan, dtype=np.float32)], axis=1)
        mass = np.concatenate([mass, np.full((3, 1), np.nan, dtype=np.float32)], axis=1)
        valid = np.concatenate([valid, np.zeros((3, 1), dtype=bool)], axis=1)
        particle_type = np.concatenate([particle_type, np.full((3, 1), 3, dtype=np.int8)], axis=1)
    with h5py.File(path, "w") as h5:
        for name, data in {
            "time": time, "position": position, "velocity": velocity,
            "mass": mass, "valid": valid, "type": particle_type,
        }.items():
            h5.create_dataset(name, data=data)
        control = h5.create_group("control")
        control.create_dataset("cup_angle_degrees", data=np.asarray([0.0, 15.0, 30.0]))
        if with_transform:
            transforms = np.repeat(np.eye(4)[None], 3, axis=0)
            angle = np.deg2rad([0.0, 15.0, 30.0])
            transforms[:, 0, 0] = np.cos(angle)
            transforms[:, 0, 2] = np.sin(angle)
            transforms[:, 2, 0] = -np.sin(angle)
            transforms[:, 2, 2] = np.cos(angle)
            control.create_dataset("cup_world_from_body", data=transforms)
    return path


def test_inactive_nan_padding_is_not_active_geometry_failure(tmp_path: Path):
    path = _write_h5(tmp_path / "padded.h5", inactive_nan=True)
    summary = _trajectory_summary(path)
    assert summary["status"] == "checked"
    assert summary["active_nonfinite"]["position"] == 0
    assert summary["inactive_nonfinite_padding"]["position"] > 0


def test_angle_only_moving_cup_is_unknown_not_inferred(tmp_path: Path):
    definition = _write_definition(tmp_path / "moving_Def.xml", moving=True)
    h5 = _write_h5(tmp_path / "angle-only.h5", with_transform=False)
    parsed = _parse_definition(definition)
    control = _control_summary(h5, parsed)
    assert control["motion_status"] == "checked"
    assert control["moving_geometry_status"] == "unknown"
    assert "world_from_body" in control["moving_geometry_reason"]


def test_finite_motion_and_capture_geometry_can_be_checked(tmp_path: Path):
    definition = _write_definition(tmp_path / "moving_Def.xml", moving=True)
    h5 = _write_h5(tmp_path / "moving.h5", with_transform=True)
    parsed = _parse_definition(definition)
    control = _control_summary(h5, parsed)
    capture = _capture_geometry_summary(parsed)
    assert parsed["geometry_status"] == "checked"
    assert control["moving_geometry_status"] == "checked"
    assert capture["status"] == "checked"
    assert capture["aabb_fallback_used"] is False


def test_missing_capture_geometry_is_blocked_without_aabb_fallback(tmp_path: Path):
    definition = _write_definition(tmp_path / "no_receiver_Def.xml", moving=True, receiver=False)
    parsed = _parse_definition(definition)
    capture = _capture_geometry_summary(parsed)
    assert capture["status"] in {"unknown", "blocked"}
    assert capture["aabb_fallback_used"] is False


def test_repository_report_blocks_static_and_external_reference_gates():
    report = build_report()
    assert report["no_solver_launched"] is True
    assert report["checks"]["static_cup"]["status"] == "blocked"
    assert report["checks"]["two_background_reference"]["status"] == "blocked"
    assert report["checks"]["two_background_reference"]["accepted_reference_count"] == 0
    assert report["decision"]["status"] == "blocked"
    assert all(not asset["eligible_as_new_f2r_evidence"] for asset in report["assets"])


def test_old_c1_angle_control_is_not_promoted_as_new_moving_geometry():
    report = build_report()
    c1 = next(asset for asset in report["assets"] if asset["asset_id"].startswith("L2_C1_F2"))
    assert c1["evidence_class"] == "legacy_canary"
    assert c1["eligible_as_new_f2r_evidence"] is False
    assert c1["motion"]["moving_geometry_status"] == "unknown"


def test_cli_writes_explicit_report_only_when_requested(tmp_path: Path, capsys):
    output = tmp_path / "f2r.json"
    assert main(["audit", "--output", str(output)]) == 0
    assert output.is_file()
    payload = json.loads(output.read_text())
    assert payload["schema"] == "l2r.f2r.audit.v1"
    assert payload["execution_plan"]["gpu_required_for_audit"] is False
    assert "GPU" in capsys.readouterr().out
