#!/usr/bin/env python3
"""Independent read-only security re-audit for the admission/runner v2 fixes.

The audit reads the current source files through stable read-only descriptors
and inspects their Python AST/text.  It never imports the audited modules, so
it cannot call their resource probe, ``Popen``, evaluator, CUDA, or HDF5
execution paths.  The only permitted write is an explicitly requested,
exclusive JSON audit report.

This is a non-authorizing review.  It records the controls closed by
``a3fe77d3``/``6e1ceb33``/``d0e5fbd8`` and keeps ``launch_allowed`` and all
formal credit fields false/zero.  A local filesystem marker is not treated as
an external scheduler authority, and a static source review is not terminal
execution proof.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
DATE_TAG = "2026-09-29"
REPORT_SCHEMA = (
    "core.f3.graph_raw.hidden16.diagnostic_admission_v3.security_reaudit.report.v1"
)
REPORT_ID = "f3-graph-raw-hidden16-diagnostic-admission-v3-security-reaudit-v1"
AUDITED_COMMITS = ("a3fe77d3", "6e1ceb33", "d0e5fbd8")
MAX_SOURCE_BYTES = 8 * 1024 * 1024
SHA256_HEX = 64

ZERO_CREDIT: dict[str, Any] = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}

AUDITED_FILES: tuple[tuple[str, Path], ...] = (
    (
        "admission_v1_after_p1_fixes",
        LAB_ROOT
        / "scripts/f3_graph_raw_hidden16_seed17_diagnostic_admission_v1.py",
    ),
    (
        "runner_v2_after_p1_fixes",
        LAB_ROOT / "scripts/f3_graph_raw_hidden16_seed17_diagnostic_runner_v2.py",
    ),
    (
        "rollout_launcher_dependency",
        LAB_ROOT
        / "scripts/f3_graph_raw_hidden16_current_manifest_rollout_launcher_v1.py",
    ),
    (
        "resource_admission_dependency",
        LAB_ROOT
        / "scripts/f3_graph_raw_hidden16_current_manifest_audited_executor_v1.py",
    ),
    (
        "hdf5_hardening_dependency",
        LAB_ROOT / "scripts/f3_graph_terminal_validator_security_hardening_v1.py",
    ),
)


class ReauditError(ValueError):
    """The source audit cannot safely make a claim."""


def _fail(message: str) -> None:
    raise ReauditError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _read_source(path: Path, role: str) -> tuple[str, dict[str, Any]]:
    """Read one source file once from an O_NOFOLLOW descriptor."""

    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        _fail(f"{role} cannot be resolved: {error}")
    if resolved != path or not _under(resolved, LAB_ROOT):
        _fail(f"{role} is outside the repository or uses a symlinked path")
    try:
        info = os.lstat(resolved)
    except OSError as error:
        _fail(f"{role} cannot be inspected: {error}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"{role} must be a regular non-symlink file")
    if info.st_nlink != 1 or info.st_size < 1 or info.st_size > MAX_SOURCE_BYTES:
        _fail(f"{role} has an unsafe size or hard-link count")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as error:
        _fail(f"{role} cannot be opened read-only: {error}")
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_SOURCE_BYTES:
            block = os.read(
                descriptor,
                min(1024 * 1024, MAX_SOURCE_BYTES + 1 - total),
            )
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after = os.fstat(descriptor)
    except OSError as error:
        _fail(f"{role} cannot be read: {error}")
    finally:
        os.close(descriptor)

    raw = b"".join(chunks)
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_nlink,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_nlink,
    )
    if before_identity != after_identity or len(raw) != before.st_size:
        _fail(f"{role} changed during the bounded read")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail(f"{role} is not UTF-8 source: {error}")
    return text, {
        "role": role,
        "path": str(resolved.relative_to(LAB_ROOT)),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "dev": int(before.st_dev),
        "ino": int(before.st_ino),
        "nlink": int(before.st_nlink),
        "mtime_ns": int(before.st_mtime_ns),
        "content_opened": True,
    }


def _parse(text: str, role: str) -> ast.Module:
    try:
        return ast.parse(text, filename=role, mode="exec")
    except SyntaxError as error:
        _fail(f"{role} is not parseable Python: {error}")


def _locations(text: str, needles: Sequence[str]) -> dict[str, list[int]]:
    lines = text.splitlines()
    return {
        needle: [index for index, line in enumerate(lines, start=1) if needle in line][:8]
        for needle in needles
    }


def _function_segment(tree: ast.Module, text: str, name: str) -> str:
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(nodes) != 1:
        _fail(f"expected exactly one function named {name!r}")
    node = nodes[0]
    lines = text.splitlines()
    end = getattr(node, "end_lineno", node.lineno)
    return "\n".join(lines[node.lineno - 1 : end])


def _call_names(tree: ast.AST) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            result.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            result.add(node.func.attr)
    return result


def _leading_fail(tree: ast.Module, name: str) -> bool:
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(nodes) != 1:
        return False
    body = list(nodes[0].body)
    if body and isinstance(body[0], ast.Expr) and isinstance(
        body[0].value, ast.Constant
    ) and isinstance(body[0].value.value, str):
        body.pop(0)
    if not body or not isinstance(body[0], ast.Expr):
        return False
    call = body[0].value
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_fail"
    )


def _dangerous_calls(tree: ast.AST) -> list[str]:
    dangerous = {
        "kill",
        "killpg",
        "terminate",
        "send_signal",
        "pkill",
        "systemctl",
        "reboot",
    }
    return sorted(_call_names(tree) & dangerous)


def _source_bundle() -> tuple[dict[str, str], dict[str, ast.Module], list[dict[str, Any]]]:
    texts: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    inventory: list[dict[str, Any]] = []
    for role, path in AUDITED_FILES:
        text, descriptor = _read_source(path, role)
        texts[role] = text
        trees[role] = _parse(text, role)
        inventory.append(descriptor)
    return texts, trees, inventory


def _static_checks(
    texts: Mapping[str, str], trees: Mapping[str, ast.Module]
) -> dict[str, Any]:
    admission = texts["admission_v1_after_p1_fixes"]
    runner = texts["runner_v2_after_p1_fixes"]
    launcher = texts["rollout_launcher_dependency"]
    resource = texts["resource_admission_dependency"]
    hardening = texts["hdf5_hardening_dependency"]

    admission_consume = _function_segment(
        trees["admission_v1_after_p1_fixes"], admission, "consume_receipt"
    )
    admission_mint = _function_segment(
        trees["admission_v1_after_p1_fixes"], admission, "mint_admission"
    )
    admission_resource = _function_segment(
        trees["admission_v1_after_p1_fixes"], admission, "_validate_resource"
    )
    launcher_reader = _function_segment(
        trees["rollout_launcher_dependency"], launcher, "_read_bounded_json"
    )
    runner_revalidate = _function_segment(
        trees["runner_v2_after_p1_fixes"], runner, "_revalidate_before_popen"
    )
    runner_popen = _function_segment(
        trees["runner_v2_after_p1_fixes"], runner, "_run_real_popen_wait"
    )
    runner_process_capture = _function_segment(
        trees["runner_v2_after_p1_fixes"], runner, "_capture_runtime_identity"
    )
    runner_report_validator = _function_segment(
        trees["runner_v2_after_p1_fixes"], runner, "validate_report"
    )
    gpu_probe = _function_segment(
        trees["resource_admission_dependency"], resource, "_query_gpu_rows"
    )

    stable_read = all(
        needle in admission
        for needle in (
            "def _open_parent_directory",
            "os.fstat(fd)",
            "O_NOFOLLOW",
            "dir_fd=parent_fd",
            "before.st_nlink != 1",
            "changed during read",
        )
    )
    stable_artifact_read = all(
        needle in runner
        for needle in (
            "def _stable_artifact",
            "os.fstat(leaf_fd)",
            "dir_fd=parent_fd",
            "before.st_nlink != 1",
            '"stable_fd": True',
            '"path_reopened": False',
        )
    )
    local_one_shot = all(
        needle in admission
        for needle in (
            "O_EXCL",
            "CONSUMPTION_LOCK_NAME",
            "CONSUMED_NAME",
            "def _validate_consumed_marker",
            "allow_consumed=False",
            "single-use admission has already been consumed or locked",
        )
    )
    owner_inode_nonce = all(
        needle in admission
        for needle in (
            "def _validate_owner",
            '"snapshot_nonce"',
            '"dev", "ino"',
            '"nonce"',
            '"uid", "gid", "host"',
        )
    )
    external_replay_authority = any(
        needle in admission.lower()
        for needle in (
            "replay_ledger",
            "scheduler_consume_token",
            "signed_consumption",
            "external_consumption_receipt",
        )
    )
    external_owner_attestation = any(
        needle in (admission + resource).lower()
        for needle in (
            "ed25519",
            "signature",
            "scheduler_attestation_token",
            "signed_scheduler",
            "trusted_scheduler_api",
        )
    )
    caller_supplied_resource = (
        "resource_admission: Mapping[str, Any] | None = None" in admission_mint
        and '"identity_attested"' in admission_resource
        and '"scheduler_owned_snapshot"' in admission_resource
    )
    launcher_path_reopen = (
        "os.lstat(candidate)" in launcher_reader
        and "os.open(candidate, flags)" in launcher_reader
        and "dir_fd" not in launcher_reader
    )
    admission_cross_binds_launcher_receipt = all(
        needle in admission
        for needle in (
            "plan.manifest_sha256",
            "checkpoint_descriptor[\"sha256\"]",
            "training_descriptor",
        )
    ) and "plan.training_receipt_sha256" in admission
    output_check_only = (
        "os.path.lexists(output)" in runner_revalidate
        and "_reserve_output" not in runner
        and "_reserve_artifact" not in runner
    )
    output_atomic_reservation = not output_check_only
    hdf5_nonhard_and_vds_closed = all(
        needle in hardening
        for needle in (
            "h5py.HardLink",
            "getlink=True",
            "is_virtual",
            "with h5py.File(io.BytesIO(raw), \"r\")",
        )
    ) and "hardening.inspect_hdf5_snapshot" in runner
    hdf5_external_storage_closed = any(
        needle in hardening
        for needle in (
            "dataset.external",
            'getattr(dataset, "external"',
            "external_storage_rejected",
        )
    )
    gpu_shape_bound = all(
        needle in admission
        for needle in (
            "GPU_UUID_RE",
            "PCI_BUS_RE",
            '"physical_index"',
            '"logical_index"',
            '"cuda_visible_devices"',
            '"cuda_device_order"',
            '"identity_sha256"',
        )
    )
    gpu_probe_identity = any(
        needle in gpu_probe.lower()
        for needle in ("uuid", "pci.bus", "pci_bus_id", "serial")
    )
    child_gpu_attestation = any(
        needle in runner_process_capture.lower()
        for needle in (
            "cuda.get_device_properties",
            "cuda device properties",
            "pci_bus_id",
            "gpu_uuid",
            "nvidia-smi",
        )
    )
    environment_closed = all(
        needle in runner
        for needle in (
            "allowlist_only_no_ambient_inheritance",
            '"inherit", False',
            "def _effective_environment",
            "def _environment_digest",
            "effective_env_sha256",
        )
    ) and "os.environ.copy()" not in runner
    executable_closed = all(
        needle in (admission + runner)
        for needle in (
            "MAX_EXECUTABLE_BYTES",
            '"sha256"',
            '"resolved_path"',
            "_stable_artifact(",
            'proc_root / "exe"',
        )
    )
    sealed_witness_closed = all(
        needle in runner
        for needle in (
            "_SEALED_POPEN",
            "_PROCESS_WITNESS_SECRET",
            "def _witness_seal",
            "def _validate_process_witness",
            "_DIAGNOSTIC_EXECUTION_CAPABILITY: object | None = None",
        )
    ) and _leading_fail(trees["runner_v2_after_p1_fixes"], "_run_real_popen_wait")
    formal_zero_credit = all(
        needle in (admission + runner)
        for needle in (
            "ZERO_CREDIT",
            '"launch_allowed": False',
            '"credit": 0',
            '"registry_writes": 0',
            '"ledger_writes": 0',
            '"gate_writes": 0',
            '"completion_writes": 0',
        )
    )
    terminal_report_is_bound = all(
        needle in runner_report_validator
        for needle in (
            '"diagnostic_terminal_verified"',
            '"popen_attempted"',
            '"wait_attempted"',
        )
    ) and all(
        needle in runner_report_validator
        for needle in ("terminal_receipt_sha256", "TERMINAL_RECEIPT_SCHEMA")
    )
    dangerous_calls = {
        role: _dangerous_calls(tree)
        for role, tree in trees.items()
    }

    return {
        "local_atomic_one_shot": local_one_shot,
        "owner_inode_nonce_binding": owner_inode_nonce,
        "external_replay_authority": external_replay_authority,
        "external_owner_attestation": external_owner_attestation,
        "caller_supplied_resource_snapshot": caller_supplied_resource,
        "admission_stable_fd_reads": stable_read,
        "launcher_path_based_preflight_reader": launcher_path_reopen,
        "admission_cross_binds_launcher_training_file_digest": admission_cross_binds_launcher_receipt,
        "runner_stable_fd_artifact_reads": stable_artifact_read,
        "runner_output_atomic_reservation_before_popen": output_atomic_reservation,
        "hdf5_nonhard_and_vds_rejection": hdf5_nonhard_and_vds_closed,
        "hdf5_external_storage_rejection": hdf5_external_storage_closed,
        "hdf5_external_soft_vds_external_storage_rejection": hdf5_nonhard_and_vds_closed and hdf5_external_storage_closed,
        "gpu_uuid_pci_logical_shape_bound": gpu_shape_bound,
        "gpu_probe_emits_uuid_pci_identity": gpu_probe_identity,
        "child_runtime_gpu_attestation": child_gpu_attestation,
        "allowlisted_environment_digest": environment_closed,
        "executable_content_and_runtime_identity": executable_closed,
        "sealed_real_popen_wait_witness": sealed_witness_closed,
        "terminal_report_receipt_identity_bound": terminal_report_is_bound,
        "formal_credit_isolation": formal_zero_credit,
        "dangerous_process_control_calls": dangerous_calls,
        "locations": {
            "admission_consumption": _locations(
                admission,
                [
                    "def consume_receipt",
                    "os.O_EXCL",
                    "def _validate_consumed_marker",
                ],
            ),
            "admission_owner_gpu": _locations(
                admission,
                [
                    "def _validate_owner",
                    "def _gpu_identity",
                    '"identity_attested"',
                ],
            ),
            "admission_read": _locations(
                admission,
                ["def _open_parent_directory", "def _read_file", "dir_fd=parent_fd"],
            ),
            "launcher_reader": _locations(
                launcher,
                ["def _read_bounded_json", "os.lstat(candidate)", "os.open(candidate, flags)"],
            ),
            "runner_output_gate": _locations(
                runner,
                ["def _revalidate_before_popen", "os.path.lexists(output)"],
            ),
            "runner_stable_artifact": _locations(
                runner,
                ["def _stable_artifact", "os.fstat(leaf_fd)", '"path_reopened": False'],
            ),
            "runner_popen": _locations(
                runner,
                ["_DIAGNOSTIC_EXECUTION_CAPABILITY: object | None = None", "def _run_real_popen_wait"],
            ),
            "runner_report": _locations(
                runner,
                ["def validate_report", '"diagnostic_terminal_verified"', 'report.terminal_receipt'],
            ),
        },
    }


def _finding(
    *,
    finding_id: str,
    severity: str,
    title: str,
    affected: Sequence[str],
    evidence: Mapping[str, Any],
    risk: str,
    required_fix: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "title": title,
        "affected": list(affected),
        "evidence": dict(evidence),
        "risk": risk,
        "current_status": "blocked_fail_closed",
        "blocking_for_readiness": True,
        "required_fix": required_fix,
    }


def _build_findings(checks: Mapping[str, Any]) -> list[dict[str, Any]]:
    locations = checks["locations"]
    findings: list[dict[str, Any]] = []
    if not checks["external_replay_authority"]:
        findings.append(
            _finding(
                finding_id="F3-DAV3-SA-001",
                severity="P1",
                title="One-shot consumption is atomic locally but not externally replay-resistant",
                affected=[
                    "admission_v1.consume_receipt",
                    "admission_v1.validate_receipt",
                    "runner_v2._verify_consumed_capability",
                ],
                evidence={
                    "local_atomic_lock_and_marker": checks["local_atomic_one_shot"],
                    "owner_controlled_namespace": "/tmp/<nonce namespace>",
                    "external_replay_authority": checks["external_replay_authority"],
                    "locations": locations["admission_consumption"],
                },
                risk="A same-owner process can delete/recreate the local namespace or replay a copied receipt; inode and nonce fields do not survive an owner-controlled namespace reset as an external consume-once fact.",
                required_fix="Bind consumption to an owner-controlled external scheduler ledger or signed one-time reservation that survives namespace deletion/recreation; require the execution boundary to consume that authority exactly once.",
            )
        )
    if checks["caller_supplied_resource_snapshot"] and not checks["external_owner_attestation"]:
        findings.append(
            _finding(
                finding_id="F3-DAV3-SA-002",
                severity="P1",
                title="Owner/inode/nonce and scheduler-owned GPU claims remain self-attested at the Python API boundary",
                affected=[
                    "admission_v1.mint_admission",
                    "admission_v1._validate_resource",
                    "admission_v1._validate_owner",
                ],
                evidence={
                    "owner_inode_nonce_shape_checks": checks["owner_inode_nonce_binding"],
                    "caller_supplied_resource_snapshot": checks["caller_supplied_resource_snapshot"],
                    "external_owner_attestation": checks["external_owner_attestation"],
                    "locations": locations["admission_owner_gpu"],
                },
                risk="The strings scheduler_owned_snapshot and identity_attested are ordinary receipt fields. A caller can construct the mapping unless a scheduler-owned signature, descriptor, or protected capability is required outside this process.",
                required_fix="Accept only a scheduler-issued, cryptographically or kernel-protected attestation bound to uid/gid/host, namespace inode, nonce, plan digest, and GPU identity; do not treat caller-provided booleans as authority.",
            )
        )
    if checks["launcher_path_based_preflight_reader"] or not checks[
        "admission_cross_binds_launcher_training_file_digest"
    ]:
        findings.append(
            _finding(
                finding_id="F3-DAV3-SA-003",
                severity="P1",
                title="The launcher preflight still has a pathname-read window before admission's stable reread",
                affected=[
                    "rollout_launcher_v1._read_bounded_json",
                    "admission_v1.mint_admission",
                ],
                evidence={
                    "launcher_path_based_preflight_reader": checks["launcher_path_based_preflight_reader"],
                    "admission_stable_fd_reread": checks["admission_stable_fd_reads"],
                    "admission_cross_binds_launcher_training_file_digest": checks[
                        "admission_cross_binds_launcher_training_file_digest"
                    ],
                    "locations": {
                        "launcher": locations["launcher_reader"],
                        "admission": locations["admission_read"],
                    },
                },
                risk="A parent replacement or input change between the launcher read and admission's second read can make command construction and the final receipt describe different training/manifests; later fail-closed validation is not a single-snapshot admission boundary.",
                required_fix="Use one descriptor-anchored reader for the launcher preflight and admission identity, or compare every launcher snapshot descriptor and canonical payload digest with the stable reread before creating any namespace state.",
            )
        )
    if not checks["runner_output_atomic_reservation_before_popen"]:
        findings.append(
            _finding(
                finding_id="F3-DAV3-SA-004",
                severity="P1",
                title="Evaluator output paths are checked for freshness but not atomically reserved before Popen",
                affected=[
                    "runner_v2._revalidate_before_popen",
                    "runner_v2._run_real_popen_wait",
                    "core_learning evaluator output paths",
                ],
                evidence={
                    "output_atomic_reservation_before_popen": checks["runner_output_atomic_reservation_before_popen"],
                    "stable_fd_read_after_exit": checks["runner_stable_fd_artifact_reads"],
                    "locations": locations["runner_output_gate"],
                },
                risk="A concurrent same-owner process can create a symlink or hardlink at evaluation/trajectory/progress between the lexists check and the child open. Post-exit stable validation can reject the artifact but cannot undo an out-of-scope write.",
                required_fix="Reserve every evaluator output with owner-checked O_EXCL descriptors before Popen, pass only reserved paths/handles to the child, and retain a parent-directory/inode commitment through publication.",
            )
        )
    if not checks["hdf5_external_storage_rejection"]:
        findings.append(
            _finding(
                finding_id="F3-DAV3-SA-005",
                severity="P1",
                title="The in-memory HDF5 hardening rejects non-hard links/VDS but does not reject external-storage datasets",
                affected=[
                    "hdf5_hardening_dependency.inspect_hdf5_snapshot",
                    "runner_v2._terminal_hdf5_receipt",
                ],
                evidence={
                    "nonhard_link_and_vds_rejection": checks["hdf5_nonhard_and_vds_rejection"],
                    "external_storage_rejection": checks["hdf5_external_storage_rejection"],
                    "path_reopen": False,
                },
                risk="An HDF5 dataset with external storage can remain a physical dataset while its data lives outside the bound trajectory bytes. A later consumer that reads it can escape the artifact identity boundary.",
                required_fix="Inspect every dataset's external-storage metadata and reject non-empty external mappings before any dataset dereference; bind the complete link/storage inventory to the terminal receipt.",
            )
        )
    if checks["gpu_uuid_pci_logical_shape_bound"] and (
        not checks["gpu_probe_emits_uuid_pci_identity"]
        or not checks["child_runtime_gpu_attestation"]
    ):
        findings.append(
            _finding(
                finding_id="F3-DAV3-SA-006",
                severity="P1",
                title="GPU UUID/PCI/logical mapping is receipt-shaped but lacks live probe and child-runtime attestation",
                affected=[
                    "admission_v1._gpu_identity",
                    "resource_admission_dependency._query_gpu_rows",
                    "runner_v2._capture_runtime_identity",
                ],
                evidence={
                    "receipt_shape_binding": checks["gpu_uuid_pci_logical_shape_bound"],
                    "gpu_probe_emits_uuid_pci_identity": checks["gpu_probe_emits_uuid_pci_identity"],
                    "child_runtime_gpu_attestation": checks["child_runtime_gpu_attestation"],
                    "shared_occupancy_policy": "allowed when independently attested VRAM remains sufficient",
                    "locations": locations["admission_owner_gpu"],
                },
                risk="Physical GPU2 can differ from a caller-supplied UUID/PCI mapping or from the child CUDA device; numeric memory probing alone cannot prove the logical cuda:0 process landed on the attested device.",
                required_fix="Have the scheduler emit UUID/PCI plus a fresh VRAM budget and require a sealed child-side device identity attestation before any terminal proof or launch promotion.",
            )
        )
    if not checks["terminal_report_receipt_identity_bound"]:
        findings.append(
            _finding(
                finding_id="F3-DAV3-SA-007",
                severity="P2",
                title="Runner report validation accepts an unbound terminal-receipt mapping",
                affected=["runner_v2.validate_report"],
                evidence={
                    "terminal_status_shape_checked": True,
                    "terminal_receipt_identity_bound": checks["terminal_report_receipt_identity_bound"],
                    "locations": locations["runner_report"],
                },
                risk="A caller can forge a diagnostic_terminal_verified report with arbitrary terminal_receipt content. This does not create formal credit today, but it weakens diagnostic evidence integrity and could become dangerous if a future gate trusts the report shape.",
                required_fix="Validate the terminal receipt schema, receipt/identity/binding digests, process witness seal, artifact descriptors, HDF5 receipt, and zero-credit fields before accepting diagnostic_terminal_verified; keep the execution capability absent until an external terminal proof is present.",
            )
        )
    return findings


def _control_matrix(checks: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "replay_one_shot_consumption": {
            "local_lock_marker_closed": checks["local_atomic_one_shot"],
            "external_replay_closed": checks["external_replay_authority"],
            "verdict": "P1_blocked" if not checks["external_replay_authority"] else "closed_pending_terminal_proof",
        },
        "owner_inode_nonce": {
            "local_shape_and_cross_binding": checks["owner_inode_nonce_binding"],
            "external_owner_attestation": checks["external_owner_attestation"],
            "verdict": "P1_blocked" if not checks["external_owner_attestation"] else "closed_pending_terminal_proof",
        },
        "full_path_toc_tou": {
            "admission_stable_fd_read": checks["admission_stable_fd_reads"],
            "launcher_preflight_stable": not checks["launcher_path_based_preflight_reader"],
            "launcher_snapshot_cross_bound": checks["admission_cross_binds_launcher_training_file_digest"],
            "evaluator_outputs_reserved_before_popen": checks["runner_output_atomic_reservation_before_popen"],
            "verdict": "P1_blocked",
        },
        "symlink_hardlink_external_vds": {
            "input_stable_fd_and_single_link": checks["admission_stable_fd_reads"],
            "artifact_stable_fd_and_single_link": checks["runner_stable_fd_artifact_reads"],
            "hdf5_nonhard_and_vds_rejected": checks["hdf5_nonhard_and_vds_rejection"],
            "hdf5_external_storage_rejected": checks["hdf5_external_storage_rejection"],
            "verdict": "P1_blocked" if not checks["hdf5_external_storage_rejection"] else "closed_locally_pending_reserved_output_boundary",
        },
        "gpu_uuid_pci_logical_mapping": {
            "receipt_shape_bound": checks["gpu_uuid_pci_logical_shape_bound"],
            "live_probe_identity": checks["gpu_probe_emits_uuid_pci_identity"],
            "child_runtime_identity": checks["child_runtime_gpu_attestation"],
            "verdict": "P1_blocked",
        },
        "environment_executable_identity": {
            "allowlisted_environment_digest": checks["allowlisted_environment_digest"],
            "executable_content_and_runtime_identity": checks[
                "executable_content_and_runtime_identity"
            ],
            "verdict": "closed_locally_pending_external_trust_anchor",
        },
        "sealed_real_popen_wait": {
            "internal_witness_structure": checks["sealed_real_popen_wait_witness"],
            "capability_admitted": False,
            "terminal_proof_observed": False,
            "verdict": "closed_non_authorizing_pending_external_terminal_proof",
        },
        "stable_fd_artifact_validation": {
            "stable_fd": checks["runner_stable_fd_artifact_reads"],
            "path_reopen_flag_false": checks["runner_stable_fd_artifact_reads"],
            "verdict": "closed_for_reads_pending_output_reservation",
        },
        "formal_credit_isolation": {
            "zero_credit_and_launch_false": checks["formal_credit_isolation"],
            "terminal_report_identity_bound": checks["terminal_report_receipt_identity_bound"],
            "verdict": "P2_report_binding_gap" if not checks["terminal_report_receipt_identity_bound"] else "closed_zero_credit_only",
        },
    }


def build_audit_report() -> dict[str, Any]:
    texts, trees, inventory = _source_bundle()
    checks = _static_checks(texts, trees)
    findings = _build_findings(checks)
    control_matrix = _control_matrix(checks)
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "contract_date": DATE_TAG,
        "status": "blocked_fail_closed",
        "audit_mode": "independent_read_only_static_ast_security_reaudit",
        "scope": {
            "audited_commits": list(AUDITED_COMMITS),
            "primary_admission": "f3_graph_raw_hidden16_seed17_diagnostic_admission_v1.py",
            "primary_runner": "f3_graph_raw_hidden16_seed17_diagnostic_runner_v2.py",
            "transitive_dependencies_read_only": True,
            "no_audited_module_import": True,
            "no_workload_execution": True,
            "no_popen_or_wait": True,
            "no_gpu_or_nvidia_smi": True,
            "no_production_artifact_open": True,
            "no_registry_ledger_gate_completion_plan_write": True,
        },
        "source_bound": True,
        "audited_files": inventory,
        "static_checks": checks,
        "control_matrix": control_matrix,
        "findings": findings,
        "readiness": {
            "local_static_review_pass": len(findings) == 0,
            "readiness_pass": False,
            "independent_terminal_proof": False,
            "external_terminal_proof_required": True,
            "launch_allowed": False,
            "popen_wait_observed": "0/0",
            "gpu_execution_observed": False,
            "formal_authority_present": False,
        },
        "side_effects": {
            "source_files_written": 0,
            "processes_started": 0,
            "processes_stopped": 0,
            "processes_restarted": 0,
            "popen_attempts": 0,
            "wait_attempts": 0,
            "solver_started": False,
            "worker_started": False,
            "gpu_used_for_execution": False,
            "nvidia_smi_invocations": 0,
            "production_artifacts_opened": 0,
            "queue_submissions": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        "blocked_reasons": [
            "external one-shot replay consumption is not attested by a scheduler-owned authority",
            "owner/inode/nonce and GPU identity fields remain caller-shaped without an external attestation token",
            "launcher preflight and evaluator output publication are not one descriptor-reserved path boundary",
            "live GPU UUID/PCI and child logical-device identity are not observed",
            "terminal proof remains external and was intentionally not executed by this audit",
        ],
        **ZERO_CREDIT,
    }


def _validate_zero_credit(report: Mapping[str, Any]) -> None:
    for key, expected in ZERO_CREDIT.items():
        if report.get(key) != expected:
            _fail(f"report.{key} must remain {expected!r}")


def validate_audit_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        expected = build_audit_report()
        if canonical_json(report) != canonical_json(expected):
            _fail("audit report does not exactly match the current source re-audit")
        if report.get("status") != "blocked_fail_closed":
            _fail("audit report cannot be promoted from blocked status")
        readiness = report.get("readiness")
        if not isinstance(readiness, Mapping):
            _fail("report.readiness must be an object")
        if readiness.get("launch_allowed") is not False:
            _fail("launch_allowed must remain false")
        if readiness.get("independent_terminal_proof") is not False:
            _fail("independent terminal proof cannot be self-declared")
        side_effects = report.get("side_effects")
        if not isinstance(side_effects, Mapping):
            _fail("report.side_effects must be an object")
        for key, value in side_effects.items():
            if key.endswith("_started") or key.endswith("_invocations") or key.endswith("_attempts") or key.endswith("_writes"):
                if value not in (False, 0):
                    _fail(f"report.side_effects.{key} must remain false/zero")
        _validate_zero_credit(report)
    except (ReauditError, TypeError, KeyError, ValueError) as error:
        errors.append(str(error))
    return errors


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    raw_path = os.fspath(path)
    if not isinstance(raw_path, str) or not raw_path or os.path.normpath(raw_path) != raw_path:
        _fail("report output must be an absolute lexical path")
    candidate = Path(raw_path)
    if not candidate.is_absolute() or any(part in {".", ".."} for part in candidate.parts):
        _fail("report output must be an absolute lexical path")
    if not candidate.parent.is_dir() or candidate.parent.is_symlink():
        _fail("report output parent must already be a non-symlink directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(candidate, flags, 0o640)
        raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = None
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        _fail(f"refusing to overwrite audit report: {error}")
    except OSError as error:
        _fail(f"cannot write audit report: {error}")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-output", type=Path, default=None)
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.verify_report is not None:
            report = json.loads(args.verify_report.read_text(encoding="utf-8"))
            errors = validate_audit_report(report)
            if errors:
                _fail("; ".join(errors))
            print(canonical_json({"status": "verified", "report": str(args.verify_report)}))
            return 0
        report = build_audit_report()
        if args.report_output is not None:
            _write_exclusive(args.report_output, report)
        print(canonical_json(report))
        return 0
    except (ReauditError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
