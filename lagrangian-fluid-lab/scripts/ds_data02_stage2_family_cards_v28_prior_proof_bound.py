#!/usr/bin/env python3
"""Bind the closed field proofs and GenCase sentinels to new family cards.

This is a metadata-only overlay.  It consumes the bounded ROOT412 census and
its 56 already closed field verification files, plus the nine ROOT700--708
owner/grid proofs.  Every referenced JSON is checked by path and SHA before
being recorded.  No H5, BI4, VTK, CSV, or generated payload is opened.  The
result deliberately keeps units, material authority, physical fate, event
labels, portability, and QI/QN/QE UNKNOWN.

The previous catalog and cards are immutable inputs.  The output is a new
directory with seven cards and an index; it does not turn the field scans or
GenCase sentinels into a scientific product.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.seven-family-card-prior-proof-bound.v28"
ROOT_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
FIELD_STATUS = "VERIFIED_ACTUAL_PRODUCTION_H5_FIELD_SCAN_METADATA_CLOSURE_NO_PHYSICAL_Q"
INDEPENDENT_SCHEMA = "ds02.stage2.verify-scientific-field-h5-audit.v5"
GENCASE_STATUS = "VERIFIED_ACTUAL_OWNER_GRID_GENCASE_PRODUCTS_NO_SCIENTIFIC_Q"
GENCASE_PROOF_SCHEMA = ROOT_PROOF_SCHEMA
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_PROOF_BYTES = 512 * 1024


class PriorProofError(ValueError):
    pass


def _fail(message: str) -> None:
    raise PriorProofError(message)


def _regular(path: Path, label: str, limit: int) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        _fail(f"{label} must be an absolute regular non-symlink file: {path}")
    if path.stat().st_size > limit:
        _fail(f"{label} exceeds the bounded metadata limit: {path}")


def _signature(path: Path) -> tuple[int, int, int, int, int]:
    value = path.stat()
    return (int(value.st_dev), int(value.st_ino), int(value.st_size),
            int(value.st_mtime_ns), int(value.st_ctime_ns))


def _sha(path: Path, label: str, limit: int = MAX_JSON_BYTES) -> str:
    _regular(path, label, limit)
    before = _signature(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if before != _signature(path):
        _fail(f"{label} changed while being hashed: {path}")
    return digest.hexdigest()


def _read(path: Path, label: str, limit: int = MAX_JSON_BYTES) -> dict[str, Any]:
    _regular(path, label, limit)
    before = _signature(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not bounded JSON: {error}")
    if before != _signature(path):
        _fail(f"{label} changed while being read: {path}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        _fail(f"{label} is not a lowercase SHA-256")
    return value


def _absolute(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        _fail(f"{label} is not an absolute path")
    return Path(value)


def _reference_field(container: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    """Verify the two reference ABIs used by actual ROOT proofs."""
    value = container.get(key)
    if isinstance(value, Mapping):
        path = _absolute(value.get("path"), f"{label}.{key}.path")
        expected = _hex(value.get("sha256"), f"{label}.{key}.sha256")
    else:
        path = _absolute(value, f"{label}.{key}")
        expected = _hex(container.get(f"{key}_sha256"), f"{label}.{key}_sha256")
    # These are proof/request/report/manifest JSON references.  Refuse a
    # payload-looking suffix rather than silently hashing it as metadata.
    if path.suffix.lower() not in {".json", ".jsonl"}:
        _fail(f"{label}.{key} is not a JSON metadata reference: {path}")
    actual = _sha(path, f"{label}.{key}")
    if actual != expected:
        _fail(f"{label}.{key} SHA differs")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def _unknown_qualification(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or any(value.get(key) != "UNKNOWN" for key in UNKNOWN):
        _fail(f"{label} promotes qualification")


def _verify_independent(path: Path, label: str) -> dict[str, Any]:
    value = _read(path, label)
    if value.get("schema") != INDEPENDENT_SCHEMA or value.get("status") != "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT":
        _fail(f"{label} is not the closed independent metadata verifier")
    if value.get("scientific_payload_content_read_by_verifier") is not False or \
            value.get("source_content_read_by_verifier") is not False:
        _fail(f"{label} reports content reads")
    if value.get("production_eligible") is not False or value.get("scientific_credit") not in (0, None):
        _fail(f"{label} carries scientific eligibility")
    _unknown_qualification(value.get("scientific_qualification"), label)
    return value


def _verify_field_proof(path: Path, expected_sha: str, expected_family: str,
                        expected_case: str) -> dict[str, Any]:
    actual_sha = _sha(path, f"field proof {path.name}", MAX_PROOF_BYTES)
    if actual_sha != expected_sha:
        _fail(f"field proof SHA differs from census: {path}")
    value = _read(path, f"field proof {path.name}", MAX_PROOF_BYTES)
    if value.get("schema") != ROOT_PROOF_SCHEMA or value.get("status") != FIELD_STATUS:
        _fail(f"{path.name} is not a closed field proof")
    if value.get("H5_BI4_read_by_root") is not False or value.get("root_h5_payload_content_read") is not False:
        _fail(f"{path.name} reports a forbidden root payload read")
    if value.get("parent_reservation_released") is not True or value.get("actual_production_h5_scan") is not True:
        _fail(f"{path.name} is not a terminal parent handoff")
    if value.get("scientific_Q_credit") not in (0, None):
        _fail(f"{path.name} carries scientific Q credit")
    _unknown_qualification(value.get("scientific_qualification"), path.name)
    rows = value.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        _fail(f"{path.name} must contain one scoped case verification")
    row = rows[0]
    if row.get("family_id") != expected_family or row.get("physical_case_id") != expected_case:
        _fail(f"{path.name} case row does not match the ROOT412 census")
    if row.get("status") != "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT" or row.get("missing_fields") != []:
        _fail(f"{path.name} case verification is not a closed metadata row")
    refs = {key: _reference_field(value, key, path.name)
            for key in ("request", "receipt", "report", "manifest",
                        "independent_verification", "source_index")}
    independent = _verify_independent(Path(refs["independent_verification"]["path"]),
                                      f"{path.name} independent verification")
    if independent.get("case_count") != 1 or independent.get("cases", [{}])[0].get("physical_case_id") != expected_case:
        _fail(f"{path.name} independent proof case does not match")
    return {
        "proof": {"path": str(path), "sha256": actual_sha, "bytes": path.stat().st_size},
        "family_id": expected_family, "physical_case_id": expected_case,
        "request": refs["request"], "receipt": refs["receipt"], "report": refs["report"],
        "manifest": refs["manifest"], "independent_verification": refs["independent_verification"],
        "source_index": refs["source_index"], "scientific_Q_credit": 0,
        "qualification": dict(UNKNOWN), "physical_authority": "UNKNOWN",
        "portable_replay": "NOT_CLAIMED", "active_fields": row.get("active_finite_status"),
        "initial_mass_status": row.get("initial_mass_status"),
    }


def _verify_gencase(path: Path) -> dict[str, Any]:
    actual_sha = _sha(path, f"GenCase proof {path.name}", MAX_PROOF_BYTES)
    value = _read(path, f"GenCase proof {path.name}", MAX_PROOF_BYTES)
    if value.get("schema") != GENCASE_PROOF_SCHEMA or value.get("status") != GENCASE_STATUS:
        _fail(f"{path.name} is not a closed GenCase proof")
    if value.get("H5_BI4_read_by_root") is not False or value.get("generated_native_vtk_payload_read_by_root") is not False:
        _fail(f"{path.name} reports a forbidden payload read")
    if value.get("parent_reservation_released") is not True or value.get("scientific_Q_credit") not in (0, None):
        _fail(f"{path.name} is not a no-Q terminal proof")
    _unknown_qualification(value.get("scientific_qualification"), path.name)
    family = str(value.get("physical_case_id", "")).split("_", 1)[0]
    if family not in FAMILIES:
        _fail(f"{path.name} has no family-bound physical case")
    refs = {key: _reference_field(value, key, path.name) for key in ("request", "receipt")}
    return {
        "proof": {"path": str(path), "sha256": actual_sha, "bytes": path.stat().st_size},
        "family_id": family, "physical_case_id": value["physical_case_id"],
        "sentinel_id": value.get("sentinel_id"), "grid_label": value.get("grid_label"),
        "request": refs["request"], "receipt": refs["receipt"],
        "scientific_Q_credit": 0, "qualification": dict(UNKNOWN),
        "physical_authority": "UNKNOWN", "portable_replay": "NOT_CLAIMED",
        "products_read": False,
    }


def _verify_base_catalog(path: Path) -> dict[str, Any]:
    value = _read(path, "base namespace330 catalog")
    if value.get("case_count") != 336 or set(value.get("cards", {})) != set(FAMILIES):
        _fail("base catalog is not the 336-case seven-family catalog")
    _unknown_qualification(value.get("qualification"), "base catalog")
    boundary = value.get("claim_boundary")
    if not isinstance(boundary, Mapping) or boundary.get("split_safe") is not False or boundary.get("qualification_credit") != "NONE":
        _fail("base catalog claim boundary is not conservative")
    case_ids: set[str] = set()
    for row in value.get("cases", []):
        if not isinstance(row, Mapping) or row.get("family_id") not in FAMILIES:
            _fail("base catalog case row is malformed")
        if row.get("canonical_case_id") is None or row.get("canonical_case_id") != row.get("physical_case_id"):
            # The one historical F2 alias is deliberately absent from this
            # canonical set; it must not be promoted by the overlay.
            continue
        case_ids.add(str(row["physical_case_id"]))
    if len(case_ids) != 335:
        _fail(f"base catalog canonical case count differs: {len(case_ids)}")
    return value


def _verify_census(path: Path, base_cases: set[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    census = _read(path, "ROOT412 closed census", 512 * 1024)
    if census.get("schema") != "ds02.stage2.closed-actual-field-census.v2" or census.get("status") != "EXACT_ACTUAL_FIELD_PROOFS_CLOSED_NOT_SCIENTIFIC_QUALIFICATION":
        _fail("ROOT412 census schema/status differs")
    if census.get("root_payload_content_read") is not False or census.get("scientific_Q_credit") not in (0, None):
        _fail("ROOT412 census carries forbidden read or Q credit")
    rows = census.get("base_actual_rows", []) + census.get("additional_actual_rows", [])
    if not isinstance(rows, list) or len(rows) != 56 or census.get("actual_canonical_field_cases_total") != 56:
        _fail("ROOT412 census does not contain exactly 56 actual field proofs")
    seen: set[tuple[str, str]] = set()
    evidence: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("family_id") not in FAMILIES:
            _fail("ROOT412 census row is malformed")
        family, case = str(row["family_id"]), str(row["physical_case_id"])
        if (family, case) in seen or case not in base_cases:
            _fail(f"ROOT412 field identity is duplicate or outside the canonical catalog: {case}")
        seen.add((family, case))
        proof = row.get("actual_proof")
        if not isinstance(proof, Mapping):
            _fail(f"ROOT412 field row has no actual proof: {case}")
        evidence.append(_verify_field_proof(_absolute(proof.get("path"), f"census.{case}.proof"),
                                            _hex(proof.get("sha256"), f"census.{case}.proof.sha256"),
                                            family, case))
    return census, evidence


def build(*, base_catalog: Path, census: Path, gencase_proofs: Sequence[Path],
          output_dir: Path) -> dict[str, Any]:
    if output_dir.exists() or output_dir.is_symlink():
        _fail(f"refusing to overwrite output directory: {output_dir}")
    catalog = _verify_base_catalog(base_catalog)
    base_cases = {str(row["physical_case_id"]) for row in catalog.get("cases", [])
                  if isinstance(row, Mapping) and row.get("canonical_case_id") == row.get("physical_case_id")}
    census_value, field_evidence = _verify_census(census, base_cases)
    if len(gencase_proofs) != 9:
        _fail("the ROOT700--708 supplementary proof set must contain exactly nine files")
    gencase = [_verify_gencase(path) for path in gencase_proofs]
    output_dir.mkdir(parents=True)
    cards: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        scoped_fields = [row for row in field_evidence if row["family_id"] == family]
        scoped_gencase = [row for row in gencase if row["family_id"] == family]
        card = {
            "schema": "ds02.stage2.family-card.v28-prior-proof-bound",
            "status": "ACTUAL_METADATA_ONLY_NO_SCIENTIFIC_Q",
            "family_id": family,
            "base_catalog": {"path": str(base_catalog), "sha256": _sha(base_catalog, "base catalog")},
            "prior_field_proofs": scoped_fields,
            "supplementary_gencase_proofs": scoped_gencase,
            "claim_boundary": {
                "production_scientific_Q_credit": 0, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                "units_material_physical_authority": "UNKNOWN", "physical_fate": "UNKNOWN",
                "dynamics": "UNKNOWN", "event_labels": "UNKNOWN", "labels_accepted": False,
                "portable_replay_verified": False, "split_safe": False,
            },
            "gaps": [
                "field proofs are metadata-only H5 audits and do not establish physical units or material authority",
                "GenCase products are supplementary owner/grid sentinels, not canonical row substitutions",
                "event/material/fate/dynamics, portable replay, and all qualification remain UNKNOWN",
            ],
        }
        card_path = output_dir / f"{family}-family-card-v28.json"
        card_path.write_text(json.dumps(card, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        cards[family] = {"path": str(card_path), "sha256": _sha(card_path, f"generated {family} card")}
    index = {
        "schema": SCHEMA,
        "status": "ACTUAL_METADATA_PRIOR_PROOF_BOUND_NO_SCIENTIFIC_Q",
        "base_catalog": {"path": str(base_catalog), "sha256": _sha(base_catalog, "base catalog")},
        "census": {"path": str(census), "sha256": _sha(census, "ROOT412 census")},
        "actual_canonical_field_proof_count": len(field_evidence),
        "supplementary_gencase_proof_count": len(gencase),
        "family_proof_counts": {family: sum(row["family_id"] == family for row in field_evidence) for family in FAMILIES},
        "family_gencase_counts": {family: sum(row["family_id"] == family for row in gencase) for family in FAMILIES},
        "family_cards": cards, "card_count": 7,
        "census_claims": {"actual_canonical_field_cases_total": census_value["actual_canonical_field_cases_total"],
                          "alias_unknown_count": census_value.get("alias_unknown_count"),
                          "canonical_unscanned_count": census_value.get("canonical_unscanned_count")},
        "claim_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                           "production_scientific_Q_credit": 0, "split_safe": False,
                           "portable_replay_verified": False},
        "read_policy": {"bounded_json_only": True, "scientific_payload_content_read": False,
                        "H5_BI4_VTK_CSV_JSONL_payloads_read": False, "ledger_mutated": False,
                        "launch_performed": False},
    }
    index_path = output_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    index["index"] = {"path": str(index_path), "sha256": _sha(index_path, "generated V28 index")}
    return index


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-catalog", type=Path, required=True)
    parser.add_argument("--census", type=Path, required=True)
    parser.add_argument("--gencase-proof", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(base_catalog=args.base_catalog, census=args.census,
                       gencase_proofs=args.gencase_proof, output_dir=args.output_dir)
        print(json.dumps({"schema": result["schema"], "status": result["status"],
                          "actual_canonical_field_proof_count": result["actual_canonical_field_proof_count"],
                          "supplementary_gencase_proof_count": result["supplementary_gencase_proof_count"],
                          "index": result["index"]}, sort_keys=True))
        return 0
    except (PriorProofError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"family cards v28: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
