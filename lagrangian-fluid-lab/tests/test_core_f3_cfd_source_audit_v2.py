import json
from pathlib import Path

import h5py
import numpy as np

from scripts.core_f3_cfd_source_audit_v2 import (
    F3_CLOSED_FACES,
    F3_OPEN_FACES,
    audit_file,
    audit_hdf5,
    digest,
    wall_spec_from_prepared,
)


def _wall_spec():
    return {
        "container_interior": {
            "xmin": -.45, "xmax": .45, "ymin": -.09, "ymax": .09,
            "zmin": 0.0, "zmax": .51,
        },
        "closed_faces": list(F3_CLOSED_FACES),
        "open_faces": list(F3_OPEN_FACES),
        "geometry_binding_pass": True,
        "geometry_source": "test_registered_f3_geometry",
    }


def _prepared(tmp_path, *, frames=5, interval=.002, particles=7):
    prefix = tmp_path / "F3_CELL3_plain"
    xml = prefix.with_suffix(".xml")
    xml.write_text(
        """<case><casedef><geometry><commands><list name="GeometryForNormals">
        <drawbox><boxfill>all^top</boxfill>
        <point x="-0.45" y="-0.09" z="0" />
        <size x="0.9" y="0.18" z="0.51" /></drawbox>
        </list></commands></geometry></casedef></case>""",
        encoding="utf-8",
    )
    prepared = {
        "schema": "core.f3.cfd.native_volume_mls.source.v1",
        "case": {
            "case_id": "TEST_F3",
            "source_asset_id": "test_source",
            "expected_native_frames": frames,
            "fluid_particles": particles,
            "output_interval_s": interval,
            "time_max_s": (frames - 1) * interval,
        },
        "config": {
            "case_id": "TEST_F3",
            "expected_native_frames": frames,
            "output_interval_s": interval,
            "time_max_s": (frames - 1) * interval,
        },
        "generated_prefix": str(prefix),
        "inputs": {str(xml.resolve()): digest(xml)},
    }
    return prepared, xml


def _write_h5(path, *, frames=5, interval=.002, particles=7, wall_bad=False, mass_bad=False,
              cadence_bad=False):
    times = np.arange(frames, dtype=np.float64) * interval
    if cadence_bad:
        times[0] = interval / 2
    position = np.zeros((frames, particles, 3), dtype=np.float64)
    position[..., 0] = np.linspace(-.4, .4, particles)[None, :]
    position[..., 1] = np.linspace(-.08, .08, particles)[None, :]
    position[..., 2] = .04
    position[:, -1, 2] = .60  # above the finite rim is the declared open top
    if wall_bad:
        position[2, 0, 0] = .46
        position[2, 0, 2] = .25
    velocity = np.zeros_like(position)
    density = np.full((frames, particles), 1000.0, dtype=np.float32)
    pressure = np.zeros((frames, particles), dtype=np.float32)
    mass = np.full((frames, particles), 1.0e-6, dtype=np.float32)
    if mass_bad:
        mass[3, 2] *= 1.1
    valid = np.ones((frames, particles), dtype=bool)
    with h5py.File(path, "w") as h:
        h.attrs["conversion_complete"] = True
        h.create_dataset("particle_id", data=np.arange(particles, dtype=np.uint32))
        h.create_dataset("particle_zone", data=np.zeros(particles, dtype=np.int16))
        h.create_dataset("source_label_initial_mk", data=np.zeros(particles, dtype=np.int16))
        h.create_dataset("time", data=times)
        h.create_dataset("position", data=position, chunks=(1, particles, 3))
        h.create_dataset("velocity", data=velocity, chunks=(1, particles, 3))
        h.create_dataset("density", data=density, chunks=(1, particles))
        h.create_dataset("mass", data=mass, chunks=(1, particles))
        h.create_dataset("pressure", data=pressure, chunks=(1, particles))
        h.create_dataset("valid", data=valid, chunks=(1, particles))
        h.create_dataset("type", data=np.full((frames, particles), 3, dtype=np.int16), chunks=(1, particles))
        h.create_dataset("mk", data=np.zeros((frames, particles), dtype=np.int16), chunks=(1, particles))


def test_streaming_audit_checks_cadence_open_top_and_per_particle_mass(tmp_path):
    prepared, xml = _prepared(tmp_path)
    h5 = tmp_path / "trajectory.h5"
    _write_h5(h5)
    report = audit_hdf5(prepared, h5, prepared_path=tmp_path / "prepared.json")
    assert report["hard_integrity_pass"]
    assert report["time"]["cadence_pass"]
    assert report["wall"]["endpoint_pass"]
    assert report["wall"]["chord_pass"]
    assert report["wall"]["open_top_observed_particle_frames"] == 5
    assert report["mass_per_particle"]["constant_pass"]
    assert report["streaming"]["frame_by_frame"]
    assert not report["streaming"]["trajectory_whole_slice_reads"]
    assert report["wall_geometry"]["geometry_binding_pass"]
    assert report["wall_geometry"]["geometry_source_path"] == str(xml.resolve())


