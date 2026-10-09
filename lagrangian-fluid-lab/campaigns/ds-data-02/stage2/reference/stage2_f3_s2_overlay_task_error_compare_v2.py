#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Forward overlay comparator with strict compact-summary terminal joins.

The consumed V1 comparator accepts the ROOT177 compact-summary schema, but its
terminal check predates the actual external-solver receipt shape: ROOT162 and
ROOT173/174 put ``returncode`` under ``execution`` and use the explicit
``COMPLETED_DEVELOPMENT_UNKNOWN`` status.  This additive adapter keeps the V1
normalizer and field diagnostics, while making the proof/request/receipt join
explicit.  It also fixes the comparison query set to the preregistered common
times 0, 2, 4, 6, and 8 seconds; a run's extra terminal query is retained in
the input summary but is never compared as a common query.

Only bounded JSON metadata and compact summaries are read here.  Full reports,
native Part files, BI4 payloads, and HDF5 files remain outside this worker.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_f3_s2_overlay_task_error_compare_v1.py"
SCHEMA = "ds02.stage2.f3-s2.overlay-task-error-compare.v2"
FROZEN_COMMON_QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)


def _load_v1():
    spec = importlib.util.spec_from_file_location(
        "stage2_f3_s2_overlay_task_error_compare_v2_v1_dependency", V1_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(V1_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V1 = _load_v1()


def _resolved(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path is missing")
    return Path(value).expanduser().resolve()


def _same_path(value: Any, expected: Path, label: str) -> None:
    actual = _resolved(value, label)
    if actual != expected:
        raise ValueError(f"{label} path differs: {actual} != {expected}")


def _same_sha(value: Any, expected: str, label: str) -> None:
    if value in (None, "UNKNOWN"):
        raise ValueError(f"{label} SHA is missing")
    if not isinstance(value, str) or value.lower() != expected:
        raise ValueError(f"{label} SHA differs")


def _request_attempt_matches(receipt_attempt: Any, request_attempt: Any, label: str) -> None:
    if receipt_attempt in (None, "") or request_attempt in (None, ""):
        return
    receipt_text = str(receipt_attempt)
    request_text = str(request_attempt)
    if receipt_text != request_text and not receipt_text.endswith("/" + request_text):
        raise ValueError(f"{label} receipt attempt does not match request attempt")


def _terminal_returncode(receipt: dict[str, Any], label: str) -> int:
    execution = receipt.get("execution")
    nested = execution if isinstance(execution, dict) else {}
    candidates = [
        receipt.get("returncode"),
        receipt.get("return_code"),
        nested.get("returncode"),
        nested.get("return_code"),
    ]
    present = [value for value in candidates if value is not None]
    if not present:
        raise ValueError(f"{label} receipt has no terminal returncode")
    try:
        parsed = [int(value) for value in present]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} receipt returncode is not integral") from exc
    if any(value != 0 for value in parsed):
        raise ValueError(f"{label} receipt returncode is not zero")
    return parsed[0]


def _validate_terminal_binding(
    label: str,
    summary: dict[str, Any],
    proof: Path,
    request: Path,
    receipt: Path,
    expected_case: str,
) -> dict[str, Any]:
    """Validate the actual proof/request/receipt join for one summary.

    ROOT177's compact summary is a baseline observer of ROOT162.  Therefore
    the supplied terminal evidence must be ROOT162 evidence; supplying the
    ROOT177 observer request is intentionally rejected by the declared
    ``case_binding.request_record`` SHA.
    """

    proof = proof.expanduser().resolve()
    request = request.expanduser().resolve()
    receipt = receipt.expanduser().resolve()
    proof_record, proof_value = V1._json_file(proof, f"{label} terminal proof")
    request_record, request_value = V1._json_file(request, f"{label} terminal request")
    receipt_record, receipt_value = V1._json_file(receipt, f"{label} terminal receipt")

    if proof_value.get("schema") not in {
        "ds02.stage2.root-actual-verification.v1",
        "ds02.stage2.root-actual-external-solver-verification.v1",
    }:
        raise ValueError(f"{label} proof schema is not an actual root proof")
    proof_status = str(proof_value.get("status", ""))
    if not ("ACTUAL" in proof_status or proof_status.startswith("VERIFIED") or "PASS" in proof_status):
        raise ValueError(f"{label} proof is not an actual terminal verification: {proof_status!r}")

    _same_path(proof_value.get("request"), request, f"{label} proof request")
    _same_sha(proof_value.get("request_sha256"), request_record["sha256"], f"{label} proof request")
    _same_path(proof_value.get("receipt"), receipt, f"{label} proof receipt")
    _same_sha(proof_value.get("receipt_sha256"), receipt_record["sha256"], f"{label} proof receipt")

    if request_value.get("physical_case_id") not in {expected_case, None}:
        raise ValueError(f"{label} terminal request physical case mismatch")
    request_case = request_value.get("case_id")
    request_attempt = request_value.get("attempt_id")

    receipt_request = receipt_value.get("request")
    if isinstance(receipt_request, dict) and "path" in receipt_request:
        # External-solver receipts use a path/SHA request record.  Observer
        # receipts such as ROOT177 instead embed the executed command object;
        # the proof's explicit request path/SHA remains the authoritative join
        # for those records, and the summary binding is checked below.
        _same_path(receipt_request.get("path"), request, f"{label} receipt request")
        _same_sha(receipt_request.get("sha256"), request_record["sha256"], f"{label} receipt request")
    _request_attempt_matches(receipt_value.get("attempt_id"), request_attempt, label)
    _terminal_returncode(receipt_value, label)
    status = str(receipt_value.get("status", "")).lower()
    if not (status.startswith("completed") or status.startswith("complete") or status in {"success", "completed0"}):
        raise ValueError(f"{label} terminal receipt is not completed: {receipt_value.get('status')!r}")

    case_binding = summary.get("case_binding")
    if not isinstance(case_binding, dict):
        case_binding = {}
    declared_request_sha = case_binding.get("terminal_request_sha256")
    if declared_request_sha not in (None, "UNKNOWN"):
        _same_sha(declared_request_sha, request_record["sha256"], f"{label} summary terminal request")
    declared_request = case_binding.get("request_record")
    if isinstance(declared_request, dict):
        _same_path(declared_request.get("path"), request, f"{label} summary terminal request")
        _same_sha(declared_request.get("sha256"), request_record["sha256"], f"{label} summary terminal request")
    if case_binding.get("physical_case_id") not in {None, expected_case}:
        raise ValueError(f"{label} summary physical case mismatch")
    if request_case is not None and case_binding.get("case_id") not in {None, request_case}:
        raise ValueError(f"{label} summary case ID differs from terminal request")
    if request_attempt is not None and case_binding.get("attempt_id") not in {None, request_attempt}:
        raise ValueError(f"{label} summary attempt ID differs from terminal request")

    return {
        "proof": proof_record,
        "request": request_record,
        "receipt": receipt_record,
        "proof_status": proof_status,
        "receipt_status": receipt_value.get("status"),
        "receipt_returncode": 0,
        "terminal_request_case_id": request_case,
        "terminal_request_attempt_id": request_attempt,
        "summary_terminal_request_sha256": request_record["sha256"],
    }


def _normalize(label: str, path: Path, expected_case: str) -> dict[str, Any]:
    """Use the consumed field normalizer, retaining v5 compact semantics."""

    return V1._normalize(label, path, expected_case)


def compare(normalized: dict[str, dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    """Compare only preregistered common queries, excluding extra endpoints."""

    required = {"same_cfl_baseline", "half_cfl", "half_output"}
    if set(normalized) != required:
        raise ValueError(f"comparison requires exactly baseline/half_cfl/half_output bindings, got {sorted(normalized)}")
    filtered: dict[str, dict[str, Any]] = {}
    for label, value in normalized.items():
        missing = [time for time in FROZEN_COMMON_QUERY_TIMES_S if time not in value["queries"]]
        if missing:
            raise ValueError(f"{label} lacks frozen common query times: {missing}")
        clone = dict(value)
        clone["queries"] = {time: value["queries"][time] for time in FROZEN_COMMON_QUERY_TIMES_S}
        filtered[label] = clone
    result = V1.compare(filtered, contract)
    result["schema"] = SCHEMA
    result["comparison_scope"]["common_query_times_s"] = list(FROZEN_COMMON_QUERY_TIMES_S)
    result["comparison_scope"]["extra_terminal_queries_excluded"] = True
    result["comparison_scope"]["query_policy"] = "frozen_common_0_2_4_6_8_s_only"
    result["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    return result


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps({key: item for key, item in value.items() if key != "sha256"}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _fixture_terminal_self_test() -> None:
    """Exercise nested receipt status and strict proof/request joins."""

    case = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
    with tempfile.TemporaryDirectory(prefix="f3-overlay-v2-binding-") as root_text:
        root = Path(root_text)
        request = root / "request.json"
        receipt = root / "receipt.json"
        proof = root / "proof.json"
        summary = root / "summary.json"
        request_value = {"physical_case_id": case, "case_id": "fixture-case", "attempt_id": "fixture-attempt"}
        request.write_text(json.dumps(request_value, sort_keys=True), encoding="utf-8")
        request_sha = hashlib.sha256(request.read_bytes()).hexdigest()
        receipt_value = {"status": "COMPLETED_DEVELOPMENT_UNKNOWN", "attempt_id": "F3/fixture-attempt", "request": {"path": str(request), "sha256": request_sha}, "execution": {"returncode": 0}}
        receipt.write_text(json.dumps(receipt_value, sort_keys=True), encoding="utf-8")
        receipt_sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
        proof_value = {"schema": "ds02.stage2.root-actual-verification.v1", "status": "VERIFIED_ACTUAL_FIXTURE", "request": str(request), "request_sha256": request_sha, "receipt": str(receipt), "receipt_sha256": receipt_sha}
        proof.write_text(json.dumps(proof_value, sort_keys=True), encoding="utf-8")
        normalized = {"case_binding": {"physical_case_id": case, "terminal_request_sha256": request_sha, "case_id": "fixture-case", "attempt_id": "fixture-attempt"}}
        result = _validate_terminal_binding("fixture", normalized, proof, request, receipt, case)
        if result["receipt_status"] != "COMPLETED_DEVELOPMENT_UNKNOWN" or result["receipt_returncode"] != 0:
            raise AssertionError("nested completed receipt was not accepted")
        bad = root / "bad-request.json"
        bad.write_text(json.dumps({**request_value, "case_id": "wrong"}, sort_keys=True), encoding="utf-8")
        try:
            _validate_terminal_binding("fixture-negative", normalized, proof, bad, receipt, case)
        except ValueError:
            pass
        else:
            raise AssertionError("mismatched request was accepted")


def self_test() -> dict[str, Any]:
    base = V1.manufactured_self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    _fixture_terminal_self_test()
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "delegated_v1_schema": V1.SCHEMA,
        "nested_completed_status": True,
        "proof_request_receipt_join": True,
        "frozen_common_query_times_s": list(FROZEN_COMMON_QUERY_TIMES_S),
        "extra_terminal_query_comparison": False,
        "full_report_read": False,
        "native_payload_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    parser.error("only --self-test is supported by the additive metadata adapter")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
