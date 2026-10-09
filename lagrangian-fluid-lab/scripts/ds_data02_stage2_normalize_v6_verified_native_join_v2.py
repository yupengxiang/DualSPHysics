#!/usr/bin/env python3
"""Strictly bind V6 case rows to one root terminal producer identity.

V1 is retained as a diagnostic row normalizer.  V2 adds the admission edges
needed by a root wrapper: the V6 request, manifest, and worker report must be
the exact request, manifest, and report named by the terminal proof; their
case IDs and completion counts must agree; and every generated case report
and PartOut CSV must live below the terminal receipt's ``output_root``.

The normalizer only consumes bounded JSON metadata and the already-produced
case reports.  It never opens typed JSONL, H5, BI4, OBI4, PartOut, or
RunPARTs payloads.  Physical fate, flux, dynamics, and QI/QN/QE remain
UNKNOWN.  ``--allow-fixture-context`` is test-only and marks its output
``production_eligible: false``; the default production path rejects that
marker.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
from typing import Any, Mapping

SCRIPT = Path(__file__).resolve()
SCRIPTS = SCRIPT.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ds_data02_stage2_build_native_overlay_adapter_v5 as v5
import ds_data02_stage2_normalize_v6_verified_native_join_v1 as v1
import ds_data02_stage2_verify_generic_native_join_v6 as v6


SCHEMA = "ds02.stage2.root-actual-verification.v1"
NORMALIZER_SCHEMA = "ds02.stage2.v6-verified-native-join-row-normalizer.v2"
MAX_JSON = v1.MAX_JSON


class NormalizationError(ValueError):
    pass


def _fail(message: str) -> None:
    raise NormalizationError(message)


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        _fail(f"{label} path is malformed")
    return Path(value).expanduser().resolve()


def _same_ref(left: Mapping[str, Any], right: Mapping[str, Any], label: str) -> None:
    if left.get("path") != right.get("path"):
        _fail(f"{label} path differs")
    if left.get("sha256") != right.get("sha256"):
        _fail(f"{label} SHA differs")


def _case_ids(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        _fail(f"{label} physical_case_ids are malformed")
    if len(value) != len(set(value)):
        _fail(f"{label} physical_case_ids repeat a case")
    return list(value)


def _document_case_ids(document: Mapping[str, Any], label: str) -> list[str]:
    return _case_ids(document.get("physical_case_ids"), label)


def _load_terminal_refs(terminal: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Read the terminal's four top refs and its receipt once for V2 checks."""
    refs: dict[str, dict[str, Any]] = {}
    documents: dict[str, Any] = {}
    for name in ("request", "receipt", "report", "manifest"):
        value = terminal.get(name)
        expected = terminal.get(f"{name}_sha256")
        if not isinstance(value, str) or not isinstance(expected, str) or len(expected) != 64:
            _fail(f"terminal {name} lacks a concrete path/SHA")
        document, actual = v5._json(value, f"terminal {name}", expected_sha=expected)
        refs[name] = actual
        documents[name] = document
    receipt = documents["receipt"]
    output_root = receipt.get("output_root")
    if not isinstance(output_root, str) or not output_root:
        _fail("terminal receipt lacks output_root")
    output_root_path = _path(output_root, "terminal receipt output_root")
    if not output_root_path.is_dir():
        _fail(f"terminal receipt output_root is not a directory: {output_root_path}")
    documents["output_root_path"] = output_root_path
    return refs, documents


def _inside(path_value: Any, root: Path, label: str) -> None:
    path = _path(path_value, label)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise NormalizationError(f"{label} is outside terminal receipt output_root: {path}") from exc


