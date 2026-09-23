#!/usr/bin/env python3
"""Reconcile the third-T1 frontier after the completed F8 R008 CPU preflight.

This version preserves the earlier frontier audits as historical snapshots and
binds the immutable R008 execution receipt, one-shot lock, and read-only
postrun audit.  It does not confer solver admission or T1 qualification.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from scripts import core_third_t1_frontier_audit_v3 as _previous
from scripts import f8_r008_cpu_native_postrun_audit_v1 as _postrun


LAB = Path(__file__).resolve().parents[1]
OUTPUT = LAB / "campaigns/core-v1/evidence/core-third-t1-frontier-audit-20260924-v4.json"
F8 = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
PREFLIGHT = F8 / "cpu-native-preflight-v3"
POSTRUN = F8 / "cpu-native-postrun-audit-v1/receipt.json"
STATUS_UPDATE = Path("reports/CORE-CONTINUATION-STATUS-2026-09-24-UPDATE-02.zh-CN.md")
SCHEMA = "core.third_t1.frontier_audit.v4"
SCOPE_ID = "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008"


def _read_stable(path: Path) -> bytes:
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


def _bind(relative: Path, role: str) -> dict[str, Any]:
    path = LAB / relative
    payload = _read_stable(path)
    return {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "role": role,
    }


def build_audit() -> dict[str, Any]:
    # Verify the already-materialized postrun audit against all retained inputs.
    # This path is read-only and does not open trajectories or run native tools.
    postrun = _postrun.verify_audit(LAB / POSTRUN)
    if not (
        postrun.get("schema") == "core.cfd.f8.r008_cpu_native_postrun_audit.v1"
        and postrun.get("scope_id") == SCOPE_ID
        and postrun.get("status") == "cpu_native_preflight_verified_zero_credit_no_solver_authorized"
        and postrun.get("qualification_credit") == 0
        and postrun.get("qualification_claim") == "none"
    ):
        raise ValueError("R008 postrun audit does not establish the expected zero-credit result")
    boundary = postrun.get("execution_boundary", {})
    if not (
        boundary.get("gencase_invocations_confirmed") == 1
        and boundary.get("native_decode_invocations_confirmed") == 1
        and boundary.get("solver_invoked") is False
        and boundary.get("solver_invocation_authorized") is False
        and boundary.get("gpu_invoked") is False
        and boundary.get("worker_started") is False
        and boundary.get("training_started") is False
        and boundary.get("same_input_retry_forbidden") is True
        and all(boundary.get(key) == 0 for key in (
            "queue_mutation", "registry_mutation", "ledger_mutation",
            "denominator_mutation"))
    ):
        raise ValueError("R008 postrun audit execution boundary changed")

    receipt_relative = PREFLIGHT / "receipt.json"
    lock_relative = PREFLIGHT / "one-shot-lock.json"
    receipt = json.loads(_read_stable(LAB / receipt_relative).decode("utf-8"))
    lock = json.loads(_read_stable(LAB / lock_relative).decode("utf-8"))
    if not (
        receipt.get("scope_id") == SCOPE_ID
        and receipt.get("status") == "cpu_native_preflight_passed_zero_credit"
        and lock.get("same_input_retry") is False
        and lock.get("gencase_invocation_budget") == 1
        and lock.get("native_decode_invocation_budget") == 1
        and lock.get("solver_invocation_budget") == 0
    ):
        raise ValueError("R008 immutable receipt or one-shot lock changed")
    if postrun.get("source_receipt", {}).get("path") != receipt_relative.as_posix():
        raise ValueError("postrun audit is not bound to the R008 one-shot receipt")

    value = copy.deepcopy(_previous.build_audit())
    value["schema"] = SCHEMA
    value["status"] = "user_selected_candidate_cpu_native_preflight_complete_t1_qualification_pending"
    value["decision"] = (
        "record_exactly_one_successful_zero_credit_f8_r008_cpu_native_preflight; "
        "keep_core_incomplete_and_require_separate_solver_t1_admission"
    )
    value["execution_controls"].update({
        "gencase_invoked": True,
        "native_decode_invoked": True,
        "solver_invoked": False,
        "gpu_started": False,
        "worker_started": False,
        "training_started": False,
        "preflight_output_namespace_created_as_of_bound_update": True,
        "preflight_one_shot_authorization_consumed": True,
        "cpu_native_preflight_invocation_count": 1,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "denominator_mutation": 0,
        "qualification_credit": 0,
    })
    f8 = value["route_decisions"]["F8"]
    f8.update({
        "cpu_native_preflight_authorization_status": f8["cpu_native_preflight_status"],
        "cpu_native_preflight_status": postrun["status"],
        "cpu_native_preflight_completed": True,
        "cpu_native_preflight_one_shot_consumed": True,
        "cpu_native_preflight_invocations": 1,
        "same_input_retry_forbidden": True,
        "cpu_native_preflight_result": copy.deepcopy(postrun["verified_result"]),
        "solver_t1_execution_authorized": False,
        "t1_solver_admission_granted": False,
        "t1_qualification": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "next_allowed_action": (
            "prepare/review a separate solver and T1 admission package; no solver, "
            "GPU, worker, or qualification run is authorized by the completed CPU/native preflight"
        ),
    })

    # Mark the preflight-pending v3 inputs as historical rather than current.
    for item in value["evidence"]:
        if item["role"] == "latest bound status: preflight deferred by live resource gates; no runtime namespace or consumed lock":
            item["role"] = "historical Sep 23 status snapshot: R008 preflight deferred before its later authorized run"
        elif item["role"] == "R008 conditional resource-admission decision":
            item["role"] = "historical R008 preflight-stage conditional resource admission; not the later launch snapshot"
    value["evidence"].extend([
        _bind(Path("campaigns/core-v1/evidence/core-third-t1-frontier-audit-20260923-v3.json"),
              "immutable v3 frontier snapshot from before the R008 CPU/native preflight"),
        _bind(receipt_relative, "immutable R008 CPU/native preflight execution receipt; exactly one invocation per native stage"),
        _bind(lock_relative, "consumed R008 one-shot lock; same-input retry forbidden and solver budget zero"),
        _bind(POSTRUN, "strict read-only postrun closure audit for the R008 CPU/native preflight"),
        _bind(STATUS_UPDATE, "continuation status including completed R008 CPU/native preflight and zero-credit boundary"),
        _bind(Path(__file__).resolve().relative_to(LAB), "v4 post-preflight frontier audit writer"),
        _bind(Path("tests/test_core_third_t1_frontier_audit_v4.py"), "v4 post-preflight frontier audit regression tests"),
    ])
    return value


def write_audit(path: Path = OUTPUT) -> dict[str, Any]:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 post-preflight frontier audit: {target}")
    audit = build_audit()
    payload = (json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return audit


def verify_audit(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(_read_stable(Path(path)).decode("utf-8"))
    if value.get("schema") != SCHEMA:
        raise ValueError("unexpected v4 third-T1 frontier audit schema")
    if value != build_audit():
        raise ValueError("v4 third-T1 frontier audit no longer matches retained evidence")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = write_audit(args.output)
    print(json.dumps({key: result[key] for key in (
        "schema", "status", "current_t1_families", "third_family_established",
        "qualification_credit", "execution_controls")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
