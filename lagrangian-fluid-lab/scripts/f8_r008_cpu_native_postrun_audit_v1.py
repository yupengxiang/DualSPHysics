#!/usr/bin/env python3
"""Read-only closure audit for the immutable F8 R008 CPU/native preflight."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any


LAB = Path(__file__).resolve().parents[1]
CASE = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
PREFLIGHT = CASE / "cpu-native-preflight-v3"
OUTPUT = LAB / CASE / "cpu-native-postrun-audit-v1/receipt.json"
SCHEMA = "core.cfd.f8.r008_cpu_native_postrun_audit.v1"
MEMORY_CAP_BYTES = 4 * 1024**3


def _read_stable(path: Path) -> bytes:
    path = Path(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"expected a regular evidence file: {path}")
        payload = stream.read()
        after = os.fstat(stream.fileno())
    signature_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    signature_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if signature_before != signature_after or len(payload) != before.st_size:
        raise RuntimeError(f"evidence changed while being read: {path}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(_read_stable(path).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _verify_binding(reference: dict[str, Any]) -> dict[str, Any]:
    relative = Path(reference["path"])
    _require(not relative.is_absolute() and ".." not in relative.parts, "artifact reference escapes the repository")
    path = LAB / relative
    cursor = LAB
    for component in relative.parts:
        cursor = cursor / component
        _require(not cursor.is_symlink(), f"symlink in artifact reference: {relative}")
    payload = _read_stable(path)
    digest = hashlib.sha256(payload).hexdigest()
    _require(len(payload) == reference["bytes"], f"artifact size mismatch: {relative}")
    _require(digest == reference["sha256"], f"artifact hash mismatch: {relative}")
    return {
        "path": relative.as_posix(),
        "bytes": len(payload),
        "sha256": digest,
        "role": reference.get("role", "receipt-bound artifact"),
    }


def _collect_references(value: Any, found: dict[str, dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if {"path", "bytes", "sha256"}.issubset(value):
            path = value["path"]
            previous = found.get(path)
            if previous is not None:
                _require(
                    previous["bytes"] == value["bytes"] and previous["sha256"] == value["sha256"],
                    f"conflicting receipt bindings for {path}",
                )
            else:
                found[path] = value
        for item in value.values():
            _collect_references(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_references(item, found)


def _verify_stage(stage: dict[str, Any], label: str) -> None:
    _require(stage.get("resource_gate_pass") is True, f"{label} resource gate did not pass")
    _require(stage.get("native_payload_invoked") is True, f"{label} native payload was not invoked")
    _require(stage.get("native_return_code") == 0, f"{label} native payload failed")
    _require(stage.get("systemd_run_return_code") == 0, f"{label} systemd scope failed")
    _require(stage.get("scope_process_tree_clean") is True, f"{label} process tree was not clean")
    _require(stage.get("timed_out") is False, f"{label} timed out")
    wrapper = stage.get("wrapper_receipt", {})
    _require(wrapper.get("child_return_code") == 0, f"{label} wrapper reports a failed child")
    _require(wrapper.get("scope_process_tree_clean") is True, f"{label} wrapper reports a dirty process tree")
    _require(wrapper.get("timed_out") is False, f"{label} wrapper reports a timeout")
    _require(wrapper.get("native_child_single_cpu_affinity_requested") is True, f"{label} was not restricted to one CPU")
    _require(wrapper.get("residual_scope_pids_after_cleanup") == [], f"{label} left processes behind")
    metrics = stage.get("memory", {})
    _require(metrics.get("cgroup_v2") is True, f"{label} did not use cgroup v2")
    _require(metrics.get("memory_max_bytes") == MEMORY_CAP_BYTES, f"{label} memory cap changed")
    _require(metrics.get("cap_pressure_observed") is False, f"{label} observed memory cap pressure")
    _require(metrics.get("oom_observed") is False, f"{label} observed OOM")
    _require(metrics.get("memory_peak_bytes", MEMORY_CAP_BYTES + 1) <= MEMORY_CAP_BYTES, f"{label} exceeded memory cap")
    events = metrics.get("memory_events", {})
    _require(all(events.get(key) == 0 for key in ("high", "max", "oom", "oom_kill", "oom_group_kill")), f"{label} cgroup recorded memory pressure")


def build_audit() -> dict[str, Any]:
    preflight_root = LAB / PREFLIGHT
    receipt_path = preflight_root / "receipt.json"
    lock_path = preflight_root / "one-shot-lock.json"
    receipt = _load_json(receipt_path)
    lock = _load_json(lock_path)

    _require(receipt.get("schema") == "core.cfd.f8.r008_cpu_native_preflight.v1", "unexpected R008 receipt schema")
    _require(receipt.get("scope_id") == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008", "receipt scope changed")
    _require(receipt.get("status") == "cpu_native_preflight_passed_zero_credit", "R008 CPU/native preflight did not pass")
    _require(receipt.get("qualification_claim") == "none" and receipt.get("qualification_credit") == 0, "R008 preflight claims qualification credit")
    _require(lock.get("schema") == "core.cfd.f8.r008_cpu_native_preflight_lock.v1", "one-shot lock schema changed")
    _require(lock.get("same_input_retry") is False, "same-input retry is not forbidden")
    _require(lock.get("gencase_invocation_budget") == 1 and lock.get("native_decode_invocation_budget") == 1, "one-shot budgets changed")
    _require(lock.get("solver_invocation_budget") == 0, "one-shot lock grants solver invocation")

    controls = receipt.get("execution_controls", {})
    _require(controls.get("cpu_gencase_invoked") is True and controls.get("native_decode_invoked") is True, "required CPU/native stages are not closed")
    _require(controls.get("solver_invoked") is False and controls.get("gpu_invoked") is False, "solver or GPU was invoked")
    _require(controls.get("worker_started") is False and controls.get("training_started") is False, "worker or training was started")
    _require(all(controls.get(key) == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation", "qualification_credit")), "forbidden accounting mutation occurred")

    admission = receipt.get("resource_admission", {})
    snapshot = admission.get("snapshot", {})
    _require(admission.get("status") == "passed_at_launch", "launch resource admission did not pass")
    _require(snapshot.get("cgroup_v2_unified") is True and snapshot.get("cgroup_v2_memory_controller") is True, "cgroup v2 resource gate changed")
    _require(snapshot.get("systemd_user_manager_responsive") is True and snapshot.get("systemd_scope_names_available") is True, "systemd resource gate changed")
    _require(snapshot.get("f3_material_row30_pids") == [] and snapshot.get("occupied_transient_scope_units") == [], "conflicting worker or scope was present at launch")
    cpus = snapshot.get("cpu_affinity_count", 0)
    loads = snapshot.get("load_average_1_5_15_min", [])
    _require(cpus >= 1 and len(loads) == 3 and loads[0] <= cpus, "recorded CPU/load gate did not pass")
    _require(snapshot.get("mem_available_bytes", 0) >= 8 * 1024**3, "recorded available-memory gate did not pass")
    _require(snapshot.get("filesystem_free_bytes", 0) >= 8 * 1024**3, "recorded free-disk gate did not pass")

    _verify_stage(receipt.get("gencase", {}), "GenCase")
    _verify_stage(receipt.get("native_decode", {}), "native decode")
    generated = receipt.get("generated_audit", {})
    _require(generated.get("pass") is True and generated.get("missing_artifacts") == [], "generated geometry/control audit failed")
    _require(generated.get("control_copy_hash_matches") is True, "generated control copy does not match")
    _require(generated.get("geometry_audit", {}).get("pass") is True, "generated geometry audit failed")
    _require(all(generated.get("geometry_audit", {}).get("checks", {}).values()), "one or more generated geometry checks failed")
    native = receipt.get("native_audit", {})
    _require(native.get("pass") is True, "native-array audit failed")
    _require(all(native.get("checks", {}).values()), "one or more native-array checks failed")
    _require(native.get("native", {}).get("boundary_particles") == 4096, "native boundary count changed")
    _require(native.get("native", {}).get("fluid_particles") == 6656, "native fluid count changed")
    _require(native.get("native", {}).get("total_particles") == 10752, "native total particle count changed")

    references: dict[str, dict[str, Any]] = {}
    _collect_references(receipt, references)
    verified = [_verify_binding(references[path]) for path in sorted(references)]
    receipt_binding = {
        "path": (CASE / "cpu-native-preflight-v3/receipt.json").as_posix(),
        "bytes": (LAB / receipt_path).stat().st_size,
        "sha256": hashlib.sha256(_read_stable(receipt_path)).hexdigest(),
        "role": "immutable CPU/native preflight receipt",
    }
    audit_script = Path(__file__).relative_to(LAB)
    audit_test = Path("tests/test_f8_r008_cpu_native_postrun_audit_v1.py")
    for path, role in ((audit_script, "read-only postrun audit builder"), (audit_test, "postrun audit regression tests")):
        source = LAB / path
        payload = _read_stable(source)
        verified.append({"path": path.as_posix(), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "role": role})

    return {
        "schema": SCHEMA,
        "record_id": "f8-oscillatory-pressure-channel-r008-cpu-native-postrun-audit-v1",
        "scope_id": receipt["scope_id"],
        "status": "cpu_native_preflight_verified_zero_credit_no_solver_authorized",
        "audit_mode": "strictly_read_only_against_r008_cpu_native_preflight_v3",
        "qualification_claim": "none",
        "qualification_credit": 0,
        "execution_boundary": {
            "gencase_invocations_confirmed": 1,
            "native_decode_invocations_confirmed": 1,
            "solver_invoked": False,
            "gpu_invoked": False,
            "worker_started": False,
            "training_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
            "same_input_retry_forbidden": True,
            "solver_invocation_authorized": False,
        },
        "verified_result": {
            "fixed_boundary_particles": 4096,
            "fluid_particles": 6656,
            "total_particles": 10752,
            "fluid_mass_kg": native["native"]["fluid_mass_kg"],
            "generated_geometry_pass": True,
            "native_decode_pass": True,
            "gencase_peak_memory_bytes": receipt["gencase"]["memory"]["memory_peak_bytes"],
            "native_decode_peak_memory_bytes": receipt["native_decode"]["memory"]["memory_peak_bytes"],
        },
        "source_receipt": receipt_binding,
        "verified_reference_count": len(references),
        "evidence": verified,
    }


def verify_audit(path: Path = OUTPUT) -> dict[str, Any]:
    audit = _load_json(path)
    _require(audit.get("schema") == SCHEMA, "unexpected R008 postrun audit schema")
    _require(audit.get("status") == "cpu_native_preflight_verified_zero_credit_no_solver_authorized", "R008 audit status changed")
    _require(audit == build_audit(), "R008 postrun audit no longer matches retained evidence")
    return audit


def write_audit(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 postrun audit: {target}")
    audit = build_audit()
    payload = (json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return audit


if __name__ == "__main__":
    result = write_audit()
    print(json.dumps({key: result[key] for key in ("schema", "status", "verified_reference_count", "qualification_credit")}, sort_keys=True))
