from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np
import pytest

from scripts import f8_r007_cpu_native_preflight_authorization_v1 as authorization
from scripts import f8_r007_cpu_native_preflight_execute_v1 as executor
from scripts import f8_r007_cpu_native_preflight_runner_v1 as runner


LAB = Path(__file__).resolve().parents[1]
WALL_Z = [-0.075, -0.0675, -0.06, -0.0525, 0.0525, 0.06, 0.0675, 0.075]


def write_vtk(path: Path, points: list[tuple[float, float, float]]) -> None:
    values = [coordinate for point in points for coordinate in point]
    header = ("# vtk DataFile Version 3.0\nfixture\nBINARY\nDATASET POLYDATA\n"
              f"POINTS {len(points)} float\n").encode("ascii")
    path.write_bytes(header + struct.pack(f">{len(values)}f", *values))


def test_authorization_is_fresh_r007_one_shot_and_zero_credit() -> None:
    value = authorization.build_authorization()
    assert value["status"] == "authorized_for_exactly_one_r007_cpu_native_preflight"
    assert value["scope_id"].endswith("R007")
    assert value["qualification_credit"] == 0
    assert value["retained_previous_failure"]["same_input_retry_forbidden"] is True
    assert value["hard_gates"]["generated_fixed_boundary_particles_exact"] == 4096
    assert value["hard_gates"]["generated_fluid_particles_exact"] == 6656
    assert value["hard_gates"]["generated_total_particles_exact"] == 10752
    assert value["hard_gates"]["native_boundary_normals_finite_and_minimum_magnitude"] == pytest.approx(0.001875)
    assert value["permissions"]["cpu_gencase"] is True and value["permissions"]["native_decode"] is True
    assert all(value["permissions"][key] is False for key in (
        "solver", "gpu", "queue", "worker", "registry", "ledger", "training", "qualification"
    ))


def test_authorization_hash_closes_all_r007_tools_and_tests() -> None:
    value = authorization.build_authorization()
    for item in value["bindings"]:
        path = LAB / item["path"]
        assert path.is_file()
        assert authorization.sha256(path) == item["sha256"]
        assert path.stat().st_size == item["bytes"]
    assert authorization.bindings_current(value)
    runner.validate_authorization(value)


def test_runner_builds_only_registered_argv_and_rejects_scope_substitution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    value = authorization.build_authorization()
    auth_path = tmp_path / "authorization.json"
    auth_path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(runner, "AUTHORIZATION", auth_path)
    plan = runner.build_execution_plan()
    assert plan["commands"]["cpu_gencase"][0].endswith("GenCase_linux64")
    assert plan["commands"]["native_decode"][0].endswith("bi4_dump")
    assert plan["commands"]["cpu_gencase"][-1] == "-save:all"
    assert plan["generated"]["control_copy"].endswith("F8_OPC_q0p500_r007_acceleration.csv")
    with pytest.raises(ValueError, match="registered F8 r007 output namespace"):
        runner.build_execution_plan(tmp_path / "wrong")
    with pytest.raises(ValueError, match="registered F8 r007 output namespace"):
        executor.run_once(tmp_path / "wrong")


