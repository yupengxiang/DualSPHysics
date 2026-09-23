from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np
import pytest

from scripts import f8_r006_cpu_native_preflight_authorization_v1 as authorization
from scripts import f8_r006_cpu_native_preflight_execute_v1 as executor
from scripts import f8_r006_cpu_native_preflight_runner_v1 as runner


LAB = Path(__file__).resolve().parents[1]
WALL_Z = [-0.075, -0.0675, -0.06, -0.0525, 0.0525, 0.06, 0.0675, 0.075]


def write_vtk(path: Path, points: list[tuple[float, float, float]]) -> None:
    values = [coordinate for point in points for coordinate in point]
    header = (
        "# vtk DataFile Version 3.0\nfixture\nBINARY\nDATASET POLYDATA\n"
        f"POINTS {len(points)} float\n"
    ).encode("ascii")
    path.write_bytes(header + struct.pack(f">{len(values)}f", *values))


def wall_points(planes: list[float] = WALL_Z) -> list[tuple[float, float, float]]:
    return [
        ((index % 32) * 0.0075, (index // 32) * 0.0075, z)
        for z in planes for index in range(512)
    ]


def fluid_points(zmax: float = 0.045) -> list[tuple[float, float, float]]:
    layers = [(-zmax) + index * 0.0075 for index in range(13)]
    return [
        (x * 0.0075, y * 0.0075, z)
        for z in layers for y in range(16) for x in range(32)
    ]


def hdp_points(zplanes: tuple[float, float] = (-0.04875, 0.04875)) -> list[tuple[float, float, float]]:
    return [
        (x, y, z)
        for z in zplanes for x, y in ((0.0, 0.0), (0.24, 0.0), (0.24, 0.12), (0.0, 0.12))
    ]


def write_generated_xml(path: Path, fluid_count: int = 6656) -> None:
    path.write_text(
        '<case><particles np="10752" nb="4096" nbf="4096">'
        '<_summary><positions><posmin x="0" y="0" z="-0.075" />'
        '<posmax x="0.2325" y="0.1125" z="0.075" /></positions></_summary>'
        '<fixed begin="0" count="4096" mkbound="0" mk="2" />'
        f'<fluid begin="4096" count="{fluid_count}" mkfluid="0" mk="1" />'
        '</particles></case>',
        encoding="utf-8",
    )


def write_generated_outputs(tmp_path: Path, *, omit_last_wall_plane: bool = False,
                            wrong_hdp: bool = False, fluid_zmax: float = 0.045) -> tuple[Path, Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    generated = tmp_path / "generated.xml"
    bound = tmp_path / "Bound.vtk"
    fluid = tmp_path / "Fluid.vtk"
    hdp = tmp_path / "hdp_Actual.vtk"
    write_generated_xml(generated)
    planes = WALL_Z[:-1] if omit_last_wall_plane else WALL_Z
    write_vtk(bound, wall_points(planes))
    write_vtk(fluid, fluid_points(fluid_zmax))
    write_vtk(hdp, hdp_points((-0.0525, 0.0525) if wrong_hdp else (-0.04875, 0.04875)))
    return generated, bound, fluid, hdp


def write_native_index(base: Path, *, normal_magnitude: float = 0.00375,
                       reverse_lower: bool = False, reverse_upper: bool = False) -> None:
    boundary, fluid_count = 4096, 6656
    folder = base / "PART_0000"
    folder.mkdir(parents=True)
    z = np.repeat(np.asarray(WALL_Z, dtype=np.float64), 512)
    pos = np.zeros((boundary + fluid_count, 3), dtype=np.float64)
    pos[:boundary, 2] = z
    vel = np.zeros((boundary + fluid_count, 3), dtype=np.float32)
    rho = np.full(boundary + fluid_count, 1000.0, dtype=np.float32)
    ids = np.arange(boundary + fluid_count, dtype=np.uint32)
    normals = np.zeros((boundary, 3), dtype=np.float32)
    lower, upper = z < 0, z > 0
    normals[lower, 2] = -normal_magnitude if reverse_lower else normal_magnitude
    normals[upper, 2] = normal_magnitude if reverse_upper else -normal_magnitude
    ids.tofile(folder / "Idp.bin")
    pos.tofile(folder / "Posd.bin")
    vel.tofile(folder / "Vel.bin")
    rho.tofile(folder / "Rhop.bin")
    normals.tofile(folder / "BoundNor.bin")
    (base.with_suffix(".xml")).write_text(
        '<data><item name="JPartDataBi4">'
        '<ullong name="CaseNfixed" v="4096" />'
        '<ullong name="CaseNmoving" v="0" />'
        '<ullong name="CaseNfloat" v="0" />'
        '<ullong name="CaseNfluid" v="6656" />'
        '<double name="MassFluid" v="0.000421875" />'
        '<item name="PART_0000"><uint name="Npok" v="10752" /></item>'
        '</item></data>',
        encoding="utf-8",
    )


def test_authorization_freezes_four_layer_counts_and_zero_credit() -> None:
    value = authorization.build_authorization()
    gates = value["hard_gates"]
    assert value["status"] == "authorized_for_exactly_one_r006_cpu_native_preflight"
    assert value["scope_id"].endswith("R006")
    assert value["qualification_credit"] == 0
    assert gates["generated_fixed_boundary_particles_exact"] == 4096
    assert gates["generated_z_wall_plane_particle_counts"] == {
        "-0.0750": 512, "-0.0675": 512, "-0.0600": 512, "-0.0525": 512,
        "0.0525": 512, "0.0600": 512, "0.0675": 512, "0.0750": 512,
    }
    assert gates["generated_hdp_surface_z_planes_m"] == [-0.04875, 0.04875]
    assert gates["generated_fluid_particles_exact"] == 6656
    assert gates["generated_total_particles_exact"] == 10752
    assert gates["native_boundary_normals_finite_and_minimum_magnitude"] == pytest.approx(0.001875)
    assert value["permissions"]["cpu_gencase"] is True
    assert value["permissions"]["native_decode"] is True
    assert all(value["permissions"][key] is False for key in (
        "solver", "gpu", "queue", "worker", "registry", "ledger", "training", "qualification"
    ))


def test_authorization_hashes_inputs_binaries_runner_executor_and_tests() -> None:
    value = authorization.build_authorization()
    for item in value["bindings"]:
        path = LAB / item["path"]
        assert path.is_file()
        assert authorization.sha256(path) == item["sha256"]
        assert path.stat().st_size == item["bytes"]
    assert authorization.bindings_current(value)
    runner.validate_authorization(value)


def test_generated_audit_requires_eight_wall_planes_and_both_offset_surfaces(tmp_path: Path) -> None:
    generated, bound, fluid, hdp = write_generated_outputs(tmp_path)
    gates = authorization.build_authorization()
    audit = executor.generated_checks(generated, bound, fluid, hdp, gates)
    assert audit["pass"] is True
    assert audit["generated_geometry"]["wall_plane_particle_counts"] == gates["hard_gates"]["generated_z_wall_plane_particle_counts"]
    assert audit["generated_geometry"]["fluid_particles"] == 6656
    assert audit["generated_geometry"]["hdp_surface_z_planes_m"] == [-0.04875, 0.04875]

    generated, bound, fluid, hdp = write_generated_outputs(tmp_path / "missing-wall", omit_last_wall_plane=True)
    failed = executor.generated_checks(generated, bound, fluid, hdp, gates)
    assert failed["checks"]["generated_z_wall_plane_particle_counts_exact"] is False
    assert failed["pass"] is False

    generated, bound, fluid, hdp = write_generated_outputs(tmp_path / "wrong-hdp", wrong_hdp=True)
    failed = executor.generated_checks(generated, bound, fluid, hdp, gates)
    assert failed["checks"]["generated_hdp_surface_z_planes_exact"] is False
    assert failed["pass"] is False


def test_generated_fluid_vtk_hard_gate_uses_fluid_only_extent(tmp_path: Path) -> None:
    generated, bound, fluid, hdp = write_generated_outputs(tmp_path, fluid_zmax=0.0375)
    gates = authorization.build_authorization()
    failed = executor.generated_checks(generated, bound, fluid, hdp, gates)
    assert failed["checks"]["generated_fluid_vtk_z_bounds_exact"] is False
    assert failed["pass"] is False


def test_native_audit_requires_normal_magnitude_orientation_and_exact_counts(tmp_path: Path) -> None:
    generated, _, _, _ = write_generated_outputs(tmp_path)
    gates = authorization.build_authorization()

    base = tmp_path / "native-good"
    write_native_index(base)
    passed = executor.native_checks(generated, base, gates)
    assert passed["pass"] is True
    assert passed["native"]["boundary_wall_plane_particle_counts"] == gates["hard_gates"]["native_boundary_z_wall_plane_particle_counts"]
    assert passed["native"]["minimum_normal_magnitude_m"] == pytest.approx(0.00375)
    assert passed["native"]["fluid_mass_kg"] == pytest.approx(2.808)

    weak = tmp_path / "native-weak-normal"
    write_native_index(weak, normal_magnitude=0.001)
    failed = executor.native_checks(generated, weak, gates)
    assert failed["checks"]["native_boundary_normals_finite_and_minimum_magnitude"] is False

    reversed_lower = tmp_path / "native-reversed-lower"
    write_native_index(reversed_lower, reverse_lower=True)
    failed = executor.native_checks(generated, reversed_lower, gates)
    assert failed["checks"]["native_boundary_normals_point_inward"] is False

    reversed_upper = tmp_path / "native-reversed-upper"
    write_native_index(reversed_upper, reverse_upper=True)
    failed = executor.native_checks(generated, reversed_upper, gates)
    assert failed["checks"]["native_boundary_normals_point_inward"] is False


def test_runner_and_executor_refuse_namespace_substitution() -> None:
    with pytest.raises(ValueError, match="registered F8 r006 output namespace"):
        runner.build_execution_plan(LAB / "wrong-output")
    with pytest.raises(ValueError, match="registered F8 r006 output namespace"):
        executor.run_once(LAB / "wrong-output")


def test_executor_source_keeps_solver_and_external_surfaces_closed() -> None:
    source = (LAB / "scripts/f8_r006_cpu_native_preflight_execute_v1.py").read_text(encoding="utf-8")
    assert '"solver_invoked": False' in source
    assert '"gpu_invoked": False' in source
    assert '"worker_started": False' in source
    assert "generated_checks" in source
    assert "native_checks" in source
    assert "failed before native decode" in source


def test_authorization_writer_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "authorization.json"
    authorization.write_authorization(target)
    assert json.loads(target.read_text(encoding="utf-8"))["qualification_credit"] == 0
    with pytest.raises(FileExistsError, match="immutable F8 r006 authorization"):
        authorization.write_authorization(target)
