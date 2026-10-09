#!/usr/bin/env python3
"""Build an evaluator-v4 request with an explicitly pinned external venv.

The consumed v1 adapter intentionally required every closure role to live under
the copied runtime root.  That rule is correct for scientific code and source
files, but it is too strong for the already pinned project interpreter: the
literal ``.../.venv/bin/python`` is a symlink to the system binary and its
NumPy/HDF5 ABI is supplied by the pinned venv environment.  Resolving that
argv[0] to ``/usr/bin/python3.10`` silently selects the wrong ABI.

This additive adapter keeps v1's request and source checks, while adding one
narrow exception for that external interpreter.  The literal path remains the
actual command argv[0]; its resolved target is provenance only.  A small ABI
smoke receipt is mandatory.  No scientific/source path may use this exception,
and standalone-environment or qualification credit remains UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
LEGACY_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_evaluator_v4_adapter_v1.py"
ABI_SMOKE_SCHEMA = "ds02.stage2.f2-pinned-venv-abi-smoke.v1"
ABI_SMOKE_STATUS = "PASS_LITERAL_VENV_ABI_IMPORT"
INTERPRETER_ROLE = "python_executable"
ABI_ROLE = "interpreter_abi_smoke"
EXTERNAL_MODE = "EXTERNAL_PINNED_VENV_INTERPRETER"
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_CODE_BYTES = 64 * 1024 * 1024


class EvaluatorAdapterV2Error(RuntimeError):
    """A malformed closure or fresh evaluator binding."""


def _load_legacy() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ds_data02_bound_f2_evaluator_v4_adapter_v1_for_v2", LEGACY_SCRIPT)
    if spec is None or spec.loader is None:
        raise EvaluatorAdapterV2Error(f"cannot load consumed v1 adapter: {LEGACY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY = _load_legacy()

# Re-export the request constants used by callers and tests.  They are values,
# not a second contract; v1 remains the implementation for all other checks.
REQUEST_SCHEMA = LEGACY.REQUEST_SCHEMA
CLOSURE_SCHEMA = LEGACY.CLOSURE_SCHEMA
CLOSURE_STATUS = LEGACY.CLOSURE_STATUS
UNKNOWN = LEGACY.UNKNOWN
REQUIRED_CLOSURE_ROLES = set(LEGACY.REQUIRED_CLOSURE_ROLES) | {ABI_ROLE}


def canonical_sha(value: Mapping[str, Any]) -> str:
    return LEGACY.canonical_sha(value)


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise EvaluatorAdapterV2Error(f"{role} must be a lowercase SHA-256")
    return value


def _file(path: Any, role: str, *, allow_symlink: bool = False,
          max_bytes: int = MAX_METADATA_BYTES) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).startswith("/"):
        raise EvaluatorAdapterV2Error(f"{role} must be an absolute path")
    target = Path(path).expanduser()
    if not target.is_file() or (target.is_symlink() and not allow_symlink):
        raise EvaluatorAdapterV2Error(f"{role} is not an allowed regular file: {target}")
    if target.stat().st_size > max_bytes:
        raise EvaluatorAdapterV2Error(f"{role} exceeds the bounded metadata limit")
    return target


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluatorAdapterV2Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluatorAdapterV2Error(f"{role} must be an object")
    return target, value


def _sha_file(path: Path, *, max_bytes: int = MAX_CODE_BYTES) -> str:
    if path.stat().st_size > max_bytes:
        raise EvaluatorAdapterV2Error(f"refusing oversized closure file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path, role: str) -> dict[str, int]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise EvaluatorAdapterV2Error(f"{role} target is not a regular file")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _declared_noninterpreter(raw: Mapping[str, Any], role: str,
                             root: Path) -> dict[str, Any]:
    """Delegate normal roles to the consumed strict binding validator."""
    try:
        return LEGACY._declared_binding(raw, f"closure.{role}", under=root)
    except Exception as error:  # normalize legacy's public RuntimeError type
        raise EvaluatorAdapterV2Error(str(error)) from error


def _external_interpreter(raw: Mapping[str, Any], root: Path) -> dict[str, Any]:
    path = _file(raw.get("path"), "closure.python_executable", allow_symlink=True,
                 max_bytes=MAX_CODE_BYTES)
    if not path.is_symlink() or path.name != "python" or ".venv" not in str(path):
        raise EvaluatorAdapterV2Error(
            "python_executable must be the literal pinned .venv/bin/python symlink")
    if raw.get("external_pinned") is not True or raw.get("interpreter_mode") != EXTERNAL_MODE:
        raise EvaluatorAdapterV2Error("external interpreter exception is not explicitly pinned")
    if raw.get("literal_invocation_path") != str(path):
        raise EvaluatorAdapterV2Error("literal interpreter argv0 was changed")
    if raw.get("original_path_fallback") != "PINNED_ENV_ONLY":
        raise EvaluatorAdapterV2Error("interpreter binding permits unbounded original fallback")
    resolved = path.resolve()
    if not resolved.is_file():
        raise EvaluatorAdapterV2Error("pinned interpreter symlink target is missing")
    if raw.get("resolved_path") != str(resolved):
        raise EvaluatorAdapterV2Error("interpreter resolved-path provenance differs")
    # The interpreter is the sole explicit external exception.  A runtime-root
    # value is retained as provenance but does not turn the venv into a copied
    # scientific/source fallback.
    expected_sha = _sha(raw.get("sha256"), "closure.python_executable.sha256")
    observed_sha = _sha_file(path)
    if observed_sha != expected_sha:
        raise EvaluatorAdapterV2Error("literal interpreter SHA differs")
    actual = _stat(path, "closure.python_executable")
    raw_bytes = raw.get("bytes")
    if isinstance(raw_bytes, bool) or not isinstance(raw_bytes, int) or raw_bytes != actual["bytes"]:
        raise EvaluatorAdapterV2Error("literal interpreter bytes differ")
    declared_stat = raw.get("stat")
    if isinstance(declared_stat, Mapping):
        for key, value in actual.items():
            if key in declared_stat and declared_stat[key] != value:
                raise EvaluatorAdapterV2Error(f"literal interpreter stat.{key} differs")
    return {
        "path": str(path), "sha256": observed_sha, "bytes": actual["bytes"],
        "stat": actual, "content_verification_phase": "AFTER_PARENT_RESERVATION",
        "external_pinned": True, "interpreter_mode": EXTERNAL_MODE,
        "literal_invocation_path": str(path), "resolved_path": str(resolved),
        "resolved_path_provenance_only": True,
        "original_path_fallback": "PINNED_ENV_ONLY",
        "runtime_root": str(root),
    }


def _validate_abi_smoke(raw: Mapping[str, Any], interpreter: Mapping[str, Any],
                        root: Path) -> dict[str, Any]:
    path = _file(raw.get("path"), "closure.interpreter_abi_smoke")
    if not _under(path, root):
        raise EvaluatorAdapterV2Error("ABI smoke must live under copied runtime root")
    value = _json(path, "pinned interpreter ABI smoke")[1]
    if value.get("schema") != ABI_SMOKE_SCHEMA or value.get("status") != ABI_SMOKE_STATUS:
        raise EvaluatorAdapterV2Error("ABI smoke is not a PASS_LITERAL_VENV_ABI_IMPORT receipt")
    if value.get("literal_argv0") != interpreter["literal_invocation_path"]:
        raise EvaluatorAdapterV2Error("ABI smoke argv0 is not the literal pinned venv path")
    expected = _sha(raw.get("sha256"), "closure.interpreter_abi_smoke.sha256")
    observed = _sha_file(path)
    if observed != expected:
        raise EvaluatorAdapterV2Error("ABI smoke SHA differs")
    actual = _stat(path, "closure.interpreter_abi_smoke")
    if raw.get("bytes") != actual["bytes"]:
        raise EvaluatorAdapterV2Error("ABI smoke bytes differ")
    return {"path": str(path), "sha256": observed, "bytes": actual["bytes"],
            "stat": actual, "content_verification_phase": "AFTER_PARENT_RESERVATION"}


def _validate_closure_external(path: Path, value: Mapping[str, Any]) -> tuple[Path, list[dict[str, Any]]]:
    if value.get("schema") != CLOSURE_SCHEMA or value.get("status") != CLOSURE_STATUS:
        raise EvaluatorAdapterV2Error("post-terminal evaluator closure schema/status differs")
    if value.get("sha256") != canonical_sha(value):
        raise EvaluatorAdapterV2Error("post-terminal closure canonical SHA differs")
    root_value = value.get("runtime_root")
    if not isinstance(root_value, str) or not root_value.startswith("/"):
        raise EvaluatorAdapterV2Error("post-terminal runtime_root is missing")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise EvaluatorAdapterV2Error(f"post-terminal runtime_root is missing: {root}")
    if value.get("original_path_fallback") != "FORBIDDEN":
        raise EvaluatorAdapterV2Error("post-terminal closure permits original fallback")
    rows = value.get("roles")
    if not isinstance(rows, list) or not rows:
        raise EvaluatorAdapterV2Error("post-terminal closure roles are missing")
    raw_roles: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("role"), str):
            raise EvaluatorAdapterV2Error(f"closure role {index} is malformed")
        role = str(raw["role"])
        if role in raw_roles:
            raise EvaluatorAdapterV2Error(f"duplicate closure role: {role}")
        raw_roles[role] = raw
    missing = REQUIRED_CLOSURE_ROLES.difference(raw_roles)
    if missing:
        raise EvaluatorAdapterV2Error(f"post-terminal closure misses roles: {sorted(missing)}")
    interpreter = _external_interpreter(raw_roles[INTERPRETER_ROLE], root)
    output: list[dict[str, Any]] = []
    for role in sorted(raw_roles):
        if role == INTERPRETER_ROLE:
            output.append({"role": role, **interpreter})
        elif role == ABI_ROLE:
            output.append({"role": role, **_validate_abi_smoke(raw_roles[role], interpreter, root)})
        else:
            output.append({"role": role, **_declared_noninterpreter(raw_roles[role], role, root)})
    return root, output


def _build_with_legacy(*, descriptor: Path | str | None,
                       fresh_v10_request: Path | str,
                       terminal_manifest: Path | str, runtime_closure: Path | str,
                       output: Path | str, v50_seal: Path | str | None,
                       fresh_proof: Path | str | None) -> dict[str, Any]:
    """Run v1's complete descriptor/seal checks with only closure validation replaced."""
    old_validator = LEGACY._validate_closure
    LEGACY._validate_closure = _validate_closure_external
    try:
        return LEGACY.build_request(
            descriptor=descriptor, fresh_v10_request=fresh_v10_request,
            terminal_manifest=terminal_manifest, runtime_closure=runtime_closure,
            output=output, v50_seal=v50_seal, fresh_proof=fresh_proof)
    except Exception as error:
        raise EvaluatorAdapterV2Error(str(error)) from error
    finally:
        LEGACY._validate_closure = old_validator


