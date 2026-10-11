from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pytest


M4_ROOT = Path(__file__).resolve().parent
if str(M4_ROOT) not in sys.path:
    sys.path.insert(0, str(M4_ROOT))

import m4_direct_enrich as producer  # noqa: E402
import m4_portable_adapter as m4  # noqa: E402


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _xml() -> str:
    return """<?xml version="1.0"?>
<case><casedef><geometry><definition dp="0.01" />
<commands><mainlist><fillbox><point x="1.992" y="0" z="0" />
<size x="1.4" y="1" z="0.50" /></fillbox></mainlist></commands></geometry></casedef>
<execution><parameters><parameter key="TimeMax" value="6" />
<parameter key="TimeOut" value="0.025" /></parameters>
<particles np="5"><fixed begin="0" count="2" mk="10" /><fluid begin="2" count="3" mk="1" /></particles>
<constants><data2d value="false" /><dp value="0.01" /><gravity x="0" y="0" z="-9.81" /></constants>
<uservars><varnum name="DefTankpx" value="0" /><varnum name="DefTankpy" value="0" />
<varnum name="DefTankpz" value="0" /><varnum name="DefTanksx" value="3.22" />
<varnum name="DefTanksy" value="1" /><varnum name="DefTanksz" value="1" />
<varnum name="Boxpx1" value="0.66" /><varnum name="Boxpx2" value="0.82" />
<varnum name="Boxpy1" value="0.30" /><varnum name="DefBoxsx" value="0.16" />
<varnum name="DefBoxsy" value="0.40" /><varnum name="DefBoxsz" value="0.16" /></uservars>
</execution></case>"""


def _mother_owner() -> dict[str, object]:
    geometry = {
        "tank": {"low_m": [0.0, 0.0, 0.0], "size_m": [3.22, 1.0, 1.0]},
        "central_obstacle": {"low_m": [0.66, 0.30, 0.0], "size_m": [0.16, 0.40, 0.16]},
        "initial_fluid_reservoir": {"low_m": [2.10, 0.0, 0.0], "size_m": [1.12, 1.0, 0.55]},
    }
    event = {"time_start_s": 0.0, "time_end_s": 6.0, "right_censor_policy": "UNKNOWN"}
    parameters = {
        "tank_length_m": 3.22,
        "tank_width_m": 1.0,
        "tank_height_m": 1.0,
        "separator_start_x_m": 1.25,
        "separator_end_x_m": 2.05,
        "separator_y_m": 0.30,
        "separator_thickness_m": 0.16,
        "separator_height_m": 0.16,
        "initial_depth_m": 0.55,
        "initial_fluid_volume_m3": 0.616,
    }
    binding = {
        "schema": "ds-data-02.physical-binding.v1",
        "family_id": "F1",
        "physical_case_id": "F1_MDBC_DAMBREAK3D",
        "mechanism_id": "dam_break_over_central_obstacle",
        "geometry_family_id": "synthetic-mother-geometry",
        "control_family_id": "synthetic-mother-controls",
        "lineage_group_id": "synthetic-lineage",
        "geometry": copy.deepcopy(geometry),
        "parameters": copy.deepcopy(parameters),
        "initial_state": {
            "continuum_mass_by_source_kg": {"initial_fluid_reservoir": 616.0},
            "initial_mass_total_kg": 616.0,
        },
        "event_window": copy.deepcopy(event),
        "controls": {"boundary": "mDBC"},
        "gravity_m_s2": [0.0, 0.0, -9.81],
        "density_kg_m3": 1000.0,
    }
    return {
        "schema": "ds-data-02.m4.official-mdbc-owner-metadata.v1",
        "family_id": "F1",
        "case_id": "UF_F1_MDBC_DAMBREAK3D",
        "physical_case_id": "F1_MDBC_DAMBREAK3D",
        "geometry_family_id": "synthetic-mother-geometry",
        "control_family_id": "synthetic-mother-controls",
        "geometry": geometry,
        "parameter_values": parameters,
        "event_window": event,
        "solver_parameters": {"TimeMax": 6.0, "TimeOut": 0.01},
        "physical_binding": binding,
    }


