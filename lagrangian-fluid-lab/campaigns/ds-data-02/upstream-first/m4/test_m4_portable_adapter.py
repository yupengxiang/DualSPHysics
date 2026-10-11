from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import h5py
import numpy as np
import pytest


M4_ROOT = Path(__file__).resolve().parent
if str(M4_ROOT) not in sys.path:
    sys.path.insert(0, str(M4_ROOT))

import m4_isolated_validate  # noqa: E402
import m4_portable_adapter as m4  # noqa: E402


def _array_hash(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values.astype("<u4")).tobytes()).hexdigest()


def _fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    hdf5_path = root / "normalized.h5"
    ids = np.array([10, 11, 12, 13], dtype="<u4")
    zones = np.zeros(4, dtype="<u4")
    valid = np.array(
        [
            [True, True, True, True],
            [True, True, False, True],
            [True, True, False, True],
        ],
        dtype=bool,
    )
    position = np.array(
        [
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]],
            [[0.1, 0.0, 0.0], [1.1, 0.0, 0.0], [np.nan, np.nan, np.nan], [3.1, 0.0, 0.0]],
            [[0.2, 0.0, 0.0], [1.2, 0.0, 0.0], [np.nan, np.nan, np.nan], [3.2, 0.0, 0.0]],
        ],
        dtype="f8",
    )
    velocity = np.zeros((3, 4, 3), dtype="f8")
    density = np.full((3, 4), 1000.0, dtype="f8")
    mass = np.ones((3, 4), dtype="f8")
    pressure = np.zeros((3, 4), dtype="f8")
    particle_type = np.full((3, 4), 3, dtype="i4")
    mk = np.zeros((3, 4), dtype="i4")
    initial_type = np.full(4, 3, dtype="i4")
    initial_mk = np.zeros(4, dtype="i4")
    initial_mass = np.ones(4, dtype="f8")
    exclusion = np.array([False, False, True, False], dtype=bool)
    source_valid = valid[0]
    destination_valid = valid[-1]
    source_position = position[0]
    destination_position = position[-1]
    displacement = np.full((4, 3), np.nan, dtype="f8")
    displacement[source_valid & destination_valid] = (
        destination_position[source_valid & destination_valid]
        - source_position[source_valid & destination_valid]
    )
    string_dtype = h5py.string_dtype(encoding="utf-8")
    with h5py.File(hdf5_path, "w") as handle:
        handle.attrs["solver_dimension"] = 3
        handle.attrs["identity_key"] = "(Zone,Idp)"
        handle.attrs["coordinate_frame"] = "DualSPHysics Cartesian coordinates (x,y,z)"
        handle.create_dataset("time", data=np.array([0.0, 0.1, 0.2], dtype="f8"))
        handle.create_dataset("particle_id", data=ids)
        handle.create_dataset("particle_zone", data=zones)
        handle.create_dataset("valid", data=valid)
        for name, values in {
            "position": position,
            "velocity": velocity,
            "density": density,
            "mass": mass,
            "pressure": pressure,
            "type": particle_type,
            "mk": mk,
            "initial_type": initial_type,
            "initial_mk": initial_mk,
            "initial_mass": initial_mass,
        }.items():
            handle.create_dataset(name, data=values)
        native = handle.create_group("native")
        native.create_dataset("exclusion_mask", data=exclusion)
        transport = handle.create_group("transport")
        transport.create_dataset("particle_id", data=ids)
        transport.create_dataset("particle_zone", data=zones)
        transport.create_dataset("source_valid", data=source_valid)
        transport.create_dataset("destination_valid", data=destination_valid)
        transport.create_dataset(
            "source_label", data=np.array(["valid_source"] * 4, dtype=string_dtype), dtype=string_dtype
        )
        transport.create_dataset(
            "destination_label",
            data=np.array(["valid_destination", "valid_destination", "unknown", "valid_destination"], dtype=string_dtype),
            dtype=string_dtype,
        )
        transport.create_dataset("source_position", data=source_position)
        transport.create_dataset("destination_position", data=destination_position)
        transport.create_dataset("displacement", data=displacement)
    hdf5_binding = {"path": hdf5_path.name, "bytes": hdf5_path.stat().st_size, "sha256": m4._sha256(hdf5_path)}
    interface = {
        "schema": m4.INTERFACE_SCHEMA,
        "status": "normalized_verified",
        "family_id": "F1",
        "case_id": "UF_F1_MDBC_SYNTHETIC",
        "source_mother": "synthetic_fixture_only",
        "condition_role": "official_mother",
        "credit_status": "not_credited",
        "physical_fate_inferred": False,
        "normalized_hdf5": hdf5_binding,
        "identity_axis": {
            "key": "(Zone,Idp)",
            "full_initial_identity": True,
            "all_frames_fixed_axis": True,
            "initial_particle_count": 4,
            "frame_count": 3,
            "initial_ids_sha256": _array_hash(ids),
        },
        "exclusion_mask": {
            "status": "verified",
            "count": 1,
            "ids_sha256": _array_hash(ids[exclusion]),
            "mask_dataset": "/native/exclusion_mask",
            "physical_fate_inferred": False,
            "native_scan_schema": "ds-data-02.upstream-first.native-frame-identity-scan.v1",
            "native_scan_path": "native-frame-scan.json",
        },
        "endpoint_transport": {
            "schema": m4.ENDPOINT_SCHEMA,
            "source_frame": 0,
            "destination_frame": "last",
            "source_valid_label": "valid_source",
            "destination_valid_label": "valid_destination",
            "missing_endpoint_labels": ["unknown", "censored"],
            "physical_fate_inferred": False,
            "particle_id_dataset": "/transport/particle_id",
            "particle_zone_dataset": "/transport/particle_zone",
            "source_valid_dataset": "/transport/source_valid",
            "destination_valid_dataset": "/transport/destination_valid",
            "source_label_dataset": "/transport/source_label",
            "destination_label_dataset": "/transport/destination_label",
            "source_position_dataset": "/transport/source_position",
            "destination_position_dataset": "/transport/destination_position",
            "displacement_dataset": "/transport/displacement",
        },
        "source_receipts": [
            {
                "role": "native_frame_scan",
                "path": "/unavailable/synthetic/native-frame-scan.json",
                "bytes": 1,
                "sha256": "0" * 64,
            }
        ],
    }
    interface_path = root / "interface.json"
    interface_path.write_text(json.dumps(interface, indent=2), encoding="utf-8")
    return interface_path


