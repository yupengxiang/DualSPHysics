from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np

from scripts.ds_data02_f1_finite_center_audit import audit, read_binary_vtk_points


def _write_points(path: Path, points: np.ndarray) -> None:
    payload = np.asarray(points, dtype=">f4").tobytes()
    path.write_bytes(
        b"# vtk DataFile Version 3.0\n"
        b"test\nBINARY\nDATASET POLYDATA\n"
        + f"POINTS {len(points)} float\n".encode()
        + payload
    )


def _metadata(path: Path) -> None:
    value = {
        "schema": "test",
        "case_id": "case",
        "physical_case_id": "mother",
        "continuous_contract": {
            "initial_center_envelope_low_m": [2.105, 0.005, 0.005],
            "initial_center_envelope_high_m": [2.115, 0.015, 0.015],
            "expected_center_envelope_low_m": [2.105, 0.005, 0.005],
            "expected_center_envelope_high_m": [2.115, 0.015, 0.015],
            "expected_center_counts_xyz": [2, 2, 2],
            "expected_fluid_count": 8,
            "expected_native_mass_kg": 0.008,
            "reservoir_low_m": [2.1, 0.0, 0.0],
            "reservoir_high_m": [2.12, 0.02, 0.02],
            "reservoir_volume_m3": 0.000008,
            "reservoir_mass_kg": 0.008,
        },
        "declared_geometry": {
            "tank_low_m": [0.0, -0.005, -0.005],
            "tank_high_m": [2.13, 0.025, 0.025],
            "wall_clearance_from_fluid_centers_m": 0.005,
            "separator_high_m": [2.0, 0.0, 0.0],
        },
    }
    path.write_text(json.dumps(value))


def test_binary_vtk_parser_reads_big_endian_points(tmp_path: Path) -> None:
    points = np.array([[2.105, 0.005, 0.005], [2.115, 0.015, 0.015]])
    path = tmp_path / "points.vtk"
    _write_points(path, points)
    np.testing.assert_allclose(read_binary_vtk_points(path), points, rtol=0, atol=1e-6)


def test_audit_records_contract_without_scientific_acceptance(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.json"
    _metadata(metadata)
    points = np.array(
        [
            [x, y, z]
            for x in [2.105, 2.115]
            for y in [0.005, 0.015]
            for z in [0.005, 0.015]
        ]
    )
    root = tmp_path / "gencase"
    root.mkdir()
    _write_points(root / "case_Fluid.vtk", points)
    _write_points(root / "case_Bound.vtk", np.array([[0.0, -0.005, -0.005]]))
    (root / "case.out").write_text(
        "Data2D=[0]\nMassFluid=[0.001]\n"
        "Fluid....: 8\nTotal particles: 9\n"
    )
    (root / "case.xml").write_text("<case />")
    (root / "case.bi4").write_bytes(b"immutable native placeholder")
    report = audit(root, metadata, tmp_path / "audit.json")
    assert report["status"] == "pass_initial_native_contract"
    assert report["q_n_status"] == "not_assessed"
    assert report["checks"]["native_fluid_count_matches"]
