#!/usr/bin/env python3
"""Build a fresh V8 JSON proof request from frozen source metadata.

This builder is intentionally a post-result metadata step.  It derives the
V8 ``expected`` contract from a canonical, frozen source-contract JSON and
binds the newly produced V16 result by its exact path, stat and SHA.  It never
opens H5/BI4 files and never runs the V16 operator, converter, evaluator or a
model.  The output remains DEVELOPMENT with QI/QN/QE UNKNOWN.

The Python invocation path is preserved literally.  Its resolved target is
recorded only as provenance, preventing a symlinked ``.venv/bin/python`` from
being silently replaced by the ABI-incompatible system interpreter.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V8_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
BUILDER_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-request-builder.v1"
SOURCE_SCHEMA = "ds02.stage2.f2-fresh-v16-source-contract.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class V16RequestBuilderError(RuntimeError):
    """Raised when a fresh-result proof binding cannot be closed."""


def _load_v8() -> Any:
    if not V8_SCRIPT.is_file():
        raise V16RequestBuilderError(f"bound V8 consumer is missing: {V8_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ds02_stage2_f2_v8_bound", V8_SCRIPT)
    if spec is None or spec.loader is None:
        raise V16RequestBuilderError("cannot import bound V8 consumer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V8 = _load_v8()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def canonical_sha(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=_json_default).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V16RequestBuilderError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise V16RequestBuilderError(f"JSON object required: {target}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise V16RequestBuilderError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=_json_default)
        stream.write("\n")
    return target


def _path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise V16RequestBuilderError(f"{name} must be an absolute path")
    return Path(value).expanduser()


def _resolved(value: Any, name: str) -> Path:
    return _path(value, name).resolve()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise V16RequestBuilderError(f"{name} must be a lowercase SHA-256")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V16RequestBuilderError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise V16RequestBuilderError(f"{name} must be finite")
    return result


def _nonnegative(value: Any, name: str) -> float:
    result = _finite(value, name)
    if result < 0:
        raise V16RequestBuilderError(f"{name} must be nonnegative")
    return result


def _stat(path: Path, name: str) -> dict[str, Any]:
    try:
        info = path.stat()
    except OSError as error:
        raise V16RequestBuilderError(f"{name} is unavailable: {path}: {error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise V16RequestBuilderError(f"{name} is not a regular file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode)),
            "resolved_path": str(path.resolve())}


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _unknown(value: Any, name: str) -> None:
    if value != UNKNOWN:
        raise V16RequestBuilderError(f"{name} must keep QI/QN/QE UNKNOWN")


def _validate_source_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise V16RequestBuilderError("source contract source_binding is required")
    source = dict(value)
    files = source.get("source_files")
    if not isinstance(files, Mapping) or not files:
        raise V16RequestBuilderError("source contract source_files is empty")
    for role, digest in files.items():
        _sha(digest, f"source_binding.source_files.{role}")
    for key, item in source.items():
        if key.endswith("sha256") and key != "source_files":
            _sha(item, f"source_binding.{key}")
    if source.get("binding_status") not in {"EXACT_CURRENT_SOURCE_BOUND", "FROZEN_SOURCE_METADATA", "MANUFACTURED_FIXTURE"}:
        raise V16RequestBuilderError("source contract binding_status is not recognized")
    return source


def _validate_expected(expected: Any) -> dict[str, Any]:
    if not isinstance(expected, Mapping):
        raise V16RequestBuilderError("source contract expected object is required")
    value = json.loads(json.dumps(expected, allow_nan=False))
    value["source_binding"] = _validate_source_binding(value.get("source_binding"))
    identity = value.get("case_identity")
    if not isinstance(identity, Mapping) or not identity:
        raise V16RequestBuilderError("expected.case_identity is required")
    cohort = value.get("cohort")
    if not isinstance(cohort, Mapping):
        raise V16RequestBuilderError("expected.cohort is required")
    count = cohort.get("selected_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise V16RequestBuilderError("expected.cohort.selected_count must be a positive integer")
    if cohort.get("identity_key") != "(Zone,Idp)":
        raise V16RequestBuilderError("expected.cohort.identity_key must be (Zone,Idp)")
    _sha(cohort.get("identity_sha256"), "expected.cohort.identity_sha256")
    mass = value.get("initial_mass_denominator")
    if not isinstance(mass, Mapping):
        raise V16RequestBuilderError("expected.initial_mass_denominator is required")
    for key in ("denominator_kg", "initial_missing_mass_kg", "later_missing_mass_kg"):
        _nonnegative(mass.get(key), f"expected.initial_mass_denominator.{key}")
    if isinstance(mass.get("later_missing_unique_count"), bool) or not isinstance(mass.get("later_missing_unique_count"), int) or mass["later_missing_unique_count"] < 0:
        raise V16RequestBuilderError("expected later_missing_unique_count must be a nonnegative integer")
    times = value.get("time")
    if not isinstance(times, Mapping):
        raise V16RequestBuilderError("expected.time is required")
    frame_count = times.get("frame_count")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count <= 0:
        raise V16RequestBuilderError("expected.time.frame_count must be a positive integer")
    first, last = _nonnegative(times.get("first_s"), "expected.time.first_s"), _nonnegative(times.get("last_s"), "expected.time.last_s")
    if last < first:
        raise V16RequestBuilderError("expected.time is reversed")
    _nonnegative(times.get("tolerance_s"), "expected.time.tolerance_s")
    if times.get("observer_profile_sha256") is not None:
        _sha(times["observer_profile_sha256"], "expected.time.observer_profile_sha256")
    fields = value.get("observer_fields", [])
    if not isinstance(fields, list) or any(not isinstance(item, str) for item in fields):
        raise V16RequestBuilderError("expected.observer_fields must be a list of strings")
    events = value.get("events")
    if not isinstance(events, Mapping) or events.get("require_unknown_recross") is not True or events.get("require_total_net_interval") is not True or events.get("require_receiver_labels") is not True:
        raise V16RequestBuilderError("expected.events must retain unknown recross/total net/receiver contracts")
    return value


def _source_contract(path: Path | str) -> tuple[Path, dict[str, Any]]:
    contract_path = Path(path).expanduser().resolve()
    contract = _load_json(contract_path)
    if contract.get("schema") != SOURCE_SCHEMA:
        raise V16RequestBuilderError("source contract schema differs")
    if contract.get("sha256") != canonical_sha(contract):
        raise V16RequestBuilderError("source contract canonical SHA differs")
    if contract.get("role") != "DEVELOPMENT":
        raise V16RequestBuilderError("source contract must remain DEVELOPMENT")
    _unknown(contract.get("quality", contract.get("qualification")), "source contract quality")
    contract["expected"] = _validate_expected(contract.get("expected"))
    roots = contract.get("original_roots")
    if not isinstance(roots, list) or not roots or any(not isinstance(item, str) or not Path(item).is_absolute() for item in roots):
        raise V16RequestBuilderError("source contract original_roots must be absolute paths")
    return contract_path, contract


def _result_binding(path: Path | str, target: Path, output: Path,
                    original_roots: Sequence[Path], max_bytes: int) -> dict[str, Any]:
    literal = _path(str(path), "result.path")
    if literal.is_symlink():
        raise V16RequestBuilderError("fresh result must not be a symlink")
    result = literal.resolve()
    if not result.is_file():
        raise V16RequestBuilderError("fresh result must exist before building a V8 request")
    if any(_under(result, root) for root in original_roots):
        raise V16RequestBuilderError("fresh result is under an original source root")
    if not (_under(result, target) or _under(result, output)):
        raise V16RequestBuilderError("fresh result must be under relocated target/output roots")
    info = _stat(result, "fresh V16 result")
    if info["bytes"] <= 0 or info["bytes"] > max_bytes:
        raise V16RequestBuilderError("fresh V16 result exceeds the request byte bound")
    return {"path": str(literal), "sha256": sha256_file(result), "bytes": info["bytes"],
            "stat": {key: info[key] for key in ("bytes", "mtime_ns", "mode_bits")},
            "content_sha_verified": False,
            "content_scope": "JSON result only; no H5/BI4/raw payload opened by builder"}


def build_request(*, source_contract: Path | str, result: Path | str,
                  target_root: Path | str, output_root: Path | str,
                  output: Path | str, parent_guard_record: Path | str | None = None,
                  trace_audit_request: Path | str | None = None,
                  python_executable: Path | str | None = None,
                  max_wall_seconds: float = 900.0,
                  max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    if not math.isfinite(max_wall_seconds) or max_wall_seconds <= 0:
        raise V16RequestBuilderError("max_wall_seconds must be finite and positive")
    if isinstance(max_result_bytes, bool) or not isinstance(max_result_bytes, int) or max_result_bytes <= 0:
        raise V16RequestBuilderError("max_result_bytes must be a positive integer")
    contract_path, contract = _source_contract(source_contract)
    target = _resolved(str(target_root), "target_root")
    relocated_output = _resolved(str(output_root), "output_root")
    if target == relocated_output:
        raise V16RequestBuilderError("target_root and output_root must be distinct")
    original_roots = [_resolved(item, "original_root") for item in contract["original_roots"]]
    if any(root == target or root == relocated_output for root in original_roots):
        raise V16RequestBuilderError("relocated roots overlap an original root")
    result_binding = _result_binding(result, target, relocated_output, original_roots, max_result_bytes)

    python_literal = _path(str(python_executable), "python_executable") if python_executable is not None else None
    python_binding: dict[str, Any] | None = None
    if python_literal is not None:
        info = _stat(python_literal, "python executable")
        if not info["mode_bits"] & 0o111:
            raise V16RequestBuilderError("python executable is not executable")
        python_binding = {
            "literal_invocation_path": str(python_literal),
            "resolved_provenance_path": str(python_literal.resolve()),
            "bytes": info["bytes"], "mtime_ns": info["mtime_ns"],
            "mode_bits": info["mode_bits"], "preserve_literal_argv0": True,
        }

    guard_binding = None
    if parent_guard_record is not None:
        guard_path = _path(str(parent_guard_record), "parent_guard_record.path")
        if not guard_path.is_file() or not (_under(guard_path.resolve(), target) or _under(guard_path.resolve(), relocated_output)):
            raise V16RequestBuilderError("parent guard record must be a relocated JSON file")
        guard_binding = {"path": str(guard_path), "sha256": sha256_file(guard_path)}

    audit_binding = {"status": "PENDING_PARENT_TRACE_AUDIT_REQUEST"}
    if trace_audit_request is not None:
        audit_path = _path(str(trace_audit_request), "trace_audit_request.path")
        if not audit_path.is_file():
            raise V16RequestBuilderError("trace audit request is missing")
        audit_binding = {"path": str(audit_path), "sha256": sha256_file(audit_path),
                         "status": "BOUND_METADATA_ONLY"}

    value: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "role": "DEVELOPMENT",
        "status": "READY_FOR_PARENT_GUARD", "model_invoked": False,
        "cfd_invoked": False, "ledger_mutated": False, "quality": dict(UNKNOWN),
        "result": result_binding,
        "relocation": {"target_root": str(target), "output_root": str(relocated_output),
                        "original_roots": [str(root) for root in original_roots]},
        "expected": contract["expected"],
        "execution": {
            "max_wall_seconds": float(max_wall_seconds), "max_result_bytes": max_result_bytes,
            "read_hdf5_or_bi4": False, "raw_opened": False,
            "python_executable": python_binding["literal_invocation_path"] if python_binding else None,
            "python_invocation_path": python_binding["literal_invocation_path"] if python_binding else None,
            "python_binding": python_binding,
            "isolated_python": "-I", "original_path_fallback": "FORBIDDEN",
        },
        "source_metadata": {"path": str(contract_path), "sha256": sha256_file(contract_path),
                            "schema": contract["schema"]},
        "v8_consumer": {"path": str(V8_SCRIPT), "sha256": sha256_file(V8_SCRIPT),
                        "schema": REQUEST_SCHEMA},
        "trace_audit": audit_binding,
        "parent_guard_record": guard_binding,
        "limitations": [
            "The builder binds a fresh JSON result only; it never validates the native H5/BI4 reconstruction.",
            "Trace/process ancestry and private readonly access require the separate parent OS audit request.",
            "All QI/QN/QE remain UNKNOWN; this request cannot grant qualification.",
        ],
    }
    value["sha256"] = V8.canonical_sha(value)
    output_path = _write_new(output, value)
    return {"schema": BUILDER_SCHEMA, "status": "READY_FOR_PARENT_V8_PROOF",
            "request_path": str(output_path), "request_sha256": value["sha256"],
            "result_sha256": result_binding["sha256"], "result_bytes": result_binding["bytes"],
            "hdf5_or_bi4_content_read": False, "model_invoked": False,
            "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build-request", nargs="?")
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent-guard-record", type=Path)
    parser.add_argument("--trace-audit-request", type=Path)
    parser.add_argument("--python-executable", type=Path)
    parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    parser.add_argument("--max-result-bytes", type=int, default=100_000_000)
    args = parser.parse_args(argv)
    if args.build_request not in {None, "build-request"}:
        parser.error("the only command is build-request")
    try:
        value = build_request(source_contract=args.source_contract, result=args.result,
                              target_root=args.target_root, output_root=args.output_root,
                              output=args.output, parent_guard_record=args.parent_guard_record,
                              trace_audit_request=args.trace_audit_request,
                              python_executable=args.python_executable,
                              max_wall_seconds=args.max_wall_seconds,
                              max_result_bytes=args.max_result_bytes)
    except (V16RequestBuilderError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof request builder: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
