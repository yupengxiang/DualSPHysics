from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from scripts import core_f3_cfd_source_dtmin_repair_v1 as runner


def test_v1_runner_delegates_to_streaming_audit_v2(tmp_path: Path) -> None:
    prefix = tmp_path / "F3_CELL3_plain_0p0075"
    xml = prefix.with_suffix(".xml")
    xml.write_text(
        "<root><list name='GeometryForNormals'><drawbox>"
        "<boxfill>all^top</boxfill>"
        "<point x='-0.45' y='-0.09' z='0.0'/><size x='0.9' y='0.18' z='0.51'/>"
        "</drawbox></list></root>"
    )
    with h5py.File(tmp_path / "trajectory.h5", "w") as handle:
        handle.attrs["conversion_complete"] = True
        handle.create_dataset("particle_id", data=np.asarray([0, 1], dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.zeros(2, dtype=np.int32))
        handle.create_dataset("source_label_initial_mk", data=np.ones(2, dtype=np.int32))
        handle.create_dataset("time", data=np.asarray([0.0, 0.002]))
        handle.create_dataset("position", data=np.asarray([
            [[0.0, 0.0, 0.1], [0.1, 0.0, 0.1]],
            [[0.0, 0.0, 0.11], [0.1, 0.0, 0.11]],
        ]))
        for name, value in {
            "velocity": np.zeros((2, 2, 3)),
            "density": np.ones((2, 2)),
            "pressure": np.zeros((2, 2)),
        }.items():
            handle.create_dataset(name, data=value)
        handle.create_dataset("mass", data=np.full(2, 0.5))
        handle.create_dataset("valid", data=np.ones((2, 2), dtype=bool))
        handle.create_dataset("type", data=np.ones((2, 2), dtype=np.int32))
        handle.create_dataset("mk", data=np.ones((2, 2), dtype=np.int32))
    prepared = {
        "case": {"case_id": "tiny", "source_asset_id": "tiny", "expected_native_frames": 2,
                 "fluid_particles": 2, "output_interval_s": 0.002, "time_max_s": 0.002},
        "config": {"expected_native_frames": 2, "output_interval_s": 0.002, "time_max_s": 0.002},
        "generated_prefix": str(prefix),
        "inputs": {str(xml.resolve()): runner.digest(xml)},
    }
    product = tmp_path / "product"
    product.mkdir()
    report = runner._audit_hdf5(
        prepared, tmp_path / "prepared.json", tmp_path / "trajectory.h5", product,
    )
    assert report["schema"] == "core.f3.cfd.native_volume_mls.source_audit.v2"
    assert report["hard_integrity_pass"] is True
    assert report["runner_audit_binding"]["delegated_without_copy"] is True
    assert report["wall"]["finite_geometry_binding_pass"] is True
    assert report["mass_per_particle"]["constant_pass"] is True
