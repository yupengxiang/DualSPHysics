from __future__ import annotations

import h5py
import pytest

from scripts.trajectory_io import audit_hdf5, convert_streaming


HEADER = ("Pos.x [m],Pos.y [m],Pos.z [m],Zone,Idp,Vel.x [m/s],Vel.y [m/s],"
          "Vel.z [m/s],Rhop [kg/m^3],Mass [kg],Press [Pa],Type,Mk,\n")


def write_csv(path, time, rows):
    lines = ["TimeStep [s],Np,Nbound,Nfixed,Nmoving,Nfloat,Nfluid\n",
             f"{time},{len(rows)},0,0,0,0,{len(rows)}\n", "\n", HEADER]
    for row in rows:
        lines.append(",".join(str(value) for value in row) + ",\n")
    path.write_text("".join(lines))


def particle(x, particle_id):
    return [x, 0, 0, 0, particle_id, 0, 0, 0, 1000, 1, 0, 3, 0]


def test_streaming_conversion_resumes_and_atomically_commits(tmp_path):
    csvs = [tmp_path / "Particles_0000.csv", tmp_path / "Particles_0001.csv"]
    write_csv(csvs[0], 0.0, [particle(0.1, 10), particle(0.2, 11)])
    write_csv(csvs[1], 1.0, [particle(0.3, 10), particle(0.4, 11)])
    out = tmp_path / "case.h5"
    record = {"id": "case", "family": "test", "mechanism": "closed", "shifting": 0}
    with pytest.raises(RuntimeError, match="injected"):
        convert_streaming(record, csvs, out, fail_after_frames=1)
    partial = tmp_path / "case.h5.partial"
    assert partial.is_file() and not out.exists()
    with h5py.File(partial) as h5:
        assert h5.attrs["conversion_complete_frames"] == 1
        assert not h5.attrs["conversion_complete"]
    convert_streaming(record, csvs, out)
    assert out.is_file() and not partial.exists()
    with h5py.File(out) as h5:
        assert h5.attrs["schema_version"] == 3
        assert h5.attrs["conversion_complete"]
        assert h5.attrs["conversion_complete_frames"] == 2
        assert h5["position"][1, 1, 0] == pytest.approx(0.4)


def test_mass_transport_denominator_includes_missing_particles(tmp_path):
    csvs = [tmp_path / "Particles_0000.csv", tmp_path / "Particles_0001.csv"]
    write_csv(csvs[0], 0.0, [particle(0.1, 10), particle(0.2, 11)])
    write_csv(csvs[1], 1.0, [particle(0.9, 10)])
    out = tmp_path / "case.h5"
    record = {"id": "case", "family": "test", "mechanism": "closed", "shifting": 0}
    convert_streaming(record, csvs, out)
    run_dir = tmp_path / "runs" / "case"
    run_dir.mkdir(parents=True)
    (run_dir / "Run.out").write_text("Excluded particles........: 1\n")
    audit = audit_hdf5(record, out, tmp_path / "runs", tmp_path)
    bins = audit["source_destination_mass_world_x_legacy"]["0"]
    assert bins["initial_mass_kg"] == pytest.approx(2.0)
    assert bins["right_x_ge_0p8_mass_fraction"] == pytest.approx(0.5)
    assert bins["numerically_missing_mass_fraction"] == pytest.approx(0.5)
    total = sum(value for key, value in bins.items() if key.endswith("_mass_fraction"))
    assert total == pytest.approx(1.0)
