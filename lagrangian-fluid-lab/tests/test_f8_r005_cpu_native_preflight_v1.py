from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np
import pytest

from scripts import f8_r005_cpu_native_preflight_authorization_v1 as authorization
from scripts import f8_r005_cpu_native_preflight_execute_v1 as executor
from scripts import f8_r005_cpu_native_preflight_runner_v1 as runner


LAB = Path(__file__).resolve().parents[1]


def write_bound_vtk(path: Path, include_upper: bool = True) -> None:
    planes = [-0.0525] * 512 + ([0.0525] * 512 if include_upper else [])
    points = []
    for plane_index, z in enumerate(planes):
        point_index = plane_index % 512
        x = (point_index % 32) * 0.0075
        y = (point_index // 32) * 0.0075
        points.extend((x, y, z))
    header = (
        "# vtk DataFile Version 3.0\nfixture\nBINARY\nDATASET POLYDATA\n"
        f"POINTS {len(planes)} float\n"
    ).encode("ascii")
    path.write_bytes(header + struct.pack(f">{len(points)}f", *points))


def write_generated_xml(path: Path) -> None:
    path.write_text(
        '<case><particles np="7680" nb="1024" nbf="1024">'
        '<fixed begin="0" count="1024" mkbound="0" mk="2" />'
        '<fluid begin="1024" count="6656" mkfluid="0" mk="1" />'
        '</particles></case>',
        encoding="utf-8",
    )


def write_native_index(base: Path, zero_normal: bool = False) -> None:
    boundary, fluid = 1024, 6656
    folder = base / "PART_0000"
    folder.mkdir(parents=True)
    z = np.concatenate((np.full(512, -0.0525), np.full(512, 0.0525)))
    pos = np.zeros((boundary + fluid, 3), dtype=np.float64)
    pos[:boundary, 2] = z
    vel = np.zeros((boundary + fluid, 3), dtype=np.float32)
    rho = np.full(boundary + fluid, 1000.0, dtype=np.float32)
    ids = np.arange(boundary + fluid, dtype=np.uint32)
    normals = np.zeros((boundary, 3), dtype=np.float32)
    normals[:512, 2] = -1.0
    normals[512:, 2] = 1.0
    if zero_normal:
        normals[0] = 0.0
    ids.tofile(folder / "Idp.bin")
    pos.tofile(folder / "Posd.bin")
    vel.tofile(folder / "Vel.bin")
    rho.tofile(folder / "Rhop.bin")
    normals.tofile(folder / "BoundNor.bin")
    (base.with_suffix(".xml")).write_text(
        '<data><item name="JPartDataBi4">'
        '<ullong name="CaseNfixed" v="1024" />'
        '<ullong name="CaseNmoving" v="0" />'
        '<ullong name="CaseNfloat" v="0" />'
        '<ullong name="CaseNfluid" v="6656" />'
        '<double name="MassFluid" v="0.000421875" />'
        '<item name="PART_0000"><uint name="Npok" v="7680" /></item>'
        '</item></data>',
        encoding="utf-8",
    )


def test_authorization_is_zero_credit_and_fixes_the_full_lattice_counts() -> None:
    value = authorization.build_authorization()
    gates = value["hard_gates"]
    assert value["status"] == "authorized_for_exactly_one_r005_cpu_native_preflight"
    assert value["scope_id"].endswith("R005")
    assert value["qualification_credit"] == 0
    assert gates["generated_fixed_boundary_particles_exact"] == 1024
    assert gates["generated_z_wall_plane_particle_counts"] == {"-0.0525": 512, "0.0525": 512}
    assert gates["generated_fluid_particles_exact"] == 6656
    assert gates["generated_total_particles_exact"] == 7680
    assert gates["native_fluid_mass_kg_expected"] == pytest.approx(2.808)
    assert value["permissions"]["cpu_gencase"] is True
    assert value["permissions"]["native_decode"] is True
    assert all(value["permissions"][key] is False for key in (
        "solver", "gpu", "queue", "worker", "registry", "ledger", "training", "qualification"
    ))


def test_authorization_hashes_all_inputs_tools_and_runner_code() -> None:
    value = authorization.build_authorization()
    for item in value["bindings"]:
        path = LAB / item["path"]
        assert path.is_file()
        assert authorization.sha256(path) == item["sha256"]
        assert path.stat().st_size == item["bytes"]
    assert authorization.bindings_current(value)


def test_generated_audit_requires_two_complete_wall_planes(tmp_path: Path) -> None:
    generated = tmp_path / "generated.xml"
    bound = tmp_path / "Bound.vtk"
    write_generated_xml(generated)
    write_bound_vtk(bound)
    gates = authorization.build_authorization()
    assert executor.generated_checks(generated, bound, gates)["pass"] is True

    write_bound_vtk(bound, include_upper=False)
    audit = executor.generated_checks(generated, bound, gates)
    assert audit["checks"]["generated_z_wall_plane_particle_counts_exact"] is False
    assert audit["pass"] is False


def test_native_audit_requires_complete_nonzero_normals_and_exact_counts(tmp_path: Path) -> None:
    generated = tmp_path / "generated.xml"
    bound = tmp_path / "Bound.vtk"
    write_generated_xml(generated)
    write_bound_vtk(bound)
    gates = authorization.build_authorization()

    base = tmp_path / "native-initial"
    write_native_index(base)
    passed = executor.native_checks(generated, base, gates)
    assert passed["pass"] is True
    assert passed["native"]["boundary_wall_plane_particle_counts"] == {"-0.0525": 512, "0.0525": 512}
    assert passed["native"]["fluid_mass_kg"] == pytest.approx(2.808)

    bad_base = tmp_path / "native-initial-zero-normal"
    write_native_index(bad_base, zero_normal=True)
    failed = executor.native_checks(generated, bad_base, gates)
    assert failed["checks"]["native_boundary_normals_finite_and_nonzero"] is False
    assert failed["pass"] is False


def test_runner_and_executor_refuse_namespace_substitution() -> None:
    with pytest.raises(ValueError, match="registered F8 r005 output namespace"):
        runner.build_execution_plan(LAB / "wrong-output")
    with pytest.raises(ValueError, match="registered F8 r005 output namespace"):
        executor.run_once(LAB / "wrong-output")


def test_executor_source_keeps_solver_and_external_surfaces_closed() -> None:
    source = (LAB / "scripts/f8_r005_cpu_native_preflight_execute_v1.py").read_text(encoding="utf-8")
    assert '"solver_invoked": False' in source
    assert '"gpu_invoked": False' in source
    assert '"worker_started": False' in source
    assert "generated_checks" in source
    assert "native_checks" in source


def test_authorization_writer_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "authorization.json"
    authorization.write_authorization(target)
    assert json.loads(target.read_text(encoding="utf-8"))["qualification_credit"] == 0
    with pytest.raises(FileExistsError, match="immutable F8 r005 authorization"):
        authorization.write_authorization(target)
