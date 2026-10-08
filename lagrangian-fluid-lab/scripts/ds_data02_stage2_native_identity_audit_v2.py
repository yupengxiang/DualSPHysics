#!/usr/bin/env python3
"""Forward-only native identity/MK audit for the completed omission ledger.

This is the all-118 wrapper around the already consumed, source-bound V1
single-case auditor.  It reads only the completed JSON, CSV, receipt, XML and
``PartOut_000.obi4`` products named by its manifest.  It never opens a
trajectory HDF5 or a ``Part_*.bi4`` frame and never starts a decoder, solver,
or model.  A case with incomplete source closure is emitted explicitly as
``SOURCE_INCOMPLETE``; it is not converted into native identity credit.

The wrapper is a new version so the V1 source and its consumed receipts remain
immutable.  Native identity credit is limited to the official PartVTKOut
CSV/RunPARTs evidence joined to the typed conversion blocks.  Initial
conversion filtering, legal flux, physical fate, continuous event time and
dynamics remain separate UNKNOWN fields.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V1_PATH = SCRIPT_DIR / "ds_data02_stage2_native_identity_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("stage2_native_identity_audit_v1_for_v2", V1_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load V1 auditor: {V1_PATH}")
V1 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V1
SPEC.loader.exec_module(V1)


MANIFEST_SCHEMA = "ds02.stage2.native-identity-audit-manifest.v2"
OUTPUT_SCHEMA = "ds02.stage2.native-identity-audit.v2"
REQUIRED_SOURCE_KEYS = (
    "scan", "scan_receipt", "native_csv", "runparts", "decoder_receipt",
    "raw_partout", "conversion_report", "solver_receipt", "gencase_receipt",
    "xml", "partvtk_binary",
)
_SHA_CACHE: dict[str, tuple[tuple[int, int, int, int], str]] = {}


class NativeIdentityAuditV2Error(ValueError):
    """Raised when the V2 manifest or all-case contract is invalid."""


def _cached_sha256(path: Path) -> str:
    """Hash each unique guarded input once while retaining exact verification.

    The V1 helper is deliberately reused for every case.  Its normal helper
    would reread the shared official binary and repeated receipt inputs for
    each of 117 rows.  Runtime source pre/post hashes still cover every input;
    this cache only avoids redundant reads of an unchanged inode during this
    one worker invocation.
    """
    path = Path(path).resolve()
    stat = path.stat()
    key = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    cached = _SHA_CACHE.get(str(path))
    if cached is not None and cached[0] == key:
        return cached[1]
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    _SHA_CACHE[str(path)] = (key, value)
    return value


def _read_manifest(path: Path) -> dict[str, Any]:
    path = V1.require_file(path, "native identity V2 manifest")
    manifest = V1.read_json(path, "native identity V2 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise NativeIdentityAuditV2Error(
            f"unsupported native identity V2 manifest schema: {manifest.get('schema')}"
        )
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise NativeIdentityAuditV2Error("native identity V2 requires exactly 118 case rows")
    keys = [case.get("case_key") for case in cases]
    if any(not isinstance(key, str) or not key for key in keys):
        raise NativeIdentityAuditV2Error("native identity V2 has an empty case key")
    if len(set(keys)) != len(keys):
        raise NativeIdentityAuditV2Error("native identity V2 case keys are not unique")
    if int(manifest.get("expected_case_count", -1)) != 118:
        raise NativeIdentityAuditV2Error("native identity V2 expected_case_count is not 118")
    return manifest


def _missing_sources(case: dict[str, Any]) -> list[dict[str, str]]:
    refs = case.get("source_refs")
    missing: list[dict[str, str]] = []
    if not isinstance(refs, dict):
        return [{"key": "source_refs", "reason": "missing_source_refs_object"}]
    for key in REQUIRED_SOURCE_KEYS:
        value = refs.get(key)
        if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not value["path"]:
            missing.append({"key": key, "reason": "missing_manifest_reference"})
            continue
        path = Path(value["path"]).expanduser()
        if not path.is_file():
            missing.append({"key": key, "reason": "source_file_missing", "path": str(path)})
    return missing


def _base_identity(case: dict[str, Any], impact: dict[str, Any], current: dict[str, Any]) -> None:
    """Validate identity fields before deciding whether a case is incomplete."""
    V1._impact_row(impact, case)
    V1._validate_current(current, case)


def _source_incomplete_case(
    case: dict[str, Any], missing: list[dict[str, str]],
    impact: dict[str, Any], current: dict[str, Any],
) -> dict[str, Any]:
    cause = V1._impact_row(impact, case).get("native_numerical_cause", {})
    current_row = V1._validate_current(current, case)
    known_refs = {
        key: value for key, value in (case.get("source_refs") or {}).items()
        if isinstance(value, dict) and isinstance(value.get("path"), str)
    }
    return {
        "case_key": case.get("case_key"),
        "family_id": case.get("family_id"),
        "physical_case_id": case.get("physical_case_id"),
        "case_status": "SOURCE_INCOMPLETE",
        "current_identity": current_row,
        "native_identity": {
            "status": "UNKNOWN_SOURCE_INCOMPLETE",
            "expected_native_motive": cause.get("motive"),
            "expected_native_count": cause.get("native_count"),
            "source_mk_counts": "UNKNOWN_SOURCE_INCOMPLETE",
            "ids": "UNKNOWN_SOURCE_INCOMPLETE",
        },
        "source_closure": {
            "status": "SOURCE_INCOMPLETE_FOR_V2_TYPED_MK_JOIN",
            "missing_sources": missing,
            "known_manifest_refs": known_refs,
            "native_cause_from_impact": "PRODUCER_LEDGER_ONLY; NOT RE-CREDITED BY V2",
        },
        "conversion_filtering": {
            "status": "UNKNOWN_SOURCE_INCOMPLETE",
            "converter_implementation": "UNKNOWN",
        },
        "native_cause": {
            "status": "NOT_CREDITED_BY_V2",
            "motive": cause.get("motive"),
            "native_count": cause.get("native_count"),
            "physical_fate": "UNKNOWN_NOT_PROVEN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "continuous_event_time": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "read_policy": {
            "trajectory_h5_opened": False, "part_frames_opened": False,
            "solver_started": False, "decoder_started": False,
            "cfd_or_model_run": False,
        },
    }


def _enrich_closed_case(result: dict[str, Any]) -> dict[str, Any]:
    native = result.get("native_identity", {})
    denominator = native.get("typed_total_mass_kg")
    missing_mass = native.get("missing_mass_kg")
    if isinstance(denominator, (int, float)) and denominator > 0 and isinstance(missing_mass, (int, float)):
        native["whole_initial_mass_denominator_kg"] = float(denominator)
        native["missing_mass_fraction_of_whole_initial"] = float(missing_mass) / float(denominator)
        native["missing_mass_fraction_scope"] = "source-visible lower bound; no physical-fate or dynamics credit"
    result["case_status"] = "NATIVE_IDENTITY_SOURCE_CLOSED"
    result.setdefault("source_closure", {})["status"] = "FULL_NATIVE_TYPED_MK_SOURCE_CLOSED"
    return result


def _rejected_case(case: dict[str, Any], error: Exception) -> dict[str, Any]:
    return {
        "case_key": case.get("case_key"),
        "family_id": case.get("family_id"),
        "physical_case_id": case.get("physical_case_id"),
        "case_status": "SOURCE_BINDING_REJECTED",
        "failure": {"type": type(error).__name__, "message": str(error)},
        "native_identity": {"status": "UNKNOWN_SOURCE_BINDING_REJECTED"},
        "native_cause": {
            "status": "NOT_CREDITED_BY_V2", "physical_fate": "UNKNOWN_NOT_PROVEN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN", "dynamical_impact": "UNKNOWN",
        },
        "read_policy": {
            "trajectory_h5_opened": False, "part_frames_opened": False,
            "solver_started": False, "decoder_started": False,
            "cfd_or_model_run": False,
        },
    }


def audit(manifest_path: Path, output: Path | None = None) -> dict[str, Any]:
    # Keep the consumed V1 source byte-for-byte unchanged while making the
    # all-case forward audit bounded on shared storage I/O.
    V1.sha256 = _cached_sha256
    manifest_path = V1.require_file(manifest_path, "native identity V2 manifest")
    manifest = _read_manifest(manifest_path)
    _, impact, impact_binding = V1.read_json_ref(manifest["impact_report"], "all118 impact report")
    _, current, current_binding = V1.read_json_ref(manifest["current"], "CURRENT336")
    results: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        try:
            _base_identity(case, impact, current)
            missing = _missing_sources(case)
            if missing:
                results.append(_source_incomplete_case(case, missing, impact, current))
                continue
            results.append(_enrich_closed_case(V1._audit_case(case, impact, current)))
        except V1.IdentityAuditError as exc:
            # A source mismatch is a case-scoped rejection.  The report keeps
            # the row visible while withholding all native identity credit.
            results.append(_rejected_case(case, exc))
    closed = [row for row in results if row.get("case_status") == "NATIVE_IDENTITY_SOURCE_CLOSED"]
    incomplete = [row for row in results if row.get("case_status") == "SOURCE_INCOMPLETE"]
    rejected = [row for row in results if row.get("case_status") == "SOURCE_BINDING_REJECTED"]
    ids = [identity for row in closed for identity in row.get("native_identity", {}).get("ids", [])]
    family_counts: dict[str, dict[str, int]] = {}
    for row in results:
        family = str(row.get("family_id"))
        bucket = family_counts.setdefault(family, {"cases": 0, "closed": 0, "source_incomplete": 0, "rejected": 0})
        bucket["cases"] += 1
        if row in closed:
            bucket["closed"] += 1
        elif row in incomplete:
            bucket["source_incomplete"] += 1
        else:
            bucket["rejected"] += 1
    if rejected:
        status = "COMPLETED_WITH_CASE_SCOPED_SOURCE_REJECTIONS"
    elif incomplete:
        status = "COMPLETED_WITH_CASE_SCOPED_SOURCE_GAPS"
    else:
        status = "COMPLETED_NATIVE_IDENTITY_MK_TYPE_AUDIT_ALL118"
    result = {
        "schema": OUTPUT_SCHEMA,
        "status": status,
        "manifest": {"path": str(manifest_path), "sha256": V1.sha256(manifest_path), "bytes": manifest_path.stat().st_size},
        "source_reports": {
            "impact": impact_binding, "current": current_binding,
            "impact_case_count": len(impact.get("cases", [])),
            "current_case_count": len(current.get("cases", [])),
        },
        "case_counts": {
            "requested": len(results), "native_identity_source_closed": len(closed),
            "source_incomplete": len(incomplete), "source_binding_rejected": len(rejected),
        },
        "native_id_count": len(ids),
        "family_counts": family_counts,
        "cases": results,
        "claim_boundary": {
            "native_identity": "CLOSED only for case rows marked NATIVE_IDENTITY_SOURCE_CLOSED: official PartVTKOut Idp/PartOut/Motive rows map to typed conversion MK/type blocks and native mass",
            "source_gaps": "Case-scoped UNKNOWN; no all-118 credit is implied by the producer impact ledger",
            "conversion_initial_filter": "Producer initial-exclusion ledger is reported only; converter implementation remains UNKNOWN",
            "physical_fate": "UNKNOWN; native numerical exclusion is not legal spill or physical outflow",
            "dynamical_impact": "UNKNOWN; missing mass is a source-visible lower bound only",
            "event_time": "UNKNOWN beyond saved first-missing bracket",
            "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        },
        "read_policy": {
            "scientific_json_opened": True, "scan_receipts_opened": True,
            "conversion_reports_opened": True, "decoder_receipts_opened": True,
            "native_csv_opened": True, "runparts_csv_opened": True,
            "raw_partout_hashed_only": True,
            "trajectory_h5_opened": False, "part_frames_opened": False,
            "solver_started": False, "decoder_started": False,
            "cfd_or_model_run": False,
        },
    }
    if output is not None:
        V1.atomic_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"preserve existing output: {args.output}")
    result = audit(args.manifest, args.output)
    print(json.dumps({"status": result["status"], **result["case_counts"], "native_ids": result["native_id_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
