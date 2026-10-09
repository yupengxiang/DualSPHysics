#!/usr/bin/env python3
"""Bind a completed V64 parent report to a fresh V16 proof/evaluator stage.

The V64 executor writes a bounded Home report whose ``executor.result`` is a
bounded worker summary.  This adapter follows that real report graph and
checks the small nested v2 worker report, but it never reads or hashes the
large typed HDF5 or V16 result.  The V8 proof consumer performs that content
verification after its own parent reservation.

This is an additive successor to the earlier V64 metadata helper.  It is
deliberately strict about identity: the V64 request, report, new case and
attempt must agree; the exact CURRENT identity must be ``df7e...c62b``; and a
relocated CURRENT view must be separately named and have a different digest.
Historical ROOT060/aabfb artefacts remain provenance only and cannot satisfy
an actionable binding.
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
V64_REPORT_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-report.v64"
V64_REQUEST_SCHEMA = "ds02.stage2.f2-root145-copied-recovery-parent-request.v64"
V64_SUMMARY_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-worker-summary.v64"
V2_REPORT_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2"
PROOF_REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
EVALUATOR_REQUEST_SCHEMA = "ds02.stage2.f2-v65-fresh-v16-evaluator-request.v1"
BUILDER_SCHEMA = "ds02.stage2.f2-v65-fresh-v16-proof-request-builder.v1"
SOURCE_SCHEMAS = {
    "ds02.stage2.f2-fresh-v16-source-contract.v1",
    "ds02.stage2.f2-fresh-v16-source-contract.v40",
    "ds02.stage2.f2-fresh-v16-source-contract.v65",
}
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_CURRENT_SHA = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
OLD_V16_RESULT_SHAS = {
    "69d2ea956b86013135c2418a8b3bc9fc2983b8395cb5a62a243d997bb3d914a5",
    "2b71dcb5370b9cdbd745ece877e892a6f30871207e9351c102cfb9720422fb47",
}
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024
STALE_ACTIONABLE_MARKERS = ("ROOT060", "root060", "aabfb")


class V65FreshProofError(ValueError):
    """Raised when a fresh post-V64 binding is unsafe or incomplete."""


def canonical_sha(value: Any) -> str:
    """Hash a JSON object while omitting its self-reported SHA field."""
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def report_canonical_sha(value: Any) -> str:
    """Canonical hash used by the pinned v2 worker report."""
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items()
                 if key not in {"sha256", "report_sha256"}}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise V65FreshProofError(f"{role} must be a lowercase SHA-256")
    return value


def _path(value: Any, role: str, *, regular: bool = False) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise V65FreshProofError(f"{role} must be an absolute path")
    target = Path(value).expanduser()
    if regular and (target.is_symlink() or not target.is_file()):
        raise V65FreshProofError(f"{role} must be a regular non-symlink file: {target}")
    return target


def _load_json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _path(str(path), role, regular=True)
    try:
        size = target.stat().st_size
    except OSError as error:
        raise V65FreshProofError(f"cannot stat {role}: {error}") from error
    if size > MAX_METADATA_BYTES:
        raise V65FreshProofError(f"{role} exceeds metadata-only limit: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V65FreshProofError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V65FreshProofError(f"{role} must contain a JSON object")
    return target, value


def _stat(path: Path, role: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise V65FreshProofError(f"{role} must be a regular non-symlink file: {path}")
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
        raise V65FreshProofError(f"{role} must retain QI/QN/QE UNKNOWN")


def _actionable_path(value: Any, role: str) -> Path:
    path = _path(value, role)
    lowered = str(path).lower()
    if any(marker.lower() in lowered for marker in STALE_ACTIONABLE_MARKERS):
        raise V65FreshProofError(f"{role} points at historical ROOT060/aabfb material")
    return path


def _require_new_id(value: Any, role: str, *, forbidden: str | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V65FreshProofError(f"{role} must be a non-empty string")
    result = value.strip()
    if any(marker.lower() in result.lower() for marker in STALE_ACTIONABLE_MARKERS):
        raise V65FreshProofError(f"{role} contains a historical marker")
    if forbidden is not None and result == forbidden:
        raise V65FreshProofError(f"{role} must differ from the historical V62 case")
    return result


def _validate_quality(value: Any, role: str) -> None:
    _unknown(value, role)


def _validate_v64_request(path: Path, expected_case: str, expected_attempt: str) -> dict[str, Any]:
    _, request = _load_json(path, "V64 parent request")
    if request.get("schema") != V64_REQUEST_SCHEMA:
        raise V65FreshProofError("V64 parent request schema differs")
    if request.get("sha256") != canonical_sha(request):
        raise V65FreshProofError("V64 parent request canonical SHA differs")
    case_id = _require_new_id(request.get("case_id"), "V64 request case_id")
    attempt_id = _require_new_id(request.get("attempt_id"), "V64 request attempt_id")
    if case_id != expected_case or attempt_id != expected_attempt:
        raise V65FreshProofError("V64 request case/attempt differs from requested fresh binding")
    provenance = request.get("v62_provenance")
    if not isinstance(provenance, Mapping):
        raise V65FreshProofError("V64 request lacks V62 provenance")
    old_case_value = provenance.get("case_id")
    if not isinstance(old_case_value, str) or not old_case_value.strip():
        raise V65FreshProofError("V62 provenance case_id must be a non-empty string")
    # The historical identity is deliberately allowed to carry ROOT060 in
    # this provenance-only field.  It is forbidden in every actionable new
    # case/path/result field above and below.
    old_case = old_case_value.strip()
    if old_case == case_id:
        raise V65FreshProofError("new V64 case_id equals historical V62 case_id")
    if request.get("fresh_cold_credit") is not False:
        raise V65FreshProofError("V64 request must keep fresh_cold_credit false")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise V65FreshProofError("V64 request model/CFD boundary is not closed")
    _validate_quality(request.get("qualification"), "V64 request qualification")
    embedded = request.get("embedded_worker_request")
    current_binding = embedded.get("current_binding") if isinstance(embedded, Mapping) else None
    if not isinstance(current_binding, Mapping):
        raise V65FreshProofError("V64 request exact CURRENT binding is missing")
    _path(current_binding.get("path"), "V64 request current binding path")
    if _sha(current_binding.get("sha256"), "V64 request current binding SHA") != ACTUAL_CURRENT_SHA:
        raise V65FreshProofError("V64 request current binding is not exact df7e...c62b")
    return request


def _validate_v64_parent_report(path: Path, request_path: Path, request: Mapping[str, Any],
                                case_id: str, attempt_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _, report = _load_json(path, "V64 parent report")
    if report.get("schema") != V64_REPORT_SCHEMA:
        raise V65FreshProofError("V64 parent report schema differs")
    status = str(report.get("status", ""))
    if not status.startswith("COMPLETED") or "FAILED" in status:
        raise V65FreshProofError(f"V64 parent report is not successful: {status}")
    binding = report.get("request")
    if not isinstance(binding, Mapping):
        raise V65FreshProofError("V64 report request binding is missing")
    if _path(binding.get("path"), "V64 report request path").resolve() != request_path.resolve():
        raise V65FreshProofError("V64 report points at a different parent request")
    if _sha(binding.get("sha256"), "V64 report request SHA") != request.get("sha256"):
        raise V65FreshProofError("V64 report request SHA differs from the parent request")
    parent = report.get("parent")
    if not isinstance(parent, Mapping) or parent.get("attempt_id") != attempt_id:
        raise V65FreshProofError("V64 report parent attempt differs")
    if report.get("fresh_cold_credit") is not False:
        raise V65FreshProofError("V64 report cannot grant fresh cold credit")
    if report.get("model_invoked") is not False or report.get("cfd_invoked") is not False:
        raise V65FreshProofError("V64 report model/CFD boundary is not closed")
    if report.get("case_id") is not None and report.get("case_id") != case_id:
        raise V65FreshProofError("V64 report case_id differs")
    if report.get("attempt_id") is not None and report.get("attempt_id") != attempt_id:
        raise V65FreshProofError("V64 report attempt_id differs")
    _validate_quality(report.get("qualification"), "V64 report qualification")
    raw = report.get("raw_source")
    closure = report.get("source_closure")
    copy_contract = report.get("copy_contract")
    if not isinstance(raw, Mapping) or raw.get("full_prepost_equal") is not True:
        raise V65FreshProofError("V64 raw source pre/post binding is not closed")
    if not isinstance(closure, Mapping) or closure.get("prepost_equal") is not True:
        raise V65FreshProofError("V64 source closure pre/post binding is not closed")
    if not isinstance(copy_contract, Mapping) or copy_contract.get("raw_copy_attempts") != 0:
        raise V65FreshProofError("V64 raw copy contract is not zero")
    executor = report.get("executor")
    summary = executor.get("result") if isinstance(executor, Mapping) else None
    if not isinstance(summary, Mapping):
        raise V65FreshProofError("V64 report lacks executor.result worker summary")
    if summary.get("schema") != V64_SUMMARY_SCHEMA:
        raise V65FreshProofError("V64 executor result is not the v64 worker summary")
    if str(summary.get("status", "")).startswith("FAILED"):
        raise V65FreshProofError("V64 worker summary is failed")
    if summary.get("model_invoked") is not False or summary.get("cfd_invoked") is not False:
        raise V65FreshProofError("V64 worker summary model/CFD boundary is not closed")
    boundary = summary.get("execution_boundary")
    if not isinstance(boundary, Mapping):
        raise V65FreshProofError("V64 worker execution boundary is missing")
    for key in ("raw_opened", "hdf5_opened", "converter_invoked", "label_operator_invoked"):
        if boundary.get(key) is not True:
            raise V65FreshProofError(f"V64 worker boundary {key} is not true")
    if boundary.get("model_invoked") is not False or boundary.get("cfd_invoked") is not False:
        raise V65FreshProofError("V64 worker execution boundary model/CFD is not closed")
    return report, dict(summary)


def _load_nested_worker_report(summary: Mapping[str, Any], target_root: Path,
                               output_root: Path, original_roots: Sequence[Path]) -> tuple[Path, dict[str, Any]]:
    report_path = _actionable_path(summary.get("report_path"), "V64 nested worker report")
    if not (_under(report_path, target_root) or _under(report_path, output_root)):
        raise V65FreshProofError("nested worker report is outside the fresh namespace")
    if any(_under(report_path, root) for root in original_roots):
        raise V65FreshProofError("nested worker report is under an original root")
    if report_path.stat().st_size > MAX_METADATA_BYTES:
        raise V65FreshProofError("nested worker report exceeds metadata-only limit")
    expected_file_sha = _sha(summary.get("report_file_sha256"), "V64 nested report file SHA")
    if sha256_file(report_path) != expected_file_sha:
        raise V65FreshProofError("nested worker report file SHA differs from summary")
    report_path, nested = _load_json(report_path, "V64 nested worker report v2")
    if nested.get("schema") != V2_REPORT_SCHEMA:
        raise V65FreshProofError("nested worker report schema is not v2")
    report_sha = _sha(nested.get("report_sha256"), "nested worker report canonical SHA")
    if report_sha != report_canonical_sha(nested):
        raise V65FreshProofError("nested worker report canonical SHA differs")
    if nested.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V65FreshProofError("nested worker report is not COMPLETE_DEVELOPMENT_UNKNOWN")
    boundary = nested.get("execution_boundary")
    if not isinstance(boundary, Mapping):
        raise V65FreshProofError("nested worker execution boundary is missing")
    if any(boundary.get(key) is not True for key in ("raw_opened", "hdf5_opened", "converter_invoked", "label_operator_invoked")):
        raise V65FreshProofError("nested worker did not close raw/HDF5/converter/label stages")
    if boundary.get("model_invoked") is not False or boundary.get("cfd_invoked") is not False:
        raise V65FreshProofError("nested worker model/CFD boundary is not closed")
    nested_request = nested.get("request")
    if not isinstance(nested_request, Mapping):
        raise V65FreshProofError("nested worker request binding is missing")
    nested_request_path = _actionable_path(nested_request.get("path"), "nested worker request")
    if not (_under(nested_request_path, target_root) or _under(nested_request_path, output_root)):
        raise V65FreshProofError("nested worker request is outside the fresh namespace")
    if any(_under(nested_request_path, root) for root in original_roots):
        raise V65FreshProofError("nested worker request is under an original root")
    _stat(nested_request_path, "nested worker request")
    if sha256_file(nested_request_path) != _sha(nested_request.get("sha256"), "nested worker request SHA"):
        raise V65FreshProofError("nested worker request SHA differs from nested report")
    return report_path, nested


def _result_binding(nested: Mapping[str, Any], summary: Mapping[str, Any],
                    report: Mapping[str, Any], target_root: Path, output_root: Path,
                    original_roots: Sequence[Path]) -> dict[str, Any]:
    typed = nested.get("typed_output")
    parent_typed = report.get("typed_output_contract")
    if not isinstance(typed, Mapping) or not isinstance(parent_typed, Mapping):
        raise V65FreshProofError("typed output contract is missing")
    typed_path = _actionable_path(typed.get("path"), "typed output")
    for role, path in (("typed output", typed_path),):
        if not (_under(path, target_root) or _under(path, output_root)):
            raise V65FreshProofError(f"{role} is outside the fresh namespace")
        if any(_under(path, root) for root in original_roots):
            raise V65FreshProofError(f"{role} is under an original root")
    typed_sha = _sha(typed.get("sha256"), "typed output SHA")
    typed_bytes = typed.get("bytes")
    if isinstance(typed_bytes, bool) or not isinstance(typed_bytes, int) or typed_bytes <= 0:
        raise V65FreshProofError("typed output bytes are invalid")
    stat_value = _stat(typed_path, "typed output")
    if stat_value["bytes"] != typed_bytes:
        raise V65FreshProofError("typed output stat differs from nested report")
    for candidate, name in ((parent_typed, "V64 parent typed output"),
                            (summary.get("typed_output_report_contract"), "V64 summary typed output")):
        if not isinstance(candidate, Mapping):
            raise V65FreshProofError(f"{name} contract is missing")
        if candidate.get("path") != str(typed_path) or candidate.get("sha256") != typed_sha or candidate.get("bytes") != typed_bytes:
            raise V65FreshProofError(f"{name} differs from nested typed output")
    labels = nested.get("typed_to_label")
    if not isinstance(labels, Mapping) or labels.get("status") != "V15_LABEL_REPLAY_COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V65FreshProofError("nested V15 label stage is incomplete")
    v16 = labels.get("v16_forward")
    if not isinstance(v16, Mapping) or v16.get("status") != "COMPLETE_DEVELOPMENT_UNKNOWN":
        raise V65FreshProofError("nested V16 stage is incomplete")
    v16_path = _actionable_path(v16.get("result"), "nested V16 result")
    if not (_under(v16_path, target_root) or _under(v16_path, output_root)):
        raise V65FreshProofError("nested V16 result is outside the fresh namespace")
    if any(_under(v16_path, root) for root in original_roots):
        raise V65FreshProofError("nested V16 result is under an original root")
    v16_sha = _sha(v16.get("result_sha256"), "nested V16 result SHA")
    if v16_sha in OLD_V16_RESULT_SHAS:
        raise V65FreshProofError("nested V16 result reuses a historical proof/result SHA")
    v16_stat = _stat(v16_path, "nested V16 result")
    return {
        "path": str(v16_path), "sha256": v16_sha, "bytes": v16_stat["bytes"],
        "stat": v16_stat, "content_sha_verified": False,
        "content_verification_phase": "PARENT_AFTER_RESERVATION",
        "source": "V64 nested v2 worker report; builder performs stat only",
        "typed_output": {"path": str(typed_path), "sha256": typed_sha,
                          "bytes": typed_bytes, "stat": stat_value},
        "v15_result": {"path": str(_actionable_path(labels.get("result"), "nested V15 result")),
                        "sha256": _sha(labels.get("result_sha256"), "nested V15 result SHA")},
    }


def _source_contract(path: Path, current_manifest: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    _, contract = _load_json(path, "fresh source contract")
    if contract.get("schema") not in SOURCE_SCHEMAS:
        raise V65FreshProofError("unsupported fresh source contract schema")
    if contract.get("sha256") != canonical_sha(contract):
        raise V65FreshProofError("fresh source contract canonical SHA differs")
    expected = contract.get("expected")
    if not isinstance(expected, Mapping):
        raise V65FreshProofError("fresh source contract expected binding is missing")
    source = expected.get("source_binding")
    if not isinstance(source, Mapping):
        raise V65FreshProofError("fresh source contract source_binding is missing")
    expected_files = source.get("source_files")
    if not isinstance(expected_files, Mapping) or not expected_files:
        raise V65FreshProofError("fresh source contract source_files are missing")
    exact_candidates = [
        source.get("actual_current_catalog_sha256"), source.get("original_current_catalog_sha256"),
        source.get("current_source_sha256"), contract.get("current_source_sha256"),
        contract.get("actual_current_catalog_sha256"),
    ]
    if isinstance(contract.get("current_catalog_provenance"), Mapping):
        original = contract["current_catalog_provenance"].get("actual_current_catalog")
        if isinstance(original, Mapping):
            exact_candidates.append(original.get("sha256"))
    binding_status = source.get("binding_status")
    if binding_status != "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND":
        exact_candidates.append(source.get("current_catalog_sha256"))
    exact = next((item for item in exact_candidates if isinstance(item, str)), None)
    if exact != ACTUAL_CURRENT_SHA:
        raise V65FreshProofError("fresh source contract exact CURRENT identity is not df7e...c62b")
    source_current = expected_files.get("current_catalog")
    if isinstance(source_current, Mapping):
        source_current = source_current.get("sha256")
    _sha(source_current, "source_files.current_catalog")
    if source_current == HISTORICAL_CURRENT_SHA:
        raise V65FreshProofError("fresh source contract source_files.current_catalog is historical aabfb")
    runtime_candidates = [source.get("runtime_view_sha256"), source.get("relocated_current_view_sha256"),
                          contract.get("runtime_view_sha256")]
    if isinstance(contract.get("current_catalog_provenance"), Mapping):
        view = contract["current_catalog_provenance"].get("relocated_runtime_view")
        if isinstance(view, Mapping):
            runtime_candidates.append(view.get("sha256"))
    # A V40 sealer contract legitimately stores the relocated view in
    # source_files.current_catalog, whereas a V65 contract stores the exact
    # CURRENT digest there and names the view separately.  Accept the former
    # only when its provenance proves the exact df7e identity; the emitted V8
    # request is normalized to the exact identity plus a separate view field.
    runtime_candidates.append(source_current)
    runtime_view = next((item for item in runtime_candidates
                         if isinstance(item, str) and item != ACTUAL_CURRENT_SHA), None)
    runtime_view = _sha(runtime_view, "relocated CURRENT runtime view SHA")
    if runtime_view in {ACTUAL_CURRENT_SHA, HISTORICAL_CURRENT_SHA}:
        raise V65FreshProofError("relocated CURRENT runtime view must be distinct from exact/historical identity")
    if current_manifest.is_symlink() or not current_manifest.is_file():
        raise V65FreshProofError("current manifest must be a regular non-symlink file")
    if current_manifest.stat().st_size > MAX_METADATA_BYTES:
        raise V65FreshProofError("current manifest exceeds metadata-only limit")
    actual_manifest_sha = sha256_file(current_manifest)
    if actual_manifest_sha != ACTUAL_CURRENT_SHA:
        raise V65FreshProofError("current manifest content is not the exact df7e...c62b identity")
    _stat(current_manifest, "current manifest")
    _unknown(contract.get("quality"), "fresh source contract quality")
    return contract, {"exact_sha256": exact, "runtime_view_sha256": runtime_view,
                      "current_manifest_sha256": actual_manifest_sha,
                      "current_manifest_stat": _stat(current_manifest, "current manifest")}


def _build(*, v64_report: Path, v64_request: Path, source_contract: Path,
           current_manifest: Path, target_root: Path, output_root: Path,
           original_roots: Sequence[Path], output_proof: Path, output_evaluator: Path,
           case_id: str, attempt_id: str, parent_guard_record: Path | None,
           trace_audit_request: Path | None, max_wall_seconds: float,
           max_result_bytes: int, python_executable: str | None) -> dict[str, Any]:
    case = _require_new_id(case_id, "requested case_id")
    attempt = _require_new_id(attempt_id, "requested attempt_id")
    target = _path(str(target_root), "target_root")
    products = _path(str(output_root), "output_root")
    if target == products or _under(target, products) or _under(products, target):
        raise V65FreshProofError("target_root and output_root must be distinct")
    originals = [_path(str(item), "original_root") for item in original_roots]
    if not originals:
        raise V65FreshProofError("at least one original_root is required")
    for root in originals:
        if root == target or root == products or _under(target, root) or _under(products, root):
            raise V65FreshProofError("fresh namespace overlaps an original root")
    request = _validate_v64_request(v64_request, case, attempt)
    request_storage = request.get("storage_scope")
    if isinstance(request_storage, Mapping) and request_storage.get("external_output_root") is not None:
        declared_output = _path(request_storage.get("external_output_root"), "V64 request output root")
        if declared_output.resolve() != products.resolve():
            raise V65FreshProofError("V64 request output root differs from the fresh output namespace")
    request_runtime = request.get("runtime")
    if isinstance(request_runtime, Mapping) and request_runtime.get("worker_target") is not None:
        declared_worker = _path(request_runtime.get("worker_target"), "V64 request worker target")
        if not _under(declared_worker, target):
            raise V65FreshProofError("V64 request worker target is outside the fresh target namespace")
    report, summary = _validate_v64_parent_report(v64_report, v64_request, request, case, attempt)
    if str(report.get("request", {}).get("path", "")).lower().find("root060") >= 0:
        raise V65FreshProofError("V64 report actionable request path is historical ROOT060")
    nested_path, nested = _load_nested_worker_report(summary, target, products, originals)
    result = _result_binding(nested, summary, report, target, products, originals)
    contract, current = _source_contract(source_contract, current_manifest)
    current_binding = request["embedded_worker_request"]["current_binding"]
    expected = copy.deepcopy(contract["expected"])
    source = expected["source_binding"]
    # The V8 result source_binding is the exact CURRENT identity contract.  A
    # V40/V65 source contract may carry relocated-view/provenance keys beside
    # it, but those are not fields emitted by the V16 result and must not be
    # turned into extra equality requirements for the proof consumer.
    source.pop("runtime_view_sha256", None)
    source.pop("relocated_current_view_sha256", None)
    source.pop("actual_current_catalog_sha256", None)
    source["binding_status"] = "EXACT_CURRENT_SOURCE_BOUND"
    source["current_catalog_sha256"] = ACTUAL_CURRENT_SHA
    source["source_files"]["current_catalog"] = ACTUAL_CURRENT_SHA
    guard = None
    if parent_guard_record is not None:
        guard_path = _actionable_path(str(parent_guard_record), "parent_guard_record")
        if not (_under(guard_path, target) or _under(guard_path, products)):
            raise V65FreshProofError("parent guard record must be in the fresh namespace")
        guard = {"path": str(guard_path), "sha256": sha256_file(guard_path),
                 "content_verification": "metadata_input_only"}
    audit = {"status": "PENDING_PARENT_OS_TRACE_AUDIT"}
    if trace_audit_request is not None:
        audit_path = _actionable_path(str(trace_audit_request), "trace_audit_request")
        audit = {"path": str(audit_path), "sha256": sha256_file(audit_path),
                 "status": "BOUND_METADATA_ONLY"}
    python_binding = None
    if python_executable is not None:
        py = _path(python_executable, "python_executable", regular=True)
        info = _stat(py, "python_executable")
        if not info["mode_bits"] & 0o111:
            raise V65FreshProofError("python_executable is not executable")
        python_binding = {"literal_invocation_path": str(py),
                          "resolved_provenance_path": str(py.resolve()),
                          **info, "preserve_literal_argv0": True}
    proof: dict[str, Any] = {
        "schema": PROOF_REQUEST_SCHEMA, "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT", "family_id": "F2", "case_id": case,
        "attempt_id": attempt, "model_invoked": False, "cfd_invoked": False,
        "ledger_mutated": False, "quality": dict(UNKNOWN),
        "result": result,
        "expected": expected,
        "relocation": {"target_root": str(target), "output_root": str(products),
                        "original_roots": [str(root) for root in originals]},
        "producer_report": {"path": str(v64_report), "sha256": sha256_file(v64_report),
                             "schema": V64_REPORT_SCHEMA, "content_read": True,
                             "nested_worker_report": {"path": str(nested_path),
                                                       "sha256": sha256_file(nested_path)}},
        "v64_parent_binding": {
            "report_path": str(v64_report), "report_sha256": sha256_file(v64_report),
            "request_path": str(v64_request), "request_sha256": request["sha256"],
            "case_id": case, "attempt_id": attempt,
            "nested_worker_report_path": str(nested_path),
            "nested_worker_report_sha256": sha256_file(nested_path),
            "nested_v16_result": {"path": result["path"], "sha256": result["sha256"],
                                   "bytes": result["bytes"]},
            "typed_output": result["typed_output"],
            "current_identity_sha256": ACTUAL_CURRENT_SHA,
            "current_binding_source": {"path": current_binding["path"],
                                       "sha256": current_binding["sha256"],
                                       "provenance_only": True},
            "relocated_current_view_sha256": current["runtime_view_sha256"],
            "historical_case_provenance": request["v62_provenance"],
        },
        "source_metadata": {"path": str(source_contract), "sha256": sha256_file(source_contract),
                             "schema": contract["schema"],
                             "current_manifest": {"path": str(current_manifest),
                                                   "sha256": current["current_manifest_sha256"],
                                                   "stat": current["current_manifest_stat"]}},
        "current_manifest_binding": {"path": str(current_manifest),
                                      "sha256": current["current_manifest_sha256"],
                                      "identity": "EXACT_CURRENT_SOURCE_IDENTITY_DF7E",
                                      "runtime_view_sha256": current["runtime_view_sha256"]},
        "execution": {"max_wall_seconds": float(max_wall_seconds),
                       "max_result_bytes": int(max_result_bytes),
                       "read_hdf5_or_bi4": False, "raw_opened": False,
                       "python_executable": str(python_binding["literal_invocation_path"])
                       if python_binding else None,
                       "python_binding": python_binding,
                       "original_path_fallback": "FORBIDDEN",
                       "result_content_verification": "AFTER_PARENT_RESERVATION",
                       "builder_content_read": "SMALL_JSON_AND_STAT_ONLY"},
        "parent_guard_record": guard, "trace_audit": audit,
        "v8_consumer": {"path": str(SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"),
                         "schema": PROOF_REQUEST_SCHEMA},
        "case_provenance": {"historical_v62_case_id": request["v62_provenance"]["case_id"],
                             "historical_reuse": False},
        "fresh_cold_credit": False,
        "limitations": [
            "V64 and nested v2 reports are the only producer evidence consumed here.",
            "The typed HDF5 and V16 result are stat-checked only; the parent proof consumer must rehash and validate them after reservation.",
            "The exact CURRENT identity is df7e...c62b; the relocated runtime view is separately bound and is not substituted for it.",
            "No model/CFD was invoked and QI/QN/QE remain UNKNOWN; this builder grants no scientific qualification.",
        ],
    }
    proof["sha256"] = canonical_sha(proof)
    if output_proof.exists() or output_proof.is_symlink() or output_evaluator.exists() or output_evaluator.is_symlink():
        raise V65FreshProofError("refusing existing proof/evaluator output")
    output_proof.parent.mkdir(parents=True, exist_ok=True)
    output_evaluator.parent.mkdir(parents=True, exist_ok=True)
    output_proof.write_text(json.dumps(proof, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    proof_file_sha = sha256_file(output_proof)
    evaluator: dict[str, Any] = {
        "schema": EVALUATOR_REQUEST_SCHEMA, "status": "DEFERRED_UNTIL_FRESH_PROOF_SUCCESS",
        "role": "DEVELOPMENT", "family_id": "F2", "case_id": case,
        "attempt_id": attempt + "::evaluator", "model_invoked": False,
        "cfd_invoked": False, "qualification": dict(UNKNOWN), "ledger_mutated": False,
        "proof_request": {"path": str(output_proof), "sha256": proof_file_sha,
                           "canonical_sha256": proof["sha256"], "schema": PROOF_REQUEST_SCHEMA},
        "producer_binding": {"v64_report": proof["v64_parent_binding"],
                              "fresh_v16_result": result},
        "source_binding": {"current_manifest_sha256": ACTUAL_CURRENT_SHA,
                            "relocated_current_view_sha256": current["runtime_view_sha256"],
                            "source_contract": proof["source_metadata"]},
        "execution": {"read_hdf5_or_bi4": False, "raw_opened": False,
                       "model_invoked": False, "original_path_fallback": "FORBIDDEN",
                       "requires_fresh_proof_status": "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN",
                       "proof_content_verification": "PARENT_AFTER_RESERVATION"},
        "old_proof_reuse": False, "fresh_cold_credit": False,
        "limitations": [
            "This is a staging request only; it cannot run before the new V8 proof succeeds.",
            "No old ROOT060/aabfb result or proof may satisfy this request.",
            "The evaluator must bind the fresh proof/result paths from this exact case and attempt.",
        ],
    }
    evaluator["sha256"] = canonical_sha(evaluator)
    output_evaluator.write_text(json.dumps(evaluator, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return {"schema": BUILDER_SCHEMA, "status": "READY_FOR_PARENT_V8_PROOF",
            "proof_request": str(output_proof), "proof_request_sha256": proof["sha256"],
            "proof_request_file_sha256": proof_file_sha,
            "evaluator_request": str(output_evaluator), "evaluator_request_sha256": evaluator["sha256"],
            "case_id": case, "attempt_id": attempt, "payload_read": False,
            "hdf5_bi4_result_content_read": False, "old_proof_reuse": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", choices=["build"])
    parser.add_argument("--v64-report", type=Path, required=True)
    parser.add_argument("--v64-request", type=Path, required=True)
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--current-manifest", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, action="append", required=True)
    parser.add_argument("--output-proof", type=Path, required=True)
    parser.add_argument("--output-evaluator", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--parent-guard-record", type=Path)
    parser.add_argument("--trace-audit-request", type=Path)
    parser.add_argument("--python-executable")
    parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    parser.add_argument("--max-result-bytes", type=int, default=100_000_000)
    args = parser.parse_args(argv)
    try:
        result = _build(
            v64_report=args.v64_report, v64_request=args.v64_request,
            source_contract=args.source_contract, current_manifest=args.current_manifest,
            target_root=args.target_root, output_root=args.output_root,
            original_roots=args.original_root, output_proof=args.output_proof,
            output_evaluator=args.output_evaluator, case_id=args.case_id,
            attempt_id=args.attempt_id, parent_guard_record=args.parent_guard_record,
            trace_audit_request=args.trace_audit_request,
            max_wall_seconds=args.max_wall_seconds, max_result_bytes=args.max_result_bytes,
            python_executable=args.python_executable)
    except (V65FreshProofError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V65 fresh V16 proof builder: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
