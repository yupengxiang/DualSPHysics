#!/usr/bin/env python3
"""Build a bounded, metadata-only plan for the remaining original-118 cases.

This planner answers a narrow question before any native/typed payload is
opened: which of the cases still classified as
``CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN`` already have a *completed* typed
lifecycle product that can be joined to their indexed native evidence?  A
declared H5 path or an indexed ``omission-forensics.json`` is deliberately not
treated as an executed audit.

The production result currently has no such intersection.  The output still
contains a bounded, family-grouped queue so that a later lifecycle batch can
be selected without rediscovering the 53 identities.  It is a metadata
product only; it does not read H5, JSONL, BI4/OBI4, PartOut, RunPARTs, or any
trajectory/report payload and it never launches a request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]
STAGE2 = ROOT / "campaigns/ds-data-02/stage2"
CHECKPOINTS = STAGE2 / "checkpoints"

CURRENT_SCHEMA = "ds02.stage2.current336.v1"
# The filename is a V4 additive overlay, while the producer kept the stable
# schema identifier at v1.  Bind the identifier, filename and expected SHA
# through the metadata input rather than guessing a schema from the filename.
OVERLAY_SCHEMA = "ds02.stage2.original118-native-cause-actual-overlay.v1"
INVENTORY_SCHEMA = "ds02.stage2.historical118-source-inventory.v1"
UNION_SCHEMA = "ds02.stage2.historical118-native-coverage-union.v3"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
REQUEST_SCHEMA = "ds02.request.v1"
PLAN_SCHEMA = "ds02.stage2.unlocated-native-cause-plan.v1"

CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
MAX_SMALL_BYTES = 8 * 1024 * 1024
MAX_CASES_PER_BATCH = 8
MAX_DECLARED_SOURCE_BYTES = 20 * 1024**3
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}

DEFAULT_OVERLAY = CHECKPOINTS / "ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT226_ACTUAL_OVERLAY_V4.json"
DEFAULT_INVENTORY = CHECKPOINTS / "HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
DEFAULT_UNION = CHECKPOINTS / "HISTORICAL_118_NATIVE_COVERAGE_UNION_003.json"
DEFAULT_CURRENT = STAGE2 / "CURRENT336.json"
DEFAULT_TYPED_PROOFS = tuple(
    CHECKPOINTS / name
    for name in (
        "TYPED_LIFECYCLE_BATCH_F1_ACTUAL_ROOT_VERIFICATION_208.json",
        "TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_193.json",
        "TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_198.json",
        "TYPED_LIFECYCLE_BATCH_F2_ACTUAL_ROOT_VERIFICATION_206.json",
        "TYPED_LIFECYCLE_BATCH_F3_ACTUAL_ROOT_VERIFICATION_215.json",
        "TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_201.json",
        "TYPED_LIFECYCLE_BATCH_F5_ACTUAL_ROOT_VERIFICATION_218.json",
        "TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_203.json",
        "TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_210.json",
        "TYPED_LIFECYCLE_BATCH_F7_ACTUAL_ROOT_VERIFICATION_224.json",
    )
)


class PlanError(ValueError):
    """Raised for an incomplete or contradictory metadata contract."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PlanError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(ch not in "0123456789abcdef" for ch in value):
        raise PlanError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise PlanError(f"{label} has no path")
    return Path(value).expanduser().resolve()


