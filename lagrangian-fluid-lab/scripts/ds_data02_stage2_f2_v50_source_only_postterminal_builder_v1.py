#!/usr/bin/env python3
"""Build V50 post-terminal sealer inputs from existing small receipts.

This builder is deliberately source-only.  It reads bounded JSON reports and
the pinned code files needed to describe a runtime closure.  It may stat newly
produced typed/result files and carries their producer-declared SHA, but it
never opens or hashes HDF5, BI4, raw frames, typed HDF5, or the large V16
result.

The parent-v3 runner already performs ``_validate_request(...,
verify_static_content=True)`` after reservation and before starting its child.
When that historical parent did not emit an instrumented static receipt, this
builder creates a *derived* sidecar.  Its derivation basis includes the
completed parent report SHA, the exact parent/executor request SHAs, and the
pinned parent/executor source SHAs.  It is never described as an instrumented
receipt.  The V50 sealer consumes the sidecar only after checking those exact
bindings.

The second entry point creates the evaluator's explicit copied-code closure.
The literal project venv Python is supported as an explicitly pinned external
interpreter exception: its invocation path is preserved verbatim, its resolved
binary is provenance only, and a small ABI-smoke receipt is required for an
evaluator-ready closure.  Scientific/source fallback remains forbidden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_CODE_BYTES = 64 * 1024 * 1024

PARENT_REPORT_SCHEMA = "ds02.stage2.f2-portable-executor-parent-report.v3"
CHILD_REPORT_SCHEMA = "ds02.stage2.f2-portable-executor-report.v34"
WORKER_REPORT_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2"
MANIFEST_SCHEMA = "ds02.stage2.f2-v47-producer-terminal-manifest.v1"
STATIC_SCHEMA = "ds02.stage2.f2-v50-parent-static-content-verification.v1"
STATIC_STATUS = "PASS_PARENT_STATIC_CONTENT_AFTER_RESERVATION"
STATIC_PHASE = "AFTER_ATOMIC_PARENT_RESERVATION"
CLOSURE_SCHEMA = "ds02.stage2.f2-postterminal-evaluator-runtime-closure.v1"
CLOSURE_STATUS = "READY_FOR_PARENT_EVALUATOR_GUARD"
ABI_SMOKE_SCHEMA = "ds02.stage2.f2-pinned-venv-abi-smoke.v1"
ABI_SMOKE_STATUS = "PASS_LITERAL_VENV_ABI_IMPORT"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_OVERLAY_SHA = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
RAW_TREE_SHA = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
RAW_TREE_FILES = 405
RAW_TREE_FRAMES = 401
REQUIRED_RUNTIME_ROLES = {
    "python_executable", "evaluator_v4", "evaluator_v3", "evaluator_v2",
    "v14_operator", "v15_operator", "v16_operator", "raw_converter",
    "raw_reconstruction_worker", "proof_consumer_v11", "proof_consumer_v10",
    "proof_consumer_v9", "proof_consumer_v8", "v47_terminal_sealer_v1",
    "v47_fresh_product_interface_v1", "interpreter_abi_smoke",
}


class BuilderError(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise BuilderError(f"{role} must be a lowercase SHA-256")
    return value


def sha256_file(path: Path | str, *, max_bytes: int | None = None, role: str = "file") -> str:
    target = Path(path).expanduser()
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise BuilderError(f"refusing to hash oversized {role}: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, role: str, *, allow_symlink: bool = False) -> dict[str, int]:
    info = path.stat()
    if (path.is_symlink() and not allow_symlink) or not stat.S_ISREG(info.st_mode):
        raise BuilderError(f"{role} is not a regular file")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _file(path: Any, role: str, *, max_bytes: int = MAX_JSON_BYTES,
          allow_symlink: bool = False) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).startswith("/"):
        raise BuilderError(f"{role} must be an absolute path")
    target = Path(path).expanduser()
    if target.is_symlink() and not allow_symlink:
        raise BuilderError(f"{role} may not be a symlink: {target}")
    if not target.is_file():
        raise BuilderError(f"{role} is missing: {target}")
    if target.stat().st_size > max_bytes:
        raise BuilderError(f"{role} exceeds bounded metadata size: {target}")
    return target


def _json(path: Path | str, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role, max_bytes=max_bytes)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BuilderError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise BuilderError(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise BuilderError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _canonical_binding(path: Path, role: str) -> dict[str, Any]:
    value = _json(path, role)[1]
    if value.get("sha256") != canonical_sha(value):
        raise BuilderError(f"{role} canonical SHA differs")
    return {"path": str(path), "sha256": sha256_file(path, max_bytes=MAX_JSON_BYTES, role=role),
            "canonical_sha256": str(value["sha256"]), "bytes": path.stat().st_size,
            "stat": _stat(path, role)}


def _payload_binding(value: Any, role: str, *, output_root: Path, namespace_root: Path) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BuilderError(f"{role} producer binding is missing")
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not raw_path.startswith("/"):
        raise BuilderError(f"{role}.path is missing/relative")
    path = Path(raw_path).expanduser()
    if not path.is_file() or path.is_symlink():
        raise BuilderError(f"{role} is not a regular fresh artifact: {path}")
    if not _under(path, output_root) and not _under(path, namespace_root):
        raise BuilderError(f"{role} is outside fresh producer namespace: {path}")
    sha = _sha(value.get("sha256"), f"{role}.sha256")
    raw_bytes = value.get("bytes")
    if isinstance(raw_bytes, bool) or not isinstance(raw_bytes, int) or raw_bytes != path.stat().st_size:
        raise BuilderError(f"{role}.bytes differs from current stat")
    return {"role": role, "path": str(path), "sha256": sha, "bytes": int(raw_bytes),
            "stat": _stat(path, role), "content_sha_verified": True,
            "verification_phase": "PARENT_AFTER_RESERVATION",
            "verified_by": "producer_report_declared_sha_and_completed_parent_v3"}


def _small_artifact(path: Path | str, role: str, *, output_root: Path, namespace_root: Path) -> dict[str, Any]:
    target = _file(path, role, max_bytes=MAX_JSON_BYTES)
    if not _under(target, output_root) and not _under(target, namespace_root):
        raise BuilderError(f"{role} is outside fresh producer namespace")
    return {"role": role, "path": str(target), "sha256": sha256_file(target, max_bytes=MAX_JSON_BYTES, role=role),
            "bytes": target.stat().st_size, "stat": _stat(target, role),
            "content_sha_verified": True, "verification_phase": "PARENT_AFTER_RESERVATION",
            "verified_by": "completed_parent_v3_report_and_bounded_json"}


def _parent_report(path: Path, parent_request: Path, executor_request: Path) -> dict[str, Any]:
    _, value = _json(path, "completed parent-v3 report")
    if value.get("schema") != PARENT_REPORT_SCHEMA:
        raise BuilderError(f"completed parent report schema differs: {value.get('schema')!r}")
    if value.get("status") != "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN":
        raise BuilderError(f"parent is not completed: {value.get('status')!r}")
    request = value.get("request")
    if not isinstance(request, Mapping) or request.get("path") != str(parent_request):
        raise BuilderError("parent report does not bind the supplied parent request")
    if request.get("sha256") != sha256_file(parent_request, max_bytes=MAX_JSON_BYTES, role="parent request"):
        raise BuilderError("parent report parent request SHA differs")
    executor = value.get("executor")
    if not isinstance(executor, Mapping) or executor.get("path") != str(executor_request):
        raise BuilderError("parent report does not bind the supplied executor request")
    if executor.get("sha256") != sha256_file(executor_request, max_bytes=MAX_JSON_BYTES, role="executor request"):
        raise BuilderError("parent report executor SHA differs")
    execution = value.get("execution")
    required_cover = {"metadata/stat preflight", "same-parent reservation",
                      "v34 child copy/hash/worker/evaluator"}
    covered = set(execution.get("hard_wall_covers", [])) if isinstance(execution, Mapping) else set()
    if not required_cover.issubset(covered):
        raise BuilderError("parent report does not prove the post-reservation validation phase")
    charge = value.get("charge")
    if not isinstance(charge, Mapping) or charge.get("ledger_mutated") is not True:
        raise BuilderError("parent report has no closed same-ledger charge")
    parent = value.get("parent")
    if not isinstance(parent, Mapping) or parent.get("same_parent_ledger") is not True:
        raise BuilderError("parent report same-ledger binding is missing")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise BuilderError("parent report model/CFD boundary is not closed")
    return value


def _worker_report(path: Path, *, output_root: Path, namespace_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    _, value = _json(path, "native worker report")
    if value.get("schema") != WORKER_REPORT_SCHEMA:
        raise BuilderError(f"native worker report schema differs: {value.get('schema')!r}")
    if value.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise BuilderError(f"native worker is not complete: {value.get('status')!r}")
    boundary = value.get("execution_boundary")
    if not isinstance(boundary, Mapping) or boundary.get("raw_opened") is not True \
            or boundary.get("hdf5_opened") is not True or boundary.get("model_invoked") is not False \
            or boundary.get("cfd_invoked") is not False:
        raise BuilderError("native worker boundary does not prove guarded payload stage")
    typed = _payload_binding(value.get("typed_output"), "typed_hdf5", output_root=output_root, namespace_root=namespace_root)
    labels = value.get("typed_to_label")
    if not isinstance(labels, Mapping) or labels.get("status") != "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN":
        raise BuilderError("native worker V15 labels are not complete")
    v15 = _payload_binding({"path": labels.get("result"), "sha256": labels.get("result_sha256"),
                            "bytes": Path(str(labels.get("result"))).stat().st_size if isinstance(labels.get("result"), str) and Path(str(labels.get("result"))).is_file() else None},
                           "v15_result", output_root=output_root, namespace_root=namespace_root)
    v16 = labels.get("v16_forward")
    if not isinstance(v16, Mapping) or v16.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise BuilderError("native worker V16 labels are not complete")
    v16_binding = _payload_binding({"path": v16.get("result"), "sha256": v16.get("result_sha256"),
                                    "bytes": Path(str(v16.get("result"))).stat().st_size if isinstance(v16.get("result"), str) and Path(str(v16.get("result"))).is_file() else None},
                                   "v16_result", output_root=output_root, namespace_root=namespace_root)
    raw_to_typed = value.get("raw_to_typed")
    if not isinstance(raw_to_typed, Mapping) or not isinstance(raw_to_typed.get("converter_report"), str):
        raise BuilderError("native worker converter report is missing")
    converter = _small_artifact(raw_to_typed["converter_report"], "raw_converter_report",
                                output_root=output_root, namespace_root=namespace_root)
    summary = {"typed": typed, "v15": v15, "v16": v16_binding, "converter": converter}
    return value, summary


def _source_identity(executor_request: Path, source_contract: Path) -> dict[str, Any]:
    _, executor = _json(executor_request, "executor request")
    _, contract = _json(source_contract, "source contract")
    if contract.get("sha256") != canonical_sha(contract):
        raise BuilderError("source contract canonical SHA differs")
    expected = contract.get("expected")
    source = expected.get("source_binding") if isinstance(expected, Mapping) else None
    provenance = contract.get("current_catalog_provenance")
    if not isinstance(source, Mapping) or not isinstance(provenance, Mapping):
        raise BuilderError("source contract identity fields are missing")
    actual = provenance.get("actual_current_catalog")
    if not isinstance(actual, Mapping) or actual.get("sha256") != CURRENT_SHA:
        raise BuilderError("source contract exact CURRENT identity is not df7e")
    relocated = _sha(source.get("current_catalog_sha256"), "relocated CURRENT SHA")
    if relocated in {CURRENT_SHA, HISTORICAL_OVERLAY_SHA}:
        raise BuilderError("source contract relocated view is stale")
    raw = executor.get("execution", {}).get("raw_tree_binding", {}) if isinstance(executor.get("execution"), Mapping) else {}
    if not isinstance(raw, Mapping) or raw.get("tree_sha256") != RAW_TREE_SHA \
            or raw.get("file_count") != RAW_TREE_FILES or raw.get("frame_count") != RAW_TREE_FRAMES:
        raise BuilderError("executor frozen raw-tree identity is missing")
    return {"actual_current_catalog_sha256": CURRENT_SHA,
            "relocated_runtime_view_sha256": relocated,
            "raw_tree_sha256": RAW_TREE_SHA, "raw_tree_file_count": RAW_TREE_FILES,
            "raw_tree_frame_count": RAW_TREE_FRAMES}


def _pinned_code_bindings(rows: Sequence[str], *, root: Path | None = None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if "=" not in raw:
            raise BuilderError("--pinned-source must be role=/absolute/path")
        role, raw_path = raw.split("=", 1)
        if not role or not raw_path.startswith("/") or role in result:
            raise BuilderError(f"malformed/duplicate pinned source: {raw}")
        path = _file(raw_path, role, max_bytes=MAX_CODE_BYTES)
        if root is not None and not _under(path, root):
            raise BuilderError(f"pinned source {role} is outside copied runtime root")
        result[role] = {"role": role, "path": str(path), "sha256": sha256_file(path, max_bytes=MAX_CODE_BYTES, role=role),
                        "bytes": path.stat().st_size, "stat": _stat(path, role), "content_read": True}
    return result


def build_runtime_closure(*, executor_request: Path | str, runtime_root: Path | str,
                          output: Path | str, role_bindings: Sequence[str],
                          pinned_sources: Sequence[str], abi_smoke: Path | str | None = None) -> dict[str, Any]:
    executor_path, executor = _json(executor_request, "executor request")
    if executor.get("sha256") != canonical_sha(executor):
        raise BuilderError("executor request canonical SHA differs")
    root = Path(runtime_root).expanduser().resolve()
    if not root.is_dir():
        raise BuilderError(f"runtime root is missing: {root}")
    expected: dict[str, Mapping[str, Any]] = {}
    for row in executor.get("runtime_sources", []):
        if isinstance(row, Mapping) and isinstance(row.get("role"), str):
            expected[str(row["role"])] = row
    roles = _pinned_code_bindings(pinned_sources, root=root)
    for raw in role_bindings:
        if "=" not in raw:
            raise BuilderError("--role-binding must be role=/absolute/path")
        role, raw_path = raw.split("=", 1)
        if not role or role in roles:
            raise BuilderError(f"malformed/duplicate runtime role: {raw}")
        roles[role] = {"role": role, "path": raw_path}
    for role in REQUIRED_RUNTIME_ROLES:
        if role == "interpreter_abi_smoke":
            continue
        if role not in roles and role in expected:
            row = expected[role]
            relative = row.get("target_relative_path")
            if isinstance(relative, str) and not relative.startswith("/"):
                candidate = root / "runtime" / relative
                if candidate.is_file():
                    roles[role] = {"role": role, "path": str(candidate), "expected_sha256": row.get("sha256")}
        if role not in roles:
            raise BuilderError(f"runtime closure role is missing: {role}")
    out_rows: list[dict[str, Any]] = []
    interpreter: dict[str, Any] | None = None
    for role in sorted(roles):
        raw = roles[role]
        path = _file(raw.get("path"), f"runtime role {role}", max_bytes=MAX_CODE_BYTES,
                     allow_symlink=(role == "python_executable"))
        if role != "python_executable" and not _under(path, root):
            raise BuilderError(f"runtime role {role} is outside copied runtime root")
        expected_sha = raw.get("expected_sha256") or expected.get(role, {}).get("sha256")
        observed_sha = sha256_file(path, max_bytes=MAX_CODE_BYTES, role=f"runtime role {role}")
        if expected_sha is not None and observed_sha != _sha(expected_sha, f"runtime role {role}.expected_sha256"):
            raise BuilderError(f"runtime role {role} SHA differs from executor closure")
        row = {"role": role, "path": str(path), "sha256": observed_sha,
               "bytes": path.stat().st_size, "stat": _stat(path, role, allow_symlink=(role == "python_executable")),
               "content_verified_by_builder": True}
        if role == "python_executable":
            if not path.is_symlink() or ".venv" not in str(path) or path.name != "python":
                raise BuilderError("python_executable must be the literal pinned project venv path")
            resolved = path.resolve()
            if not resolved.is_file():
                raise BuilderError("pinned venv interpreter target is missing")
            row.update({"external_pinned": True, "interpreter_mode": "EXTERNAL_PINNED_VENV_INTERPRETER",
                        "literal_invocation_path": str(path), "resolved_path": str(resolved),
                        "original_path_fallback": "PINNED_ENV_ONLY"})
            interpreter = row
        out_rows.append(row)
    if abi_smoke is None:
        raise BuilderError("--abi-smoke is required for an evaluator-ready pinned interpreter closure")
    abi_path, abi = _json(abi_smoke, "pinned interpreter ABI smoke")
    if not _under(abi_path, root):
        raise BuilderError("ABI smoke is outside copied runtime root")
    if abi.get("schema") != ABI_SMOKE_SCHEMA or abi.get("status") != ABI_SMOKE_STATUS:
        raise BuilderError("pinned interpreter ABI smoke is not a PASS receipt")
    if interpreter is None or abi.get("literal_argv0") != interpreter["literal_invocation_path"]:
        raise BuilderError("ABI smoke does not bind the literal venv argv0")
    abi_row = {"role": "interpreter_abi_smoke", "path": str(abi_path),
               "sha256": sha256_file(abi_path, max_bytes=MAX_JSON_BYTES, role="ABI smoke"),
               "bytes": abi_path.stat().st_size, "stat": _stat(abi_path, "ABI smoke"),
               "content_verified_by_builder": True}
    out_rows.append(abi_row)
    closure: dict[str, Any] = {
        "schema": CLOSURE_SCHEMA, "status": CLOSURE_STATUS,
        "runtime_root": str(root), "original_path_fallback": "FORBIDDEN",
        "interpreter_contract": {
            "mode": "EXTERNAL_PINNED_VENV_INTERPRETER",
            "literal_argv0": interpreter["literal_invocation_path"],
            "resolved_path_provenance_only": interpreter["resolved_path"],
            "abi_smoke": {"path": str(abi_path), "sha256": abi_row["sha256"]},
            "standalone_environment_credit": "UNKNOWN; explicit environment binding required",
            "scientific_source_fallback": "FORBIDDEN",
        },
        "roles": out_rows,
        "source_executor_request": {"path": str(executor_path), "sha256": sha256_file(executor_path, max_bytes=MAX_JSON_BYTES, role="executor request")},
        "content_read_scope": "small code/JSON only; no HDF5/BI4/raw/typed/result payload",
    }
    closure["sha256"] = canonical_sha(closure)
    output_path = _write_new(output, closure)
    return {"schema": CLOSURE_SCHEMA, "status": CLOSURE_STATUS,
            "closure": str(output_path), "sha256": closure["sha256"],
            "payload_read": False, "qualification": dict(UNKNOWN)}


def build_terminal_inputs(*, executor_request: Path | str, parent_request: Path | str,
                          preflight: Path | str, parent_report: Path | str,
                          worker_report: Path | str, source_contract: Path | str,
                          output_root: Path | str, namespace_root: Path | str,
                          static_output: Path | str, manifest_output: Path | str,
                          pinned_sources: Sequence[str], artifact_bindings: Sequence[str]) -> dict[str, Any]:
    executor_path = _file(executor_request, "executor request", max_bytes=MAX_JSON_BYTES)
    parent_path = _file(parent_request, "parent request", max_bytes=MAX_JSON_BYTES)
    preflight_path = _file(preflight, "V50 metadata preflight", max_bytes=MAX_JSON_BYTES)
    contract_path = _file(source_contract, "source contract", max_bytes=MAX_JSON_BYTES)
    _, executor = _json(executor_path, "executor request")
    _, parent = _json(parent_path, "parent request")
    _, preflight_value = _json(preflight_path, "V50 metadata preflight")
    if executor.get("schema") != "ds02.stage2.f2-portable-executor-request.v34":
        raise BuilderError("executor schema is not v34")
    if parent.get("schema") != "ds02.stage2.f2-portable-executor-parent-request.v3":
        raise BuilderError("parent schema is not parent-v3")
    if preflight_value.get("schema") != "ds02.stage2.root.v50-metadata-preflight.v1" \
            or preflight_value.get("status") != "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS":
        raise BuilderError("V50 metadata preflight schema/status differs")
    if preflight_value.get("array_payload_read") is not False \
            or preflight_value.get("qualification_credit") not in {None, "NONE"}:
        raise BuilderError("V50 metadata preflight claims payload access or qualification credit")
    if preflight_value.get("content_hash_phase") != "AFTER_ATOMIC_PARENT_RESERVATION":
        raise BuilderError("V50 metadata preflight content phase differs")
    if preflight_value.get("namespace_absent") is not True:
        raise BuilderError("V50 metadata preflight namespace absence is not explicit")
    report_path = _file(parent_report, "completed parent report", max_bytes=MAX_JSON_BYTES)
    report = _parent_report(report_path, parent_path, executor_path)
    out_root = Path(output_root).expanduser().resolve()
    ns_root = Path(namespace_root).expanduser().resolve()
    if not out_root.is_dir() or not ns_root.is_dir():
        raise BuilderError("fresh output/namespace roots must exist after the producer run")
    worker_path = _file(worker_report, "native worker report", max_bytes=MAX_JSON_BYTES)
    worker, products = _worker_report(worker_path, output_root=out_root, namespace_root=ns_root)
    # Explicit JSON roles are copied-runtime/product metadata that the V47
    # manifest requires but the worker report does not name directly.
    explicit: dict[str, dict[str, Any]] = {}
    for raw in artifact_bindings:
        if "=" not in raw:
            raise BuilderError("--artifact must be role=/absolute/path")
        role, raw_path = raw.split("=", 1)
        if role in explicit:
            raise BuilderError(f"duplicate artifact role: {role}")
        explicit[role] = _small_artifact(raw_path, role, output_root=out_root, namespace_root=ns_root)
    required_explicit = {"current_runtime_view", "relocated_v15_request", "engine_report"}
    missing = required_explicit.difference(explicit)
    if missing:
        raise BuilderError(f"terminal manifest needs explicit artifact roles: {sorted(missing)}")
    source_contract_binding = _small_artifact(contract_path, "source_contract", output_root=out_root, namespace_root=ns_root)
    identity = _source_identity(executor_path, contract_path)
    request_bindings = {
        "executor": {"path": str(executor_path), "physical_sha256": sha256_file(executor_path, max_bytes=MAX_JSON_BYTES, role="executor request")},
        "parent": {"path": str(parent_path), "physical_sha256": sha256_file(parent_path, max_bytes=MAX_JSON_BYTES, role="parent request")},
        "root_metadata_verification": {"path": str(preflight_path), "physical_sha256": sha256_file(preflight_path, max_bytes=MAX_JSON_BYTES, role="V50 preflight")},
    }
    pinned = _pinned_code_bindings(pinned_sources)
    # Derivation is based on the completed parent-v3 receipt and pinned source
    # code, not on an invented field in that historical receipt.
    static: dict[str, Any] = {
        "schema": STATIC_SCHEMA, "status": STATIC_STATUS, "phase": STATIC_PHASE,
        "static_content_verified": True, "verification_mode": "DERIVED_FROM_COMPLETED_PARENT_TERMINAL_RECORD",
        "instrumented_receipt": False, "derived_sidecar": True,
        "request": str(parent_path), "executor": str(executor_path),
        "request_file_sha256": request_bindings["parent"]["physical_sha256"],
        "executor_file_sha256": request_bindings["executor"]["physical_sha256"],
        "same_parent_ledger": True,
        "parent_attempt_id": report.get("parent", {}).get("attempt_id"),
        "charge_id": report.get("accounting", {}).get("charge_id") or report.get("charge", {}).get("id"),
        "completed_parent_report": {"path": str(report_path), "sha256": sha256_file(report_path, max_bytes=MAX_JSON_BYTES, role="parent report")},
        "preflight_basis": {"path": str(preflight_path), "sha256": request_bindings["root_metadata_verification"]["physical_sha256"],
                             "schema": "ds02.stage2.root.v50-metadata-preflight.v1"},
        "derivation": {
            "statement": "The completed parent-v3 execution covers metadata/stat preflight, same-parent reservation, and v34 child copy/hash/worker/evaluator. Parent-v3 calls verify_static_content=True after reservation; this sidecar derives that phase from the completed receipt and pinned source paths.",
            "parent_report_status": report.get("status"),
            "hard_wall_covers": report.get("execution", {}).get("hard_wall_covers", []),
            "original_instrumented_receipt_present": False,
            "payload_rehashed_by_this_builder": False,
        },
        "verified_source_hashes": {
            **{key: dict(value) for key, value in pinned.items()},
            "executor_request": request_bindings["executor"],
            "parent_request": request_bindings["parent"],
            "v50_preflight": request_bindings["root_metadata_verification"],
            "source_contract": source_contract_binding,
        },
        "qualification": dict(UNKNOWN),
    }
    static["sha256"] = canonical_sha(static)
    static_path = _write_new(static_output, static)
    artifacts = {
        "worker_report": _small_artifact(worker_path, "worker_report", output_root=out_root, namespace_root=ns_root),
        "raw_converter_report": products["converter"], "typed_hdf5": products["typed"],
        "v15_result": products["v15"], "v16_result": products["v16"],
        **explicit, "source_contract": source_contract_binding,
    }
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA, "status": "COMPLETED_DEVELOPMENT_UNKNOWN",
        "request_bindings": request_bindings,
        "source_identity": identity,
        "parent_attempt_id": report.get("parent", {}).get("attempt_id"),
        "charge_id": report.get("accounting", {}).get("charge_id") or report.get("charge", {}).get("id"),
        "terminal": {
            "parent_guard_completed": True, "reservation_closed": True, "charge_closed": True,
            "ledger_mutated": True, "payload_read_after_reservation": True,
            "model_invoked": False, "cfd_invoked": False,
            "derived_static_attestation": True, "instrumented_static_receipt": False,
        },
        "source_contract": {"path": str(contract_path), "sha256": source_contract_binding["sha256"]},
        "artifacts": artifacts,
        "parent_static_content_verification": {
            "path": str(static_path), "physical_sha256": sha256_file(static_path, max_bytes=MAX_JSON_BYTES, role="static attestation"),
            "status": STATIC_STATUS, "phase": STATIC_PHASE,
        },
        "limitations": [
            "The static-content result is a derived sidecar from the completed parent report, not an instrumented receipt written by the historical parent.",
            "Payload artifact SHA values are producer-declared and are not rehashed by this source-only builder.",
            "QI/QN/QE remain UNKNOWN; a fresh V10 semantic proof and evaluator guard are still required.",
        ],
        "qualification": dict(UNKNOWN),
    }
    manifest["sha256"] = canonical_sha(manifest)
    manifest_path = _write_new(manifest_output, manifest)
    return {"manifest": str(manifest_path), "manifest_sha256": manifest["sha256"],
            "static_attestation": str(static_path), "static_attestation_sha256": static["sha256"],
            "derived_sidecar": True, "payload_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    closure = sub.add_parser("build-runtime-closure")
    closure.add_argument("--executor-request", type=Path, required=True)
    closure.add_argument("--runtime-root", type=Path, required=True)
    closure.add_argument("--output", type=Path, required=True)
    closure.add_argument("--role-binding", action="append", default=[])
    closure.add_argument("--pinned-source", action="append", default=[])
    closure.add_argument("--abi-smoke", type=Path, required=True)
    terminal = sub.add_parser("build-terminal-inputs")
    for name in ("executor-request", "parent-request", "preflight", "parent-report", "worker-report",
                 "source-contract", "output-root", "namespace-root", "static-output", "manifest-output"):
        terminal.add_argument(f"--{name}", type=Path, required=True)
    terminal.add_argument("--pinned-source", action="append", default=[])
    terminal.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "build-runtime-closure":
            result = build_runtime_closure(
                executor_request=args.executor_request, runtime_root=args.runtime_root,
                output=args.output, role_bindings=args.role_binding,
                pinned_sources=args.pinned_source, abi_smoke=args.abi_smoke)
        else:
            result = build_terminal_inputs(
                executor_request=args.executor_request, parent_request=args.parent_request,
                preflight=args.preflight, parent_report=args.parent_report,
                worker_report=args.worker_report, source_contract=args.source_contract,
                output_root=args.output_root, namespace_root=args.namespace_root,
                static_output=args.static_output, manifest_output=args.manifest_output,
                pinned_sources=args.pinned_source, artifact_bindings=args.artifact)
    except (BuilderError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V50 source-only post-terminal builder: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
