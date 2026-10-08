#!/usr/bin/env python3
"""Build a fresh V16 proof request from a small producer report.

This is an additive successor to the v1/v2 builders.  The producer report is
the only result metadata read before the parent reservation: it binds the
result SHA and the result path, while this builder records a stat-only byte
count.  The proof consumer is responsible for reading and hashing the large
V16 JSON result after the parent guard has reserved the slot.  Cohort,
identity, initial-mass, time and censor contracts still come only from the
frozen V15 request and scientific scan via the v2 derivation code.

No HDF5, BI4, raw trajectory, or result-content bytes are opened here.  The
result report and derived source contract are small JSON metadata inputs;
qualification remains UNKNOWN.
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
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_request_builder_v1.py"
V2_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_request_builder_v2.py"
REPORT_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
BUILDER_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-request-builder.v3"
SOURCE_SCHEMA = "ds02.stage2.f2-fresh-v16-source-contract.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024


class V16ForwardRequestError(RuntimeError):
    """The fresh producer report or derived proof binding is unsafe."""


def _load_module(path: Path, name: str) -> Any:
    if not path.is_file():
        raise V16ForwardRequestError(f"bound module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise V16ForwardRequestError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_module(V1_SCRIPT, "ds02_stage2_f2_v16_builder_v1_bound_v3")
V2 = _load_module(V2_SCRIPT, "ds02_stage2_f2_v16_builder_v2_bound_v3")
V8 = V1.V8


def canonical_sha(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise V16ForwardRequestError(f"{name} must be an absolute path")
    return Path(value).expanduser()


def _resolved(value: Any, name: str) -> Path:
    return _path(value, name).resolve()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise V16ForwardRequestError(f"{name} must be a lowercase SHA-256")
    return value


def _load_small_json(path: Path | str, name: str) -> tuple[Path, dict[str, Any]]:
    target = _resolved(str(path), name)
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise V16ForwardRequestError(f"{name} is not a regular file: {target}")
    if int(info.st_size) > MAX_METADATA_BYTES:
        raise V16ForwardRequestError(f"{name} exceeds metadata-only byte bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V16ForwardRequestError(f"cannot read {name}: {error}") from error
    if not isinstance(value, dict):
        raise V16ForwardRequestError(f"{name} must contain a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _resolved(str(path), "output")
    if target.exists():
        raise V16ForwardRequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _stat(path: Path, name: str) -> dict[str, Any]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise V16ForwardRequestError(f"{name} is not a regular file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode)), "resolved_path": str(path.resolve())}


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _unknown(value: Any, name: str) -> None:
    if value != UNKNOWN:
        raise V16ForwardRequestError(f"{name} must keep QI/QN/QE UNKNOWN")


def _load_producer_report(path: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any], Path]:
    report_path, report = _load_small_json(path, "typed-only producer report")
    if report.get("schema") != REPORT_SCHEMA:
        raise V16ForwardRequestError(f"producer report schema differs: {report.get('schema')!r}")
    if report.get("sha256") != canonical_sha(report):
        raise V16ForwardRequestError("producer report canonical SHA differs")
    if not str(report.get("status", "")).startswith("COMPLETE_TYPED_ONLY_LABELS_"):
        raise V16ForwardRequestError("producer report is not a completed typed-only report")
    if report.get("model_invoked") is not False or report.get("cfd_invoked") is not False:
        raise V16ForwardRequestError("producer report model/CFD flags are not closed")
    _unknown(report.get("qualification"), "producer report qualification")
    labels = report.get("labels")
    if not isinstance(labels, Mapping) or not isinstance(labels.get("v16"), Mapping):
        raise V16ForwardRequestError("producer report labels.v16 binding is missing")
    binding = dict(labels["v16"])
    result_path = _path(binding.get("path"), "producer report labels.v16.path")
    if result_path.is_symlink() or not result_path.is_file():
        raise V16ForwardRequestError("producer V16 result must be a regular non-symlink file")
    result_sha = _sha(binding.get("sha256"), "producer report labels.v16.sha256")
    info = _stat(result_path, "producer V16 result")
    if info["bytes"] <= 0:
        raise V16ForwardRequestError("producer V16 result is empty")
    binding["path"] = str(result_path)
    binding["sha256"] = result_sha
    binding["bytes"] = info["bytes"]
    binding["stat"] = {key: info[key] for key in ("bytes", "mtime_ns", "mode_bits")}
    binding["content_sha_verified"] = False
    binding["content_verification_phase"] = "PARENT_AFTER_RESERVATION"
    return report_path, report, binding, result_path


def _python_binding(path: Path | str) -> dict[str, Any]:
    literal = _path(str(path), "python_executable")
    info = _stat(literal, "python executable")
    if not info["mode_bits"] & 0o111:
        raise V16ForwardRequestError("python executable is not executable")
    return {"literal_invocation_path": str(literal),
            "resolved_provenance_path": str(literal.resolve()),
            "bytes": info["bytes"], "mtime_ns": info["mtime_ns"],
            "mode_bits": info["mode_bits"], "preserve_literal_argv0": True}


def _build_v8_request(*, source_contract: Path, producer_report: Path,
                      result_binding: Mapping[str, Any], target: Path, output_root: Path,
                      output: Path, parent_guard_record: Path | None,
                      trace_audit_request: Path | None, python_executable: Path | None,
                      max_wall_seconds: float, max_result_bytes: int) -> dict[str, Any]:
    contract_path, contract = V1._source_contract(source_contract)
    original_roots = [_resolved(item, "original_root") for item in contract["original_roots"]]
    result_path = _resolved(result_binding["path"], "producer V16 result")
    if any(_under(result_path, root) for root in original_roots):
        raise V16ForwardRequestError("producer V16 result is under an original source root")
    if not (_under(result_path, target) or _under(result_path, output_root)):
        raise V16ForwardRequestError("producer V16 result must be under relocated target/output roots")
    if target == output_root or any(root == target or root == output_root for root in original_roots):
        raise V16ForwardRequestError("relocated roots overlap")
    guard_binding = None
    if parent_guard_record is not None:
        guard = _path(str(parent_guard_record), "parent_guard_record.path")
        if not guard.is_file() or not (_under(guard.resolve(), target) or _under(guard.resolve(), output_root)):
            raise V16ForwardRequestError("parent guard record must be a relocated JSON file")
        guard_binding = {"path": str(guard), "sha256": sha256_file(guard)}
    audit_binding: dict[str, Any] = {"status": "PENDING_PARENT_TRACE_AUDIT_REQUEST"}
    if trace_audit_request is not None:
        audit = _path(str(trace_audit_request), "trace_audit_request.path")
        if not audit.is_file():
            raise V16ForwardRequestError("trace audit request is missing")
        audit_binding = {"path": str(audit), "sha256": sha256_file(audit), "status": "BOUND_METADATA_ONLY"}
    python_binding = _python_binding(python_executable) if python_executable is not None else None
    value: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "role": "DEVELOPMENT", "status": "READY_FOR_PARENT_GUARD",
        "model_invoked": False, "cfd_invoked": False, "ledger_mutated": False,
        "quality": dict(UNKNOWN), "result": dict(result_binding),
        "producer_report": {"path": str(producer_report), "sha256": sha256_file(producer_report),
                             "schema": REPORT_SCHEMA, "content_read": True},
        "relocation": {"target_root": str(target), "output_root": str(output_root),
                        "original_roots": [str(root) for root in original_roots]},
        "expected": contract["expected"],
        "execution": {"max_wall_seconds": float(max_wall_seconds), "max_result_bytes": max_result_bytes,
                       "read_hdf5_or_bi4": False, "raw_opened": False,
                       "python_executable": python_binding["literal_invocation_path"] if python_binding else None,
                       "python_invocation_path": python_binding["literal_invocation_path"] if python_binding else None,
                       "python_binding": python_binding, "isolated_python": "-I",
                       "original_path_fallback": "FORBIDDEN",
                       "result_content_verification": "after_parent_reservation"},
        "source_metadata": {"path": str(contract_path), "sha256": sha256_file(contract_path),
                            "schema": contract["schema"]},
        "v8_consumer": {"path": str(V1.V8_SCRIPT), "sha256": sha256_file(V1.V8_SCRIPT),
                         "schema": REQUEST_SCHEMA},
        "trace_audit": audit_binding, "parent_guard_record": guard_binding,
        "limitations": [
            "The producer report supplies the expected V16 SHA; the builder does not read result content.",
            "The parent proof consumer must hash and validate the result after reservation.",
            "No HDF5/BI4/raw payload was opened and all QI/QN/QE remain UNKNOWN.",
        ],
    }
    value["sha256"] = V8.canonical_sha(value)
    path = _write_new(output, value)
    return {"schema": BUILDER_SCHEMA, "status": "READY_FOR_PARENT_V8_PROOF",
            "request_path": str(path), "request_sha256": value["sha256"],
            "producer_report_sha256": sha256_file(producer_report),
            "result_sha256": result_binding["sha256"], "result_bytes": result_binding["bytes"],
            "result_content_read": False, "hdf5_or_bi4_content_read": False,
            "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN)}


def derive_and_build(*, v15_request: Path | str, scan_sidecar: Path | str,
                     source_contract_output: Path | str, producer_report: Path | str,
                     target_root: Path | str, output_root: Path | str, output: Path | str,
                     original_roots: Sequence[Path | str], parent_guard_record: Path | str | None = None,
                     trace_audit_request: Path | str | None = None,
                     python_executable: Path | str | None = None,
                     max_wall_seconds: float = 900.0, max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    if not math.isfinite(max_wall_seconds) or max_wall_seconds <= 0:
        raise V16ForwardRequestError("max_wall_seconds must be finite and positive")
    if isinstance(max_result_bytes, bool) or not isinstance(max_result_bytes, int) or max_result_bytes <= 0:
        raise V16ForwardRequestError("max_result_bytes must be a positive integer")
    report_path, _report, result_binding, _result_path = _load_producer_report(producer_report)
    derived = V2.derive_source_contract(v15_request=v15_request, scan_sidecar=scan_sidecar,
                                         source_contract_output=source_contract_output,
                                         original_roots=original_roots)
    target = _resolved(str(target_root), "target_root")
    output_root_path = _resolved(str(output_root), "output_root")
    built = _build_v8_request(source_contract=Path(derived["source_contract"]), producer_report=report_path,
                              result_binding=result_binding, target=target, output_root=output_root_path,
                              output=_resolved(str(output), "output"),
                              parent_guard_record=_path(str(parent_guard_record), "parent_guard_record") if parent_guard_record else None,
                              trace_audit_request=_path(str(trace_audit_request), "trace_audit_request") if trace_audit_request else None,
                              python_executable=_path(str(python_executable), "python_executable") if python_executable else None,
                              max_wall_seconds=max_wall_seconds, max_result_bytes=max_result_bytes)
    built["derived_source_contract"] = derived
    return built


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?")
    parser.add_argument("--v15-request", type=Path, required=True)
    parser.add_argument("--scan-sidecar", type=Path, required=True)
    parser.add_argument("--source-contract-output", type=Path, required=True)
    parser.add_argument("--producer-report", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, action="append", required=True)
    parser.add_argument("--parent-guard-record", type=Path)
    parser.add_argument("--trace-audit-request", type=Path)
    parser.add_argument("--python-executable", type=Path)
    parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    parser.add_argument("--max-result-bytes", type=int, default=100_000_000)
    args = parser.parse_args(argv)
    if args.command not in {None, "derive-and-build"}:
        parser.error("the only command is derive-and-build")
    try:
        value = derive_and_build(v15_request=args.v15_request, scan_sidecar=args.scan_sidecar,
                                 source_contract_output=args.source_contract_output,
                                 producer_report=args.producer_report, target_root=args.target_root,
                                 output_root=args.output_root, output=args.output,
                                 original_roots=args.original_root, parent_guard_record=args.parent_guard_record,
                                 trace_audit_request=args.trace_audit_request,
                                 python_executable=args.python_executable,
                                 max_wall_seconds=args.max_wall_seconds,
                                 max_result_bytes=args.max_result_bytes)
    except (V16ForwardRequestError, V2.V16DerivedRequestError, V1.V16RequestBuilderError,
            OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof request builder v3: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