def _load_v6_identity(v6_document: Mapping[str, Any], terminal_refs: Mapping[str, Mapping[str, Any]], terminal_docs: Mapping[str, Any]) -> dict[str, Any]:
    """Validate V6 top references, producer docs, IDs, status, and counts."""
    if v6_document.get("schema") != v6.OUTPUT_SCHEMA:
        _fail("input is not a V6 verification output")
    status = v6_document.get("status")
    if not isinstance(status, str) or not status.startswith("VERIFIED_"):
        _fail("V6 output is not verified")

    refs: dict[str, dict[str, Any]] = {}
    docs: dict[str, Any] = {}
    for name in ("request", "manifest", "report"):
        value = v6_document.get(name)
        if not isinstance(value, Mapping):
            _fail(f"V6 output lacks top-level {name} reference")
        document, actual = v1._json_ref(value, f"V6 {name}")
        _same_ref(actual, terminal_refs[name], f"V6 {name} vs terminal")
        refs[name] = actual
        docs[name] = document

    request = docs["request"]
    manifest = docs["manifest"]
    report = docs["report"]
    if request.get("schema") != v6.REQUEST_SCHEMA:
        _fail("V6 request schema is not ds02.request.v1")
    request_ids = _document_case_ids(request, "V6 request")
    manifest_ids = _document_case_ids(manifest, "V6 manifest")
    if manifest_ids != request_ids:
        _fail("V6 request and manifest physical_case_ids differ")
    terminal_request_ids = _document_case_ids(terminal_docs["request"], "terminal request")
    terminal_manifest_ids = _document_case_ids(terminal_docs["manifest"], "terminal manifest")
    if terminal_request_ids != request_ids or terminal_manifest_ids != request_ids:
        _fail("V6 producer physical_case_ids differ from terminal request/manifest")
    if terminal_docs["request"].get("schema") != v6.REQUEST_SCHEMA:
        _fail("terminal request schema is not ds02.request.v1")

    report_schema = report.get("schema")
    accepted_report_schemas = {v6.WORKER_REPORT_SCHEMA, *v6.ACCEPTED_ROOT312_REPORT_SCHEMAS}
    if report_schema not in accepted_report_schemas:
        _fail(f"V6 worker report schema is unsupported: {report_schema!r}")
    results = report.get("case_results")
    report_counts = report.get("counts")
    if not isinstance(results, list) or not isinstance(report_counts, Mapping):
        _fail("V6 worker report lacks case_results/counts")
    report_ids = [row.get("physical_case_id") for row in results if isinstance(row, Mapping)]
    if len(report_ids) != len(results) or report_ids != request_ids:
        _fail("V6 worker report physical_case_ids differ from the request")
    counts = v6_document.get("counts")
    if not isinstance(counts, Mapping):
        _fail("V6 output lacks counts")
    case_rows = v6_document.get("case_verifications")
    if not isinstance(case_rows, list) or [row.get("physical_case_id") for row in case_rows] != request_ids:
        _fail("V6 case rows differ from exact request physical_case_ids")
    if counts.get("worker_requested") != len(request_ids) or counts.get("worker_completed") != len(request_ids) or counts.get("worker_failed") != 0:
        _fail("V6 counts do not prove every requested case completed")
    if report_counts.get("requested") != len(request_ids) or report_counts.get("completed") != len(request_ids) or report_counts.get("failed") != 0:
        _fail("V6 producer report counts do not prove every requested case completed")
    if report.get("status") not in {"COMPLETED_ALL_CASES", "COMPLETED_SELECTED_ORIGINAL118_NATIVE_DIAGNOSTIC_ONLY"}:
        _fail("V6 producer report is not an all-completed report")
    if terminal_docs["report"].get("schema") != report_schema:
        _fail("terminal report schema differs from the V6 producer report")
    return {"refs": refs, "documents": docs, "case_ids": request_ids, "output_root": terminal_docs["output_root_path"]}


def _validate_case_output_roots(v6_document: Mapping[str, Any], rows: list[dict[str, Any]], output_root: Path) -> None:
    cases = v6_document.get("case_verifications")
    if not isinstance(cases, list) or len(cases) != len(rows):
        _fail("V6 case rows changed during normalization")
    for case, row in zip(cases, rows):
        case_id = row["physical_case_id"]
        if not isinstance(case, Mapping) or case.get("physical_case_id") != case_id:
            _fail(f"V6 case identity changed during normalization: {case_id}")
        case_output = case.get("case_output")
        if not isinstance(case_output, Mapping):
            _fail(f"V6 case lacks case_output: {case_id}")
        _inside(case_output.get("path"), output_root, f"V6 case output {case_id}")
        _inside(row["native_csv_evidence"].get("path"), output_root, f"V6 native CSV {case_id}")


