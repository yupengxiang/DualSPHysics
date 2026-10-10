#!/usr/bin/env python3
"""Aggregate the seven completed scientific-field pilot handoffs.

The ROOT346--352 handoffs are small terminal records for seven guarded H5
field scans.  This module joins those records into an immutable, family-card
ready evidence report.  It reads only the handoff JSON, the bounded root
verification JSON, and the small source request index.  It never opens a
trajectory H5/BI4/raw/typed payload and it does not reserve resources, launch
workers, or mutate a ledger.

The resulting report is deliberately a metadata qualification boundary.  A
completed worker, finite input checks, and a released reservation establish
the terminal execution evidence, but they do not establish physical units,
material authority, QI/QN/QE, labels, or portable replay.  Those fields stay
UNKNOWN and the report grants zero scientific credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


HANDOFF_SCHEMA = "ds02.stage2.root-actual-scientific-field-pilot-handoff.v1"
ROOT_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
SOURCE_INDEX_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-request-index.v1"
REPORT_SCHEMA = "ds02.stage2.scientific-field-h5-pilot-handoff-v2-actual-report.v1"
REPORT_STATUS = "ACTUAL_FIELD_PILOTS_METADATA_VERIFIED_NO_SCIENTIFIC_Q"

MAX_HANDOFF_BYTES = 64 * 1024
MAX_PROOF_BYTES = 128 * 1024
MAX_SOURCE_INDEX_BYTES = 256 * 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")

PILOTS: tuple[tuple[int, str, str], ...] = (
    (346, "F1", "F1_DUAL_HEAD_340_VX_150_FRESH090_V1"),
    (347, "F2", "F2_STAGE1_FIRST8_OFFSET_OPEN_RIM_RX050_RY014_FILL080"),
    (348, "F3", "F3_TWOAXIS_PITCH1000_AY0540_STAGE1_FIRST24_NEW"),
    (349, "F4", "F4_DROP_gap0p24000_xoffm0p08000_yoff0p04000_uz0p60000"),
    (350, "F5", "F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100"),
    (351, "F6", "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S130_DP025"),
    (352, "F7", "F7_OBSTACLE_QUINTIC_B08_A036P5"),
)


class PilotHandoffV2Error(ValueError):
    """The seven-pilot metadata closure is stale, incomplete, or unsafe."""


def _fail(message: str) -> None:
    raise PilotHandoffV2Error(message)


def _regular(path: Path, label: str, maximum: int) -> Path:
    if not path.is_absolute():
        _fail(f"{label} must be absolute: {path}")
    try:
        stat = path.lstat()
    except OSError as exc:
        _fail(f"{label} is unavailable: {path}: {exc}")
    if path.is_symlink() or not path.is_file():
        _fail(f"{label} must be a regular non-symlink file: {path}")
    if stat.st_size > maximum:
        _fail(f"{label} exceeds bounded metadata limit ({stat.st_size} bytes): {path}")
    return path


def _sha256(path: Path, label: str, maximum: int) -> str:
    _regular(path, label, maximum)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str, maximum: int) -> dict[str, Any]:
    _regular(path, label, maximum)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not valid bounded JSON: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        _fail(f"{label} is not a lowercase SHA-256")
    return value


def _absolute(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        _fail(f"{label} is not an absolute path")
    return Path(value)


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(f"{label} is not finite")
    return float(value)


def _require_bool(value: Any, expected: bool, label: str) -> None:
    if value is not expected:
        _fail(f"{label} must be {expected}")


def _verify_source_index(
    path: Path,
    declared_sha: str,
    expected_path: Path | None,
    expected_sha: str | None,
) -> tuple[dict[str, Any], str]:
    source = _json(path, "pilot source index", MAX_SOURCE_INDEX_BYTES)
    actual_sha = _sha256(path, "pilot source index", MAX_SOURCE_INDEX_BYTES)
    _sha(declared_sha, "handoff source_index.sha256")
    if actual_sha != declared_sha:
        _fail(f"pilot source index SHA differs: declared {declared_sha}, observed {actual_sha}")
    if expected_path is not None and path != expected_path:
        _fail(f"pilot source index path differs from pinned path: {path}")
    if expected_sha is not None and declared_sha != expected_sha:
        _fail("pilot source index SHA differs from pinned SHA")
    if source.get("schema") != SOURCE_INDEX_SCHEMA:
        _fail("pilot source index schema differs")
    if source.get("pilot_count") != 7 or tuple(source.get("families") or ()) != tuple(f for _, f, _ in PILOTS):
        _fail("pilot source index does not describe exactly the seven families")
    boundary = source.get("qualification_boundary")
    if not isinstance(boundary, dict) or boundary.get("scientific_credit") != 0:
        _fail("pilot source index carries scientific credit")
    if any(boundary.get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
        _fail("pilot source index has a promoted qualification")
    policy = source.get("read_policy")
    expected_policy = {
        "metadata_only": True,
        "launch_performed": False,
        "solver_started": False,
        "trajectory_h5_opened": False,
        "trajectory_h5_hashed": False,
        "bi4_opened": False,
    }
    if not isinstance(policy, dict) or any(policy.get(key) is not value for key, value in expected_policy.items()):
        _fail("pilot source index read policy is unsafe")
    return source, actual_sha


def _verify_case_row(
    row: Any,
    family: str,
    case_id: str,
    proof_path: Path,
) -> dict[str, Any]:
    if not isinstance(row, dict):
        _fail(f"{proof_path}: case_verifications row is not an object")
    if row.get("family_id") != family or row.get("physical_case_id") != case_id:
        _fail(f"{proof_path}: selected case row does not match handoff")
    if row.get("status") != "VERIFIED_METADATA_ONLY_NO_SCIENTIFIC_CREDIT":
        _fail(f"{proof_path}: case row is not metadata-only verified")
    if row.get("initial_mass_status") != "PRESENT_FINITE_POSITIVE":
        _fail(f"{proof_path}: initial mass is not explicitly finite and positive")
    if row.get("missing_fields") != []:
        _fail(f"{proof_path}: required fields are missing")
    if row.get("unit_comparison") != "DECLARED_MATCHES_PRODUCER_PROTOCOL":
        _fail(f"{proof_path}: unit comparison is not producer-protocol bounded")
    if row.get("physical_ranges_diagnostic") is not True:
        _fail(f"{proof_path}: physical range diagnostic is absent")
    active = row.get("active_finite_status")
    if active not in {"ALL_ACTIVE_REQUIRED_FIELDS_FINITE", "ACTIVE_TYPE_OR_ROLE_UNKNOWN"}:
        _fail(f"{proof_path}: unsupported active finite status {active!r}")
    return {
        "family_id": family,
        "physical_case_id": case_id,
        "status": row["status"],
        "active_finite_status": active,
        "initial_mass_status": row["initial_mass_status"],
        "missing_fields": [],
        "unit_comparison": row["unit_comparison"],
        "physical_ranges_diagnostic": True,
    }


def _verify_root_proof(
    proof_path: Path,
    declared_sha: str,
    family: str,
    case_id: str,
    source_path: Path,
    source_sha: str,
) -> dict[str, Any]:
    observed_sha = _sha256(proof_path, "root pilot proof", MAX_PROOF_BYTES)
    _sha(declared_sha, f"{proof_path} handoff proof SHA")
    if observed_sha != declared_sha:
        _fail(f"{proof_path}: handoff proof SHA differs")
    proof = _json(proof_path, "root pilot proof", MAX_PROOF_BYTES)
    if proof.get("schema") != ROOT_PROOF_SCHEMA:
        _fail(f"{proof_path}: root proof schema differs")
    if proof.get("status") != "VERIFIED_ACTUAL_PRODUCTION_H5_FIELD_SCAN_METADATA_CLOSURE_NO_PHYSICAL_Q":
        _fail(f"{proof_path}: root proof status is not the verified metadata closure")
    for key in ("request_sha256", "receipt_sha256", "report_sha256", "manifest_sha256", "independent_verification_sha256", "systemd_evidence_sha256", "terminal_cpu_reconciliation_sha256"):
        _sha(proof.get(key), f"{proof_path}.{key}")
    _absolute(proof.get("request"), f"{proof_path}.request")
    _absolute(proof.get("receipt"), f"{proof_path}.receipt")
    _require_bool(proof.get("parent_actual_prepost_content_hashes_equal"), True, f"{proof_path}.parent_actual_prepost_content_hashes_equal")
    _require_bool(proof.get("parent_reservation_released"), True, f"{proof_path}.parent_reservation_released")
    _require_bool(proof.get("H5_BI4_read_by_root"), False, f"{proof_path}.H5_BI4_read_by_root")
    _require_bool(proof.get("root_h5_payload_content_read"), False, f"{proof_path}.root_h5_payload_content_read")
    _require_bool(proof.get("repeat_fee_idempotent"), True, f"{proof_path}.repeat_fee_idempotent")
    if proof.get("scientific_Q_credit") != 0:
        _fail(f"{proof_path}: scientific Q credit is nonzero")
    qualification = proof.get("scientific_qualification")
    if not isinstance(qualification, dict) or any(qualification.get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
        _fail(f"{proof_path}: qualification boundary is promoted")
    if proof.get("units_material_physical_authority") != "UNKNOWN":
        _fail(f"{proof_path}: material authority is promoted")
    if proof.get("guarded_receipt_status") != "completed" or proof.get("outer_unit_result") != "success":
        _fail(f"{proof_path}: terminal receipt/unit is not successful")
    _finite_number(proof.get("actual_cpu_core_seconds"), f"{proof_path}.actual_cpu_core_seconds")
    _finite_number(proof.get("full_systemd_cpu_seconds"), f"{proof_path}.full_systemd_cpu_seconds")
    _finite_number(proof.get("actual_tree_bytes"), f"{proof_path}.actual_tree_bytes")
    binding = proof.get("source_index")
    if not isinstance(binding, dict):
        _fail(f"{proof_path}: source_index binding is missing")
    if _absolute(binding.get("path"), f"{proof_path}.source_index.path") != source_path or binding.get("sha256") != source_sha:
        _fail(f"{proof_path}: source index binding differs")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != 1:
        _fail(f"{proof_path}: expected exactly one selected case row")
    row = _verify_case_row(rows[0], family, case_id, proof_path)
    return {
        "path": str(proof_path),
        "sha256": observed_sha,
        "request": str(proof["request"]),
        "request_sha256": proof["request_sha256"],
        "receipt": str(proof["receipt"]),
        "receipt_sha256": proof["receipt_sha256"],
        "status": proof["status"],
        "guarded_receipt_status": proof["guarded_receipt_status"],
        "outer_unit_result": proof["outer_unit_result"],
        "actual_cpu_core_seconds": proof["actual_cpu_core_seconds"],
        "full_systemd_cpu_seconds": proof["full_systemd_cpu_seconds"],
        "actual_cpu_delta_seconds": proof.get("actual_cpu_delta_seconds"),
        "actual_tree_bytes": int(proof["actual_tree_bytes"]),
        "case_verification": row,
        "scientific_credit": 0,
        "production_payload_read_by_aggregator": False,
    }


def aggregate(
    handoff_dir: Path,
    output_path: Path,
    *,
    expected_source_index: Path | None = None,
    expected_source_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate ROOT346--352 and write one new family-card evidence report."""
    handoff_dir = handoff_dir.expanduser()
    if not handoff_dir.is_absolute():
        _fail("handoff directory must be absolute")
    if expected_source_index is not None:
        expected_source_index = expected_source_index.expanduser()
        if not expected_source_index.is_absolute():
            _fail("expected source index must be absolute")
    if expected_source_sha256 is not None:
        _sha(expected_source_sha256, "expected source index SHA")

    selected: list[dict[str, Any]] = []
    source_path: Path | None = None
    source_sha: str | None = None
    for ordinal, (root_id, family, case_id) in enumerate(PILOTS, start=1):
        handoff_path = handoff_dir / f"ROOT{root_id}_ACTUAL_SCIENTIFIC_FIELD_H5_PILOT_HANDOFF_V1.json"
        handoff = _json(handoff_path, f"ROOT{root_id} handoff", MAX_HANDOFF_BYTES)
        if handoff.get("schema") != HANDOFF_SCHEMA:
            _fail(f"{handoff_path}: handoff schema differs")
        if handoff.get("actual_pilot_count") != ordinal:
            _fail(f"{handoff_path}: cumulative pilot count differs")
        if handoff.get("selected_case_id") != case_id:
            _fail(f"{handoff_path}: selected case differs")
        if handoff.get("production_scientific_Q_credit") != 0:
            _fail(f"{handoff_path}: handoff carries scientific credit")
        if handoff.get("goal_complete") is not False or handoff.get("goal_status") != "ACTIVE_FULL_SEVEN_ITEMS":
            _fail(f"{handoff_path}: goal boundary differs")
        _finite_number(handoff.get("full_cpu_seconds"), f"{handoff_path}.full_cpu_seconds")
        binding = handoff.get("source_index")
        if not isinstance(binding, dict):
            _fail(f"{handoff_path}: source_index is missing")
        handoff_source_path = _absolute(binding.get("path"), f"{handoff_path}.source_index.path")
        handoff_source_sha = _sha(binding.get("sha256"), f"{handoff_path}.source_index.sha256")
        if source_path is None:
            source_path, source_sha = handoff_source_path, handoff_source_sha
            _verify_source_index(source_path, source_sha, expected_source_index, expected_source_sha256)
        elif handoff_source_path != source_path or handoff_source_sha != source_sha:
            _fail(f"{handoff_path}: source index differs from earlier pilot")

        actual_proofs = handoff.get("actual_proofs")
        if not isinstance(actual_proofs, list) or len(actual_proofs) != ordinal:
            _fail(f"{handoff_path}: cumulative actual_proofs list is incomplete")
        proof_records: list[dict[str, Any]] = []
        for proof_ordinal, proof_ref in enumerate(actual_proofs, start=1):
            if not isinstance(proof_ref, dict):
                _fail(f"{handoff_path}: actual_proofs[{proof_ordinal - 1}] is not an object")
            proof_path = _absolute(proof_ref.get("path"), f"{handoff_path}.actual_proofs.path")
            expected_id, expected_family, expected_case = PILOTS[proof_ordinal - 1]
            if str(expected_id) not in proof_path.name:
                _fail(f"{handoff_path}: proof order/path does not match ROOT{expected_id}")
            proof_records.append(_verify_root_proof(proof_path, proof_ref.get("sha256"), expected_family, expected_case, source_path, source_sha))
        if proof_records[-1]["case_verification"]["physical_case_id"] != case_id:
            _fail(f"{handoff_path}: latest proof row does not match selected case")
        latest = proof_records[-1]
        selected.append({
            "family_id": family,
            "physical_case_id": case_id,
            "root_id": root_id,
            "handoff_path": str(handoff_path),
            "handoff_sha256": _sha256(handoff_path, f"ROOT{root_id} handoff", MAX_HANDOFF_BYTES),
            "root_proof": latest,
            "full_cpu_seconds": handoff["full_cpu_seconds"],
            "actual_tree_bytes": latest["actual_tree_bytes"],
        })

    assert source_path is not None and source_sha is not None
    if output_path.exists() or output_path.is_symlink():
        _fail(f"refusing to overwrite report: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_cpu = sum(float(item["root_proof"]["full_systemd_cpu_seconds"]) for item in selected)
    total_tree = sum(int(item["actual_tree_bytes"]) for item in selected)
    report = {
        "schema": REPORT_SCHEMA,
        "status": REPORT_STATUS,
        "source_index": {"path": str(source_path), "sha256": source_sha},
        "pilot_count": 7,
        "family_card_evidence": {
            item["family_id"]: {
                "physical_case_id": item["physical_case_id"],
                "pilot_root": item["root_id"],
                "handoff": {"path": item["handoff_path"], "sha256": item["handoff_sha256"]},
                "root_proof": item["root_proof"],
            }
            for item in selected
        },
        "aggregate_terminal": {
            "full_systemd_cpu_seconds_sum": total_cpu,
            "actual_tree_bytes_sum": total_tree,
            "all_reservations_released": True,
            "all_outer_units_success": True,
            "all_parent_prepost_content_hashes_equal": True,
            "all_fee_reconciliation_repeat_idempotent": True,
        },
        "claim_boundary": {
            "development_only": True,
            "production_scientific_Q_credit": 0,
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "units_material_physical_authority": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "labels_accepted": False,
            "portable_replay_verified": False,
            "production_payload_read_by_aggregator": False,
        },
        "unknowns": [
            "declared units have not established material/physical authority",
            "no QI/QN/QE qualification is granted",
            "physical fate, flux, dynamics, and event labels remain UNKNOWN",
            "pilot metadata does not establish canonical identity promotion or portable replay",
            "the seven pilots do not represent the remaining 328 current cases",
        ],
        "input_read_policy": {
            "handoff_json_bounded": True,
            "root_proof_json_bounded": True,
            "source_index_json_bounded": True,
            "trajectory_h5_opened": False,
            "bi4_opened": False,
            "raw_arrays_opened": False,
            "typed_payload_opened": False,
            "solver_launched": False,
            "ledger_mutated": False,
        },
        "family_card_scope": "metadata-only pilot evidence overlay; not a complete seven-family product",
    }
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    report["report_path"] = str(output_path)
    report["report_sha256"] = _sha256(output_path, "generated pilot report", MAX_SOURCE_INDEX_BYTES)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-index", type=Path)
    parser.add_argument("--source-index-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = aggregate(
            args.handoff_dir,
            args.output,
            expected_source_index=args.source_index,
            expected_source_sha256=args.source_index_sha256,
        )
    except PilotHandoffV2Error as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps({"report": report["report_path"], "sha256": report["report_sha256"], "status": report["status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
