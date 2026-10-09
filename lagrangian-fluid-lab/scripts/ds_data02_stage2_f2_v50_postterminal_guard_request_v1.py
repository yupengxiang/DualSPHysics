#!/usr/bin/env python3
"""Build a source-only post-terminal hand-off for the V51 cold executor.

ROOT122 copied the declared bundle, then failed before native conversion because
the V40 request still named the consumer worktree's ``v14_operator``.  V51
repairs that edge.  This builder records the next parent-owned stages without
opening raw, BI4, HDF5, typed, or result payloads:

* the V51 copied-module mapping and the complete V50 runtime registry;
* the separately supplied Home receipt and returned parent report contract;
* the pinned external venv ABI smoke boundary;
* concrete copied-runtime commands for closure, sealer, fresh proof, and the
  no-model evaluator.

The output is a request, not a success receipt.  All scientific artefacts and
quality fields remain pending/UNKNOWN until a new parent reservation performs
the actual source checks and native run.  Original source paths are provenance
only and are never executable fallbacks.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
SCHEMA = "ds02.stage2.f2-v50-postterminal-parent-guard-request.v1"
V51_SCHEMA = "ds02.stage2.f2-portable-executor-v51-forward.v1"
V34_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
PARENT_SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
PREFLIGHT_SCHEMA = "ds02.stage2.root.v50-metadata-preflight.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_CODE_BYTES = 8 * 1024 * 1024


class PostterminalRequestError(RuntimeError):
    """Raised when the additive hand-off is not source-bound."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str, *, limit: int = MAX_CODE_BYTES) -> str:
    target = Path(path).expanduser()
    info = target.stat()
    if info.st_size > limit:
        raise PostterminalRequestError(f"refusing oversized bounded input: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise PostterminalRequestError(f"{role} must be a lowercase SHA-256")
    return value


def _absolute(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise PostterminalRequestError(f"{role} must be an absolute path")
    return Path(value).expanduser()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _absolute(str(path), role)
    if target.is_symlink() or not target.is_file():
        raise PostterminalRequestError(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > MAX_JSON_BYTES:
        raise PostterminalRequestError(f"{role} exceeds the bounded JSON limit: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PostterminalRequestError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise PostterminalRequestError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _absolute(str(path), "output")
    if target.exists() or target.is_symlink():
        raise PostterminalRequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def _relative(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise PostterminalRequestError(f"{role} must be a relative path")
    path = Path(value)
    if ".." in path.parts or str(path) != value:
        raise PostterminalRequestError(f"{role} escapes the copied root")
    return value


def _validate_v50(executor_path: Path, executor: Mapping[str, Any],
                  parent_path: Path, parent: Mapping[str, Any],
                  preflight_path: Path, preflight: Mapping[str, Any]) -> None:
    if executor.get("schema") != V34_SCHEMA:
        raise PostterminalRequestError("executor request is not V50 v34")
    if parent.get("schema") != PARENT_SCHEMA:
        raise PostterminalRequestError("parent request is not parent-v3")
    if executor.get("sha256") != canonical_sha(executor):
        raise PostterminalRequestError("executor canonical SHA differs")
    if parent.get("sha256") != canonical_sha(parent):
        raise PostterminalRequestError("parent canonical SHA differs")
    if executor.get("status") not in {"READY_FOR_PARENT_STAGE2_GUARD", "READY_FOR_PARENT_GUARD"}:
        raise PostterminalRequestError("executor is not a parent-guard request")
    if parent.get("status") not in {"READY_FOR_PARENT_GUARD", "READY_FOR_PARENT_STAGE2_GUARD"}:
        raise PostterminalRequestError("parent is not a parent-guard request")
    if executor.get("model_invoked") is not False or executor.get("cfd_invoked") is not False:
        raise PostterminalRequestError("model/CFD state is not false")
    if executor.get("raw_opened") is not False or executor.get("hdf5_opened") is not False:
        raise PostterminalRequestError("V50 build unexpectedly opened payload")
    if executor.get("qualification") != UNKNOWN or parent.get("qualification") != UNKNOWN:
        raise PostterminalRequestError("V50 qualification is not UNKNOWN")
    forward = executor.get("forward_v51")
    if not isinstance(forward, Mapping) or forward.get("schema") != V51_SCHEMA:
        raise PostterminalRequestError("V51 copied-module forward marker is required")
    if preflight.get("schema") != PREFLIGHT_SCHEMA:
        raise PostterminalRequestError("V50 preflight schema differs")
    if preflight.get("status") != "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS":
        raise PostterminalRequestError("V50 preflight is not the metadata-only pass")
    if preflight.get("array_payload_read") is not False:
        raise PostterminalRequestError("V50 preflight claims payload access")
    if preflight.get("qualification_credit") != "NONE":
        raise PostterminalRequestError("V50 preflight claims qualification credit")
    if preflight.get("content_hash_phase") != "AFTER_ATOMIC_PARENT_RESERVATION":
        raise PostterminalRequestError("V50 preflight content phase differs")
    # These are used to prove that the three records refer to one request.  A
    # missing field is rejected rather than silently accepting a neighbouring
    # attempt.
    binding = preflight.get("request_binding")
    if isinstance(binding, Mapping):
        if binding.get("executor_request_sha256") not in {None, executor.get("sha256")}:
            raise PostterminalRequestError("preflight executor binding differs")
        if binding.get("parent_request_sha256") not in {None, parent.get("sha256")}:
            raise PostterminalRequestError("preflight parent binding differs")


def _runtime_rows(executor: Mapping[str, Any], target_root: Path) -> list[dict[str, Any]]:
    rows = executor.get("runtime_sources")
    if not isinstance(rows, list) or not rows:
        raise PostterminalRequestError("V50 runtime_sources are missing")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("role"), str):
            raise PostterminalRequestError(f"runtime_sources[{index}] is malformed")
        role = str(raw["role"])
        if role in seen:
            raise PostterminalRequestError(f"duplicate runtime role: {role}")
        seen.add(role)
        relative = _relative(raw.get("target_relative_path"), f"runtime_sources[{index}].target_relative_path")
        expected = _sha(raw.get("sha256"), f"runtime_sources[{index}].sha256")
        bytes_value = raw.get("bytes")
        if isinstance(bytes_value, bool) or not isinstance(bytes_value, int) or bytes_value < 0:
            raise PostterminalRequestError(f"runtime_sources[{index}].bytes is malformed")
        output.append({
            "role": role,
            "source_path_provenance": raw.get("path"),
            "resolved_source_path_provenance": raw.get("resolved_source_path"),
            "target_relative_path": relative,
            "target_path": str(target_root / relative),
            "expected_sha256": expected,
            "expected_bytes": int(bytes_value),
            "source_mode_bits": raw.get("source_mode_bits", raw.get("mode_bits")),
            "required_executable": raw.get("required_executable", False),
            "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
            "source_path_fallback": "FORBIDDEN",
        })
    return output


def _module_plan(executor: Mapping[str, Any], target_root: Path) -> dict[str, dict[str, Any]]:
    forward = executor.get("forward_v51")
    if not isinstance(forward, Mapping) or forward.get("schema") != V51_SCHEMA:
        raise PostterminalRequestError("V51 copied-module forward marker is required")
    plan = forward.get("module_rebinding")
    if not isinstance(plan, Mapping):
        raise PostterminalRequestError("V51 module rebinding plan is missing")
    result: dict[str, dict[str, Any]] = {}
    for role in ("raw_converter", "v14_operator", "v15_operator", "v16_operator"):
        raw = plan.get(role)
        if not isinstance(raw, Mapping):
            raise PostterminalRequestError(f"V51 module role is missing: {role}")
        relative = _relative(raw.get("target_relative_path"), f"V51 module {role}.target_relative_path")
        expected = _sha(raw.get("expected_sha256"), f"V51 module {role}.expected_sha256")
        result[role] = {
            "module_role": role,
            "source_role": raw.get("source_role", role),
            "source_path_provenance": raw.get("source_path_provenance"),
            "target_relative_path": relative,
            "target_path": str(target_root / relative),
            "expected_sha256": expected,
            "expected_bytes": raw.get("expected_bytes"),
            "content_verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
            "source_path_fallback": "FORBIDDEN",
        }
    return result


def _code_role(role: str, relative: str, source: Path) -> dict[str, Any]:
    target = source
    if not target.is_file() or target.is_symlink():
        raise PostterminalRequestError(f"postterminal source is not a regular file: {target}")
    info = target.stat()
    if info.st_size > MAX_CODE_BYTES:
        raise PostterminalRequestError(f"postterminal source exceeds code bound: {target}")
    return {
        "role": role,
        "source_path_provenance": str(target),
        "target_relative_path": _relative(relative, f"{role}.target_relative_path"),
        "expected_sha256": sha256_file(target),
        "expected_bytes": int(info.st_size),
        "source_mode_bits": int(stat.S_IMODE(info.st_mode)),
        "materialization": "PARENT_GUARDED_COPY_AFTER_RESERVATION",
        "source_path_fallback": "FORBIDDEN",
    }


def _metadata_binding(role: str, source: Path, target_root: Path, relative: str) -> dict[str, Any]:
    """Bind a small request JSON to its future copied path.

    This records a physical hash of the request itself.  It does not inspect
    any path named inside that JSON; payload/source content remains a parent
    after-reservation responsibility.
    """
    if source.is_symlink() or not source.is_file():
        raise PostterminalRequestError(f"{role} is not a regular non-symlink file: {source}")
    info = source.stat()
    if info.st_size > MAX_JSON_BYTES:
        raise PostterminalRequestError(f"{role} exceeds the metadata bound")
    relative = _relative(relative, f"{role}.target_relative_path")
    return {
        "role": role,
        "source_path_provenance": str(source),
        "target_relative_path": relative,
        "target_path": str(target_root / relative),
        "expected_sha256": sha256_file(source, limit=MAX_JSON_BYTES),
        "expected_bytes": int(info.st_size),
        "source_mode_bits": int(stat.S_IMODE(info.st_mode)),
        "copy_phase": "PARENT_GUARDED_COPY_AFTER_RESERVATION",
        "source_path_fallback": "FORBIDDEN",
    }


def _postterminal_roles() -> list[tuple[str, str, str]]:
    return [
        ("executor_v51", "runtime/executor/ds_data02_stage2_f2_portable_executor_v51.py",
         "ds_data02_stage2_f2_portable_executor_v51.py"),
        ("runtime_closure_v2", "runtime/postterminal/ds_data02_stage2_f2_v50_source_only_postterminal_builder_v2.py",
         "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v2.py"),
        ("terminal_inputs_split_v3", "runtime/postterminal/ds_data02_stage2_f2_v50_source_only_postterminal_builder_v3.py",
         "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v3.py"),
        ("terminal_sealer_v2", "runtime/postterminal/ds_data02_stage2_f2_v50_terminal_sealer_v2.py",
         "ds_data02_stage2_f2_v50_terminal_sealer_v2.py"),
        ("fresh_proof_request_builder_v4", "runtime/postterminal/ds_data02_stage2_f2_fresh_v16_proof_request_builder_v4.py",
         "ds_data02_stage2_f2_fresh_v16_proof_request_builder_v4.py"),
        ("fresh_proof_consumer_v11", "runtime/postterminal/ds_data02_stage2_f2_fresh_v16_proof_consumer_v11.py",
         "ds_data02_stage2_f2_fresh_v16_proof_consumer_v11.py"),
        ("fresh_product_interface_v1", "runtime/postterminal/ds_data02_stage2_f2_v47_fresh_product_interface_v1.py",
         "ds_data02_stage2_f2_v47_fresh_product_interface_v1.py"),
        ("evaluator_adapter_v2", "runtime/postterminal/ds_data02_stage2_f2_evaluator_v4_adapter_v2.py",
         "ds_data02_stage2_f2_evaluator_v4_adapter_v2.py"),
    ]


def _literal_python(executor: Mapping[str, Any]) -> str:
    for row in executor.get("runtime_sources", []):
        if isinstance(row, Mapping) and row.get("role") == "python_executable":
            value = row.get("path")
            if isinstance(value, str) and ".venv/bin/python" in value and not value.endswith("python3.10"):
                return value
    raise PostterminalRequestError("V50 has no literal pinned .venv/bin/python invocation")


def _commands(python: str, target: Path, output: Path, *, executor_request: Path,
              parent_request: Path, preflight: Path) -> dict[str, Any]:
    runtime = target / "runtime"
    post = runtime / "postterminal"
    return {
        "abi_smoke": {
            "phase": "AFTER_PARENT_RESERVATION_BEFORE_PAYLOAD",
            "timeout_seconds": 60,
            "command": [python, "-B", "-I", str(post / "abi_smoke.py"),
                         "--output", str(output / "runtime" / "abi-smoke.json")],
            "payload_read": False,
            "source_path_fallback": "FORBIDDEN",
        },
        "runtime_closure": {
            "phase": "AFTER_PARENT_RESERVATION",
            "timeout_seconds": 300,
            "command_template": [python, "-B", "-I", str(post / "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v2.py"),
                                  "--executor-request", str(executor_request), "--parent-request", str(parent_request),
                                  "--runtime-root", str(target), "--output", str(output / "runtime-closure.json"),
                                  "--abi-smoke", str(output / "runtime" / "abi-smoke.json")],
            "content_scope": "code/JSON/stat only; no HDF5/BI4/raw/typed/result payload",
        },
        "split_terminal_inputs": {
            "phase": "AFTER_PARENT_TERMINAL",
            "timeout_seconds": 300,
            "command_template": [python, "-B", "-I", str(post / "ds_data02_stage2_f2_v50_source_only_postterminal_builder_v3.py"),
                                  "--executor-request", str(executor_request), "--parent-request", str(parent_request),
                                  "--v50-preflight", str(preflight), "--home-receipt", "<actual-home-receipt>",
                                  "--returned-parent-report", "<actual-returned-parent-report>", "--output-root", str(output)],
        },
        "v50_sealer": {
            "phase": "AFTER_NEW_TYPED_RESULT_AND_PARENT_STATIC_RECEIPT",
            "timeout_seconds": 900,
            "command_template": [python, "-B", "-I", str(post / "ds_data02_stage2_f2_v50_terminal_sealer_v2.py"),
                                  "--v50-executor-request", str(executor_request), "--v50-parent-request", str(parent_request),
                                  "--v50-metadata-preflight", str(preflight), "--parent-static-verification", "<parent-static-receipt>",
                                  "--terminal-manifest", str(output / "terminal-manifest.json"), "--source-contract", str(output / "source-contract.json"),
                                  "--adapter-output", str(output / "producer-adapter.json"), "--v10-request-output", str(output / "fresh-v10-request.json"),
                                  "--seal-output", str(output / "v50-seal.json")],
            "old_root060_reuse": "FORBIDDEN",
        },
        "fresh_v16_proof": {
            "phase": "AFTER_NEW_TYPED_RESULT_AND_NEW_RUNTIME_CURRENT_VIEW",
            "timeout_seconds": 900,
            "command_template": [python, "-B", "-I", str(post / "ds_data02_stage2_f2_fresh_v16_proof_request_builder_v4.py"),
                                  "--v41-worker-report", str(output / "worker-report.json"), "--v40-engine-report", str(output / "engine-report.json"),
                                  "--v40-contract", str(output / "source-contract.json"), "--target-root", str(target), "--output-root", str(output),
                                  "--adapter-output", str(output / "fresh-proof-adapter.json"), "--request-output", str(output / "fresh-proof-request.json")],
            "old_root060_reuse": "FORBIDDEN",
        },
        "fresh_v10_semantic_proof": {
            "phase": "AFTER_PARENT_RESERVATION_WITH_IO_SLOT",
            "timeout_seconds": 900,
            "command_template": [python, "-B", "-I", str(post / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v11.py"), "run",
                                  "--request", str(output / "fresh-proof-request.json"), "--output", str(output / "fresh-v16-proof.json"),
                                  "--io-slot-approved", "--parent-pid", "<parent-pid>", "--max-wall-seconds", "900"],
            "qualification": "UNKNOWN",
        },
        "evaluator_adapter": {
            "phase": "AFTER_FRESH_V10_PROOF",
            "timeout_seconds": 900,
            "command_template": [python, "-B", "-I", str(post / "ds_data02_stage2_f2_evaluator_v4_adapter_v2.py"),
                                  "--v50-seal", str(output / "v50-seal.json"), "--fresh-proof", str(output / "fresh-v16-proof.json"),
                                  "--fresh-v10-request", str(output / "fresh-v10-request.json"), "--terminal-manifest", str(output / "terminal-manifest.json"),
                                  "--runtime-closure", str(output / "runtime-closure.json"), "--output", str(output / "evaluator-request.json")],
            "model_invoked": False,
            "cfd_invoked": False,
            "qualification": "UNKNOWN",
        },
    }


def build_request(*, executor_request: Path | str, parent_request: Path | str,
                  v50_preflight: Path | str, output: Path | str,
                  target_root: Path | str, output_root: Path | str) -> dict[str, Any]:
    executor_path, executor = _json(executor_request, "V50/V51 executor request")
    parent_path, parent = _json(parent_request, "V50 parent request")
    preflight_path, preflight = _json(v50_preflight, "V50 metadata preflight")
    _validate_v50(executor_path, executor, parent_path, parent, preflight_path, preflight)
    target = _absolute(str(target_root), "target_root")
    product = _absolute(str(output_root), "output_root")
    if target == product:
        raise PostterminalRequestError("target_root and output_root must differ")
    old_roots = executor.get("fresh_roots")
    if isinstance(old_roots, Mapping):
        old_target = old_roots.get("target_root")
        old_product = old_roots.get("output_root")
        if str(target) in {str(old_target), str(old_product)} or str(product) in {str(old_target), str(old_product)}:
            raise PostterminalRequestError("postterminal request cannot reuse the failed V50 namespace")
    if target.exists() or product.exists():
        raise PostterminalRequestError("new target/output namespace must not already exist")
    runtime_rows = _runtime_rows(executor, target)
    module_plan = _module_plan(executor, target)
    literal_python = _literal_python(executor)
    request_bindings = [
        _metadata_binding("v51_executor_request", executor_path, target,
                          "sources/postterminal-v51-executor-request.json"),
        _metadata_binding("parent_request", parent_path, target,
                          "sources/postterminal-parent-request.json"),
        _metadata_binding("v50_preflight", preflight_path, target,
                          "sources/postterminal-v50-preflight.json"),
    ]
    post_roles: list[dict[str, Any]] = []
    existing_runtime_roles = {row["role"] for row in runtime_rows}
    for role, relative, filename in _postterminal_roles():
        # V51 already adds its executor to runtime_sources.  Keep one role
        # record with one expected SHA; duplicate role rows make the copied
        # closure ambiguous and would hide an accidental old executor.
        if role in existing_runtime_roles:
            continue
        source = SCRIPT_DIR / filename
        row = _code_role(role, relative, source)
        row["target_path"] = str(target / relative)
        post_roles.append(row)
    # ABI smoke is an intentionally small generated script; the parent must
    # materialize it and bind its own hash after reservation.
    abi_relative = "runtime/postterminal/abi_smoke.py"
    post_roles.append({
        "role": "abi_smoke_script",
        "source_path_provenance": None,
        "target_relative_path": abi_relative,
        "target_path": str(target / abi_relative),
        "materialization": "PARENT_GENERATED_AFTER_RESERVATION",
        "expected_sha256": None,
        "expected_bytes": None,
        "source_path_fallback": "FORBIDDEN",
    })
    parent_binding = dict(parent.get("parent_resource_binding", {}))
    storage = dict(parent.get("storage_scope", {}))
    command = list(executor.get("execution", {}).get("command", []))
    if not command or not isinstance(command[0], str) or ".venv/bin/python" not in command[0]:
        raise PostterminalRequestError("V50 executor command does not preserve literal venv")
    command[3:4] = [str(target / "runtime/executor/ds_data02_stage2_f2_portable_executor_v51.py")]
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_POSTTERMINAL_GUARD",
        "role": "DEVELOPMENT",
        "request_id": str(executor.get("request_id", "f2-s1-v51")) + "-postterminal-v1",
        "family_id": executor.get("family_id", "F2"),
        "case_id": executor.get("case_id"),
        "model_invoked": False,
        "cfd_invoked": False,
        "raw_opened": False,
        "hdf5_opened": False,
        "qualification": dict(UNKNOWN),
        "parent_resource_binding": {
            **parent_binding,
            "same_parent_ledger": True,
            "ledger_reset": False,
            "no_new_data_root": True,
            "reservation_order": "atomic parent reservation before any copied-source content hash",
            "new_ledger_owner": False,
        },
        "storage_scope": {
            **storage,
            "target_root": str(target),
            "output_root": str(product),
            "source_copy_bytes_declared": storage.get("source_copy_bytes"),
            "typed_output_budget_bytes": storage.get("declared_typed_output_budget_bytes"),
            "decoder_scratch_budget_bytes": storage.get("declared_decoder_scratch_bytes"),
            "trace_and_home_receipt_charged": True,
            "filesystem_accounting": "same-parent dual-filesystem; Home receipt and external output are separate fields",
        },
        "v51_forward": {
            "schema": V51_SCHEMA,
            "executor_request": {"path": str(executor_path), "physical_sha256": sha256_file(executor_path, limit=MAX_JSON_BYTES),
                                  "canonical_sha256": executor.get("sha256")},
            "module_rebinding": module_plan,
            "source_path_fallback": "FORBIDDEN",
            "payload_read_during_build": False,
        },
        "runtime_closure": {
            "schema": "ds02.stage2.f2-postterminal-runtime-closure.v1",
            "status": "PENDING_AFTER_PARENT_RESERVATION",
            "roles": runtime_rows + post_roles,
            "original_path_fallback": "FORBIDDEN",
            "content_scope": "bounded code/JSON/stat and ABI smoke only; payload content deferred",
            "literal_interpreter": {
                "argv0": literal_python,
                "resolved_path_provenance_only": next((r.get("resolved_source_path") for r in executor.get("runtime_sources", [])
                                                       if isinstance(r, Mapping) and r.get("role") == "python_executable"), None),
                "standalone_environment_credit": "UNKNOWN; pinned external venv exception only",
            },
        },
        "copied_module_import_contract": {
            "worker_root": str(target),
            "module_paths": module_plan,
            "all_four_native_roles_rebound": True,
            "original_consumer_worktree_import": "FORBIDDEN",
            "import_audit": "parent-owned private subprocess; source path provenance is not an open permission",
        },
        "parent_terminal_inputs": {
            "home_receipt": {"path": None, "sha256": None, "schema": "parent-v3-home-receipt"},
            "returned_parent_report": {"path": None, "sha256": None, "schema": "parent-v3-returned-report"},
            "two_files_required": True,
            "synthetic_report_merge": "FORBIDDEN",
            "pairing_fields": ["request_sha256", "parent_attempt_id", "charge_id", "same_parent_ledger", "reservation_released"],
            "phase": "AFTER_PARENT_TERMINAL",
        },
        "execution": {
            "command": command,
            "stages": ["copy_and_seal", "v51_module_rebound_raw_to_typed_to_label", "new_v16_semantic_proof", "private_no_model_evaluator"],
            "postterminal_commands": _commands(
                literal_python, target, product,
                executor_request=Path(request_bindings[0]["target_path"]),
                parent_request=Path(request_bindings[1]["target_path"]),
                preflight=Path(request_bindings[2]["target_path"])),
            "parent_guard_required": True,
            "max_wall_seconds": {"copy_and_native": 6000, "closure": 300, "sealer": 900, "fresh_proof": 900, "evaluator": 900},
            "payload_content_hash_phase": "AFTER_ATOMIC_PARENT_RESERVATION",
            "old_root060_reuse": "FORBIDDEN",
            "original_path_fallback": "FORBIDDEN",
        },
        "artifacts": {
            "new_typed_hdf5": {"status": "PENDING", "path": None, "sha256": None},
            "new_v16_result": {"status": "PENDING", "path": None, "sha256": None},
            "fresh_v10_proof": {"status": "PENDING", "path": None, "sha256": None},
            "v50_seal": {"status": "PENDING", "path": None, "sha256": None},
            "evaluator_request": {"status": "PENDING", "path": None, "sha256": None},
        },
        "copied_metadata_inputs": request_bindings,
        "historical_failure": {
            "scope": "ROOT122 failed before native conversion; preserved for provenance only",
            "successful_product_reuse": "FORBIDDEN",
            "old_proof_input": "FORBIDDEN",
        },
        "source_inputs": {
            "executor_request": {"path": str(executor_path), "physical_sha256": sha256_file(executor_path, limit=MAX_JSON_BYTES)},
            "parent_request": {"path": str(parent_path), "physical_sha256": sha256_file(parent_path, limit=MAX_JSON_BYTES)},
            "preflight": {"path": str(preflight_path), "physical_sha256": sha256_file(preflight_path, limit=MAX_JSON_BYTES)},
            "payload_content_read": False,
            "payload_hashes_computed": False,
        },
        "limitations": [
            "This request is source-only and does not prove copied content, ABI success, native conversion, labels, or evaluator success.",
            "The external pinned venv is an explicit environment exception; standalone-environment portability remains UNKNOWN.",
            "QI/QN/QE remain UNKNOWN until a new parent-owned terminal and fresh semantic proof.",
        ],
    }
    value["sha256"] = canonical_sha(value)
    out = _write_new(output, value)
    return {"schema": SCHEMA, "status": value["status"], "request": str(out),
            "request_sha256": sha256_file(out, limit=MAX_JSON_BYTES), "module_roles": sorted(module_plan),
            "runtime_role_count": len(runtime_rows), "postterminal_role_count": len(post_roles),
            "payload_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor-request", type=Path, required=True)
    parser.add_argument("--parent-request", type=Path, required=True)
    parser.add_argument("--v50-preflight", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_request(executor_request=args.executor_request, parent_request=args.parent_request,
                               v50_preflight=args.v50_preflight, target_root=args.target_root,
                               output_root=args.output_root, output=args.output)
    except (PostterminalRequestError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V50 postterminal parent-guard request: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
