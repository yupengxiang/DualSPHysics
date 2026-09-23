#!/usr/bin/env python3
"""Read-only closure audit for the immutable F8 r003 one-shot preflight."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

LAB = Path(__file__).resolve().parents[1]
CASE = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r003")
PREFLIGHT = CASE / "cpu-native-preflight-v1"
OUTPUT = LAB / CASE / "cpu-native-preflight-postrun-audit-v1/receipt.json"
SCHEMA = "core.cfd.f8.r003_cpu_native_preflight_postrun_audit.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path.relative_to(LAB)), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def build_audit() -> dict[str, Any]:
    preflight = LAB / PREFLIGHT
    receipt_path, lock_path = preflight / "receipt.json", preflight / "one-shot-lock.json"
    log_path = preflight / "gencase.stdout.log"
    generated_xml = preflight / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003.xml"
    generated_bi4 = preflight / "generated/F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003.bi4"
    receipt, lock = load(receipt_path), load(lock_path)
    require(receipt.get("schema") == "core.cfd.f8.r003_cpu_native_preflight.v1", "preflight schema changed")
    require(receipt.get("status") == "cpu_gencase_or_control_copy_failed_hard_audit", "r003 is not the retained control-copy hard failure")
    require(receipt.get("qualification_claim") == "none" and receipt.get("qualification_credit") == 0, "preflight has credit")
    require(lock.get("gencase_invocation_budget") == 1 and lock.get("native_decode_invocation_budget") == 1 and lock.get("same_input_retry") is False, "one-shot lock changed")
    controls = receipt.get("execution_controls", {})
    require(controls.get("cpu_gencase_invoked") is True and controls.get("native_decode_invoked") is False, "r003 invocation closure changed")
    require(controls.get("solver_invoked") is False and controls.get("gpu_invoked") is False and controls.get("worker_started") is False, "prohibited execution occurred")
    require(all(controls.get(key) == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation", "qualification_credit")), "forbidden accounting mutation")
    constants = receipt.get("input_constantsdef", {})
    require(constants.get("pass") is True and constants.get("checks", {}).get("hswl_explicit_auto_zero") is True, "r003 hswl schema proof changed")
    log = log_path.read_text(encoding="utf-8")
    require(log.count("GenCase v5.4.354.01 (07-04-2025)") == 1 and log.count("Finished execution (code=0).") == 1, "log does not prove exactly one successful GenCase")
    warning = "WARNING: File 'acceleration/F8_OPC_q0p500_r003_acceleration.csv' could not be copied."
    require(log.count(warning) == 1, "required r003 control-copy failure is absent or repeated")
    root = ET.parse(generated_xml).getroot(); particles = root.find(".//particles")
    require(particles is not None, "generated XML lacks particle summary")
    fixed = particles.findall("./fixed"); fluid = particles.findall("./fluid")
    require(len(fixed) == 1 and fixed[0].get("count") == "512" and particles.get("nb") == "512", "fixed boundary realization is not exactly retained")
    require(len(fluid) == 1 and fluid[0].get("count") == "6656", "fluid realization changed")
    require(generated_bi4.stat().st_size > 0, "successful GenCase BI4 is absent or empty")
    evidence = [bind(receipt_path, "retained r003 one-shot preflight receipt"), bind(lock_path, "pre-execution retry lock"), bind(log_path, "single GenCase stdout log"), bind(generated_xml, "GenCase-generated XML"), bind(generated_bi4, "GenCase-generated BI4")]
    return {"schema": SCHEMA, "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R003", "status": "retained_hard_failure_no_retry_zero_credit", "qualification_claim": "none", "qualification_credit": 0, "audit_mode": "strictly_read_only_against_r003_cpu_native_preflight_v1", "failure_closure": {"preflight_status": receipt["status"], "same_input_retry_forbidden": True, "r002_output_reuse_forbidden": True, "gencase_invocations_confirmed": 1, "native_decode_invocations_confirmed": 0, "solver_invoked": False, "gpu_invoked": False, "queue_mutation": 0, "worker_started": False, "registry_mutation": 0, "ledger_mutation": 0, "denominator_mutation": 0, "qualification_credit": 0}, "retained_facts": {"r003_constantsdef_contract_passed_before_gencase": True, "hswl_explicit_auto_zero": True, "generated_fixed_boundary_particle_count": 512, "generated_fluid_particle_count": 6656, "generated_bi4_present_nonempty": True, "control_csv_copy_warning": warning, "native_decode_not_invoked": "mandatory control-copy hash gate failed before decoder admission", "boundary_normals": "not inspected: no native decode is permitted after failed control-copy hard gate"}, "evidence": evidence}


def verify_audit(path: Path = OUTPUT) -> dict[str, Any]:
    audit = load(path)
    require(audit.get("schema") == SCHEMA and audit.get("status") == "retained_hard_failure_no_retry_zero_credit", "audit status changed")
    require(audit == build_audit(), "postrun audit no longer matches read-only retained evidence")
    return audit


def write_audit(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite immutable F8 r003 postrun audit: {target}")
    audit = build_audit(); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


if __name__ == "__main__":
    audit = write_audit()
    print(json.dumps({key: audit[key] for key in ("schema", "status", "qualification_credit")}, sort_keys=True))
