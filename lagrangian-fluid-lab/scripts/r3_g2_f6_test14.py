#!/usr/bin/env python3
"""Reproduce the SPHERIC Test 14 Float1 free-heave route.

This is deliberately a route/acceptance experiment, not a dataset generator.
It runs the two published Float1 release offsets at three spatial resolutions,
extracts the rigid-body centre directly from PartFloatInfo, and compares it to
the 200 Hz experimental displacement traces.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

import numpy as np

try:
    from scripts.campaign_runner import execute_attempt, require_idle_allowed_gpu
    from scripts.protocol_metrics import require_strict_time
except ModuleNotFoundError:
    from campaign_runner import execute_attempt, require_idle_allowed_gpu
    from protocol_metrics import require_strict_time


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
FLOATING_INFO = BIN / "FloatingInfo_linux64"
CASE_ROOT = CAMPAIGN / "cases" / "r3-g2-f6-test14"
ARTIFACT = CAMPAIGN / "artifacts" / "r3-g2-f6-test14"
EXTERNAL_ROOT = CAMPAIGN / "artifacts" / "w05" / "external"
EXTRACTED = EXTERNAL_ROOT / "test14"
RUN_ROOT = CAMPAIGN / "runs"
REPORT = CAMPAIGN / "r3-g2-f6-test14.json"
PLOT = CAMPAIGN / "r3-g2-f6-test14-curves.png"
ARCHIVE_URL = (
    "https://9449af45-2363-44f6-8b03-03b6b7c2aee5.usrfiles.com/archives/"
    "9449af_89e9dae6260449eb9cae8af3a3cbcf2f.zip"
)
ARCHIVE_SHA256 = "03d264db42797da73011e20418b5ffc1a2e763aa7a338c68abe4dbd997b0f8cf"
FILE_SHA256 = {
    "Float1.STL": "f859a2e487d7cafcd119ebd680113830291f784cf736e875dce0acc88ff62cb1",
    "Fl1-0p074.txt": "abdb2f41cce578598400237acd8c0c11463376bfa4210e05cbd1e8b7ee165509",
    "Fl1+0p76.txt": "2cfe025f26256ffc4c304e73a541166d055164e0e00141346a8a664615c6033e",
    "SPHERIC_TestCase14_Free_heave.pdf": "9c46438b4b8e0d38c63a98565e7a36eb9be78420dc53596acaffd0b9c3686356",
}

# Float1 dimensions and equilibrium placement are from the official Test 14
# description. The STL coordinates are millimetres with Y vertical.
FLOAT_MASS_KG = 9.75
FLOAT_COG_ABOVE_BASE_M = 0.090
EQUILIBRIUM_BASE_Z_M = 0.613
EQUILIBRIUM_COG_Z_M = EQUILIBRIUM_BASE_Z_M + FLOAT_COG_ABOVE_BASE_M
WATER_DEPTH_M = 0.8
TANK_RADIUS_M = 2.0
DAMPING_START_RADIUS_M = 1.4
TIME_MAX_S = 4.5
TIME_OUT_S = 0.01
RESOLUTIONS = {"coarse": 0.060, "medium": 0.045, "fine": 0.035}
OFFSETS = {
    "neg074": {"offset_m": -0.074, "experiment": "Fl1-0p074.txt"},
    "pos076": {"offset_m": 0.076, "experiment": "Fl1+0p76.txt"},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_external() -> None:
    """Acquire and verify the small official archive used by the route."""
    if all((EXTRACTED / name).is_file() for name in FILE_SHA256):
        for name, expected in FILE_SHA256.items():
            actual = sha256(EXTRACTED / name)
            if actual != expected:
                raise RuntimeError(f"checksum mismatch for {name}: {actual}")
        return
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    archive = EXTERNAL_ROOT / "SPHERIC_TestCase14.zip"
    if not archive.is_file() or sha256(archive) != ARCHIVE_SHA256:
        partial = archive.with_suffix(".zip.partial")
        with urllib.request.urlopen(ARCHIVE_URL, timeout=120) as response:
            partial.write_bytes(response.read())
        if sha256(partial) != ARCHIVE_SHA256:
            raise RuntimeError("downloaded Test 14 archive checksum mismatch")
        os.replace(partial, archive)
    EXTRACTED.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        by_basename = {Path(name).name: name for name in bundle.namelist() if not name.endswith("/")}
        for name in FILE_SHA256:
            if name not in by_basename:
                raise RuntimeError(f"{name} absent from official Test 14 archive")
            (EXTRACTED / name).write_bytes(bundle.read(by_basename[name]))
    fetch_external()


def records() -> list[dict]:
    output = []
    gpus = [4, 5, 6, 7]
    for offset_name, offset in OFFSETS.items():
        for level, dp in RESOLUTIONS.items():
            output.append({
                "case_id": f"R3_F6_test14_float1_{offset_name}_{level}",
                "offset_name": offset_name,
                "offset_m": offset["offset_m"],
                "experiment": offset["experiment"],
                "level": level,
                "dp": dp,
                "gpu": gpus[len(output) % len(gpus)],
                "tmax": TIME_MAX_S,
                "tout": TIME_OUT_S,
            })
    return output


def read_binary_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return normals and triangle vertices from the official binary STL."""
    content = path.read_bytes()
    if len(content) < 84:
        raise ValueError(f"invalid binary STL: {path}")
    count = struct.unpack_from("<I", content, 80)[0]
    if len(content) != 84 + count * 50:
        raise ValueError(f"unexpected binary STL length for {path}")
    normals = np.empty((count, 3), dtype=float)
    triangles = np.empty((count, 3, 3), dtype=float)
    for index in range(count):
        values = struct.unpack_from("<12fH", content, 84 + index * 50)
        normals[index] = values[:3]
        triangles[index] = np.asarray(values[3:12]).reshape(3, 3)
    return normals, triangles


