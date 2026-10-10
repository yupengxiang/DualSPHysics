#!/usr/bin/env python3
"""Add actual ROOT363--370 field handoffs to an immutable card overlay.

The V26 seven-pilot overlay remains byte-for-byte untouched.  V27 reads only
the bounded root verification JSON and its bounded independent/report/manifest
references, then writes a new overlay and seven new card files.  The field
proofs are metadata-only and retain QI/QN/QE, material authority, and physical
equivalence as UNKNOWN.  This is an evidence increment, not a seven-family
scientific product or portable replay proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.seven-family-card-actual-field-increment.v27"
ROOT_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
INDEPENDENT_SCHEMA = "ds02.stage2.verify-scientific-field-h5-audit.v5"
MAX_JSON_BYTES = 512 * 1024
MAX_REFERENCE_BYTES = 4 * 1024 * 1024
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
HEX64 = re.compile(r"^[0-9a-f]{64}$")
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class FieldIncrementError(ValueError):
    pass


def _fail(message: str) -> None:
    raise FieldIncrementError(message)


def _regular(path: Path, label: str, maximum: int) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        _fail(f"{label} must be an absolute regular non-symlink file: {path}")
    if path.stat().st_size > maximum:
        _fail(f"{label} exceeds bounded metadata limit: {path}")


def _sha(path: Path, label: str, maximum: int = MAX_JSON_BYTES) -> str:
    _regular(path, label, maximum)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path, label: str, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
    _regular(path, label, maximum)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not bounded JSON: {error}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        _fail(f"{label} is not a lowercase SHA-256")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        _fail(f"{label} is not an absolute path")
    return Path(value)


def _reference(container: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, Mapping):
        _fail(f"{label} lacks {key}")
    path = _path(value.get("path"), f"{label}.{key}.path")
    expected = _hex(value.get("sha256"), f"{label}.{key}.sha256")
    actual = _sha(path, f"{label}.{key}", MAX_REFERENCE_BYTES)
    if actual != expected:
        _fail(f"{label}.{key} SHA differs")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def _reference_field(container: Mapping[str, Any], key: str, label: str) -> dict[str, Any]:
    """Accept the real ROOT proof's path + sibling ``*_sha256`` ABI.

    Small manufactured fixtures may use the nested ``{"path", "sha256"}``
    shape; the actual ROOT363--370 verification uses top-level path strings
    and separately named digest fields.  Both forms are strict and hash the
    referenced bounded metadata file before admission.
    """
    value = container.get(key)
    if isinstance(value, Mapping):
        return _reference(container, key, label)
    path = _path(value, f"{label}.{key}")
    digest_key = f"{key}_sha256"
    expected = _hex(container.get(digest_key), f"{label}.{digest_key}")
    actual = _sha(path, f"{label}.{key}", MAX_REFERENCE_BYTES)
    if actual != expected:
        _fail(f"{label}.{key} SHA differs")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def _verify_base(base_path: Path) -> dict[str, Any]:
    value = _read(base_path, "base family-card index")
    if value.get("card_count") != 7 or set(value.get("family_cards", {})) != set(FAMILIES):
        _fail("base overlay does not contain exactly seven family cards")
    for family in FAMILIES:
        ref = value["family_cards"][family]
        if not isinstance(ref, Mapping):
            _fail(f"base card reference is malformed for {family}")
        card = _read(_path(ref.get("path"), f"base {family} card"), f"base {family} card")
        if card.get("family_id") != family:
            _fail(f"base card family differs for {family}")
        boundary = card.get("claim_boundary")
        if not isinstance(boundary, Mapping) or any(boundary.get(key) != "UNKNOWN" for key in UNKNOWN):
            _fail(f"base card promotes qualification for {family}")
    return value


def _verify_proof(path: Path) -> dict[str, Any]:
    value = _read(path, f"ROOT field proof {path.name}")
    if value.get("schema") != ROOT_PROOF_SCHEMA:
        _fail(f"{path.name} has the wrong root verification schema")
    if value.get("status") != "VERIFIED_ACTUAL_PRODUCTION_H5_FIELD_SCAN_METADATA_CLOSURE_NO_PHYSICAL_Q":
        _fail(f"{path.name} is not the closed metadata-only field status")
    if value.get("H5_BI4_read_by_root") is not False or value.get("root_h5_payload_content_read") is not False:
        _fail(f"{path.name} reports a forbidden root payload read")
    if value.get("parent_reservation_released") is not True or value.get("actual_production_h5_scan") is not True:
        _fail(f"{path.name} is not a closed actual handoff")
    if value.get("scientific_Q_credit") not in (None, 0):
        _fail(f"{path.name} carries scientific Q credit")
    qualification = value.get("scientific_qualification")
    if not isinstance(qualification, Mapping) or any(qualification.get(key) != "UNKNOWN" for key in UNKNOWN):
        _fail(f"{path.name} promotes qualification")
    rows = value.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        _fail(f"{path.name} must contain one scoped case row")
    row = rows[0]
    family = row.get("family_id")
    case_id = row.get("physical_case_id")
    if family not in FAMILIES or not isinstance(case_id, str) or not case_id:
        _fail(f"{path.name} case row is not family/case bound")
    references = {
        key: _reference_field(value, key, path.name)
        for key in ("request", "receipt", "report", "manifest", "independent_verification", "source_index")
    }
    independent = _read(_path(references["independent_verification"]["path"],
                               f"{path.name}.independent_verification.path"),
                        f"{path.name} independent verification")
    if independent.get("schema") != INDEPENDENT_SCHEMA or independent.get("status") != "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT":
        _fail(f"{path.name} independent verification status differs")
    if independent.get("scientific_payload_content_read_by_verifier") is not False:
        _fail(f"{path.name} independent verifier read scientific payload")
    return {
        "root": path.name,
        "ref": {"path": str(path), "sha256": _sha(path, f"{path.name} proof"), "bytes": path.stat().st_size},
        "family_id": family, "physical_case_id": case_id,
        "request": references["request"], "receipt": references["receipt"],
        "report": references["report"], "manifest": references["manifest"],
        "independent_verification": references["independent_verification"],
        "source_index": references["source_index"],
        "scientific_credit": 0, "qualification": dict(UNKNOWN),
        "physical_authority": "UNKNOWN", "portable_replay": "NOT_CLAIMED",
        "active_fields": row.get("active_finite_status"),
        "initial_mass_status": row.get("initial_mass_status"),
    }


def build(*, base_index: Path, proofs: Sequence[Path], output_dir: Path,
          previous_field_count: int = 15) -> dict[str, Any]:
    if output_dir.exists() or output_dir.is_symlink():
        _fail(f"refusing to overwrite field increment directory: {output_dir}")
    if isinstance(previous_field_count, bool) or previous_field_count < 0:
        _fail("previous_field_count must be non-negative")
    base = _verify_base(base_index)
    if len(proofs) != 8:
        _fail("ROOT363--370 increment requires exactly eight proofs")
    evidence = [_verify_proof(path) for path in proofs]
    identities = {(item["family_id"], item["physical_case_id"]) for item in evidence}
    if len(identities) != len(evidence):
        _fail("field increment repeats a family/case identity")
    output_dir.mkdir(parents=True)
    base_ref = {"path": str(base_index), "sha256": _sha(base_index, "base family-card index")}
    cards: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        base_ref_card = base["family_cards"][family]
        base_card_path = _path(base_ref_card["path"], f"base {family} card")
        base_card = _read(base_card_path, f"base {family} card")
        scoped = [item for item in evidence if item["family_id"] == family]
        card = {
            "schema": "ds02.stage2.family-card.v27-actual-field-increment",
            "status": "ACTUAL_METADATA_ONLY_NO_SCIENTIFIC_Q",
            "family_id": family,
            "base_card": {"path": str(base_card_path), "sha256": _sha(base_card_path, f"base {family} card")},
            "actual_field_increment": scoped,
            "claim_boundary": {
                "production_scientific_Q_credit": 0, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                "units_material_physical_authority": "UNKNOWN", "physical_fate": "UNKNOWN",
                "dynamics": "UNKNOWN", "labels_accepted": False,
                "portable_replay_verified": False, "case_identity_promotion": False,
            },
            "gaps": [
                "field audit is metadata-only and does not establish physical units/material authority",
                "Q, physical equivalence, fate, dynamics, and portable replay remain UNKNOWN",
            ],
        }
        card_path = output_dir / f"{family}-card.json"
        card_path.write_text(json.dumps(card, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        cards[family] = {"path": str(card_path), "sha256": _sha(card_path, f"generated {family} card")}
    output = {
        "schema": SCHEMA,
        "status": "ACTUAL_METADATA_FIELD_INCREMENT_NO_SCIENTIFIC_Q",
        "base_overlay": base_ref,
        "previous_field_count": previous_field_count,
        "increment_field_count": len(evidence),
        "actual_field_count": previous_field_count + len(evidence),
        "proofs": evidence,
        "family_cards": cards,
        "card_count": 7,
        "claim_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                           "production_scientific_Q_credit": 0,
                           "portable_replay_verified": False},
        "read_policy": {"bounded_json_only": True, "scientific_payload_content_read": False,
                        "ledger_mutated": False, "launch_performed": False},
    }
    index_path = output_dir / "index.json"
    index_path.write_text(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    output["index"] = {"path": str(index_path), "sha256": _sha(index_path, "generated field increment")}
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-index", required=True, type=Path)
    parser.add_argument("--proof", action="append", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--previous-field-count", type=int, default=15)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = build(base_index=args.base_index, proofs=args.proof, output_dir=args.output_dir,
                      previous_field_count=args.previous_field_count)
        print(json.dumps({"schema": value["schema"], "status": value["status"],
                          "index": value["index"], "actual_field_count": value["actual_field_count"]},
                         sort_keys=True, ensure_ascii=True))
        return 0
    except (FieldIncrementError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"family field increment v27: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
