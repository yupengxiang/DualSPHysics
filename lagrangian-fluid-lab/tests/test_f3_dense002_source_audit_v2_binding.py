from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np

from scripts import core_f3_cfd_source_dtmin_repair_v2 as runner


def _tiny_source(tmp_path: Path) -> tuple[dict, Path]:
    prefix = tmp_path / "F3_CELL3_plain_0p0075"
    xml = prefix.with_suffix(".xml")
    xml.write_text(
        "<root><list name='GeometryForNormals'><drawbox>"
        "<boxfill>all^top</boxfill>"
        "<point x='-0.45' y='-0.09' z='0.0'/>"
        "<size x='0.9' y='0.18' z='0.51'/>"
        "</drawbox></list></root>"
    )
    n, nt = 2, 2
    positions = np.asarray(
        [[[0.0, 0.0, 0.1], [0.1, 0.0, 0.1]],
         [[0.0, 0.0, 0.11], [0.1, 0.0, 0.11]]], dtype=np.float64
    )
    with h5py.File(tmp_path / "trajectory.h5", "w") as handle:
        handle.attrs["conversion_complete"] = True
        handle.create_dataset("particle_id", data=np.arange(n, dtype=np.int64))
        handle.create_dataset("particle_zone", data=np.ones(n, dtype=np.int32))
        handle.create_dataset("source_label_initial_mk", data=np.ones(n, dtype=np.int32))
        handle.create_dataset("time", data=np.asarray([0.0, 0.002]))
        handle.create_dataset("position", data=positions)
        handle.create_dataset("velocity", data=np.zeros((nt, n, 3)))
        handle.create_dataset("density", data=np.ones((nt, n)))
        handle.create_dataset("mass", data=np.full(n, 0.5))
        handle.create_dataset("pressure", data=np.zeros((nt, n)))
        handle.create_dataset("valid", data=np.ones((nt, n), dtype=bool))
        handle.create_dataset("type", data=np.full((nt, n), 1, dtype=np.int32))
        handle.create_dataset("mk", data=np.full((nt, n), 1, dtype=np.int32))
    prepared = {
        "case": {
            "case_id": "tiny",
            "source_asset_id": "tiny",
            "expected_native_frames": nt,
            "fluid_particles": n,
            "output_interval_s": 0.002,
            "time_max_s": 0.002,
        },
        "config": {"expected_native_frames": nt, "output_interval_s": 0.002, "time_max_s": 0.002},
        "generated_prefix": str(prefix),
        "inputs": {str(xml.resolve()): runner.digest(xml)},
    }
    return prepared, tmp_path / "trajectory.h5"


def test_source_runner_delegates_to_audit_v2(tmp_path: Path) -> None:
    prepared, h5 = _tiny_source(tmp_path)
    output = tmp_path / "product"
    output.mkdir()
    report = runner._audit_hdf5(prepared, h5, output, prepared_path=tmp_path / "prepared.json")
    assert report["schema"] == "core.f3.cfd.native_volume_mls.source_audit.v2"
    assert report["audit_version"] == 2
    assert report["hard_integrity_pass"] is True
    assert report["runner_audit_binding"]["delegated_without_copy"] is True
    assert report["runner_audit_binding"]["audit_schema_required"].endswith("source_audit.v2")
    assert json.loads((output / "audit.json").read_text())["schema"].endswith("source_audit.v2")
