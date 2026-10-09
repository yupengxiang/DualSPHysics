#!/usr/bin/env python3
"""Strict additive V5 consumer for the Namespace330 mass wrapper.

The consumed V4 adapter already normalizes the real ROOT313/ROOT322--326
``case_verifications`` rows without inventing a selected or whole-case mass.
This version preserves that implementation and tightens cross-proof agreement:
the selected-row partition (exact versus missing) is part of the semantic
observation, so two same-count proofs with different partitions fail closed.

Only bounded JSON metadata is read.  Scientific H5, BI4, trajectory and
native payloads remain outside this interface.  This module is a separately
named forward version; it never edits or monkey-patches the consumed V4
source on disk.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "namespace330_actual_verify_v4_for_v5",
    SCRIPT_DIR / "ds_data02_stage2_namespace330_v4_actual_verify_v4.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace330 V4 source is unavailable")
_V4 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V4)


SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v4.independent-verification.v5"
MAX_METADATA_BYTES = int(_V4.MAX_METADATA_BYTES)
Namespace330V5ActualVerificationError = _V4.Namespace330V4ActualVerificationError


def _mass_signature(item: Mapping[str, Any]) -> tuple[Any, ...]:
    """Include the actual verifier's exact/missing partition in agreement.

    Scope/path/SHA remain provenance and are deliberately excluded.  Legacy
    V3 rows have no ``verifier_summary`` and retain the consumed V4 semantic
    signature.  Actual V5/V6 rows always carry all five summary fields.
    """
    summary = item.get("verifier_summary")
    if summary is None:
        verifier_signature: tuple[Any, ...] | None = None
    elif isinstance(summary, Mapping):
        verifier_signature = tuple(summary.get(key) for key in (
            "status",
            "selected_native_id_count",
            "exact_selected_mass_rows",
            "missing_selected_mass_rows",
            "whole_case_mass_exported",
        ))
    else:
        raise Namespace330V5ActualVerificationError(
            "verifier_summary must be an object when present"
        )
    return tuple(item.get(key) for key in (
        "status", "selected_initial_mass_sum_kg", "selected_initial_mass_count",
        "selected_initial_mass_status", "selected_exclusion_mass_kg",
        "case_total_initial_mass_kg", "expected_initial_mass_kg",
        "observed_initial_mass_kg", "mass_match",
    )) + (verifier_signature,)


def validate_mass_proof_inputs(
    refs: Sequence[Mapping[str, Any]],
    canonical_case_ids: set[str],
) -> dict[str, Any]:
    """Run consumed V4 normalization with the V5 strict conflict policy."""
    previous = _V4._mass_signature
    _V4._mass_signature = _mass_signature
    try:
        result = _V4.validate_mass_proof_inputs(refs, canonical_case_ids)
    finally:
        _V4._mass_signature = previous
    result = dict(result)
    summary = dict(result.get("summary", {}))
    summary["conflict_policy"] = (
        "semantic_mass_plus_actual_verifier_exact_missing_partition"
    )
    result["summary"] = summary
    return result


def verify_namespace330_v5_dynamic(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run the consumed lifecycle/catalog verifier through the V5 mass hook."""
    previous = _V4._mass_signature
    _V4._mass_signature = _mass_signature
    try:
        report = _V4.verify_namespace330_v4_dynamic(*args, **kwargs)
    finally:
        _V4._mass_signature = previous
    report = dict(report)
    report["schema"] = SCHEMA
    report["mass_parser"] = {
        "schema": "ds02.stage2.namespace330.actual-root-mass-verifier-wrapper.v5",
        "supports": [
            "ROOT313_V5_case_verifications",
            "ROOT322_326_V6_case_verifications",
        ],
        "whole_case_mass_credit": "NONE_FROM_VERIFIER_SUMMARY_ONLY",
        "conflict_policy": (
            "same semantic mass requires same exact/missing selected-row partition"
        ),
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
        result = verify_namespace330_v5_dynamic(
            args.output_dir, plan_path=args.plan, registry_path=args.registry,
        )
    except Exception as error:
        print(f"NAMESPACE330_ACTUAL_VERIFY_V5_ERROR: {error}")
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