def _refresh_hdf5_binding(interface_path: Path) -> None:
    payload = json.loads(interface_path.read_text(encoding="utf-8"))
    hdf5_path = interface_path.parent / payload["normalized_hdf5"]["path"]
    payload["normalized_hdf5"] = {
        "path": hdf5_path.name,
        "bytes": hdf5_path.stat().st_size,
        "sha256": m4._sha256(hdf5_path),
    }
    interface_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_validity_aware_normalized_case_accepts_nan_only_on_invalid_nodes(tmp_path: Path) -> None:
    interface = _fixture(tmp_path)
    result = m4.validate_interface(interface)
    assert result["summary"]["initial_identity_complete"] is True
    assert result["summary"]["native_exclusion_count"] == 1
    assert result["summary"]["missing_destination_count"] == 1


def test_nonfinite_valid_field_is_rejected(tmp_path: Path) -> None:
    interface = _fixture(tmp_path)
    with h5py.File(tmp_path / "normalized.h5", "r+") as handle:
        handle["density"][1, 0] = np.nan
    _refresh_hdf5_binding(interface)
    with pytest.raises(m4.M4Error, match="density.*non-finite valid"):
        m4.validate_interface(interface)


def test_full_identity_and_mask_hash_cannot_be_permuted(tmp_path: Path) -> None:
    interface = _fixture(tmp_path)
    with h5py.File(tmp_path / "normalized.h5", "r+") as handle:
        handle["particle_id"][1] = handle["particle_id"][0]
    _refresh_hdf5_binding(interface)
    with pytest.raises(m4.M4Error, match="duplicates"):
        m4.validate_interface(interface)


