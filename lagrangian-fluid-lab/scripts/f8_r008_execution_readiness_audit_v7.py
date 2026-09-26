#!/usr/bin/env python3
"""Bind the V18 terminal fanotify profile correction without granting runtime readiness."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts import f8_r008_terminal_fanotify_profile_verifier_v1 as fanotify_profiles


ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
V6_RECEIPT = ROOT / "t1-execution-readiness-audit-v6/receipt.json"
OUTPUT = LAB / ROOT / "t1-execution-readiness-audit-v7/receipt.json"
SCHEMA = "core.cfd.f8.r008_execution_readiness_audit.v7"
RECORD_ID = "f8-r008-execution-readiness-audit-v7"
MAX_EVIDENCE_BYTES = 128 * 1024 * 1024
V17 = fanotify_profiles.V17
V18 = fanotify_profiles.V18
PROFILE_MANIFEST = fanotify_profiles.MANIFEST
EVIDENCE_PATHS = (
    Path("scripts/f8_r008_terminal_fanotify_profile_verifier_v1.py"),
    Path("tests/test_f8_r008_terminal_fanotify_profile_verifier_v1.py"),
)
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class ReadinessAuditError(ValueError):
    """The versioned R008 terminal profile readiness evidence is inconsistent."""


def _read_from_root(root: Path, parts: tuple[str, ...], display: str) -> tuple[bytes, dict[str, Any]]:
    opened: list[int] = []
    try:
        parent_fd = os.open(root, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        opened.append(parent_fd)
        for component in parts[:-1]:
            parent_fd = os.open(component, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
            opened.append(parent_fd)
        descriptor = os.open(parts[-1], os.O_RDONLY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
        opened.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ReadinessAuditError(f"readiness evidence must be a single-link regular file: {display}")
        if before.st_size > MAX_EVIDENCE_BYTES:
            raise ReadinessAuditError(f"readiness evidence exceeds the byte limit: {display}")
        chunks: list[bytes] = []
        size = 0
        while True:
            block = os.read(descriptor, min(1024 * 1024, MAX_EVIDENCE_BYTES + 1 - size))
            if not block:
                break
            size += len(block)
            if size > MAX_EVIDENCE_BYTES:
                raise ReadinessAuditError(f"readiness evidence exceeds the byte limit: {display}")
            chunks.append(block)
        after = os.fstat(descriptor)
        named = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
        identity = lambda value: (
            value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns, value.st_nlink,
        )
        if identity(before) != identity(after) or identity(after) != identity(named) or size != before.st_size:
            raise ReadinessAuditError(f"readiness evidence changed while being read: {display}")
        payload = b"".join(chunks)
        return payload, {"path": display, "bytes": size, "sha256": hashlib.sha256(payload).hexdigest()}
    except OSError as error:
        raise ReadinessAuditError(f"cannot safely open readiness evidence beneath pinned root: {display}") from error
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _read_beneath_lab(relative: str | Path) -> tuple[bytes, dict[str, Any]]:
    raw_path = str(relative)
    path = Path(raw_path)
    if path.is_absolute() or path.as_posix() != raw_path or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ReadinessAuditError("readiness evidence path must be canonical and beneath the lab root")
    return _read_from_root(LAB, path.parts, path.as_posix())


def _read_regular(relative: str | Path) -> tuple[bytes, dict[str, Any]]:
    raw_path = str(relative)
    path = Path(raw_path)
    if not path.is_absolute():
        return _read_beneath_lab(raw_path)
    if path.as_posix() != raw_path or any(part in {".", ".."} for part in path.parts):
        raise ReadinessAuditError("absolute receipt path must be canonical")
    parts = path.parts[1:]
    if not parts:
        raise ReadinessAuditError("absolute receipt path must name a regular file")
    return _read_from_root(Path("/"), parts, path.as_posix())


def _load_json(relative: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw, reference = _read_regular(relative)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadinessAuditError(f"readiness evidence is not strict UTF-8 JSON: {relative}") from error
    if not isinstance(value, dict):
        raise ReadinessAuditError(f"readiness evidence must be a JSON object: {relative}")
    return value, reference


def _add_evidence(inventory: dict[str, dict[str, Any]], relative: str | Path, role: str) -> None:
    _, reference = _read_beneath_lab(relative)
    path = reference["path"]
    if path in inventory:
        current = inventory[path]
        if current["sha256"] != reference["sha256"] or current["bytes"] != reference["bytes"]:
            raise ReadinessAuditError(f"evidence path has conflicting bindings: {path}")
        current["role"] += f" | {role}"
        return
    inventory[path] = {**reference, "role": role}


def build_audit() -> dict[str, Any]:
    predecessor, predecessor_ref = _load_json(V6_RECEIPT)
    if not (
        predecessor.get("schema") == "core.cfd.f8.r008_execution_readiness_audit.v6"
        and predecessor.get("record_id") == "f8-r008-execution-readiness-audit-v6"
        and predecessor.get("status") == "static_diagnostic_matrix_reviewed_execution_trust_and_t1_pending"
        and predecessor.get("readiness_pass") is False
        and predecessor.get("full_t1_decision") is False
        and predecessor.get("T1_numerical") is False
        and type(predecessor.get("qualification_credit")) is int
        and predecessor.get("qualification_credit") == 0
    ):
        raise ReadinessAuditError("historical R008 readiness v6 must retain its zero-credit hold")
    if predecessor.get("qualification_claim") != "none" or predecessor.get("scope_id") != "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008":
        raise ReadinessAuditError("historical R008 readiness v6 has an unexpected scope or qualification claim")
    expected_v6_gaps = {
        "trusted_worker_execution_source_and_runtime_identity_missing",
        "real_provenance_verified_15_case_t1_results_missing",
        "native_integrity_and_solver_timestep_adjudication_missing",
    }
    if {item.get("code") for item in predecessor.get("blocking_gaps", []) if isinstance(item, dict)} != expected_v6_gaps:
        raise ReadinessAuditError("historical R008 readiness v6 blocker set changed")
    previous_evidence = predecessor.get("evidence")
    if not isinstance(previous_evidence, list) or not previous_evidence:
        raise ReadinessAuditError("historical R008 readiness v6 lacks its evidence inventory")
    previous_by_path: dict[str, dict[str, Any]] = {}
    for prior in previous_evidence:
        if not isinstance(prior, dict) or not isinstance(prior.get("path"), str):
            raise ReadinessAuditError("historical v6 evidence inventory contains a malformed item")
        path = prior["path"]
        if path in previous_by_path:
            raise ReadinessAuditError(f"historical v6 evidence inventory duplicates a path: {path}")
        _, current_ref = _read_beneath_lab(path)
        if type(prior.get("bytes")) is not int or not isinstance(prior.get("sha256"), str) or len(prior["sha256"]) != 64:
            raise ReadinessAuditError(f"historical v6 evidence ref has an invalid digest/size type: {path}")
        if current_ref["sha256"] != prior.get("sha256") or current_ref["bytes"] != prior.get("bytes"):
            raise ReadinessAuditError(f"historical v6 evidence binding is stale: {path}")
        previous_by_path[path] = prior
    for role_key in ("implementation", "test"):
        binding = predecessor.get(role_key)
        if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
            raise ReadinessAuditError(f"historical v6 {role_key} binding is missing")
        prior = previous_by_path.get(binding["path"])
        if prior is None or prior.get("sha256") != binding.get("sha256") or prior.get("bytes") != binding.get("bytes"):
            raise ReadinessAuditError(f"historical v6 {role_key} is not included in its evidence inventory")

    profile_verification = fanotify_profiles.verify_profiles()
    if not (
        profile_verification.get("status") == "static_profile_schema_pass_no_runtime_conformance"
        and profile_verification.get("pidfd_required_for_both_groups") is True
        and profile_verification.get("target_abi_raw_values_pinned") is False
        and profile_verification.get("pinned_kernel_conformance_passed") is False
        and profile_verification.get("fanotify_syscall_invoked") is False
        and profile_verification.get("readiness_pass") is False
        and profile_verification.get("qualification_credit") == 0
    ):
        raise ReadinessAuditError("terminal fanotify profile verification must remain static and zero-credit")

    inventory: dict[str, dict[str, Any]] = {}
    for prior in previous_evidence:
        path = prior.get("path") if isinstance(prior, dict) else None
        if not isinstance(path, str):
            raise ReadinessAuditError("v6 evidence inventory contains a malformed path")
        _, current_ref = _read_beneath_lab(path)
        if current_ref["sha256"] != prior.get("sha256") or current_ref["bytes"] != prior.get("bytes"):
            raise ReadinessAuditError(f"transitive v6 evidence binding is stale: {path}")
        _add_evidence(inventory, path, f"transitive_v6:{prior.get('role', path)}")
    _add_evidence(inventory, V6_RECEIPT, "immutable_historical_v6_readiness_receipt")
    for path, role in (
        (PROFILE_MANIFEST, "proposal-only terminal fanotify profile manifest"),
        (V17, "historical V17 terminal evidence contract"),
        (V18, "current additive V18 capability overlay"),
        ("scripts/f8_r008_terminal_fanotify_profile_verifier_v1.py", "static profile schema verifier"),
        ("tests/test_f8_r008_terminal_fanotify_profile_verifier_v1.py", "static profile verifier tests"),
        ("scripts/f8_r008_execution_readiness_audit_v7.py", "this readiness audit implementation"),
        ("tests/test_f8_r008_execution_readiness_audit_v7.py", "this readiness audit tests"),
    ):
        _add_evidence(inventory, path, role)

    blocking_gaps = list(predecessor["blocking_gaps"])
    blocking_gaps.extend([
        {
            "code": "terminal_fanotify_profiles_lack_pinned_kernel_runtime_conformance",
            "severity": "high",
            "detail": "The V17/V18 static profiles are schema-checked only; target-ABI raw flags, privileged group creation, marks, FID/PIDFD parser vectors, filesystem joins, queue bounds, and pinned-kernel conformance remain untested.",
        },
        {
            "code": "trusted_terminal_supervisor_and_final_fput_observer_missing",
            "severity": "high",
            "detail": "No trusted supervisor/responder or implemented and independently verified final-fput observer/join exists; the static profile manifest cannot authenticate a runtime attempt.",
        },
    ])
    evidence = sorted(inventory.values(), key=lambda item: item["path"])
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "scope_id": "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008",
        "status": "static_terminal_fanotify_profiles_reviewed_runtime_readiness_blocked",
        "supersedes": {
            "path": V6_RECEIPT.as_posix(),
            "sha256": predecessor_ref["sha256"],
            "reason": "V7 mechanically binds the V17 historical profile and V18 capability overlay to a strict proposal-only JSON profile verifier; no runtime conformance or qualification gate is cleared.",
        },
        "predecessor_v6": {
            "receipt_preserved": True,
            "receipt_integrity": "source_bound_evidence_reverified",
            "readiness_pass": False,
            "qualification_credit": 0,
        },
        "terminal_fanotify_profile_verification": profile_verification,
        "execution_authority": {
            "solver": False,
            "worker": False,
            "gpu": False,
            "queue": False,
            "root_or_capability_probe": False,
            "fanotify_init_or_mark": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "execution_controls": {
            "solver_invoked": False,
            "worker_started": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "root_or_capability_probe": False,
            "fanotify_init_or_mark": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "native_integrity_adjudicated": False,
        "solver_timestep_audit_adjudicated": False,
        "readiness_pass": False,
        "full_t1_decision": False,
        "T1_numerical": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "blocking_gaps": blocking_gaps,
        "evidence": evidence,
        "implementation": {
            "path": "scripts/f8_r008_execution_readiness_audit_v7.py",
            **_read_regular("scripts/f8_r008_execution_readiness_audit_v7.py")[1],
        },
        "test": {
            "path": "tests/test_f8_r008_execution_readiness_audit_v7.py",
            **_read_regular("tests/test_f8_r008_execution_readiness_audit_v7.py")[1],
        },
    }


def verify_audit(path: str | Path = OUTPUT) -> dict[str, Any]:
    receipt, _ = _load_json(Path(path))
    if receipt.get("schema") != SCHEMA or receipt != build_audit():
        raise ReadinessAuditError("R008 execution-readiness audit v7 no longer matches its pinned evidence")
    return receipt


def _write_new_file_at(parent_fd: int, name: str, payload: bytes, display: str) -> None:
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644, dir_fd=parent_fd)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("short write while creating immutable audit receipt")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.fsync(parent_fd)
    except BaseException:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise


def _write_test_receipt(target: Path) -> Path:
    """Private temporary-target helper; the public writer cannot select a path."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable R008 execution-readiness audit v7: {target}")
    payload = (json.dumps(build_audit(), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    parent_fd = os.open(target.parent, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
    try:
        _write_new_file_at(parent_fd, target.name, payload, target.as_posix())
    finally:
        os.close(parent_fd)
    return target


def write_audit() -> Path:
    """Create the single immutable V7 receipt at the fixed lab-relative location."""
    relative = OUTPUT.relative_to(LAB)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReadinessAuditError("fixed V7 output path escaped the lab root")
    payload = (json.dumps(build_audit(), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    opened: list[int] = []
    try:
        parent_fd = os.open(LAB, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        opened.append(parent_fd)
        for component in relative.parts[:-1]:
            try:
                os.mkdir(component, 0o755, dir_fd=parent_fd)
            except FileExistsError:
                pass
            parent_fd = os.open(component, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC, dir_fd=parent_fd)
            opened.append(parent_fd)
        _write_new_file_at(parent_fd, relative.parts[-1], payload, relative.as_posix())
    finally:
        for fd in reversed(opened):
            os.close(fd)
    return OUTPUT


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable R008 readiness v7 receipt once at its fixed path")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_audit().relative_to(LAB))
    else:
        print(json.dumps(build_audit(), indent=2, sort_keys=True))
