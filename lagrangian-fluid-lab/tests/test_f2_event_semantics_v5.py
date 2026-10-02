from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import h5py
import numpy as np


SCRIPT = Path(__file__).parents[1] / "campaigns/ds-data-02/families/F2/f2_handoff_20261002_event_semantics_v5.py"
SPEC = importlib.util.spec_from_file_location("f2_event_semantics_v5", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _owner(tmp_path: Path, xml: Path) -> Path:
    value = {
        "family_id": "F2",
        "case_id": "F2_TEST_TOP",
        "mechanism_id": "center_catch",
        "resolution": "test",
        "physical_condition_hash_declared": "p" * 64,
        "physical_binding_sha256": "b" * 64,
        "definition": {"path": str(xml), "sha256": "x" * 64},
        "geometry": {
            "cup_low_m": [0.0, 0.0, 0.0], "cup_size_m": [1.0, 1.0, 1.0],
            "receiver_low_m": [2.0, 0.0, 0.0], "receiver_size_m": [1.0, 1.0, 1.0],
            "tray_low_m": [0.0, 2.0, 0.0], "tray_size_m": [1.0, 1.0, 0.2],
        },
        "physical_binding": {"parameters": {
            "motion_axis_origin_m": [0.0, 0.0, 0.0],
            "motion_axis_unit": [0.0, 1.0, 0.0],
        }},
        "event_window": {"hold_start_s": 0.0},
        "quality_contract": {"event_thresholds": {"cup_mouth": {"crossing_tolerance_m": 0.01}}},
        "mass_reference": {"continuous_mass_kg": 0.001},
        "numerical_recipe_hash_declared": "n" * 64,
    }
    path = tmp_path / "owner.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_operator_hash_is_separate_from_physical_identity():
    spec = MODULE.operator_spec()
    assert spec["cup_opening"]["surface"].startswith("moving finite cup local-z")
    assert "physical_condition_hash" not in spec
    assert MODULE.operator_hash() == MODULE._canonical_sha256(spec)
    manifest = json.loads((SCRIPT.parent / "handoff_20261002/event_semantics_v5/operator_manifest.json").read_text())
    assert manifest["operator_sha256"] == MODULE.operator_hash()


def test_actual_pose_top_crossing_replaces_legacy_mouth(tmp_path):
    xml = tmp_path / "case.xml"
    xml.write_text('<case><massfluid value="0.001" units_comment="kg" /></case>', encoding="utf-8")
    owner = _owner(tmp_path, xml)
    trajectory = tmp_path / "trajectory.h5"
    rigid_dtype = np.dtype([("actual_angle_rad", "f8")])
    with h5py.File(trajectory, "w") as handle:
        handle.create_dataset("time", data=np.asarray([0.0, 1.0, 2.0]))
        handle.create_dataset("position", data=np.asarray([
            [[0.5, 0.5, 0.9]], [[0.5, 0.5, 1.1]], [[0.5, 0.5, 0.9]],
        ], dtype="f4"))
        handle.create_dataset("initial_mass", data=np.asarray([0.001], dtype="f4"))
        handle.create_dataset("initial_mk", data=np.asarray([0], dtype="i2"))
        handle.create_dataset("initial_type", data=np.asarray([3], dtype="i1"))
        handle.create_dataset("particle_zone", data=np.asarray([0], dtype="i2"))
        handle.create_dataset("particle_id", data=np.asarray([7], dtype="u4"))
        handle.create_dataset("valid", data=np.ones((3, 1), dtype=bool))
        handle.create_dataset("type", data=np.full((3, 1), 3, dtype="i1"))
        handle.create_dataset("rigid_body_state", data=np.asarray([(0.0,), (0.0,), (0.0,)], dtype=rigid_dtype))
    output = tmp_path / "v5.h5"
    report = tmp_path / "v5.json"
    result = MODULE.observe(trajectory=trajectory, owner_metadata=owner, output=output, report=report)
    assert result["event_ledger"]["counts_by_code"]["cup_top_departure"] == 1
    assert result["event_ledger"]["counts_by_code"]["cup_top_return"] == 1
    assert result["legacy_semantics_comparison"] is None
    assert result["source_population"]["mass_reference_status"] == "pass"
    with h5py.File(output, "r") as handle:
        assert handle.attrs["operator_sha256"] == MODULE.operator_hash()
        assert handle["destination_code"][-1, 0] == MODULE.DESTINATION_CODES["cup"]


def test_native_exclusion_reasons_keep_wall_and_tray_distinct(tmp_path):
    csv_path = tmp_path / "excluded.csv"
    csv_path.write_text(
        "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3],\n"
        "1,2,3,4,1,9,0,0,0,1000,\n", encoding="utf-8")
    records, binding = MODULE._parse_exclusion_csv(csv_path)
    assert records[9]["motive"] == 1
    assert records[9]["position_m"] == [1.0, 2.0, 3.0]
    assert binding["motive_counts"] == {"1": 1}