def _make_inputs(root: Path) -> dict[str, Path]:
    root.mkdir()
    xml_path = root / "child.xml"
    xml_path.write_text(_xml(), encoding="utf-8")
    definition_path = root / "child-def.xml"
    definition_path.write_text(_xml(), encoding="utf-8")
    owner_path = root / "mother-owner.json"
    _write_json(owner_path, _mother_owner())
    semantic_path = root / "semantic-diff.json"
    _write_json(
        semantic_path,
        {
            "schema": producer.SEMANTIC_DIFF_SCHEMA,
            "status": "verified_prepared_definitions_no_launch",
            "fixed_controls_excluding_output_schedule_sha256": "a" * 64,
            "comparisons": [
                {
                    "case_id": "UF_F1_MDBC_DP010_H050",
                    "candidate_sha256": producer._sha256(definition_path),
                    "allowed_physical_changes": [{"path": "fillbox/size/@z", "after": "0.50"}],
                }
            ],
        },
    )
    manifest_path = root / "case-manifest.json"
    _write_json(
        manifest_path,
        {
            "schema": producer.CHILD_MANIFEST_SCHEMA,
            "status": "prepared_not_submitted",
            "case_id": "UF_F1_MDBC_DP010_H050",
            "family_id": "F1",
            "definition": {
                "path": str(definition_path),
                "sha256": producer._sha256(definition_path),
                "geometry": {"fillbox_size_z_m": "0.50"},
            },
            "physical_axis": {
                "name": "initial_fill_height_m",
                "mother_value_m": 0.55,
                "candidate_value_m": 0.5,
                "path": "fillbox/size/@z",
                "allowed_change": {"before": "0.55", "after": "0.50"},
            },
        },
    )
    owner_child_path = root / "prepared-child-owner.json"
    producer.prepare_child_owner(
        owner_metadata=owner_path,
        generated_xml=xml_path,
        case_manifest=manifest_path,
        semantic_diff=semantic_path,
        output=owner_child_path,
    )

    ids = np.array([10, 11, 12, 13, 14], dtype="<u4")
    zones = np.zeros(5, dtype="<i2")
    valid = np.array(
        [[True, True, True, True, True], [True, True, True, False, True], [True, True, True, True, False]],
        dtype=bool,
    )
    position = np.zeros((3, 5, 3), dtype="f4")
    for frame in range(3):
        position[frame, :, 0] = np.arange(5, dtype="f4") + frame * 0.1
    position[1, 3] = np.nan
    position[2, 4] = np.nan
    velocity = np.zeros((3, 5, 3), dtype="f4")
    density = np.full((3, 5), 1000.0, dtype="f4")
    mass = np.ones((3, 5), dtype="f4")
    pressure = np.zeros((3, 5), dtype="f4")
    particle_type = np.full((3, 5), 3, dtype="i1")
    mk = np.ones((3, 5), dtype="i2")
    for array in (velocity, density, mass, pressure):
        array[1, 3] = np.nan
        array[2, 4] = np.nan
    trajectory = root / "direct.h5"
    with h5py.File(trajectory, "w") as handle:
        handle.attrs.update(
            {
                "schema": "ds-data-02.hdf5-schema.v1",
                "conversion_complete": True,
                "identity_key": "(Zone,Idp)",
                "solver_dimension": 3,
                "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
                "units_json": json.dumps({"time": "s", "position": "m", "velocity": "m/s", "density": "kg/m^3", "mass": "kg", "pressure": "Pa"}, sort_keys=True),
            }
        )
        handle.create_dataset("time", data=np.array([0.0, 0.1, 0.2], dtype="f8"))
        handle.create_dataset("particle_id", data=ids)
        handle.create_dataset("particle_zone", data=zones)
        handle.create_dataset("valid", data=valid)
        for name, data in {
            "position": position,
            "velocity": velocity,
            "density": density,
            "mass": mass,
            "pressure": pressure,
            "type": particle_type,
            "mk": mk,
        }.items():
            handle.create_dataset(name, data=data)
        handle.create_dataset("initial_type", data=np.full(5, 3, dtype="i1"))
        handle.create_dataset("initial_mk", data=np.ones(5, dtype="i2"))
        handle.create_dataset("initial_mass", data=np.ones(5, dtype="f4"))
    source_hash = producer._sha256(trajectory)
    ids_hash = m4._sha256_array(ids, dtype="<u4")
    excluded_ids = np.array([14], dtype="<u4")
    excluded_hash = m4._sha256_array(excluded_ids, dtype="<u4")
    xml_evidence = producer._xml_evidence(xml_path)
    child_owner = json.loads(owner_child_path.read_text(encoding="utf-8"))
    report_path = root / "direct-report.json"
    _write_json(
        report_path,
        {
            "schema": producer.DIRECT_REPORT_SCHEMA,
            "conversion_status": "completed",
            "output_sha256": source_hash,
            "frames": 3,
            "particles": 5,
            "solver_dimension": {"solver_dimension": 3},
            "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
            "typed_identity": {"key": "(Zone,Idp)"},
            "time_evidence": {"first_s": 0.0, "last_s": 0.2, "strictly_increasing": True},
            "source_provenance": {
                "generated_xml": {"sha256": xml_evidence["sha256"]},
                "geometry_sha256": xml_evidence["geometry_sha256"],
                "control_sha256": xml_evidence["control_sha256"],
                "owner_metadata": {"sha256": producer._sha256(owner_child_path)},
            },
            "hash_scopes": {"physical_condition_sha256": producer._canonical_hash(child_owner["physical_binding"])},
        },
    )
    integrity_path = root / "native-integrity.json"
    _write_json(
        integrity_path,
        {
            "schema": producer.NATIVE_INTEGRITY_SCHEMA,
            "status": "verified",
            "case_id": "UF_F1_MDBC_DP010_H050",
            "family_id": "F1",
            "count_continuity": {"initial_particles": 5, "excluded_particles": 1},
            "decoded_identity": {"key": "Idp", "id_unique": True},
            "native_rows": [{"idp": 14, "motive": "position", "part_out_time_s": 0.2}],
            "excluded_particle_records": {"record_count": 1, "raw_native_fields_retained": True},
        },
    )
    scan_path = root / "frame-scan.json"
    _write_json(
        scan_path,
        {
            "schema": producer.FRAME_SCAN_SCHEMA,
            "status": "verified",
            "case_id": "UF_F1_MDBC_DP010_H050",
            "family_id": "F1",
            "coverage": {"frame_count": 3, "raw_frames_opened_one_at_a_time": True},
            "fatal_findings": [],
            "finite_field_audit": {"all_frames_checked": True},
            "identity_axis": {
                "initial_count": 5,
                "initial_ids_sha256": ids_hash,
                "final_missing_count": 1,
                "final_missing_ids_sha256": excluded_hash,
                "physical_fate_inferred": False,
            },
            "native_exclusions": {
                "final_missing_count": 1,
                "record_count": 1,
                "excluded_particles_runout": 1,
                "id_set_sha256": excluded_hash,
                "raw_native_fields_retained": True,
            },
        },
    )
    return {
        "trajectory": trajectory,
        "report": report_path,
        "generated_xml": xml_path,
        "owner": owner_path,
        "owner_child": owner_child_path,
        "definition": definition_path,
        "integrity": integrity_path,
        "scan": scan_path,
        "manifest": manifest_path,
        "semantic": semantic_path,
    }