def connected_triangle_components(triangles: np.ndarray) -> list[np.ndarray]:
    """Find exact edge-connected components in an STL triangle soup."""
    parent = list(range(len(triangles)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    edges: dict[tuple, list[int]] = defaultdict(list)
    for index, triangle in enumerate(triangles):
        vertices = [tuple(vertex) for vertex in triangle]
        for left, right in ((vertices[0], vertices[1]), (vertices[1], vertices[2]),
                            (vertices[2], vertices[0])):
            edges[tuple(sorted((left, right)))].append(index)
    for owners in edges.values():
        for other in owners[1:]:
            union(owners[0], other)
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(triangles)):
        components[find(index)].append(index)
    return [np.asarray(indices, dtype=int) for indices in components.values()]


def signed_mesh_volume(triangles: np.ndarray) -> float:
    return float(np.einsum(
        "ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])
    ).sum() / 6.0)


def write_world_stl(source: Path, target: Path, base_z: float) -> dict:
    """Convert millimetre X/Y(vertical)/Z STL axes to metre X/Y/Z axes.

    Performing this explicit conversion keeps the input transform auditable and
    avoids relying on undocumented composition order among GenCase drawmove,
    drawscale and drawrotate operations.
    """
    all_normals, all_triangles = read_binary_stl(source)
    components = connected_triangle_components(all_triangles)
    volumes = [signed_mesh_volume(all_triangles[indices]) for indices in components]
    # The supplied Float1 file describes a thin physical shell: one outer and
    # one oppositely wound inner closed surface. SPH boundary particles must
    # represent the displaced outer hull, not the wall material or ambiguous
    # nested autofill volume.
    selected = components[int(np.argmax(np.abs(volumes)))]
    normals, triangles = all_normals[selected], all_triangles[selected]
    world = np.empty_like(triangles)
    world[:, :, 0] = (triangles[:, :, 0] - 150.0) / 1000.0
    world[:, :, 1] = (150.0 - triangles[:, :, 2]) / 1000.0
    world[:, :, 2] = base_z + triangles[:, :, 1] / 1000.0
    world_normals = np.column_stack((normals[:, 0], -normals[:, 2], normals[:, 1]))
    length = np.linalg.norm(world_normals, axis=1)
    nonzero = length > 0
    world_normals[nonzero] /= length[nonzero, None]
    with target.open("w") as stream:
        stream.write("solid Float1_world\n")
        for normal, triangle in zip(world_normals, world):
            stream.write(f"  facet normal {normal[0]:.9g} {normal[1]:.9g} {normal[2]:.9g}\n")
            stream.write("    outer loop\n")
            for vertex in triangle:
                stream.write(f"      vertex {vertex[0]:.9g} {vertex[1]:.9g} {vertex[2]:.9g}\n")
            stream.write("    endloop\n  endfacet\n")
        stream.write("endsolid Float1_world\n")
    return {
        "source_triangles": len(all_triangles),
        "source_connected_components": len(components),
        "source_component_signed_volumes_m3": [value / 1e9 for value in volumes],
        "selected_outer_triangles": len(triangles),
        "selected_outer_volume_m3": abs(signed_mesh_volume(triangles)) / 1e9,
        "transformed_stl_bbox_min_m": world.reshape(-1, 3).min(axis=0).tolist(),
        "transformed_stl_bbox_max_m": world.reshape(-1, 3).max(axis=0).tolist(),
        "transformed_stl_sha256": sha256(target),
    }


def environment() -> dict[str, str]:
    value = os.environ.copy()
    value["LD_LIBRARY_PATH"] = f"{BIN}:{value.get('LD_LIBRARY_PATH', '')}"
    return value


def definition_text(record: dict) -> str:
    base_z = EQUILIBRIUM_BASE_Z_M + record["offset_m"]
    center_z = EQUILIBRIUM_COG_Z_M + record["offset_m"]
    stl = f"../../artifacts/r3-g2-f6-test14/{record['case_id']}/generated/Float1_world.stl"
    return f'''<?xml version="1.0" encoding="UTF-8" ?>
<case>
  <casedef>
    <constantsdef>
      <lattice bound="1" fluid="1" />
      <gravity x="0" y="0" z="-9.81" />
      <rhop0 value="1000" />
      <rhopgradient value="2" />
      <hswl value="0" auto="true" />
      <gamma value="7" />
      <speedsystem value="0" auto="true" />
      <coefsound value="20" />
      <speedsound value="0" auto="true" />
      <coefh value="1.0" />
      <cflnumber value="0.2" />
    </constantsdef>
    <mkconfig boundcount="241" fluidcount="9" />
    <geometry>
      <definition dp="{record['dp']:.6f}">
        <pointref x="0" y="0" z="0" />
        <pointmin x="-2.2" y="-2.2" z="-0.2" />
        <pointmax x="2.2" y="2.2" z="1.4" />
      </definition>
      <commands>
        <mainlist>
          <setshapemode>real | dp | bound</setshapemode>
          <setdrawmode mode="full" />
          <setmkbound mk="0" />
          <drawcylinder radius="{TANK_RADIUS_M}" mask="2">
            <point x="0" y="0" z="0" />
            <point x="0" y="0" z="1.10" />
            <layers vdp="0,1,2" />
          </drawcylinder>
          <setmkbound mk="10" />
          <drawfilestl file="{stl}" autofill="true" />
          <setmkfluid mk="0" />
          <setboxlimitmode mode="full" />
          <fillbox x="0.8" y="0" z="0.4">
            <modefill>void</modefill>
            <point x="-2.0" y="-2.0" z="0" />
            <size x="4.0" y="4.0" z="{WATER_DEPTH_M}" />
          </fillbox>
        </mainlist>
      </commands>
    </geometry>
    <floatings>
      <floating mkbound="10">
        <massbody value="{FLOAT_MASS_KG}" />
        <center x="0" y="0" z="{center_z:.6f}" />
        <translationDOF x="0" y="0" z="1" />
        <rotationDOF x="0" y="0" z="0" />
      </floating>
    </floatings>
  </casedef>
  <execution>
    <special>
      <damping>
        <dampingcylinder active="true">
          <point1 x="0" y="0" z="0" />
          <point2 x="0" y="0" z="1.2" />
          <limitmin radius="{DAMPING_START_RADIUS_M}" />
          <limitmax radius="{TANK_RADIUS_M}" />
          <overlimit value="0.1" />
          <redumax value="10" />
          <factorxyz x="1" y="1" z="1" />
        </dampingcylinder>
      </damping>
    </special>
    <parameters>
      <parameter key="SavePosDouble" value="2" />
      <parameter key="Boundary" value="1" />
      <parameter key="StepAlgorithm" value="2" />
      <parameter key="Kernel" value="2" />
      <parameter key="ViscoTreatment" value="1" />
      <parameter key="Visco" value="0.01" />
      <parameter key="DensityDT" value="3" />
      <parameter key="DensityDTvalue" value="0.1" />
      <parameter key="Shifting" value="0" />
      <parameter key="RigidAlgorithm" value="1" />
      <parameter key="FtPause" value="0" />
      <parameter key="CoefDtMin" value="0.05" />
      <parameter key="TimeMax" value="{record['tmax']}" />
      <parameter key="TimeOut" value="{record['tout']}" />
      <parameter key="RhopOutMin" value="700" />
      <parameter key="RhopOutMax" value="1300" />
      <parameter key="MinFluidStop" value="0" />
      <parameter key="WrnPartsOut" value="1" />
      <simulationdomain>
        <posmin x="default" y="default" z="default" />
        <posmax x="default" y="default" z="1.4" />
      </simulationdomain>
    </parameters>
  </execution>
</case>
'''


def vtk_binary_points(path: Path) -> np.ndarray:
    """Read the leading big-endian POINTS payload written by GenCase."""
    content = path.read_bytes()
    match = re.search(br"POINTS\s+(\d+)\s+(float|double)\r?\n", content)
    if not match:
        raise ValueError(f"POINTS header missing from {path}")
    count = int(match.group(1))
    dtype = ">f4" if match.group(2) == b"float" else ">f8"
    start = match.end()
    return np.frombuffer(content, dtype=dtype, count=count * 3, offset=start).reshape(count, 3).astype(float)


def generated_counts(prefix: Path) -> dict:
    root = ET.parse(prefix.with_suffix(".xml")).getroot()
    particles = root.find(".//particles")
    floating = root.find(".//particles/floating")
    fluid = root.find(".//particles/fluid")
    if particles is None or floating is None or fluid is None:
        raise ValueError("generated XML is missing floating/fluid particle blocks")
    bound_points = vtk_binary_points(prefix.with_name(prefix.name + "_Bound.vtk"))
    begin = int(floating.get("begin"))
    count = int(floating.get("count"))
    body = bound_points[begin:begin + count]
    return {
        "total_particles": int(particles.get("np")),
        "boundary_particles": int(particles.get("nb")),
        "floating_particles": count,
        "fluid_particles": int(fluid.get("count")),
        "floating_bbox_min_m": body.min(axis=0).tolist(),
        "floating_bbox_max_m": body.max(axis=0).tolist(),
        "floating_particle_centroid_m": body.mean(axis=0).tolist(),
    }


def validate_preflight(record: dict, counts: dict) -> None:
    lower = np.asarray(counts["floating_bbox_min_m"])
    upper = np.asarray(counts["floating_bbox_max_m"])
    expected_base = EQUILIBRIUM_BASE_Z_M + record["offset_m"]
    size = upper - lower
    errors = []
    if counts["floating_particles"] < 20:
        errors.append("fewer than 20 floating particles")
    if not np.allclose(size[:2], [0.30, 0.30], atol=record["dp"] * 2):
        errors.append(f"unexpected horizontal extent {size[:2].tolist()}")
    if not np.isclose(size[2], 0.29, atol=record["dp"] * 2):
        errors.append(f"unexpected vertical extent {size[2]}")
    if abs(lower[2] - expected_base) > record["dp"] * 1.5:
        errors.append(f"unexpected base z {lower[2]} vs {expected_base}")
    if errors:
        raise RuntimeError(f"{record['case_id']} geometry preflight failed: {errors}")


def prepare(selected: list[dict]) -> list[dict]:
    fetch_external()
    CASE_ROOT.mkdir(parents=True, exist_ok=True)
    matrix = []
    for record in selected:
        definition = CASE_ROOT / f"{record['case_id']}_Def.xml"
        definition.write_text(definition_text(record))
        generated = ARTIFACT / record["case_id"] / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        transform = write_world_stl(
            EXTRACTED / "Float1.STL", generated / "Float1_world.stl",
            EQUILIBRIUM_BASE_Z_M + record["offset_m"],
        )
        prefix = generated / record["case_id"]
        proc = subprocess.run(
            [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
            cwd=CASE_ROOT, env=environment(), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        (generated / "gencase.stdout.log").write_text(proc.stdout)
        if proc.returncode or not prefix.with_suffix(".xml").is_file():
            raise RuntimeError(f"GenCase failed for {record['case_id']}: {proc.stdout[-2000:]}")
        counts = generated_counts(prefix)
        validate_preflight(record, counts)
        matrix.append({key: record[key] for key in (
            "case_id", "offset_name", "offset_m", "experiment", "level", "dp", "gpu", "tmax", "tout"
        )} | transform | counts)
    path = CASE_ROOT / "matrix.json"
    known = {item["case_id"]: item for item in json.loads(path.read_text())} if path.exists() else {}
    known.update({item["case_id"]: item for item in matrix})
    path.write_text(json.dumps(sorted(known.values(), key=lambda item: item["case_id"]), indent=2) + "\n")
    return matrix


def allowed_uuids() -> list[str]:
    inventory = json.loads((CAMPAIGN / "w00-inventory.json").read_text())
    return inventory["execution_policy"]["allowed_gpu_uuids"]


def run_one(record: dict) -> dict:
    launch_gpu = require_idle_allowed_gpu(record["gpu"], allowed_uuids())
    prefix = ARTIFACT / record["case_id"] / "generated" / record["case_id"]
    result = execute_attempt(
        record["case_id"],
        [str(SOLVER), f"-gpu:{record['gpu']}", str(prefix), "{output}"],
        RUN_ROOT, cwd=prefix.parent, env=environment(),
        evidence_glob="data/Part_*.bi4", required_text="Finished execution (code=0)",
    )
    result["gpu_at_launch"] = launch_gpu
    if result["status"] != "completed":
        raise RuntimeError(f"solver failed for {record['case_id']}: {result['attempt_directory']}")
    return result


def run(selected: list[dict]) -> list[dict]:
    output = []
    for start in range(0, len(selected), 4):
        batch = selected[start:start + 4]
        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            output.extend(pool.map(run_one, batch))
    return output


def latest(case_id: str) -> Path:
    return Path(json.loads((RUN_ROOT / case_id / "latest.json").read_text())["attempt_directory"])


def extract_one(record: dict) -> Path:
    attempt = latest(record["case_id"])
    output = attempt / "floating"
    output.mkdir(exist_ok=True)
    target = output / "Float1"
    proc = subprocess.run(
        [str(FLOATING_INFO), "-dirdata", str(attempt / "data"), "-savedata", str(target), "-csvsep:1"],
        cwd=attempt, env=environment(), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    (output / "floatinginfo.stdout.log").write_text(proc.stdout)
    matches = list(output.glob("Float1_mk*.csv"))
    if proc.returncode or len(matches) != 1:
        raise RuntimeError(f"FloatingInfo failed for {record['case_id']}: {proc.stdout[-2000:]}")
    return matches[0]


def extract(selected: list[dict]) -> None:
    for record in selected:
        extract_one(record)


def load_experiment(record: dict) -> tuple[np.ndarray, np.ndarray]:
    data = np.loadtxt(EXTRACTED / record["experiment"])
    return data[:, 0], data[:, 1] / 1000.0


def load_simulation(record: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    attempt = latest(record["case_id"])
    matches = list((attempt / "floating").glob("Float1_mk*.csv"))
    if len(matches) != 1:
        raise FileNotFoundError(f"run extract first for {record['case_id']}")
    with matches[0].open(newline="") as stream:
        rows = list(csv.DictReader(stream, skipinitialspace=True))
    time = np.asarray([float(row["time [s]"]) for row in rows])
    heave = np.asarray([float(row["heave [m]"]) for row in rows])
    center_z = np.asarray([float(row["center.z [m]"]) for row in rows])
    require_strict_time(time)
    return time, record["offset_m"] + heave, center_z


def dominant_period(time: np.ndarray, signal: np.ndarray) -> float | None:
    grid = np.arange(time[0], time[-1], 0.005)
    values = np.interp(grid, time, signal)
    values = values - np.polyval(np.polyfit(grid, values, 1), grid)
    spectrum = np.abs(np.fft.rfft(values))
    frequency = np.fft.rfftfreq(len(grid), grid[1] - grid[0])
    band = (frequency >= 0.5) & (frequency <= 2.5)
    if not np.any(band):
        return None
    selected = np.flatnonzero(band)[int(np.argmax(spectrum[band]))]
    return float(1.0 / frequency[selected])


def extrema_amplitudes(time: np.ndarray, signal: np.ndarray) -> list[dict]:
    grid = np.arange(time[0], time[-1] + 1e-9, 0.005)
    values = np.interp(grid, time, signal)
    # A short moving average suppresses the millimetric measurement noise.
    values = np.convolve(values, np.ones(5) / 5, mode="same")
    candidates = np.flatnonzero(np.diff(np.sign(np.diff(values))) != 0) + 1
    candidates = candidates[(grid[candidates] >= 0.15) & (grid[candidates] <= time[-1] - 0.05)]
    chosen = []
    for index in sorted(candidates, key=lambda idx: abs(values[idx]), reverse=True):
        if all(abs(grid[index] - grid[prior]) >= 0.30 for prior in chosen):
            chosen.append(int(index))
    chosen = sorted(chosen)[:8]
    return [{"time_s": float(grid[index]), "displacement_m": float(values[index]),
             "absolute_amplitude_m": float(abs(values[index]))} for index in chosen]


def internal_timestep(record: dict) -> dict:
    log = (latest(record["case_id"]) / "process.stdout.log").read_text(errors="replace")
    match = re.search(r"Steps of simulation\.+:\s*([0-9,]+)", log)
    if not match:
        raise ValueError(f"solver step count absent for {record['case_id']}")
    steps = int(match.group(1).replace(",", ""))
    return {"adaptive_solver_steps": steps, "mean_internal_dt_s": record["tmax"] / steps}


def audit_case(record: dict) -> tuple[dict, np.ndarray, np.ndarray]:
    exp_time, exp_displacement = load_experiment(record)
    sim_time, sim_displacement, center_z = load_simulation(record)
    sim_on_exp = np.interp(exp_time, sim_time, sim_displacement)
    residual = sim_on_exp - exp_displacement
    tail = exp_time >= exp_time[-1] - 1.0
    initial_center_expected = EQUILIBRIUM_COG_Z_M + record["offset_m"]
    result = {
        "dp_m": record["dp"],
        "simulation_frames": len(sim_time),
        "experimental_samples": len(exp_time),
        "experiment_cadence_s": float(np.median(np.diff(exp_time))),
        "simulation_saved_cadence_s": float(np.median(np.diff(sim_time))),
        "comparison_alignment": "simulation linearly interpolated at experimental timestamps; no time shift or amplitude fit",
        "initial_offset_error_m": float(sim_displacement[0] - exp_displacement[0]),
        "initial_center_z_error_m": float(center_z[0] - initial_center_expected),
        "rmse_m": float(np.sqrt(np.mean(residual ** 2))),
        "normalized_rmse_by_abs_initial_offset": float(
            np.sqrt(np.mean(residual ** 2)) / abs(record["offset_m"])
        ),
        "mae_m": float(np.mean(np.abs(residual))),
        "correlation": float(np.corrcoef(sim_on_exp, exp_displacement)[0, 1]),
        "last_1s_simulation_mean_m": float(np.mean(sim_on_exp[tail])),
        "last_1s_experiment_mean_m": float(np.mean(exp_displacement[tail])),
        "last_1s_mean_bias_m": float(np.mean(sim_on_exp[tail] - exp_displacement[tail])),
        "experiment_dominant_period_s": dominant_period(exp_time, exp_displacement),
        "simulation_dominant_period_s": dominant_period(sim_time, sim_displacement),
        "experiment_extrema": extrema_amplitudes(exp_time, exp_displacement),
        "simulation_extrema": extrema_amplitudes(sim_time, sim_displacement),
        **internal_timestep(record),
    }
    return result, exp_time, sim_on_exp


def save_plot(curves: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True, constrained_layout=True)
    colors = {"coarse": "#d95f02", "medium": "#7570b3", "fine": "#1b9e77"}
    for axis, offset_name in zip(axes, OFFSETS):
        record = next(item for item in records() if item["offset_name"] == offset_name)
        exp_time, exp_displacement = load_experiment(record)
        axis.plot(exp_time, exp_displacement * 1000, color="black", linewidth=1.8,
                  label="experiment (200 Hz)")
        for level in RESOLUTIONS:
            time, values = curves[(offset_name, level)]
            axis.plot(time, values * 1000, color=colors[level], linewidth=1.1,
                      label=f"{level}, dp={RESOLUTIONS[level]:.3f} m")
        axis.axhline(0, color="#999999", linewidth=0.6)
        axis.set_ylabel("heave from equilibrium [mm]")
        axis.set_title(f"Float1 release offset {OFFSETS[offset_name]['offset_m'] * 1000:+.0f} mm")
        axis.grid(alpha=0.2)
    axes[0].legend(ncol=2, fontsize=8)
    axes[-1].set_xlabel("time [s]")
    figure.suptitle("SPHERIC Test 14 route audit — current DBC proxy is not accepted")
    figure.savefig(PLOT, dpi=160)
    plt.close(figure)


def analyze(run_results: list[dict] | None = None) -> dict:
    fetch_external()
    by_offset = {}
    curves = {}
    for offset_name in OFFSETS:
        cases = {}
        for record in [item for item in records() if item["offset_name"] == offset_name]:
            metrics, exp_time, sim_curve = audit_case(record)
            cases[record["level"]] = metrics
            curves[(offset_name, record["level"])] = (exp_time, sim_curve)
        comparisons = {}
        for left, right in (("coarse", "medium"), ("medium", "fine")):
            time_left, curve_left = curves[(offset_name, left)]
            time_right, curve_right = curves[(offset_name, right)]
            if not np.array_equal(time_left, time_right):
                raise ValueError("external comparison grids differ")
            comparisons[f"{left}_to_{right}"] = {
                "curve_rmse_m": float(np.sqrt(np.mean((curve_left - curve_right) ** 2))),
                "external_rmse_change_m": cases[right]["rmse_m"] - cases[left]["rmse_m"],
                "dominant_period_change_s": (
                    cases[right]["simulation_dominant_period_s"] - cases[left]["simulation_dominant_period_s"]
                ),
            }
        by_offset[offset_name] = {
            "published_initial_offset_m": OFFSETS[offset_name]["offset_m"],
            "experiment_file": OFFSETS[offset_name]["experiment"],
            "resolutions": cases,
            "resolution_change": comparisons,
        }
    if run_results is None:
        run_results = [json.loads((RUN_ROOT / record["case_id"] / "latest.json").read_text()) for record in records()]
    compact = [{
        "case_id": item["case_id"], "attempt_id": item["attempt_id"], "status": item["status"],
        "elapsed_seconds": item["elapsed_seconds"], "saved_parts": len(item["evidence_files"]),
    } for item in run_results]
    rmse_fine = [by_offset[name]["resolutions"]["fine"]["rmse_m"] for name in OFFSETS]
    convergence = []
    for name in OFFSETS:
        changes = by_offset[name]["resolution_change"]
        convergence.append(
            changes["medium_to_fine"]["curve_rmse_m"] < changes["coarse_to_medium"]["curve_rmse_m"]
        )
    matrix = json.loads((CASE_ROOT / "matrix.json").read_text())
    particle_phase_span = {}
    for level in RESOLUTIONS:
        values = [item["floating_particles"] for item in matrix if item["level"] == level]
        particle_phase_span[level] = (max(values) - min(values)) / float(np.mean(values))
    all_attempts = []
    for record in records():
        for attempt in (RUN_ROOT / record["case_id"] / "attempts").glob("*.complete/attempt.json"):
            all_attempts.append(json.loads(attempt.read_text()))
    save_plot(curves)
    payload = {
        "schema_version": 1,
        "scope": "true-3D SPHERIC Test 14 Float1, two published offsets by three spatial resolutions",
        "execution_status": "completed",
        "scientific_acceptance": "rejected_current_DBC_proxy",
        "acceptance_reason": (
            "The physical geometry/data path and six-case comparison are executable, but the response has a large "
            "positive equilibrium bias and no resolution stability. The 2 m-radius damped tank is also a computational "
            "proxy and the finest dp resolves the 0.3 m body with only about 8.6 spacings."
        ),
        "experiment": {
            "source_page": "https://www.spheric-sph.org/tests/test-14",
            "archive_url": ARCHIVE_URL,
            "archive_sha256": ARCHIVE_SHA256,
            "file_sha256": FILE_SHA256,
            "water_depth_m": WATER_DEPTH_M,
            "float": "Float1 round-base body",
            "mass_kg": FLOAT_MASS_KG,
            "cog_above_base_m": FLOAT_COG_ABOVE_BASE_M,
            "published_sampling_hz": 200,
            "published_natural_period_s": 0.87,
        },
        "numerical_configuration": {
            "solver": "DualSPHysics 5.4 CPU/GPU binary release",
            "boundary": "DBC",
            "tank_radius_m": TANK_RADIUS_M,
            "radial_damping_start_m": DAMPING_START_RADIUS_M,
            "water_depth_m": WATER_DEPTH_M,
            "float_motion": "heave translation only; surge, sway and all rotations constrained",
            "time_max_s": TIME_MAX_S,
            "spatial_resolution_m": RESOLUTIONS,
            "saved_output_cadence_s": TIME_OUT_S,
            "internal_timestep": "adaptive and reported per case",
        },
        "geometry_preflight": {
            "source_stl_interpretation": (
                "official Float1 STL is a watertight physical shell with separate outer and oppositely-wound inner surfaces"
            ),
            "generation_decision": (
                "select the largest-volume connected outer surface, transform mm X/Y(vertical)/Z to m X/Y/Z, "
                "then autofill the displaced outer hull before void-filling water"
            ),
            "source_connected_components": matrix[0]["source_connected_components"],
            "source_component_signed_volumes_m3": matrix[0]["source_component_signed_volumes_m3"],
            "selected_outer_volume_m3": matrix[0]["selected_outer_volume_m3"],
            "floating_particle_count_relative_span_between_offsets": particle_phase_span,
            "cases": [{key: item[key] for key in (
                "case_id", "dp", "offset_m", "floating_particles", "fluid_particles",
                "transformed_stl_bbox_min_m", "transformed_stl_bbox_max_m",
                "floating_bbox_min_m", "floating_bbox_max_m", "transformed_stl_sha256"
            )} for item in matrix],
        },
        "offsets": by_offset,
        "run_results": compact,
        "resource_summary": {
            "successful_runs": len(compact),
            "solver_gpu_seconds": sum(item["elapsed_seconds"] for item in compact),
            "successful_attempts_including_short_preflight": len(all_attempts),
            "gpu_seconds_including_short_preflight": sum(item["elapsed_seconds"] for item in all_attempts),
        },
        "diagnostic_summary": {
            "resolution_curve_change_decreases_for_both_offsets": all(convergence),
            "fine_external_rmse_range_m": [min(rmse_fine), max(rmse_fine)],
        },
        "open_blockers": [
            "eliminate the 70-120 mm positive late-time equilibrium bias before any acceptance claim",
            "repeat domain-radius/damping sensitivity against a substantially larger basin",
            "extend to dp <= 0.02 m before claiming body-surface resolution convergence",
            "compare DBC with a verified mDBC geometry-normal setup",
            "independently verify the STL vertical transform, outer-hull coupling and equilibrium base placement",
            "control the 5-10% floating-particle count change caused by release-height lattice phase",
            "Float2 -0.088 m remains an out-of-sample body-geometry extension",
        ],
        "plot": PLOT.name,
    }
    REPORT.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("fetch", "prepare", "run", "extract", "analyze", "all"),
                        nargs="?", default="all")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--preflight-tmax", type=float,
                        help="override TimeMax in generated definitions for a short route check")
    args = parser.parse_args()
    known = {record["case_id"]: record for record in records()}
    unknown = set(args.cases or ()) - set(known)
    if unknown:
        parser.error(f"unknown cases: {sorted(unknown)}")
    selected = [known[name].copy() for name in args.cases] if args.cases else [item.copy() for item in records()]
    if args.preflight_tmax is not None:
        for record in selected:
            record["tmax"] = args.preflight_tmax
    run_results = None
    if args.action in ("fetch", "all"):
        fetch_external()
    if args.action in ("prepare", "all"):
        prepare(selected)
    if args.action in ("run", "all"):
        run_results = run(selected)
    if args.action in ("extract", "all"):
        extract(selected)
    if args.action in ("analyze", "all"):
        if args.preflight_tmax is not None:
            parser.error("analyze is not valid with --preflight-tmax")
        analyze(run_results)


if __name__ == "__main__":
    main()