def test_streaming_audit_reports_wall_and_mass_failures_without_overwriting_h5(tmp_path):
    prepared, _ = _prepared(tmp_path)
    h5 = tmp_path / "trajectory.h5"
    _write_h5(h5, wall_bad=True, mass_bad=True)
    before = h5.read_bytes()
    report = audit_hdf5(prepared, h5, wall_spec=_wall_spec())
    assert not report["hard_integrity_pass"]
    assert "mass:per_particle_not_constant" in report["errors"]
    assert "wall:finite_geometry_or_crossing" in report["errors"]
    assert report["mass_per_particle"]["changed_particle_count"] == 1
    assert report["wall"]["endpoint_violation_count_by_face"]["right"] == 1
    assert h5.read_bytes() == before


def test_streaming_audit_rejects_first_frame_or_cadence_mismatch(tmp_path):
    prepared, _ = _prepared(tmp_path)
    h5 = tmp_path / "trajectory.h5"
    _write_h5(h5, cadence_bad=True)
    report = audit_hdf5(prepared, h5, wall_spec=_wall_spec())
    assert not report["hard_integrity_pass"]
    assert "time:saved_cadence_or_window" in report["errors"]
    assert not report["time"]["first_pass"]
    assert report["time"]["cadence_bad_indices_first64"] == [0]


def test_audit_file_writes_independent_immutable_report(tmp_path):
    prepared, _ = _prepared(tmp_path)
    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
    h5 = tmp_path / "trajectory.h5"
    _write_h5(h5)
    output = tmp_path / "re_audit" / "source-audit-v2.json"
    report = audit_file(prepared_path, h5, output)
    assert output.is_file()
    assert report["read_only"]
    assert report["central_ledger_mutation"] == 0
    assert report["gpu_started"] is False
    with np.testing.assert_raises(FileExistsError):
        audit_file(prepared_path, h5, output)


def test_missing_geometry_xml_is_diagnostic_only_and_fails_closed(tmp_path):
    prepared, _ = _prepared(tmp_path)
    h5 = tmp_path / "trajectory.h5"
    _write_h5(h5)
    xml = Path(prepared["generated_prefix"] + ".xml")
    xml.unlink()
    wall = wall_spec_from_prepared(prepared, prepared_path=tmp_path / "prepared.json")
    assert wall["geometry_binding_pass"] is False
    assert "no prepared.inputs-bound" in wall["geometry_binding_error"]
    report = audit_hdf5(prepared, h5, prepared_path=tmp_path / "prepared.json")
    assert not report["hard_integrity_pass"]
    assert "wall:finite_geometry_or_crossing" in report["errors"]


def test_unrecognized_or_bad_geometry_xml_fails_closed(tmp_path):
    prepared, xml = _prepared(tmp_path)
    h5 = tmp_path / "trajectory.h5"
    _write_h5(h5)
    xml.write_text(
        "<case><casedef><geometry><commands><list name=\"GeometryForNormals\">"
        "<drawbox><boxfill>solid</boxfill><point x=\"-0.45\" y=\"-0.09\" z=\"0\"/>"
        "<size x=\"0.9\" y=\"0.18\" z=\"0.51\"/></drawbox>"
        "</list></commands></geometry></casedef></case>",
        encoding="utf-8",
    )
    prepared["inputs"][str(xml.resolve())] = digest(xml)
    wall = wall_spec_from_prepared(prepared, prepared_path=tmp_path / "prepared.json")
    assert wall["geometry_binding_pass"] is False
    assert "lacks the expected" in wall["geometry_binding_error"]
    xml.write_text("<not-xml", encoding="utf-8")
    prepared["inputs"][str(xml.resolve())] = digest(xml)
    wall = wall_spec_from_prepared(prepared, prepared_path=tmp_path / "prepared.json")
    assert wall["geometry_binding_pass"] is False
    assert "invalid" in wall["geometry_binding_error"]


def test_geometry_hash_mismatch_fails_closed(tmp_path):
    prepared, xml = _prepared(tmp_path)
    prepared["inputs"][str(xml.resolve())] = "0" * 64
    wall = wall_spec_from_prepared(prepared, prepared_path=tmp_path / "prepared.json")
    assert wall["geometry_binding_pass"] is False
    assert wall["geometry_source_sha256"] == digest(xml)
    assert wall["geometry_expected_sha256"] == "0" * 64
    assert "hash differs" in wall["geometry_binding_error"]
