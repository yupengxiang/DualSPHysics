#!/usr/bin/env python3
"""Build a conservative family-card overlay from actual small proof records.

This is an additive evidence directory for the seven ROOT346--352 field
pilots.  It also records the current shared native-cause (111 bound / 64
saved-frame joins), ROOT313 selected-mass diagnostics, ROOT316 geometry
sentinels, and the ROOT353 failed scalar attempt.  Those shared records are
kept as scoped evidence; they are never copied into every family card as if
they were per-case labels.

The builder reads only bounded JSON proof records.  It does not open H5,
BI4, raw arrays, typed payloads, solver logs, or the mutable ledger.  Its
cards remain metadata-only, with QI/QN/QE and physical authority UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-handoff-v2-actual-report.v1"
OVERLAY_SCHEMA = "ds02.stage2.seven-family-card-actual-evidence-overlay.v1"
CARD_SCHEMA = "ds02.stage2.family-card.v26-actual-evidence-overlay"
MAX_JSON_BYTES = 256 * 1024
MAX_PILOT_REPORT_BYTES = 2 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FAMILIES = tuple(f"F{i}" for i in range(1, 8))


class FamilyOverlayError(ValueError):
    """Actual proof overlay is missing, stale, or over-promoted."""


def _fail(message: str) -> None:
    raise FamilyOverlayError(message)


def _regular(path: Path, label: str, maximum: int) -> None:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        _fail(f"{label} must be an absolute regular non-symlink file: {path}")
    try:
        size = path.stat().st_size
    except OSError as exc:
        _fail(f"cannot stat {label}: {exc}")
    if size > maximum:
        _fail(f"{label} exceeds bounded metadata limit: {path} ({size} bytes)")


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
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not bounded JSON: {exc}")
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


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(f"{label} is not finite")
    return float(value)


def _proof_ref(path: Path, label: str) -> dict[str, Any]:
    value = _read(path, label)
    return {"path": str(path), "sha256": _sha(path, label), "schema": value.get("schema"), "status": value.get("status")}


def _verify_pilot_report(path: Path) -> dict[str, Any]:
    report = _read(path, "actual seven-pilot report", MAX_PILOT_REPORT_BYTES)
    if report.get("schema") != REPORT_SCHEMA:
        _fail("pilot report schema differs")
    if report.get("status") != "ACTUAL_FIELD_PILOTS_METADATA_VERIFIED_NO_SCIENTIFIC_Q":
        _fail("pilot report is not the actual metadata-only status")
    if report.get("pilot_count") != 7:
        _fail("pilot report does not contain seven pilots")
    boundary = report.get("claim_boundary")
    if not isinstance(boundary, dict) or boundary.get("production_scientific_Q_credit") != 0:
        _fail("pilot report carries scientific credit")
    if any(boundary.get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
        _fail("pilot report has promoted Q status")
    cards = report.get("family_card_evidence")
    if not isinstance(cards, dict) or set(cards) != set(FAMILIES):
        _fail("pilot report does not cover exactly F1--F7")
    for family in FAMILIES:
        item = cards[family]
        if not isinstance(item, dict):
            _fail(f"pilot report card evidence is malformed for {family}")
        proof = item.get("root_proof")
        if not isinstance(proof, dict):
            _fail(f"pilot report lacks root proof for {family}")
        proof_path = _absolute(proof.get("path"), f"pilot report {family} root proof path")
        expected_sha = _hex(proof.get("sha256"), f"pilot report {family} root proof SHA")
        if _sha(proof_path, f"pilot report {family} root proof") != expected_sha:
            _fail(f"pilot report root proof SHA differs for {family}")
        row = proof.get("case_verification")
        if not isinstance(row, dict) or row.get("family_id") != family:
            _fail(f"pilot report selected row is not bound to {family}")
    return report


def _verify_native_causes(path: Path) -> dict[str, Any]:
    value = _read(path, "native cause overlay")
    if value.get("schema") != "ds02.stage2.original118-native-cause-actual-overlay.v1":
        _fail("native cause overlay schema differs")
    if value.get("status") != "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS":
        _fail("native cause overlay is not verified")
    if value.get("physical_case_count") != 118 or value.get("native_cause_bound_per_fluid_id_cases") != 111 or value.get("actual_typed_native_saved_frame_join_physical_cases") != 64:
        _fail("native cause overlay counts differ from actual scope")
    if value.get("cause_not_located_after_completed_scan_cases") != 7:
        _fail("native cause unresolved count differs from actual scope")
    if value.get("root_H5_native_JSONL_content_read") is not False:
        _fail("native cause overlay reports forbidden payload read")
    boundary = value.get("qualification_boundary")
    if not isinstance(boundary, dict) or any(boundary.get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
        _fail("native cause overlay qualification is promoted")
    return {
        "ref": _proof_ref(path, "native cause overlay"),
        "physical_case_count": 118,
        "native_cause_bound_per_fluid_id_cases": 111,
        "cause_not_located_after_completed_scan_cases": 7,
        "saved_frame_join_physical_cases": 64,
        "case_specific_binding": False,
        "scientific_credit": 0,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _verify_mass(path: Path) -> dict[str, Any]:
    value = _read(path, "ROOT313 mass proof")
    if value.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(value.get("status", "")).startswith("VERIFIED_ACTUAL_ROOT313_NATIVE_TYPED_MASS_IMPACT"):
        _fail("ROOT313 mass proof schema/status differs")
    rows = value.get("case_verifications")
    counts = value.get("verified_counts")
    if not isinstance(rows, list) or len(rows) != 17 or not isinstance(counts, dict):
        _fail("ROOT313 mass proof does not contain 17 case rows")
    if counts.get("cases") != 17 or counts.get("completed") != 17 or counts.get("failed") != 0:
        _fail("ROOT313 mass proof terminal counts differ")
    if value.get("new_native_cause_credit") != 0 or value.get("new_native_join_credit") != 0 or value.get("scientific_Q_credit") not in (None, 0):
        _fail("ROOT313 mass proof carries scientific credit")
    if value.get("H5_BI4_read_by_root") is not False or value.get("root_deferred_payload_content_read") is not False:
        _fail("ROOT313 mass proof reports forbidden payload read")
    if value.get("parent_reservation_released") is not True or value.get("outer_unit_result") != "success" or value.get("guarded_receipt_status") != "completed":
        _fail("ROOT313 mass proof is not a closed terminal record")
    case_ids = sorted(str(row.get("physical_case_id")) for row in rows if isinstance(row, dict))
    if len(case_ids) != 17 or any(not case_id or case_id == "None" for case_id in case_ids):
        _fail("ROOT313 mass proof has unbound case rows")
    return {
        "ref": _proof_ref(path, "ROOT313 mass proof"),
        "case_count": 17,
        "case_ids": case_ids,
        "scope": value.get("scientific_mass_scope"),
        "physical_fate_flux_dynamics": value.get("physical_fate_flux_dynamics"),
        "scientific_credit": 0,
        "qualification": dict(value.get("scientific_qualification") or {}),
    }


def _verify_geometry(path: Path) -> dict[str, Any]:
    value = _read(path, "ROOT316 geometry proof")
    if value.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(value.get("status", "")).startswith("VERIFIED_ACTUAL_ROOT316_FOUR_SENTINEL"):
        _fail("ROOT316 geometry proof schema/status differs")
    rows = value.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != 4:
        _fail("ROOT316 geometry proof does not contain four sentinels")
    sentinel_ids = sorted(row.get("sentinel_id") for row in rows if isinstance(row, dict))
    if sentinel_ids != ["F2-S2", "F4-S2", "F5-S2", "F7-S1"]:
        _fail("ROOT316 geometry sentinel set differs")
    if value.get("continuous_owner_credit") != 0 or value.get("physical_penetration_credit") != 0 or value.get("scientific_Q_credit") != 0:
        _fail("ROOT316 geometry proof carries scientific credit")
    if value.get("H5_BI4_read_by_root") is not False or value.get("root_deferred_payload_content_read") is not False:
        _fail("ROOT316 geometry proof reports forbidden payload read")
    if value.get("parent_reservation_released") is not True or value.get("outer_unit_result") != "success" or value.get("guarded_receipt_status") != "completed":
        _fail("ROOT316 geometry proof is not a closed terminal record")
    return {
        "ref": _proof_ref(path, "ROOT316 geometry proof"),
        "sentinel_count": 4,
        "sentinel_ids": sentinel_ids,
        "case_specific_binding": True,
        "scientific_credit": 0,
        "qualification": dict(value.get("scientific_qualification") or {}),
    }


def _verify_failure(path: Path) -> dict[str, Any]:
    value = _read(path, "ROOT353 failure proof")
    if value.get("schema") != "ds02.stage2.root353-failed-native-scalar-metadata-closure.v1":
        _fail("ROOT353 failure proof schema differs")
    if value.get("status") != "VERIFIED_FAILED_PARENT_FULL_CPU_NATIVE_PRODUCER_PRESERVED_NO_CHAIN_CREDIT":
        _fail("ROOT353 failure proof status differs")
    if value.get("scientific_Q_credit") != 0 or value.get("reservation_released") is not True or value.get("repeat_cpu_fee_idempotent") is not True or value.get("unit_cgroup_empty") is not True:
        _fail("ROOT353 failure proof has unsafe terminal/accounting state")
    if value.get("root_payload_content_read") is not False:
        _fail("ROOT353 failure proof reports forbidden payload read")
    return {
        "ref": _proof_ref(path, "ROOT353 failure proof"),
        "status": value["status"],
        "failure": value.get("failure"),
        "chain_credit": 0,
        "scientific_credit": 0,
        "preserved_successful_producer_scope": value.get("preserved_successful_producer_scope"),
    }


def build(
    *,
    pilot_report: Path,
    native_causes: Path,
    mass_proof: Path,
    geometry_proof: Path,
    failure_proof: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Write one global evidence report and seven conservative card files."""
    if output_dir.exists() or output_dir.is_symlink():
        _fail(f"refusing to overwrite family overlay directory: {output_dir}")
    pilot = _verify_pilot_report(pilot_report)
    cause = _verify_native_causes(native_causes)
    mass = _verify_mass(mass_proof)
    geometry = _verify_geometry(geometry_proof)
    failure = _verify_failure(failure_proof)
    output_dir.mkdir(parents=True)
    shared = {
        "schema": OVERLAY_SCHEMA,
        "status": "ACTUAL_METADATA_EVIDENCE_OVERLAY_NO_SCIENTIFIC_Q",
        "pilot_report": {"path": str(pilot_report), "sha256": _sha(pilot_report, "pilot report", MAX_PILOT_REPORT_BYTES)},
        "source_index": pilot["source_index"],
        "native_cause_scope": cause,
        "selected_mass_scope": mass,
        "geometry_scope": geometry,
        "failed_native_scope": failure,
        "claim_boundary": {
            "development_only": True,
            "production_scientific_Q_credit": 0,
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "units_material_physical_authority": "UNKNOWN",
            "physical_fate": "UNKNOWN", "dynamics": "UNKNOWN",
            "labels_accepted": False, "portable_replay_verified": False,
            "case_identity_promotion": False,
        },
        "read_policy": {
            "bounded_json_only": True,
            "h5_bi4_raw_typed_payload_opened": False,
            "solver_launched": False,
            "ledger_mutated": False,
        },
        "scope_notes": [
            "ROOT346--352 are exact per-case metadata-only field pilot records.",
            "The 111-cause/64-join record is a shared original118 scope and is not attached to every family card.",
            "ROOT313 selected mass rows and ROOT316 geometry sentinels are attached only where their exact rows/sentinels match.",
            "ROOT353 is a preserved failed scalar attempt and grants no chain or scientific credit.",
            "The seven pilots do not complete the remaining current cases or the seven-family product.",
        ],
    }
    shared_path = output_dir / "actual-evidence-overlay.json"
    shared_path.write_text(json.dumps(shared, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    shared_ref = {"path": str(shared_path), "sha256": _sha(shared_path, "generated overlay")}
    cards: dict[str, dict[str, Any]] = {}
    for family in FAMILIES:
        pilot_card = pilot["family_card_evidence"][family]
        mass_ids = [case_id for case_id in mass["case_ids"] if case_id.startswith(family + "_")]
        sentinel_ids = [sid for sid in geometry["sentinel_ids"] if sid.startswith(family + "-")]
        card = {
            "schema": CARD_SCHEMA,
            "status": "ACTUAL_METADATA_ONLY_NO_SCIENTIFIC_Q",
            "family_id": family,
            "overlay": shared_ref,
            "pilot_evidence": pilot_card,
            "scoped_native_mass_rows": mass_ids,
            "scoped_geometry_sentinels": sentinel_ids,
            "shared_native_cause_scope": {
                "physical_case_count": 118,
                "native_cause_bound_per_fluid_id_cases": 111,
                "saved_frame_join_physical_cases": 64,
                "attached_to_this_card": False,
            },
            "failed_native_scalar_scope": {
                "root": 353,
                "attached_as_failure_provenance_only": True,
                "scientific_credit": 0,
            },
            "claim_boundary": shared["claim_boundary"],
            "gaps": [
                "pilot verifies metadata/finite-field closure only; physical units and material authority remain UNKNOWN",
                "QI/QN/QE and physical fate/dynamics remain UNKNOWN",
                "no canonical identity promotion or portable replay credit",
            ],
        }
        if not mass_ids:
            card["gaps"].append("ROOT313 selected-mass diagnostics have no exact case row for this family")
        if not sentinel_ids:
            card["gaps"].append("ROOT316 geometry diagnostics have no exact sentinel for this family")
        card_path = output_dir / f"{family}-card.json"
        card_path.write_text(json.dumps(card, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        cards[family] = {"path": str(card_path), "sha256": _sha(card_path, f"generated {family} card")}
    index = {
        "schema": OVERLAY_SCHEMA,
        "status": shared["status"],
        "overlay": shared_ref,
        "family_cards": cards,
        "card_count": 7,
        "qualification": shared["claim_boundary"],
        "unknown_boundary": shared["scope_notes"],
    }
    index_path = output_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    index["index"] = {"path": str(index_path), "sha256": _sha(index_path, "generated overlay index")}
    return index


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-report", required=True, type=Path)
    parser.add_argument("--native-causes", required=True, type=Path)
    parser.add_argument("--mass-proof", required=True, type=Path)
    parser.add_argument("--geometry-proof", required=True, type=Path)
    parser.add_argument("--failure-proof", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build(
            pilot_report=args.pilot_report,
            native_causes=args.native_causes,
            mass_proof=args.mass_proof,
            geometry_proof=args.geometry_proof,
            failure_proof=args.failure_proof,
            output_dir=args.output_dir,
        )
    except FamilyOverlayError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result["index"], sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
