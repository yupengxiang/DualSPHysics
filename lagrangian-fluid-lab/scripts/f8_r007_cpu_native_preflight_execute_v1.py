#!/usr/bin/env python3
"""Run F8 r007's exactly-once CPU/native preflight and retain every outcome."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

from scripts import f8_r003_cpu_native_preflight_execute_v1 as native
from scripts import f8_r006_cpu_native_preflight_execute_v1 as audit_helpers
from scripts import f8_r007_cpu_native_preflight_runner_v1 as runner
from scripts import f8_r007_static_design_review_v1 as design


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / design.PREFLIGHT_ROOT
SCOPE = design.SCOPE
SCHEMA = "core.cfd.f8.r007_cpu_native_preflight.v1"


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
        raise FileExistsError(f"immutable F8 r007 receipt already exists: {path}")
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def cpu_environment() -> dict[str, str]:
    env = os.environ.copy()
    binary_dir = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux"
    env.update({
        "LD_LIBRARY_PATH": str(binary_dir) + ":" + env.get("LD_LIBRARY_PATH", ""),
        "CUDA_VISIBLE_DEVICES": "", "NVIDIA_VISIBLE_DEVICES": "void",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    })
    return env


def generated_checks(generated: Path, bound: Path, fluid: Path, hdp: Path,
                     authorization: dict[str, Any]) -> dict[str, Any]:
    """Use the audited r006 geometry checks against the fresh r007 artifacts."""
    return audit_helpers.generated_checks(generated, bound, fluid, hdp, authorization)


def native_checks(generated: Path, base: Path, authorization: dict[str, Any]) -> dict[str, Any]:
    """Use the audited r006 native-array/normal checks against r007 output."""
    return audit_helpers.native_checks(generated, base, authorization)


def run_once(output: Path = OUTPUT) -> dict[str, Any]:
    if Path(output).resolve() != OUTPUT.resolve():
        raise ValueError("only the registered F8 r007 output namespace is permitted")
    plan = runner.build_execution_plan()
    authorization = json.loads((LAB / plan["authorization"]).read_text(encoding="utf-8"))
    output = Path(plan["output_namespace"])
    output.mkdir(parents=True, exist_ok=False)
    lock = output / "one-shot-lock.json"
    write_json(lock, {
        "schema": "core.cfd.f8.r007_cpu_native_preflight_lock.v1",
        "created_at_utc": stamp(),
        "authorization": ref(LAB / plan["authorization"], "r007 one-shot authorization"),
        "same_input_retry": False, "gencase_invocation_budget": 1,
        "native_decode_invocation_budget": 1,
    })
    receipt: dict[str, Any] = {
        "schema": SCHEMA, "scope_id": SCOPE, "created_at_utc": stamp(),
        "status": "cpu_native_preflight_pending", "qualification_claim": "none", "qualification_credit": 0,
        "authorization": ref(LAB / plan["authorization"], "r007 one-shot authorization"),
        "input": {
            "definition": ref(Path(plan["input"]["definition"]), "r007 Definition"),
            "control": ref(Path(plan["input"]["control"]), "r007 colocated acceleration control"),
        },
        "commands": plan["commands"], "one_shot_lock": ref(lock, "pre-execution retry lock"),
        "execution_controls": {
            "cpu_gencase_invoked": False, "native_decode_invoked": False,
            "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0,
            "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0,
            "denominator_mutation": 0, "training_started": False, "qualification_credit": 0,
        },
        "closed_prior_scopes": authorization["closed_prior_scopes"],
        "retained_previous_failure": authorization["retained_previous_failure"],
        "failure_policy": "Any failed hard gate closes r007 with zero credit; no retry or prior-scope output reuse.",
        "resource_scope": authorization["resource_scope"],
    }
    generated = Path(plan["generated"]["definition"])
    bi4 = Path(plan["generated"]["bi4"])
    bound = Path(plan["generated"]["bound_vtk"])
    fluid = Path(plan["generated"]["fluid_vtk"])
    hdp = Path(plan["generated"]["hdp_actual_vtk"])
    copied_control = Path(plan["generated"]["control_copy"])
    gencase_log, decode_log = output / "gencase.stdout.log", output / "native-decode.stdout.log"
    try:
        constants = native.constantsdef_checks(Path(plan["input"]["definition"]), authorization["single_input"]["constantsdef"])
        receipt["input_constantsdef"] = constants
        if not constants["pass"]:
            receipt.update({"status": "input_constantsdef_failed_hard_audit", "failure": "r007 constantsdef contract failed before GenCase"})
        else:
            Path(plan["generated"]["prefix"]).parent.mkdir(parents=True, exist_ok=False)
            receipt["execution_controls"]["cpu_gencase_invoked"] = True
            with gencase_log.open("w", encoding="utf-8") as log:
                result = subprocess.run(
                    plan["commands"]["cpu_gencase"], cwd=Path(plan["input"]["definition"]).parent,
                    env=cpu_environment(), stdout=log, stderr=subprocess.STDOUT, check=False,
                    timeout=int(authorization["resource_scope"]["gencase_timeout_seconds"]),
                )
            receipt["gencase"] = {
                "returncode": int(result.returncode), "stdout": ref(gencase_log, "CPU GenCase stdout"),
                "generated_xml": ref(generated, "GenCase XML"), "native_bi4": ref(bi4, "GenCase BI4"),
                "bound_vtk": ref(bound, "GenCase fixed-boundary VTK"),
                "fluid_vtk": ref(fluid, "GenCase fluid VTK"), "hdp_actual_vtk": ref(hdp, "GenCase hdp normal geometry VTK"),
            }
            copied_matches = copied_control.is_file() and sha256(copied_control) == authorization["control_dependency_copy"]["required_copy_hash"]
            receipt["generated_colocated_control_copy"] = {
                "expected_path": str(design.COPIED_CONTROL),
                "observed": ref(copied_control, "generated colocated acceleration control"),
                "hash_matches": copied_matches,
            }
            if (result.returncode != 0 or not generated.is_file() or not bi4.is_file()
                    or not bound.is_file() or not fluid.is_file() or not hdp.is_file() or not copied_matches):
                receipt.update({"status": "cpu_gencase_or_control_copy_failed_hard_audit", "failure": "GenCase/XML/BI4/VTK/control-copy hard gate failed"})
            else:
                audit = generated_checks(generated, bound, fluid, hdp, authorization)
                receipt["generated_geometry_audit"] = audit
                if not audit["pass"]:
                    receipt.update({"status": "generated_geometry_failed_hard_audit", "failure": "generated geometry/control gates failed before native decode"})
                else:
                    receipt["execution_controls"]["native_decode_invoked"] = True
                    with decode_log.open("w", encoding="utf-8") as log:
                        result = subprocess.run(
                            plan["commands"]["native_decode"], cwd=output, env=cpu_environment(),
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
                            receipt["failure"] = "one or more frozen r007 native-initial hard gates failed"
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