def normalize(
    v6_result_path: Path,
    terminal_identity_path: Path,
    output_path: Path,
    *,
    allow_fixture_context: bool = False,
) -> dict[str, Any]:
    """Normalize one exact V6/terminal chain without changing source files."""
    v6_result_path = Path(v6_result_path).expanduser().resolve()
    terminal_identity_path = Path(terminal_identity_path).expanduser().resolve()
    v6_document, v6_ref = v1._json_ref(
        {"path": str(v6_result_path), "sha256": v1._sha_file(v6_result_path, "V6 verification output")},
        "V6 verification output",
    )
    terminal, terminal_ref = v1._json_ref(
        {"path": str(terminal_identity_path), "sha256": v1._sha_file(terminal_identity_path, "root terminal identity")},
        "root terminal identity",
    )
    if terminal.get("fixture_context") is not None and not allow_fixture_context:
        _fail("fixture terminal identity requires explicit allow_fixture_context")
    if terminal.get("fixture_context") is not None and terminal.get("fixture_context") != "EXPLICIT_TEST_ONLY":
        _fail("unsupported fixture_context marker")
    try:
        if v5._terminal_state(terminal) != "COMPLETED":
            _fail("root terminal identity is not completed")
        v5._require_completed_accounting(terminal)
    except v5.TerminalOverlayError as exc:
        raise NormalizationError(str(exc)) from exc
    terminal_refs, terminal_docs = _load_terminal_refs(terminal)
    context = _load_v6_identity(v6_document, terminal_refs, terminal_docs)
    rows = v1.normalize_rows(v6_document)
    _validate_case_output_roots(v6_document, rows, context["output_root"])
    if output_path.exists() or output_path.is_symlink():
        _fail(f"refusing to overwrite normalized proof: {output_path}")

    proof = copy.deepcopy(terminal)
    for key in (
        "actual_join_proof", "native_join_proof", "join_proof", "selected_case_ids",
        "case_verifications", "failed_cases", "failed_physical_cases",
        "actual_completed_physical_cases", "new_original118_cause_bound_physical_cases",
        "new_original118_typed_native_joins", "newly_bound_case_ids", "target_fluid_identity_count",
        "actual_typed_native_saved_frame_join_physical_cases",
    ):
        proof.pop(key, None)
    proof["schema"] = SCHEMA
    proof["case_verifications"] = rows
    proof["actual_completed_physical_cases"] = len(rows)
    proof["failed_physical_cases"] = 0
    proof["failed_cases"] = []
    if isinstance(proof.get("counts"), Mapping):
        proof["counts"] = {**dict(proof["counts"]), "cases_requested": len(rows), "completed": len(rows), "failed": 0}
    proof["new_original118_cause_bound_physical_cases"] = 0
    proof["new_original118_typed_native_joins"] = len(rows)
    proof["newly_bound_case_ids"] = []
    proof["target_fluid_identity_count"] = sum(row["target_fluid_identity_count"] for row in rows)
    proof["actual_typed_native_saved_frame_join_physical_cases"] = len(rows)
    proof["v6_verification_output"] = v6_ref
    proof["v6_terminal_identity_input"] = terminal_ref
    proof["normalization_schema"] = NORMALIZER_SCHEMA
    proof["v6_producer_identity"] = {
        "request": context["refs"]["request"],
        "manifest": context["refs"]["manifest"],
        "report": context["refs"]["report"],
        "case_ids": context["case_ids"],
        "case_outputs_under_terminal_output_root": True,
    }
    proof["production_eligible"] = not allow_fixture_context
    if allow_fixture_context:
        proof["fixture_context"] = "EXPLICIT_TEST_ONLY"
    proof["claim_boundary"] = {
        "native_id_join": "VERIFIED_PER_V6_CASE_OUTPUT_EXACT_ROWS_AND_TERMINAL_IDENTITY",
        "new_native_cause_credit": "DEFERRED_TO_ROOT_ROLLING_SCOPE",
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }
    encoded = (json.dumps(proof, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_JSON:
        _fail("normalized root proof exceeds bounded metadata size")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encoded)
    output_ref = v1._ref_after_write(output_path, "normalized root proof")
    return {
        "schema": NORMALIZER_SCHEMA,
        "status": "NORMALIZED_V6_VERIFIED_CASE_ROWS_STRICT_TERMINAL_BOUND",
        "output": output_ref,
        "case_ids": context["case_ids"],
        "new_native_cause_credit": 0,
        "production_eligible": not allow_fixture_context,
        "physical_fate": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v6-result", type=Path, required=True)
    parser.add_argument("--terminal-identity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-fixture-context", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = normalize(args.v6_result, args.terminal_identity, args.output, allow_fixture_context=args.allow_fixture_context)
    except (NormalizationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"V6_NATIVE_JOIN_NORMALIZER_V2_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
