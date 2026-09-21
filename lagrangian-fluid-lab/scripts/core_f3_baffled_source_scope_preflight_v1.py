#!/usr/bin/env python3
"""CPU/native preflight for the independent F3 internal-baffle source scope.

The current Core F3 source handoff is a prepared-only, plain finite tank with a
prescribed acceleration control.  This module prepares one fresh anchor for a
different physical boundary mechanism: a fixed internal baffle represented by
``mkbound=1``.  It only copies and rewrites the legacy *definition* as a
provenance input, then runs GenCase and the native initial-frame decoder.  It
never runs DualSPHysics, starts a GPU, submits a queue item, or mutates a
ledger/registry.

The generated ``prepared.json`` is intentionally fail-closed.  It is an input
preflight artifact for a later root review; it carries no qualification claim
and cannot credit a matrix row by itself.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

try:
    from scripts import core_cfd
except ModuleNotFoundError:  # pragma: no cover - direct invocation
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import core_cfd


LAB = Path(__file__).resolve().parents[1]
SCHEMA = "core.f3.baffled_source_scope.preflight.v1"
FAMILY = "F3"
SCOPE_ID = "F3_baffle_exchange_native_mdbc_x_v1"
REVISION_ID = "F3_baffle_exchange_native_mdbc_v1"
QUALIFICATION_CLAIM = "none; independent source-scope preflight only"
BASE_DEFINITION_REL = "cases/F3/F3_baffled_slosh/F3_baffled_slosh_Def.xml"
SOLVER_REL = "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
GENCASE_REL = "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DECODER_REL = "campaigns/l1-resume/artifacts/bi4_dump"
TIME_MAX_S = 8.35
DEFAULT_OUTPUT_INTERVAL_S = 0.01
DEFAULT_CFL = 0.05
RHO0 = 1000.0
# The legacy probe used a .04 m lattice with a 1.0 x .32 x .25 m fill and a
# .04 m baffle.  The independent scope uses a thin, mass-resolved fill and a
# .03 m baffle.  The remaining fluid length is .87 m, divisible by all three
# registered resolutions (.01, .0075 and .005 m), so native mass is closed
# without rescaling at every matrix resolution.
BASE_FLUID_LOW = np.asarray([0.1, 0.04, 0.04], dtype=np.float64)
BASE_FLUID_SIZE = np.asarray([0.9, 0.18, 0.09], dtype=np.float64)
BAFFLE_LOW = np.asarray([0.58, 0.04, 0.0], dtype=np.float64)
BAFFLE_SIZE = np.asarray([0.03, 0.18, 0.19], dtype=np.float64)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"immutable output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(path)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lab_path(lab_root: Path, relative: str) -> Path:
    return (Path(lab_root).resolve() / relative).resolve()


def _environment(lab_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    binary_dir = _lab_path(lab_root, "vendor/official/DualSPHysics_v5.4/bin/linux")
    env["LD_LIBRARY_PATH"] = str(binary_dir) + ":" + env.get("LD_LIBRARY_PATH", "")
    env.setdefault("OMP_NUM_THREADS", "2")
    return env


def amplitude_from_q(q: float) -> float:
    """Map the new initial-impulse axis to amplitudes absent from the legacy probe."""
    q = float(q)
    if not math.isfinite(q) or not 0.0 <= q <= 1.0:
        raise ValueError("q must be finite and in [0, 1]")
    # The legacy .04 m probe used 0.65 m/s.  The new axis deliberately uses
    # [0.45, 1.05] m/s, so no candidate row repeats that old input.
    return 0.45 + 0.60 * q


def _parameter(root: ET.Element, key: str, value: float | int | str) -> None:
    parameters = root.find("./execution/parameters")
    if parameters is None:
        raise ValueError("definition has no execution parameters")
    node = parameters.find(f"parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(parameters, "parameter", key=key)
    node.set("value", str(value))


def _rewrite_definition(source: Path, target: Path, *, dp_m: float, amplitude: float,
                        output_interval_s: float, time_max_s: float, cfl: float) -> None:
    if target.exists():
        raise FileExistsError(target)
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError("baffled definition has no geometry definition")
    definition.set("dp", f"{dp_m:.17g}")
    # The legacy .04 m probe had no point reference, which makes GenCase
    # include both box endpoints at finer resolutions.  A half-cell pointref
    # is part of this new source recipe and makes the declared native lattice
    # explicit and mass-resolved.
    pointref = definition.find("pointref")
    if pointref is None:
        pointref = ET.Element("pointref")
        definition.insert(0, pointref)
    for axis in "xyz":
        pointref.set(axis, f"{dp_m / 2.0:.17g}")
    drawboxes = root.findall("./casedef/geometry/commands/mainlist/drawbox")
    if len(drawboxes) != 4:
        raise ValueError("baffled definition must contain fluid, outer, void and baffle drawboxes")

    def set_box(node: ET.Element, low: np.ndarray, size: np.ndarray) -> None:
        point = node.find("point")
        extent = node.find("size")
        if point is None or extent is None:
            raise ValueError("drawbox is missing point/size")
        for axis, value in zip("xyz", low):
            point.set(axis, f"{float(value):.17g}")
        for axis, value in zip("xyz", size):
            extent.set(axis, f"{float(value):.17g}")

    # GenCase's solid-box contract samples the declared points inclusively.
    # Write the cell-centre range explicitly so the physical half-open fill
    # remains exactly BASE_FLUID_SIZE at every registered dp.
    counts = np.rint(BASE_FLUID_SIZE / dp_m).astype(int)
    if not np.allclose(counts * dp_m, BASE_FLUID_SIZE, rtol=0.0, atol=1e-12):
        raise ValueError("registered dp does not resolve the declared fluid box")
    set_box(drawboxes[0], BASE_FLUID_LOW + dp_m / 2.0, (counts - 1) * dp_m)
    # The void precursor follows the exact fluid-cell columns intersecting the
    # baffle.  The boundary drawbox stays physical and is audited separately.
    fluid_first = BASE_FLUID_LOW + dp_m / 2.0
    baffle_first = np.ceil((BAFFLE_LOW - fluid_first) / dp_m - 1e-10).astype(int)
    baffle_stop = np.ceil((BAFFLE_LOW + BAFFLE_SIZE - fluid_first) / dp_m - 1e-10).astype(int)
    baffle_counts = baffle_stop - baffle_first
    if np.any(baffle_counts <= 0):
        raise ValueError("registered dp does not resolve the internal baffle")
    void_low = fluid_first + baffle_first * dp_m
    void_size = (baffle_counts - 1) * dp_m
    set_box(drawboxes[2], void_low, void_size)
    set_box(drawboxes[3], BAFFLE_LOW, BAFFLE_SIZE)
    initials = root.find("./casedef/initials")
    if initials is None:
        raise ValueError("baffled definition has no initial state")
    velocities = initials.findall("velocity")
    if len(velocities) != 1 or velocities[0].get("mkfluid") != "0":
        raise ValueError("expected one mkfluid=0 initial velocity")
    velocity = velocities[0]
    velocity.set("x", f"{amplitude:.17g}")
    velocity.set("y", "0")
    velocity.set("z", "0")
    _parameter(root, "SavePosDouble", 2)
    _parameter(root, "ViscoTreatment", 1)
    _parameter(root, "Visco", 0.05)
    _parameter(root, "ViscoBoundFactor", 1)
    _parameter(root, "Shifting", 0)
    _parameter(root, "CoefDtMin", 0.05)
    _parameter(root, "TimeMax", f"{time_max_s:.17g}")
    _parameter(root, "TimeOut", f"{output_interval_s:.17g}")
    _parameter(root, "Boundary", 2)
    _parameter(root, "SlipMode", 2)
    _parameter(root, "NoPenetration", 1)
    cfl_node = root.find(".//cflnumber")
    if cfl_node is None:
        raise ValueError("definition has no cflnumber")
    cfl_node.set("value", f"{cfl:.17g}")
    # The default domain is tied to the low-resolution probe.  This explicit
    # computational domain gives the later runtime audit a stable contract;
    # it does not alter the physical tank or baffle geometry.
    domain = root.find("./execution/parameters/simulationdomain")
    if domain is None:
        parameters = root.find("./execution/parameters")
        if parameters is None:
            raise ValueError("definition has no execution parameter block")
        domain = ET.SubElement(parameters, "simulationdomain")
    domain.clear()
    ET.SubElement(domain, "posmin", x="-0.40", y="-0.30", z="-0.30")
    ET.SubElement(domain, "posmax", x="1.60", y="0.70", z="1.60")
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(target, encoding="utf-8", xml_declaration=True)


def _assert_baffle_contract(definition: Path, *, dp_m: float) -> dict[str, Any]:
    root = ET.parse(definition).getroot()
    drawboxes = root.findall("./casedef/geometry/commands/mainlist/drawbox")
    if len(drawboxes) != 4:
        raise ValueError(f"expected fluid, outer-wall, void and baffle source boxes, got {len(drawboxes)}")
    fluid = drawboxes[0]
    outer = drawboxes[1]
    void = drawboxes[2]
    baffle = drawboxes[3]
    def box(node: ET.Element) -> tuple[str, np.ndarray, np.ndarray]:
        fill = " ".join((node.findtext("boxfill") or "").split())
        point = node.find("point")
        size = node.find("size")
        if point is None or size is None:
            raise ValueError("drawbox is missing point or size")
        low = np.asarray([float(point.get(axis)) for axis in "xyz"], dtype=np.float64)
        extent = np.asarray([float(size.get(axis)) for axis in "xyz"], dtype=np.float64)
        return fill, low, extent
    fluid_fill, fluid_low, fluid_size = box(fluid)
    outer_fill, outer_low, outer_size = box(outer)
    baffle_fill, baffle_low, baffle_size = box(baffle)
    if fluid_fill != "solid":
        raise ValueError("fluid volume is not a solid fill")
    if not np.allclose(fluid_low - dp_m / 2.0, BASE_FLUID_LOW, rtol=0.0, atol=1e-12):
        raise ValueError("fluid cell-centre range does not bind the declared low corner")
    if not np.allclose(fluid_size + dp_m, BASE_FLUID_SIZE, rtol=0.0, atol=1e-12):
        raise ValueError("fluid cell-centre range does not bind the declared size")
    if outer_fill != "bottom | left | right | front | back":
        raise ValueError("outer boundary is not finite with an open top")
    if "solid" not in " ".join((void.findtext("boxfill") or "").split()):
        raise ValueError("the baffle void precursor is missing")
    if baffle_fill != "top | left | right | front | back":
        raise ValueError("internal baffle must be a solid top/side/front/back wall")
    if not np.allclose(baffle_low, BAFFLE_LOW) or not np.allclose(baffle_size, BAFFLE_SIZE):
        raise ValueError("internal baffle geometry changed")
    mkbound = root.findall("./casedef/geometry/commands/mainlist/setmkbound")
    if [node.get("mk") for node in mkbound] != ["0", "1"]:
        raise ValueError("expected outer mkbound=0 then internal mkbound=1")
    return {
        "fluid_box_low_m": fluid_low.tolist(),
        "fluid_box_size_m": fluid_size.tolist(),
        "outer_wall_low_m": outer_low.tolist(),
        "outer_wall_size_m": outer_size.tolist(),
        "outer_wall_fill": outer_fill,
        "internal_baffle_low_m": baffle_low.tolist(),
        "internal_baffle_size_m": baffle_size.tolist(),
        "internal_baffle_fill": baffle_fill,
        "mkbound_roles": {"0": "finite_outer_tank_open_top", "1": "internal_baffle"},
        "physical_geometry_changed_relative_to_plain_source": True,
    }


def _fluid_count_from_generated(generated: Path) -> tuple[int, int, int]:
    root = ET.parse(generated).getroot()
    particles = root.find("./execution/particles")
    if particles is None:
        raise ValueError("GenCase output has no particle summary")
    fixed = particles.findall("fixed")
    fluid = particles.findall("fluid")
    if len(fluid) != 1 or len(fixed) < 2:
        raise ValueError("baffle source must contain one fluid block and two boundary mk blocks")
    boundary = sum(int(node.get("count")) for node in fixed)
    fluid_count = int(fluid[0].get("count"))
    total = int(particles.get("np"))
    if total != boundary + fluid_count:
        raise ValueError("GenCase particle counts do not close")
    if fluid[0].get("mkfluid") != "0":
        raise ValueError("unexpected fluid label")
    return total, boundary, fluid_count


def prepare_anchor(lab_root: Path, output: Path, *, q: float = 0.5, dp_m: float = 0.0075,
                   output_interval_s: float = DEFAULT_OUTPUT_INTERVAL_S,
                   time_max_s: float = TIME_MAX_S, cfl: float = DEFAULT_CFL) -> dict[str, Any]:
    """Create one fresh anchor and perform CPU GenCase/native initial checks."""
    lab_root = Path(lab_root).resolve()
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"preflight output must be fresh: {output}")
    if not math.isclose(float(dp_m), 0.0075, abs_tol=1e-12):
        raise ValueError("the bounded preflight is registered only at dp=.0075")
    if not math.isclose(float(output_interval_s), 0.01, abs_tol=1e-12):
        raise ValueError("the bounded preflight is registered only at native .01 s")
    if not math.isclose(float(time_max_s), TIME_MAX_S, abs_tol=1e-12):
        raise ValueError("the source scope requires the complete 8.35 s window")
    amplitude = amplitude_from_q(q)
    source = _lab_path(lab_root, BASE_DEFINITION_REL)
    solver = _lab_path(lab_root, SOLVER_REL)
    gencase = _lab_path(lab_root, GENCASE_REL)
    decoder = _lab_path(lab_root, DECODER_REL)
    for path in (source, solver, gencase, decoder):
        if not path.is_file():
            raise FileNotFoundError(path)
    output.mkdir(parents=True, exist_ok=True)
    case_id = f"CORE_F3_BAFFLE_EXCHANGE_q{float(q):.8f}_dp{float(dp_m):.12f}_anchor".replace(".", "p")
    definition = output / f"{case_id}_Def.xml"
    _rewrite_definition(source, definition, dp_m=float(dp_m), amplitude=amplitude,
                        output_interval_s=float(output_interval_s), time_max_s=float(time_max_s), cfl=float(cfl))
    geometry = _assert_baffle_contract(definition, dp_m=float(dp_m))
    generated_prefix = output / "generated" / case_id
    generated_prefix.parent.mkdir(parents=True, exist_ok=True)
    log_path = output / "gencase.log"
    command = [str(gencase), str(definition.with_suffix("")), str(generated_prefix), "-save:all"]
    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=output, env=_environment(lab_root),
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"GenCase failed; inspect {log_path}")
    generated_xml = generated_prefix.with_suffix(".xml")
    generated_bi4 = generated_prefix.with_suffix(".bi4")
    generated_vtk = [
        generated_prefix.with_name(generated_prefix.name + suffix)
        for suffix in ("_All.vtk", "_Bound.vtk", "_Fluid.vtk", "_MkCells.vtk")
    ]
    required_generated = [generated_xml, generated_bi4, *generated_vtk]
    if not all(path.is_file() for path in required_generated):
        raise ValueError("GenCase did not produce the complete static artifact set")
    total_particles, boundary_particles, fluid_particles = _fluid_count_from_generated(generated_xml)
    with tempfile.TemporaryDirectory(prefix="core-f3-baffle-initial-") as temp:
        ids, position, velocity, density, metadata, info, arrays = core_cfd.native_frame(
            generated_bi4, Path(temp) / "native", decoder
        )
    if len(ids) != total_particles or len(np.unique(ids)) != len(ids):
        raise ValueError("native initial identities do not close or are not unique")
    if not all(np.isfinite(array).all() for array in (position, velocity, density)):
        raise ValueError("native initial state contains nonfinite values")
    if int(metadata.get("CaseNfixed", -1)) != boundary_particles or int(metadata.get("CaseNfluid", -1)) != fluid_particles:
        raise ValueError("native decoder metadata disagrees with GenCase particle summary")
    fluid_velocity = velocity[boundary_particles:boundary_particles + fluid_particles]
    fluid_velocity_error = float(np.max(np.abs(fluid_velocity[:, 0] - amplitude)))
    fluid_transverse_max = float(np.max(np.abs(fluid_velocity[:, 1:])))
    if fluid_velocity_error > 1e-6 or fluid_transverse_max > 1e-6:
        raise ValueError("native initial fluid velocity does not match the new impulse axis")
    fluid_volume = float((BASE_FLUID_SIZE[0] - BAFFLE_SIZE[0]) * BASE_FLUID_SIZE[1] * BASE_FLUID_SIZE[2])
    continuous_mass = float(fluid_volume * RHO0)
    discrete_mass = float(fluid_particles * float(dp_m) ** 3 * RHO0)
    mass_error = discrete_mass / continuous_mass - 1.0
    mass_pass = bool(math.isfinite(mass_error) and abs(mass_error) <= 0.03)
    if not mass_pass:
        raise ValueError(f"native source mass representation failed: {mass_error}")
    files = [definition, log_path, *required_generated]
    inputs = {str(path.resolve()): digest(path) for path in files}
    prepared = {
        "schema": SCHEMA,
        "created_at_utc": _stamp(),
        "status": "prepared_only",
        "execution_status": "prepared_only",
        "launch_allowed": False,
        "qualification_claim": QUALIFICATION_CLAIM,
        "scope_id": SCOPE_ID,
        "revision_id": REVISION_ID,
        "case_id": case_id,
        "family": FAMILY,
        "source_asset_id": "f3_baffle_exchange_q0p5_dp0p0075_anchor",
        "parameter": {
            "name": "initial_impulse_velocity_x_m_s",
            "q": float(q),
            "value": amplitude,
            "range_m_s": [0.45, 1.05],
            "mapping": "u0_x = 0.45 + 0.60*q",
        },
        "recipe": {
            "boundary_method": 2,
            "solver_arguments": ["-mdbc_noslip:1"],
            "boundary_semantics": "native mDBC/no-slip with finite outer tank and an internal mkbound=1 baffle",
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "dp_m": float(dp_m),
            "cfl": float(cfl),
            "output_interval_s": float(output_interval_s),
            "time_max_s": float(time_max_s),
            "mass_policy": "native rho*dp^3; no rescaling",
            "shifting": 0,
            "visco_treatment": 1,
            "visco": 0.05,
        },
        "geometry": geometry,
        "novelty_contract": {
            "relative_to_current_f3_mls_handoff": {
                "physical_geometry_changed": True,
                "change": "internal finite mkbound=1 baffle at x=[0.58,0.61] m; current handoff is plain tank",
                "plain_handoff_scope_id": "F3_native_volume_mls_source",
            },
            "relative_to_legacy_baffle_probe": {
                "same_input": False,
                "changes": [
                    "dp=.04 -> .0075",
                    "initial_velocity_x=.65 -> .75 m/s",
                    "TimeMax=.9 -> 8.35 s",
                    "TimeOut=.05 -> .01 s",
                    "CFL=.20 -> .05",
                    "fresh thin fill and .03 m baffle; legacy fill and .04 m baffle are not reused",
                    "fresh case identity and fresh generated artifacts",
                ],
                "legacy_trajectory_reused": False,
                "legacy_bi4_reused": False,
            },
        },
        "source_provenance": {
            "legacy_definition_path": str(source),
            "legacy_definition_sha256": digest(source),
            "core_preflight_runner_path": str(Path(__file__).resolve()),
            "core_preflight_runner_sha256": digest(Path(__file__)),
            "core_conversion_helper_path": str(Path(core_cfd.__file__).resolve()),
            "core_conversion_helper_sha256": digest(Path(core_cfd.__file__)),
            "solver_path": str(solver),
            "solver_sha256": digest(solver),
            "gencase_path": str(gencase),
            "gencase_sha256": digest(gencase),
            "decoder_path": str(decoder),
            "decoder_sha256": digest(decoder),
        },
        "sampling": {
            "continuous_fluid_box_low_m": BASE_FLUID_LOW.tolist(),
            "continuous_fluid_box_size_m": BASE_FLUID_SIZE.tolist(),
            "baffle_overlap_removed_from_fluid_volume_m3": float(BAFFLE_SIZE[0] * BASE_FLUID_SIZE[1] * BASE_FLUID_SIZE[2]),
            "fluid_particles": fluid_particles,
            "boundary_particles": boundary_particles,
            "total_particles": total_particles,
            "continuous_mass_kg": continuous_mass,
            "discrete_native_mass_kg": discrete_mass,
            "relative_mass_error": mass_error,
            "mass_gate_pass": mass_pass,
            "mass_rescaling": False,
        },
        "native_initial": {
            "initial_time_s": float(info.get("TimeStep", 0.0)),
            "fluid_particles": fluid_particles,
            "boundary_particles": boundary_particles,
            "total_particles": total_particles,
            "unique_particle_ids": True,
            "finite_position_velocity_density": True,
            "fluid_velocity_x_m_s": amplitude,
            "fluid_velocity_max_abs_error_m_s": fluid_velocity_error,
            "fluid_transverse_velocity_max_abs_m_s": fluid_transverse_max,
            "initial_state_pass": True,
        },
        "generated_prefix": str(generated_prefix.resolve()),
        "inputs": inputs,
        "solver_binary": str(solver),
        "solver_sha256": digest(solver),
        "decoder": str(decoder),
        "decoder_sha256": digest(decoder),
        "execution_controls": {
            "cpu_gencase_invoked": True,
            "cpu_native_decode_invoked": True,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "qualification_numerator_credit": 0,
        },
        "preflight_pass": True,
        "solver_product_present": False,
        "downstream": {
            "consumer": "future root-reviewed F3 baffle qualification runtime/audit only",
            "required_before_solver": [
                "root approval for this independent scope",
                "fresh immutable job spec bound to this prepared hash",
                "15-row matrix admission with failure denominator frozen",
                "runtime hard-integrity and spatial/temporal scope audit",
            ],
            "forbidden_until_approval": ["solver", "GPU", "queue", "ledger", "registry", "material training"],
        },
    }
    _write_json(output / "prepared.json", prepared)
    return prepared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--q", type=float, default=0.5)
    parser.add_argument("--dp", type=float, default=0.0075)
    args = parser.parse_args(argv)
    prepared = prepare_anchor(args.lab_root, args.output, q=args.q, dp_m=args.dp)
    print(json.dumps({
        "status": prepared["status"],
        "case_id": prepared["case_id"],
        "prepared_sha256": digest(args.output / "prepared.json"),
        "fluid_particles": prepared["sampling"]["fluid_particles"],
        "mass_error": prepared["sampling"]["relative_mass_error"],
        "solver_invoked": prepared["execution_controls"]["solver_invoked"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
