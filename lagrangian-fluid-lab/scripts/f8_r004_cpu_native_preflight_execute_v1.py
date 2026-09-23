#!/usr/bin/env python3
"""Execute F8 r004's exact once-only CPU/native preflight and retain all outcomes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from scripts import f8_r003_cpu_native_preflight_execute_v1 as native
from scripts import f8_r004_cpu_native_preflight_runner_v1 as runner

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB / "campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r004"
OUTPUT = ROOT / "cpu-native-preflight-v1"
SCOPE = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R004"
SCHEMA = "core.cfd.f8.r004_cpu_native_preflight.v1"


def stamp() -> str: return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any] | None:
    path = Path(path).resolve()
    return None if not path.is_file() else {"path": str(path.relative_to(LAB)), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def write_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists(): raise FileExistsError(f"immutable F8 r004 receipt already exists: {path}")
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def run_once(output: Path = OUTPUT) -> dict[str, Any]:
    if Path(output).resolve() != OUTPUT.resolve(): raise ValueError("only the registered F8 r004 output namespace is permitted")
    plan = runner.build_execution_plan(); authorization = json.loads((LAB / plan["authorization"]).read_text(encoding="utf-8"))
    output = Path(plan["output_namespace"]); output.mkdir(parents=True, exist_ok=False)
    lock = output / "one-shot-lock.json"
    write_json(lock, {"schema": "core.cfd.f8.r004_cpu_native_preflight_lock.v1", "created_at_utc": stamp(), "authorization": ref(LAB / plan["authorization"], "r004 one-shot authorization"), "same_input_retry": False, "gencase_invocation_budget": 1, "native_decode_invocation_budget": 1})
    receipt: dict[str, Any] = {"schema": SCHEMA, "scope_id": SCOPE, "created_at_utc": stamp(), "status": "cpu_native_preflight_pending", "qualification_claim": "none", "qualification_credit": 0, "authorization": ref(LAB / plan["authorization"], "r004 one-shot authorization"), "input": {"definition": ref(Path(plan["input"]["definition"]), "r004 Definition"), "control": ref(Path(plan["input"]["control"]), "r004 colocated control")}, "commands": plan["commands"], "one_shot_lock": ref(lock, "pre-execution retry lock"), "execution_controls": {"cpu_gencase_invoked": False, "native_decode_invoked": False, "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0, "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0, "denominator_mutation": 0, "training_started": False, "qualification_credit": 0}, "closed_prior_scopes": authorization["closed_prior_scopes"], "failure_policy": "Any failure closes r004; same-input retry and r001--r003 output reuse are forbidden."}
    prefix = Path(plan["commands"]["cpu_gencase"][2]); generated, bi4 = prefix.with_suffix(".xml"), prefix.with_suffix(".bi4")
    gencase_log, decode_log = output / "gencase.stdout.log", output / "native-decode.stdout.log"
    try:
        constant_audit = native.constantsdef_checks(Path(plan["input"]["definition"]), authorization["single_input"]["constantsdef"])
        receipt["input_constantsdef"] = constant_audit
        if not constant_audit["pass"]:
            receipt.update({"status": "input_constantsdef_failed_hard_audit", "failure": "r004 constantsdef contract did not match before GenCase"})
        else:
            prefix.parent.mkdir(parents=True, exist_ok=False)
            with gencase_log.open("w", encoding="utf-8") as log:
                result = subprocess.run(plan["commands"]["cpu_gencase"], cwd=Path(plan["input"]["definition"]).parent, env=native.cpu_environment(), stdout=log, stderr=subprocess.STDOUT, check=False, timeout=900)
            receipt["execution_controls"]["cpu_gencase_invoked"] = True
            receipt["gencase"] = {"returncode": int(result.returncode), "stdout": ref(gencase_log, "CPU GenCase stdout"), "generated_xml": ref(generated, "GenCase XML"), "native_bi4": ref(bi4, "GenCase BI4")}
            copied = prefix.parent / Path(plan["input"]["control"]).name
            receipt["generated_colocated_control_copy"] = {"expected_path": authorization["control_dependency_copy"]["required_generated_copy"], "observed": ref(copied, "generated colocated acceleration control"), "hash_matches": copied.is_file() and sha256(copied) == authorization["control_dependency_copy"]["required_copy_hash"]}
            if result.returncode != 0 or not generated.is_file() or not bi4.is_file() or not receipt["generated_colocated_control_copy"]["hash_matches"]:
                receipt.update({"status": "cpu_gencase_or_colocated_control_copy_failed_hard_audit", "failure": "GenCase/XML/BI4/colocated-control-copy hard gate failed"})
            else:
                with decode_log.open("w", encoding="utf-8") as log:
                    result = subprocess.run(plan["commands"]["native_decode"], cwd=output, env=native.cpu_environment(), stdout=log, stderr=subprocess.STDOUT, check=False, timeout=300)
                receipt["execution_controls"]["native_decode_invoked"] = True
                receipt["native_decode"] = {"returncode": int(result.returncode), "stdout": ref(decode_log, "native BI4 decoder stdout")}
                if result.returncode != 0:
                    receipt.update({"status": "native_decode_failed_hard_audit", "failure": "native decoder returned nonzero"})
                else:
                    audit = native.native_checks(generated, Path(plan["commands"]["native_decode"][2]), authorization)
                    receipt.update(audit)
                    receipt["status"] = "cpu_native_preflight_passed_zero_credit" if audit["pass"] else "cpu_native_preflight_failed_hard_audit"
                    if not audit["pass"]: receipt["failure"] = "one or more frozen r004 native-initial hard gates failed"
    except subprocess.TimeoutExpired as error:
        receipt.update({"status": "cpu_native_preflight_failed_hard_audit", "failure": f"timed out: {error.cmd}"})
    except Exception as error:
        receipt.update({"status": "cpu_native_preflight_failed_hard_audit", "failure": f"executor exception: {error!r}"})
    receipt["finished_at_utc"] = stamp(); write_json(output / "receipt.json", receipt); return receipt


if __name__ == "__main__":
    receipt = run_once(); print(json.dumps({"status": receipt["status"], "qualification_credit": 0}, sort_keys=True)); raise SystemExit(0 if receipt["status"] == "cpu_native_preflight_passed_zero_credit" else 1)
