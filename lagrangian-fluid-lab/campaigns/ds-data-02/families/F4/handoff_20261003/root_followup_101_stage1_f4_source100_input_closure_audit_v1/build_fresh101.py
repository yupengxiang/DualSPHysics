#!/usr/bin/env python3
"""Audit source100 non-scientific input digests.

The audit reads source100 request JSON, JSON/XML/Python metadata inputs,
Root547 manifests, current JSON execution receipts, and the Root561 review.
It skips BI4/H5/CSV/DAT/VTK-family paths before opening them.  It never
changes source099/source100, starts a job, or reads a scientific payload.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f4/DualSPHysics").resolve()
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics").resolve()
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02").resolve()
PACKAGE = Path(__file__).resolve().parent
SOURCE100 = WORKTREE / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F4/"
    "handoff_20261003/root_followup_100_stage1_f4_actual_root547_xmf_root023_render_v1"
)
ROOT561_REVIEW = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f4_actualtyped533_XMF547_all24_independent_review_561/"
    "actual-root-all24-full1201-typed-XMF-review.json"
)
ROOT570_REVIEW = INTEGRATION / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_f4_fresh100_exact_actualXMF547_adoption_570/"
    "actual-source-adoption-review.json"
)

SCOPE = "root_followup_101_stage1_f4_source100_input_closure_audit_v1"
RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".vtp"}
STATIC_SUFFIXES = {"", ".json", ".jsonl", ".xml", ".xmf", ".py", ".md", ".txt", ".log"}


def load_json(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise RuntimeError(f"scientific payload read refused: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def sha_static(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES:
        raise RuntimeError(f"scientific payload hash refused: {path}")
    if path.suffix.lower() not in STATIC_SUFFIXES:
        raise RuntimeError(f"non-static input hash refused: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path) -> dict[str, str] | None:
    path = Path(path).resolve()
    if not path.is_file():
        return None
    return {"path": str(path), "sha256": sha_static(path)}


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def root561_rows() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    review = load_json(ROOT561_REVIEW)
    rows: dict[str, dict[str, Any]] = {}
    for row in review.get("rows", []):
        if isinstance(row, dict) and row.get("case_id"):
            rows[str(row["case_id"])] = row
    if len(rows) != 24:
        raise RuntimeError(f"Root561 rows expected 24, found {len(rows)}")
    return rows, {
        "path": str(ROOT561_REVIEW),
        "sha256": sha_static(ROOT561_REVIEW),
    }


def selected_root561_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "case_id",
        "physical_case_id",
        "request",
        "request_sha256",
        "XMF_receipt",
        "XMF_receipt_sha256",
        "manifest",
        "manifest_sha256",
        "case_xmf",
        "case_xmf_sha256",
        "actual_full1201_N3",
        "actual_time_s_summary",
        "actual_initial_UID_axis",
        "max_missing_native_UID",
        "original_lifecycle_exclusions_retained_no_padding",
        "source_and_legacy_converter_scope_remain_separate",
        "actual_allframe_render_and_visual_pending",
    )
    return {key: row.get(key) for key in keys if key in row}


def audit_request(path: Path, root561: dict[str, dict[str, Any]]) -> dict[str, Any]:
    request = load_json(path)
    case_id = str(request["case_id"])
    checked: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    skipped_science_extensions: dict[str, int] = {}
    for raw_path, expected in sorted((request.get("input_sha256") or {}).items()):
        input_path = Path(str(raw_path)).resolve()
        suffix = input_path.suffix.lower()
        if suffix in RAW_SUFFIXES:
            skipped_science_extensions[suffix] = skipped_science_extensions.get(suffix, 0) + 1
            continue
        if suffix not in STATIC_SUFFIXES:
            unsupported.append({"path": str(input_path), "suffix": suffix, "expected_sha256": expected})
            continue
        if not input_path.is_file():
            row = {
                "path": str(input_path),
                "status": "missing",
                "expected_sha256": expected,
                "actual_sha256": None,
            }
            checked.append(row)
            missing.append(row)
            continue
        actual = sha_static(input_path)
        status = "match" if actual == expected else "mismatch"
        row = {
            "path": str(input_path),
            "status": status,
            "expected_sha256": expected,
            "actual_sha256": actual,
        }
        checked.append(row)
        if status == "mismatch":
            mismatches.append(row)

    manifest_paths = [
        Path(str(raw)).resolve()
        for raw in request.get("input_files", [])
        if str(raw).endswith("/manifest.json") and "-root547/" in str(raw)
    ]
    manifest_path = manifest_paths[0] if len(manifest_paths) == 1 else None
    manifest = load_json(manifest_path) if manifest_path and manifest_path.is_file() else None
    typed_receipt_path = (
        Path(str(manifest["typed_receipt"])).resolve()
        if manifest and isinstance(manifest.get("typed_receipt"), str)
        else None
    )
    actual_receipt_sha = sha_static(typed_receipt_path) if typed_receipt_path and typed_receipt_path.is_file() else None
    actual_receipt = load_json(typed_receipt_path) if typed_receipt_path and typed_receipt_path.is_file() else None
    receipt_metadata = {
        "path": str(typed_receipt_path) if typed_receipt_path else None,
        "actual_sha256": actual_receipt_sha,
        "status": actual_receipt.get("status") if actual_receipt else "WAIT",
        "returncode": actual_receipt.get("returncode") if actual_receipt else None,
        "finished_at_utc": actual_receipt.get("finished_at_utc") if actual_receipt else None,
        "attempt_id": (actual_receipt.get("request") or {}).get("attempt_id") if actual_receipt else None,
    }
    manifest_metadata = {
        "path": str(manifest_path) if manifest_path else None,
        "sha256": sha_static(manifest_path) if manifest_path and manifest_path.is_file() else None,
        "typed_receipt": manifest.get("typed_receipt") if manifest else None,
        "typed_receipt_sha256": manifest.get("typed_receipt_sha256") if manifest else None,
        "frames": manifest.get("frames") if manifest else None,
        "particles": manifest.get("particles") if manifest else None,
        "expected_dimension": manifest.get("expected_dimension") if manifest else None,
    }
    case_mismatches: list[dict[str, Any]] = []
    for mismatch in mismatches:
        if mismatch["path"] == receipt_metadata["path"]:
            case_mismatches.append({
                "input_path": mismatch["path"],
                "before_sha256": mismatch["expected_sha256"],
                "actual_after_sha256": mismatch["actual_sha256"],
                "actual_status": receipt_metadata["status"],
                "actual_returncode": receipt_metadata["returncode"],
                "attempt_id": receipt_metadata["attempt_id"],
                "root547_manifest_typed_receipt_sha256": manifest_metadata["typed_receipt_sha256"],
            })
        else:
            case_mismatches.append({
                "input_path": mismatch["path"],
                "before_sha256": mismatch["expected_sha256"],
                "actual_after_sha256": mismatch["actual_sha256"],
                "actual_status": "metadata_digest_mismatch",
            })
    return {
        "case_id": case_id,
        "source100_request": str(path.resolve()),
        "source100_request_sha256": sha_static(path),
        "attempt_id": request.get("attempt_id"),
        "input_count": len(request.get("input_files", [])),
        "non_scientific_checked_count": len(checked),
        "non_scientific_match_count": sum(item["status"] == "match" for item in checked),
        "non_scientific_mismatch_count": len(mismatches),
        "missing_count": len(missing),
        "unsupported_count": len(unsupported),
        "scientific_inputs_skipped_by_suffix": skipped_science_extensions,
        "all_non_scientific_input_digests_recomputed": True,
        "checked_non_scientific_inputs": checked,
        "mismatches": mismatches,
        "repair_candidates": case_mismatches,
        "root547_manifest": manifest_metadata,
        "root561_review": selected_root561_row(root561[case_id]) if case_id in root561 else None,
        "root561_review_ref": {
            "path": str(ROOT561_REVIEW),
            "sha256": sha_static(ROOT561_REVIEW),
        },
        "source_did_not_read_or_hash_scientific_payload": True,
    }


def main() -> None:
    (PACKAGE / "evidence").mkdir(parents=True, exist_ok=True)
    (PACKAGE / "metadata").mkdir(parents=True, exist_ok=True)
    (PACKAGE / "tests").mkdir(parents=True, exist_ok=True)
    root561, root561_ref = root561_rows()
    request_paths = sorted((SOURCE100 / "requests").glob("*-full1201-render-fresh100-disabled.request.json"))
    if len(request_paths) != 24:
        raise RuntimeError(f"source100 requests expected 24, found {len(request_paths)}")
    rows = [audit_request(path, root561) for path in request_paths]
    mismatches = [
        mismatch
        for row in rows
        for mismatch in row["repair_candidates"]
    ]
    root570_ref = ref(ROOT570_REVIEW)
    audit = {
        "schema": "ds02.f4.fresh101.source100-nonscience-input-closure-audit.v1",
        "scope_id": SCOPE,
        "source100_commit": "1bb52632bc2feffc95baf21cefcbdb2de31720bb",
        "source100_immutable": True,
        "source100_request_count": len(rows),
        "cases": rows,
        "repair_candidate_count": len(mismatches),
        "repair_candidates": mismatches,
        "audit_summary": {
            "requests_audited": len(rows),
            "non_scientific_inputs_checked": sum(row["non_scientific_checked_count"] for row in rows),
            "non_scientific_matches": sum(row["non_scientific_match_count"] for row in rows),
            "non_scientific_mismatches": sum(row["non_scientific_mismatch_count"] for row in rows),
            "missing_non_scientific_inputs": sum(row["missing_count"] for row in rows),
            "unsupported_inputs": sum(row["unsupported_count"] for row in rows),
            "scientific_payloads_read_or_hashed": False,
        },
        "root561_review": root561_ref,
        "root570_adoption_review": root570_ref,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "scientific_payload_read_or_hashed_by_source": False,
    }
    dump(PACKAGE / "evidence/source100-input-closure-audit.json", audit)
    dump(PACKAGE / "metadata/receipt-sha-repair-checklist.json", {
        "schema": "ds02.f4.fresh101.receipt-sha-repair-checklist.v1",
        "source100_commit": audit["source100_commit"],
        "rule": (
            "Only Root may derive/apply a corrected request. Replace a stale "
            "source100 input SHA when the same path and exact attempt receipt "
            "is current completed/0 and the Root547 manifest typed_receipt_sha256 "
            "equals the recomputed receipt digest."
        ),
        "repair_candidates": mismatches,
        "root561_review": root561_ref,
        "no_source_request_mutated": True,
        "no_jobs_started": True,
        "scientific_payload_read_or_hashed": False,
    })
    dump(PACKAGE / "source-binding.json", {
        "schema": "ds02.f4.fresh101-source-binding.v1",
        "scope_id": SCOPE,
        "family_id": "F4",
        "source100_commit": audit["source100_commit"],
        "requests_audited": len(rows),
        "repair_candidate_count": len(mismatches),
        "source100_unchanged": True,
        "scientific_payloads_skipped": True,
        "jobs_started_by_source": False,
        "shared_registry_write_by_source": False,
        "root_owned_application_required": True,
    })


if __name__ == "__main__":
    main()
