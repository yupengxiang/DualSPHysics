#!/usr/bin/env python3
"""Bind a fresh V41 raw-to-label result to the V10 semantic proof consumer.

This is a post-producer metadata step.  It consumes the small V41 worker
report, V40 engine-integration report, and V40 source contract.  The newly
written V16 JSON is only stat-checked here; its content SHA is the producer's
declared SHA and is rehashed by the parent-approved V10/V11 consumer after
reservation.  The builder never opens the V16 JSON, reconstructed HDF5, BI4,
raw frames, or a historical proof.

V40 keeps the exact CURRENT source identity (df7e...) separate from the new
relocated CURRENT runtime view.  The request therefore binds the V40
relocated digest as its actionable source while retaining the exact source
digest in provenance.  QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V8_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V11_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v11.py"
V40_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_cold_producer_forward_v2.py"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
PRODUCER_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
WORKER_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2"
ENGINE_SCHEMA = "ds02.stage2.f2-v40-engine-integration-report.v1"
CONTRACT_SCHEMA = "ds02.stage2.f2-fresh-v16-source-contract.v40"
BUILDER_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-request-builder.v4"
RELOCATED_STATUS = "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_OVERLAY_SHA = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
REQUIRED_TYPED_FIELDS = [
    "time", "particle_id", "particle_zone", "valid", "position", "velocity",
    "mass", "initial_type", "initial_mk", "initial_mass",
]
EXPECTED_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
EXPECTED_COUNT = 21114
EXPECTED_DENOMINATOR = 21.114001002861187
EXPECTED_LATER_MISSING = 0.003000000142492354


class V16V4BuilderError(RuntimeError):
    """Raised when the actual V41 output cannot be source-bound."""


def canonical_sha(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key not in {"sha256", "report_sha256"}}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise V16V4BuilderError(f"{role} must be a lowercase SHA-256")
    return value


def _path(value: Any, role: str, *, regular: bool = True) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise V16V4BuilderError(f"{role} must be an absolute path")
    target = Path(value).expanduser()
    if regular and (target.is_symlink() or not target.is_file()):
        raise V16V4BuilderError(f"{role} is not a regular non-symlink file: {target}")
    return target


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _path(str(path), role)
    info = target.stat()
    if info.st_size > MAX_METADATA_BYTES:
        raise V16V4BuilderError(f"{role} exceeds metadata-only limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V16V4BuilderError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V16V4BuilderError(f"{role} must contain a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise V16V4BuilderError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _stat(path: Path, role: str) -> dict[str, Any]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise V16V4BuilderError(f"{role} is not a regular non-symlink file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _finite(value: Any, role: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V16V4BuilderError(f"{role} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise V16V4BuilderError(f"{role} must be finite")
    return result


def _unknown(value: Any, role: str) -> None:
    if value != UNKNOWN:
        raise V16V4BuilderError(f"{role} must keep QI/QN/QE UNKNOWN")


def _load_contract(path: Path | str) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, "V40 source contract")
    if value.get("schema") != CONTRACT_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise V16V4BuilderError("V40 source contract schema/canonical SHA differs")
    expected = value.get("expected")
    if not isinstance(expected, Mapping):
        raise V16V4BuilderError("V40 source contract expected binding is missing")
    source = expected.get("source_binding")
    if not isinstance(source, Mapping):
        raise V16V4BuilderError("V40 source contract source binding is missing")
    relocated = source.get("current_catalog_sha256")
    _sha(relocated, "V40 relocated CURRENT digest")
    if relocated in {ACTUAL_CURRENT_SHA, HISTORICAL_OVERLAY_SHA}:
        raise V16V4BuilderError("V40 contract does not contain a distinct relocated CURRENT view")
    if source.get("binding_status") != RELOCATED_STATUS:
        raise V16V4BuilderError("V40 source binding scope is not relocated-runtime-only")
    source_files = source.get("source_files")
    if not isinstance(source_files, Mapping) or source_files.get("current_catalog") != relocated:
        raise V16V4BuilderError("V40 source file current_catalog digest differs from relocated view")
    provenance = value.get("current_catalog_provenance")
    if not isinstance(provenance, Mapping):
        raise V16V4BuilderError("V40 CURRENT provenance is missing")
    original = provenance.get("actual_current_catalog")
    view = provenance.get("relocated_runtime_view")
    if not isinstance(original, Mapping) or original.get("sha256") != ACTUAL_CURRENT_SHA:
        raise V16V4BuilderError("V40 exact CURRENT source identity is not df7e")
    if not isinstance(view, Mapping) or view.get("sha256") != relocated:
        raise V16V4BuilderError("V40 relocated view provenance differs from expected source")
    _unknown(value.get("quality"), "V40 source contract quality")
    return target, value


def _load_engine(path: Path | str, *, worker_path: Path, contract: Mapping[str, Any],
                 output_root: Path) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, "V40 engine-integration report")
    if value.get("schema") != ENGINE_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise V16V4BuilderError("V40 engine report schema/canonical SHA differs")
    if value.get("status") != "COMPLETE_V40_RELOCATED_RAW_TYPED_LABEL":
        raise V16V4BuilderError("V40 engine report is not a completed raw-to-label report")
    expected_source = contract["expected"]["source_binding"]["current_catalog_sha256"]
    if value.get("original_current_identity_sha256") != ACTUAL_CURRENT_SHA:
        raise V16V4BuilderError("engine report exact CURRENT identity differs")
    view = value.get("relocated_current_view")
    if not isinstance(view, Mapping) or view.get("sha256") != expected_source:
        raise V16V4BuilderError("engine report relocated CURRENT digest differs")
    worker = value.get("actual_outputs", {}).get("worker_report")
    if not isinstance(worker, Mapping) or worker.get("path") != str(worker_path):
        raise V16V4BuilderError("engine report does not bind the supplied worker report")
    _sha(worker.get("sha256"), "engine worker report SHA")
    if not _under(worker_path, output_root):
        raise V16V4BuilderError("worker report is outside the relocated output root")
    return target, value


def _result_binding(value: Mapping[str, Any], role: str, output_root: Path,
                    original_roots: Sequence[Path]) -> dict[str, Any]:
    path = _path(value.get("result"), f"{role}.result")
    expected = _sha(value.get("result_sha256"), f"{role}.result_sha256")
    if any(_under(path, root) for root in original_roots):
        raise V16V4BuilderError(f"{role} result remains under an original source root")
    if not _under(path, output_root):
        raise V16V4BuilderError(f"{role} result is outside the relocated output root")
    info = _stat(path, role)
    declared_bytes = value.get("bytes")
    if declared_bytes is not None and int(declared_bytes) != info["bytes"]:
        raise V16V4BuilderError(f"{role} result byte stat differs from report")
    return {"path": str(path), "sha256": expected, "bytes": info["bytes"],
            "stat": info, "content_sha_verified": False,
            "content_verification_phase": "PARENT_AFTER_RESERVATION"}


def _load_worker(path: Path | str, *, contract: Mapping[str, Any], output_root: Path,
                 original_roots: Sequence[Path]) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    target, value = _json(path, "V41 worker report")
    if value.get("schema") != WORKER_SCHEMA:
        raise V16V4BuilderError("V41 worker report schema differs")
    report_sha = value.get("report_sha256")
    if report_sha != canonical_sha(value):
        raise V16V4BuilderError("V41 worker report canonical SHA differs")
    if value.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V16V4BuilderError("V41 worker report is not complete")
    boundary = value.get("execution_boundary")
    if not isinstance(boundary, Mapping) or boundary.get("model_invoked") is not False or boundary.get("cfd_invoked") is not False:
        raise V16V4BuilderError("V41 worker model/CFD boundary is not closed")
    typed = value.get("typed_output")
    if not isinstance(typed, Mapping):
        raise V16V4BuilderError("V41 worker typed output binding is missing")
    typed_path = _path(typed.get("path"), "V41 typed output")
    if not _under(typed_path, output_root) or any(_under(typed_path, root) for root in original_roots):
        raise V16V4BuilderError("V41 typed output is outside relocated roots")
    typed_sha = _sha(typed.get("sha256"), "V41 typed output SHA")
    typed_stat = _stat(typed_path, "V41 typed output")
    if typed.get("bytes") is not None and int(typed["bytes"]) != typed_stat["bytes"]:
        raise V16V4BuilderError("V41 typed output byte stat differs")
    validation = typed.get("validation")
    if not isinstance(validation, Mapping) or validation.get("status") != "PASS_TYPED_IDENTITY_LIFECYCLE_DEVELOPMENT":
        raise V16V4BuilderError("V41 typed validation is not complete")
    cohort = validation.get("fluid_cohort")
    expected_cohort = contract["expected"]["cohort"]
    if not isinstance(cohort, Mapping) or cohort.get("count") != expected_cohort.get("selected_count"):
        raise V16V4BuilderError("V41 typed cohort count differs from V40 source contract")
    if cohort.get("identity_sha256") != expected_cohort.get("identity_sha256"):
        raise V16V4BuilderError("V41 typed identity SHA differs from V40 source contract")
    labels = value.get("typed_to_label")
    if not isinstance(labels, Mapping) or labels.get("status") != "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V16V4BuilderError("V41 V15 label stage is incomplete")
    v15 = _result_binding(labels, "V41 V15 label", output_root, original_roots)
    v16_value = labels.get("v16_forward")
    if not isinstance(v16_value, Mapping) or v16_value.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V16V4BuilderError("V41 V16 label stage is incomplete")
    v16 = _result_binding(v16_value, "V41 V16 label", output_root, original_roots)
    raw = value.get("raw_to_typed")
    if not isinstance(raw, Mapping):
        raise V16V4BuilderError("V41 raw-to-typed stage is missing")
    converter = raw.get("converter_report")
    converter_sha = _sha(raw.get("converter_report_sha256"), "V41 converter report SHA")
    converter_path = _path(converter, "V41 converter report")
    if not _under(converter_path, output_root):
        raise V16V4BuilderError("V41 converter report is outside relocated output root")
    _stat(converter_path, "V41 converter report")
    return target, value, {
        "typed": {"path": str(typed_path), "sha256": typed_sha, "stat": typed_stat},
        "typed_validation": dict(validation), "v15": v15, "v16": v16,
        "converter": {"path": str(converter_path), "sha256": converter_sha},
        "raw_evidence": dict(raw.get("raw_evidence", {})) if isinstance(raw.get("raw_evidence"), Mapping) else {},
    }


def _build_adapter(*, worker_path: Path, worker: Mapping[str, Any], details: Mapping[str, Any],
                   contract_path: Path, contract: Mapping[str, Any], engine_path: Path,
                   engine: Mapping[str, Any], output: Path) -> tuple[Path, dict[str, Any]]:
    validation = details["typed_validation"]
    shape = validation.get("typed_shape", {}) if isinstance(validation.get("typed_shape"), Mapping) else {}
    fluid = validation.get("fluid_cohort", {}) if isinstance(validation.get("fluid_cohort"), Mapping) else {}
    raw = details["raw_evidence"]
    adapter: dict[str, Any] = {
        "schema": PRODUCER_SCHEMA,
        "status": "COMPLETE_TYPED_ONLY_LABELS_DEVELOPMENT_UNKNOWN",
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "request": dict(worker.get("request", {})),
        "typed_input": {
            "path": details["typed"]["path"], "sha256": details["typed"]["sha256"],
            "pre_stat": dict(details["typed"]["stat"]), "post_stat": dict(details["typed"]["stat"]),
            "content_sha256_phase": "PARENT_AFTER_RESERVATION",
        },
        "typed_validation": {
            "frames": int(shape.get("frames", contract["expected"]["time"]["frame_count"])),
            "particles": int(shape.get("particles", 0)),
            "selected_particles": int(fluid.get("count", 0)),
            "identity_sha256": fluid.get("identity_sha256"),
            "raw_opened": True,
            "typed_fields_validated": list(REQUIRED_TYPED_FIELDS),
        },
        "labels": {"v15": dict(details["v15"]), "v16": dict(details["v16"])},
        "v37_provenance": {
            "converter_report": dict(details["converter"]),
            "raw_tree_sha256": raw.get("expected_raw_tree_sha256"),
            "raw_file_count": raw.get("file_count"), "frame_count": raw.get("frame_count"),
            "source": "V41 worker report; V40 relocated engine binding",
        },
        "v41_provenance": {
            "worker_report": {"path": str(worker_path), "report_sha256": worker.get("report_sha256")},
            "engine_report": {"path": str(engine_path), "sha256": engine.get("sha256")},
            "source_contract": {"path": str(contract_path), "sha256": contract.get("sha256")},
            "original_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "relocated_current_view_sha256": contract["expected"]["source_binding"]["current_catalog_sha256"],
            "old_f208_reuse": "FORBIDDEN",
        },
        "execution_boundary": {
            "raw_opened": True, "hdf5_opened": True, "model_invoked": False,
            "cfd_invoked": False, "parent_stage2guard_required": True,
            "result_content_rehash_deferred_to_parent_consumer": True,
        },
        "limitations": [
            "This adapter reads only completed V41 JSON reports and result stat; it does not read the new V16 JSON.",
            "The parent V10/V11 proof consumer must rehash and semantically validate the new V16 result after reservation.",
            "The V40 relocated CURRENT digest is actionable; exact CURRENT df7e is retained as source identity only.",
            "QI/QN/QE remain UNKNOWN.",
        ],
    }
    if adapter["typed_validation"]["selected_particles"] != EXPECTED_COUNT or adapter["typed_validation"]["identity_sha256"] != EXPECTED_IDENTITY_SHA:
        raise V16V4BuilderError("V41 typed validation is not the frozen F2-S1 cohort")
    adapter["sha256"] = canonical_sha(adapter)
    return _write_new(output, adapter), adapter


def _build_request(*, contract_path: Path, contract: Mapping[str, Any], adapter_path: Path,
                   adapter: Mapping[str, Any], worker_path: Path, engine_path: Path,
                   target_root: Path, output_root: Path, output: Path,
                   parent_guard_record: Path | None, trace_audit_request: Path | None,
                   python_executable: Path | None, max_wall_seconds: float,
                   max_result_bytes: int) -> tuple[Path, dict[str, Any]]:
    if target_root == output_root or not target_root.is_dir() or not output_root.is_dir():
        raise V16V4BuilderError("relocated target/output roots must be existing and distinct")
    expected = copy.deepcopy(contract["expected"])
    source = expected["source_binding"]
    if source.get("binding_status") != RELOCATED_STATUS:
        raise V16V4BuilderError("request source binding is not the relocated V40 scope")
    original_roots = [Path(value).expanduser() for value in contract.get("original_roots", []) if isinstance(value, str)]
    if not original_roots:
        raise V16V4BuilderError("V40 contract has no original source roots")
    result = dict(adapter["labels"]["v16"])
    result["content_sha_verified"] = False
    result["content_verification_phase"] = "PARENT_AFTER_RESERVATION"
    parent_binding = None
    if parent_guard_record is not None:
        guard = _path(str(parent_guard_record), "parent guard record")
        if not _under(guard, target_root) and not _under(guard, output_root):
            raise V16V4BuilderError("parent guard record must be in relocated roots")
        parent_binding = {"path": str(guard), "sha256": sha256_file(guard), "content_read_during_build": True}
    trace_binding = {"status": "PENDING_PARENT_TRACE_AUDIT_REQUEST"}
    if trace_audit_request is not None:
        trace = _path(str(trace_audit_request), "trace audit request")
        trace_binding = {"path": str(trace), "sha256": sha256_file(trace), "status": "BOUND_METADATA_ONLY"}
    python_binding = None
    if python_executable is not None:
        executable = _path(str(python_executable), "python executable")
        info = _stat(executable, "python executable")
        if not info["mode_bits"] & 0o111:
            raise V16V4BuilderError("python executable is not executable")
        python_binding = {"literal_invocation_path": str(executable),
                          "resolved_provenance_path": str(executable.resolve()), **info,
                          "preserve_literal_argv0": True}
    declared = {str(Path(adapter["typed_input"]["path"]).expanduser().resolve()),
                str(Path(adapter["v37_provenance"]["converter_report"]["path"]).expanduser().resolve())}
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "role": "DEVELOPMENT", "status": "READY_FOR_PARENT_GUARD",
        "model_invoked": False, "cfd_invoked": False, "ledger_mutated": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN), "result": result,
        "producer_report": {"path": str(adapter_path), "sha256": sha256_file(adapter_path),
                             "schema": PRODUCER_SCHEMA, "content_read": True},
        "provenance_source_report": {"path": str(adapter_path), "sha256": sha256_file(adapter_path),
                                      "schema": PRODUCER_SCHEMA, "content_read_during_build": True},
        "provenance_path_declarations": [
            {"path": path, "role": "typed_input.provenance", "source": "V41_worker_report"}
            for path in sorted(declared)
        ],
        "relocation": {"target_root": str(target_root), "output_root": str(output_root),
                        "original_roots": [str(root) for root in original_roots]},
        "expected": expected,
        "execution": {
            "max_wall_seconds": float(max_wall_seconds), "max_result_bytes": int(max_result_bytes),
            "read_hdf5_or_bi4": False, "raw_opened": False,
            "result_content_verification": "after_parent_reservation",
            "original_path_fallback": "FORBIDDEN", "isolated_python": "-I",
            "python_executable": None if python_binding is None else python_binding["literal_invocation_path"],
            "python_binding": python_binding,
        },
        "source_metadata": {"path": str(contract_path), "sha256": sha256_file(contract_path),
                            "schema": CONTRACT_SCHEMA, "content_read_during_build": True},
        "v8_consumer": {"path": str(V8_SCRIPT), "sha256": sha256_file(V8_SCRIPT), "schema": REQUEST_SCHEMA},
        "v11_consumer": {"path": str(V11_SCRIPT), "sha256": sha256_file(V11_SCRIPT),
                         "schema": "fresh_v16_proof_consumer_v11"},
        "v11_forward": {
            "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-v11-forward.v1",
            "v10_consumer": {"path": str(SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v10.py"),
                             "sha256": sha256_file(SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v10.py")},
            "consumer": {"path": str(V11_SCRIPT), "sha256": sha256_file(V11_SCRIPT)},
            "relocated_status_allowlist": ["RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND"],
            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "relocated_view_sha256": source["current_catalog_sha256"],
            "current_catalog_provenance": {
                "original_current_catalog_sha256": ACTUAL_CURRENT_SHA,
                "relocated_view_sha256": source["current_catalog_sha256"],
                "historical_v39_overlay_sha256": HISTORICAL_OVERLAY_SHA,
                "exact_current_claim": "REJECTED_FOR_RELOCATED_VIEW",
            },
            "original_path_fallback": "FORBIDDEN",
            "qualification": dict(UNKNOWN),
        },
        "v41_binding": {
            "worker_report": {"path": str(worker_path), "report_sha256": adapter["v41_provenance"]["worker_report"]["report_sha256"]},
            "engine_report": {"path": str(engine_path), "sha256": adapter["v41_provenance"]["engine_report"]["sha256"]},
            "source_contract": {"path": str(contract_path), "sha256": contract["sha256"]},
            "current_source_identity_sha256": ACTUAL_CURRENT_SHA,
            "relocated_view_sha256": source["current_catalog_sha256"],
            "old_f208_reuse": "FORBIDDEN",
        },
        "v10_mass_scope_contract": {
            "accepted_result_missing_scope": "initial_fluid_source_cohort_global; identity fate unknown",
            "semantics": "initial denominator is already the frozen fluid mass; later missing mass remains in the unknown bucket and is never added",
            "source_report": {"path": str(adapter_path), "sha256": sha256_file(adapter_path), "schema": PRODUCER_SCHEMA},
            "later_missing_is_not_added_to_initial_denominator": True,
            "source_bound_only": True,
        },
        "parent_guard_record": parent_binding,
        "trace_audit": trace_binding,
        "fresh_result_binding": {
            "source": "V41 worker report + V40 engine report",
            "content_sha_verified": False,
            "verify_after_parent_reservation": True,
        },
        "limitations": [
            "Builder consumes V41/V40 metadata only and stat-checks the new V16 result; it does not hash/read result content.",
            "V11 accepts only the explicit relocated-runtime source binding and delegates all V8/V10 identity, mass, time, event and path checks.",
            "The new V16 result must be rehashed and semantically validated by the parent-approved consumer.",
            "This is DEVELOPMENT only; QI/QN/QE remain UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    return _write_new(output, request), request


def build_from_v41(*, v41_worker_report: Path | str, v40_engine_report: Path | str,
                   v40_contract: Path | str, target_root: Path | str,
                   output_root: Path | str, adapter_output: Path | str,
                   request_output: Path | str, parent_guard_record: Path | str | None = None,
                   trace_audit_request: Path | str | None = None,
                   python_executable: Path | str | None = None,
                   max_wall_seconds: float = 900.0,
                   max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    if not math.isfinite(max_wall_seconds) or max_wall_seconds <= 0:
        raise V16V4BuilderError("max_wall_seconds must be finite and positive")
    if isinstance(max_result_bytes, bool) or not isinstance(max_result_bytes, int) or max_result_bytes <= 0:
        raise V16V4BuilderError("max_result_bytes must be a positive integer")
    contract_path, contract = _load_contract(v40_contract)
    target = Path(target_root).expanduser()
    output = Path(output_root).expanduser()
    worker_path, worker, details = _load_worker(v41_worker_report, contract=contract,
                                                output_root=output, original_roots=[Path(x) for x in contract.get("original_roots", [])])
    engine_path, engine = _load_engine(v40_engine_report, worker_path=worker_path,
                                       contract=contract, output_root=output)
    actual_outputs = engine.get("actual_outputs")
    if not isinstance(actual_outputs, Mapping):
        raise V16V4BuilderError("V40 engine report has no actual output bindings")
    actual_v16 = actual_outputs.get("v16_label_result")
    if (not isinstance(actual_v16, Mapping) or actual_v16.get("path") != details["v16"]["path"]
            or actual_v16.get("sha256") != details["v16"]["sha256"]):
        raise V16V4BuilderError("V40 engine report V16 binding differs from the worker report")
    actual_typed = actual_outputs.get("typed_output")
    if (not isinstance(actual_typed, Mapping) or actual_typed.get("path") != details["typed"]["path"]
            or actual_typed.get("sha256") != details["typed"]["sha256"]):
        raise V16V4BuilderError("V40 engine report typed-output binding differs from the worker report")
    adapter_path, adapter = _build_adapter(worker_path=worker_path, worker=worker, details=details,
                                           contract_path=contract_path, contract=contract,
                                           engine_path=engine_path, engine=engine,
                                           output=Path(adapter_output).expanduser())
    request_path, request = _build_request(
        contract_path=contract_path, contract=contract, adapter_path=adapter_path, adapter=adapter,
        worker_path=worker_path, engine_path=engine_path, target_root=target, output_root=output,
        output=Path(request_output).expanduser(),
        parent_guard_record=None if parent_guard_record is None else Path(parent_guard_record).expanduser(),
        trace_audit_request=None if trace_audit_request is None else Path(trace_audit_request).expanduser(),
        python_executable=None if python_executable is None else Path(python_executable).expanduser(),
        max_wall_seconds=max_wall_seconds, max_result_bytes=max_result_bytes)
    return {
        "schema": BUILDER_SCHEMA, "status": "READY_FOR_PARENT_V11_PROOF_GUARD",
        "adapter_report": str(adapter_path), "adapter_report_sha256": sha256_file(adapter_path),
        "request": str(request_path), "request_sha256": request["sha256"],
        "result_path": request["result"]["path"], "result_sha256": request["result"]["sha256"],
        "result_bytes": request["result"]["bytes"], "result_content_read": False,
        "hdf5_or_bi4_content_read": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v41-worker-report", type=Path, required=True)
    parser.add_argument("--v40-engine-report", type=Path, required=True)
    parser.add_argument("--v40-contract", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--adapter-output", type=Path, required=True)
    parser.add_argument("--request-output", type=Path, required=True)
    parser.add_argument("--parent-guard-record", type=Path)
    parser.add_argument("--trace-audit-request", type=Path)
    parser.add_argument("--python-executable", type=Path)
    parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    parser.add_argument("--max-result-bytes", type=int, default=100_000_000)
    args = parser.parse_args(argv)
    try:
        value = build_from_v41(
            v41_worker_report=args.v41_worker_report, v40_engine_report=args.v40_engine_report,
            v40_contract=args.v40_contract, target_root=args.target_root, output_root=args.output_root,
            adapter_output=args.adapter_output, request_output=args.request_output,
            parent_guard_record=args.parent_guard_record, trace_audit_request=args.trace_audit_request,
            python_executable=args.python_executable, max_wall_seconds=args.max_wall_seconds,
            max_result_bytes=args.max_result_bytes)
    except (V16V4BuilderError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof request builder v4: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