def test_enriches_standard_direct_hdf5_and_keeps_source_immutable(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    source_hash = producer._sha256(inputs["trajectory"])
    output_dir = tmp_path / "enriched"
    receipt = producer.enrich_direct(
        trajectory=inputs["trajectory"],
        report=inputs["report"],
        generated_xml=inputs["generated_xml"],
        owner_metadata=inputs["owner_child"],
        native_integrity=inputs["integrity"],
        frame_scan=inputs["scan"],
        output_dir=output_dir,
        case_manifest=inputs["manifest"],
        semantic_diff=inputs["semantic"],
    )
    assert receipt["status"] == "completed"
    assert producer._sha256(inputs["trajectory"]) == source_hash
    interface = output_dir / "interface.json"
    checked = m4.validate_interface(interface)
    assert checked["summary"]["native_exclusion_count"] == 1
    assert checked["summary"]["missing_destination_count"] == 1
    owner = json.loads((output_dir / "owner-metadata.json").read_text(encoding="utf-8"))
    assert owner["physical_condition_id"].endswith("0.500000")
    assert owner["source_mother"]["case_id"] == "UF_F1_MDBC_DAMBREAK3D"
    assert owner["parameter_values"]["separator_start_x_m"] == 0.66
    assert owner["parameter_values"]["separator_end_x_m"] == 0.82
    assert owner["geometry"]["central_obstacle"]["low_m"] == [0.66, 0.3, 0.0]
    bundle = tmp_path / "bundle"
    packaged = m4.build_bundle(interface, bundle)
    assert packaged["summary"]["native_exclusion_count"] == 1


def test_child_owner_preparation_is_runnable_before_conversion(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    prepared = tmp_path / "child-owner.json"
    receipt = producer.prepare_child_owner(
        owner_metadata=inputs["owner"],
        generated_xml=inputs["generated_xml"],
        case_manifest=inputs["manifest"],
        semantic_diff=inputs["semantic"],
        output=prepared,
    )
    assert receipt["status"] == "prepared"
    value = json.loads(prepared.read_text(encoding="utf-8"))
    assert value["case_id"] == "UF_F1_MDBC_DP010_H050"
    assert value["physical_binding"]["parameters"]["initial_depth_m"] == 0.5
    assert value["physical_binding"]["parameters"]["separator_start_x_m"] == 0.66
    assert value["physical_condition_id"].endswith("0.500000")


def test_native_scan_mismatch_rejects_without_creating_output(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    scan = json.loads(inputs["scan"].read_text(encoding="utf-8"))
    scan["native_exclusions"]["id_set_sha256"] = "f" * 64
    _write_json(inputs["scan"], scan)
    output_dir = tmp_path / "rejected"
    with pytest.raises(m4.M4Error, match="Idp hash"):
        producer.enrich_direct(
            trajectory=inputs["trajectory"],
            report=inputs["report"],
            generated_xml=inputs["generated_xml"],
            owner_metadata=inputs["owner"],
            native_integrity=inputs["integrity"],
            frame_scan=inputs["scan"],
            output_dir=output_dir,
            case_manifest=inputs["manifest"],
            semantic_diff=inputs["semantic"],
        )
    assert not output_dir.exists()


def test_child_owner_rejects_definition_bytes_outside_manifest_hash(tmp_path: Path) -> None:
    inputs = _make_inputs(tmp_path / "inputs")
    inputs["definition"].write_text(_xml().replace('z="0.50"', 'z="0.51"'), encoding="utf-8")
    with pytest.raises(m4.M4Error, match="definition bytes"):
        producer.prepare_child_owner(
            owner_metadata=inputs["owner"],
            generated_xml=inputs["generated_xml"],
            case_manifest=inputs["manifest"],
            semantic_diff=inputs["semantic"],
            output=tmp_path / "rejected-owner.json",
        )


def test_child_request_templates_bind_real_inputs_and_expected_241_frames() -> None:
    request_root = M4_ROOT / "requests"
    for suffix, depth, bytes_upper in (("H050", 0.5, 17_179_869_184), ("H060", 0.6, 19_327_352_832)):
        path = request_root / f"UF_F1_MDBC_DP010_{suffix}-enrichment.template.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["status"] == "prepared_not_run"
        assert value["physical_axis"]["value_m"] == depth
        assert value["storage_reservation"]["new_bytes_upper_bound"] == bytes_upper
        assert value["launch_authorization"].startswith("root-controlled")
        assert value["prepare_owner_command"][2] == "prepare-owner"
        assert value["enrichment_command"][2] == "enrich"
        assert "native-frame-scan-001/frame-identity-scan.json" in value["inputs"]["native_frame_scan"]
        assert any("241-frame" in gate for gate in value["required_gates"])
