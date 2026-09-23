#!/usr/bin/env python3
"""Run F8 r002's only permitted CPU/native preflight exactly once."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

from scripts import f8_r002_cpu_native_preflight_runner_v1 as runner


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r002"
OUTPUT = ROOT / "cpu-native-preflight-v1"
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"
SCHEMA = "core.cfd.f8.r002_cpu_native_preflight.v1"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any] | None:
    path = Path(path).resolve()
    if not path.is_file():
        return None
    return {"path": str(path.relative_to(LAB)), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"immutable F8 r002 receipt already exists: {path}")
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def cpu_environment() -> dict[str, str]:
    environment = os.environ.copy()
    binary_dir = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
    environment.update({"LD_LIBRARY_PATH": str(binary_dir) + ":" + environment.get("LD_LIBRARY_PATH", ""), "CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "void", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    return environment


def generated_groups(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    particles = ET.parse(path).getroot().find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles")
    return [dict(node.attrib) for node in particles.findall("./fixed")], [dict(node.attrib) for node in particles.findall("./fluid")]


def decode_native(base: Path) -> dict[str, Any]:
    root = ET.parse(str(base) + ".xml").getroot()
    parent = root.find("item")
    particle = parent.find("item") if parent is not None else None
    if parent is None or particle is None or not particle.get("name"):
        raise ValueError("native decoder XML lacks a particle item")
    metadata = {str(item.get("name")): str(item.get("v")) for item in parent if item.tag != "item"}
    folder = base / str(particle.get("name"))
    ids = np.fromfile(folder / "Idp.bin", np.uint32)
    position_file = folder / "Posd.bin" if (folder / "Posd.bin").is_file() else folder / "Pos.bin"
    position = np.fromfile(position_file, np.float64 if position_file.name == "Posd.bin" else np.float32).reshape(-1, 3)
    velocity = np.fromfile(folder / "Vel.bin", np.float32).reshape(-1, 3)
    density = np.fromfile(folder / "Rhop.bin", np.float32)
    normal_file = folder / "BoundNor.bin"
    normals = np.fromfile(normal_file, np.float32).reshape(-1, 3) if normal_file.is_file() else np.empty((0, 3), dtype=np.float32)
    if not (len(ids) == len(position) == len(velocity) == len(density)):
        raise ValueError("native particle arrays disagree")
    return {"metadata": metadata, "folder": folder, "ids": ids, "position": position, "velocity": velocity, "density": density, "normals": normals, "normal_file": normal_file}


def native_checks(generated_xml: Path, decoded_base: Path, authorization: dict[str, Any]) -> dict[str, Any]:
    fixed, fluid = generated_groups(generated_xml)
    native = decode_native(decoded_base)
    meta, gates = native["metadata"], authorization["hard_gates"]
    boundary_count, fluid_count = int(round(float(meta.get("CaseNfixed", "nan")))), int(round(float(meta.get("CaseNfluid", "nan"))))
    normals = native["normals"]
    fixed_z = [item for item in fixed if int(item.get("count", "0")) > 0]
    mass = float(meta.get("MassFluid", "nan"))
    checks = {
        "generated_fixed_boundary_count_positive": bool(fixed_z),
        "generated_z_wall_planes_present": len(fixed_z) >= 2,
        "generated_one_fluid_marker": len(fluid) == 1 and int(fluid[0].get("mkfluid", "-1")) == 0,
        "native_boundary_particle_count_positive": boundary_count > 0,
        "native_boundary_normal_count_positive": len(normals) > 0 and len(normals) == boundary_count,
        "native_boundary_normals_finite_and_nonzero": bool(len(normals) and np.isfinite(normals).all() and np.all(np.linalg.norm(normals, axis=1) > 0)),
        "native_fluid_particle_count_exact": fluid_count == int(gates["native_fluid_particle_count_exact"]),
        "native_total_count_consistent": len(native["ids"]) == boundary_count + fluid_count,
        "native_arrays_finite": bool(np.isfinite(native["position"]).all() and np.isfinite(native["velocity"]).all() and np.isfinite(native["density"]).all()),
        "native_ids_unique": len(np.unique(native["ids"])) == len(native["ids"]),
        "native_fluid_mass_matches": bool(math.isclose(mass * fluid_count, float(gates["native_fluid_mass_kg_expected"]), rel_tol=1e-6, abs_tol=1e-10)),
    }
    return {"checks": checks, "pass": bool(all(checks.values())), "generated_groups": {"fixed": fixed, "fluid": fluid}, "native": {"total_particles": int(len(native["ids"])), "boundary_particles": boundary_count, "fluid_particles": fluid_count, "boundary_normals": ref(native["normal_file"], "decoded boundary normals"), "decoded_arrays": str(native["folder"].relative_to(LAB)), "fluid_mass_kg": mass * fluid_count}}


def run_once(output: Path = OUTPUT) -> dict[str, Any]:
    if Path(output).resolve() != OUTPUT.resolve():
        raise ValueError("only the registered F8 r002 output namespace is permitted")
    plan = runner.build_execution_plan()
    authorization = json.loads((LAB / plan["authorization"]).read_text(encoding="utf-8"))
    output = Path(plan["output_namespace"])
    output.mkdir(parents=True, exist_ok=False)
    lock = output / "one-shot-lock.json"
    write_json(lock, {"schema": "core.cfd.f8.r002_cpu_native_preflight_lock.v1", "created_at_utc": stamp(), "authorization": ref(LAB / plan["authorization"], "r002 one-shot authorization"), "same_input_retry": False, "gencase_invocation_budget": 1, "native_decode_invocation_budget": 1})
    receipt: dict[str, Any] = {"schema": SCHEMA, "scope_id": SCOPE, "created_at_utc": stamp(), "status": "cpu_native_preflight_pending", "qualification_claim": "none", "qualification_credit": 0, "authorization": ref(LAB / plan["authorization"], "r002 one-shot authorization"), "input": {"definition": ref(Path(plan["input"]["definition"]), "r002 Definition"), "control": ref(Path(plan["input"]["control"]), "r002 control")}, "commands": plan["commands"], "one_shot_lock": ref(lock, "pre-execution retry lock"), "execution_controls": {"cpu_gencase_invoked": False, "native_decode_invoked": False, "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0, "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0, "denominator_mutation": 0, "training_started": False, "qualification_credit": 0}, "r001_is_immutable_closed_history": {"scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001", "r001_evidence_mutated": False, "same_input_retry_forbidden": True}, "failure_policy": "Any failure is retained in r002 and same-input retry is forbidden."}
    prefix = Path(plan["commands"]["cpu_gencase"][2])
    generated_xml, bi4 = prefix.with_suffix(".xml"), prefix.with_suffix(".bi4")
    gencase_log, decode_log = output / "gencase.stdout.log", output / "native-decode.stdout.log"
    try:
        prefix.parent.mkdir(parents=True, exist_ok=False)
        with gencase_log.open("w", encoding="utf-8") as log:
            result = subprocess.run(plan["commands"]["cpu_gencase"], cwd=Path(plan["input"]["definition"]).parent, env=cpu_environment(), stdout=log, stderr=subprocess.STDOUT, check=False, timeout=900)
        receipt["execution_controls"]["cpu_gencase_invoked"] = True
        receipt["gencase"] = {"returncode": int(result.returncode), "stdout": ref(gencase_log, "CPU GenCase stdout"), "generated_xml": ref(generated_xml, "GenCase XML"), "native_bi4": ref(bi4, "GenCase BI4")}
        copied = prefix.parent / "acceleration" / Path(plan["input"]["control"]).name
        expected_hash = authorization["control_dependency_copy"]["required_copy_hash"]
        receipt["generated_control_copy"] = {"expected_path": authorization["control_dependency_copy"]["required_generated_copy"], "observed": ref(copied, "generated copied acceleration control"), "hash_matches": copied.is_file() and sha256(copied) == expected_hash}
        if result.returncode != 0 or not generated_xml.is_file() or not bi4.is_file() or not receipt["generated_control_copy"]["hash_matches"]:
            receipt.update({"status": "cpu_gencase_or_control_copy_failed_hard_audit", "failure": "GenCase/XML/BI4/control-copy hard gate failed"})
        else:
            with decode_log.open("w", encoding="utf-8") as log:
                result = subprocess.run(plan["commands"]["native_decode"], cwd=output, env=cpu_environment(), stdout=log, stderr=subprocess.STDOUT, check=False, timeout=300)
            receipt["execution_controls"]["native_decode_invoked"] = True
            receipt["native_decode"] = {"returncode": int(result.returncode), "stdout": ref(decode_log, "native BI4 decoder stdout")}
            if result.returncode != 0:
                receipt.update({"status": "native_decode_failed_hard_audit", "failure": "native decoder returned nonzero"})
            else:
                audit = native_checks(generated_xml, Path(plan["commands"]["native_decode"][2]), authorization)
                receipt.update(audit)
                receipt["status"] = "cpu_native_preflight_passed_zero_credit" if audit["pass"] else "cpu_native_preflight_failed_hard_audit"
                if not audit["pass"]:
                    receipt["failure"] = "one or more frozen r002 native-initial hard gates failed"
    except subprocess.TimeoutExpired as error:
        receipt.update({"status": "cpu_native_preflight_failed_hard_audit", "failure": f"timed out: {error.cmd}"})
    except Exception as error:
        receipt.update({"status": "cpu_native_preflight_failed_hard_audit", "failure": f"executor exception: {error!r}"})
    receipt["finished_at_utc"] = stamp()
    write_json(output / "receipt.json", receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    receipt = run_once()
    print(json.dumps({"status": receipt["status"], "qualification_credit": 0}, sort_keys=True))
    return 0 if receipt["status"] == "cpu_native_preflight_passed_zero_credit" else 1


if __name__ == "__main__":
    raise SystemExit(main())
