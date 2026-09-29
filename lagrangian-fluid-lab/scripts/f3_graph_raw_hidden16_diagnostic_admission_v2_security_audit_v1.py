#!/usr/bin/env python3
"""Independent read-only security design audit for the future diagnostic v2 runner.

The audit is deliberately additive and non-authorizing.  It reads the current
v1 runner, audited executor, raw terminal validator/bridge, production
validator boundary, and the common HDF5 hardening implementation as source
text/AST only.  It does not import those modules, execute ``nvidia-smi``,
create a namespace, call ``Popen``/``wait``, open a trajectory/checkpoint, or
write registry, ledger, gate, completion, or PLAN state.

The result records what is safe today and what prevents a safe diagnostic
admission/v2 upgrade.  In particular, a serialized receipt, PID, boolean,
callback, or numeric GPU index is never treated as formal authority.  The
report remains diagnostic-only and zero-credit even when the source audit
finds the expected v1 deny gates.
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
REPORT_SCHEMA = (
    "core.f3.graph_raw.hidden16.diagnostic_admission_v2.security_audit.report.v1"
)
REPORT_ID = "f3-graph-raw-hidden16-diagnostic-admission-v2-security-audit-v1"
DATE_TAG = "2026-09-29"
MAX_SOURCE_BYTES = 4 * 1024 * 1024
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
        "diagnostic_runner_v1",
        LAB_ROOT
        / "scripts/f3_graph_raw_hidden16_current_manifest_seed17_diagnostic_runner_v1.py",
    ),
    (
        "audited_executor_v1",
        LAB_ROOT
        / "scripts/f3_graph_raw_hidden16_current_manifest_audited_executor_v1.py",
    ),
    (
        "rollout_launcher_v1",
        LAB_ROOT
        / "scripts/f3_graph_raw_hidden16_current_manifest_rollout_launcher_v1.py",
    ),
    (
        "raw_terminal_validator_v1",
        LAB_ROOT
        / "scripts/f3_graph_raw_hidden16_current_manifest_terminal_artifact_validator_v1.py",
    ),
    (
        "raw_terminal_bridge_v1",
        LAB_ROOT
        / "scripts/f3_graph_raw_hidden16_current_manifest_terminal_execution_bridge_v1.py",
    ),
    (
        "production_validator_capability_v1",
        LAB_ROOT / "scripts/f3_graph_terminal_production_validator_capability_v1.py",
    ),
    (
        "validator_admission_v1",
        LAB_ROOT / "scripts/f3_graph_terminal_production_validator_admission_v1.py",
    ),
    (
        "common_hdf5_validator_v1",
        LAB_ROOT / "scripts/f3_full_rollout_receipt_hdf5_validator_v1.py",
    ),
    (
        "validator_hardening_contract_v1",
        LAB_ROOT / "scripts/f3_graph_terminal_validator_security_hardening_v1.py",
    ),
)


class AuditError(ValueError):
    """The audit cannot safely make a claim about the current source boundary."""


def _fail(message: str) -> None:
    raise AuditError(f"fail-closed: {message}")


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


def _read_source(path: Path, role: str) -> tuple[str, dict[str, Any]]:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        _fail(f"{role} cannot be resolved: {error}")
    if resolved != path or LAB_ROOT not in resolved.parents:
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
        raw = os.read(descriptor, MAX_SOURCE_BYTES + 1)
        after = os.fstat(descriptor)
    except OSError as error:
        _fail(f"{role} cannot be read: {error}")
    finally:
        os.close(descriptor)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(raw) != before.st_size:
        _fail(f"{role} changed during the bounded audit read")
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
    result: dict[str, list[int]] = {}
    for needle in needles:
        found = [index for index, line in enumerate(lines, start=1) if needle in line]
        if not found:
            _fail(f"audit evidence needle is absent: {needle!r}")
        result[needle] = found[:8]
    return result


def _all_call_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            names.add(function.id)
        elif isinstance(function, ast.Attribute):
            names.add(function.attr)
    return names


def _function_argument_hits(tree: ast.AST, names: set[str]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        overlap = sorted({argument.arg for argument in arguments} & names)
        if overlap:
            hits.append({"function": node.name, "line": node.lineno, "arguments": overlap})
    return sorted(hits, key=lambda item: (item["line"], item["function"]))


def _source_bundle() -> tuple[dict[str, str], list[dict[str, Any]], dict[str, ast.Module]]:
    texts: dict[str, str] = {}
    inventory: list[dict[str, Any]] = []
    trees: dict[str, ast.Module] = {}
    for role, path in AUDITED_FILES:
        text, descriptor = _read_source(path, role)
        texts[role] = text
        inventory.append(descriptor)
        trees[role] = _parse(text, role)
    return texts, inventory, trees


def _static_checks(
    texts: Mapping[str, str], trees: Mapping[str, ast.Module]
) -> dict[str, Any]:
    runner = texts["diagnostic_runner_v1"]
    executor = texts["audited_executor_v1"]
    launcher = texts["rollout_launcher_v1"]
    bridge = texts["raw_terminal_bridge_v1"]
    production = texts["production_validator_capability_v1"]
    admission = texts["validator_admission_v1"]
    base_hdf5 = texts["common_hdf5_validator_v1"]
    hardening = texts["validator_hardening_contract_v1"]

    process_control_names = {
        "kill",
        "killpg",
        "terminate",
        "send_signal",
        "pkill",
        "systemctl",
    }
    process_control_calls = {
        role: sorted(_all_call_names(trees[role]) & process_control_names)
        for role in (
            "diagnostic_runner_v1",
            "audited_executor_v1",
            "raw_terminal_bridge_v1",
            "production_validator_capability_v1",
        )
    }

    callback_names = {
        "resource_admission",
        "admission",
        "admission_probe",
        "popen_factory",
        "terminal_validator",
        "capability",
        "terminal_capability",
        "_capability",
    }
    callback_surfaces = {
        role: _function_argument_hits(trees[role], callback_names)
        for role in (
            "diagnostic_runner_v1",
            "audited_executor_v1",
            "raw_terminal_bridge_v1",
        )
    }

    return {
        "runner_execute_capability_is_uninstalled": (
            "_DIAGNOSTIC_EXECUTE_CAPABILITY: object | None = None" in runner
        ),
        "production_validator_capability_is_uninstalled": (
            "_PRODUCTION_VALIDATOR_CAPABILITY: object | None = None" in production
        ),
        "bridge_explicit_execute_fails_before_popen": (
            "production HDF5 validator capability is not admitted; Popen was not attempted"
            in bridge
        ),
        "executor_explicit_execute_fails_before_popen": (
            "can be created in the diagnostic-only boundary" in executor
        ),
        "numeric_gpu_env_mapping_present": (
            '"CUDA_VISIBLE_DEVICES": str(GPU_INDEX)' in runner
            and '"CUDA_VISIBLE_DEVICES": str(gpu_index)' in launcher
            and '"cuda:0"' in runner
        ),
        "stable_gpu_uuid_or_pci_binding_absent": not any(
            token in (runner + executor + bridge).lower()
            for token in ("gpu_uuid", "pci_bus", "pci.bus", "cuda_device_order")
        ),
        "resource_admission_is_snapshot_not_reservation": (
            "memory.free" in executor
            or "memory.free" in admission
            or "_query_gpu_rows" in executor
        )
        and "reservation" not in executor.lower(),
        "production_validator_reopens_hdf5_path": (
            'with h5py.File(path, "r") as handle' in production
        ),
        "production_validator_has_path_based_bounded_reader": (
            "fd = os.open(path, flags)" in production
            and "def _read_bounded_bytes" in production
        ),
        "common_hdf5_descriptor_and_link_hardening_exists": (
            "def _read_stable_hdf5_snapshot" in base_hdf5
            and "def _reject_unsafe_hdf5_links" in base_hdf5
            and "def inspect_hdf5_snapshot" in hardening
        ),
        "raw_runner_reopens_path_in_independent_validator": (
            "hdf5_validator.validate_receipt(" in runner
            and 'outputs["trajectory"]' in runner
        ),
        "production_process_pid_is_receipt_field": (
            'proof.get("evaluator_pid")' in production
            and 'proof.get("command")' in production
        ),
        "bridge_terminal_attestation_is_serialized_mapping": (
            "def validate_terminal_attestation(" in bridge
            and "terminal_attestation" in bridge
        ),
        "sealed_in_memory_record_exists_but_is_not_admitted": (
            "class _RealProcessRecord" in bridge
            and "production validator capability is not admitted" in bridge
        ),
        "ambient_environment_is_copied_for_future_popen": (
            "environment = os.environ.copy()" in runner
            and "environment = os.environ.copy()" in bridge
        ),
        "executable_content_hash_is_not_required_by_snapshot": (
            "allow_leaf_symlink=True" in runner
            and '"sha256": hashlib.sha256' not in runner.split("def _stable_descriptor", 1)[1].split("def _read_bounded_json", 1)[0]
        ),
        "namespace_consumption_ledger_is_absent": (
            "consumed" not in production.lower()
            and "replay_ledger" not in production.lower()
            and "namespace_reservation" not in production.lower()
        ),
        "executor_does_not_materialize_namespace_reservation": (
            "def build_audited_plan" in executor
            and "_reserve_namespace" not in executor
            and "os.mkdir" not in executor.split("def build_audited_plan", 1)[1].split(
                "def _validate_outputs_fresh", 1
            )[0]
            and "O_EXCL" not in executor.split("def build_audited_plan", 1)[1].split(
                "def _validate_outputs_fresh", 1
            )[0]
        ),
        "zero_credit_and_launch_denial_are_explicit": (
            '"launch_allowed": False' in runner
            and '"launch_allowed": False' in bridge
            and '"credit": 0' in runner
        ),
        "dangerous_process_control_calls": process_control_calls,
        "callback_injection_surfaces": callback_surfaces,
        "admission_probe_runs_nvidia_smi": "nvidia-smi" in executor,
        "hdf5_link_rejection_is_byte_snapshot_only": (
            "_reject_unsafe_hdf5_links" in base_hdf5
            and "h5py.File(path, \"r\")" in production
        ),
    }


def _finding(
    *,
    finding_id: str,
    severity: str,
    title: str,
    affected: Sequence[str],
    evidence: Mapping[str, Any],
    risk: str,
    blocker: str,
    required_fix: str,
    current_status: str = "blocked_fail_closed",
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "title": title,
        "affected": list(affected),
        "evidence": dict(evidence),
        "risk": risk,
        "current_status": current_status,
        "blocking_for_v2": True,
        "blocker": blocker,
        "required_fix": required_fix,
    }


def _build_findings(texts: Mapping[str, str], checks: Mapping[str, Any]) -> list[dict[str, Any]]:
    runner = texts["diagnostic_runner_v1"]
    executor = texts["audited_executor_v1"]
    bridge = texts["raw_terminal_bridge_v1"]
    production = texts["production_validator_capability_v1"]
    admission = texts["validator_admission_v1"]
    base_hdf5 = texts["common_hdf5_validator_v1"]

    admission_locations = {
        "runner": _locations(
            runner,
            ["resource_admission: Mapping[str, Any] | None = None", "def _validate_current_admission"],
        ),
        "executor": _locations(
            executor,
            ["admission: Mapping[str, Any] | None = None", "admission_probe: Callable"],
        ),
        "bridge": _locations(
            bridge,
            ["admission: Mapping[str, Any] | None = None", "admission_probe: Callable"],
        ),
    }
    findings = [
        _finding(
            finding_id="F3-DAV2-SA-001",
            severity="P1",
            title="Admission and execution callbacks remain caller-injectable at the v1 API boundary",
            affected=[
                "diagnostic_runner_v1.build_plan/build_report",
                "audited_executor_v1.build_audited_plan/_revalidate_for_execution",
                "raw_terminal_bridge_v1.build_bridge_plan/_revalidate_bridge_plan/execute_diagnostic_one_shot",
            ],
            evidence={
                "callback_argument_locations": admission_locations,
                "numeric_gpu_probe": checks["admission_probe_runs_nvidia_smi"],
                "current_gate": "execution capability is uninstalled and explicit execution fails closed",
            },
            risk="A future v2 caller could supply a self-declared admitted mapping, probe callback, terminal validator, or Popen seam and accidentally turn advisory input into execution authority.",
            blocker="v2_admission_requires_scheduler_owned_probe_and_no_authorizing_caller_callbacks",
            required_fix="Remove authorizing callback parameters from the privileged path; obtain a scheduler-owned, timestamped GPU/CPU/I/O snapshot and bind its host/GPU identity, freshness, and reservation token to the one-shot plan.",
        ),
        _finding(
            finding_id="F3-DAV2-SA-002",
            severity="P1",
            title="Fresh nonce and namespace claims do not yet provide externally consumed replay protection",
            affected=[
                "audited_executor_v1.build_audited_plan",
                "production_validator_capability_v1._validate_identity/_validate_process_proof",
                "diagnostic_runner_v1._reserve_namespace/execute_diagnostic",
            ],
            evidence={
                "executor_does_not_materialize_reservation": checks["executor_does_not_materialize_namespace_reservation"],
                "namespace_consumption_ledger_absent": checks["namespace_consumption_ledger_is_absent"],
                "claim_only_fields": ["fresh_namespace", "namespace_fresh", "reuse_forbidden", "nonce"],
                "runner_local_reservation_exists": "def _reserve_namespace" in runner,
            },
            risk="A copied or replayed receipt can repeat a valid-looking nonce/namespace claim because the production boundary has no scheduler-owned consume-once marker or external replay ledger.",
            blocker="v2_requires_atomic_one_shot_namespace_reservation_and_receipt_consumption",
            required_fix="Reserve the output namespace through an owner-controlled descriptor/marker, bind owner host/inode/nonce/plan digest, atomically consume it once, and reject any receipt whose reservation is already consumed or absent.",
        ),
        _finding(
            finding_id="F3-DAV2-SA-003",
            severity="P1",
            title="The production validator still has pathname reopen windows outside the common descriptor snapshot",
            affected=[
                "production_validator_capability_v1._read_bounded_bytes",
                "production_validator_capability_v1._validate_hdf5_identity",
                "raw_terminal_validator_v1 -> common_hdf5_validator_v1 integration",
            ],
            evidence={
                "production_path_reader": checks["production_validator_has_path_based_bounded_reader"],
                "production_hdf5_path_open": checks["production_validator_reopens_hdf5_path"],
                "raw_runner_independent_path_call": checks["raw_runner_reopens_path_in_independent_validator"],
                "common_safe_reader_exists_but_is_not_global": checks["common_hdf5_descriptor_and_link_hardening_exists"],
                "locations": {
                    "production": _locations(production, ["def _read_bounded_bytes", "with h5py.File(path, \"r\") as handle"]),
                    "runner": _locations(runner, ["hdf5_validator.validate_receipt("]),
                },
            },
            risk="A parent-directory rename, replacement, or in-place mutation can make a later path open observe bytes different from the audited descriptor/path identity.",
            blocker="v2_requires_one_descriptor_bound_snapshot_for_every_json_and_hdf5_artifact",
            required_fix="Route every artifact through directory-fd/O_NOFOLLOW/single-link reads and hand only the immutable bytes to JSON/HDF5 validators; never reopen the pathname after identity validation.",
        ),
        _finding(
            finding_id="F3-DAV2-SA-004",
            severity="P1",
            title="HDF5 external/soft/VDS rejection is not enforced before every v1 path-based HDF5 open",
            affected=[
                "production_validator_capability_v1._validate_hdf5_identity",
                "common_hdf5_validator_v1._reject_unsafe_hdf5_links",
                "raw_terminal_validator_v1._hardened_hdf5_checks",
            ],
            evidence={
                "common_rejection_exists": checks["common_hdf5_descriptor_and_link_hardening_exists"],
                "path_open_precedes_common_snapshot": checks["hdf5_link_rejection_is_byte_snapshot_only"],
                "required_link_policy": ["reject ExternalLink", "reject SoftLink", "reject virtual datasets", "reject externally stored datasets"],
                "production_open_locations": _locations(production, ["with h5py.File(path, \"r\") as handle"]),
            },
            risk="A crafted output HDF5 can reach a path-based preflight before the safe byte-snapshot validator; the v2 boundary must make link rejection a precondition, not a later check.",
            blocker="v2_requires_hdf5_parse_only_from_bound_bytes_after_link_inventory",
            required_fix="Read once into a stable byte snapshot, inventory every HDF5 link/object before dereference, reject external/soft/VDS/external-storage objects, then run all validators on the same in-memory handle.",
        ),
        _finding(
            finding_id="F3-DAV2-SA-005",
            severity="P1",
            title="GPU admission binds a numeric index and advisory free VRAM, not a stable physical device identity",
            affected=[
                "audited_executor_v1._query_gpu_rows/probe_resource_admission",
                "diagnostic_runner_v1._assert_exact_command",
                "raw_terminal_bridge_v1._parse_gpu_bindings",
            ],
            evidence={
                "numeric_mapping_present": checks["numeric_gpu_env_mapping_present"],
                "stable_identity_absent": checks["stable_gpu_uuid_or_pci_binding_absent"],
                "resource_reservation_absent": checks["resource_admission_is_snapshot_not_reservation"],
                "mapping": {"physical_selector": "CUDA_VISIBLE_DEVICES=<nvidia-smi index>", "logical_selector": "cuda:0"},
                "policy_note": "shared GPU use is allowed when VRAM is sufficient; this audit does not require exclusivity",
            },
            risk="CUDA enumeration/order or a concurrent allocator can make numeric index 2 differ from the probed physical GPU or invalidate the free-VRAM snapshot after admission.",
            blocker="v2_requires_uuid_or_pci_identity_and_child_runtime_device_attestation",
            required_fix="Bind the selected GPU UUID/PCI identity and a fresh memory snapshot; set and bind the CUDA ordering policy, verify the child runtime device identity, and treat occupancy as shareable only when the bound VRAM budget remains valid.",
        ),
        _finding(
            finding_id="F3-DAV2-SA-006",
            severity="P1",
            title="Serialized Popen/PID and terminal attestation fields are not authoritative process evidence",
            affected=[
                "production_validator_capability_v1._validate_process_proof",
                "raw_terminal_bridge_v1.validate_terminal_attestation",
                "raw_terminal_bridge_v1._RealProcessRecord/_run_real_popen_wait",
            ],
            evidence={
                "receipt_pid_and_command_fields": checks["production_process_pid_is_receipt_field"],
                "serialized_terminal_mapping": checks["bridge_terminal_attestation_is_serialized_mapping"],
                "sealed_record_present_but_gate_closed": checks["sealed_in_memory_record_exists_but_is_not_admitted"],
                "production_locations": _locations(production, ["def _validate_process_proof", 'proof.get("evaluator_pid")']),
            },
            risk="A receipt can self-declare a successful PID, command, wait, or artifact proof and pass its own digest without proving that the current process executed the exact plan.",
            blocker="v2_requires_in_memory_sealed_real_popen_wait_witness_bound_to_kernel_and_plan_identity",
            required_fix="Accept process evidence only from an internal sealed record created immediately after the captured real Popen/wait path; bind argv, cwd, sanitized environment, executable identity, PID start-time/host, plan digest, and one-shot namespace.",
        ),
        _finding(
            finding_id="F3-DAV2-SA-007",
            severity="P1",
            title="Future Popen identity includes ambient inherited environment and stat-only executable metadata",
            affected=[
                "diagnostic_runner_v1._run_real_popen_wait",
                "raw_terminal_bridge_v1._run_real_popen_wait",
                "diagnostic_runner_v1._snapshot_inputs",
            ],
            evidence={
                "ambient_environment_copied": checks["ambient_environment_is_copied_for_future_popen"],
                "executable_content_hash_not_required": checks["executable_content_hash_is_not_required_by_snapshot"],
                "locations": {
                    "runner": _locations(runner, ["environment = os.environ.copy()", "allow_leaf_symlink=True"]),
                    "bridge": _locations(bridge, ["environment = os.environ.copy()"]),
                },
            },
            risk="PATH/LD_PRELOAD/PYTHONPATH and an executable replaced after stat validation can change what the child actually runs while the recorded override map remains unchanged.",
            blocker="v2_requires_allowlisted_environment_and_trusted_executable_runtime_identity",
            required_fix="Construct a minimal allowlisted environment, bind the full effective environment digest, require stable executable bytes or a trusted immutable runtime image, and verify the child executable identity before any promotion.",
        ),
        _finding(
            finding_id="F3-DAV2-SA-008",
            severity="P1",
            title="Formal/credit promotion is correctly closed today but has no safe v2 promotion contract",
            affected=[
                "diagnostic_runner_v1.ZERO_CREDIT/report validation",
                "raw_terminal_bridge_v1.build_diagnostic_evidence",
                "production_validator_admission_v1",
            ],
            evidence={
                "zero_credit_explicit": checks["zero_credit_and_launch_denial_are_explicit"],
                "runner_capability_uninstalled": checks["runner_execute_capability_is_uninstalled"],
                "production_capability_uninstalled": checks["production_validator_capability_is_uninstalled"],
                "required_separation": "diagnostic receipt must never mutate formal registry/ledger/gate/completion state",
            },
            risk="Adding v2 admission by flipping a boolean or trusting a validator report would allow diagnostic evidence to become formal credit without an independent gate/ledger decision.",
            blocker="v2_formal_promotion_requires_separate_authority_and_explicit_nonzero_credit_gate",
            required_fix="Keep v2 diagnostic admission zero-credit; if formal release is ever requested, require a separately reviewed gate that consumes only sealed, replay-free, source/terminal-bound evidence and records the decision outside the runner.",
        ),
    ]
    return findings


def _boundary_matrix(checks: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "receipt_replay": {
            "v1": "local fresh namespace/nonce checks exist, but production receipt freshness is declarative and no external consume-once ledger is bound",
            "v2": "blocked_until_atomic_reservation_and_consumption",
            "safe_now": False,
        },
        "toctou": {
            "v1": "common HDF5 descriptor snapshot exists; production capability and some independent path openings remain outside one immutable snapshot",
            "v2": "blocked_until_all_artifacts_use_descriptor_bound_bytes",
            "safe_now": False,
        },
        "gpu_env_device_mapping": {
            "v1": "CUDA_VISIBLE_DEVICES numeric index maps to logical cuda:0 and free VRAM is probed",
            "v2": "blocked_until_UUID_or_PCI_and_child_runtime_attestation",
            "safe_now": False,
            "shared_occupancy_allowed": True,
            "numeric_mapping_present": checks["numeric_gpu_env_mapping_present"],
        },
        "popen_identity": {
            "v1": "raw runner/bridge have sealed future-only in-memory records; production receipt validation still accepts serialized declarations",
            "v2": "blocked_until_only_internal_sealed_witness_can_authorize",
            "safe_now": False,
        },
        "output_hdf5_external_links": {
            "v1": "common byte-snapshot validator rejects unsafe links, but production path preflight is not uniformly behind it",
            "v2": "blocked_until_link_inventory_precedes_every_dereference",
            "safe_now": False,
        },
        "formal_credit_promotion": {
            "v1": "launch false, formal false, credit zero, capability absent",
            "v2": "must_remain_zero_credit_and_external_gate_only",
            "safe_now": True,
        },
        "existing_job_stop_restart": {
            "v1": "no kill/killpg/terminate/send_signal/pkill/systemctl call was found in audited execution boundaries",
            "v2": "must retain no-arbitrary-job-control contract; only the own child process group may be supervised",
            "safe_now": not any(checks["dangerous_process_control_calls"].values()),
            "dangerous_calls": checks["dangerous_process_control_calls"],
        },
    }


def build_audit_report() -> dict[str, Any]:
    texts, inventory, trees = _source_bundle()
    checks = _static_checks(texts, trees)
    if not checks["runner_execute_capability_is_uninstalled"]:
        _fail("runner v1 execution capability is no longer visibly uninstalled")
    if not checks["production_validator_capability_is_uninstalled"]:
        _fail("production validator capability is no longer visibly uninstalled")
    findings = _build_findings(texts, checks)
    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "contract_date": DATE_TAG,
        "status": "blocked_fail_closed",
        "audit_mode": "independent_read_only_static_ast_boundary_audit",
        "scope": {
            "future_runner": "diagnostic_admission_v2",
            "existing_runner_v1": True,
            "existing_audited_executor_v1": True,
            "existing_raw_terminal_validator_v1": True,
            "existing_raw_terminal_bridge_v1": True,
            "existing_production_validator_capability_v1": True,
            "existing_validator_admission_v1": True,
            "common_hdf5_validator_v1": True,
            "no_module_import_execution": True,
            "no_workload_or_gpu_execution": True,
        },
        "source_bound": True,
        "audited_files": inventory,
        "static_checks": checks,
        "findings": findings,
        "boundary_matrix": _boundary_matrix(checks),
        "v2_admission": {
            "safe_to_upgrade_now": False,
            "launch_allowed": False,
            "formal_authority_present": False,
            "required_blocker_count": sum(1 for item in findings if item["blocking_for_v2"]),
            "minimum_contract": {
                "scheduler_owned_one_shot_namespace_reservation": True,
                "external_replay_consumption_record": True,
                "descriptor_bound_json_and_hdf5_bytes": True,
                "reject_external_soft_vds_and_external_storage_links": True,
                "gpu_uuid_or_pci_identity": True,
                "fresh_vram_snapshot_with_shared_occupancy_budget": True,
                "child_runtime_device_attestation": True,
                "sealed_internal_real_popen_wait_witness": True,
                "allowlisted_effective_environment_digest": True,
                "trusted_executable_identity": True,
                "no_caller_authorizing_callbacks": True,
                "diagnostic_zero_credit_only": True,
                "no_existing_job_stop_or_restart": True,
            },
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
            "queue_submissions": 0,
            "production_artifacts_opened": 0,
            "registry_writes": 0,
            "ledger_writes": 0,
            "gate_writes": 0,
            "completion_writes": 0,
            "plan_writes": 0,
        },
        "blocked_reasons": [
            "v1 is safe only as a non-authorizing zero-credit boundary",
            "v2 must not promote caller-supplied admission/proof/validator fields",
            "scheduler-owned replay consumption and full descriptor-bound artifact reads are absent",
            "GPU numeric index/free-VRAM snapshot is not a stable physical-device reservation",
            "formal/credit promotion remains outside this diagnostic audit",
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
            _fail("audit report does not exactly match the current read-only source contract")
        if report.get("status") != "blocked_fail_closed":
            _fail("audit report cannot be promoted from blocked status")
        if report.get("v2_admission", {}).get("safe_to_upgrade_now") is not False:
            _fail("v2 admission cannot be marked safe")
        _validate_zero_credit(report)
        side_effects = report.get("side_effects")
        if not isinstance(side_effects, Mapping):
            _fail("report.side_effects must be an object")
        for key, value in side_effects.items():
            if key.endswith("_started") or key.endswith("_invocations") or key.endswith("_attempts") or key.endswith("_writes"):
                if value not in (False, 0):
                    _fail(f"report.side_effects.{key} must remain false/zero")
    except (AuditError, TypeError, KeyError, ValueError) as error:
        errors.append(str(error))
    return errors


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        _fail(f"refusing to overwrite audit report: {error}")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-output", type=Path, default=None)
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.verify_report is not None:
            try:
                report = json.loads(args.verify_report.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                _fail(f"cannot read audit report: {error}")
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
    except (AuditError, OSError, TypeError, ValueError) as error:
        print(canonical_json({"status": "blocked_fail_closed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