def _stat(path: Path, label: str) -> dict[str, Any]:
    try:
        value = path.stat()
    except OSError as exc:
        raise PlanError(f"{label} is missing: {path}") from exc
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _digest(path: Path, label: str) -> str:
    info = _stat(path, label)
    if info["bytes"] > MAX_SMALL_BYTES:
        raise PlanError(f"{label} exceeds the metadata-only bound: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise PlanError(f"cannot read metadata input {path}") from exc
    return digest.hexdigest()


def _small_ref(path: Path, label: str, expected: Any | None = None) -> dict[str, Any]:
    path = _path(path, label)
    info = _stat(path, label)
    actual = _digest(path, label)
    if expected is not None and actual != _sha(expected, f"{label} expected SHA"):
        raise PlanError(f"{label} SHA differs: expected {expected}, got {actual}")
    return {**info, "sha256": actual, "content_opened": True}


def _read_json(path: Path, label: str) -> dict[str, Any]:
    path = _path(path, label)
    info = _stat(path, label)
    if info["bytes"] > MAX_SMALL_BYTES:
        raise PlanError(f"{label} exceeds the metadata-only bound: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PlanError(f"{label} must be a JSON object")
    return value


def _atomic_json(path: Path, value: dict[str, Any], *, limit: int = 16 * 1024 * 1024) -> None:
    path = _path(path, "output")
    if path.exists() or path.is_symlink():
        raise PlanError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise PlanError(f"output exceeds bounded size {limit}: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _case_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise PlanError(f"{label} is not a physical case ID")
    return value


def _family(case_id: str, declared: Any) -> str:
    if not isinstance(declared, str) or not declared:
        raise PlanError(f"family is missing for {case_id}")
    prefix = case_id.split("_", 1)[0]
    if prefix != declared:
        raise PlanError(f"case/family mismatch for {case_id}: {declared}")
    return declared


def _declared_ref(item: Any, label: str, *, suffixes: set[str] | None = None) -> dict[str, Any] | None:
    """Copy a producer-declared reference without opening its target."""
    if isinstance(item, (str, os.PathLike)):
        item = {"path": str(item)}
    if not isinstance(item, dict):
        return None
    raw_path = item.get("path", item.get("canonical_path"))
    if not raw_path:
        return None
    path = _path(raw_path, label)
    if suffixes and path.suffix.lower() not in suffixes:
        raise PlanError(f"{label} has an unexpected suffix: {path}")
    declared = item.get("declared_sha256", item.get("known_sha256", item.get("sha256")))
    if declared is not None:
        declared = _sha(declared, f"{label} declared SHA")
    stat = item.get("stat") if isinstance(item.get("stat"), dict) else {}
    result: dict[str, Any] = {
        "path": str(path),
        "bytes": item.get("bytes", stat.get("bytes")),
        "mtime_ns": item.get("mtime_ns", stat.get("mtime_ns")),
        "ctime_ns": item.get("ctime_ns", stat.get("ctime_ns")),
        "st_dev": item.get("st_dev", stat.get("st_dev")),
        "st_ino": item.get("st_ino", stat.get("st_ino")),
        "sha256": declared,
        "declared_status": item.get("status", "PRESENT_STAT_ONLY"),
        "content_opened": bool(item.get("content_opened", False)),
        "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION_SINGLE_PASS",
    }
    return result


def _load_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    overlay_path = _path(args.overlay, "overlay")
    inventory_path = _path(args.inventory, "inventory")
    union_path = _path(args.union, "union")
    current_path = _path(args.current, "CURRENT")
    overlay = _read_json(overlay_path, "overlay")
    inventory = _read_json(inventory_path, "inventory")
    union = _read_json(union_path, "union")
    current = _read_json(current_path, "CURRENT")
    if overlay.get("schema") != OVERLAY_SCHEMA:
        raise PlanError(f"overlay schema differs: {overlay.get('schema')}")
    if inventory.get("schema") != INVENTORY_SCHEMA:
        raise PlanError(f"inventory schema differs: {inventory.get('schema')}")
    if union.get("schema") != UNION_SCHEMA:
        raise PlanError(f"union schema differs: {union.get('schema')}")
    if current.get("schema") != CURRENT_SCHEMA:
        raise PlanError(f"CURRENT schema differs: {current.get('schema')}")
    current_ref = _small_ref(current_path, "CURRENT", CURRENT_SHA256 if not args.allow_fixture else None)
    typed_proofs: list[dict[str, Any]] = []
    proof_paths = args.typed_proof or [str(path) for path in DEFAULT_TYPED_PROOFS]
    for raw in proof_paths:
        path = _path(raw, "typed lifecycle proof")
        proof = _read_json(path, f"typed lifecycle proof {path.name}")
        typed_proofs.append({"path": path, "value": proof, "ref": _small_ref(path, f"typed lifecycle proof {path.name}")})
    refs = {
        "overlay": _small_ref(overlay_path, "overlay"),
        "inventory": _small_ref(inventory_path, "inventory"),
        "union": _small_ref(union_path, "union"),
        "current": current_ref,
    }
    return overlay, inventory, union, current, typed_proofs, refs


def _extract_typed_cases(proofs: Iterable[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    typed: dict[str, dict[str, Any]] = {}
    duplicates: dict[str, list[str]] = defaultdict(list)
    for item in proofs:
        path = item["path"]
        proof = item["value"]
        if proof.get("schema") != PROOF_SCHEMA:
            raise PlanError(f"typed proof schema differs: {path}")
        status = proof.get("status", "")
        if not isinstance(status, str) or not status.startswith("VERIFIED_ACTUAL"):
            continue
        rows = proof.get("case_verifications")
        if not isinstance(rows, list):
            raise PlanError(f"typed proof case_verifications is not a list: {path}")
        for row in rows:
            if not isinstance(row, dict):
                raise PlanError(f"typed proof contains a non-object case row: {path}")
            case = _case_id(row.get("physical_case_id"), f"typed proof {path.name} case")
            if row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
                continue
            family = _family(case, row.get("family_id"))
            if case in typed:
                duplicates[case].extend([typed[case]["proof_path"], str(path)])
            typed[case] = {
                "case_id": case,
                "family_id": family,
                "proof_path": str(path),
                "proof_sha256": item["ref"]["sha256"],
                "case_status": row.get("status"),
                "summary": _declared_ref(row.get("summary"), f"typed summary {case}", suffixes={".json"}),
                "records_stat_only": _declared_ref(row.get("records_stat_only"), f"typed records {case}", suffixes={".jsonl"}),
                "source_H5": _declared_ref(
                    row.get("source_H5") or row.get("source_trajectory") or row.get("trajectory_h5"),
                    f"typed source H5 {case}",
                    suffixes=PAYLOAD_SUFFIXES & {".h5", ".hdf5"},
                ),
                "physical_fate_legal_flux_dynamics": row.get(
                    "native_cause_fate_legal_flux_dynamics", row.get("native_cause_fate_legal_flux_dynamics", "UNKNOWN")
                ),
            }
    if duplicates:
        raise PlanError(f"typed proof case appears in multiple completed proof rows: {sorted(duplicates)}")
    return typed, {key: value for key, value in duplicates.items()}


def _extract_join_cases(overlay: dict[str, Any], join_proofs: list[dict[str, Any]]) -> set[str]:
    """Extract physical case IDs from the small join proofs, without payload reads."""
    result: set[str] = set()
    for ref in overlay.get("actual_join_proofs", []):
        if not isinstance(ref, dict):
            raise PlanError("overlay actual_join_proofs contains a non-object")
        path = _path(ref.get("path"), "actual join proof")
        expected = ref.get("sha256")
        proof = _read_json(path, f"actual join proof {path.name}")
        if expected is not None and _digest(path, f"actual join proof {path.name}") != _sha(expected, "actual join proof SHA"):
            raise PlanError(f"actual join proof SHA differs: {path}")
        join_proofs.append({"path": str(path), "sha256": expected, "value": proof})
        scalar = proof.get("physical_case_id")
        if isinstance(scalar, str):
            result.add(scalar)
        for key in ("newly_bound_case_ids", "actual_completed_physical_cases"):
            values = proof.get(key)
            if isinstance(values, list):
                result.update(x for x in values if isinstance(x, str))
        rows = proof.get("case_verifications")
        if isinstance(rows, list):
            result.update(x.get("physical_case_id") for x in rows if isinstance(x, dict) and isinstance(x.get("physical_case_id"), str))
    return result


def _union_report_map(union: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    values = union.get("native_evidence")
    if not isinstance(values, list):
        raise PlanError("union native_evidence is not a list")
    for row in values:
        if not isinstance(row, dict):
            raise PlanError("union native_evidence has a non-object")
        case = _case_id(row.get("physical_case_id"), "union native evidence case")
        report = row.get("report")
        if not isinstance(report, dict):
            raise PlanError(f"union native evidence has no report: {case}")
        output[case] = report
    return output


def _case_record(row: dict[str, Any], union_report: dict[str, Any] | None, typed: dict[str, Any] | None) -> dict[str, Any]:
    case = _case_id(row.get("physical_case_id"), "inventory case")
    family = _family(case, row.get("family_id"))
    evidence = row.get("original_omission_evidence") if isinstance(row.get("original_omission_evidence"), dict) else {}
    if evidence.get("status") != "REFERENCE_PRESENT_PRIOR_NATIVE_EVIDENCE":
        raise PlanError(f"unexpected omission evidence status for {case}: {evidence.get('status')}")
    source = row.get("source_artifacts") if isinstance(row.get("source_artifacts"), dict) else {}
    artifacts = source.get("artifacts") if isinstance(source.get("artifacts"), dict) else {}
    report = _declared_ref(evidence.get("report"), f"native omission report {case}", suffixes={".json"})
    if report is None:
        raise PlanError(f"native omission report is not indexed for {case}")
    if union_report is not None:
        if union_report.get("path") and Path(union_report["path"]).expanduser().resolve() != Path(report["path"]).resolve():
            raise PlanError(f"inventory/union native report path differs for {case}")
        if union_report.get("sha256") and report.get("sha256") and _sha(union_report["sha256"], f"union report {case}") != report["sha256"]:
            raise PlanError(f"inventory/union native report SHA differs for {case}")
        report["union_bytes"] = union_report.get("bytes")
        report["union_sha256"] = union_report.get("sha256")
    typed_h5 = _declared_ref(artifacts.get("typed_trajectory_h5"), f"typed H5 {case}", suffixes={".h5", ".hdf5"})
    native_dir = _declared_ref(artifacts.get("native_part_directory_stat_index"), f"native directory {case}", suffixes=None)
    if typed_h5 is None or native_dir is None:
        raise PlanError(f"typed/native source index is incomplete for {case}")
    identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
    if identity.get("current_physical_case_id") != case or identity.get("current_identity_match") is not True:
        raise PlanError(f"CURRENT identity is not closed for {case}")
    typed_status = row.get("cause_and_fate_scope", {}).get("typed_lifecycle")
    if typed is None:
        classification = "NATIVE_SOURCE_INDEXED_TYPED_LIFECYCLE_MISSING"
        reason = "indexed native report and declared H5 exist, but no completed typed lifecycle proof covers this exact physical case"
    else:
        classification = "TYPED_LIFECYCLE_READY_NATIVE_JOIN"
        reason = "exact completed typed proof and indexed native report are available; native join remains a separate guarded operation"
    return {
        "physical_case_id": case,
        "family_id": family,
        "current336_index": row.get("current336_index"),
        "identity": {
            "current_physical_case_id": case,
            "current_identity_match": True,
            "current_trajectory_bytes": identity.get("current_trajectory_bytes"),
            "current_trajectory_declared_sha256": identity.get("current_trajectory_declared_sha256"),
            "current_trajectory_path": identity.get("current_trajectory_path"),
        },
        "classification": classification,
        "classification_reason": reason,
        "historical_native_status": "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN",
        "native_cause_credit": "NONE_FROM_THIS_PLAN",
        "physical_fate_legal_flux_dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "typed_lifecycle_inventory_status": typed_status,
        "typed_trajectory": typed_h5,
        "native_omission_report": report,
        "native_part_directory_stat_index": native_dir,
        "source_artifact_roles": {
            key: _declared_ref(value, f"{key} {case}", suffixes=None)
            for key, value in artifacts.items()
            if key in {"conversion_report", "gencase_receipt", "generated_xml", "manifest", "owner_metadata", "raw_solver_root", "xmf"}
        },
        "typed_proof": typed,
        "read_policy": {
            "metadata_inputs_opened": True,
            "trajectory_h5_opened": False,
            "typed_jsonl_opened": False,
            "native_partout_opened": False,
            "native_bi4_opened": False,
            "runparts_opened": False,
            "solver_started": False,
        },
    }


def _build_plan(args: argparse.Namespace) -> dict[str, Any]:
    overlay, inventory, union, current, typed_proofs, refs = _load_inputs(args)
    typed_cases, _ = _extract_typed_cases(typed_proofs)
    join_proofs: list[dict[str, Any]] = []
    consumed_join_cases = _extract_join_cases(overlay, join_proofs)
    declared_join_count = overlay.get("actual_typed_native_saved_frame_join_physical_cases")
    if not args.allow_fixture and declared_join_count != len(consumed_join_cases):
        raise PlanError(
            "overlay actual typed/native join count differs from its exact proof registry: "
            f"{declared_join_count} != {len(consumed_join_cases)}"
        )
    report_map = _union_report_map(union)
    unlocated = overlay.get("remaining_cause_not_located_case_ids")
    if not isinstance(unlocated, list) or not unlocated:
        raise PlanError("overlay has no remaining cause-not-located case list")
    if len(unlocated) != len(set(unlocated)):
        raise PlanError("overlay remaining case IDs are duplicated")
    rows = inventory.get("rows")
    if not isinstance(rows, list):
        raise PlanError("inventory rows is not a list")
    by_case: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PlanError("inventory contains a non-object row")
        case = _case_id(row.get("physical_case_id"), "inventory row")
        if case in by_case:
            raise PlanError(f"inventory case is duplicated: {case}")
        by_case[case] = row
    current_case_ids = {case for case, row in by_case.items() if row.get("historical_118_membership") is True}
    expected_members = len(rows) if args.allow_fixture else 118
    if len(current_case_ids) != expected_members:
        raise PlanError(f"inventory historical membership is not exactly {expected_members}: {len(current_case_ids)}")
    if set(unlocated) - current_case_ids:
        raise PlanError("overlay contains a case absent from exact historical inventory")
    if len(unlocated) != int(overlay.get("cause_not_located_after_completed_scan_cases", len(unlocated))):
        raise PlanError("overlay unlocated count does not match its case list")
    if not args.allow_fixture and int(overlay.get("native_cause_bound_per_fluid_id_cases", -1)) + len(unlocated) != 118:
        raise PlanError("overlay bound and unlocated counts do not close the original 118 cases")
    if len(typed_cases) != len(set(typed_cases)):
        raise PlanError("completed typed proof case IDs are duplicated")
    cases: list[dict[str, Any]] = []
    for case in unlocated:
        row = by_case[case]
        cases.append(_case_record(row, report_map.get(case), typed_cases.get(case)))
    cases.sort(key=lambda row: (row["family_id"], int(row["current336_index"]), row["physical_case_id"]))
    candidate_cases = [row for row in cases if row["classification"] == "TYPED_LIFECYCLE_READY_NATIVE_JOIN" and row["physical_case_id"] not in consumed_join_cases]
    # A completed typed proof already consumed by an earlier join is never
    # silently re-issued.  It remains visible in the consumed set.
    blocked_consumed = [row["physical_case_id"] for row in cases if row["physical_case_id"] in consumed_join_cases]
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cases:
        by_family[row["family_id"]].append(row)
    recommendations = []
    for family in sorted(by_family):
        family_cases = by_family[family]
        for offset in range(0, len(family_cases), MAX_CASES_PER_BATCH):
            chunk = family_cases[offset : offset + MAX_CASES_PER_BATCH]
            recommendations.append(
                {
                    "family_id": family,
                    "batch_id": f"{family}-unlocated-lifecycle-precondition-{offset // MAX_CASES_PER_BATCH:03d}",
                    "case_ids": [row["physical_case_id"] for row in chunk],
                    "case_count": len(chunk),
                    "requires_completed_typed_lifecycle_before_native_join": True,
                    "native_join_launch_allowed_by_this_plan": False,
                    "source_read_policy": "metadata_only_until_a_new_parent_guarded_lifecycle_and_native_join_request",
                }
            )
    family_counts = Counter(row["family_id"] for row in cases)
    typed_unlocated = sorted(set(typed_cases) & set(unlocated))
    input_refs = list(refs.values()) + [item["ref"] for item in typed_proofs]
    return {
        "schema": PLAN_SCHEMA,
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "created_by": str(SCRIPT),
        "scope": {
            "historical118_exact_case_count": 118 if not args.allow_fixture else len(current_case_ids),
            "remaining_unlocated_case_count": len(cases),
            "remaining_unlocated_case_ids": [row["physical_case_id"] for row in cases],
            "remaining_unlocated_by_family": dict(sorted(family_counts.items())),
            "completed_typed_case_count_from_registry": len(typed_cases),
            "unlocated_cases_with_completed_typed_product": len(typed_unlocated),
            "unlocated_typed_case_ids": typed_unlocated,
            "consumed_typed_native_join_case_count": len(consumed_join_cases),
            "unlocated_consumed_join_case_ids": sorted(blocked_consumed),
            "candidate_native_typed_join_case_count": len(candidate_cases),
            "candidate_native_typed_join_case_ids": [row["physical_case_id"] for row in candidate_cases],
        },
        "evidence_interpretation": {
            "native_indexed_cases_are_not_cause_bound": True,
            "typed_declared_h5_is_not_completed_lifecycle": True,
            "global_or_empty_native_counts_are_not_per_id_cause": True,
            "fluid_identity_counts_are_not_physical_case_counts": True,
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "metadata_inputs": input_refs,
        "actual_join_proof_registry": [
            {"path": item["path"], "sha256": item["sha256"]} for item in join_proofs
        ],
        "completed_typed_proof_registry": [
            {
                "path": item["ref"]["path"],
                "sha256": item["ref"]["sha256"],
                "case_count": sum(1 for row in item["value"].get("case_verifications", []) if isinstance(row, dict) and row.get("status") == "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY"),
            }
            for item in typed_proofs
        ],
        "cases": cases,
        "next_bounded_batches": recommendations,
        "candidate_cases": candidate_cases,
        "deferred_payload_policy": {
            "h5_jsonl_partout_bi4_content_opened": False,
            "minimum_future_operation": "first parent-reserved typed lifecycle product, then one native PartOut/RunPARTs source-bound join per case",
            "max_cases_per_batch": MAX_CASES_PER_BATCH,
            "max_declared_source_bytes_per_batch": MAX_DECLARED_SOURCE_BYTES,
            "output_credit": "NONE_FROM_THIS_PLAN",
        },
        "source_refs": {
            "current336": {"path": refs["current"]["path"], "sha256": refs["current"]["sha256"]},
            "overlay": {"path": refs["overlay"]["path"], "sha256": refs["overlay"]["sha256"]},
            "inventory": {"path": refs["inventory"]["path"], "sha256": refs["inventory"]["sha256"]},
            "union": {"path": refs["union"]["path"], "sha256": refs["union"]["sha256"]},
        },
    }


def _validate_plan(path: Path) -> dict[str, Any]:
    plan = _read_json(path, "plan manifest")
    if plan.get("schema") != PLAN_SCHEMA:
        raise PlanError("plan schema differs")
    if plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise PlanError("plan is not metadata-only")
    scope = plan.get("scope")
    if not isinstance(scope, dict):
        raise PlanError("plan scope is missing")
    ids = scope.get("remaining_unlocated_case_ids")
    if not isinstance(ids, list) or len(ids) != len(set(ids)):
        raise PlanError("plan unlocated IDs are not unique")
    if len(ids) != scope.get("remaining_unlocated_case_count"):
        raise PlanError("plan unlocated count differs")
    candidates = plan.get("candidate_cases")
    if not isinstance(candidates, list):
        raise PlanError("candidate_cases is not a list")
    if scope.get("candidate_native_typed_join_case_count") != len(candidates):
        raise PlanError("candidate count differs")
    for row in plan.get("cases", []):
        if row.get("physical_case_id") not in ids:
            raise PlanError("case row is outside exact unlocated set")
        if row.get("native_cause_credit") != "NONE_FROM_THIS_PLAN":
            raise PlanError("plan grants native cause credit")
        if row.get("physical_fate_legal_flux_dynamics") != "UNKNOWN":
            raise PlanError("plan grants physical fate/dynamics credit")
    for ref in plan.get("metadata_inputs", []):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise PlanError("metadata input reference is malformed")
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise PlanError("payload path was placed in metadata_inputs")
    for batch in plan.get("next_bounded_batches", []):
        case_ids = batch.get("case_ids")
        if not isinstance(case_ids, list) or len(case_ids) > MAX_CASES_PER_BATCH:
            raise PlanError("next batch exceeds case bound")
        if batch.get("native_join_launch_allowed_by_this_plan") is not False:
            raise PlanError("next batch unexpectedly allows launch")
    return plan


def _request_from_plan(manifest: Path, plan: dict[str, Any], output: Path) -> dict[str, Any]:
    metadata_refs = [
        {"path": item["path"], "sha256": item["sha256"], "bytes": item.get("bytes"), "role": "metadata_only"}
        for item in plan.get("metadata_inputs", [])
    ]
    manifest_sha = _digest(manifest, "generated manifest")
    worker_ref = _small_ref(SCRIPT, "planner worker source")
    metadata_refs.extend(
        [
            {"path": worker_ref["path"], "sha256": worker_ref["sha256"], "bytes": worker_ref["bytes"], "role": "worker_source"},
            {"path": str(manifest), "sha256": manifest_sha, "bytes": manifest.stat().st_size, "role": "prepared_manifest"},
        ]
    )
    return {
        "schema": REQUEST_SCHEMA,
        "request_id": "native-cause-unlocated-batch-root235-prepared-001",
        "status": "PREPARED_METADATA_ONLY_NO_LAUNCH",
        "launch_allowed": False,
        "cpu_task_kind": "audit",
        "command": [str(VENV_PATH()), str(SCRIPT), "validate", "--manifest", str(manifest)],
        "manifest": {"path": str(manifest), "sha256": manifest_sha, "read_policy": "metadata_only"},
        "input_files": metadata_refs,
        "deferred_case_payloads": {
            "case_count": int(plan["scope"]["remaining_unlocated_case_count"]),
            "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION; NOT_READ_BY_PREPARE",
            "physical_fate": "UNKNOWN",
        },
        "resource_policy": {
            "workers": 1,
            "memory_max_bytes": 4 * 1024**3,
            "max_wall_seconds": 900,
            "max_cases_per_future_batch": MAX_CASES_PER_BATCH,
            "max_declared_source_bytes_per_future_batch": MAX_DECLARED_SOURCE_BYTES,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "note": "Metadata planner only. A future lifecycle product must be completed before any native typed join is admitted.",
    }


def VENV_PATH() -> Path:
    # Keep this a literal environment role.  The primary may rebind it in a
    # new request; prepare never resolves or opens the interpreter.
    return Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _prepare(args: argparse.Namespace) -> int:
    plan = _build_plan(args)
    manifest = _path(args.manifest_output, "manifest output")
    request = _path(args.request_output, "request output")
    checkpoint = _path(args.checkpoint, "checkpoint output")
    _atomic_json(manifest, plan)
    request_value = _request_from_plan(manifest, plan, request)
    _atomic_json(request, request_value)
    checkpoint_value = {
        "schema": "ds02.stage2.unlocated-native-cause-plan-checkpoint.v1",
        "status": plan["status"],
        "manifest": {"path": str(manifest), "sha256": _digest(manifest, "generated manifest")},
        "request": {"path": str(request), "sha256": _digest(request, "generated request")},
        "scope": plan["scope"],
        "candidate_cases": plan["candidate_cases"],
        "metadata_only": True,
        "payload_content_read": False,
        "solver_started": False,
    }
    _atomic_json(checkpoint, checkpoint_value)
    print(json.dumps({"status": plan["status"], "manifest": str(manifest), "request": str(request), "checkpoint": str(checkpoint), "scope": plan["scope"]}, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    prepare.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    prepare.add_argument("--union", default=str(DEFAULT_UNION))
    prepare.add_argument("--current", default=str(DEFAULT_CURRENT))
    prepare.add_argument("--typed-proof", action="append", default=None)
    prepare.add_argument("--manifest-output", required=True)
    prepare.add_argument("--request-output", required=True)
    prepare.add_argument("--checkpoint", required=True)
    prepare.add_argument("--allow-fixture", action="store_true")
    prepare.set_defaults(func=_prepare)
    validate = sub.add_parser("validate")
    validate.add_argument("--manifest", required=True)
    validate.set_defaults(func=lambda args: (print(json.dumps(_validate_plan(_path(args.manifest, "manifest")), sort_keys=True)) or 0))
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        return int(args.func(args))
    except PlanError as exc:
        print(f"PlanError: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
