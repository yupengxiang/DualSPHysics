#!/usr/bin/env python3
"""Prepare and bind the ROOT145 post-terminal executable contract (V3).

This is a metadata-only forward companion to the V53 parent hand-off.  The
``prepare`` operation records the copied runtime role table, the literal
interpreter exception, the ABI smoke command, and the complete post-terminal
CLI while terminal products do not exist.  The ``bind-terminal`` operation is
usable only after the parent has produced its two real terminal records and
the private worker has emitted small JSON reports.  It binds those records by
path, SHA, request, attempt, charge, and output namespace; it never merges
the Home receipt and returned report and never reads HDF5, BI4, raw, typed,
or result payloads.

The builder is intentionally outside the already bound V53 executor.  It
does not rewrite a consumed request or alter any copied runtime source path.
Its outputs remain DEVELOPMENT/UNKNOWN and must be independently checked by
the parent guard before any fresh proof or evaluator is run.

V2 adds an immutable *actual launch parent* overlay.  A launch request may be
a small forward request made after the source hand-off, so it is bound by its
own path and bytes rather than silently treated as the older source-prep
parent request.  The parent metadata verification is an evidence JSON and
therefore need not carry a canonical JSON field; its request/executor SHA
fields are checked against the actual launch files.

V3 adds an explicit source-path overlay for a relocated root checkout.  The
declared ``source_inputs`` paths remain provenance and are never rewritten.
An overlay is accepted only when its regular-file SHA is byte-identical to the
declared role SHA; implicit path discovery and SHA-only fallback remain
forbidden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-root145-postterminal-executable-contract.v3"
PREPARED_STATUS = "PREPARED_PENDING_PARENT_TERMINAL"
BOUND_STATUS = "BOUND_PARENT_TERMINAL_METADATA"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_METADATA_BYTES = 64 * 1024 * 1024
HEX = set("0123456789abcdef")


class ContractError(RuntimeError):
    """A stale, ambiguous, or non-metadata post-terminal input."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str).encode("utf-8")).hexdigest()


def _absolute(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute():
        raise ContractError(f"{role} must be absolute: {target}")
    return target


def sha256_file(path: Path | str, *, role: str, max_bytes: int = MAX_METADATA_BYTES) -> str:
    target = _absolute(path, role)
    if target.is_symlink() or not target.is_file():
        raise ContractError(f"{role} is not a regular non-symlink file: {target}")
    size = target.stat().st_size
    if size > max_bytes:
        raise ContractError(f"{role} exceeds metadata limit ({size} > {max_bytes})")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str, role: str) -> tuple[Path, dict[str, Any], str]:
    target = _absolute(path, role)
    physical = sha256_file(target, role=role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"{role} must be a JSON object")
    return target, value, physical


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX for ch in value):
        raise ContractError(f"{role} is not a lowercase SHA-256")
    return value


def _canonical_input(path: Path, value: Mapping[str, Any], role: str) -> dict[str, Any]:
    declared = value.get("sha256")
    if not isinstance(declared, str) or declared != canonical_sha(value):
        raise ContractError(f"{role} canonical SHA differs")
    return {"path": str(path), "canonical_sha256": declared,
            "physical_sha256": sha256_file(path, role=role),
            "schema": value.get("schema"), "status": value.get("status")}


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _role_contract(row: Mapping[str, Any], *, target_root: Path) -> dict[str, Any]:
    required = ("role", "target_relative_path", "target_path", "expected_sha256",
                "expected_bytes", "source_path_provenance", "source_path_fallback")
    missing = [key for key in required if key not in row]
    if missing:
        raise ContractError(f"runtime role missing fields: {missing}")
    role = row["role"]
    if not isinstance(role, str) or not role:
        raise ContractError("runtime role name is invalid")
    generated_after_reservation = role == "abi_smoke_script" \
        or row.get("materialization") == "PARENT_GENERATED_AFTER_RESERVATION"
    expected_sha_value = row.get("expected_sha256")
    if generated_after_reservation and expected_sha_value in (None, ""):
        expected_sha = None
    else:
        expected_sha = _sha(expected_sha_value, f"runtime role {role} expected_sha256")
    expected_bytes = row["expected_bytes"]
    if generated_after_reservation and expected_bytes in (None, 0):
        expected_bytes = None
    if expected_bytes is not None and (not isinstance(expected_bytes, int) or expected_bytes <= 0):
        raise ContractError(f"runtime role {role} expected_bytes is invalid")
    target_relative = row["target_relative_path"]
    target_path = _absolute(row["target_path"], f"runtime role {role} target_path")
    expected_target = target_root / "runtime" / str(target_relative)
    if target_path != expected_target:
        raise ContractError(f"runtime role {role} target path is not target_root/runtime/<relative>")
    source = row.get("source_path_provenance")
    if generated_after_reservation and source is None:
        source = None
    elif not isinstance(source, str) or not source.startswith("/"):
        raise ContractError(f"runtime role {role} lacks source provenance")
    if row["source_path_fallback"] != "FORBIDDEN":
        raise ContractError(f"runtime role {role} allows source fallback")
    phase = row.get("content_verification_phase")
    if phase is None:
        materialization = row.get("materialization")
        phase = ("PARENT_GENERATED_AFTER_RESERVATION" if materialization == "PARENT_GENERATED_AFTER_RESERVATION"
                 else "PARENT_GUARDED_COPY_AFTER_RESERVATION")
    result = {
        "role": role,
        "target_relative_path": str(target_relative),
        "target_path": str(target_path),
        "expected_sha256": expected_sha,
        "expected_bytes": expected_bytes,
        "source_path_provenance": source,
        "resolved_source_path_provenance": row.get("resolved_source_path_provenance"),
        "source_mode_bits": row.get("source_mode_bits"),
        "required_executable": bool(row.get("required_executable", False)),
        "content_verification_phase": phase,
        "materialization_path_policy": row.get("materialization_path_policy"),
        "source_path_fallback": "FORBIDDEN",
    }
    if "AFTER_RESERVATION" not in result["content_verification_phase"] \
            and result["content_verification_phase"] != "AFTER_ATOMIC_PARENT_RESERVATION":
        raise ContractError(f"runtime role {role} content phase is not parent-after-reservation")
    return result