def test_endpoint_semantic_negatives_are_rejected(tmp_path: Path) -> None:
    interface = _fixture(tmp_path)
    with h5py.File(tmp_path / "normalized.h5", "r+") as handle:
        handle["transport/destination_label"][2] = "escaped"
    _refresh_hdf5_binding(interface)
    with pytest.raises(m4.M4Error, match="physical fate|outside the endpoint"):
        m4.validate_interface(interface)

    interface = _fixture(tmp_path / "second")
    with h5py.File(interface.parent / "normalized.h5", "r+") as handle:
        handle["transport/destination_label"][2] = "valid_destination"
    _refresh_hdf5_binding(interface)
    with pytest.raises(m4.M4Error, match="does not identify a valid destination|fabricates a destination fate"):
        m4.validate_interface(interface)


def test_missing_endpoint_cannot_publish_finite_displacement(tmp_path: Path) -> None:
    interface = _fixture(tmp_path)
    with h5py.File(tmp_path / "normalized.h5", "r+") as handle:
        handle["transport/displacement"][2] = [0.0, 0.0, 0.0]
    _refresh_hdf5_binding(interface)
    with pytest.raises(m4.M4Error, match="missing endpoint pairs"):
        m4.validate_interface(interface)


def test_pending_children_are_inspectable_but_not_complete_products(tmp_path: Path) -> None:
    interface = _fixture(tmp_path)
    payload = json.loads(interface.read_text(encoding="utf-8"))
    payload["status"] = "template_pending_native_audit"
    payload["identity_axis"]["initial_particle_count"] = None
    payload["identity_axis"]["frame_count"] = None
    payload["identity_axis"].pop("initial_ids_sha256")
    payload["exclusion_mask"]["status"] = "pending_audit"
    payload["exclusion_mask"]["count"] = None
    payload["exclusion_mask"].pop("ids_sha256")
    interface.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    pending = m4.validate_interface(interface, allow_pending=True, verify_payload=False)
    assert pending["summary"]["pending"] is True
    with pytest.raises(m4.M4Error, match="pending"):
        m4.validate_interface(interface)


def test_bundle_is_relocatable_and_runtime_recomputes_summary(tmp_path: Path) -> None:
    interface = _fixture(tmp_path / "input")
    bundle = tmp_path / "bundle"
    result = m4.build_bundle(interface, bundle)
    assert result["portable"] is True
    assert result["source_paths_redacted"] is True
    assert not (bundle / "runtime/m4_isolated_validate.py").exists()
    bundled_interface = json.loads((bundle / "interface.json").read_text(encoding="utf-8"))
    assert bundled_interface["source_receipts"][0]["path"].startswith("portable/source-receipt/")
    assert "/unavailable/" not in (bundle / "interface.json").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap is unavailable")
def test_bubblewrap_wrapper_runs_only_bundled_runtime(tmp_path: Path) -> None:
    interface = _fixture(tmp_path / "input")
    bundle = tmp_path / "bundle"
    m4.build_bundle(interface, bundle)
    output = tmp_path / "isolated.json"
    python = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
    if not python.is_file():
        pytest.skip("project virtualenv is unavailable")
    result = m4_isolated_validate._run(
        argparse.Namespace(
            bundle_root=bundle,
            python=python,
            output=output,
            max_wall_seconds=120.0,
            denied_path=[],
        )
    )
    assert result["validation"]["portable"] is True
    assert result["namespace"]["denied_probes_passed"] is True
