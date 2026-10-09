#!/usr/bin/env python3
"""Bind a real V66 producer run to a fresh V8 proof request.

ROOT179C writes a top-level V64 parent report, a separate v64 worker summary,
and a nested v2 raw-to-typed-to-label report.  The older V65 builder expects a
synthetic nested parent shape and also conflates the producer case/attempt with
the new proof attempt.  This additive bridge consumes the real files directly,
keeps those identities separate, and emits the standard V8 proof request plus
a deferred evaluator descriptor for a new ROOT190 namespace.

The builder reads bounded JSON and stats the new typed/V16 files.  It never
reads or hashes HDF5, BI4, raw frames, or the large V16 result.  The exact
CURRENT df7e identity comes from the source-bound producer request; the
CURRENT file is stat-checked only.  A later V8 proof worker must verify the
result content after its own parent reservation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V8_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V8_REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
V8_EVALUATOR_SCHEMA = "ds02.stage2.f2-v66-fresh-v16-evaluator-request.v1"
BRIDGE_SCHEMA = "ds02.stage2.f2-v66-fresh-v16-proof-request-builder.v1"
SOURCE_SCHEMA = "ds02.stage2.f2-fresh-v16-source-contract.v66"
PARENT_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-parent-request.v64"
PARENT_REPORT_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-report.v64"
SUMMARY_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-worker-summary.v64"
NESTED_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2"
TERMINAL_EVIDENCE_SCHEMA = "ds02.stage2.systemd-cpu-evidence.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
FORBIDDEN_HISTORICAL_RESULT_SHA = {
    # This is the proof consumer's historical artifact.  The V66 output SHA
    # 69d2... may be byte-equal to an earlier result, but it is accepted only
    # when the new producer path/report joins below prove a new run produced it.
    "2b71dcb5370b9cdbd745ece877e892a6f30871207e9351c102cfb9720422fb47",
}
HEX64 = set("0123456789abcdef")
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 32 * 1024 * 1024


class V66FreshProofError(ValueError):
    pass


def _load_v8() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_fresh_v16_v8_for_v66", V8_SCRIPT)
    if spec is None or spec.loader is None:
        raise V66FreshProofError(f"cannot load V8 consumer: {V8_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V8 = _load_v8()


def canonical_sha(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def report_canonical_sha(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items()
                 if key not in {"sha256", "report_sha256"}}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    if max_bytes is not None and target.stat().st_size > max_bytes:
        raise V66FreshProofError(f"file exceeds metadata bound: {target}")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, role: str, *, regular: bool = False) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise V66FreshProofError(f"{role} must be an absolute path")
    target = Path(value).expanduser()
    if regular and (target.is_symlink() or not target.is_file()):
        raise V66FreshProofError(f"{role} must be a regular non-symlink file: {target}")
    return target


def _json(path: Path | str, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[Path, dict[str, Any]]:
    target = _path(str(path), role, regular=True)
    if target.stat().st_size > max_bytes:
        raise V66FreshProofError(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V66FreshProofError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V66FreshProofError(f"{role} must be a JSON object")
    return target, value


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise V66FreshProofError(f"{role} must be a lowercase SHA-256")
    return value


def _stat(path: Path, role: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise V66FreshProofError(f"{role} must be a regular non-symlink file: {path}")
    info = path.stat()
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _unknown(value: Any, role: str) -> None:
    if value != UNKNOWN:
        raise V66FreshProofError(f"{role} must keep QI/QN/QE UNKNOWN")


def _optional_false(value: Any, role: str) -> None:
    """Reject a positive execution flag while accepting omitted legacy flags.

    The top-level V64 returned report predates the worker boundary fields and
    therefore omits ``model_invoked``/``cfd_invoked``.  The producer request
    and worker report carry those flags explicitly; an omitted parent-report
    field is provenance-limited, while an explicit true value is unsafe.
    """
    if value not in (None, False):
        raise V66FreshProofError(f"{role} is not false/omitted")


def _new_id(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V66FreshProofError(f"{role} must be a non-empty string")
    lowered = value.lower()
    if any(marker in lowered for marker in ("root060", "aabfb", "oldproof", "old-proof")):
        raise V66FreshProofError(f"{role} contains a historical marker")
    return value.strip()


def _request_binding(path: Path) -> tuple[dict[str, Any], str, str]:
    request_file, request = _json(path, "V66 producer parent request")
    if request.get("schema") != PARENT_SCHEMA:
        raise V66FreshProofError("producer parent request schema differs")
    if request.get("sha256") != canonical_sha(request):
        raise V66FreshProofError("producer parent request canonical SHA differs")
    request_sha = sha256_file(request_file)
    case_id = _new_id(request.get("case_id"), "producer case_id")
    attempt_id = _new_id(request.get("attempt_id"), "producer attempt_id")
    if request.get("fresh_cold_credit") is not False:
        raise V66FreshProofError("producer request must keep fresh_cold_credit false")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise V66FreshProofError("producer request model/CFD boundary is not closed")
    _unknown(request.get("qualification"), "producer request qualification")
    embedded = request.get("embedded_worker_request")
    current = embedded.get("current_binding") if isinstance(embedded, Mapping) else None
    if not isinstance(current, Mapping):
        raise V66FreshProofError("producer request exact CURRENT binding is missing")
    current_path = _path(current.get("path"), "producer CURRENT path")
    _sha(current.get("sha256"), "producer CURRENT SHA")
    if current.get("sha256") != ACTUAL_CURRENT_SHA:
        raise V66FreshProofError("producer CURRENT identity is not exact df7e")
    return request, request_sha, case_id + "::" + attempt_id


def _check_parent_report(*, request_file: Path, request: Mapping[str, Any], request_sha: str,
                         report_path: Path, receipt_path: Path) -> dict[str, Any]:
    report_file, report = _json(report_path, "V66 returned parent report")
    if report.get("schema") != PARENT_REPORT_SCHEMA:
        raise V66FreshProofError("returned parent report schema differs")
    if not str(report.get("status", "")).startswith("COMPLETED"):
        raise V66FreshProofError("V66 parent report is not successful")
    if report.get("request_sha256") != request_sha:
        raise V66FreshProofError("V66 parent report request file SHA differs")
    if Path(str(report.get("report_path", ""))).expanduser().resolve() != receipt_path.resolve():
        raise V66FreshProofError("V66 parent report does not point at supplied receipt")
    for key in ("raw_opened", "hdf5_opened"):
        if report.get(key) is not True:
            raise V66FreshProofError(f"V66 parent report {key} is not true")
    if report.get("raw_copy_attempts") != 0:
        raise V66FreshProofError("V66 parent report execution boundary is not closed")
    _optional_false(report.get("model_invoked"), "V66 parent report model_invoked")
    _optional_false(report.get("cfd_invoked"), "V66 parent report cfd_invoked")
    _unknown(report.get("qualification"), "V66 parent report qualification")
    charge = report.get("charge")
    row = charge.get("charge") if isinstance(charge, Mapping) else None
    if not isinstance(row, Mapping) or row.get("status", "").lower() not in {"completed", "failed", "cancelled", "timeout"}:
        raise V66FreshProofError("V66 parent report charge row is missing/unsupported")
    receipt_file, receipt = _json(receipt_path, "V66 Home receipt", max_bytes=MAX_RECEIPT_BYTES)
    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, Mapping) or Path(str(receipt_request.get("path", ""))).expanduser().resolve() != request_file.resolve():
        raise V66FreshProofError("V66 receipt request path differs")
    if receipt_request.get("sha256") != request_sha:
        raise V66FreshProofError("V66 receipt request file SHA differs")
    report_charge_id = row.get("id")
    accounting = receipt.get("accounting")
    if isinstance(accounting, Mapping) and accounting.get("charge_id") != report_charge_id:
        raise V66FreshProofError("V66 receipt charge ID differs")
    return {"file": report_file, "value": report, "sha256": sha256_file(report_file),
            "receipt_file": receipt_file, "receipt": receipt,
            "receipt_sha256": sha256_file(receipt_file), "charge_id": report_charge_id,
            "reservation_id": accounting.get("reservation_id") if isinstance(accounting, Mapping) else None}


def _check_worker_reports(*, summary_path: Path, nested_path: Path, producer_target: Path,
                          producer_output: Path, original_roots: Sequence[Path]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary_file, summary = _json(summary_path, "V66 worker summary")
    if summary.get("schema") != SUMMARY_SCHEMA or summary.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V66FreshProofError("V66 worker summary is not complete")
    boundary = summary.get("execution_boundary")
    if not isinstance(boundary, Mapping) or any(boundary.get(key) is not True for key in ("raw_opened", "hdf5_opened", "converter_invoked", "label_operator_invoked")):
        raise V66FreshProofError("V66 worker boundary is incomplete")
    if boundary.get("model_invoked") is not False or boundary.get("cfd_invoked") is not False:
        raise V66FreshProofError("V66 worker model/CFD boundary is not closed")
    if summary.get("raw_copy_attempts") != 0 or summary.get("raw_tree_before_sha256") != summary.get("raw_tree_after_sha256"):
        raise V66FreshProofError("V66 worker raw pre/post contract is not closed")
    nested_declared = _path(summary.get("report_path"), "V66 nested report path", regular=True)
    if nested_declared.resolve() != nested_path.resolve():
        raise V66FreshProofError("V66 summary nested report path differs")
    if summary.get("report_file_sha256") != sha256_file(nested_path, max_bytes=MAX_METADATA_BYTES):
        raise V66FreshProofError("V66 summary nested report file SHA differs")
    nested_file, nested = _json(nested_path, "V66 nested worker report")
    if nested.get("schema") != NESTED_SCHEMA or nested.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V66FreshProofError("nested V2 report is not complete")
    if nested.get("report_sha256") != report_canonical_sha(nested):
        raise V66FreshProofError("nested V2 report canonical SHA differs")
    nested_boundary = nested.get("execution_boundary")
    if not isinstance(nested_boundary, Mapping) or any(nested_boundary.get(key) is not True for key in ("raw_opened", "hdf5_opened", "converter_invoked", "label_operator_invoked")):
        raise V66FreshProofError("nested V2 execution boundary is incomplete")
    if nested_boundary.get("model_invoked") is not False or nested_boundary.get("cfd_invoked") is not False:
        raise V66FreshProofError("nested V2 model/CFD boundary is not closed")
    nested_request = nested.get("request")
    if not isinstance(nested_request, Mapping):
        raise V66FreshProofError("nested V2 request binding is missing")
    nested_request_path = _path(nested_request.get("path"), "nested V2 request")
    if not _under(nested_request_path, producer_target) or any(_under(nested_request_path, root) for root in original_roots):
        raise V66FreshProofError("nested V2 request is outside producer namespace")
    _stat(nested_request_path, "nested V2 request")
    if sha256_file(nested_request_path) != _sha(nested_request.get("sha256"), "nested V2 request SHA"):
        raise V66FreshProofError("nested V2 request SHA differs")
    typed = nested.get("typed_output")
    summary_typed = summary.get("typed_output_report_contract")
    if not isinstance(typed, Mapping) or not isinstance(summary_typed, Mapping):
        raise V66FreshProofError("typed output contract is missing")
    typed_path = _path(typed.get("path"), "typed output", regular=True)
    if not _under(typed_path, producer_output) or any(_under(typed_path, root) for root in original_roots):
        raise V66FreshProofError("typed output is outside producer output namespace")
    typed_stat = _stat(typed_path, "typed output")
    typed_sha = _sha(typed.get("sha256"), "typed output SHA")
    typed_bytes = typed.get("bytes")
    if typed_stat["bytes"] != typed_bytes or summary_typed.get("path") != str(typed_path) or summary_typed.get("sha256") != typed_sha or summary_typed.get("bytes") != typed_bytes:
        raise V66FreshProofError("typed output contracts differ")
    labels = nested.get("typed_to_label")
    v16 = labels.get("v16_forward") if isinstance(labels, Mapping) else None
    if not isinstance(labels, Mapping) or labels.get("status") != "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN" or not isinstance(v16, Mapping) or v16.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V66FreshProofError("nested V15/V16 label stage is incomplete")
    result_path = _path(v16.get("result"), "fresh V16 result", regular=True)
    if not _under(result_path, producer_output) or any(_under(result_path, root) for root in original_roots):
        raise V66FreshProofError("fresh V16 result is outside producer output namespace")
    result_sha = _sha(v16.get("result_sha256"), "fresh V16 result SHA")
    if result_sha in FORBIDDEN_HISTORICAL_RESULT_SHA:
        raise V66FreshProofError("fresh V16 result uses the forbidden historical proof SHA")
    result_stat = _stat(result_path, "fresh V16 result")
    return summary, nested, {
        "path": str(result_path), "sha256": result_sha, "bytes": result_stat["bytes"],
        "stat": result_stat, "content_sha_verified": False,
        "content_verification_phase": "PARENT_AFTER_RESERVATION",
        "typed_output": {"path": str(typed_path), "sha256": typed_sha,
                          "bytes": typed_bytes, "stat": typed_stat},
        "v15_result": {"path": str(_path(labels.get("result"), "V15 result")),
                        "sha256": _sha(labels.get("result_sha256"), "V15 result SHA")},
    }


def _normalise_source_contract(path: Path, current_path: Path, current_stat: dict[str, Any],
                               source_sha: str, output: Path, producer_case: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, source_contract = _json(path, "source contract")
    expected = source_contract.get("expected")
    if not isinstance(expected, Mapping):
        raise V66FreshProofError("source contract expected binding is missing")
    expected = copy.deepcopy(expected)
    binding = expected.get("source_binding")
    if not isinstance(binding, Mapping):
        raise V66FreshProofError("source contract source binding is missing")
    binding = dict(binding)
    files = binding.get("source_files")
    if not isinstance(files, Mapping) or not files:
        raise V66FreshProofError("source contract source_files are missing")
    files = dict(files)
    files["current_catalog"] = ACTUAL_CURRENT_SHA
    binding["source_files"] = files
    binding["binding_status"] = "EXACT_CURRENT_SOURCE_BOUND"
    binding["current_catalog_sha256"] = ACTUAL_CURRENT_SHA
    # Keep relocation provenance outside the V8 result-facing source binding.
    # The producer's V16 result has the canonical source fields only; adding
    # bridge-only fields here would make V8's strict result/source comparison
    # reject an otherwise valid new result.
    for key in ("actual_current_catalog_sha256", "runtime_view_sha256",
                "relocated_current_view_sha256",
                "relocated_current_view_content_equal_exact"):
        binding.pop(key, None)
    expected["source_binding"] = binding
    normalized = {
        "schema": SOURCE_SCHEMA, "role": "DEVELOPMENT", "quality": dict(UNKNOWN),
        "producer_case_id": producer_case, "source_contract_input_sha256": sha256_file(path),
        "current_catalog_provenance": {
            "actual_current_catalog": {"path": str(current_path), "sha256": ACTUAL_CURRENT_SHA,
                                        "stat": current_stat},
            "relocated_runtime_view": {"sha256": ACTUAL_CURRENT_SHA,
                                        "content_equal_exact_current": True,
                                        "verification": "producer_request_source_binding"},
        },
        "expected": expected,
    }
    # The old contract is read only as an input.  It may retain the stale
    # relocated-view digest in other provenance fields, but no actionable
    # output contract may carry that digest or ROOT060 marker.
    normalized_text = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
    if "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972" in normalized_text:
        raise V66FreshProofError("normalized source contract still contains stale aabfb CURRENT digest")
    if "root060" in normalized_text.lower() or "oldproof" in normalized_text.lower():
        raise V66FreshProofError("normalized source contract still contains historical actionable marker")
    normalized["sha256"] = canonical_sha(normalized)
    _write_new(output, normalized)
    return normalized, {"path": str(output), "sha256": sha256_file(output),
                        "schema": SOURCE_SCHEMA}


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise V66FreshProofError(f"refusing existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _check_terminal_file(path: Path | None, role: str, *, request_file: Path,
                         report_file: Path, receipt_file: Path) -> dict[str, Any] | None:
    if path is None:
        return None
    file, value = _json(path, role, max_bytes=MAX_RECEIPT_BYTES)
    if role == "terminal systemd evidence":
        if value.get("schema") != TERMINAL_EVIDENCE_SCHEMA or value.get("terminal") is not True:
            raise V66FreshProofError("terminal systemd evidence is not terminal")
        if value.get("request_sha256") != sha256_file(request_file):
            raise V66FreshProofError("terminal evidence request SHA differs")
        if Path(str(value.get("request", ""))).expanduser().resolve() != request_file.resolve():
            raise V66FreshProofError("terminal evidence request path differs")
        if value.get("receipt_sha256") != sha256_file(receipt_file):
            raise V66FreshProofError("terminal evidence receipt SHA differs")
        if value.get("actual_returned_report_sha256") != sha256_file(report_file):
            raise V66FreshProofError("terminal evidence report SHA differs")
    return {"path": str(file), "sha256": sha256_file(file), "bytes": file.stat().st_size,
            "schema": value.get("schema")}


def build_requests(*, parent_request: Path, parent_report: Path, parent_receipt: Path,
                   worker_summary: Path, nested_report: Path, current_manifest: Path,
                   source_contract: Path, producer_target_root: Path,
                   producer_output_root: Path, original_roots: Sequence[Path],
                   output_source_contract: Path, output_proof: Path,
                   output_evaluator: Path, case_id: str, attempt_id: str,
                   terminal_evidence: Path | None = None,
                   terminal_delta: Path | None = None,
                   max_wall_seconds: float = 900.0,
                   max_result_bytes: int = 100_000_000,
                   python_executable: str | None = None) -> dict[str, Any]:
    fresh_case = _new_id(case_id, "fresh ROOT190 case_id")
    fresh_attempt = _new_id(attempt_id, "fresh ROOT190 attempt_id")
    producer_request, request_sha, producer_identity = _request_binding(parent_request)
    producer_case, producer_attempt = producer_identity.split("::", 1)
    if fresh_case == producer_case or fresh_attempt == producer_attempt:
        raise V66FreshProofError("fresh ROOT190 case/attempt must differ from producer ROOT179C identity")
    current_binding = producer_request["embedded_worker_request"]["current_binding"]
    current_path = _path(current_binding["path"], "exact CURRENT path", regular=True)
    supplied_current_path = _path(str(current_manifest), "supplied CURRENT manifest", regular=True)
    if supplied_current_path.resolve() != current_path.resolve():
        raise V66FreshProofError("supplied CURRENT manifest differs from producer request binding")
    current_stat = _stat(current_path, "exact CURRENT")
    parent = _check_parent_report(request_file=parent_request, request=producer_request,
                                  request_sha=request_sha, report_path=parent_report,
                                  receipt_path=parent_receipt)
    summary, nested, result = _check_worker_reports(
        summary_path=worker_summary, nested_path=nested_report,
        producer_target=producer_target_root, producer_output=producer_output_root,
        original_roots=original_roots)
    evidence = _check_terminal_file(terminal_evidence, "terminal systemd evidence",
                                    request_file=parent_request, report_file=parent["file"],
                                    receipt_file=parent["receipt_file"])
    delta = None
    if terminal_delta is not None:
        delta_file, delta_value = _json(terminal_delta, "terminal CPU delta sidecar")
        if delta_value.get("status") not in {"APPENDED_SAME_PARENT_TERMINAL_DELTA", "ALREADY_APPLIED_SAME_PARENT_TERMINAL_DELTA", "READY_FOR_SAME_PARENT_TERMINAL_DELTA"}:
            raise V66FreshProofError("terminal CPU delta sidecar is not a recognized terminal state")
        delta = {"path": str(delta_file), "sha256": sha256_file(delta_file), "bytes": delta_file.stat().st_size,
                 "schema": delta_value.get("schema"), "status": delta_value.get("status")}
    normalized_source, source_meta = _normalise_source_contract(
        source_contract, current_path, current_stat, ACTUAL_CURRENT_SHA,
        output_source_contract, producer_case)
    expected = copy.deepcopy(normalized_source["expected"])
    expected_source = expected["source_binding"]
    _unknown(normalized_source.get("quality"), "normalized source contract quality")
    py_binding = None
    if python_executable is not None:
        py = _path(python_executable, "python executable", regular=True)
        py_stat = _stat(py, "python executable")
        if not py_stat["mode_bits"] & 0o111:
            raise V66FreshProofError("python executable is not executable")
        py_binding = {"literal_invocation_path": str(py), "resolved_provenance_path": str(py.resolve()),
                      **py_stat, "preserve_literal_argv0": True}
    producer = {
        "producer_case_id": producer_case, "producer_attempt_id": producer_attempt,
        "request": {"path": str(parent_request), "file_sha256": request_sha,
                     "canonical_sha256": producer_request["sha256"]},
        "parent_report": {"path": str(parent["file"]), "sha256": parent["sha256"],
                          "status": parent["value"].get("status")},
        "home_receipt": {"path": str(parent["receipt_file"]), "sha256": parent["receipt_sha256"]},
        "worker_summary": {"path": str(worker_summary), "sha256": sha256_file(worker_summary)},
        "nested_worker_report": {"path": str(nested_report), "sha256": sha256_file(nested_report)},
        "terminal_evidence": evidence, "terminal_delta": delta,
        "raw_prepost_tree_sha256": summary.get("raw_tree_before_sha256"),
        "raw_file_count": summary.get("raw_tree_file_count"),
        "fresh_result_digest_collision_allowed": result["sha256"] not in FORBIDDEN_HISTORICAL_RESULT_SHA,
        "content_read_scope": "bounded parent/worker JSON and result stat only; V8 rehash after reservation",
    }
    proof: dict[str, Any] = {
        "schema": V8_REQUEST_SCHEMA, "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "family_id": "F2", "case_id": fresh_case,
        "attempt_id": fresh_attempt, "model_invoked": False, "cfd_invoked": False,
        "ledger_mutated": False, "quality": dict(UNKNOWN),
        "result": result, "expected": expected,
        "relocation": {"target_root": str(producer_target_root.resolve()),
                        "output_root": str(producer_output_root.resolve()),
                        "original_roots": [str(root.resolve()) for root in original_roots]},
        "producer_report": {"path": str(parent_report), "sha256": parent["sha256"],
                             "schema": PARENT_REPORT_SCHEMA, "content_read": True,
                             "worker_summary": {"path": str(worker_summary), "sha256": sha256_file(worker_summary)},
                             "nested_worker_report": {"path": str(nested_report), "sha256": sha256_file(nested_report)}},
        "v66_parent_binding": producer,
        "source_metadata": source_meta,
        "current_manifest_binding": {
            "path": str(current_path), "sha256": ACTUAL_CURRENT_SHA, "stat": current_stat,
            "identity": "EXACT_CURRENT_SOURCE_IDENTITY_DF7E",
            "runtime_view_sha256": ACTUAL_CURRENT_SHA,
            "runtime_view_content_equal_exact_current": True,
            "verification_phase": "PRODUCER_REQUEST_SOURCE_BOUND; V8 RESULT CHECK AFTER RESERVATION",
        },
        "execution": {"max_wall_seconds": float(max_wall_seconds),
                       "max_result_bytes": int(max_result_bytes),
                       "read_hdf5_or_bi4": False, "raw_opened": False,
                       "python_executable": py_binding["literal_invocation_path"] if py_binding else None,
                       "python_binding": py_binding, "original_path_fallback": "FORBIDDEN",
                       "result_content_verification": "AFTER_PARENT_RESERVATION",
                       "builder_content_read": "BOUNDED_JSON_AND_STAT_ONLY"},
        "v8_consumer": {"path": str(V8_SCRIPT), "sha256": sha256_file(V8_SCRIPT),
                         "schema": V8_REQUEST_SCHEMA},
        "fresh_cold_credit": False,
        "case_provenance": {"producer_case_id": producer_case, "producer_attempt_id": producer_attempt,
                             "fresh_case_id": fresh_case, "fresh_attempt_id": fresh_attempt,
                             "historical_reuse": False},
        "limitations": [
            "ROOT179C producer evidence is joined by exact file and canonical SHA; producer and fresh proof identities remain distinct.",
            "The typed HDF5 and V16 JSON are stat-checked only; V8 must rehash and validate the result after its own reservation.",
            "Exact CURRENT df7e is source-bound by the producer request; relocated CURRENT is an exact-byte view, not a substitute identity.",
            "No model/CFD was invoked and QI/QN/QE remain UNKNOWN; this builder grants no qualification.",
        ],
    }
    proof["sha256"] = canonical_sha(proof)
    evaluator: dict[str, Any] = {
        "schema": V8_EVALUATOR_SCHEMA, "status": "DEFERRED_UNTIL_FRESH_PROOF_SUCCESS",
        "role": "DEVELOPMENT", "family_id": "F2", "case_id": fresh_case,
        "attempt_id": fresh_attempt + "::evaluator", "model_invoked": False,
        "cfd_invoked": False, "qualification": dict(UNKNOWN), "ledger_mutated": False,
        "proof_request": {"path": str(output_proof), "file_sha256": "PENDING_OUTPUT_SHA256",
                           "canonical_sha256": proof["sha256"], "schema": V8_REQUEST_SCHEMA},
        "producer_binding": producer, "source_binding": {
            "current_manifest_sha256": ACTUAL_CURRENT_SHA,
            "relocated_current_view_sha256": ACTUAL_CURRENT_SHA,
            "source_contract": source_meta,
        },
        "execution": {"read_hdf5_or_bi4": False, "raw_opened": False,
                       "model_invoked": False, "original_path_fallback": "FORBIDDEN",
                       "requires_fresh_proof_status": "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN",
                       "proof_content_verification": "PARENT_AFTER_RESERVATION"},
        "old_proof_reuse": False, "fresh_cold_credit": False,
        "limitations": ["Evaluator remains deferred until this exact ROOT190 proof succeeds.",
                         "No historical ROOT060/aabfb proof or result is an input."],
    }
    if output_proof.exists() or output_evaluator.exists():
        raise V66FreshProofError("refusing existing proof/evaluator output")
    output_proof.parent.mkdir(parents=True, exist_ok=True)
    output_evaluator.parent.mkdir(parents=True, exist_ok=True)
    output_proof.write_text(json.dumps(proof, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    evaluator["proof_request"]["file_sha256"] = sha256_file(output_proof)
    evaluator["sha256"] = canonical_sha(evaluator)
    output_evaluator.write_text(json.dumps(evaluator, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return {"schema": BRIDGE_SCHEMA, "status": "READY_FOR_PARENT_V8_PROOF",
            "proof_request": str(output_proof), "proof_request_file_sha256": sha256_file(output_proof),
            "proof_request_canonical_sha256": proof["sha256"],
            "evaluator_request": str(output_evaluator), "evaluator_request_sha256": evaluator["sha256"],
            "producer_case_id": producer_case, "producer_attempt_id": producer_attempt,
            "fresh_case_id": fresh_case, "fresh_attempt_id": fresh_attempt,
            "result_sha256": result["sha256"], "result_bytes": result["bytes"],
            "payload_read": False, "hdf5_bi4_result_content_read": False,
            "old_proof_reuse": False, "qualification": dict(UNKNOWN)}


def validate_emitted_v8_request(path: Path | str, *, verify_result_stat: bool = True) -> dict[str, Any]:
    proof_path, proof = _json(path, "V66 emitted V8 proof request")
    if proof.get("schema") != V8_REQUEST_SCHEMA or proof.get("sha256") != canonical_sha(proof):
        raise V66FreshProofError("emitted V8 proof request schema/canonical SHA is invalid")
    parent = proof.get("v66_parent_binding")
    if not isinstance(parent, Mapping):
        raise V66FreshProofError("emitted request lacks V66 parent binding")
    if parent.get("producer_case_id") == proof.get("case_id") or parent.get("producer_attempt_id") == proof.get("attempt_id"):
        raise V66FreshProofError("fresh proof identity was not separated from producer identity")
    source = proof.get("current_manifest_binding")
    if not isinstance(source, Mapping) or source.get("sha256") != ACTUAL_CURRENT_SHA:
        raise V66FreshProofError("emitted request exact CURRENT binding is not df7e")
    if source.get("runtime_view_sha256") != ACTUAL_CURRENT_SHA or source.get("runtime_view_content_equal_exact_current") is not True:
        raise V66FreshProofError("emitted request relocated CURRENT equality contract is incomplete")
    expected = proof.get("expected")
    if not isinstance(expected, Mapping) or expected.get("source_binding", {}).get("current_catalog_sha256") != ACTUAL_CURRENT_SHA:
        raise V66FreshProofError("emitted request expected source is not exact df7e")
    v8 = V8._validate_request(proof, verify_result_stat=verify_result_stat)
    return {"schema": "ds02.stage2.f2-v66-v8-metadata-preflight.v1",
            "status": "V8_METADATA_VALIDATED_READY_FOR_PARENT_PROOF",
            "request": {"path": str(proof_path), "sha256": sha256_file(proof_path)},
            "case_id": proof["case_id"], "attempt_id": proof["attempt_id"],
            "producer_case_id": parent["producer_case_id"],
            "producer_attempt_id": parent["producer_attempt_id"],
            "result": {"path": str(v8["result_path"]), "sha256": v8["result_sha256"],
                       "bytes": v8["result_bytes"], "content_sha_verified": False},
            "payload_read": False, "hdf5_or_bi4_content_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", choices=["build"])
    parser.add_argument("--parent-request", type=Path, required=True)
    parser.add_argument("--parent-report", type=Path, required=True)
    parser.add_argument("--parent-receipt", type=Path, required=True)
    parser.add_argument("--worker-summary", type=Path, required=True)
    parser.add_argument("--nested-report", type=Path, required=True)
    parser.add_argument("--current-manifest", type=Path, required=True)
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--producer-target-root", type=Path, required=True)
    parser.add_argument("--producer-output-root", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, action="append", required=True)
    parser.add_argument("--output-source-contract", type=Path, required=True)
    parser.add_argument("--output-proof", type=Path, required=True)
    parser.add_argument("--output-evaluator", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--terminal-evidence", type=Path)
    parser.add_argument("--terminal-delta", type=Path)
    parser.add_argument("--python-executable")
    parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    parser.add_argument("--max-result-bytes", type=int, default=100_000_000)
    args = parser.parse_args(argv)
    try:
        value = build_requests(
            parent_request=args.parent_request.absolute(), parent_report=args.parent_report.absolute(),
            parent_receipt=args.parent_receipt.absolute(), worker_summary=args.worker_summary.absolute(),
            nested_report=args.nested_report.absolute(), current_manifest=args.current_manifest.absolute(),
            source_contract=args.source_contract.absolute(), producer_target_root=args.producer_target_root.absolute(),
            producer_output_root=args.producer_output_root.absolute(),
            original_roots=[item.absolute() for item in args.original_root],
            output_source_contract=args.output_source_contract.absolute(), output_proof=args.output_proof.absolute(),
            output_evaluator=args.output_evaluator.absolute(), case_id=args.case_id, attempt_id=args.attempt_id,
            terminal_evidence=args.terminal_evidence.absolute() if args.terminal_evidence else None,
            terminal_delta=args.terminal_delta.absolute() if args.terminal_delta else None,
            max_wall_seconds=args.max_wall_seconds, max_result_bytes=args.max_result_bytes,
            python_executable=args.python_executable)
    except (V66FreshProofError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"V66 fresh V16 proof bridge: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
