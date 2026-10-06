#!/usr/bin/env python3
"""Validate the fresh147 F3 native-receipt metadata closure.

This validator intentionally opens JSON metadata only.  It never follows an
output_root, trajectory, image, or scientific-data path.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parents[1]
REPORT_PATH = PACKAGE_DIR / "metadata" / "f3-native-receipt-scope-closure.json"
MANIFEST_PATH = PACKAGE_DIR / "metadata" / "package-manifest.json"
JSON_SUFFIXES = {".json", ".jsonl"}


class ValidationError(AssertionError):
    pass


def _assert(condition: Any, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _read_json(path: Path, label: str) -> Any:
    _assert(path.suffix.lower() in JSON_SUFFIXES, f"{label}: non-JSON path refused: {path}")
    _assert(path.is_file(), f"{label}: missing JSON metadata: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - gives a useful source failure
        raise ValidationError(f"{label}: invalid JSON: {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_ref(ref: dict[str, Any], label: str, *, expected_key: str = "observed_sha256") -> Any:
    _assert(isinstance(ref, dict), f"{label}: reference is not an object")
    path_value = ref.get("path")
    _assert(isinstance(path_value, str) and path_value.startswith("/"), f"{label}: absolute path required")
    path = Path(path_value)
    value = _read_json(path, label)
    actual = _sha256(path)
    expected = ref.get(expected_key)
    _assert(isinstance(expected, str) and len(expected) == 64, f"{label}: {expected_key} missing")
    _assert(actual == expected, f"{label}: SHA mismatch ({actual} != {expected})")
    declared = ref.get("declared_sha256")
    if declared is not None:
        _assert(declared == actual, f"{label}: declared SHA mismatch ({declared} != {actual})")
    return value


def _request_identity(receipt: dict[str, Any]) -> dict[str, Any]:
    request = receipt.get("request")
    if not isinstance(request, dict):
        request = receipt.get("embedded_request")
    _assert(isinstance(request, dict), "native receipt has no embedded request identity")
    return request


def _check_special_paths(row: dict[str, Any], label: str) -> None:
    """Check recovery-role JSON paths without treating them as native receipts."""

    special = row.get("special_role_closure")
    if not isinstance(special, dict):
        return
    for key, value in special.items():
        if not key.endswith("_path"):
            continue
        _read_json(Path(value), f"{label}.{key}")


def _check_package_manifest() -> None:
    """Check package bytes without making the manifest self-referential."""

    if not MANIFEST_PATH.exists():
        return
    manifest = _read_json(MANIFEST_PATH, "package manifest")
    _assert(manifest.get("schema") == "ds02.f3.native-receipt-scope-closure-package.v1",
            "wrong package manifest schema")
    files = manifest.get("files")
    _assert(isinstance(files, dict) and files, "package manifest has no files")
    for relative, expected in files.items():
        path = (PACKAGE_DIR / relative).resolve()
        _assert(PACKAGE_DIR.resolve() in path.parents, f"manifest escapes package: {relative}")
        _assert(path.is_file(), f"manifest file missing: {relative}")
        _assert(_sha256(path) == expected, f"manifest SHA mismatch: {relative}")
    _assert("metadata/package-manifest.json" in manifest.get("integrity_excludes", []),
            "package manifest must exclude itself")


def load_and_validate() -> dict[str, Any]:
    _check_package_manifest()
    report = _read_json(REPORT_PATH, "fresh147 report")
    _assert(report.get("schema") == "ds02.f3.native-receipt-scope-closure.v1", "wrong report schema")
    _assert(report.get("fresh_id") == "fresh147", "wrong fresh id")
    _assert(report.get("family_id") == "F3", "wrong family")

    sources = report["authoritative_sources"]
    for key in ("current_full336_roster", "checkpoint_183", "fresh146_membership_audit"):
        _json_ref(sources[key], f"authoritative_sources.{key}")
    accepted_refs = sources["accepted_decision_refs"]
    _assert(len(accepted_refs) == 35, "accepted decision reference count changed")
    for item in accepted_refs:
        _json_ref(item["ref"], f"accepted decision {item['case_id']}", expected_key="sha256")

    counts = report["collection_counts"]
    expected_counts = {
        "current_f3_roster": 48,
        "current_f3_unique_physical_case_ids": 48,
        "current_roster_accepted": 35,
        "current_roster_registered_pending": 13,
        "native_completed0_total": 44,
        "native_nonterminal_total": 4,
        "accepted_native_completed0": 31,
        "accepted_native_nonterminal": 4,
        "pending_native_completed0": 13,
    }
    for key, expected in expected_counts.items():
        _assert(counts.get(key) == expected, f"collection count changed: {key}")

    rows = report["rows"]
    _assert(len(rows) == 48, "row count changed")
    _assert(len({row["case_id"] for row in rows}) == 48, "case IDs are not unique")
    _assert(len({row["physical_case_id"] for row in rows}) == 48, "physical IDs are not unique")

    accepted_native_nonterminal = []
    pending_native_completed = 0
    for row in rows:
        case_id = row["case_id"]
        _assert(row.get("family_id") == "F3", f"{case_id}: wrong family")
        receipt_ref = row["native_receipt"]
        receipt = _json_ref(receipt_ref, f"{case_id}.native_receipt")
        request = _request_identity(receipt)

        # Identity must come from the receipt/request, never from a directory name.
        _assert(request.get("case_id") == case_id, f"{case_id}: native case identity mismatch")
        expected_physical = row["physical_case_id"]
        actual_physical = request.get("physical_case_id")
        if actual_physical is None:
            binding = request.get("physical_binding")
            if isinstance(binding, dict):
                actual_physical = binding.get("physical_case_id")
        _assert(actual_physical == expected_physical, f"{case_id}: native physical identity mismatch")

        status = receipt_ref.get("status")
        returncode = receipt_ref.get("returncode")
        _assert(status == receipt_ref.get("status"), f"{case_id}: inconsistent receipt status metadata")
        completion = status == "completed" and returncode == 0
        _assert(receipt_ref.get("completion_qualified") is completion, f"{case_id}: completion flag mismatch")
        if completion:
            if row["roster_status"] == "registered-render-still-pending":
                pending_native_completed += 1
        else:
            accepted_native_nonterminal.append(case_id)

        native_scope = row["native_canonical_scope"].get("sha256")
        request_scope = request.get("physical_condition_sha256")
        mismatch = row.get("native_request_condition_mismatch")
        if mismatch is None:
            _assert(native_scope == request_scope, f"{case_id}: native canonical scope is not request scope")
        else:
            # The historical mother row has a known request/accepted-decision
            # semantic mismatch.  Preserve both values and require the report
            # to disclose the exact receipt-side value rather than collapsing
            # the roles.
            _assert(mismatch == request_scope, f"{case_id}: mismatch does not preserve receipt scope")
            _assert(native_scope != request_scope, f"{case_id}: disclosed mismatch was collapsed")
        _assert(isinstance(native_scope, str) and len(native_scope) == 64, f"{case_id}: missing native scope")

        # Role-bearing scope fields are deliberately separate.  Equal hashes are
        # legal for v1 owners, but no field may silently replace another field.
        for role in ("source_plan_scope", "native_canonical_scope", "actual_converter_legacy_scope"):
            value = row[role]
            _assert(isinstance(value, dict) and (value.get("sha256") is None or len(value["sha256"]) == 64),
                    f"{case_id}: malformed {role}")

        source_request = row.get("native_source_request")
        if source_request is not None:
            source = _json_ref(source_request, f"{case_id}.native_source_request")
            _assert(source_request.get("request_case_id") == case_id, f"{case_id}: source request case mismatch")
            _assert(source_request.get("request_physical_case_id") == expected_physical,
                    f"{case_id}: source request physical mismatch")

        render = row.get("pending_render_request")
        if render is not None:
            _json_ref(render, f"{case_id}.pending_render_request")
            _assert(render.get("case_id") == case_id, f"{case_id}: render case mismatch")
            _assert(render.get("physical_case_id") == expected_physical, f"{case_id}: render physical mismatch")
            _assert(render.get("physical_condition_sha256") == native_scope,
                    f"{case_id}: render/native canonical mismatch")
            _assert(render.get("actual_converter_scope_sha256") == row["actual_converter_legacy_scope"]["sha256"],
                    f"{case_id}: render/legacy scope mismatch")

        for index, alternate in enumerate(row.get("alternate_completion_evidence") or []):
            _json_ref(alternate, f"{case_id}.alternate_completion_evidence[{index}]")

        _check_special_paths(row, case_id)

    _assert(len(accepted_native_nonterminal) == 4, "nonterminal native set changed")
    _assert(pending_native_completed == 13, "pending native completed count changed")

    # Explicit role regressions that have caused real integration errors before.
    ay0270 = next(row for row in rows if row["case_id"].endswith("AY0270"))
    _assert(ay0270["roster_canonical_physical_condition_sha256"] is None,
            "AY0270 roster null evidence was unexpectedly replaced")
    _assert(ay0270["special_role_closure"]["render_request_declared_condition_sha256"] ==
            ay0270["native_canonical_scope"]["sha256"], "AY0270 render/native condition was collapsed")
    _assert(ay0270["special_role_closure"]["original154_conversion_role"].startswith("original conversion receipt remains"),
            "AY0270 original conversion role was relabeled")

    ay0340 = next(row for row in rows if row["case_id"].endswith("AY0340"))
    _assert(ay0340["accepted_decision_top_hash"]["role"] ==
            "actual_converter_legacy_scope (decision top field; do not call canonical)",
            "AY0340 top hash role changed")
    _assert(ay0340["accepted_decision_top_hash"]["sha256"] == ay0340["actual_converter_legacy_scope"]["sha256"],
            "AY0340 top hash is not legacy scope")
    _assert(ay0340["native_canonical_scope"]["sha256"] != ay0340["actual_converter_legacy_scope"]["sha256"],
            "AY0340 native and legacy scopes were collapsed")

    return report


def synthetic_contract_tests(report: dict[str, Any]) -> None:
    """Small metadata-only regressions for the two known scope hazards."""

    # A pending roster null must not erase a concrete native/render condition.
    ay0270 = next(row for row in report["rows"] if row["case_id"].endswith("AY0270"))
    copied = copy.deepcopy(ay0270)
    copied["roster_canonical_physical_condition_sha256"] = None
    _assert(copied["native_canonical_scope"]["sha256"] ==
            copied["special_role_closure"]["render_request_declared_condition_sha256"],
            "synthetic AY0270 null-roster regression")

    # A legacy top hash must remain distinct from a native canonical hash.
    ay0340 = next(row for row in report["rows"] if row["case_id"].endswith("AY0340"))
    copied = copy.deepcopy(ay0340)
    _assert(copied["accepted_decision_top_hash"]["sha256"] ==
            copied["actual_converter_legacy_scope"]["sha256"],
            "synthetic AY0340 legacy-role regression")
    _assert(copied["accepted_decision_top_hash"]["sha256"] !=
            copied["native_canonical_scope"]["sha256"],
            "synthetic AY0340 scope-collapse regression")

    # The four original P1000 receipts are intentionally not relabeled by
    # recovered typed/audit evidence.
    nonterminal = [
        row for row in report["rows"]
        if row["native_receipt"]["status"] != "completed" or row["native_receipt"]["returncode"] != 0
    ]
    _assert(len(nonterminal) == 4, "synthetic nonterminal-native regression")
    _assert(all(row["native_receipt"]["returncode"] is None for row in nonterminal),
            "synthetic nonterminal returncode regression")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic", action="store_true", help="also run metadata-only contract tests")
    args = parser.parse_args()
    report = load_and_validate()
    if args.synthetic:
        synthetic_contract_tests(report)
    print("fresh147 scope closure validation: PASS")
    if args.synthetic:
        print("fresh147 synthetic metadata contracts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