def test_generated_audit_rejects_missing_top_plane_before_native_decode(tmp_path: Path) -> None:
    authorization_value = authorization.build_authorization()
    generated = tmp_path / "generated.xml"
    generated.write_text(
        '<case><particles np="10752" nb="4096" nbf="4096">'
        '<_summary><positions><posmin z="-0.075"/><posmax z="0.075"/></positions></_summary>'
        '<fixed begin="0" count="4096" mkbound="0" mk="2"/>'
        '<fluid begin="4096" count="6656" mkfluid="0" mk="1"/>'
        '</particles></case>', encoding="utf-8",
    )
    bound = tmp_path / "Bound.vtk"
    wall_planes = WALL_Z[:-1]
    wall_points = [((index % 32) * 0.0075, (index // 32) * 0.0075, z)
                   for z in wall_planes for index in range(512)]
    write_vtk(bound, wall_points)
    fluid = tmp_path / "Fluid.vtk"
    fluid_points = [(x * 0.0075, y * 0.0075, -0.045 + layer * 0.0075)
                    for layer in range(13) for y in range(16) for x in range(32)]
    write_vtk(fluid, fluid_points)
    hdp = tmp_path / "hdp.vtk"
    write_vtk(hdp, [(x, y, z) for z in (-0.04875, 0.04875)
                    for x, y in ((0.0, 0.0), (0.24, 0.0), (0.24, 0.12), (0.0, 0.12))])
    audit = executor.generated_checks(generated, bound, fluid, hdp, authorization_value)
    assert audit["checks"]["generated_z_wall_plane_particle_counts_exact"] is False
    assert audit["pass"] is False


def test_native_audit_rejects_weak_or_reversed_normals(tmp_path: Path) -> None:
    authorization_value = authorization.build_authorization()
    generated = tmp_path / "generated.xml"
    generated.write_text(
        '<case><particles np="10752" nb="4096" nbf="4096">'
        '<fixed begin="0" count="4096" mkbound="0" mk="2"/>'
        '<fluid begin="4096" count="6656" mkfluid="0" mk="1"/>'
        '</particles></case>', encoding="utf-8",
    )
    base = tmp_path / "native"
    folder = base / "PART_0000"
    folder.mkdir(parents=True)
    z = np.repeat(np.asarray(WALL_Z, dtype=np.float64), 512)
    positions = np.zeros((10752, 3), dtype=np.float64)
    positions[:4096, 2] = z
    velocities = np.zeros((10752, 3), dtype=np.float32)
    density = np.full(10752, 1000.0, dtype=np.float32)
    ids = np.arange(10752, dtype=np.uint32)
    normals = np.zeros((4096, 3), dtype=np.float32)
    normals[z < 0, 2] = 0.00375
    normals[z > 0, 2] = -0.00375
    normals.tofile(folder / "BoundNor.bin")
    ids.tofile(folder / "Idp.bin")
    positions.tofile(folder / "Posd.bin")
    velocities.tofile(folder / "Vel.bin")
    density.tofile(folder / "Rhop.bin")
    (base.with_suffix(".xml")).write_text(
        '<data><item name="JPartDataBi4"><ullong name="CaseNfixed" v="4096"/>'
        '<ullong name="CaseNmoving" v="0"/><ullong name="CaseNfloat" v="0"/>'
        '<ullong name="CaseNfluid" v="6656"/><double name="MassFluid" v="0.000421875"/>'
        '<item name="PART_0000"><uint name="Npok" v="10752"/></item></item></data>', encoding="utf-8",
    )
    good = executor.native_checks(generated, base, authorization_value)
    assert good["pass"] is True
    normals[z < 0, 2] = -0.001
    normals.tofile(folder / "BoundNor.bin")
    weak = executor.native_checks(generated, base, authorization_value)
    assert weak["checks"]["native_boundary_normals_finite_and_minimum_magnitude"] is False
    assert weak["checks"]["native_boundary_normals_point_inward"] is False


def test_executor_surface_stays_cpu_only_and_fail_closed() -> None:
    source = (LAB / "scripts/f8_r007_cpu_native_preflight_execute_v1.py").read_text(encoding="utf-8")
    assert '"solver_invoked": False' in source
    assert '"gpu_invoked": False' in source
    assert '"worker_started": False' in source
    assert "generated geometry/control gates failed before native decode" in source
    assert '"same_input_retry": False' in source


def test_authorization_writer_refuses_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "authorization.json"
    authorization.write_authorization(target)
    assert json.loads(target.read_text(encoding="utf-8"))["qualification_credit"] == 0
    with pytest.raises(FileExistsError, match="immutable F8 r007 authorization"):
        authorization.write_authorization(target)
