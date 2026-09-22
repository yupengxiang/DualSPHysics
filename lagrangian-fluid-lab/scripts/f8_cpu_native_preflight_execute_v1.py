#!/usr/bin/env python3
"""Execute F8's already-authorized one-shot CPU/native preflight.

This is deliberately a narrow executor: it creates the registered fresh
namespace, invokes the hash-bound ``GenCase`` and ``bi4_dump`` argv once each,
and records an immutable, zero-credit receipt.  It contains no solver, GPU,
queue, registry, ledger, training, or qualification entry point.  A namespace
is locked before the first invocation, so an interrupted or failed attempt is
still retained and cannot be retried with this input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

from scripts import f8_cpu_native_preflight_runner_v1 as runner


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r001"
OUTPUT = ROOT / "cpu-native-preflight-v1"
SCHEMA = "core.cfd.f8.cpu_native_preflight.v1"


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
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def _cpu_environment() -> dict[str, str]:
    env = os.environ.copy()
    binary_dir = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
    env["LD_LIBRARY_PATH"] = str(binary_dir) + ":" + env.get("LD_LIBRARY_PATH", "")
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["NVIDIA_VISIBLE_DEVICES"] = "void"
    env["OMP_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    return env


def _groups(generated_xml: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = ET.parse(generated_xml).getroot()
    particles = root.find(".//particles")
    if root.tag != "case" or particles is None:
        raise ValueError("generated XML has no case/particles tree")
    fixed = [dict(node.attrib) for node in particles.findall("./fixed")]
    fluid = [dict(node.attrib) for node in particles.findall("./fluid")]
    return fixed, fluid


def _decode_native(decoded_base: Path) -> dict[str, Any]:
    root = ET.parse(str(decoded_base) + ".xml").getroot()
    parent = root.find("item")
    node = parent.find("item") if parent is not None else None
    if parent is None or node is None or not node.get("name"):
        raise ValueError("native decoder XML has no top-level particle item")
    metadata = {str(item.get("name")): str(item.get("v")) for item in parent if item.tag != "item"}
    folder = decoded_base / str(node.get("name"))
    ids = np.fromfile(folder / "Idp.bin", np.uint32)
    position_file = folder / "Posd.bin" if (folder / "Posd.bin").is_file() else folder / "Pos.bin"
    positions = np.fromfile(position_file, np.float64 if position_file.name == "Posd.bin" else np.float32)
    velocity = np.fromfile(folder / "Vel.bin", np.float32)
    density = np.fromfile(folder / "Rhop.bin", np.float32)
    normals_file = folder / "BoundNor.bin"
    normals = np.fromfile(normals_file, np.float32) if normals_file.is_file() else np.array([], dtype=np.float32)
    if len(positions) % 3 or len(velocity) % 3 or len(normals) % 3:
        raise ValueError("native vector array has a non-triple length")
    positions = positions.reshape(-1, 3)
    velocity = velocity.reshape(-1, 3)
    normals = normals.reshape(-1, 3)
    if not (len(ids) == len(positions) == len(velocity) == len(density)):
        raise ValueError("native ID/position/velocity/density array lengths disagree")
    return {
        "metadata": metadata,
        "folder": folder,
        "ids": ids,
        "positions": positions,
        "velocity": velocity,
        "density": density,
        "normals": normals,
        "normals_file": normals_file,
    }


def _native_checks(generated_xml: Path, decoded_base: Path, gates: dict[str, Any]) -> dict[str, Any]:
    fixed, fluid = _groups(generated_xml)
    native = _decode_native(decoded_base)
    ids = native["ids"]
    positions = native["positions"]
    velocity = native["velocity"]
    density = native["density"]
    normals = native["normals"]
    metadata = native["metadata"]
    expected_fluid = int(gates["native_initial_particle_checks"]["fluid_particle_count_exact"])
    expected_mass = float(gates["native_initial_particle_checks"]["fluid_mass_kg_expected"])
    boundary_count = int(round(float(metadata.get("CaseNfixed", "nan"))))
    fluid_count = int(round(float(metadata.get("CaseNfluid", "nan"))))
    mass_particle = float(metadata.get("MassFluid", "nan"))
    checks = {
        "generated_one_fluid_marker": len(fluid) == 1 and int(fluid[0].get("mkfluid", -1)) == 0,
        "generated_one_boundary_marker": len({item.get("mkbound") for item in fixed}) == 1 and len(fixed) >= 1,
        "generated_fluid_count_exact": len(fluid) == 1 and int(fluid[0].get("count", -1)) == expected_fluid,
        "native_fluid_count_exact": fluid_count == expected_fluid,
        "native_boundary_count_positive": boundary_count >= int(gates["native_initial_particle_checks"]["boundary_particle_count_min"]),
        "native_total_count_consistent": len(ids) == boundary_count + fluid_count,
        "native_ids_unique": len(np.unique(ids)) == len(ids),
        "native_arrays_finite": bool(np.isfinite(positions).all() and np.isfinite(velocity).all() and np.isfinite(density).all()),
        "native_density_within_contract": bool(len(density) and np.all(density >= 950.0) and np.all(density <= 1050.0)),
        "native_no_particle_overlap": len(np.unique(positions, axis=0)) == len(positions),
        "boundary_normal_count": len(normals) == boundary_count,
        "boundary_normals_finite": bool(len(normals) and np.isfinite(normals).all()),
        "boundary_normals_nonzero": bool(len(normals) and np.all(np.linalg.norm(normals, axis=1) > 0.0)),
        "fluid_mass_matches": bool(math.isfinite(mass_particle) and math.isclose(mass_particle * fluid_count, expected_mass, rel_tol=1e-6, abs_tol=1e-10)),
    }
    return {
        "checks": checks,
        "pass": bool(all(checks.values())),
        "generated_groups": {"fixed": fixed, "fluid": fluid},
        "native": {
            "total_particles": int(len(ids)), "boundary_particles": boundary_count, "fluid_particles": fluid_count,
            "mass_per_fluid_particle_kg": mass_particle, "fluid_mass_kg": mass_particle * fluid_count,
            "decoder_xml": ref(Path(str(decoded_base) + ".xml"), "native decoder XML"),
            "decoded_arrays": str(native["folder"].relative_to(LAB)),
            "boundary_normals": ref(native["normals_file"], "decoded boundary normals"),
        },
    }


def _base_receipt(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001",
        "created_at_utc": stamp(),
        "status": "cpu_native_preflight_pending",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "authorization": ref(LAB / plan["authorization"], "one-shot CPU/native authorization"),
        "input": {"definition": ref(Path(plan["input"]["definition"]), "only permitted F8 Definition"), "control": ref(Path(plan["input"]["control"]), "only permitted F8 control")},
        "commands": plan["commands"],
        "execution_controls": {"cpu_gencase_invoked": False, "native_decode_invoked": False, "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0, "denominator_mutation": 0, "training_started": False, "qualification_credit": 0},
        "failure_policy": "Failure is retained in this namespace and same-input retry is forbidden.",
    }


def run_once(output: Path = OUTPUT) -> dict[str, Any]:
    if Path(output).resolve() != OUTPUT.resolve():
        raise ValueError("only the registered F8 output namespace is permitted")
    plan = runner.build_execution_plan()
    output = Path(plan["output_namespace"])
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "one-shot-lock.json", {"schema": "core.cfd.f8.cpu_native_preflight_lock.v1", "created_at_utc": stamp(), "authorization": ref(LAB / plan["authorization"], "authorization at lock"), "same_input_retry": False, "gencase_invocation_budget": 1, "native_decode_invocation_budget": 1})
    receipt = _base_receipt(plan)
    receipt["one_shot_lock"] = ref(output / "one-shot-lock.json", "pre-execution retry lock")
    gencase_log = output / "gencase.stdout.log"
    decode_log = output / "native-decode.stdout.log"
    prefix = Path(plan["commands"]["cpu_gencase"][2])
    generated_xml = prefix.with_suffix(".xml")
    bi4 = prefix.with_suffix(".bi4")
    decoded_base = Path(plan["commands"]["native_decode"][2])
    try:
        prefix.parent.mkdir(parents=True, exist_ok=False)
        with gencase_log.open("w", encoding="utf-8") as log:
            result = subprocess.run(plan["commands"]["cpu_gencase"], cwd=Path(plan["input"]["definition"]).parent, env=_cpu_environment(), stdout=log, stderr=subprocess.STDOUT, check=False, timeout=900)
        receipt["execution_controls"]["cpu_gencase_invoked"] = True
        receipt["gencase"] = {"returncode": int(result.returncode), "stdout": ref(gencase_log, "CPU GenCase stdout"), "generated_xml": ref(generated_xml, "GenCase generated XML"), "native_bi4": ref(bi4, "GenCase native BI4")}
        if result.returncode != 0 or not generated_xml.is_file() or not bi4.is_file():
            receipt.update({"status": "cpu_gencase_failed_hard_audit", "failure": "GenCase did not return zero with generated XML and BI4"})
        else:
            with decode_log.open("w", encoding="utf-8") as log:
                result = subprocess.run(plan["commands"]["native_decode"], cwd=output, env=_cpu_environment(), stdout=log, stderr=subprocess.STDOUT, check=False, timeout=300)
            receipt["execution_controls"]["native_decode_invoked"] = True
            receipt["native_decode"] = {"returncode": int(result.returncode), "stdout": ref(decode_log, "native BI4 decoder stdout")}
            if result.returncode != 0:
                receipt.update({"status": "native_decode_failed_hard_audit", "failure": "native decoder returned nonzero"})
            else:
                audit = _native_checks(generated_xml, decoded_base, json.loads((LAB / plan["authorization"]).read_text(encoding="utf-8"))["hard_gates"])
                receipt.update(audit)
                receipt["status"] = "cpu_native_preflight_passed_zero_credit" if audit["pass"] else "cpu_native_preflight_failed_hard_audit"
                if not audit["pass"]:
                    receipt["failure"] = "one or more frozen native-initial hard gates failed"
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
    print(json.dumps({"status": receipt["status"], "qualification_credit": receipt["qualification_credit"]}, sort_keys=True))
    return 0 if receipt["status"] == "cpu_native_preflight_passed_zero_credit" else 1


if __name__ == "__main__":
    raise SystemExit(main())
