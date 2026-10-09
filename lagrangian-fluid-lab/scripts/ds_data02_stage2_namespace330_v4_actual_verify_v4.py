#!/usr/bin/env python3
"""Consume the real ROOT313/ROOT322--326 mass-verifier wrapper shape.

The V3 namespace checker remains consumed and immutable.  The ROOT mass
verifier wrappers put the independently checked per-case rows in
``case_verifications``.  Those rows intentionally contain only the summary
that the V5/V6 verifier can prove without exporting the typed payload:
``selected_native_id_count``, ``exact_selected_mass_rows`` and
``missing_selected_mass_rows``.  They do not contain a selected mass sum or a
whole-case mass.  This additive adapter preserves that distinction instead of
silently treating the summary as a complete mass observation.

Only bounded JSON metadata is read.  No typed JSONL, H5, BI4, trajectory, or
native payload is opened by this module.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "namespace330_actual_verify_v3_for_v4",
    SCRIPT_DIR / "ds_data02_stage2_namespace330_v4_actual_verify_v3.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace330 V3 source is unavailable")
_V3 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V3)

SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v4.independent-verification.v4"
MAX_METADATA_BYTES = int(_V3.MAX_METADATA_BYTES)
Namespace330V4ActualVerificationError = _V3.Namespace330V4DynamicVerificationError


def _fail(message: str) -> None:
    raise Namespace330V4ActualVerificationError(message)


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{label} must be a non-negative integer")
    return int(value)


def _is_actual_mass_verifier_row(row: Mapping[str, Any]) -> bool:
    """Recognize the exact V5/V6 independent-verifier case summary.

    This is deliberately stricter than checking for a generic ``status``:
    callers cannot turn an arbitrary hand-written selected-mass row into an
    actual ROOT verifier observation merely by adding a status string.
    """
    status = row.get("status")
    return status in {
        "VERIFIED_SAVED_MASK_MASS_DIAGNOSTIC_ONLY",
        "FAILED_NO_MASS_CREDIT",
    } and "selected_native_id_count" in row


def _mass_row_from_actual_verifier(
    proof: Mapping[str, Any], row: Mapping[str, Any]
) -> dict[str, Any]:
    """Normalize a ROOT V5/V6 ``case_verifications`` row.

    Exact/missing counts are retained as verifier evidence.  Since the V5/V6
    wrapper intentionally omits each typed mass and the selected sum, all
    numeric selected and whole-case mass values remain NULL here.
    """
    if not _is_actual_mass_verifier_row(row):
        return _V3._V4._mass_row(proof, row)

    case_id = _V3._V2._case_id(row)
    if not isinstance(case_id, str):
        _fail("actual mass verifier row has no physical_case_id")
    status = row["status"]
    selected_count = _nonnegative_int(
        row.get("selected_native_id_count"),
        f"{case_id} selected_native_id_count",
    )

    if status == "FAILED_NO_MASS_CREDIT":
        # V5/V6 intentionally rewrite a failed case's selected count to zero
        # in the independent output.  Accepting a nonzero count here would
        # make a failed attempt look like saved-mask evidence.
        if selected_count != 0:
            _fail(f"{case_id} failed verifier row exposes selected IDs")
        for key in ("exact_selected_mass_rows", "missing_selected_mass_rows"):
            if key in row:
                _fail(f"{case_id} failed verifier row unexpectedly exposes {key}")
        normalized_status = "FAILED_OR_UNKNOWN"
        exact_rows = missing_rows = 0
    else:
        exact_rows = _nonnegative_int(
            row.get("exact_selected_mass_rows"),
            f"{case_id} exact_selected_mass_rows",
        )
        missing_rows = _nonnegative_int(
            row.get("missing_selected_mass_rows"),
            f"{case_id} missing_selected_mass_rows",
        )
        if exact_rows + missing_rows != selected_count:
            _fail(f"{case_id} verifier selected-row counts do not balance")
        normalized_status = "COMPLETED"

    return {
        "status": normalized_status,
        "scope_id": proof["scope_id"],
        "source_file_sha256": proof["file_sha256"],
        "initial_mass_kg": None,
        "selected_initial_mass_sum_kg": None,
        "selected_initial_mass_count": selected_count if status != "FAILED_NO_MASS_CREDIT" else None,
        "selected_native_id_count": selected_count,
        "selected_initial_mass_status": (
            "EXACT_ALL_SELECTED_ROWS"
            if status != "FAILED_NO_MASS_CREDIT" and missing_rows == 0
            else "UNKNOWN_AT_LEAST_ONE_SELECTED_ROW_MASS_MISSING"
            if status != "FAILED_NO_MASS_CREDIT"
            else None
        ),
        "selected_exclusion_mass_kg": None,
        "case_total_initial_mass_kg": None,
        "expected_initial_mass_kg": None,
        "observed_initial_mass_kg": None,
        "mass_match": None,
        "failure_reason": row.get("error_message") if status == "FAILED_NO_MASS_CREDIT" else None,
        "verifier_summary": {
            "status": status,
            "selected_native_id_count": selected_count,
            "exact_selected_mass_rows": exact_rows,
            "missing_selected_mass_rows": missing_rows,
            "whole_case_mass_exported": False,
        },
    }


def _mass_signature(item: Mapping[str, Any]) -> tuple[Any, ...]:
    # Keep the same semantic comparison as V3 while retaining the actual
    # verifier count summary in the normalized observation separately.
    return tuple(item.get(key) for key in (
        "status", "selected_initial_mass_sum_kg", "selected_initial_mass_count",
        "selected_initial_mass_status", "selected_exclusion_mass_kg",
        "case_total_initial_mass_kg", "expected_initial_mass_kg",
        "observed_initial_mass_kg", "mass_match",
    ))


def validate_mass_proof_inputs(
    refs: Sequence[Mapping[str, Any]],
    canonical_case_ids: set[str],
) -> dict[str, Any]:
    """Validate V3 mass refs plus actual ROOT V5/V6 verifier wrappers."""
    identities: set[tuple[str, str, str]] = set()
    mass_by_case: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    mass_unmatched = 0
    mass_unscoped = 0
    mass_proofs_with_rows = 0
    mass_row_count = 0
    proof_refs: list[dict[str, Any]] = []

    for index, ref in enumerate(refs):
        if not isinstance(ref, Mapping):
            _fail(f"mass proof ref {index} is malformed")
        role = ref.get("role")
        path_value = ref.get("path")
        declared_sha = ref.get("file_sha256")
        if not isinstance(role, str) or not role.startswith("mass_proof"):
            _fail(f"mass proof ref {index} has invalid role")
        if not isinstance(path_value, str) or not isinstance(declared_sha, str):
            _fail(f"mass proof ref {role} lacks path/SHA")
        identity = (role, path_value, declared_sha)
        if identity in identities:
            _fail(f"mass proof role/path/SHA is duplicated: {identity!r}")
        identities.add(identity)
        path = Path(path_value).expanduser()
        observed_sha = _V3._sha(path)
        _V3._expect(f"mass proof {role} file SHA", observed_sha, declared_sha)
        value = _V3._read_json(path, f"mass proof {role}")
        proof, rows = _V3._V4._proof_scope_v4(value, ref, kind="mass")
        proof_refs.append(proof)
        if rows:
            mass_proofs_with_rows += 1
        else:
            mass_unscoped += 1
        for row in rows:
            case_id = _V3._V2._case_id(row)
            if not isinstance(case_id, str) or case_id not in canonical_case_ids:
                mass_unmatched += 1
                continue
            mass_row_count += 1
            mass_by_case.setdefault(case_id, []).append((proof, row))

    observations: dict[str, dict[str, Any]] = {}
    for case_id in sorted(canonical_case_ids):
        entries = mass_by_case.get(case_id, [])
        normalized: list[dict[str, Any]] = []
        for proof, row in entries:
            item = _mass_row_from_actual_verifier(proof, row)
            if item.get("status") != "COMPLETED":
                item["case_total_initial_mass_kg"] = None
                item["observed_initial_mass_kg"] = None
                item["mass_match"] = None
                item["initial_mass_kg"] = None
            if item.get("case_total_initial_mass_kg") is None:
                if item.get("initial_mass_kg") is not None or item.get("mass_match") is not None:
                    _fail(f"case {case_id} promotes NULL whole-case mass")
            if item.get("verifier_summary") is not None and item.get("selected_initial_mass_status") == "COMPLETED":
                _fail(f"case {case_id} uses unnormalized selected mass status")
            normalized.append(item)
        signatures = {_mass_signature(item) for item in normalized}
        if len(signatures) > 1:
            _fail(f"conflicting mass proofs for case {case_id}")
        expected = normalized[0] if normalized else {
            "status": "UNKNOWN_NO_EXACT_CASE_ROW", "scope_id": None,
            "source_file_sha256": None, "initial_mass_kg": None,
            "selected_initial_mass_sum_kg": None, "selected_initial_mass_count": None,
            "selected_native_id_count": None, "selected_initial_mass_status": None,
            "selected_exclusion_mass_kg": None, "case_total_initial_mass_kg": None,
            "expected_initial_mass_kg": None, "observed_initial_mass_kg": None,
            "mass_match": None, "verifier_summary": None,
        }
        observations[case_id] = {
            "status": expected["status"],
            "scope_ids": [item["scope_id"] for item in normalized],
            "source_file_sha256s": [item["source_file_sha256"] for item in normalized],
            "matching_case_row_count": len(entries),
            "verifier_summaries": [item.get("verifier_summary") for item in normalized],
            **{key: expected.get(key) for key in (
                "initial_mass_kg", "selected_initial_mass_sum_kg", "selected_initial_mass_count",
                "selected_native_id_count", "selected_initial_mass_status",
                "selected_exclusion_mass_kg", "case_total_initial_mass_kg",
                "expected_initial_mass_kg", "observed_initial_mass_kg", "mass_match",
            )},
        }
    return {
        "refs": proof_refs,
        "by_case": mass_by_case,
        "observations": observations,
        "summary": {
            "proof_count": len(refs),
            "proofs_with_case_rows": mass_proofs_with_rows,
            "matching_case_rows": mass_row_count,
            "unmatched_case_rows": mass_unmatched,
            "unscoped_top_level_proofs": mass_unscoped,
            "actual_verifier_rows_normalized": sum(
                sum(summary is not None for summary in observation["verifier_summaries"])
                for observation in observations.values()
            ),
        },
    }


def verify_namespace330_v4_dynamic(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run the consumed V3 catalog verifier with this additive mass hook."""
    previous = _V3.validate_mass_proof_inputs
    _V3.validate_mass_proof_inputs = validate_mass_proof_inputs
    try:
        report = _V3.verify_namespace330_v4_dynamic(*args, **kwargs)
    finally:
        _V3.validate_mass_proof_inputs = previous
    report = dict(report)
    report["schema"] = SCHEMA
    report["mass_parser"] = {
        "schema": "ds02.stage2.namespace330.actual-root-mass-verifier-wrapper.v4",
        "supports": ["ROOT313_V5_case_verifications", "ROOT322_326_V6_case_verifications"],
        "whole_case_mass_credit": "NONE_FROM_VERIFIER_SUMMARY_ONLY",
    }
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--registry", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_namespace330_v4_dynamic(
            args.output_dir, plan_path=args.plan, registry_path=args.registry,
        )
    except Exception as error:
        print(f"NAMESPACE330_ACTUAL_VERIFY_V4_ERROR: {error}")
        return 2
    print(__import__("json").dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
