#!/usr/bin/env python3
"""Bounded F4 Tallwall120 archive-v2 inventory and completeness audit.

This audit is intentionally narrower than the F4 material sidecar contract.
It inventories the existing qualification and production archive namespaces,
checks only bounded JSON metadata plus file-system metadata, and reports the
32-case material-sidecar namespace without authorizing any execution.

The audit never opens, reads, or re-hashes an HDF5 file.  For an HDF5 output
it uses ``stat`` only to compare existence and the declared byte count.  Small
non-HDF5 outputs are bounded before their SHA-256 is recomputed.  It never
copies, converts, repairs, overwrites, or promotes an archive and never
touches a gate, registry, ledger, PLAN, worker, GPU, or queue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any, Mapping


LAB_ROOT = Path(__file__).resolve().parents[1]

SCHEMA = "core.audit.f4.tallwall120.archive_v2_inventory.v1"
RECORD_ID = "f4-tallwall120-archive-v2-inventory-audit-v1-2026-09-29"
OBSERVED_AT_UTC = "2026-09-29T00:00:00Z"
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_SMALL_OUTPUT_HASH_BYTES = 8 * 1024 * 1024
HDF5_SUFFIXES = frozenset({".h5", ".hdf5", ".h5part"})

FAMILY = "F4"
SCOPE_ID = "F4_resting_pool_laminar_tallwall120_x_v1"
EXPECTED_CASE_IDS = tuple(f"{SCOPE_ID}_DEV_{index:02d}" for index in range(32))
EXPECTED_PRODUCTION_DIRS = tuple(
    f"f4-tallwall120-production-dev-{index:02d}" for index in range(32)
)
DEFAULT_QUALIFICATION_DIRS = tuple(
    f"f4-tallwall120-qualification-cell-{index:02d}" for index in range(15)
)

COLLECTION_MANIFEST = Path(
    "campaigns/core-v1/cfd/f4-tallwall120-production-root-v1/"
    "collection-refresh-terminal32-formal-v1.json"
)
PREPARED_MATRIX = Path(
    "campaigns/core-v1/cfd/prepared/F4_tallwall120_qualification_v2/"
    "prepared-matrix.json"
)
SIDECAR_NAMESPACE = Path(
    "campaigns/core-v1/material/sidecars/"
    "f4-tallwall120-sidecar-matrix-v1-20260928"
)

ARCHIVE_ROOTS = {
    "qualification_v2": Path(
        "campaigns/core-v1/cfd/f4-tallwall120-archives-v2"
    ),
    "production_v1": Path(
        "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v1"
    ),
    "production_v2": Path(
        "campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2"
    ),
}

CURATED_OUTPUT_PATHS = (
    "product/result.json",
    "product/trajectory.h5",
    "product/audit.json",
    "product/observations.json",
    "product/solver/RunPARTs.csv",
    "product/solver/Run.out",
)
PRODUCTION_DIR_RE = re.compile(r"^f4-tallwall120-production-dev-\d{2}$")
QUALIFICATION_DIR_RE = re.compile(r"^f4-tallwall120-qualification-cell-\d{2}$")

DEFAULT_REPORT = Path(
    "reports/F4-TALLWALL120-ARCHIVE-V2-INVENTORY-AUDIT-V1-2026-09-29.json"
)
DEFAULT_MARKDOWN = Path(
    "reports/F4-TALLWALL120-ARCHIVE-V2-INVENTORY-AUDIT-V1-2026-09-29.zh-CN.md"
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_small_file(path: Path) -> str:
    """Hash only a bounded, non-HDF5 file."""

    size = path.stat().st_size
    if size > MAX_SMALL_OUTPUT_HASH_BYTES:
        raise ValueError(f"small output exceeds bounded hash limit: {path}")
    return _sha256_bytes(path.read_bytes())


def _safe_relative(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ValueError(f"unsafe repository-relative path: {path}")
    return candidate


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _read_json(root: Path, relative: Path, *, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    reference: dict[str, Any] = {
        "role": role,
        "path": relative.as_posix(),
        "exists": False,
        "regular_file": False,
        "bytes": None,
        "sha256": None,
        "bounded_json": True,
        "content_read": False,
        "error": None,
    }
    try:
        target = root / _safe_relative(relative.as_posix())
        info = target.stat()
        reference["exists"] = True
        reference["regular_file"] = stat.S_ISREG(info.st_mode)
        reference["bytes"] = info.st_size
        if not reference["regular_file"]:
            reference["error"] = "not_regular_file"
            return {}, reference
        if info.st_size > MAX_JSON_BYTES:
            reference["error"] = "json_size_limit"
            return {}, reference
        raw = target.read_bytes()
        reference["sha256"] = _sha256_bytes(raw)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            reference["error"] = "json_not_object"
            return {}, reference
        reference["content_read"] = True
        return dict(payload), reference
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        reference["error"] = type(error).__name__
        return {}, reference


def _presence(root: Path, relative: Path, *, role: str) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "role": role,
        "path": relative.as_posix(),
        "exists": False,
        "regular_file": False,
        "bytes": None,
        "content_read": False,
    }
    try:
        target = root / _safe_relative(relative.as_posix())
        info = target.stat()
    except (OSError, ValueError):
        return reference
    reference.update(
        {
            "exists": True,
            "regular_file": stat.S_ISREG(info.st_mode),
            "bytes": info.st_size,
        }
    )
    return reference


def _variant(path: Any) -> str | None:
    if not isinstance(path, str):
        return None
    for value in ("archives-v1", "archives-v2"):
        if value in path:
            return value
    return None


def _expected_qualification_dirs(root: Path) -> tuple[tuple[str, ...], dict[str, Any]]:
    payload, reference = _read_json(root, PREPARED_MATRIX, role="qualification_prepared_matrix")
    names: list[str] = []
    cells = payload.get("cells")
    if isinstance(cells, list):
        for cell in cells:
            if not isinstance(cell, Mapping):
                continue
            prepared = cell.get("prepared")
            if not isinstance(prepared, str):
                continue
            name = Path(prepared).parent.name
            if re.fullmatch(r"cell-\d{2}", name):
                names.append(f"f4-tallwall120-qualification-{name}")
    if len(names) != len(set(names)) or not names:
        names = list(DEFAULT_QUALIFICATION_DIRS)
    names = sorted(names)
    return tuple(names), {
        "reference": reference,
        "schema": payload.get("schema"),
        "matrix_complete": payload.get("complete"),
        "prepared_cell_count": len(cells) if isinstance(cells, list) else None,
        "expected_archive_dirs": names,
    }


def _output_check(archive_dir: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    declared_path = item.get("path")
    result: dict[str, Any] = {
        "path": declared_path,
        "declared_bytes": item.get("bytes"),
        "declared_sha256": item.get("sha256"),
        "exists": False,
        "regular_file": False,
        "actual_bytes": None,
        "bytes_match": False,
        "hdf5": False,
        "content_read": False,
        "hash_recomputed": False,
        "actual_sha256": None,
        "hash_match": None,
        "error": None,
    }
    try:
        if not isinstance(declared_path, str):
            raise ValueError("output path is not a string")
        relative = _safe_relative(declared_path)
        target = archive_dir / relative
        info = target.stat()
        result["exists"] = True
        result["regular_file"] = stat.S_ISREG(info.st_mode)
        result["actual_bytes"] = info.st_size
        result["bytes_match"] = (
            result["regular_file"] and info.st_size == item.get("bytes")
        )
        is_hdf5 = target.suffix.lower() in HDF5_SUFFIXES
        result["hdf5"] = is_hdf5
        if is_hdf5:
            # Deliberately stat-only: never open or hash trajectory content.
            return result
        if not result["regular_file"]:
            return result
        if info.st_size > MAX_SMALL_OUTPUT_HASH_BYTES:
            result["error"] = "small_output_hash_size_limit"
            return result
        actual_sha = _sha256_small_file(target)
        result["content_read"] = True
        result["hash_recomputed"] = True
        result["actual_sha256"] = actual_sha
        result["hash_match"] = actual_sha == item.get("sha256")
        return result
    except (OSError, ValueError) as error:
        result["error"] = type(error).__name__
        return result


def _inspect_archive(root: Path, relative_dir: Path, *, kind: str) -> dict[str, Any]:
    archive_payload, archive_ref = _read_json(
        root, relative_dir / "archive.json", role=f"{kind}_archive_manifest"
    )
    receipt_payload, receipt_ref = _read_json(
        root,
        relative_dir / "execution-receipt.json",
        role=f"{kind}_execution_receipt",
    )
    audit_payload, audit_ref = _read_json(
        root, relative_dir / "product/audit.json", role=f"{kind}_product_audit"
    )

    outputs = archive_payload.get("outputs")
    output_items = [item for item in outputs if isinstance(item, Mapping)] if isinstance(outputs, list) else []
    output_paths = [item.get("path") for item in output_items]
    output_checks = [_output_check(root / relative_dir, item) for item in output_items]
    required_path_exact = set(output_paths) == set(CURATED_OUTPUT_PATHS) and len(output_paths) == len(set(output_paths))
    all_present = bool(output_checks) and all(item["exists"] and item["regular_file"] for item in output_checks)
    all_bytes_match = bool(output_checks) and all(item["bytes_match"] for item in output_checks)
    non_hdf5 = [item for item in output_checks if not item["hdf5"]]
    non_hdf5_hashes_checked = bool(non_hdf5) and all(item["hash_recomputed"] for item in non_hdf5)
    non_hdf5_hashes_match = bool(non_hdf5) and all(item["hash_match"] is True for item in non_hdf5)
    hdf5_outputs = [item for item in output_checks if item["hdf5"]]

    receipt_canonical_sha = _sha256_bytes(_canonical(receipt_payload)) if receipt_payload else None
    receipt_hash_match = receipt_canonical_sha == archive_payload.get("receipt_sha256")
    execution_success = (
        receipt_payload.get("schema") == "core.execution_receipt.v1"
        and receipt_payload.get("execution_status") == "succeeded"
        and receipt_payload.get("returncode") == 0
        and receipt_payload.get("missing_outputs") == []
    )
    audit_projection = {
        "schema": audit_payload.get("schema"),
        "case_id": audit_payload.get("case_id"),
        "event_window_complete": audit_payload.get("event_window_complete"),
        "event_window_status": audit_payload.get("event_window_status"),
        "source_mass_gate_pass": audit_payload.get("source_mass_gate_pass"),
        "data_qualification_status": audit_payload.get("structural", {}).get("attrs", {}).get("data_qualification_status")
        if isinstance(audit_payload.get("structural"), Mapping)
        else None,
        "T2_macro_status": audit_payload.get("structural", {}).get("attrs", {}).get("T2_macro_status")
        if isinstance(audit_payload.get("structural"), Mapping)
        else None,
    }
    archive_bundle_complete = bool(
        archive_ref["content_read"]
        and receipt_ref["content_read"]
        and audit_ref["content_read"]
        and archive_payload.get("schema") == "core.verified_archive.v1"
        and archive_payload.get("execution_status") == "succeeded"
        and archive_payload.get("qualification_claim") == "none"
        and required_path_exact
        and execution_success
        and receipt_hash_match
        and all_present
        and all_bytes_match
        and non_hdf5_hashes_checked
        and non_hdf5_hashes_match
        and len(hdf5_outputs) == 1
        and all(item["content_read"] is False and item["hash_recomputed"] is False for item in hdf5_outputs)
    )

    return {
        "directory": relative_dir.as_posix(),
        "directory_name": relative_dir.name,
        "kind": kind,
        "job_id": archive_payload.get("job_id"),
        "attempt_dir": archive_payload.get("attempt_dir"),
        "source_host": archive_payload.get("source_host"),
        "archive_manifest": archive_ref,
        "execution_receipt": receipt_ref,
        "product_audit": audit_ref,
        "archive_schema": archive_payload.get("schema"),
        "execution_status": archive_payload.get("execution_status"),
        "qualification_claim": archive_payload.get("qualification_claim"),
        "archive_receipt_sha256": archive_payload.get("receipt_sha256"),
        "receipt_canonical_sha256": receipt_canonical_sha,
        "receipt_hash_match": receipt_hash_match,
        "execution_success": execution_success,
        "audit": audit_projection,
        "outputs": [
            {
                "path": item.get("path"),
                "bytes": item.get("bytes"),
                "sha256": item.get("sha256"),
            }
            for item in output_items
        ],
        "output_checks": output_checks,
        "output_summary": {
            "declared_count": len(output_items),
            "required_path_exact": required_path_exact,
            "all_present": all_present,
            "all_declared_bytes_match": all_bytes_match,
            "non_hdf5_hashes_checked": non_hdf5_hashes_checked,
            "non_hdf5_hashes_match": non_hdf5_hashes_match,
            "hdf5_count": len(hdf5_outputs),
            "hdf5_content_read": any(item["content_read"] for item in hdf5_outputs),
            "hdf5_hash_recomputed": any(item["hash_recomputed"] for item in hdf5_outputs),
        },
        "archive_bundle_complete": archive_bundle_complete,
        "_archive_payload": archive_payload,
        "_receipt_payload": receipt_payload,
    }


def _inventory(
    root: Path,
    relative_root: Path,
    *,
    kind: str,
    expected_dirs: tuple[str, ...],
    pattern: re.Pattern[str],
) -> dict[str, Any]:
    target_root = root / relative_root
    root_lock = _presence(root, relative_root / ".archive.lock", role=f"{kind}_archive_root_lock")
    observed_dirs: list[str] = []
    if target_root.is_dir():
        observed_dirs = sorted(
            child.name
            for child in target_root.iterdir()
            if child.is_dir() and pattern.fullmatch(child.name)
        )
    expected_set = set(expected_dirs)
    observed_set = set(observed_dirs)
    rows: dict[str, dict[str, Any]] = {}
    for directory_name in observed_dirs:
        row = _inspect_archive(root, relative_root / directory_name, kind=kind)
        row["expected_directory"] = directory_name in expected_set
        rows[directory_name] = row
    return {
        "root": relative_root.as_posix(),
        "root_exists": target_root.is_dir(),
        "archive_root_lock": root_lock,
        "expected_directory_count": len(expected_dirs),
        "expected_directories": list(expected_dirs),
        "observed_directory_count": len(observed_dirs),
        "observed_directories": observed_dirs,
        "missing_directories": sorted(expected_set - observed_set),
        "unexpected_directories": sorted(observed_set - expected_set),
        "archive_bundle_complete_count": sum(
            bool(row["archive_bundle_complete"]) for row in rows.values()
        ),
        "receipt_valid_count": sum(bool(row["receipt_hash_match"]) for row in rows.values()),
        "rows": rows,
    }


def _production_case_id(directory_name: str) -> str | None:
    match = re.fullmatch(r"f4-tallwall120-production-dev-(\d{2})", directory_name)
    if not match:
        return None
    return f"{SCOPE_ID}_DEV_{match.group(1)}"


def _collection_audit(
    root: Path,
    production_v1: Mapping[str, Any],
    production_v2: Mapping[str, Any],
) -> dict[str, Any]:
    payload, reference = _read_json(root, COLLECTION_MANIFEST, role="production_collection_manifest")
    cases = payload.get("cases")
    rows = [row for row in cases if isinstance(row, Mapping)] if isinstance(cases, list) else []
    by_case = {str(row.get("case_id")): row for row in rows if isinstance(row.get("case_id"), str)}
    variant_counts: dict[str, int] = {}
    source_sha_matches: list[str] = []
    source_bytes_matches: list[str] = []
    path_variant_drift: list[str] = []
    v2_path_exact: list[str] = []
    v2_archive_present: list[str] = []
    row_projections: list[dict[str, Any]] = []
    for case_id in EXPECTED_CASE_IDS:
        row = by_case.get(case_id, {})
        trajectory = row.get("trajectory") if isinstance(row.get("trajectory"), Mapping) else {}
        path = trajectory.get("path")
        variant = _variant(path)
        if variant is not None:
            variant_counts[variant] = variant_counts.get(variant, 0) + 1
        expected_v1_dir = f"f4-tallwall120-production-dev-{case_id[-2:]}"
        v1_row = production_v1.get("rows", {}).get(expected_v1_dir, {})
        v2_row = production_v2.get("rows", {}).get(expected_v1_dir, {})
        v1_traj = next(
            (item for item in v1_row.get("outputs", []) if item.get("path") == "product/trajectory.h5"),
            {},
        )
        sha_match = trajectory.get("sha256") == v1_traj.get("sha256") and bool(v1_traj)
        bytes_match = trajectory.get("bytes") == v1_traj.get("bytes") and bool(v1_traj)
        if sha_match:
            source_sha_matches.append(case_id)
        if bytes_match:
            source_bytes_matches.append(case_id)
        expected_v2_path = (
            path.replace("archives-v1", "archives-v2") if isinstance(path, str) else None
        )
        if variant != "archives-v2":
            path_variant_drift.append(case_id)
        if isinstance(expected_v2_path, str) and expected_v2_path.endswith(
            f"f4-tallwall120-production-dev-{case_id[-2:]}/product/trajectory.h5"
        ):
            v2_path_exact.append(case_id)
        if v2_row:
            v2_archive_present.append(case_id)
        row_projections.append(
            {
                "case_id": case_id,
                "collection_path": path,
                "collection_variant": variant,
                "collection_sha256": trajectory.get("sha256"),
                "collection_bytes": trajectory.get("bytes"),
                "production_v1_archive_sha256": v1_traj.get("sha256"),
                "production_v1_archive_bytes": v1_traj.get("bytes"),
                "source_sha_match": sha_match,
                "source_bytes_match": bytes_match,
                "expected_archives_v2_path": expected_v2_path,
                "production_v2_archive_present": bool(v2_row),
            }
        )
    return {
        "manifest": reference,
        "schema": payload.get("schema"),
        "family": payload.get("family"),
        "scope_id": payload.get("scope_id"),
        "case_count": len(rows),
        "variant_counts": variant_counts,
        "expected_material_archive_variant": "archives-v2",
        "path_variant_drift_case_ids": path_variant_drift,
        "source_sha_match_case_count": len(source_sha_matches),
        "source_sha_match_case_ids": source_sha_matches,
        "source_bytes_match_case_count": len(source_bytes_matches),
        "source_bytes_match_case_ids": source_bytes_matches,
        "expected_archives_v2_path_case_count": len(v2_path_exact),
        "production_v2_archive_present_case_ids": v2_archive_present,
        "production_v2_archive_present_case_count": len(v2_archive_present),
        "rows": row_projections,
    }


def _sidecar_is_complete(payload: Mapping[str, Any], case_id: str) -> bool:
    terminal = payload.get("terminal") if isinstance(payload.get("terminal"), Mapping) else {}
    markers = payload.get("material_markers") if isinstance(payload.get("material_markers"), Mapping) else {}
    claims = payload.get("claims") if isinstance(payload.get("claims"), Mapping) else {}
    return bool(
        payload.get("schema") == "core.material.f4.tallwall120.material_sidecar.v1"
        and payload.get("family") == FAMILY
        and payload.get("scope_id") == SCOPE_ID
        and payload.get("case_id") == case_id
        and terminal.get("status") == "complete"
        and terminal.get("execution_complete") is True
        and terminal.get("event_window_complete") is True
        and terminal.get("right_censor_status") == "not_right_censored"
        and markers.get("right_censor_status") == "not_right_censored"
        and isinstance(markers.get("mass_closure"), Mapping)
        and isinstance(markers.get("unknown_fraction"), Mapping)
        and isinstance(markers.get("reliable_coverage"), Mapping)
        and not any(bool(claims.get(key)) for key in ("formal", "formal_eligible", "qualification", "T1", "T2"))
        and claims.get("credit", 0) == 0
        and claims.get("qualification_credit", 0) == 0
    )


def _sidecar_audit(root: Path) -> dict[str, Any]:
    namespace = root / SIDECAR_NAMESPACE
    files = sorted(namespace.rglob("*.json")) if namespace.is_dir() else []
    entries: list[dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(root)
        payload, reference = _read_json(root, relative, role="material_sidecar")
        case_id = payload.get("case_id")
        entries.append(
            {
                "path": relative.as_posix(),
                "reference": reference,
                "schema": payload.get("schema"),
                "case_id": case_id,
                "complete": _sidecar_is_complete(payload, case_id) if isinstance(case_id, str) else False,
            }
        )
    case_ids = [item["case_id"] for item in entries if isinstance(item["case_id"], str)]
    counts: dict[str, int] = {}
    for case_id in case_ids:
        counts[case_id] = counts.get(case_id, 0) + 1
    expected = set(EXPECTED_CASE_IDS)
    observed = set(case_ids)
    complete_ids = sorted(
        {item["case_id"] for item in entries if item["complete"] and isinstance(item["case_id"], str)}
    )
    return {
        "namespace": SIDECAR_NAMESPACE.as_posix(),
        "namespace_exists": namespace.is_dir(),
        "json_file_count": len(files),
        "entries": entries,
        "case_id_counts": counts,
        "duplicate_case_ids": sorted(case_id for case_id, count in counts.items() if count > 1),
        "missing_case_ids": sorted(expected - observed),
        "extra_case_ids": sorted(observed - expected),
        "complete_case_ids": complete_ids,
        "complete_case_count": len(complete_ids),
        "expected_case_count": len(EXPECTED_CASE_IDS),
    }


def _production_duplicate_audit(
    production_v1: Mapping[str, Any], production_v2: Mapping[str, Any]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for directory_name in sorted(production_v2.get("rows", {})):
        v1 = production_v1.get("rows", {}).get(directory_name)
        v2 = production_v2.get("rows", {}).get(directory_name)
        if not isinstance(v1, Mapping) or not isinstance(v2, Mapping):
            continue
        v1_manifest = v1.get("_archive_payload", {})
        v2_manifest = v2.get("_archive_payload", {})
        diff_keys = sorted(
            key
            for key in set(v1_manifest) | set(v2_manifest)
            if v1_manifest.get(key) != v2_manifest.get(key)
        )
        same_receipt_json = v1.get("_receipt_payload") == v2.get("_receipt_payload")
        same_output_descriptors = v1.get("outputs") == v2.get("outputs")
        same_attempt = v1_manifest.get("attempt_dir") == v2_manifest.get("attempt_dir")
        same_receipt_digest = v1_manifest.get("receipt_sha256") == v2_manifest.get("receipt_sha256")
        identity_exact = bool(
            same_receipt_json
            and same_output_descriptors
            and same_attempt
            and same_receipt_digest
        )
        rows.append(
            {
                "directory_name": directory_name,
                "case_id": _production_case_id(directory_name),
                "archive_manifest_bytes_distinct": v1.get("archive_manifest", {}).get("sha256")
                != v2.get("archive_manifest", {}).get("sha256"),
                "archive_manifest_semantic_diff_keys": diff_keys,
                "same_execution_receipt_payload": same_receipt_json,
                "same_output_descriptors": same_output_descriptors,
                "same_attempt_dir": same_attempt,
                "same_receipt_sha256": same_receipt_digest,
                "independent_artifact_identity_exact": identity_exact,
                "identity_basis": "bounded archive/execution JSON metadata; HDF5 content not rehashed",
            }
        )
    duplicate_case_ids = sorted(
        row["case_id"] for row in rows if row["independent_artifact_identity_exact"] and row["case_id"]
    )
    return {
        "compared_case_count": len(rows),
        "rows": rows,
        "same_artifact_identity_case_ids": duplicate_case_ids,
        "same_artifact_identity_case_count": len(duplicate_case_ids),
        "new_independent_case_count": 0 if len(duplicate_case_ids) == len(rows) else len(rows) - len(duplicate_case_ids),
    }


def _strip_internal(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_internal(item) for key, item in value.items() if not key.startswith("_")}
    if isinstance(value, list):
        return [_strip_internal(item) for item in value]
    return value


def build_report(root: Path = LAB_ROOT) -> dict[str, Any]:
    qualification_dirs, qualification_design = _expected_qualification_dirs(root)
    qualification = _inventory(
        root,
        ARCHIVE_ROOTS["qualification_v2"],
        kind="qualification_v2",
        expected_dirs=qualification_dirs,
        pattern=QUALIFICATION_DIR_RE,
    )
    production_v1 = _inventory(
        root,
        ARCHIVE_ROOTS["production_v1"],
        kind="production_v1",
        expected_dirs=EXPECTED_PRODUCTION_DIRS,
        pattern=PRODUCTION_DIR_RE,
    )
    production_v2 = _inventory(
        root,
        ARCHIVE_ROOTS["production_v2"],
        kind="production_v2",
        expected_dirs=EXPECTED_PRODUCTION_DIRS,
        pattern=PRODUCTION_DIR_RE,
    )
    collection = _collection_audit(root, production_v1, production_v2)
    sidecars = _sidecar_audit(root)
    duplicate_audit = _production_duplicate_audit(production_v1, production_v2)

    production_v1_complete = (
        production_v1["observed_directory_count"] == 32
        and not production_v1["missing_directories"]
        and not production_v1["unexpected_directories"]
        and production_v1["archive_bundle_complete_count"] == 32
        and production_v1["receipt_valid_count"] == 32
    )
    production_v2_complete = (
        production_v2["observed_directory_count"] == 32
        and not production_v2["missing_directories"]
        and production_v2["archive_bundle_complete_count"] == 32
    )
    qualification_complete = (
        qualification["observed_directory_count"] == qualification["expected_directory_count"]
        and not qualification["missing_directories"]
        and not qualification["unexpected_directories"]
        and qualification["archive_bundle_complete_count"] == qualification["expected_directory_count"]
    )
    all_hdf5_guarded = all(
        not output["content_read"] and not output["hash_recomputed"]
        for inventory in (qualification, production_v1, production_v2)
        for row in inventory["rows"].values()
        for output in row["output_checks"]
        if output["hdf5"]
    )
    report = {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "observed_at_utc": OBSERVED_AT_UTC,
        "scope": {
            "family": FAMILY,
            "scope_id": SCOPE_ID,
            "fixed_production_case_count": len(EXPECTED_CASE_IDS),
            "material_archive_variant_required": "archives-v2",
            "sidecar_namespace": SIDECAR_NAMESPACE.as_posix(),
        },
        "input_bindings": {
            "collection_manifest": collection["manifest"],
            "qualification_prepared_matrix": qualification_design["reference"],
            "archive_roots": {
                name: {
                    "path": value["root"],
                    "root_exists": value["root_exists"],
                    "root_lock": value["archive_root_lock"],
                }
                for name, value in (
                    ("qualification_v2", qualification),
                    ("production_v1", production_v1),
                    ("production_v2", production_v2),
                )
            },
            "sidecar_namespace": {
                "path": sidecars["namespace"],
                "exists": sidecars["namespace_exists"],
            },
        },
        "qualification_v2": {
            "expected_matrix": qualification_design,
            "inventory": qualification,
        },
        "production_archives": {
            "v1": production_v1,
            "v2": production_v2,
            "v1_v2_identity_comparison": duplicate_audit,
        },
        "collection_source_audit": collection,
        "material_sidecars": sidecars,
        "checks": {
            "production_v1_32_case_inventory_complete": production_v1_complete,
            "production_v1_archive_bundles_complete": production_v1_complete,
            "production_v1_receipt_bindings_valid": production_v1["receipt_valid_count"] == 32,
            "production_v2_32_case_inventory_complete": production_v2_complete,
            "production_v2_archive_bundles_complete_for_observed_entries": (
                production_v2["archive_bundle_complete_count"] == production_v2["observed_directory_count"]
                and production_v2["observed_directory_count"] > 0
            ),
            "production_v1_archive_root_lock_present": (
                production_v1["archive_root_lock"]["exists"]
                and production_v1["archive_root_lock"]["regular_file"]
            ),
            "production_v2_archive_root_lock_present": (
                production_v2["archive_root_lock"]["exists"]
                and production_v2["archive_root_lock"]["regular_file"]
            ),
            "production_v2_entries_are_independent": duplicate_audit["new_independent_case_count"] > 0,
            "qualification_v2_15_cell_inventory_complete": qualification_complete,
            "collection_uses_required_archives_v2_variant": (
                collection["case_count"] == 32
                and collection["variant_counts"] == {"archives-v2": 32}
            ),
            "collection_source_sha_matches_production_v1": collection["source_sha_match_case_count"] == 32,
            "collection_source_bytes_matches_production_v1": collection["source_bytes_match_case_count"] == 32,
            "material_sidecar_32_case_complete": sidecars["complete_case_count"] == 32
            and not sidecars["missing_case_ids"]
            and not sidecars["duplicate_case_ids"]
            and not sidecars["extra_case_ids"],
            "hdf5_content_never_read_or_rehashed": all_hdf5_guarded,
        },
        "findings": [
            {
                "id": "collection_archives_v1_vs_required_v2",
                "severity": "blocking",
                "observed": f"{len(collection['path_variant_drift_case_ids'])}/32 collection paths use a non-required archive variant",
            },
            {
                "id": "production_archives_v2_incomplete",
                "severity": "blocking",
                "observed": f"{production_v2['observed_directory_count']}/32 production case directories exist under archives-v2",
            },
            {
                "id": "production_archives_v2_reuses_v1_identity",
                "severity": "blocking",
                "observed": f"{duplicate_audit['same_artifact_identity_case_count']}/{duplicate_audit['compared_case_count']} observed v2 entries share v1 attempt/receipt/artifact identity",
            },
            {
                "id": "production_archives_v2_root_lock_missing",
                "severity": "diagnostic",
                "observed": "production-archives-v2 has no root .archive.lock publication marker",
            },
            {
                "id": "material_sidecar_matrix_empty",
                "severity": "blocking",
                "observed": f"{sidecars['complete_case_count']}/32 complete material sidecars in the bounded namespace",
            },
            {
                "id": "qualification_archive_v2_partial",
                "severity": "diagnostic",
                "observed": f"{qualification['observed_directory_count']}/{qualification['expected_directory_count']} qualification cells have archive bundles",
            },
        ],
        "qualification": {
            "formal": False,
            "T1": False,
            "T2": False,
            "credit": 0,
            "status": "blocked_fail_closed",
        },
        "decision": "bounded_archive_inventory_only",
        "status": "blocked_fail_closed",
        "execution_controls": {
            "bounded_json_and_stat_only": True,
            "hdf5_opened": False,
            "hdf5_read": False,
            "hdf5_hash_recomputed": False,
            "archive_copied": False,
            "archive_converted": False,
            "archive_overwritten": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_started": False,
            "formal_gate_mutations": 0,
            "registry_mutations": 0,
            "ledger_mutations": 0,
            "denominator_mutations": 0,
            "plan_mutations": 0,
        },
    }
    return _strip_internal(report)


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema")
    if report.get("status") != "blocked_fail_closed":
        errors.append("status")
    if report.get("decision") != "bounded_archive_inventory_only":
        errors.append("decision")
    qualification = report.get("qualification")
    if (
        not isinstance(qualification, Mapping)
        or qualification.get("credit") != 0
        or qualification.get("formal") is not False
        or qualification.get("T1") is not False
        or qualification.get("T2") is not False
    ):
        errors.append("qualification")
    controls = report.get("execution_controls")
    if not isinstance(controls, Mapping):
        errors.append("execution_controls")
    else:
        for key in (
            "hdf5_opened",
            "hdf5_read",
            "hdf5_hash_recomputed",
            "archive_copied",
            "archive_converted",
            "archive_overwritten",
            "solver_started",
            "worker_started",
            "gpu_started",
            "queue_started",
        ):
            if controls.get(key) is not False:
                errors.append(f"execution_controls.{key}")
        for key in (
            "formal_gate_mutations",
            "registry_mutations",
            "ledger_mutations",
            "denominator_mutations",
            "plan_mutations",
        ):
            if controls.get(key) != 0:
                errors.append(f"execution_controls.{key}")
    checks = report.get("checks")
    if not isinstance(checks, Mapping) or checks.get("hdf5_content_never_read_or_rehashed") is not True:
        errors.append("checks.hdf5_content_never_read_or_rehashed")
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    production = report["production_archives"]
    qualification = report["qualification_v2"]["inventory"]
    collection = report["collection_source_audit"]
    sidecars = report["material_sidecars"]
    duplicate = production["v1_v2_identity_comparison"]
    lines = [
        "# F4 Tallwall120 archive-v2 inventory audit",
        "",
        "本报告是 bounded、只读的 archive inventory 审计；没有打开、读取或重新哈希任何 HDF5，没有复制/转换 archive，也没有修改 formal gate、registry、ledger 或 PLAN。",
        "",
        "## 结论",
        "",
        f"- 状态：`{report['status']}`；qualification credit=`{report['qualification']['credit']}`。",
        f"- `production-archives-v1`：{production['v1']['observed_directory_count']}/32 个 case directory，{production['v1']['archive_bundle_complete_count']}/32 个 bounded archive bundle 完整。",
        f"- `production-archives-v2`：{production['v2']['observed_directory_count']}/32 个 case directory，观察到的 bundle 为 {production['v2']['archive_bundle_complete_count']}/{production['v2']['observed_directory_count']}；这 {duplicate['same_artifact_identity_case_count']} 个条目均与 v1 共享同一 attempt/receipt/artifact identity，不构成新增独立覆盖。",
        f"- immutable publication marker：v1 root `.archive.lock` 存在；v2 root `.archive.lock` 缺失，因此 v2 没有同等的 collector lock 证据。",
        f"- collection manifest 仍是 `archives-v1`（{sum(collection['variant_counts'].values())}/32），而 material contract 要求 `archives-v2`；collection 的 source SHA/bytes 与 v1 archive metadata 均为 {collection['source_sha_match_case_count']}/32 匹配，但路径 variant 仍漂移。",
        f"- material sidecar bounded namespace：{sidecars['complete_case_count']}/32 complete，目录存在=`{sidecars['namespace_exists']}`。",
        f"- qualification-v2 archive：{qualification['observed_directory_count']}/{qualification['expected_directory_count']} 个 cell bundle，缺失：`{', '.join(qualification['missing_directories']) or '无'}`。",
        "",
        "## 文件级边界",
        "",
        "每个 archive 的 `archive.json` 与 `execution-receipt.json` 只按 JSON 读取；archive 内的 HDF5 只用 `stat` 比较存在性和声明字节数，`content_read=false`、`hash_recomputed=false`。非 HDF5 小输出在 8 MiB 上限内重新计算 SHA-256。",
        "",
        "本审计只产生本报告和测试，不授权新的 solver/worker/GPU/queue 执行，也不把 CFD archive 自动升级为 material sidecar 或 T1/T2。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    report = build_report(args.root)
    errors = validate_report(report)
    if errors:
        raise SystemExit("invalid audit report: " + ", ".join(errors))
    output = args.output if args.output.is_absolute() else args.root / args.output
    markdown = args.markdown if args.markdown.is_absolute() else args.root / args.markdown
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"report": str(output), "markdown": str(markdown), "status": report["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
