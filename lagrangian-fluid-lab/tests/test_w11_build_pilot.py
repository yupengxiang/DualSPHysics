from pathlib import Path
import json

import h5py
import numpy as np
import pytest

from scripts import w11_build_pilot
from scripts.w11_build_pilot import audit_case, build


def test_pilot_audit_accepts_closed_finite_case(tmp_path: Path):
    path = tmp_path / "tiny.h5"
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 0.1])
        h5.create_dataset("particle_id", data=[1, 2])
        h5.create_dataset("particle_zone", data=[0, 0])
        h5.create_dataset("valid", data=np.ones((2, 2), dtype=bool))
        for name in ("position", "velocity"):
            h5.create_dataset(name, data=np.zeros((2, 2, 3)))
        for name in ("density", "pressure", "mass"):
            h5.create_dataset(name, data=np.ones((2, 2)))
        for name in ("type", "mk"):
            h5.create_dataset(name, data=np.ones((2, 2), dtype=np.int16))
    result = audit_case(path, {"case_id": "tiny"})
    assert result["numerical_loss_fraction"] == 0
    assert result["frames"] == 2


def make_bad_case(path: Path, *, reappearing=False, mass_change=False, nan_density=False):
    valid = np.ones((3, 2), dtype=bool)
    if reappearing:
        valid[1, 0] = False
        valid[2, 0] = True
    with h5py.File(path, "w") as h5:
        h5.create_dataset("time", data=[0.0, 0.1, 0.2])
        h5.create_dataset("particle_id", data=[1, 2])
        h5.create_dataset("particle_zone", data=[0, 0])
        h5.create_dataset("valid", data=valid)
        for name in ("position", "velocity"):
            h5.create_dataset(name, data=np.zeros((3, 2, 3)))
        density = np.ones((3, 2))
        if nan_density:
            density[1, 0] = np.nan
        h5.create_dataset("density", data=density)
        h5.create_dataset("pressure", data=np.ones((3, 2)))
        mass = np.ones((3, 2))
        if mass_change:
            mass[1:, 0] = 2
        h5.create_dataset("mass", data=mass)
        h5.create_dataset("type", data=np.full((3, 2), 2, dtype=np.int16))
        h5.create_dataset("mk", data=np.ones((3, 2), dtype=np.int16))


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("reappearing", "interrupted or terminated"),
        ("mass_change", "mass changes over time"),
        ("nan_density", "non-finite value under valid mask"),
    ],
)
def test_pilot_audit_rejects_intermediate_defects(tmp_path: Path, defect: str, message: str):
    path = tmp_path / "bad.h5"
    make_bad_case(path, **{defect: True})
    with pytest.raises(ValueError, match=message):
        audit_case(path, {"case_id": "bad"})


def make_selection(path: Path, source: Path, *, case_id: str = "tiny", release_id: str = "pilot") -> Path:
    selection = path / "selection.json"
    selection.write_text(json.dumps({
        "release_id": release_id, "material_tracers_per_fluid_case": 0,
        "cases": [{"case_id": case_id, "source_hdf5": source.name, "family": "F6",
                   "split": "test", "lineage_group_id": case_id, "dp": 0.1,
                   "mechanism": "test", "validation_scope": []}],
    }))
    return selection


def test_failed_build_never_publishes_final_filename(tmp_path: Path):
    source = tmp_path / "bad-source.h5"
    make_bad_case(source, nan_density=True)
    selection = make_selection(tmp_path, source, case_id="bad", release_id="bad")
    release = tmp_path / "release"
    with pytest.raises(ValueError):
        build(selection, tmp_path, release)
    assert not (release / "data/bad.h5").exists()


def test_failed_rebuild_preserves_existing_final_file(tmp_path: Path):
    source = tmp_path / "source.h5"
    make_bad_case(source)
    selection = make_selection(tmp_path, source)
    release = tmp_path / "release"
    build(selection, tmp_path, release)
    target = release / "data/tiny.h5"
    original = target.read_bytes()

    make_bad_case(source, nan_density=True)
    with pytest.raises(ValueError):
        build(selection, tmp_path, release)
    assert target.read_bytes() == original
    assert (release / "data/tiny.h5.partial").exists()


def test_build_audits_partial_before_atomic_publish(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.h5"
    make_bad_case(source)
    selection = make_selection(tmp_path, source)
    release = tmp_path / "release"
    target = release / "data/tiny.h5"
    partial = release / "data/tiny.h5.partial"
    observed = {}
    real_audit = w11_build_pilot.audit_case

    def audit_during_build(candidate, expected):
        observed["candidate"] = candidate
        observed["final_exists"] = target.exists()
        observed["partial_exists"] = partial.exists()
        return real_audit(candidate, expected)

    monkeypatch.setattr(w11_build_pilot, "audit_case", audit_during_build)
    w11_build_pilot.build(selection, tmp_path, release)

    assert observed == {
        "candidate": partial,
        "final_exists": False,
        "partial_exists": True,
    }
    assert target.exists()
    assert not partial.exists()


def test_pilot_audit_rejects_material_mass_nonclosure(tmp_path: Path):
    path = tmp_path / "bad-material.h5"
    make_bad_case(path)
    with h5py.File(path, "r+") as h5:
        h5["type"][:] = 3
        material = h5.create_group("material")
        material.create_dataset("valid", data=np.ones((3, 1), dtype=bool))
        material.create_dataset("position", data=np.zeros((3, 1, 3)))
        material.create_dataset("mass_weight", data=[0.5])
        material.create_dataset("tracer_id", data=[0])
    with pytest.raises(ValueError, match="do not close"):
        audit_case(path, {"case_id": "bad-material"})
