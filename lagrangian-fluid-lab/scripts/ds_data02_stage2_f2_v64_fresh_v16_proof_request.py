#!/usr/bin/env python3
"""Build post-terminal metadata requests for a fresh V64 V16 proof/evaluator.

This builder is intentionally downstream of a successful V64 parent receipt.
It reads only bounded JSON reports and source-contract metadata.  It never
opens or hashes the new typed HDF5, native BI4, or an old proof/result.  The
later proof worker must perform its own after-reservation content verification
and bind the new typed result to the source contract supplied here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


MAX_METADATA_BYTES = 8 * 1024 * 1024
HEX64 = set("0123456789abcdef")
SCHEMA = "ds02.stage2.f2-v64-fresh-v16-proof-request.v1"
EVALUATOR_SCHEMA = "ds02.stage2.f2-v64-fresh-v16-evaluator-request.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
STALE_MARKERS = ("ROOT060", "root060", "aabfb", "oldproof", "old-proof",
                 "previous_proof", "previous-result")


class FreshV16RequestError(ValueError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, role: str) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise FreshV16RequestError(f"{role} must be an absolute regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise FreshV16RequestError(f"{role} exceeds metadata bound: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FreshV16RequestError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise FreshV16RequestError(f"{role} must be a JSON object")
    return value


def _require_sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise FreshV16RequestError(f"{role} must be a lowercase SHA-256")
    return value


def _canonical(value: Any) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"} if isinstance(value, Mapping) else value
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _contains_stale(value: Any) -> str | None:
    if isinstance(value, str):
        lowered = value.lower()
        for marker in STALE_MARKERS:
            if marker.lower() in lowered:
                return value
        return None
    if isinstance(value, Mapping):
        for item in value.values():
            found = _contains_stale(item)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _contains_stale(item)
            if found is not None:
                return found
    return None


def _typed_contract(report: Mapping[str, Any], summary: Mapping[str, Any]) -> dict[str, Any]:
    contract = report.get("typed_output_contract")
    if not isinstance(contract, Mapping):
        raise FreshV16RequestError("V64 report lacks typed_output_contract")
    path = contract.get("path")
    sha = _require_sha(contract.get("sha256"), "fresh typed output SHA")
    bytes_value = contract.get("bytes")
    if not isinstance(path, str) or not path.startswith("/") or not isinstance(bytes_value, int) or bytes_value < 0:
        raise FreshV16RequestError("fresh typed output path/bytes contract is incomplete")
    summary_contract = summary.get("typed_output_report_contract")
    if not isinstance(summary_contract, Mapping):
        raise FreshV16RequestError("V64 worker summary lacks typed output join")
    if (summary_contract.get("path") != path or
            summary_contract.get("sha256") != sha or
            summary_contract.get("bytes") != bytes_value):
        raise FreshV16RequestError("V64 report and worker summary typed contracts differ")
    if bool(contract.get("parent_rehashed", False)):
        # A true value is fine, but it must still be a new V64 product.  The
        # builder does not trust it as scientific proof; the later worker
        # repeats the content check after its own reservation.
        pass
    return {"path": path, "sha256": sha, "bytes": int(bytes_value),
            "source": "V64_SUCCESSFUL_WORKER_REPORT_AND_SUMMARY_JOIN",
            "content_verification": "DEFERRED_TO_FRESH_PROOF_PARENT_AFTER_RESERVATION"}


def build_requests(*, v64_report: Path, worker_summary: Path, source_contract: Path,
                   output_proof: Path, output_evaluator: Path,
                   attempt_id: str) -> dict[str, Any]:
    if output_proof.absolute() == output_evaluator.absolute():
        raise FreshV16RequestError("proof and evaluator outputs must be distinct")
    report = _load_json(v64_report, "V64 parent report")
    summary = _load_json(worker_summary, "V64 worker summary")
    source = _load_json(source_contract, "fresh source contract")
    if report.get("schema") != "ds02.stage2.f2-root145-copied-recovery-report.v64":
        raise FreshV16RequestError("input is not a V64 parent report")
    if not str(report.get("status", "")).startswith("COMPLETED"):
        raise FreshV16RequestError("fresh proof requires a successful V64 parent report")
    if summary.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-worker-summary.v64":
        raise FreshV16RequestError("input is not a V64 worker summary")
    if str(summary.get("status", "")).startswith("FAILED"):
        raise FreshV16RequestError("fresh proof cannot bind a failed worker summary")
    for value, role in ((report.get("request"), "V64 report request"),
                        (summary.get("summary_path"), "V64 summary path")):
        if isinstance(value, Mapping):
            _require_sha(value.get("sha256"), role)
    stale = _contains_stale({"report": report.get("request"), "summary": summary.get("summary_path"),
                             "source": source})
    if stale is not None:
        raise FreshV16RequestError(f"stale proof/result binding is forbidden: {stale}")
    current_sha = source.get("current_source_sha256", source.get("current_catalog_sha256"))
    current_sha = _require_sha(current_sha, "current source identity SHA")
    runtime_view_sha = _require_sha(source.get("runtime_view_sha256"), "new runtime view SHA")
    current_case_id = source.get("current_case_id")
    if not isinstance(current_case_id, str) or not current_case_id:
        raise FreshV16RequestError("fresh source contract needs current_case_id")
    typed = _typed_contract(report, summary)
    report_request = report.get("request")
    if not isinstance(report_request, Mapping):
        raise FreshV16RequestError("V64 report request binding is missing")
    report_sha = _require_sha(report_request.get("sha256"), "V64 parent request SHA")
    producer = {
        "v64_parent_report_path": str(v64_report),
        "v64_parent_report_sha256": _sha(v64_report),
        "v64_parent_request_sha256": report_sha,
        "worker_summary_path": str(worker_summary),
        "worker_summary_sha256": _sha(worker_summary),
        "typed_output": typed,
        "raw_tree_sha256": report.get("raw_source", {}).get("expected_tree_sha256"),
        "source_closure_prepost_equal": report.get("source_closure", {}).get("prepost_equal"),
        "content_read_scope": "bounded_json_reports_only_at_builder; fresh proof rechecks typed content after reservation",
    }
    source_binding = {
        "current_case_id": current_case_id,
        "current_source_sha256": current_sha,
        "runtime_view_sha256": runtime_view_sha,
        "source_contract_path": str(source_contract),
        "source_contract_sha256": _sha(source_contract),
        "identity_provenance": "new V64 product joined to original CURRENT identity; no old proof/result reuse",
    }
    proof = {
        "schema": SCHEMA,
        "status": "READY_FOR_FRESH_PROOF_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "attempt_id": attempt_id,
        "producer": producer,
        "source_binding": source_binding,
        "proof_scope": {
            "typed_result": "new_v64_product_only",
            "fresh_content_verification": "AFTER_ATOMIC_PARENT_RESERVATION",
            "raw_or_bi4_read_by_builder": False,
            "model_invoked": False,
            "cfd_invoked": False,
            "qualification": dict(UNKNOWN),
            "censor_unknown_preserved": True,
        },
        "sha256": "",
    }
    proof["sha256"] = _canonical(proof)
    evaluator = {
        "schema": EVALUATOR_SCHEMA,
        "status": "DEFERRED_UNTIL_FRESH_PROOF_SUCCESS",
        "role": "DEVELOPMENT",
        "attempt_id": attempt_id + "::evaluator",
        "proof_request_path": str(output_proof),
        "proof_request_sha256": _canonical(proof),
        "source_binding": source_binding,
        "producer_typed_output": typed,
        "fresh_proof_result_sha256": None,
        "model_invoked": False,
        "qualification": dict(UNKNOWN),
        "old_proof_reuse": False,
        "sha256": "",
    }
    evaluator["sha256"] = _canonical(evaluator)
    for path, value in ((output_proof, proof), (output_evaluator, evaluator)):
        if path.exists() or path.is_symlink():
            raise FreshV16RequestError(f"refusing existing output: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                        encoding="utf-8", newline="\n")
    return {"proof_request": str(output_proof), "proof_sha256": _sha(output_proof),
            "evaluator_request": str(output_evaluator), "evaluator_sha256": _sha(output_evaluator),
            "payload_read": False, "old_proof_reuse": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build")
    parser.add_argument("--v64-report", type=Path, required=True)
    parser.add_argument("--worker-summary", type=Path, required=True)
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--output-proof", type=Path, required=True)
    parser.add_argument("--output-evaluator", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    args = parser.parse_args(argv)
    if args.build != "build":
        parser.error("the only command is 'build'")
    try:
        result = build_requests(v64_report=args.v64_report.absolute(),
                                worker_summary=args.worker_summary.absolute(),
                                source_contract=args.source_contract.absolute(),
                                output_proof=args.output_proof.absolute(),
                                output_evaluator=args.output_evaluator.absolute(),
                                attempt_id=args.attempt_id)
    except (FreshV16RequestError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"v64 fresh V16 request builder: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