def build_request(*, descriptor: Path | str | None = None,
                  fresh_v10_request: Path | str,
                  terminal_manifest: Path | str, runtime_closure: Path | str,
                  output: Path | str, v50_seal: Path | str | None = None,
                  fresh_proof: Path | str | None = None) -> dict[str, Any]:
    if (descriptor is None) == (v50_seal is None):
        raise EvaluatorAdapterV2Error("supply exactly one of --descriptor or --v50-seal")
    result = _build_with_legacy(
        descriptor=descriptor, fresh_v10_request=fresh_v10_request,
        terminal_manifest=terminal_manifest, runtime_closure=runtime_closure,
        output=output, v50_seal=v50_seal, fresh_proof=fresh_proof)
    output_path = Path(result["request"])
    try:
        built = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluatorAdapterV2Error(f"cannot reopen v1 adapter output: {error}") from error
    if not isinstance(built, dict):
        raise EvaluatorAdapterV2Error("v1 adapter output is not an object")
    closure_path, closure = _json(runtime_closure, "post-terminal evaluator closure")
    closure_root, rows = _validate_closure_external(closure_path, closure)
    interpreter = next(row for row in rows if row["role"] == INTERPRETER_ROLE)
    abi = next(row for row in rows if row["role"] == ABI_ROLE)
    command = built.get("execution", {}).get("command") if isinstance(built.get("execution"), Mapping) else None
    if not isinstance(command, list) or not command or command[0] != interpreter["literal_invocation_path"]:
        raise EvaluatorAdapterV2Error("legacy adapter did not preserve literal interpreter argv0")
    built["postterminal_runtime_closure"] = {
        **dict(built.get("postterminal_runtime_closure", {})),
        "path": str(closure_path), "sha256": _sha(closure.get("sha256"), "closure.sha256"),
        "runtime_root": str(closure_root), "roles": rows,
    }
    built["adapter"] = {
        **dict(built.get("adapter", {})),
        "schema": "ds02.stage2.f2-v50-descriptor-to-evaluator-v4-adapter.v2",
        "external_interpreter_exception": True,
        "relocated_v15_request_used": True,
        "result_content_read_during_build": False,
    }
    built["interpreter_contract"] = {
        "mode": EXTERNAL_MODE,
        "literal_argv0": interpreter["literal_invocation_path"],
        "resolved_path_provenance_only": interpreter["resolved_path"],
        "abi_smoke": {"path": abi["path"], "sha256": abi["sha256"]},
        "standalone_environment_credit": "UNKNOWN; explicit pinned environment binding only",
        "scientific_source_fallback": "FORBIDDEN",
    }
    limitations = list(built.get("limitations", []))
    limitations.append("The external interpreter is explicitly pinned; this is not standalone-environment portability credit.")
    built["limitations"] = limitations
    built["sha256"] = canonical_sha(built)
    with output_path.open("w", encoding="utf-8") as stream:
        json.dump(built, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return {**result, "request_sha256": built["sha256"],
            "interpreter_mode": EXTERNAL_MODE,
            "literal_argv0": interpreter["literal_invocation_path"],
            "result_content_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    descriptor_group = parser.add_mutually_exclusive_group(required=True)
    descriptor_group.add_argument("--descriptor", type=Path)
    descriptor_group.add_argument("--v50-seal", type=Path)
    parser.add_argument("--fresh-proof", type=Path)
    parser.add_argument("--fresh-v10-request", type=Path, required=True)
    parser.add_argument("--terminal-manifest", type=Path, required=True)
    parser.add_argument("--runtime-closure", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.v50_seal is not None and args.fresh_proof is None:
            parser.error("--fresh-proof is required with --v50-seal")
        result = build_request(
            descriptor=args.descriptor, v50_seal=args.v50_seal,
            fresh_proof=args.fresh_proof, fresh_v10_request=args.fresh_v10_request,
            terminal_manifest=args.terminal_manifest,
            runtime_closure=args.runtime_closure, output=args.output)
    except (EvaluatorAdapterV2Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 evaluator-v4 external-interpreter adapter: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
