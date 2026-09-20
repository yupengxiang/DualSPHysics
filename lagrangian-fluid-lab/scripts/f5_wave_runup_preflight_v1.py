#!/usr/bin/env python3
"""Run exactly one fresh CPU GenCase/native decode preflight for F5.

The root-review receipt is the only authorization.  This command cannot call
the DualSPHysics solver or a GPU worker, and it never writes the Core registry
or qualification matrix.  A materialized output is immutable; subsequent
verification is read-only and cannot rerun the input.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))
from scripts.core_cfd import native_frame


ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v1"
REVIEW = ROOT / "preflight-root-review-v1.json"
DEFINITION = ROOT / "F5_wave_runup_q0p50_dp0p0075_Def.xml"
OUTPUT = ROOT / "preflight-v1"
CASE_ID = "F5_wave_runup_q0p50_dp0p0075"
GENCASE = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
WRITER = LAB / "scripts/f5_wave_runup_definition_writer_v1.py"
RUNNER = LAB / "scripts/f5_wave_runup_preflight_v1.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def parse_generated_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//particles")
    constants = root.find(".//constants")
    if particles is None:
        raise ValueError("generated XML has no particles node")
    summary = particles.find("./_summary")
    fixed = summary.find("./fixed") if summary is not None else None
    fluid = summary.find("./fluid") if summary is not None else None
    return {
        "total_particles": int(particles.get("np", "0")),
        "boundary_particles": int(particles.get("nb", "0")),
        "fixed_particles": int(fixed.get("count", "0")) if fixed is not None else 0,
        "fluid_particles": int(fluid.get("count", "0")) if fluid is not None else 0,
        "dp_m": _number(constants.find("./dp").get("value") if constants is not None and constants.find("./dp") is not None else None),
        "massfluid_kg": _number(constants.find("./massfluid").get("value") if constants is not None and constants.find("./massfluid") is not None else None),
    }


def read_vtk_points(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False, "points": [], "declared_points": 0}
    raw = path.read_bytes()
    match = re.search(rb"(?:^|\n)POINTS\s+(\d+)\s+(\S+)\s*\n", raw)
    if match is None:
        return {"present": True, "points": [], "declared_points": 0, "parse_error": "POINTS header missing"}
    count = int(match.group(1))
    kind = match.group(2).decode("ascii", errors="replace").lower()
    header = raw[:match.end()].upper()
    if b"ASCII" in header:
        tokens = re.findall(rb"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw[match.end():])
        values = [float(item) for item in tokens[: 3 * count]]
        encoding = "ascii"
    else:
        width = {"float": 4, "double": 8}.get(kind)
        if width is None:
            return {"present": True, "points": [], "declared_points": count, "parse_error": f"unsupported VTK type {kind}"}
        payload = raw[match.end():match.end() + width * 3 * count]
        if len(payload) != width * 3 * count:
            return {"present": True, "points": [], "declared_points": count, "parse_error": "short binary VTK payload"}
        values = list(struct.unpack(">" + ("f" if width == 4 else "d") * 3 * count, payload))
        encoding = "binary_big_endian"
    if len(values) != 3 * count:
        return {"present": True, "points": [], "declared_points": count, "parse_error": "wrong coordinate count"}
    points = [tuple(values[index:index + 3]) for index in range(0, len(values), 3)]
    return {"present": True, "points": points, "declared_points": count, "encoding": encoding}


def _geometry_audit(prefix: Path, generated: dict[str, Any], definition: Path) -> dict[str, Any]:
    records = {}
    anomalies: list[str] = []
    for name, suffix, expected in (("all", "_All.vtk", generated["total_particles"]),
                                   ("bound", "_Bound.vtk", generated["boundary_particles"]),
                                   ("fluid", "_Fluid.vtk", generated["fluid_particles"])):
        record = read_vtk_points(prefix.with_name(prefix.name + suffix))
        records[name] = {key: value for key, value in record.items() if key != "points"}
        if record.get("parse_error"):
            anomalies.append(f"{name}:{record['parse_error']}")
        if record.get("declared_points") != expected:
            anomalies.append(f"{name}_count:{record.get('declared_points')}!={expected}")
        points = record.get("points", [])
        if not points:
            anomalies.append(f"{name}_empty")
        if any(not math.isfinite(float(value)) for point in points for value in point):
            anomalies.append(f"{name}_nonfinite")
    root = ET.parse(definition).getroot()
    d = root.find("./casedef/geometry/definition")
    low = [float(d.find("./pointmin").get(axis)) for axis in "xyz"] if d is not None else None
    high = [float(d.find("./pointmax").get(axis)) for axis in "xyz"] if d is not None else None
    out_of_bounds = {}
    if low and high:
        for name, suffix, _ in (("all", "_All.vtk", 0), ("bound", "_Bound.vtk", 0), ("fluid", "_Fluid.vtk", 0)):
            points = read_vtk_points(prefix.with_name(prefix.name + suffix)).get("points", [])
            count = sum(any(value < low[i] - 1e-8 or value > high[i] + 1e-8 for i, value in enumerate(point)) for point in points)
            out_of_bounds[name] = count
            if count:
                anomalies.append(f"{name}_outside_definition:{count}")
    return {"vtk": records, "declared_bounds_m": {"min": low, "max": high},
            "out_of_bounds": out_of_bounds, "anomalies": anomalies, "pass": not anomalies}


def _verify_receipt() -> dict[str, Any]:
    review = load(REVIEW)
    if review["schema"] != "core.f5.third_t1.preflight_root_review_receipt.v1":
        raise ValueError("wrong F5 preflight root review schema")
    if review["status"] != "authorized_one_fresh_cpu_native_preflight_only":
        raise ValueError("F5 preflight is not authorized")
    if review["review_decision"]["authorized_action"] != "run_exactly_one_fresh_cpu_gencase_native_decode":
        raise ValueError("wrong F5 preflight action")
    if any(review["review_decision"].get(key) for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_matrix")):
        raise ValueError("F5 preflight receipt opens a forbidden path")
    for item in review["input_review"].values():
        if isinstance(item, dict) and {"path", "sha256"} <= set(item):
            path = LAB / item["path"]
            if not path.is_file() or sha256(path) != item["sha256"]:
                raise ValueError(f"F5 input hash mismatch: {path}")
    for path in (DEFINITION,):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not GENCASE.is_file() or not DECODER.is_file():
        raise FileNotFoundError("pinned GenCase or native decoder missing")
    return review


def run_once() -> dict[str, Any]:
    _verify_receipt()
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError("F5 preflight output already materialized; same input cannot be rerun")
    OUTPUT.mkdir(parents=True)
    generated_dir = OUTPUT / "generated"
    generated_dir.mkdir()
    prefix = generated_dir / CASE_ID
    command = [str(GENCASE), str(DEFINITION.with_suffix("")), str(prefix), "-save:all"]
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["NVIDIA_VISIBLE_DEVICES"] = "void"
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.run(command, cwd=DEFINITION.parent, env=env, text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, check=False)
    log = OUTPUT / "gencase.stdout.log"
    log.write_text(process.stdout, encoding="utf-8")
    record: dict[str, Any] = {
        "schema": "core.f5.third_t1.preflight.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "cpu_native_preflight_failed_hard_audit",
        "qualification_claim": "none",
        "case_id": CASE_ID,
        "authorization": bind(REVIEW, "F5 preflight root review"),
        "input": bind(DEFINITION, "fresh F5 Definition"),
        "motion": bind(ROOT / "Mov_piston_q0p50_scaled.dat", "fresh F5 motion"),
        "gencase": {"command": command, "started_at_utc": started, "return_code": process.returncode,
                    "stdout_log": bind(log, "CPU GenCase stdout"), "environment": {"CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "void"}},
        "binaries": {"gencase": bind(GENCASE, "pinned CPU GenCase"), "native_decoder": bind(DECODER, "pinned native BI4 decoder")},
        "execution_controls": {"gencase_invoked": True, "native_decode_invoked": False, "solver_invoked": False,
                               "gpu_started": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0,
                               "matrix_mutation": 0, "qualification_credit": 0},
        "hard_gates": {},
    }
    if process.returncode != 0:
        record["failure_reason"] = "GenCase returned nonzero"
        (OUTPUT / "preflight.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return record
    generated_xml = prefix.with_suffix(".xml")
    bi4 = prefix.with_suffix(".bi4")
    if not generated_xml.is_file() or not bi4.is_file():
        record["failure_reason"] = "GenCase did not produce generated XML and BI4"
        (OUTPUT / "preflight.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return record
    generated = parse_generated_xml(generated_xml)
    geometry = _geometry_audit(prefix, generated, DEFINITION)
    with tempfile.TemporaryDirectory(prefix="f5-native-") as temp:
        ids, pos, vel, rho, metadata, info, arrays = native_frame(bi4, Path(temp) / "native", DECODER)
        record["execution_controls"]["native_decode_invoked"] = True
        boundary_count = int(float(metadata.get("CaseNfixed", 0)))
        fluid_count = int(float(metadata.get("CaseNfluid", 0)))
        mass_per_particle = float(metadata.get("MassFluid", "nan"))
        finite = bool(np.isfinite(pos).all() and np.isfinite(vel).all() and np.isfinite(rho).all())
        unique_ids = len(np.unique(ids)) == len(ids)
        axis_aligned = len(ids) == boundary_count + fluid_count and fluid_count == generated["fluid_particles"]
        xml_mass = generated.get("massfluid_kg")
        mass_match = bool(xml_mass is not None and math.isfinite(mass_per_particle) and abs(xml_mass - mass_per_particle) <= max(1e-12, abs(xml_mass) * 1e-6))
        record["native"] = {"total_particles": int(len(ids)), "boundary_particles": boundary_count,
                            "fluid_particles": fluid_count, "unique_ids": unique_ids,
                            "finite_arrays": finite, "metadata_massfluid_kg": mass_per_particle,
                            "xml_massfluid_kg": xml_mass, "mass_metadata_match": mass_match,
                            "initial_total_fluid_mass_kg": mass_per_particle * fluid_count if math.isfinite(mass_per_particle) else None,
                            "arrays_directory": str(arrays)}
    record["generated"] = generated
    record["geometry"] = geometry
    gates = {
        "gencase_return_code_zero": process.returncode == 0,
        "generated_xml_present": generated_xml.is_file(),
        "native_bi4_present": bi4.is_file(),
        "id_unique_and_xml_aligned": bool(record["native"]["unique_ids"] and record["native"]["fluid_particles"] == generated["fluid_particles"]),
        "finite_native_arrays": record["native"]["finite_arrays"],
        "mass_metadata_match": record["native"]["mass_metadata_match"],
        "geometry_static_integrity": geometry["pass"],
        "trajectory_endpoint_gate": "not_applicable_until_solver",
        "full_window_reached": "not_applicable_until_solver",
        "event_completion": "not_applicable_until_solver",
    }
    record["hard_gates"] = gates
    record["preflight_pass"] = bool(all(gates[key] for key in ("gencase_return_code_zero", "generated_xml_present", "native_bi4_present",
                                                                  "id_unique_and_xml_aligned", "finite_native_arrays", "mass_metadata_match", "geometry_static_integrity")))
    record["qualified"] = False
    record["matrix_credit"] = 0
    record["status"] = "cpu_native_preflight_passed_static_only" if record["preflight_pass"] else "cpu_native_preflight_failed_hard_audit"
    record["artifacts"] = {"generated_xml": bind(generated_xml, "fresh generated XML"), "native_bi4": bind(bi4, "fresh native BI4"),
                            "preflight": {"path": rel(OUTPUT / "preflight.json")}}
    (OUTPUT / "preflight.json").write_text(json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    record["artifacts"]["preflight"]["sha256"] = sha256(OUTPUT / "preflight.json")
    # The self-reference is deliberately omitted from the JSON file; the returned
    # value carries the final output hash for the caller.
    return record


def verify_materialized() -> dict[str, Any]:
    path = OUTPUT / "preflight.json"
    record = load(path)
    if record.get("schema") != "core.f5.third_t1.preflight.v1":
        raise ValueError("wrong F5 preflight schema")
    if record.get("execution_controls", {}).get("solver_invoked") is not False:
        raise ValueError("preflight claims solver invocation")
    if record.get("execution_controls", {}).get("gpu_started") is not False:
        raise ValueError("preflight claims GPU invocation")
    if record.get("matrix_credit") != 0 or record.get("qualified") is not False:
        raise ValueError("preflight changed qualification credit")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run-once", "verify-preflight"))
    args = parser.parse_args()
    result = run_once() if args.command == "run-once" else verify_materialized()
    print(json.dumps({"status": result.get("status"), "preflight_pass": result.get("preflight_pass"),
                      "qualified": result.get("qualified"), "matrix_credit": result.get("matrix_credit", 0),
                      "output": rel(OUTPUT / "preflight.json")}, indent=2))
    return 0 if args.command == "verify-preflight" or result.get("preflight_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
