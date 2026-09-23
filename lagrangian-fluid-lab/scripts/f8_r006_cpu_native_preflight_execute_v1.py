#!/usr/bin/env python3
"""Execute F8 r006's exactly-once CPU/native preflight and retain all outcomes."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

from scripts import f8_r003_cpu_native_preflight_execute_v1 as native
from scripts import f8_r006_cpu_native_preflight_runner_v1 as runner
from scripts import f8_r006_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / str(design.PREFLIGHT_ROOT)
OUTPUT = ROOT
SCOPE = design.SCOPE
SCHEMA = "core.cfd.f8.r006_cpu_native_preflight.v1"


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
    try:
        display_path = str(path.relative_to(LAB))
    except ValueError:
        display_path = str(path)
    return {"path": display_path, "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"immutable F8 r006 receipt already exists: {path}")
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def plane_counts(values: np.ndarray) -> dict[str, int]:
    counts = Counter(f"{round(float(value), 5):.4f}" for value in values)
    return dict(sorted(counts.items()))


def generated_checks(
    generated: Path,
    bound_vtk: Path,
    fluid_vtk: Path,
    hdp_vtk: Path,
    authorization: dict[str, Any],
) -> dict[str, Any]:
    fixed, fluid = native.generated_groups(generated)
    particles = ET.parse(generated).getroot().find(".//particles")
    if particles is None:
        raise ValueError("generated GenCase XML has no particles node")
    hard = authorization["hard_gates"]
    expected_planes = hard["generated_z_wall_plane_particle_counts"]
    bound_points = design.vtk_binary_points(bound_vtk)
    bound_zcounts = plane_counts(np.asarray([point[2] for point in bound_points], dtype=np.float64))
    fluid_points = design.vtk_binary_points(fluid_vtk)
    fluid_z_bounds = [min(point[2] for point in fluid_points), max(point[2] for point in fluid_points)] if fluid_points else []
    hdp_points = design.vtk_binary_points(hdp_vtk)
    hdp_planes = sorted({round(point[2], 5) for point in hdp_points})
    fixed_count = sum(int(group.get("count", "0")) for group in fixed)
    fluid_count = sum(int(group.get("count", "0")) for group in fluid)
    attrs = particles.attrib
    summary_positions = particles.find("./_summary/positions")
    expected_outer_wall = max(abs(float(value)) for value in expected_planes)
    checks = {
        "generated_fixed_boundary_count_positive": fixed_count > 0,
        "generated_fixed_boundary_particles_exact": fixed_count == int(hard["generated_fixed_boundary_particles_exact"]),
        "generated_wall_vtk_point_count_matches_fixed": len(bound_points) == fixed_count,
        "generated_z_wall_plane_particle_counts_exact": bound_zcounts == expected_planes,
        "generated_hdp_surface_point_count_exact": len(hdp_points) == int(hard["generated_hdp_surface_points_exact"]),
        "generated_hdp_surface_z_planes_exact": hdp_planes == [round(float(value), 5) for value in hard["generated_hdp_surface_z_planes_m"]],
        "generated_one_fluid_marker": len(fluid) == 1 and int(fluid[0].get("mkfluid", "-1")) == 0,
        "generated_fluid_particles_exact": fluid_count == int(hard["generated_fluid_particles_exact"]),
        "generated_fluid_vtk_point_count_matches": len(fluid_points) == fluid_count,
        "generated_fluid_vtk_z_bounds_exact": bool(fluid_z_bounds)
            and math.isclose(fluid_z_bounds[0], -0.045, abs_tol=1e-7)
            and math.isclose(fluid_z_bounds[1], 0.045, abs_tol=1e-7),
        "generated_total_particles_exact": int(attrs.get("np", "-1")) == int(hard["generated_total_particles_exact"]),
        "generated_boundary_header_matches": int(attrs.get("nb", "-1")) == fixed_count,
        "generated_fixed_header_matches": int(attrs.get("nbf", "-1")) == fixed_count,
        "generated_global_z_bounds_cover_outer_layers": summary_positions is not None
            and math.isclose(float(summary_positions.find("./posmin").get("z")), -expected_outer_wall, abs_tol=1e-7)
            and math.isclose(float(summary_positions.find("./posmax").get("z")), expected_outer_wall, abs_tol=1e-7),
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
            "generated_groups": {"fixed": fixed, "fluid": fluid},
        "generated_geometry": {
            "bound_vtk_points": len(bound_points), "wall_plane_particle_counts": bound_zcounts,
            "fixed_boundary_particles": fixed_count, "fluid_particles": fluid_count,
            "total_particles_header": int(attrs.get("np", "-1")),
            "hdp_surface_points": len(hdp_points), "hdp_surface_z_planes_m": hdp_planes,
            "fluid_vtk_points": len(fluid_points), "fluid_z_bounds_m": fluid_z_bounds,
            "global_particle_z_bounds_m": None if summary_positions is None else [
                float(summary_positions.find("./posmin").get("z")), float(summary_positions.find("./posmax").get("z"))],
        },
    }


def native_checks(generated: Path, base: Path, authorization: dict[str, Any]) -> dict[str, Any]:
    native_data = native.decode_native(base)
    meta = native_data["metadata"]
    hard = authorization["hard_gates"]
    normals = native_data["normals"]
    position = native_data["position"]
    boundary = sum(int(round(float(meta.get(name, "0")))) for name in ("CaseNfixed", "CaseNmoving", "CaseNfloat"))
    fixed = int(round(float(meta.get("CaseNfixed", "0"))))
    moving = int(round(float(meta.get("CaseNmoving", "0"))))
    floating = int(round(float(meta.get("CaseNfloat", "0"))))
    fluid_count = int(round(float(meta.get("CaseNfluid", "nan"))))
    mass = float(meta.get("MassFluid", "nan"))
    normal_file = native_data["normal_file"]
    boundary_planes = plane_counts(position[:boundary, 2]) if boundary else {}
    generated_fixed, generated_fluid = native.generated_groups(generated)
    generated_fixed_count = sum(int(group.get("count", "0")) for group in generated_fixed)
    generated_fluid_count = sum(int(group.get("count", "0")) for group in generated_fluid)
    expected_mass = float(hard["native_fluid_mass_kg_expected"])
    min_norm = float(hard["native_boundary_normals_finite_and_minimum_magnitude"])
    direction = float(hard["native_boundary_inward_normal_z_component_minimum_m"])
    normal_norms = np.linalg.norm(normals, axis=1) if len(normals) else np.empty((0,), dtype=np.float32)
    lower = position[:boundary, 2] < 0 if boundary else np.zeros((0,), dtype=bool)
    upper = position[:boundary, 2] > 0 if boundary else np.zeros((0,), dtype=bool)
    checks = {
        "native_fixed_boundary_particles_exact": fixed == int(hard["native_boundary_particles_exact"]),
        "native_moving_and_floating_boundary_particles_zero": moving == 0 and floating == 0,
        "native_boundary_count_matches_generated": boundary == generated_fixed_count,
        "native_boundary_z_wall_plane_particle_counts_exact": boundary_planes == hard["native_boundary_z_wall_plane_particle_counts"],
        "native_boundary_normal_file_present": normal_file.is_file(),
        "native_boundary_normal_count_exact": len(normals) == int(hard["native_boundary_normal_count_exact"]),
        "native_boundary_normal_file_size_exact": normal_file.is_file()
            and normal_file.stat().st_size == boundary * 3 * np.dtype(np.float32).itemsize,
        "native_boundary_normals_finite_and_minimum_magnitude": bool(
            len(normals) == boundary and np.isfinite(normals).all()
            and np.isfinite(normal_norms).all() and np.all(normal_norms >= min_norm)
        ),
        "native_boundary_normals_point_inward": bool(
            lower.sum() == boundary // 2 and upper.sum() == boundary // 2
            and np.all(normals[lower, 2] >= direction)
            and np.all(normals[upper, 2] <= -direction)
        ),
        "native_fluid_particle_count_exact": fluid_count == int(hard["native_fluid_particle_count_exact"]),
        "native_fluid_count_matches_generated": fluid_count == generated_fluid_count,
        "native_total_count_consistent": len(native_data["ids"]) == boundary + fluid_count,
        "native_total_count_matches_generated": len(native_data["ids"]) == generated_fixed_count + generated_fluid_count,
        "native_arrays_finite": bool(np.isfinite(position).all() and np.isfinite(native_data["velocity"]).all()
                                     and np.isfinite(native_data["density"]).all()),
        "native_ids_unique": len(np.unique(native_data["ids"])) == len(native_data["ids"]),
        "native_fluid_mass_matches": bool(math.isclose(mass * fluid_count, expected_mass, rel_tol=1e-6, abs_tol=1e-10)),
    }
    return {
        "checks": checks,
        "pass": all(checks.values()),
        "native": {
            "total_particles": int(len(native_data["ids"])),
            "boundary_particles": boundary,
            "fixed_boundary_particles": fixed,
            "moving_boundary_particles": moving,
            "floating_boundary_particles": floating,
            "boundary_wall_plane_particle_counts": boundary_planes,
            "fluid_particles": fluid_count,
            "boundary_normals": ref(normal_file, "decoded native boundary normals"),
            "minimum_normal_magnitude_m": float(normal_norms.min()) if len(normal_norms) else None,
            "lower_wall_normal_z_minimum_m": float(normals[lower, 2].min()) if lower.any() else None,
            "upper_wall_normal_z_maximum_m": float(normals[upper, 2].max()) if upper.any() else None,
            "decoded_arrays": str(native_data["folder"].relative_to(LAB)) if native_data["folder"].is_relative_to(LAB) else str(native_data["folder"]),
            "fluid_mass_kg": mass * fluid_count,
        },
    }


def run_once(output: Path = OUTPUT) -> dict[str, Any]:
    if Path(output).resolve() != OUTPUT.resolve():
        raise ValueError("only the registered F8 r006 output namespace is permitted")
    plan = runner.build_execution_plan()
    authorization = json.loads((LAB / plan["authorization"]).read_text(encoding="utf-8"))
    output = Path(plan["output_namespace"])
    output.mkdir(parents=True, exist_ok=False)
    lock = output / "one-shot-lock.json"
    write_json(lock, {
        "schema": "core.cfd.f8.r006_cpu_native_preflight_lock.v1",
        "created_at_utc": stamp(),
        "authorization": ref(LAB / plan["authorization"], "r006 one-shot authorization"),
        "same_input_retry": False,
        "gencase_invocation_budget": 1,
        "native_decode_invocation_budget": 1,
    })
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "scope_id": SCOPE, "created_at_utc": stamp(),
        "status": "cpu_native_preflight_pending", "qualification_claim": "none", "qualification_credit": 0,
        "authorization": ref(LAB / plan["authorization"], "r006 one-shot authorization"),
        "input": {
            "definition": ref(Path(plan["input"]["definition"]), "r006 Definition"),
            "control": ref(Path(plan["input"]["control"]), "r006 colocated acceleration control"),
        },
        "commands": plan["commands"], "one_shot_lock": ref(lock, "pre-execution retry lock"),
        "execution_controls": {
            "cpu_gencase_invoked": False, "native_decode_invoked": False,
            "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0,
            "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0,
            "denominator_mutation": 0, "training_started": False, "qualification_credit": 0,
        },
        "closed_prior_scopes": authorization["closed_prior_scopes"],
        "failure_policy": "Any failed hard gate closes r006 with zero credit; no retry, prior-scope output reuse, solver, or GPU.",
        "resource_scope": authorization["resource_scope"],
    }
    generated = Path(plan["generated"]["definition"])
    bi4 = Path(plan["generated"]["bi4"])
    bound_vtk = Path(plan["generated"]["bound_vtk"])
    fluid_vtk = Path(plan["generated"]["fluid_vtk"])
    hdp_vtk = Path(plan["generated"]["hdp_actual_vtk"])
    copied_control = Path(plan["generated"]["control_copy"])
    gencase_log, decode_log = output / "gencase.stdout.log", output / "native-decode.stdout.log"
    try:
        constant_audit = native.constantsdef_checks(Path(plan["input"]["definition"]), authorization["single_input"]["constantsdef"])
        receipt["input_constantsdef"] = constant_audit
        if not constant_audit["pass"]:
            receipt.update({"status": "input_constantsdef_failed_hard_audit", "failure": "r006 constantsdef contract did not match before GenCase"})
        else:
            Path(plan["generated"]["prefix"]).parent.mkdir(parents=True, exist_ok=False)
            receipt["execution_controls"]["cpu_gencase_invoked"] = True
            with gencase_log.open("w", encoding="utf-8") as log:
                result = subprocess.run(
                    plan["commands"]["cpu_gencase"], cwd=Path(plan["input"]["definition"]).parent,
                    env=native.cpu_environment(), stdout=log, stderr=subprocess.STDOUT, check=False,
                    timeout=int(authorization["resource_scope"]["gencase_timeout_seconds"]),
                )
            receipt["gencase"] = {
                "returncode": int(result.returncode), "stdout": ref(gencase_log, "CPU GenCase stdout"),
                "generated_xml": ref(generated, "GenCase XML"), "native_bi4": ref(bi4, "GenCase BI4"),
                "bound_vtk": ref(bound_vtk, "GenCase fixed-boundary VTK"),
                "fluid_vtk": ref(fluid_vtk, "GenCase fluid VTK"),
                "hdp_actual_vtk": ref(hdp_vtk, "GenCase hdp normal geometry VTK"),
            }
            copied_matches = copied_control.is_file() and sha256(copied_control) == authorization["control_dependency_copy"]["required_copy_hash"]
            receipt["generated_colocated_control_copy"] = {
                "expected_path": str(design.COPIED_CONTROL), "observed": ref(copied_control, "generated colocated acceleration control"),
                "hash_matches": copied_matches,
            }
            if (result.returncode != 0 or not generated.is_file() or not bi4.is_file()
                    or not bound_vtk.is_file() or not fluid_vtk.is_file() or not hdp_vtk.is_file() or not copied_matches):
                receipt.update({"status": "cpu_gencase_or_control_copy_failed_hard_audit", "failure": "GenCase/XML/BI4/VTK/control-copy hard gate failed"})
            else:
                generated_audit = generated_checks(generated, bound_vtk, fluid_vtk, hdp_vtk, authorization)
                receipt["generated_geometry_audit"] = generated_audit
                if not generated_audit["pass"]:
                    receipt.update({"status": "generated_geometry_failed_hard_audit", "failure": "generated boundary/fluid/hdp geometry gates failed before native decode"})
                else:
                    receipt["execution_controls"]["native_decode_invoked"] = True
                    with decode_log.open("w", encoding="utf-8") as log:
                        result = subprocess.run(
                            plan["commands"]["native_decode"], cwd=output, env=native.cpu_environment(),
                            stdout=log, stderr=subprocess.STDOUT, check=False,
                            timeout=int(authorization["resource_scope"]["native_decode_timeout_seconds"]),
                        )
                    receipt["native_decode"] = {"returncode": int(result.returncode), "stdout": ref(decode_log, "native BI4 decoder stdout")}
                    if result.returncode != 0:
                        receipt.update({"status": "native_decode_failed_hard_audit", "failure": "native decoder returned nonzero"})
                    else:
                        audit = native_checks(generated, Path(plan["commands"]["native_decode"][2]), authorization)
                        receipt.update(audit)
                        receipt["status"] = "cpu_native_preflight_passed_zero_credit" if audit["pass"] else "cpu_native_preflight_failed_hard_audit"
                        if not audit["pass"]:
                            receipt["failure"] = "one or more frozen r006 native-initial hard gates failed"
    except subprocess.TimeoutExpired as error:
        receipt.update({"status": "cpu_native_preflight_failed_hard_audit", "failure": f"timed out: {error.cmd}"})
    except Exception as error:
        receipt.update({"status": "cpu_native_preflight_failed_hard_audit", "failure": f"executor exception: {error!r}"})
    receipt["finished_at_utc"] = stamp()
    write_json(output / "receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    result = run_once()
    print(json.dumps({"status": result["status"], "qualification_credit": 0}, sort_keys=True))
    raise SystemExit(0 if result["status"] == "cpu_native_preflight_passed_zero_credit" else 1)
