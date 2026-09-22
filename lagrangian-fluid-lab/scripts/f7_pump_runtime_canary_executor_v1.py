#!/usr/bin/env python3
"""Execute one explicitly requested, isolated official Pump CPU canary.

This executor is deliberately separate from the proposal-only planner.  It
copies the allowlisted official inputs into a fresh temporary root, changes
only the requested TimeMax/TimeOut for a bounded canary, invokes direct
GenCase/CPU binaries, and decodes fluid BI4 frames into a standalone HDF5.
It never uses the destructive example wrapper and never mutates Core queue,
registry, ledger, completion, or qualification denominators.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import h5py
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.core_cfd import native_frame
from scripts.f7_pump_geometry_adapter_v1 import (
    DEFAULT_DEFINITION,
    DEFAULT_FIXED,
    DEFAULT_MOVING,
    parse_pump_definition,
)
from scripts.f7_pump_runtime_canary_v1 import (
    DECODER,
    GENCASE,
    SCHEMA as PLAN_SCHEMA,
    SOLVER_CPU,
    prepare_plan,
    sha256_file,
)


LAB = Path(__file__).resolve().parents[1]
SCHEMA = "core.f7.pump.runtime_canary_execution.v1"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _derived_definition(source: Path, target: Path, *, time_max_s: float,
                        time_out_s: float, dp_m: float | None = None) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    parameters = {node.get("key"): node for node in root.findall("./execution/parameters/parameter")}
    if "TimeMax" not in parameters or "TimeOut" not in parameters:
        raise ValueError("official Pump definition lacks TimeMax/TimeOut parameters")
    if dp_m is not None:
        dp_m = float(dp_m)
        if not np.isfinite(dp_m) or dp_m <= 0:
            raise ValueError("derived dp_m must be positive and finite")
        geometry = root.find("./casedef/geometry/definition")
        if geometry is None:
            raise ValueError("official Pump definition lacks geometry definition")
        geometry.set("dp", f"{dp_m:.17g}")
    parameters["TimeMax"].set("value", f"{time_max_s:.17g}")
    parameters["TimeOut"].set("value", f"{time_out_s:.17g}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tree.write(target, encoding="UTF-8", xml_declaration=True)


def _fluid_axis(generated_xml: Path) -> np.ndarray:
    root = ET.parse(generated_xml).getroot()
    blocks = root.findall(".//particles/fluid")
    if not blocks:
        raise ValueError("GenCase XML contains no fluid blocks")
    ids = []
    for block in blocks:
        begin, count = int(block.get("begin")), int(block.get("count"))
        if begin < 0 or count <= 0:
            raise ValueError("GenCase XML contains invalid fluid identity range")
        ids.append(np.arange(begin, begin + count, dtype=np.uint32))
    axis = np.concatenate(ids)
    if len(np.unique(axis)) != len(axis):
        raise ValueError("GenCase XML fluid identity ranges overlap")
    return axis


def _convert_fluid_frames(generated_xml: Path, data_dir: Path, output: Path,
                          *, source_hash: str, definition_hash: str,
                          time_max_s: float, time_out_s: float) -> dict[str, Any]:
    paths = sorted(data_dir.glob("Part_[0-9][0-9][0-9][0-9].bi4"))
    if len(paths) < 2:
        raise ValueError("Pump canary produced fewer than two BI4 frames")
    axis = _fluid_axis(generated_xml)
    n, frame_count = len(axis), len(paths)
    partial = output.with_suffix(output.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f7-pump-decode-") as decode_root:
        with h5py.File(partial, "w") as h5:
            h5.attrs.update(
                schema_version=1,
                case_id="F7_PUMP_RUNTIME_CANARY",
                family="F7",
                conversion_complete=False,
                trajectory_semantics="official DualSPHysics Pump fluid particle trajectory; canary only",
                source_trajectory_provenance="direct official GenCase + DualSPHysics CPU execution",
                f7_runtime_evidence=True,
                f7_torque_dataset_present=False,
                f7_qualification_credit=0,
                source_definition_sha256=definition_hash,
                source_assets_sha256=source_hash,
                time_max_s=float(time_max_s),
                time_out_s=float(time_out_s),
            )
            h5.create_dataset("particle_id", data=axis)
            h5.create_dataset("particle_zone", data=np.zeros(n, dtype=np.int16))
            h5.create_dataset("time", shape=(frame_count,), dtype="f8")
            chunk = min(n, 65536)
            for name, dtype, fill in (
                ("position", "f8", np.nan), ("velocity", "f4", np.nan),
                ("density", "f4", np.nan), ("mass", "f4", np.nan),
                ("valid", "bool", False), ("type", "i2", -1),
                ("mk", "i2", -1),
            ):
                vector = name in {"position", "velocity"}
                h5.create_dataset(
                    name, shape=(frame_count, n, 3) if vector else (frame_count, n),
                    dtype=dtype, chunks=(1, chunk, 3) if vector else (1, chunk),
                    compression="lzf", fillvalue=fill,
                )
            previous_time = -1.0
            with tempfile.TemporaryDirectory(prefix="f7-pump-frame-") as frame_root:
                for frame_index, path in enumerate(paths):
                    ids, position, velocity, density, metadata, info, _ = native_frame(
                        path, Path(frame_root) / "frame", DECODER
                    )
                    index = np.searchsorted(axis, ids)
                    selected = index < n
                    selected[selected] &= axis[index[selected]] == ids[selected]
                    index, position, velocity, density = (
                        index[selected], position[selected], velocity[selected], density[selected]
                    )
                    if len(np.unique(index)) != len(index):
                        raise ValueError("decoded fluid identities are duplicated")
                    current_time = float(info["TimeStep"])
                    if not np.isfinite(current_time) or current_time <= previous_time:
                        raise ValueError("decoded Pump times are not finite and increasing")
                    previous_time = current_time
                    mass = np.full(len(index), float(metadata["MassFluid"]), dtype=np.float32)
                    h5["time"][frame_index] = current_time
                    h5["valid"][frame_index, index] = True
                    h5["position"][frame_index, index] = position
                    h5["velocity"][frame_index, index] = velocity
                    h5["density"][frame_index, index] = density
                    h5["mass"][frame_index, index] = mass
                    h5["type"][frame_index, index] = 3
                    h5["mk"][frame_index, index] = 1
                    h5.attrs["conversion_complete_frames"] = frame_index + 1
            h5.create_dataset("particle_id_by_frame", data=np.broadcast_to(axis, (frame_count, n)))
            h5.create_dataset("particle_zone_by_frame", data=np.zeros((frame_count, n), dtype=np.int16))
            h5.attrs["conversion_complete"] = True
    partial.replace(output)
    return {"path": str(output), "sha256": sha256_file(output), "frames": frame_count, "fluid_particles": n}


def execute_canary(output_root: str | Path, *, time_max_s: float = 0.6,
                   time_out_s: float = 0.02, dp_m: float = 0.01) -> dict[str, Any]:
    """Run one bounded CPU canary in a fresh root and return immutable receipt."""
    output_root = Path(output_root).expanduser().resolve()
    if output_root == LAB or LAB in output_root.parents:
        raise ValueError("canary output must not be inside the source lab")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("canary output must be fresh or empty")
    output_root.mkdir(parents=True, exist_ok=True)
    plan = prepare_plan(output_root, time_max_s=time_max_s, time_out_s=time_out_s, dp_m=dp_m)
    contract = parse_pump_definition(DEFAULT_DEFINITION)
    input_root = output_root / "input"
    generated_root = output_root / "generated"
    solver_root = output_root / "solver"
    input_root.mkdir()
    generated_root.mkdir()
    for source in (DEFAULT_FIXED, DEFAULT_MOVING):
        shutil.copyfile(source, input_root / source.name)
    derived_xml = input_root / "CasePump_Def.xml"
    _derived_definition(DEFAULT_DEFINITION, derived_xml, time_max_s=time_max_s,
                        time_out_s=time_out_s, dp_m=dp_m)
    generated_prefix = generated_root / "CasePump"
    gencase_log = output_root / "gencase.stdout.log"
    solver_log = output_root / "solver.stdout.log"
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(GENCASE.parent) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    with gencase_log.open("w", encoding="utf-8") as stream:
        gencase = subprocess.run(
            [str(GENCASE), "CasePump_Def", str(generated_prefix), "-save:all"],
            cwd=input_root, env=env, stdout=stream, stderr=subprocess.STDOUT,
            check=False,
        )
    if gencase.returncode != 0:
        raise RuntimeError(f"GenCase failed with return code {gencase.returncode}; see {gencase_log}")
    solver_root.mkdir()
    with solver_log.open("w", encoding="utf-8") as stream:
        solver = subprocess.run(
            [str(SOLVER_CPU), str(generated_prefix), str(solver_root)],
            cwd=output_root, env=env, stdout=stream, stderr=subprocess.STDOUT,
            check=False,
        )
    solver_text = solver_log.read_text(encoding="utf-8", errors="replace")
    if solver.returncode != 0 or "Finished execution (code=0)" not in solver_text:
        raise RuntimeError(f"Pump solver failed with return code {solver.returncode}; see {solver_log}")
    trajectory = _convert_fluid_frames(
        generated_prefix.with_suffix(".xml"), solver_root / "data", output_root / "trajectory.h5",
        source_hash=sha256_file(DEFAULT_DEFINITION), definition_hash=sha256_file(derived_xml),
        time_max_s=time_max_s, time_out_s=time_out_s,
    )
    receipt = {
        "schema": SCHEMA,
        "status": "runtime_canary_completed_unqualified",
        "plan_schema": PLAN_SCHEMA,
        "plan": plan,
        "derived_definition": {"path": str(derived_xml), "sha256": sha256_file(derived_xml)},
        "execution": {
            "gencase_returncode": gencase.returncode,
            "solver_returncode": solver.returncode,
            "gencase_invoked": True,
            "solver_invoked": True,
            "gpu_started": False,
            "native_decoder_invoked": True,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "qualification_credit": 0,
        },
        "trajectory": trajectory,
        "official_motion_sha256": contract["motion_sha256"],
        "qualification": {
            "T1_numerical": False,
            "T2_macro": False,
            "root_review_required": True,
            "reason": "one bounded runtime canary cannot establish a qualified 15-row range",
        },
    }
    _write_json(output_root / "runtime-canary-receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--time-max", type=float, default=0.6)
    parser.add_argument("--time-out", type=float, default=0.02)
    parser.add_argument("--dp", type=float, default=0.01)
    parser.add_argument("--execute", action="store_true", help="required acknowledgement before invoking binaries")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("refusing to invoke GenCase/solver without --execute")
    result = execute_canary(args.output_root, time_max_s=args.time_max,
                            time_out_s=args.time_out, dp_m=args.dp)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