def _split_cli(pg: Mapping[str, Any]) -> list[str]:
    execution = pg.get("execution")
    if not isinstance(execution, Mapping):
        raise ContractError("post-terminal execution section is missing")
    commands = execution.get("postterminal_commands")
    if not isinstance(commands, Mapping):
        raise ContractError("post-terminal command table is missing")
    split = commands.get("split_terminal_inputs")
    if not isinstance(split, Mapping) or not isinstance(split.get("command_template"), list):
        raise ContractError("split-terminal CLI is missing")
    command = split["command_template"]
    if not all(isinstance(item, str) for item in command):
        raise ContractError("split-terminal CLI is malformed")
    required = ("--parent-receipt", "--returned-parent-report", "--worker-report",
                "--source-contract", "--namespace-root", "--output-root",
                "--static-output", "--manifest-output", "--pinned-source", "--artifact")
    for flag in required:
        if flag not in command:
            raise ContractError(f"split-terminal CLI lacks {flag}")
    if "--home-receipt" in command:
        raise ContractError("obsolete --home-receipt alias is present")
    return list(command)


def _artifact_paths(command: Sequence[str]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for index, item in enumerate(command):
        if item == "--artifact":
            if index + 1 >= len(command) or "=" not in command[index + 1]:
                raise ContractError("malformed --artifact binding")
            role, path = command[index + 1].split("=", 1)
            if role in paths or not role or not path.startswith("/"):
                raise ContractError(f"malformed or duplicate artifact role: {role}")
            paths[role] = path
    expected = {"current_runtime_view", "relocated_v15_request", "engine_report"}
    if set(paths) != expected:
        raise ContractError(f"artifact roles differ: {sorted(paths)}")
    return paths


def _pinned_sources(command: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, item in enumerate(command):
        if item == "--pinned-source":
            if index + 1 >= len(command) or "=" not in command[index + 1]:
                raise ContractError("malformed --pinned-source binding")
            role, path = command[index + 1].split("=", 1)
            if not role or not path.startswith("/") or any(row["role"] == role for row in rows):
                raise ContractError(f"malformed or duplicate pinned source: {role}")
            rows.append({"role": role, "path": path, "source_path_fallback": "FORBIDDEN"})
    if not rows:
        raise ContractError("no pinned source roles in split-terminal CLI")
    return rows


def _prepare_inputs(*, executor_request: Path | str, parent_request: Path | str,
                    preflight: Path | str, postterminal_request: Path | str,
                    source_overlays: Mapping[str, Path | str] | None = None) -> dict[str, Any]:
    executor_path, executor, executor_physical = load_json(executor_request, "V53 executor request")
    parent_path, parent, parent_physical = load_json(parent_request, "parent V3 request")
    preflight_path, preflight_value, preflight_physical = load_json(preflight, "V50 metadata preflight")
    pg_path, pg, pg_physical = load_json(postterminal_request, "V53 post-terminal request")
    if executor.get("schema") != "ds02.stage2.f2-portable-executor-request.v34" \
            or executor.get("status") != "READY_FOR_PARENT_STAGE2_GUARD":
        raise ContractError("V53 executor is not a ready v34 request")
    if parent.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3" \
            or parent.get("status") != "READY_FOR_PARENT_GUARD":
        raise ContractError("parent request is not a ready V3 request")
    if preflight_value.get("schema") != "ds02.stage2.root.v50-metadata-preflight.v1" \
            or preflight_value.get("status") != "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS":
        raise ContractError("metadata preflight is not the actual parent validator pass")
    if preflight_value.get("array_payload_read") is not False \
            or preflight_value.get("namespace_absent") is not True \
            or preflight_value.get("qualification_credit") != "NONE":
        raise ContractError("metadata preflight claims payload access, namespace presence, or credit")
    if pg.get("schema") != "ds02.stage2.f2-v50-postterminal-parent-guard-request.v3" \
            or pg.get("status") != "READY_FOR_PARENT_POSTTERMINAL_GUARD":
        raise ContractError("post-terminal request is not a ready V3 hand-off")
    for value, name in ((executor, "V53 executor"), (parent, "parent request"),
                        (preflight_value, "metadata preflight"), (pg, "post-terminal request")):
        if value.get("sha256") != canonical_sha(value):
            raise ContractError(f"{name} canonical SHA differs")
    source_inputs = pg.get("source_inputs")
    if not isinstance(source_inputs, Mapping):
        raise ContractError("post-terminal source inputs are missing")
    expected_sources = {
        "executor_request": (executor_path, executor_physical),
        "parent_request": (parent_path, parent_physical),
        "preflight": (preflight_path, preflight_physical),
    }
    overlays = dict(source_overlays or {})
    unknown_overlays = sorted(set(overlays) - set(expected_sources))
    if unknown_overlays:
        raise ContractError(f"source overlay has unknown roles: {unknown_overlays}")
    source_overlay_records: dict[str, dict[str, Any]] = {}
    for role, (path, physical) in expected_sources.items():
        row = source_inputs.get(role)
        if not isinstance(row, Mapping) or row.get("physical_sha256") != physical:
            raise ContractError(f"post-terminal {role} binding differs")
        declared_path = row.get("path")
        if not isinstance(declared_path, str) or not declared_path.startswith("/"):
            raise ContractError(f"post-terminal {role} declared provenance path is invalid")
        if declared_path != str(path) and role not in overlays:
            raise ContractError(f"post-terminal {role} path differs without explicit overlay")
        if role in overlays:
            actual_path = _absolute(overlays[role], f"source overlay {role}")
            actual_physical = sha256_file(actual_path, role=f"source overlay {role}")
            if actual_physical != physical:
                raise ContractError(f"source overlay {role} SHA differs from declared role")
            source_overlay_records[role] = {
                "declared_path": declared_path,
                "actual_path": str(actual_path),
                "declared_physical_sha256": physical,
                "actual_physical_sha256": actual_physical,
            }
        elif declared_path != str(path):
            raise ContractError(f"post-terminal {role} path differs")
    execution = pg.get("execution")
    storage = pg.get("storage_scope")
    closure = pg.get("runtime_closure")
    if not isinstance(execution, Mapping) or not isinstance(storage, Mapping) \
            or not isinstance(closure, Mapping):
        raise ContractError("post-terminal execution/storage/runtime closure is incomplete")
    if execution.get("original_path_fallback") != "FORBIDDEN" \
            or execution.get("old_root060_reuse") != "FORBIDDEN":
        raise ContractError("post-terminal source fallback or old proof reuse is enabled")
    target_root = _absolute(storage.get("target_root"), "post-terminal target_root")
    output_root = _absolute(storage.get("output_root"), "post-terminal output_root")
    roles = closure.get("roles")
    if not isinstance(roles, list) or not roles:
        raise ContractError("runtime role table is empty")
    role_rows = [_role_contract(row, target_root=target_root) for row in roles]
    names = [row["role"] for row in role_rows]
    if len(names) != len(set(names)):
        raise ContractError("runtime role table contains duplicate roles")
    literal = closure.get("literal_interpreter")
    if not isinstance(literal, Mapping) or literal.get("argv0") != \
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python":
        raise ContractError("literal pinned venv interpreter is missing")
    split = _split_cli(pg)
    artifacts = _artifact_paths(split)
    pinned = _pinned_sources(split)
    abi = execution.get("postterminal_commands", {}).get("abi_smoke")
    if not isinstance(abi, Mapping) or not isinstance(abi.get("command"), list):
        raise ContractError("ABI smoke command is missing")
    abi_command = list(abi["command"])
    if abi_command[0] != literal["argv0"] or abi.get("payload_read") is not False:
        raise ContractError("ABI smoke is not bound to the literal interpreter/payload boundary")
    return {
        "paths": {
            "executor_request": executor_path, "parent_request": parent_path,
            "preflight": preflight_path, "postterminal_request": pg_path,
        },
        "values": {"executor": executor, "parent": parent, "preflight": preflight_value,
                   "postterminal": pg},
        "physical": {"executor_request": executor_physical, "parent_request": parent_physical,
                      "preflight": preflight_physical, "postterminal_request": pg_physical},
        "target_root": target_root, "output_root": output_root,
        "storage": dict(storage), "execution": dict(execution),
        "closure": dict(closure), "runtime_roles": role_rows,
        "literal_interpreter": dict(literal), "split_cli": split,
        "artifact_paths": artifacts, "pinned_sources": pinned,
        "abi_command": abi_command,
        "source_overlays": source_overlay_records,
    }


def _binding(path: Path, value: Mapping[str, Any], physical: str) -> dict[str, Any]:
    return {"path": str(path), "canonical_sha256": value["sha256"],
            "physical_sha256": physical, "schema": value.get("schema"),
            "status": value.get("status")}


def _actual_launch_inputs(*, parent_request: Path | str, metadata_preflight: Path | str,
                          expected_executor_sha: str) -> dict[str, Any]:
    """Load ROOT's small forward launch request and its validator evidence.

    The evidence file is not a request and is intentionally not required to
    carry a self-canonical SHA.  Its physical SHA, request SHA, and executor
    SHA are retained so a later terminal binder cannot silently substitute an
    older source-preparation parent request.
    """
    parent_path, parent, parent_physical = load_json(parent_request, "actual launch parent request")
    evidence_path, evidence, evidence_physical = load_json(
        metadata_preflight, "actual launch metadata evidence")
    if parent.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3" \
            or parent.get("status") != "READY_FOR_PARENT_GUARD":
        raise ContractError("actual launch parent is not a ready V3 request")
    if parent.get("sha256") != canonical_sha(parent):
        raise ContractError("actual launch parent canonical SHA differs")
    if evidence.get("schema") != "ds02.stage2.root.v50-metadata-preflight.v1" \
            or evidence.get("status") != "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS":
        raise ContractError("actual launch metadata evidence is not the parent validator pass")
    if evidence.get("request_sha256") != parent_physical:
        raise ContractError("actual metadata evidence is not bound to the actual parent bytes")
    if evidence.get("executor_request_sha256") != expected_executor_sha:
        raise ContractError("actual metadata evidence is not bound to this executor bytes")
    if evidence.get("payload_read") is not False \
            or evidence.get("root_array_content_read") is not False \
            or evidence.get("namespace_absent_before_run") is not True:
        raise ContractError("actual metadata evidence claims payload access or an existing namespace")
    if evidence.get("ROOT122_copied_partial_reused") is not False:
        raise ContractError("actual metadata evidence permits ROOT122 copied-partial reuse")
    executor_binding = parent.get("executor_request")
    if not isinstance(executor_binding, Mapping) \
            or executor_binding.get("sha256") != expected_executor_sha:
        raise ContractError("actual launch parent executor binding differs")
    resource = parent.get("parent_resource_binding")
    if not isinstance(resource, Mapping) or resource.get("same_parent_ledger") is not True \
            or resource.get("ledger_reset") is not False:
        raise ContractError("actual launch parent is not same-ledger/non-reset")
    execution = parent.get("execution")
    storage = parent.get("storage_scope")
    if not isinstance(execution, Mapping) or not isinstance(storage, Mapping):
        raise ContractError("actual launch parent lacks execution/storage scope")
    if execution.get("original_path_fallback") == "ALLOWED" \
            or execution.get("old_root060_reuse") == "ALLOWED":
        raise ContractError("actual launch parent allows forbidden fallback or old proof")
    return {
        "parent_path": parent_path,
        "parent": parent,
        "parent_physical": parent_physical,
        "evidence_path": evidence_path,
        "evidence": evidence,
        "evidence_physical": evidence_physical,
        "resource": dict(resource),
        "execution": dict(execution),
        "storage": dict(storage),
    }


def _attach_actual_launch(contract: dict[str, Any], actual: Mapping[str, Any],
                          *, executor_sha: str) -> None:
    parent = actual["parent"]
    resource = actual["resource"]
    contract["source_preparation_parent_guard"] = contract["parent_guard"]
    contract["parent_attempt_id"] = resource.get("attempt_id")
    contract["parent_guard"] = {
        "ledger_path": resource.get("ledger_path"),
        "same_parent_ledger": resource.get("same_parent_ledger"),
        "ledger_reset": resource.get("ledger_reset"),
        "allow_missing_parent": resource.get("allow_missing_parent"),
        "reservation_before_payload_content_hash": True,
        "terminal_records_required": ["immutable Home receipt", "returned parent report"],
        "synthetic_report_merge": "FORBIDDEN",
    }
    contract["storage_scope"]["actual_launch"] = dict(actual["storage"])
    contract["commands"]["actual_parent_closed_executor"] = \
        actual["execution"].get("closed_executor_command", actual["execution"].get("command"))
    contract["actual_launch_binding"] = {
        "parent_request": {
            "path": str(actual["parent_path"]),
            "physical_sha256": actual["parent_physical"],
            "canonical_sha256": parent.get("sha256"),
            "schema": parent.get("schema"),
            "status": parent.get("status"),
        },
        "metadata_preflight": {
            "path": str(actual["evidence_path"]),
            "physical_sha256": actual["evidence_physical"],
            "schema": actual["evidence"].get("schema"),
            "status": actual["evidence"].get("status"),
            "request_sha256": actual["evidence"].get("request_sha256"),
            "executor_request_sha256": actual["evidence"].get("executor_request_sha256"),
            "payload_read": actual["evidence"].get("payload_read"),
        },
        "executor_sha256": executor_sha,
        "attempt_id": resource.get("attempt_id"),
        "charge_id": resource.get("charge_id"),
        "namespace": actual["evidence"].get("namespace"),
        "storage_scope": dict(actual["storage"]),
        "terminal_parent_request_sha_required": actual["parent_physical"],
    }


def _base_contract(inputs: Mapping[str, Any]) -> dict[str, Any]:
    values = inputs["values"]
    executor = values["executor"]
    parent = values["parent"]
    pg = values["postterminal"]
    split = inputs["split_cli"]
    storage = inputs["storage"]
    execution = inputs["execution"]
    contract: dict[str, Any] = {
        "schema": SCHEMA,
        "status": PREPARED_STATUS,
        "role": "DEVELOPMENT",
        "qualification": dict(UNKNOWN),
        "phase": "STATIC_PREPARATION_ONLY",
        "case_id": executor.get("case_id"),
        "family_id": executor.get("family_id"),
        "parent_attempt_id": parent.get("parent_resource_binding", {}).get("attempt_id"),
        "input_bindings": {
            "executor_request": _binding(inputs["paths"]["executor_request"], executor,
                                          inputs["physical"]["executor_request"]),
            "parent_request": _binding(inputs["paths"]["parent_request"], parent,
                                        inputs["physical"]["parent_request"]),
            "metadata_preflight": _binding(inputs["paths"]["preflight"], values["preflight"],
                                            inputs["physical"]["preflight"]),
            "postterminal_request": _binding(inputs["paths"]["postterminal_request"], pg,
                                              inputs["physical"]["postterminal_request"]),
            # The declared path remains the immutable provenance.  An explicit
            # relocation overlay is a separate binding and is never inferred
            # from a matching SHA.
            "source_path_overlays": dict(inputs.get("source_overlays", {})),
        },
        "parent_guard": {
            "ledger_path": parent.get("parent_resource_binding", {}).get("ledger_path"),
            "same_parent_ledger": parent.get("parent_resource_binding", {}).get("same_parent_ledger"),
            "ledger_reset": parent.get("parent_resource_binding", {}).get("ledger_reset"),
            "allow_missing_parent": parent.get("parent_resource_binding", {}).get("allow_missing_parent"),
            "reservation_before_payload_content_hash": True,
            "terminal_records_required": ["immutable Home receipt", "returned parent report"],
            "synthetic_report_merge": "FORBIDDEN",
        },
        "storage_scope": {
            "external_filesystem": storage.get("external_filesystem"),
            "target_root": storage.get("target_root"),
            "output_root": storage.get("output_root"),
            "supervisor_output_root": storage.get("supervisor_output_root"),
            "external_reservation_bytes": storage.get("external_reservation_bytes"),
            "source_copy_bytes": storage.get("source_copy_bytes"),
            "home_receipt_bytes": storage.get("home_receipt_bytes"),
            "home_min_free_bytes": storage.get("home_min_free_bytes"),
            "two_filesystem_charge_required": storage.get("two_filesystem_charge_required"),
            "new_namespace_absent_before_run": storage.get("new_namespace_absent_before_run"),
        },
        "runtime_closure": {
            "schema": "ds02.stage2.f2-root145-runtime-closure-contract.v3",
            "materialization_policy": inputs["closure"].get("materialization_path_policy"),
            "original_path_fallback": "FORBIDDEN",
            "literal_interpreter": inputs["literal_interpreter"],
            "role_count": len(inputs["runtime_roles"]),
            "roles": inputs["runtime_roles"],
            "pinned_sources": inputs["pinned_sources"],
            "abi_smoke": {
                "command": inputs["abi_command"],
                "phase": "AFTER_PARENT_RESERVATION_BEFORE_PAYLOAD",
                "payload_read": False,
                "source_path_fallback": "FORBIDDEN",
            },
        },
        "commands": {
            "copied_v53_run": execution.get("command"),
            "postterminal_split_parent_and_returned_report": split,
            "fresh_v16_proof": execution.get("postterminal_commands", {}).get("fresh_v16_proof", {}).get("command_template"),
            "fresh_v10_semantic_proof": execution.get("postterminal_commands", {}).get("fresh_v10_semantic_proof", {}).get("command_template"),
            "evaluator_adapter": execution.get("postterminal_commands", {}).get("evaluator_adapter", {}).get("command_template"),
        },
        "required_terminal_artifacts": {
            "current_runtime_view": {"role": "current_runtime_view", "path": inputs["artifact_paths"]["current_runtime_view"], "sha256": None, "status": "PENDING"},
            "relocated_v15_request": {"role": "relocated_v15_request", "path": inputs["artifact_paths"]["relocated_v15_request"], "sha256": None, "status": "PENDING"},
            "engine_report": {"role": "engine_report", "path": inputs["artifact_paths"]["engine_report"], "sha256": None, "status": "PENDING"},
            "parent_receipt": {"path": None, "sha256": None, "status": "PENDING"},
            "returned_parent_report": {"path": None, "sha256": None, "status": "PENDING"},
            "worker_report": {"path": None, "sha256": None, "status": "PENDING"},
            "source_contract": {"path": None, "sha256": None, "status": "PENDING"},
        },
        "proof_and_evaluator": {
            "old_root060_proof_reuse": "FORBIDDEN",
            "old_root122_partial_reuse": "FORBIDDEN",
            "fresh_v16_proof": "DEFERRED_UNTIL_NEW_TYPED_RESULT_AND_CURRENT_VIEW",
            "private_no_model_evaluator": "DEFERRED_UNTIL_FRESH_PROOF",
            "model_invoked": False,
            "cfd_invoked": False,
            "qualification": dict(UNKNOWN),
        },
        "source_content_hash_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
        "payload_read_during_prepare": False,
        "limitations": [
            "This contract records copied runtime expectations and exact command templates; it is not a terminal product or scientific result.",
            "The parent must independently verify terminal fee closure, reservation release, target/source SHA and OS-level opens.",
            "The literal external venv is an explicit environment exception; standalone-environment portability remains UNKNOWN.",
            "No old ROOT060 proof or ROOT122 copied partial may satisfy the fresh proof/evaluator stages.",
        ],
    }
    return contract


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(path, "output")
    if target.exists() or target.is_symlink():
        raise ContractError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = dict(value)
    body["sha256"] = canonical_sha(body)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(body, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def _small_terminal_binding(path: Path | str, role: str, *, output_root: Path) -> dict[str, Any]:
    target, value, physical = load_json(path, role)
    if not _under(target, output_root):
        raise ContractError(f"{role} escapes the new output namespace: {target}")
    result = {"path": str(target), "physical_sha256": physical,
              "schema": value.get("schema"), "status": value.get("status")}
    if isinstance(value.get("sha256"), str):
        result["declared_canonical_sha256"] = value["sha256"]
        if value["sha256"] == canonical_sha(value):
            result["canonical_verified"] = True
        else:
            raise ContractError(f"{role} canonical SHA differs")
    return result


def _bind_terminal(*, prepared: Mapping[str, Any], parent_receipt: Path | str,
                   returned_parent_report: Path | str, worker_report: Path | str,
                   source_contract: Path | str, current_runtime_view: Path | str,
                   relocated_v15_request: Path | str, engine_report: Path | str) -> dict[str, Any]:
    storage = prepared["storage_scope"]
    output_root = _absolute(storage["output_root"], "output_root")
    home_path, home, home_physical = load_json(parent_receipt, "Home parent receipt")
    returned_path, returned, returned_physical = load_json(returned_parent_report, "returned parent report")
    if home.get("schema") != "ds02.stage2.f2-portable-executor-parent-report.v3":
        raise ContractError("Home receipt schema differs")
    if returned.get("schema") != home.get("schema"):
        raise ContractError("returned report schema differs from Home receipt")
    request = home.get("request")
    executor = home.get("executor")
    expected_executor = prepared["input_bindings"]["executor_request"]
    if not isinstance(request, Mapping):
        raise ContractError("Home receipt lacks its parent request binding")
    if not isinstance(executor, Mapping) or executor.get("sha256") != expected_executor["physical_sha256"]:
        raise ContractError("Home receipt executor SHA is not bound to this executor request")
    if returned.get("report_path") != str(home_path):
        raise ContractError("returned report does not bind the Home receipt path")
    actual = prepared.get("actual_launch_binding")
    if not isinstance(actual, Mapping):
        raise ContractError("prepared contract lacks actual launch binding")
    launch_parent = actual.get("parent_request")
    if not isinstance(launch_parent, Mapping):
        raise ContractError("actual launch parent binding is incomplete")
    launch_parent_sha = launch_parent.get("physical_sha256")
    if request.get("sha256") != launch_parent_sha:
        raise ContractError("Home receipt request SHA is not bound to actual launch parent")
    if returned.get("request_sha256") != launch_parent_sha:
        raise ContractError("returned report request SHA differs")
    charge = returned.get("charge")
    row = charge.get("charge") if isinstance(charge, Mapping) else None
    if not isinstance(charge, Mapping) or charge.get("ledger_mutated") is not True or not isinstance(row, Mapping):
        raise ContractError("returned report does not prove a same-parent charge")
    parent_attempt_id = actual.get("attempt_id")
    if row.get("parent_attempt_id") != parent_attempt_id:
        raise ContractError("terminal charge parent attempt differs from actual launch")
    if not isinstance(home.get("status"), str) or not home["status"].startswith("COMPLETED"):
        raise ContractError("Home receipt is not a completed terminal record")
    if not isinstance(returned.get("status"), str) or not returned["status"].startswith("COMPLETED"):
        raise ContractError("returned parent report is not a completed terminal record")
    if str(row.get("status", "")).lower() not in {"completed", "closed", "charged"}:
        raise ContractError("same-parent charge row is not closed")
    if home.get("model_invoked") not in (None, False) or returned.get("model_invoked") not in (None, False):
        raise ContractError("terminal record claims a model invocation")
    if home.get("cfd_invoked") not in (None, False) or returned.get("cfd_invoked") not in (None, False):
        raise ContractError("terminal record claims a CFD invocation")
    accounting = home.get("accounting")
    if not isinstance(accounting, Mapping) or accounting.get("charge_id") != row.get("id"):
        raise ContractError("Home/returned charge IDs differ")
    artifacts = {
        "parent_receipt": {"path": str(home_path), "physical_sha256": home_physical, "status": home.get("status")},
        "returned_parent_report": {"path": str(returned_path), "physical_sha256": returned_physical, "status": returned.get("status")},
        "worker_report": _small_terminal_binding(worker_report, "worker_report", output_root=output_root),
        "source_contract": _small_terminal_binding(source_contract, "source_contract", output_root=output_root),
        "current_runtime_view": _small_terminal_binding(current_runtime_view, "current_runtime_view", output_root=output_root),
        "relocated_v15_request": _small_terminal_binding(relocated_v15_request, "relocated_v15_request", output_root=output_root),
        "engine_report": _small_terminal_binding(engine_report, "engine_report", output_root=output_root),
    }
    result = dict(prepared)
    result["schema"] = SCHEMA
    result["status"] = BOUND_STATUS
    result["phase"] = "POST_TERMINAL_METADATA_ONLY"
    result["terminal_bindings"] = {
        "parent_attempt_id": row.get("parent_attempt_id"),
        "charge_id": row.get("id"),
        "same_parent_ledger": returned.get("ledger_mutated") is True,
        "reservation_released": returned.get("reservation_released"),
        "reservation_release_verification": (
            "reported_true" if returned.get("reservation_released") is True
            else "parent_must_verify_from_ledger_and_receipt"),
        "home_receipt_status": home.get("status"),
        "returned_report_status": returned.get("status"),
        "charge_status": row.get("status"),
    }
    result["required_terminal_artifacts"] = artifacts
    result["payload_read_during_bind"] = False
    result["qualification"] = dict(UNKNOWN)
    return result


def prepare(*, executor_request: Path | str, parent_request: Path | str,
            preflight: Path | str, postterminal_request: Path | str,
            output: Path | str, actual_parent_request: Path | str,
            actual_preflight: Path | str,
            source_overlays: Mapping[str, Path | str] | None = None) -> dict[str, Any]:
    inputs = _prepare_inputs(executor_request=executor_request, parent_request=parent_request,
                             preflight=preflight, postterminal_request=postterminal_request,
                             source_overlays=source_overlays)
    actual = _actual_launch_inputs(parent_request=actual_parent_request,
                                   metadata_preflight=actual_preflight,
                                   expected_executor_sha=inputs["physical"]["executor_request"])
    value = _base_contract(inputs)
    _attach_actual_launch(value, actual,
                          executor_sha=inputs["physical"]["executor_request"])
    out = _write_new(output, value)
    return {"schema": SCHEMA, "status": PREPARED_STATUS, "request": str(out),
            "request_sha256": sha256_file(out, role="contract output"),
            "runtime_role_count": len(inputs["runtime_roles"]),
            "actual_launch_parent_sha256": actual["parent_physical"],
            "actual_launch_metadata_sha256": actual["evidence_physical"],
            "payload_read": False, "qualification": dict(UNKNOWN)}


def bind_terminal(*, prepared_contract: Path | str, parent_receipt: Path | str,
                  returned_parent_report: Path | str, worker_report: Path | str,
                  source_contract: Path | str, current_runtime_view: Path | str,
                  relocated_v15_request: Path | str, engine_report: Path | str,
                  output: Path | str) -> dict[str, Any]:
    contract_path, prepared, _ = load_json(prepared_contract, "prepared ROOT145 contract")
    if prepared.get("schema") != SCHEMA or prepared.get("status") != PREPARED_STATUS:
        raise ContractError("prepared contract is not the source-only V3 contract")
    if prepared.get("sha256") != canonical_sha(prepared):
        raise ContractError("prepared contract canonical SHA differs")
    value = _bind_terminal(prepared=prepared, parent_receipt=parent_receipt,
                           returned_parent_report=returned_parent_report, worker_report=worker_report,
                           source_contract=source_contract, current_runtime_view=current_runtime_view,
                           relocated_v15_request=relocated_v15_request, engine_report=engine_report)
    value["prepared_contract"] = {"path": str(contract_path),
                                   "physical_sha256": sha256_file(contract_path, role="prepared contract")}
    out = _write_new(output, value)
    return {"schema": SCHEMA, "status": BOUND_STATUS, "request": str(out),
            "request_sha256": sha256_file(out, role="bound contract output"),
            "payload_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--executor-request", type=Path, required=True)
    prep.add_argument("--parent-request", type=Path, required=True)
    prep.add_argument("--preflight", type=Path, required=True)
    prep.add_argument("--postterminal-request", type=Path, required=True)
    prep.add_argument("--actual-parent-request", type=Path, required=True)
    prep.add_argument("--actual-preflight", type=Path, required=True)
    prep.add_argument("--source-overlay", action="append", default=[], metavar="ROLE=PATH",
                      help="explicit relocated source path; SHA must match the declared role")
    prep.add_argument("--output", type=Path, required=True)
    bind = sub.add_parser("bind-terminal")
    bind.add_argument("--prepared-contract", type=Path, required=True)
    bind.add_argument("--parent-receipt", type=Path, required=True)
    bind.add_argument("--returned-parent-report", type=Path, required=True)
    bind.add_argument("--worker-report", type=Path, required=True)
    bind.add_argument("--source-contract", type=Path, required=True)
    bind.add_argument("--current-runtime-view", type=Path, required=True)
    bind.add_argument("--relocated-v15-request", type=Path, required=True)
    bind.add_argument("--engine-report", type=Path, required=True)
    bind.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            overlays: dict[str, str] = {}
            for item in args.source_overlay:
                if "=" not in item:
                    raise ContractError("--source-overlay must be ROLE=ABSOLUTE_PATH")
                role, path = item.split("=", 1)
                if not role or role in overlays:
                    raise ContractError(f"duplicate or empty source overlay role: {role}")
                overlays[role] = path
            result = prepare(executor_request=args.executor_request, parent_request=args.parent_request,
                             preflight=args.preflight, postterminal_request=args.postterminal_request,
                             output=args.output, actual_parent_request=args.actual_parent_request,
                             actual_preflight=args.actual_preflight,
                             source_overlays=overlays)
        else:
            result = bind_terminal(prepared_contract=args.prepared_contract,
                                   parent_receipt=args.parent_receipt,
                                   returned_parent_report=args.returned_parent_report,
                                   worker_report=args.worker_report, source_contract=args.source_contract,
                                   current_runtime_view=args.current_runtime_view,
                                   relocated_v15_request=args.relocated_v15_request,
                                   engine_report=args.engine_report, output=args.output)
    except (ContractError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"ROOT145 postterminal contract: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
