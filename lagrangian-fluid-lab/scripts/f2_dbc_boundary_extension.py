#!/usr/bin/env python3
"""Prepare the pre-registered one-time 5 s extension of the F2 DBC canary.

This is an event-window extension after a successful 2.5 s DBC hard audit.  It
does not introduce another repair hypothesis: Boundary=1, CFL=.20, geometry,
initial lattice, motion law, observer and all gates remain fixed.  The only
solver input changes are the requested horizon and the motion-file tail,
which holds the already-completed rotation at -105 degrees.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_cfd
from scripts import core_f2_qualification as f2q
from scripts import f2_full_cup_closed_catchment_dbc as dbc


JOB_SCHEMA = "core.cfd.job.v1"
REVISION_ID = "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2_extension5s_v2"
CASE_ID = "CORE_F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_q0p50000000_dp0p007500000000_extension5s_v2"
JOB_ID = "f2-resting-fill-side-wet-full-cup-closed-catchment-dbc-boundary-extension5s-v2-001"
TIME_MAX_S = 5.0
OUTPUT_INTERVAL_S = 0.01
SOURCE_RELATIVE = (
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2/prepared.json"
)
SOURCE_PRODUCT_RELATIVE = (
    "campaigns/core-v1/runtime/attempts/ada-f2-dbc-boundary-canary-v1/"
    "20260920T030416-78fe3cfbab20/product"
)
OUTPUT_RELATIVE = (
    "campaigns/core-v1/cfd/prepared/"
    "F2_resting_fill_side_wet_full_cup_closed_catchment_dbc_boundary_v2_extension5s_v1"
)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    partial.replace(path)


def _motion(path: Path) -> None:
    lines = ["#Time;Degrees"]
    for time_s in np.arange(0.0, TIME_MAX_S + 0.0001, OUTPUT_INTERVAL_S):
        angle = f2q.motion_angle(float(time_s), dbc.ROTATION_DURATION_S, dbc.ANGLE_DEGREES)
        lines.append(f"{time_s:.6f};{angle:.9f}")
    path.write_text("\n".join(lines) + "\n")


def _set_parameter(root: ET.Element, key: str, value: str | int | float) -> None:
    node = root.find(f".//execution/parameters/parameter[@key='{key}']")
    if node is None:
        raise ValueError(f"missing execution parameter {key}")
    node.set("value", str(value))


def _asset_hashes(prefix: Path) -> dict[str, str]:
    suffixes = {
        "bi4": ".bi4",
        "all_vtk": "_All.vtk",
        "bound_vtk": "_Bound.vtk",
        "fluid_vtk": "_Fluid.vtk",
        "mkcells_vtk": "_MkCells.vtk",
    }
    result = {}
    for name, suffix in suffixes.items():
        path = prefix.with_name(prefix.name + suffix)
        if not path.is_file():
            raise FileNotFoundError(path)
        result[name] = _sha256(path)
    return result


def _native_state_equivalence(left: Path, right: Path, decoder: Path) -> dict:
    """Compare decoded native arrays while allowing GenCase CaseName metadata."""
    with tempfile.TemporaryDirectory(prefix="f2-dbc-extension-native-") as folder:
        left_frame = core_cfd.native_frame(left.with_suffix(".bi4"), Path(folder) / "left", decoder)
        right_frame = core_cfd.native_frame(right.with_suffix(".bi4"), Path(folder) / "right", decoder)
    arrays_equal = all(np.array_equal(left_frame[index], right_frame[index]) for index in range(4))
    metadata_differences = {
        key: [left_frame[4].get(key), right_frame[4].get(key)]
        for key in set(left_frame[4]) | set(right_frame[4])
        if left_frame[4].get(key) != right_frame[4].get(key)
    }
    return {
        "decoded_ids_positions_velocities_density_equal": bool(arrays_equal),
        "metadata_differences": metadata_differences,
        "only_case_name_metadata_changed": set(metadata_differences) <= {"CaseName"},
        "pass": bool(arrays_equal and set(metadata_differences) <= {"CaseName"}),
    }


def _event_window() -> dict:
    value = f2q.event_window(TIME_MAX_S, TIME_MAX_S)
    value["motion_source_file_duration_s"] = TIME_MAX_S
    value["right_censor_policy"] = (
        "this is the one pre-registered 5 s extension after the 2.5 s canary; "
        "retain all existing hard, spill and settled gates without modification"
    )
    return value


def prepare_extension(lab: Path, output: Path) -> dict:
    lab, output = Path(lab).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"extension output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    source_path = lab / SOURCE_RELATIVE
    source = json.loads(source_path.read_text())
    if not source.get("preflight_pass") or source.get("config", {}).get("boundary_method") != 1:
        raise ValueError("source DBC canary is not CPU-preflighted")
    source_definition = Path(source["definition_audit"]["definition"])
    if not source_definition.is_file():
        raise FileNotFoundError(source_definition)
    tree = ET.parse(source_definition)
    root = tree.getroot()
    motion_node = root.find(".//mvrotfile")
    if motion_node is None or motion_node.find("file") is None:
        raise ValueError("DBC source definition has no mvrotfile")
    motion_node.set("duration", f"{TIME_MAX_S:.17g}")
    motion_node.find("file").set("name", f"{CASE_ID}_motion.dat")
    for begin in root.findall(".//begin"):
        begin.set("finish", f"{TIME_MAX_S:.17g}")
    _set_parameter(root, "Boundary", 1)
    _set_parameter(root, "TimeMax", TIME_MAX_S)
    _set_parameter(root, "TimeOut", OUTPUT_INTERVAL_S)
    definition_path = output / f"{CASE_ID}_Def.xml"
    ET.indent(tree, space="    ")
    tree.write(definition_path, encoding="utf-8", xml_declaration=True)
    motion_path = output / f"{CASE_ID}_motion.dat"
    _motion(motion_path)

    binaries = lab / "vendor/official/DualSPHysics_v5.4/bin/linux"
    prefix = output / "generated" / CASE_ID
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [str(binaries / "GenCase_linux64"), str(definition_path.with_suffix("")), str(prefix), "-save:all"]
    with (output / "gencase.log").open("w") as log:
        process = subprocess.run(command, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        raise RuntimeError(f"GenCase failed; inspect {output / 'gencase.log'}")

    generated = ET.parse(prefix.with_suffix(".xml")).getroot()
    resolved_domain = f2q._runtime_domain_from_xml(generated)
    if resolved_domain != source["resolved_runtime_domain"]:
        raise ValueError("extension runtime domain changed")
    fluid_count = sum(int(group.get("count", 0)) for group in generated.findall(".//particles/fluid"))
    expected_fluid = int(source["sampling"]["expected_fluid_particles"])
    if fluid_count != expected_fluid:
        raise ValueError(f"extension fluid count changed: {fluid_count} != {expected_fluid}")
    decoder = lab / "campaigns/l1-resume/artifacts/bi4_dump"
    static = json.loads((lab / dbc.STATIC_RELATIVE).read_text())
    native = dbc._native_initial(prefix, decoder, expected_fluid, Path(static["generated_prefix"]))
    source_prefix = Path(source["generated_prefix"])
    source_assets = _asset_hashes(source_prefix)
    extension_assets = _asset_hashes(prefix)
    native_equivalence = _native_state_equivalence(source_prefix, prefix, decoder)
    geometry_asset_reuse = {
        "bi4_decoded_native_state": native_equivalence["pass"],
        "all_vtk": extension_assets["all_vtk"] == source_assets["all_vtk"],
        "bound_vtk": extension_assets["bound_vtk"] == source_assets["bound_vtk"],
        "fluid_vtk": extension_assets["fluid_vtk"] == source_assets["fluid_vtk"],
        "mkcells_vtk": extension_assets["mkcells_vtk"] == source_assets["mkcells_vtk"],
    }
    if not all(geometry_asset_reuse.values()):
        raise ValueError(f"extension changed geometry/native assets: {geometry_asset_reuse}; native={native_equivalence}")

    config = copy.deepcopy(source["config"])
    config.update({
        "revision_id": REVISION_ID,
        "case_id": CASE_ID,
        "stage": "extension_canary",
        "qualification_only": True,
        "split": "qualification_only",
        "qualified": False,
        "time_max_s": TIME_MAX_S,
        "maximum_extended_time_s": TIME_MAX_S,
        "output_interval_s": OUTPUT_INTERVAL_S,
        "event_window": _event_window(),
        "qualification_claim": "none; one-time 5 s extension of the DBC hard-passing canary",
        "extension_only": True,
        "extension_of_prepared": str(source_path.resolve()),
        "extension_of_prepared_sha256": _sha256(source_path),
        "extension_reason": "pre-registered single 5 s window extension to observe settled event; no new repair variable",
        "definition_audit": {
            "source_definition": str(source_definition),
            "source_definition_sha256": _sha256(source_definition),
            "definition": str(definition_path.resolve()),
            "definition_sha256": _sha256(definition_path),
            "motion_file": str(motion_path.resolve()),
            "motion_sha256": _sha256(motion_path),
            "changed_fields": [
                "registered event horizon TimeMax 2.50 -> 5.00 s",
                "motion file extended to 5.00 s with the same prescribed law and -105 degree hold after motion completion",
            ],
            "unchanged_fields": [
                "Boundary=1 DBC, CFL=.20, dp=.0075 and all Dt controls",
                "full-cup fluid initial lattice and native mass",
                "cup, receiver, tray, catchment and runtime domain geometry",
                "observer and all hard, spill, event and settled thresholds",
            ],
            "qualification_claim": "none",
        },
    })
    prepared = {
        "schema": "core.cfd.v1",
        "created_at": _stamp(),
        "config": config,
        "sampling": copy.deepcopy(source["sampling"]),
        "mass_preflight": copy.deepcopy(source["mass_preflight"]),
        "native_initial": native,
        "resolved_runtime_domain": resolved_domain,
        "dynamic_canary_preflight": {
            "generated_fluid_count": fluid_count,
            "expected_fluid_count": expected_fluid,
            "native_initial_state_finite_unique": native["unique_ids"] and native["finite_initial_arrays"],
            "native_sampling_matches_passed_static": native["native_sampling_matches_passed_static"],
            "normal_preflight_applicability": "not_applicable_for_DBC",
            "catchment_wall_particles_present": native["fixed_particles"] > 0,
            "registered_full_window_s": TIME_MAX_S,
            "geometry_asset_reuse": geometry_asset_reuse,
            "native_equivalence": native_equivalence,
            "extension_only": True,
        },
        "definition_audit": config["definition_audit"],
        "wall_recipe": copy.deepcopy(source["wall_recipe"]),
        "boundary_recipe": copy.deepcopy(source["boundary_recipe"]),
        "preflight_pass": bool(
            fluid_count == expected_fluid
            and native["unique_ids"]
            and native["finite_initial_arrays"]
            and native["initial_fluid_zero_velocity"]
            and native["native_sampling_matches_passed_static"]
            and all(geometry_asset_reuse.values())
            and source["mass_preflight"]["mass_gate_pass"]
        ),
        "generated_prefix": str(prefix.resolve()),
        "source_template": str(source_definition),
        "source_template_sha256": _sha256(source_definition),
        "solver_binary": str(binaries / "DualSPHysics5.4_linux64"),
        "solver_sha256": _sha256(binaries / "DualSPHysics5.4_linux64"),
        "decoder": str(decoder),
        "decoder_sha256": _sha256(decoder),
        "solver_arguments": [],
        "qualification_only": True,
        "qualification_claim": "none; one-time 5 s extension of the DBC hard-passing canary",
        "extension_of_prepared": str(source_path.resolve()),
        "extension_of_prepared_sha256": _sha256(source_path),
        "source_canary_product": str((lab / SOURCE_PRODUCT_RELATIVE).resolve()),
        "source_canary_product_sha256": _sha256(lab / SOURCE_PRODUCT_RELATIVE / "result.json"),
    }
    prepared["inputs"] = {
        str(path.resolve()): _sha256(path)
        for path in output.rglob("*")
        if path.is_file()
    }
    _write_json(output / "prepared.json", prepared)
    return prepared


def make_job(prepared_path: Path, lab: Path, output: Path) -> dict:
    prepared_path, lab, output = Path(prepared_path).resolve(), Path(lab).resolve(), Path(output).resolve()
    prepared = json.loads(prepared_path.read_text())
    if not prepared.get("preflight_pass") or not prepared.get("config", {}).get("extension_only"):
        raise ValueError("extension prepared case did not pass CPU preflight")
    solver = Path(prepared["solver_binary"]).resolve()
    decoder = Path(prepared["decoder"]).resolve()
    runner = lab / "scripts/core_f2_qualification.py"
    generator = lab / "scripts/f2_dbc_boundary_extension.py"
    input_files = [{"path": str(prepared_path), "sha256": _sha256(prepared_path)}]
    for path, sha256 in sorted(prepared.get("inputs", {}).items()):
        if path != str(prepared_path):
            input_files.append({"path": path, "sha256": sha256})
    for path in (solver, decoder, runner, generator):
        item = {"path": str(path), "sha256": _sha256(path)}
        if not any(existing["path"] == item["path"] for existing in input_files):
            input_files.append(item)
    config = prepared["config"]
    spec = {
        "schema": JOB_SCHEMA,
        "job_id": JOB_ID,
        "logical_id": JOB_ID,
        "attempt_role": "f2_dbc_boundary_horizon_extension_canary",
        "category": "f2_dynamic_dbc_boundary_extension5s_canary",
        "host": "ada",
        "source_lab": str(lab),
        "cwd": str(lab),
        "argv": [str(lab / ".venv/bin/python"), str(runner), "--lab-root", str(lab), "run", "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": ["product/result.json", "product/trajectory.h5", "product/audit.json", "product/observations.json"],
        "resources": {"cpu_cores": 2, "ram_mib": 32768, "gpu_peak_mib": 12288, "io_weight": 2},
        "timeout_seconds": 14400,
        "depends_on": [],
        "qualification_claim": "none",
        "qualification_only": True,
        "split": "qualification_only",
        "qualification_status": "candidate-only; one-time 5 s extension; no range or T1 qualification",
        "launch_recommendation": "root review/queue only; extension preserves all gates and is not a new repair hypothesis",
        "input_files": input_files,
        "prepared_case_id": config["case_id"],
        "registered_window_s": TIME_MAX_S,
        "maximum_extended_window_s": TIME_MAX_S,
        "motion_start_s": dbc.MOTION_START_S,
        "rotation_duration_s": dbc.ROTATION_DURATION_S,
        "angle_degrees": dbc.ANGLE_DEGREES,
        "scope_id": config["scope_id"],
        "revision_id": config["revision_id"],
        "family": "F2",
        "extension_only": True,
        "extension_of_prepared": config["extension_of_prepared"],
        "extension_of_prepared_sha256": config["extension_of_prepared_sha256"],
        "boundary_method": "native DBC Boundary=1; unchanged from hard-passing canary",
        "cfl": 0.2,
        "physical_geometry_changed": True,
        "initial_condition_changed": False,
        "mass_rescaling": False,
        "gate_policy": "unchanged hard integrity, native identity, mass, geometry, spill, event and settled gates",
        "resource_estimate_basis": {
            "source_canary_solver_seconds": 66.66454605595209,
            "source_canary_peak_gpu_mib": 606,
            "extension_trajectory_estimate_gib": 1.2,
            "reservation_reason": "five-second output is approximately twice the 2.5 s product; retain the existing conservative worker reservation",
        },
        "worker_contract": "core_runtime worker; scheduler supplies one CUDA UUID and solver uses -gpu:0; output is attempt_dir/product",
    }
    _write_json(output, spec)
    return spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, default=SOURCE_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    job = sub.add_parser("make-job")
    job.add_argument("--prepared", type=Path, required=True)
    job.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = args.lab_root.resolve()
    result = prepare_extension(lab, args.output) if args.command == "prepare" else make_job(args.prepared, lab, args.output)
    print(json.dumps({key: result.get(key) for key in ("preflight_pass", "qualification_only", "extension_only", "prepared_case_id", "job_id", "registered_window_s") if key in result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
