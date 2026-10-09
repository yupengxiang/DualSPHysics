#!/usr/bin/env python3
"""Build a metadata-only source inventory for the historical 118 omissions.

The historical omission population is the exact F2/F4/F6 union (48/22/48)
from an immutable omission-coverage proof.  This command joins those physical
case identities to CURRENT336 and inventories already-produced source edges:
conversion reports, solver receipts/logs, RunPARTs/Run.csv/Run.out, native
Part output directories, and the declared typed trajectory H5.  It performs
filesystem ``stat`` only for case artifacts.  It never opens or hashes H5,
BI4/OBI4, raw solver outputs, or large scientific JSON products.

The result is a source contract for a later guarded native-cause audit.  A
present report/path is an evidence edge, not a new cause inference.  Counts,
directory presence, and missing files never establish physical fate, legal
flux, continuous event time, or dynamics.  The ROOT192 typed-lifecycle pilot
is represented as a separate one-case comparison contract; its typed particle
records are never added to the historical 118 case membership.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "ds02.stage2.historical118-source-inventory.v1"
CONTRACT_SCHEMA = "ds02.stage2.historical118-cause-audit-source-contract.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
UNION_SCHEMA = "ds02.stage2.historical118-native-coverage-union.v3"
AUDIT_SCHEMA = "ds02.stage2.historical-omission-index-independent-verification.v1"
FAMILIES = ("F2", "F4", "F6")
EXPECTED_FAMILY_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
EXPECTED_CURRENT_COUNT = 336
DEFAULT_SMALL_JSON_LIMIT = 4 * 1024 * 1024
MAX_ALLOWED_INPUT_BYTES = 8 * 1024 * 1024
FORBIDDEN_CONTENT_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}
PART_FRAME_RE = re.compile(r"^Part_\d+\.bi4$")
PART_OUT_RE = re.compile(r"^PartOut(?:_\d+)?\.(?:obi4|csv)$", re.IGNORECASE)


class InventoryError(ValueError):
    """Raised when an immutable source identity cannot be closed."""


def _canonical(value: str | os.PathLike[str]) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


def _sha256(path: Path, *, max_bytes: int | None = None) -> str:
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        raise InventoryError(
            f"refusing content hash above metadata limit ({size} > {max_bytes}): {path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha_required(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise InventoryError(f"{label} must be a SHA-256 digest")
    return value.lower()


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise InventoryError(f"{label} lacks a path")
    return Path(value).expanduser()


def _read_json(path: Path, label: str, *, max_bytes: int = DEFAULT_SMALL_JSON_LIMIT) -> dict[str, Any]:
    if not path.is_file():
        raise InventoryError(f"{label} is missing: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise InventoryError(
            f"{label} exceeds metadata JSON read limit ({size} > {max_bytes}): {path}"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InventoryError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise InventoryError(f"{label} must be a JSON object: {path}")
    return value


def _stat_fields(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "mode": int(stat.st_mode),
    }


def _stat_ref(
    value: str | os.PathLike[str],
    role: str,
    *,
    declared_sha256: str | None = None,
    kind: str = "file",
) -> dict[str, Any]:
    """Return a stat-only source reference.

    The function intentionally does not open a file.  In particular, a
    declared H5/BI4 digest is carried as provenance but is not recomputed by
    this inventory.
    """
    path = _path(value, role)
    result: dict[str, Any] = {
        "role": role,
        "path": str(path),
        "canonical_path": _canonical(path),
        "kind": kind,
        "content_opened_by_inventory": False,
        "hash_checked_by_inventory": False,
        "declared_sha256": declared_sha256,
    }
    if not path.exists():
        result.update({"status": "MISSING", "stat": None})
        return result
    try:
        result.update({"status": "PRESENT_STAT_ONLY", "stat": _stat_fields(path)})
    except OSError as exc:
        result.update({"status": "STAT_FAILED", "stat_error": str(exc), "stat": None})
    return result


def _input_ref(path: Path, role: str, expected_sha256: str, *, max_bytes: int) -> dict[str, Any]:
    """Hash one bounded metadata input used to establish the inventory scope."""
    if not path.is_file():
        raise InventoryError(f"{role} is missing: {path}")
    expected = _sha_required(expected_sha256, f"{role} expected SHA")
    actual = _sha256(path, max_bytes=max_bytes)
    if actual != expected:
        raise InventoryError(f"{role} SHA differs: expected {expected}, got {actual}")
    return {
        "role": role,
        "path": str(path),
        "canonical_path": _canonical(path),
        "sha256": actual,
        "bytes": int(path.stat().st_size),
        "content_opened_by_inventory": True,
        "hash_checked_by_inventory": True,
    }


def _declared_ref(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        return {"role": role, "status": "DECLARATION_MISSING", "path": None}
    declared = value.get("sha256") or value.get("recomputed_sha256")
    if declared is not None:
        _sha_required(declared, f"{role} declared SHA")
    return _stat_ref(value["path"], role, declared_sha256=declared)


def _directory_index(path: Path, role: str) -> dict[str, Any]:
    """Index directory entries without opening any entry."""
    result = _stat_ref(path, role, kind="directory")
    if result.get("status") != "PRESENT_STAT_ONLY":
        result.update({"entry_count": 0, "entry_counts": {}, "entry_samples": []})
        return result
    try:
        entries = sorted(path.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        result.update({"entry_count": None, "entry_error": str(exc), "entry_counts": {}})
        return result
    counts = {
        "part_frame_bi4": 0,
        "part_out": 0,
        "bi4_or_obi4": 0,
        "run_or_log": 0,
        "other": 0,
    }
    selected: list[dict[str, Any]] = []
    for entry in entries:
        name = entry.name
        lower = name.lower()
        if PART_FRAME_RE.fullmatch(name):
            category = "part_frame_bi4"
        elif PART_OUT_RE.fullmatch(name):
            category = "part_out"
        elif lower.endswith((".bi4", ".obi4")):
            category = "bi4_or_obi4"
        elif lower.startswith("run") or lower.endswith((".out", ".log")):
            category = "run_or_log"
        else:
            category = "other"
        counts[category] += 1
        # Keep only a bounded deterministic sample.  Each selected item is
        # stat-only; no native bytes are read.
        if category != "other" and len(selected) < 2:
            selected.append(_stat_ref(entry, f"{role}:{name}", kind="entry"))
    if len(entries) > 4:
        for entry in entries[-2:]:
            if entry.name not in {item.get("path", "").rsplit("/", 1)[-1] for item in selected}:
                selected.append(_stat_ref(entry, f"{role}:{entry.name}", kind="entry"))
    result.update({
        "entry_count": len(entries),
        "entry_counts": counts,
        "entry_samples": selected[:16],
        "index_scope": "directory names/stat only; entry content not opened",
    })
    return result


def _solver_output_inventory(row: dict[str, Any]) -> dict[str, Any]:
    bindings = row.get("source_bindings")
    if not isinstance(bindings, dict):
        return {"status": "DECLARATION_MISSING", "artifacts": []}
    solver_receipt = bindings.get("solver_receipt")
    if not isinstance(solver_receipt, dict) or not isinstance(solver_receipt.get("path"), str):
        return {"status": "DECLARATION_MISSING", "artifacts": []}
    receipt_path = Path(solver_receipt["path"]).expanduser()
    refs = [_declared_ref(solver_receipt, "solver_receipt")]
    solver_output = receipt_path.parent / "solver_output"
    output_ref = _directory_index(solver_output, "solver_output_directory")
    refs.append(output_ref)
    for name in ("Run.out", "RunPARTs.csv", "Run.csv"):
        refs.append(_stat_ref(solver_output / name, f"solver_output:{name}"))
    return {
        "status": "SOURCE_PATHS_INDEXED",
        "solver_receipt_parent": str(receipt_path.parent),
        "artifacts": refs,
        "read_policy": "receipt/log/RunPARTs paths are stat-only; no text is opened",
    }


def _source_artifacts(row: dict[str, Any]) -> dict[str, Any]:
    bindings = row.get("source_bindings", {})
    if not isinstance(bindings, dict):
        bindings = {}
    source_refs = {
        "manifest": _declared_ref(row.get("manifest"), "CURRENT_case_manifest"),
        "xmf": _declared_ref(row.get("xmf"), "CURRENT_case_xmf"),
        "generated_xml": _declared_ref(bindings.get("generated_xml"), "generated_xml"),
        "gencase_receipt": _declared_ref(bindings.get("gencase_receipt"), "gencase_receipt"),
        "owner_metadata": _declared_ref(bindings.get("owner_metadata"), "owner_metadata"),
        "conversion_report": _declared_ref(row.get("conversion_report"), "conversion_report"),
        "typed_trajectory_h5": _declared_ref(row.get("trajectory"), "typed_trajectory_h5"),
        "raw_solver_root": _stat_ref(
            row.get("raw_root", {}).get("path") if isinstance(row.get("raw_root"), dict) else "",
            "raw_solver_root",
            kind="directory",
        ),
    }
    trajectory = row.get("trajectory", {})
    if isinstance(trajectory, dict):
        producer_sha = trajectory.get("producer_declared_sha256")
        if producer_sha is not None:
            _sha_required(producer_sha, "CURRENT trajectory producer_declared_sha256")
            source_refs["typed_trajectory_h5"]["declared_sha256"] = producer_sha
        source_refs["typed_trajectory_h5"].update({
            "known_sha256_source": "CURRENT.trajectory.producer_declared_sha256",
            "declared_bytes": trajectory.get("bytes"),
            "content_opened_by_inventory": False,
            "hash_verification": "DEFERRED_TO_GUARDED_WORKER",
        })
    raw_root = Path(str(row.get("raw_root", {}).get("path", ""))).expanduser()
    source_refs["native_part_directory_stat_index"] = _directory_index(
        raw_root, "native_part_directory")
    source_refs["solver_output"] = _solver_output_inventory(row)
    return {
        "artifacts": source_refs,
        "all_case_artifacts_content_opened": False,
        "h5_bi4_content_opened": False,
        "source_hash_scope": (
            "CURRENT-declared hashes are retained; H5/BI4/raw/log content hashes are "
            "deferred to a parent-guarded worker"
        ),
    }


def _root192_ref(path: Path, role: str, expected_sha256: str) -> dict[str, Any]:
    ref = _stat_ref(path, role, declared_sha256=_sha_required(expected_sha256, f"{role} SHA"))
    ref.update({
        "sha256_source": "caller-supplied immutable producer proof",
        "hash_verification": "DEFERRED_TO_GUARDED_WORKER",
        "content_opened_by_inventory": False,
    })
    return ref


def _validate_inputs(
    current_path: Path,
    current_expected_sha: str,
    union_path: Path,
    union_expected_sha: str,
    audit_path: Path,
    audit_expected_sha: str,
    *,
    max_input_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    current_ref = _input_ref(current_path, "CURRENT336", current_expected_sha, max_bytes=max_input_bytes)
    union_ref = _input_ref(union_path, "historical 118 omission union", union_expected_sha, max_bytes=max_input_bytes)
    audit_ref = _input_ref(audit_path, "historical omission audit proof", audit_expected_sha, max_bytes=max_input_bytes)
    current = _read_json(current_path, "CURRENT336", max_bytes=max_input_bytes)
    union = _read_json(union_path, "historical 118 omission union", max_bytes=max_input_bytes)
    audit = _read_json(audit_path, "historical omission audit proof", max_bytes=max_input_bytes)
    if current.get("schema") != CURRENT_SCHEMA:
        raise InventoryError("CURRENT336 schema differs")
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) != EXPECTED_CURRENT_COUNT:
        raise InventoryError(f"CURRENT336 must contain {EXPECTED_CURRENT_COUNT} cases")
    current_by_id: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, row in enumerate(cases):
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise InventoryError(f"CURRENT336 case {index} lacks physical_case_id")
        case_id = row["physical_case_id"]
        if case_id in current_by_id:
            raise InventoryError(f"CURRENT336 duplicate physical_case_id: {case_id}")
        current_by_id[case_id] = (index, row)
    if union.get("schema") != UNION_SCHEMA or union.get("status") != "PASS_EXACT_118_OF118_SOURCE_CASE_UNION":
        raise InventoryError("historical union is not the exact v3 118 proof")
    if audit.get("schema") != AUDIT_SCHEMA or audit.get("status") != "PASS_SCOPED_EXACT_REGISTRY_AND_EVIDENCE_CLOSURE":
        raise InventoryError("historical audit proof is not the scoped exact registry proof")
    if audit.get("exact_historical118_membership_verified") is not True:
        raise InventoryError("historical audit proof does not assert exact 118 membership")
    audit_current = audit.get("CURRENT", {})
    if audit_current.get("sha256", "").lower() != current_ref["sha256"]:
        raise InventoryError("audit proof CURRENT SHA differs from supplied CURRENT")
    evidence = union.get("native_evidence")
    if not isinstance(evidence, list) or len(evidence) != 118:
        raise InventoryError("historical union does not contain exactly 118 evidence rows")
    seen: set[tuple[str, str]] = set()
    family_counts = {family: 0 for family in FAMILIES}
    for item in evidence:
        if not isinstance(item, dict):
            raise InventoryError("historical union evidence row is not an object")
        family = item.get("family_id")
        case_id = item.get("physical_case_id")
        if family not in FAMILIES or not isinstance(case_id, str):
            raise InventoryError(f"historical union contains non-F2/F4/F6 case: {item}")
        key = (family, case_id)
        if key in seen:
            raise InventoryError(f"historical union duplicate case: {key}")
        seen.add(key)
        family_counts[family] += 1
        current_item = current_by_id.get(case_id)
        if current_item is None:
            raise InventoryError(f"historical union case absent from CURRENT336: {case_id}")
        current_index, current_row = current_item
        if current_row.get("family_id") != family:
            raise InventoryError(f"CURRENT/union family mismatch: {case_id}")
        if "current_index" in item and item["current_index"] != current_index:
            raise InventoryError(f"CURRENT/union index mismatch: {case_id}")
        report = item.get("report")
        if not isinstance(report, dict) or not isinstance(report.get("path"), str):
            raise InventoryError(f"historical union lacks native report reference: {case_id}")
        if report.get("sha256") is not None:
            _sha_required(report["sha256"], f"native report SHA {case_id}")
    if family_counts != EXPECTED_FAMILY_COUNTS:
        raise InventoryError(f"historical union family counts differ: {family_counts}")
    return current, union, audit, {
        "current": current_ref,
        "union": union_ref,
        "audit": audit_ref,
        "current_by_id": current_by_id,
        "membership": seen,
    }


def _evidence_ref(item: dict[str, Any], *, current_row: dict[str, Any]) -> dict[str, Any]:
    report = item["report"]
    path = Path(report["path"]).expanduser()
    ref = _stat_ref(path, "prior_native_omission_report", declared_sha256=report.get("sha256"))
    if ref["status"] == "PRESENT_STAT_ONLY":
        status = "REFERENCE_PRESENT_PRIOR_NATIVE_EVIDENCE"
        cause_scope = "NATIVE_NUMERICAL_EXCLUSION_EVIDENCE_ONLY"
    else:
        status = "REFERENCE_MISSING_PRIOR_NATIVE_EVIDENCE"
        cause_scope = "UNKNOWN_MISSING_NATIVE_EVIDENCE"
    return {
        "status": status,
        "cause_scope": cause_scope,
        "cause_inferred_from_counts": False,
        "union_scope": item.get("scope"),
        "report": ref,
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "continuous_event_time": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "interpretation": (
            "A prior source-bound report reference is indexed only as an evidence "
            "edge.  No numerical count is converted into a cause, fate, or flux claim."
        ),
    }


def _case_entry(
    item: dict[str, Any],
    current_index: int,
    current_row: dict[str, Any],
) -> dict[str, Any]:
    source = _source_artifacts(current_row)
    typed = source["artifacts"]["typed_trajectory_h5"]
    return {
        "family_id": item["family_id"],
        "physical_case_id": item["physical_case_id"],
        "historical_118_membership": True,
        "current336_index": current_index,
        "identity": {
            "runtime_case_alias": current_row.get("runtime_case_alias"),
            "current_family_id": current_row.get("family_id"),
            "current_physical_case_id": current_row.get("physical_case_id"),
            "current_identity_match": True,
            "current_trajectory_path": current_row.get("trajectory", {}).get("path"),
            "current_trajectory_declared_sha256": current_row.get("trajectory", {}).get("producer_declared_sha256"),
            "current_trajectory_bytes": current_row.get("trajectory", {}).get("bytes"),
            "current_trajectory_content_opened": False,
        },
        "original_omission_evidence": _evidence_ref(item, current_row=current_row),
        "source_artifacts": source,
        "cause_and_fate_scope": {
            "native_numerical_cause": "SOURCE_BOUND_PRIOR_EVIDENCE_ONLY",
            "conversion_filtering": "UNKNOWN",
            "type_miscount": "UNKNOWN",
            "recovery_lineage_replacement": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "continuous_first_event": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "typed_lifecycle": "DECLARED_H5_ONLY_NOT_OPENED",
            "typed_h5_known_sha256": current_row.get("trajectory", {}).get("producer_declared_sha256"),
            "typed_h5_reference_status": typed.get("status"),
            "qualification_credit": "NONE_FROM_THIS_INVENTORY",
        },
        "next_cause_audit": {
            "status": "READY_FOR_PARENT_GUARDED_NATIVE_CONTENT_AUDIT",
            "deferred_inputs": [
                "native PartOut/Part*.bi4 content",
                "RunPARTs/Run.out semantic content",
                "typed H5 lifecycle content only for a separately authorized comparison",
            ],
            "input_scope": "stat/index now; content hash/decode only after parent reservation",
            "new_attempt_identity_required": True,
            "no_solver_or_scan_requested": True,
        },
    }


def _typed_pilot_contract(
    *,
    case_id: str,
    case_entry: dict[str, Any],
    proof_path: Path | None,
    proof_sha: str | None,
    summary_path: Path | None,
    summary_sha: str | None,
) -> dict[str, Any]:
    if proof_path is None and summary_path is None:
        return {
            "status": "NOT_SUPPLIED",
            "case_id": case_id,
            "historical_case_membership": True,
            "typed_records_not_added_to_historical_case_count": True,
            "comparison": "DEFERRED",
        }
    if proof_path is None or proof_sha is None or summary_path is None or summary_sha is None:
        raise InventoryError("ROOT192 pilot requires proof/summary paths and both known SHAs")
    native = case_entry["original_omission_evidence"]["report"]
    return {
        "status": "READY_SEPARATE_GUARDED_COMPARISON",
        "case_id": case_id,
        "historical_case_membership": True,
        "typed_records_not_added_to_historical_case_count": True,
        "typed_proof": _root192_ref(proof_path, "ROOT192_typed_lifecycle_proof", proof_sha),
        "typed_summary": _root192_ref(summary_path, "ROOT192_typed_lifecycle_summary", summary_sha),
        "native_omission_report": native,
        "comparison_fields": [
            "typed first_disappearance frame/time",
            "native PartOut/RunPARTs saved-time bracket",
            "typed/native Idp and (Zone,Idp) identity join",
            "typed source H5 declared SHA versus CURRENT",
        ],
        "comparison_result": "UNKNOWN_UNTIL_GUARDED_TYPED_AND_NATIVE_CONTENT_READ",
        "read_policy": {
            "inventory_opened_typed_summary": False,
            "inventory_opened_typed_h5": False,
            "inventory_opened_native_content": False,
            "guarded_worker_required": True,
        },
        "scope_warning": (
            "ROOT192 is one typed lifecycle pilot for this physical case. Its particle "
            "records are not 118 additional omission cases and do not expand the F2/F4/F6 registry."
        ),
    }


def _worker_source_ref(path: Path, role: str) -> dict[str, Any]:
    """Bind an existing decoder/audit implementation without invoking it."""
    ref = _stat_ref(path, role, kind="source_code")
    if ref.get("status") == "PRESENT_STAT_ONLY":
        size = int(ref["stat"]["bytes"])
        if size > DEFAULT_SMALL_JSON_LIMIT:
            raise InventoryError(f"existing worker source exceeds source binding limit: {path}")
        ref["sha256"] = _sha256(path, max_bytes=DEFAULT_SMALL_JSON_LIMIT)
        ref["content_opened_by_inventory"] = True
        ref["hash_checked_by_inventory"] = True
    ref["invoked_by_inventory"] = False
    return ref


def _make_contract(
    rows: list[dict[str, Any]],
    worker_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    by_family: dict[str, list[str]] = {family: [] for family in FAMILIES}
    for row in rows:
        by_family[row["family_id"]].append(row["physical_case_id"])
    groups: list[dict[str, Any]] = []
    for family in FAMILIES:
        ids = by_family[family]
        for start in range(0, len(ids), 8):
            batch = ids[start:start + 8]
            groups.append({
                "group_id": f"{family}-native-cause-audit-{start // 8 + 1:02d}",
                "family_id": family,
                "case_ids": batch,
                "case_count": len(batch),
                "max_cases": 8,
                "status": "PREPARED_NOT_LAUNCHED",
                "requires_parent_guard": True,
                "requires_new_attempt_identity": True,
                "content_reads_deferred": True,
            })
    return {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_METADATA_ONLY_NOT_LAUNCHED",
        "scope": {
            "historical_case_count": len(rows),
            "families": EXPECTED_FAMILY_COUNTS,
            "excludes_f3_fine512": True,
            "excludes_typed_particle_records_as_case_membership": True,
        },
        "deferred_content": [
            "native PartOut/Part*.bi4 bytes",
            "RunPARTs.csv/Run.out semantic contents",
            "typed H5 content only for an explicitly bound comparison",
        ],
        "hash_scope": {
            "inventory_hashes": "CURRENT336, union proof, and audit proof only",
            "case_artifact_hashes": "declared CURRENT/union values carried without recomputation",
            "native_h5_hashes": "DEFERRED_TO_PARENT_GUARDED_WORKER",
        },
        "existing_worker_reuse": worker_sources,
        "guard_budget": {
            "max_cases_per_attempt": 8,
            "cpu_workers": 1,
            "solver_or_scan_launch": False,
            "h5_content_opened_by_inventory": False,
            "native_content_opened_by_inventory": False,
            "estimated_output_cap_bytes": 2 * 1024 * 1024,
            "source_stat_only_preflight": True,
        },
        "groups": groups,
        "qualification": {
            "native_cause": "existing source evidence only; later worker may reconcile identity",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
    }


def build_inventory(
    *,
    current_path: Path,
    current_sha256: str,
    union_path: Path,
    union_sha256: str,
    audit_path: Path,
    audit_sha256: str,
    root192_case_id: str,
    root192_proof: Path | None,
    root192_proof_sha256: str | None,
    root192_summary: Path | None,
    root192_summary_sha256: str | None,
    max_input_bytes: int = DEFAULT_SMALL_JSON_LIMIT,
) -> dict[str, Any]:
    current, union, audit, refs = _validate_inputs(
        current_path, current_sha256, union_path, union_sha256,
        audit_path, audit_sha256, max_input_bytes=max_input_bytes)
    current_by_id: dict[str, tuple[int, dict[str, Any]]] = refs["current_by_id"]
    rows: list[dict[str, Any]] = []
    for item in sorted(union["native_evidence"], key=lambda value: (value["family_id"], value["physical_case_id"])):
        index, current_row = current_by_id[item["physical_case_id"]]
        rows.append(_case_entry(item, index, current_row))
    pilot_case = current_by_id.get(root192_case_id)
    if pilot_case is None:
        raise InventoryError(f"ROOT192 pilot case is absent from CURRENT336: {root192_case_id}")
    pilot_entry = next(row for row in rows if row["physical_case_id"] == root192_case_id)
    worker_sources = [
        _worker_source_ref(
            Path(__file__).resolve().with_name("ds_data02_stage2_native_identity_audit_v1.py"),
            "existing_native_identity_audit_worker",
        ),
        _worker_source_ref(
            Path(__file__).resolve().with_name("ds_data02_stage2_omission_forensics_v1.py"),
            "existing_omission_forensics_worker",
        ),
    ]
    output = {
        "schema": SCHEMA,
        "status": "SOURCE_INVENTORY_READY_METADATA_ONLY",
        "scope": {
            "historical_case_count": len(rows),
            "family_counts": EXPECTED_FAMILY_COUNTS,
            "source_population": "historical F2/F4/F6 omission registry only",
            "f3_fine512_included": False,
            "root192_typed_particle_records_added_as_cases": False,
        },
        "generator": {
            "script": str(Path(__file__).resolve()),
            "content_policy": {
                "current_union_audit_opened": True,
                "case_artifacts_opened": False,
                "h5_opened": False,
                "bi4_opened": False,
                "large_scientific_json_opened": False,
                "solver_started": False,
            },
        },
        "input_bindings": {
            "current": refs["current"],
            "historical_union": refs["union"],
            "historical_audit": refs["audit"],
            "audit_current_declaration": _declared_ref(audit.get("CURRENT"), "audit_CURRENT_alias_declaration"),
            "union_membership_index_declaration": _declared_ref(union.get("historical_membership_index"), "union_membership_index_declaration"),
        },
        "rows": rows,
        "root192_typed_pilot": _typed_pilot_contract(
            case_id=root192_case_id,
            case_entry=pilot_entry,
            proof_path=root192_proof,
            proof_sha=root192_proof_sha256,
            summary_path=root192_summary,
            summary_sha=root192_summary_sha256,
        ),
        "next_cause_audit_source_contract": _make_contract(rows, worker_sources),
        "interpretation": {
            "counts_are_not_cause": True,
            "native_report_reference_is_not_physical_fate": True,
            "physical_fate_and_dynamics": "UNKNOWN_FOR_ALL_ROWS",
            "typed_pilot_scope": "one physical case comparison contract only; no case-count expansion",
        },
    }
    return output


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise InventoryError(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--current-sha256", required=True)
    parser.add_argument("--membership-evidence", required=True, type=Path)
    parser.add_argument("--membership-sha256", required=True)
    parser.add_argument("--audit-evidence", required=True, type=Path)
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--root192-case-id", default="F2H10V2_OFFSET_V1")
    parser.add_argument("--root192-proof", type=Path)
    parser.add_argument("--root192-proof-sha256")
    parser.add_argument("--root192-summary", type=Path)
    parser.add_argument("--root192-summary-sha256")
    parser.add_argument("--max-input-bytes", type=int, default=DEFAULT_SMALL_JSON_LIMIT)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.max_input_bytes <= 0 or args.max_input_bytes > MAX_ALLOWED_INPUT_BYTES:
        raise InventoryError(
            f"--max-input-bytes must be in (0, {MAX_ALLOWED_INPUT_BYTES}]"
        )
    result = build_inventory(
        current_path=args.current.expanduser().resolve(),
        current_sha256=args.current_sha256,
        union_path=args.membership_evidence.expanduser().resolve(),
        union_sha256=args.membership_sha256,
        audit_path=args.audit_evidence.expanduser().resolve(),
        audit_sha256=args.audit_sha256,
        root192_case_id=args.root192_case_id,
        root192_proof=args.root192_proof.expanduser().resolve() if args.root192_proof else None,
        root192_proof_sha256=args.root192_proof_sha256,
        root192_summary=args.root192_summary.expanduser().resolve() if args.root192_summary else None,
        root192_summary_sha256=args.root192_summary_sha256,
        max_input_bytes=args.max_input_bytes,
    )
    _write_atomic(args.output.expanduser().resolve(), result)
    print(json.dumps({
        "status": result["status"],
        "output": str(args.output.expanduser().resolve()),
        "historical_case_count": result["scope"]["historical_case_count"],
        "family_counts": result["scope"]["family_counts"],
        "root192_status": result["root192_typed_pilot"]["status"],
        "solver_started": False,
        "h5_opened": False,
        "native_opened": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InventoryError as exc:
        raise SystemExit(f"InventoryError: {exc}")
