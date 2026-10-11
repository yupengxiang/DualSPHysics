#!/usr/bin/env python3
"""Build the DS-DATA-02 M3 scope catalog from frozen metadata only.

The input tree is the read-only stage2 worktree.  This builder opens only the
listed JSON/Markdown metadata files.  It never opens HDF5, BI4, JSONL, XMF,
CSV, or solver-output files referenced by those records; paths to such files
are retained as pointers in the resulting catalog.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SOURCE_ROOT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics"
)

CURRENT_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/CURRENT336.json"
)
CASE_CATALOG_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/review_20261007/CASES_336.json"
)
FINAL_REPORT_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-handoff/20261010-closeout-v1/FINAL_REPORT_ZH.md"
)
EVIDENCE_INDEX_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-handoff/20261010-closeout-v1/EVIDENCE_INDEX.json"
)
MASK_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
)
SCAN_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/ROOT434_ACTUAL_H5_CLOSED_CENSUS_V2.json"
)
NATIVE_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/ORIGINAL118_NATIVE_JOIN_AFTER_ROOT717_INDEPENDENT_STRICT_V5_OVERLAY_V1.json"
)
NATIVE_SCOPE_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/ORIGINAL118_NATIVE_JOIN_AFTER_ROOT717_INDEPENDENT_STRICT_V5_OVERLAY_V1-canonical-base-scope.json"
)
MISSING_MANIFEST_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/governance/root-owned-source-interface-review-v1/field335-primary-v5-actual-metadata-preflight-v1.json"
)
FAMILY_INDEX_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v21-source-proof/CURRENT336-source-proof-v21.json"
)
FAMILY_CARD_DIR_REL = Path(
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v21-source-proof"
)

FAMILIES = tuple(f"F{i}" for i in range(1, 8))
ALIAS_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
MISSING_MANIFEST_CASE_ID = "F2H10V2_OFFSET_V1"


def read_json(path: Path) -> Any:
    # All paths passed to this function are explicit metadata JSON sources.
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_record(
    root: Path,
    rel: Path,
    *,
    source_id: str,
    role: str,
    schema: str | None = None,
) -> dict[str, Any]:
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(f"metadata source is missing: {path}")
    record: dict[str, Any] = {
        "source_id": source_id,
        "role": role,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if schema is not None:
        record["schema"] = schema
    return record


def pointer(value: Any) -> dict[str, Any] | None:
    """Copy a path/hash pointer without opening its target."""
    if not isinstance(value, dict) or "path" not in value:
        return None
    result: dict[str, Any] = {"path": value["path"]}
    for key in ("sha256", "recomputed_sha256", "producer_declared_sha256"):
        if value.get(key) is not None:
            result[key] = value[key]
    return result


def compact_pointer_map(value: Any, keys: Iterable[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in keys:
        item = pointer(value.get(key))
        if item:
            result[key] = item
    return result


def evidence_index_entry(index: dict[str, Any], evidence_id: str) -> dict[str, Any]:
    for item in index.get("key_evidence", []):
        if item.get("id") == evidence_id:
            return {
                "id": item.get("id"),
                "description": item.get("description"),
                "original_path": item.get("original_path"),
                "member": item.get("member"),
                "bytes": item.get("bytes"),
                "sha256": item.get("sha256"),
                "role": item.get("role"),
            }
    raise KeyError(f"evidence index entry not found: {evidence_id}")


def header_summary(header: dict[str, Any]) -> dict[str, Any]:
    fields = header.get("fields", {})
    return {
        "field_names": sorted(fields),
        "field_shapes": {
            name: field.get("shape")
            for name, field in sorted(fields.items())
            if isinstance(field, dict)
        },
        "field_dtypes": {
            name: field.get("dtype")
            for name, field in sorted(fields.items())
            if isinstance(field, dict)
        },
        "units": header.get("units", {}),
        "identity_key": header.get("identity_key"),
        "coordinate_frame": header.get("coordinate_frame"),
        "conversion_complete": header.get("conversion_complete"),
        "scope": "header metadata only; payload was not opened by this builder",
    }


def build_family_scope(
    root: Path,
    family_index: dict[str, Any],
    family_id: str,
    *,
    mask_count: int,
    scan_count: int,
    native_count: int,
) -> dict[str, Any]:
    card_meta = family_index["family_cards"][family_id]
    card_path = root / FAMILY_CARD_DIR_REL / f"{family_id}-family-card-v21-source-proof.json"
    if not card_path.is_file():
        raise FileNotFoundError(f"family card is missing: {card_path}")
    card = read_json(card_path)
    return {
        "family_id": family_id,
        "case_count": card_meta.get("case_count"),
        "physical_mechanism": card.get("physical_mechanism"),
        "status": card.get("status"),
        "qualification": card.get("qualification", {}),
        "split_safe": card.get("raw_anchor_policy", {}).get("split_safe"),
        "source_link_count": card.get("source_link_count"),
        "observer_contract": card.get("observer_contract", []),
        "task_subsets": card.get("task_subsets", []),
        "effective_condition": card.get("effective_condition", {}),
        "source_closure": card.get("source_closure", {}),
        "actual_evidence_scope": card.get("actual_evidence_scope", {}),
        "unknown_scope": card.get("unknown_scope", []),
        "evidence_counts": {
            "current_cases": card_meta.get("case_count"),
            "saved_mask_cases": mask_count,
            "actual_field_scan_cases": scan_count,
            "native_cause_join_cases": native_count,
        },
        "proof": {
            "index_path": str(root / FAMILY_INDEX_REL),
            "index_sha256": sha256_file(root / FAMILY_INDEX_REL),
            "card_path": str(card_path),
            "card_sha256": sha256_file(card_path),
            "card_declared_sha256": card_meta.get("sha256"),
        },
    }


def build_catalog(source_root: Path) -> dict[str, Any]:
    current_path = source_root / CURRENT_REL
    current = read_json(current_path)
    case_catalog_path = source_root / CASE_CATALOG_REL
    case_catalog = read_json(case_catalog_path)
    mask = read_json(source_root / MASK_REL)
    scan = read_json(source_root / SCAN_REL)
    native = read_json(source_root / NATIVE_REL)
    native_scope = read_json(source_root / NATIVE_SCOPE_REL)
    missing_manifest = read_json(source_root / MISSING_MANIFEST_REL)
    family_index = read_json(source_root / FAMILY_INDEX_REL)
    evidence_index = read_json(source_root / EVIDENCE_INDEX_REL)

    cases = current.get("cases", [])
    review_cases = case_catalog.get("cases", [])
    if len(cases) != 336 or len(review_cases) != 336:
        raise ValueError(f"expected two 336-case catalogs, got {len(cases)} and {len(review_cases)}")
    if current.get("schema") != "ds02.stage2.current336.v1":
        raise ValueError(f"unexpected CURRENT schema: {current.get('schema')!r}")
    if current.get("source_catalog_sha256") != sha256_file(case_catalog_path):
        raise ValueError("CURRENT source_catalog_sha256 does not match CASES_336 metadata")
    family_counts = Counter(case.get("family_id") for case in cases)
    if family_counts != Counter({family: 48 for family in FAMILIES}):
        raise ValueError(f"unexpected family counts: {family_counts}")

    current_by_id = {case["physical_case_id"]: case for case in cases}
    review_by_id = {case["physical_case_id"]: case for case in review_cases}
    if set(current_by_id) != set(review_by_id):
        raise ValueError("CURRENT336 and CASES_336 physical-case sets differ")

    mask_records = {record["physical_case_id"]: record for record in mask["case_records"]}
    if len(mask_records) != 336:
        raise ValueError(f"expected 336 mask records, got {len(mask_records)}")
    mask_coverage = mask["coverage"]
    if mask_coverage.get("actual_saved_mask_cases") != 335:
        raise ValueError(f"saved-mask proof does not report 335 cases: {mask_coverage}")
    alias_ids = [
        case_id
        for case_id, record in mask_records.items()
        if record.get("status") == "HISTORICAL_ALIAS_UNRESOLVED"
    ]
    if alias_ids != [ALIAS_CASE_ID]:
        raise ValueError(f"unexpected unresolved alias IDs: {alias_ids}")

    scan_rows = scan.get("base_actual_rows", []) + scan.get("additional_actual_rows", [])
    scan_by_id = {row["physical_case_id"]: row for row in scan_rows}
    if len(scan_by_id) != scan.get("actual_canonical_field_cases_total"):
        raise ValueError("field-scan rows are not unique or census total is inconsistent")
    if scan.get("actual_canonical_field_cases_total") != 78:
        raise ValueError(
            f"field-scan proof does not report 78 cases: {scan.get('actual_canonical_field_cases_total')}"
        )

    native_scope_rows = {
        row["physical_case_id"]: row for row in native_scope.get("case_rows", [])
    }
    if len(native_scope_rows) != 118:
        raise ValueError(f"expected 118 native scope rows, got {len(native_scope_rows)}")
    native_counts = Counter(row["classification"] for row in native_scope_rows.values())
    if native_counts != Counter(
        {"NATIVE_CAUSE_BOUND_PER_FLUID_ID": 117, "HISTORICAL_ALIAS_UNRESOLVED": 1}
    ):
        raise ValueError(f"unexpected native scope classifications: {native_counts}")
    if native.get("native_cause_bound_per_fluid_id_cases") != 117:
        raise ValueError(
            "native overlay does not report 117 bound cases: "
            f"{native.get('native_cause_bound_per_fluid_id_cases')}"
        )
    if native.get("unresolved_alias_case_ids") != [ALIAS_CASE_ID]:
        raise ValueError(
            f"native overlay alias partition differs: {native.get('unresolved_alias_case_ids')}"
        )

    preflight_results = {
        row["physical_case_id"]: row for row in missing_manifest.get("case_results", [])
    }
    blocked = [
        row
        for row in preflight_results.values()
        if row.get("status") == "BLOCKED_METADATA_CHAIN"
    ]
    if missing_manifest.get("case_count") != 335 or len(blocked) != 1:
        raise ValueError("missing-manifest preflight does not match expected 335/1 closure")
    if blocked[0].get("physical_case_id") != MISSING_MANIFEST_CASE_ID:
        raise ValueError(f"unexpected missing-manifest case: {blocked[0]}")

    newly_bound = {
        row["physical_case_id"]: row for row in native.get("newly_bound_cases", [])
    }

    case_rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_id = case["physical_case_id"]
        mask_record = mask_records[case_id]
        scan_record = scan_by_id.get(case_id)
        native_record = native_scope_rows.get(case_id)
        review = review_by_id[case_id]
        producer_evidence = mask_record.get("producer_evidence") or {}
        evidence_pointers = compact_pointer_map(
            producer_evidence,
            ("proof", "case_manifest", "case_receipt", "summary", "request", "receipt", "report"),
        )
        scan_evidence: dict[str, Any] | None = None
        if scan_record:
            scan_evidence = {
                "proof": pointer(scan_record.get("actual_proof")),
                "request": pointer(scan_record.get("request")),
                "namespace": scan_record.get("namespace"),
                "full_cpu_seconds": scan_record.get("full_cpu_seconds"),
                "source_h5_bytes": scan_record.get("source_h5_bytes"),
                "scientific_Q_credit": scan_record.get("scientific_Q_credit"),
            }
        native_detail: dict[str, Any] | None = None
        if case_id in newly_bound:
            row = newly_bound[case_id]
            native_detail = {
                "classification": row.get("classification"),
                "previous_classification": row.get("previous_classification"),
                "native_cause": row.get("native_cause"),
                "native_cause_categories": row.get("native_cause_categories"),
                "source_native_motive_categories": row.get("source_native_motive_categories"),
                "fluid_identity_count": row.get("fluid_identity_count"),
                "saved_frame_join": row.get("saved_frame_join"),
                "evidence": {
                    "path": row.get("evidence"),
                    "sha256": row.get("evidence_sha256"),
                },
                "case_report": {
                    "path": row.get("case_report"),
                    "sha256": row.get("case_report_sha256"),
                },
            }

        preflight_row = preflight_results.get(case_id, {})
        row = {
            "case_number": index + 1,
            "current_index": index,
            "family_id": case["family_id"],
            "physical_case_id": case_id,
            "runtime_case_alias": case["runtime_case_alias"],
            "frames": case["frames"],
            "particles": case["particles"],
            "actual_time_window_s": case["actual_time_window_s"],
            "known_numeric_physical_parameters": case["known_numeric_physical_parameters"],
            "review_membership": {
                "first8_member": review.get("first8_member"),
                "first24_member": review.get("first24_member"),
                "final48_member": review.get("final48_member"),
                "precision_status": review.get("precision_status"),
                "scope_limits": review.get("scope_limits"),
            },
            "visual_status": case.get("quality", {}).get("visual"),
            "qualification": {
                "QI": case.get("quality", {}).get("QI"),
                "QN": case.get("quality", {}).get("QN"),
                "QE": case.get("quality", {}).get("QE"),
            },
            "header": header_summary(case.get("header", {})),
            "current_catalog_scan_status": case.get("scientific_scan_status"),
            "manifest": pointer(case.get("manifest")),
            "xmf": pointer(case.get("xmf")),
            "trajectory": pointer(case.get("trajectory")),
            "conversion_report": pointer(case.get("conversion_report")),
            "raw_root": pointer(case.get("raw_root")),
            "saved_mask": {
                "coverage": mask_record.get("actual_saved_mask_coverage"),
                "status": mask_record.get("status"),
                "scientific_credit": mask_record.get("scientific_credit"),
                "source_join_status": mask_record.get("source_join_status"),
                "historical_alias": mask_record.get("historical_alias"),
                "physical_fate": mask_record.get("physical_fate"),
                "dynamical_impact": mask_record.get("dynamical_impact"),
                "evidence_pointers": evidence_pointers,
                "scope": "saved-mask lifecycle and identity audit only; no physical/scientific credit",
            },
            "field_scan": {
                "status": "ACTUAL_FIELD_SCAN_METADATA_PROOF"
                if scan_record
                else "NOT_SCANNED_IN_ROOT434_CENSUS",
                "evidence": scan_evidence,
                "scope": "historical field proof row only; no QI/QN/QE credit",
            },
            "native_cause_join": {
                "status": (
                    native_record.get("classification")
                    if native_record
                    else "NOT_IN_ORIGINAL118_SCOPE"
                ),
                "detail": native_detail,
                "scope": (
                    "per-fluid-ID native cause and typed saved-frame join only; physical fate, legal flux, dynamics and Q remain UNKNOWN"
                    if native_record
                    else "outside the original-118 native-cause scope"
                ),
            },
            "special_metadata_flags": {
                "historical_alias_unresolved": case_id == ALIAS_CASE_ID,
                "field335_missing_manifest_unknown": case_id == MISSING_MANIFEST_CASE_ID,
                "current_manifest_pointer_present": bool(case.get("manifest")),
                "field335_preflight_status": preflight_row.get("status"),
                "field335_preflight_reason": preflight_row.get("reason"),
            },
        }
        case_rows.append(row)

    mask_family_counts = Counter(
        row["family_id"] for row in case_rows if row["saved_mask"]["coverage"]
    )
    scan_family_counts = Counter(
        row["family_id"] for row in case_rows if row["field_scan"]["evidence"]
    )
    native_family_counts = Counter(
        row["family_id"]
        for row in case_rows
        if row["native_cause_join"]["status"] == "NATIVE_CAUSE_BOUND_PER_FLUID_ID"
    )

    family_scopes = {
        family: build_family_scope(
            source_root,
            family_index,
            family,
            mask_count=mask_family_counts.get(family, 0),
            scan_count=scan_family_counts.get(family, 0),
            native_count=native_family_counts.get(family, 0),
        )
        for family in FAMILIES
    }

    evidence_ids = {
        evidence_id: evidence_index_entry(evidence_index, evidence_id)
        for evidence_id in ("E001", "E002", "E003", "E004", "E012", "E031")
    }

    source_files = {
        "current336": source_record(
            source_root,
            CURRENT_REL,
            source_id="current336",
            role="frozen 336-case header/XMF/source-digest catalog",
            schema=current.get("schema"),
        ),
        "review_cases_336": source_record(
            source_root,
            CASE_CATALOG_REL,
            source_id="review_cases_336",
            role="336-case review catalog and membership pointers",
            schema=case_catalog.get("schema"),
        ),
        "final_report_20261010": source_record(
            source_root,
            FINAL_REPORT_REL,
            source_id="final_report_20261010",
            role="2026-10-10 closeout report; scope and limitations narrative",
        ),
        "evidence_index": source_record(
            source_root,
            EVIDENCE_INDEX_REL,
            source_id="evidence_index",
            role="closeout evidence IDs and recorded metadata hashes",
            schema=evidence_index.get("schema"),
        ),
        "saved_mask_proof": source_record(
            source_root,
            MASK_REL,
            source_id="saved_mask_proof",
            role="335 saved-mask/lifecycle cases and one alias exception",
            schema=mask.get("schema"),
        ),
        "field_scan_proof": source_record(
            source_root,
            SCAN_REL,
            source_id="field_scan_proof",
            role="78 actual field-scan rows, 256 remaining and one manifest UNKNOWN",
            schema=scan.get("schema"),
        ),
        "native_join_proof": source_record(
            source_root,
            NATIVE_REL,
            source_id="native_join_proof",
            role="117 native-cause/typed-saved-frame joins in original-118 scope",
            schema=native.get("schema"),
        ),
        "native_join_scope": source_record(
            source_root,
            NATIVE_SCOPE_REL,
            source_id="native_join_scope",
            role="canonical 118-row native scope partition",
            schema=native_scope.get("schema"),
        ),
        "missing_manifest_preflight": source_record(
            source_root,
            MISSING_MANIFEST_REL,
            source_id="missing_manifest_preflight",
            role="335-case metadata preflight identifying one missing manifest reference",
            schema=missing_manifest.get("schema"),
        ),
        "family_source_proof_v21": source_record(
            source_root,
            FAMILY_INDEX_REL,
            source_id="family_source_proof_v21",
            role="seven family source-bound development cards",
            schema=family_index.get("schema"),
        ),
    }

    catalog: dict[str, Any] = {
        "schema": "ds02.upstream-first.m3-scope-catalog.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "M3 seven-family and 336-case scope index built from frozen metadata; no scientific payload replay",
        "source_snapshot": {
            "source_root": str(source_root),
            "current_scope": current.get("scope"),
            "current_schema": current.get("schema"),
            "current_source_catalog": current.get("source_catalog"),
            "current_source_catalog_sha256": current.get("source_catalog_sha256"),
            "total_hdf5_bytes_declared_by_current": current.get("total_hdf5_bytes"),
            "payload_content_opened_by_builder": False,
            "scientific_payloads_opened_by_builder": [],
            "scope_boundary": [
                "Only explicit JSON/Markdown metadata sources below were opened.",
                "Referenced HDF5/BI4/JSONL/XMF/CSV/solver-output paths are retained as pointers only.",
                "Historical actual scan/join counts are imported from proof metadata; this run did not repeat scans or science analysis.",
            ],
        },
        "counts": {
            "cases": len(case_rows),
            "families": len(FAMILIES),
            "cases_per_family": {family: family_counts[family] for family in FAMILIES},
            "saved_mask_cases": mask_coverage.get("actual_saved_mask_cases"),
            "saved_mask_unresolved_alias_cases": mask_coverage.get("historical_alias_unresolved"),
            "field_scan_cases": scan.get("actual_canonical_field_cases_total"),
            "field_scan_remaining_executable_cases": scan.get("remaining_executable_count"),
            "field_scan_canonical_source_cases": scan.get("canonical_source_count"),
            "native_scope_cases": native.get("physical_case_count"),
            "native_cause_join_cases": native.get("native_cause_bound_per_fluid_id_cases"),
            "native_scope_unresolved_alias_cases": len(native.get("unresolved_alias_case_ids", [])),
            "field_scan_missing_manifest_unknown_cases": scan.get("missing_case_manifest_unknown_count"),
            "field335_preflight_pass_cases": missing_manifest.get("counts", {}).get("PASS_BOUNDED_ACTUAL_PRODUCER_METADATA_CHAIN_ONLY"),
            "field335_preflight_blocked_cases": missing_manifest.get("counts", {}).get("BLOCKED_METADATA_CHAIN"),
            "physical_or_scientific_qualification_credit": 0,
        },
        "proof_sources": source_files,
        "frozen_evidence_ids": evidence_ids,
        "exceptions": {
            "unresolved_historical_alias": {
                "physical_case_id": ALIAS_CASE_ID,
                "family_id": "F2",
                "current_index": mask_records[ALIAS_CASE_ID].get("current_index"),
                "mask_status": mask_records[ALIAS_CASE_ID].get("status"),
                "native_scope_classification": native_scope_rows[ALIAS_CASE_ID].get("classification"),
                "proof_sources": ["E002", "E004", "native_join_scope"],
                "scope": "preserve UNKNOWN; no alias renaming or evidence borrowing",
            },
            "missing_case_manifest_reference": {
                "physical_case_id": MISSING_MANIFEST_CASE_ID,
                "family_id": "F2",
                "preflight_status": blocked[0].get("status"),
                "reason": blocked[0].get("reason"),
                "current_manifest_pointer_present": bool(
                    current_by_id[MISSING_MANIFEST_CASE_ID].get("manifest")
                ),
                "proof_sources": ["E003", "missing_manifest_preflight"],
                "scope": "field335 producer metadata chain UNKNOWN; do not treat the CURRENT row pointer as closure of this missing reference",
            },
        },
        "family_scopes": family_scopes,
        "unknowns": [
            "All family cards remain DEVELOPMENT_ONLY with QI/QN/QE UNKNOWN; source/header metadata is not scientific acceptance.",
            "335 saved-mask cases cover saved-mask lifecycle and identity audit only; physical fate, legal flux, dynamical impact and task error remain UNKNOWN.",
            "78 field scans are historical actual proof rows; CURRENT336 scientific_scan_status remains NOT_SCANNED and 256 canonical cases remain executable/unscanned in ROOT434 census.",
            "117 native joins identify per-fluid-ID native cause and typed saved-frame association only; they do not prove physical fate, legal outflow, dynamics or numerical/experimental validity.",
            "One F2 historical alias remains unresolved, and one distinct F2 field335 manifest reference remains UNKNOWN.",
            "No split is scientifically safe yet; resolution/window/recovery transfer and cross-family equivalence remain UNKNOWN.",
        ],
        "cases": case_rows,
    }
    return catalog


def csv_row(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_number": case["case_number"],
        "current_index": case["current_index"],
        "family_id": case["family_id"],
        "physical_case_id": case["physical_case_id"],
        "runtime_case_alias": case["runtime_case_alias"],
        "frames": case["frames"],
        "particles": case["particles"],
        "time_start_s": case["actual_time_window_s"][0],
        "time_end_s": case["actual_time_window_s"][1],
        "known_numeric_physical_parameters": json.dumps(
            case["known_numeric_physical_parameters"], ensure_ascii=False, sort_keys=True
        ),
        "visual_status": case["visual_status"],
        "QI": case["qualification"]["QI"],
        "QN": case["qualification"]["QN"],
        "QE": case["qualification"]["QE"],
        "current_catalog_scan_status": case["current_catalog_scan_status"],
        "saved_mask_status": case["saved_mask"]["status"],
        "saved_mask_coverage": case["saved_mask"]["coverage"],
        "field_scan_status": case["field_scan"]["status"],
        "native_join_status": case["native_cause_join"]["status"],
        "field335_preflight_status": case["special_metadata_flags"]["field335_preflight_status"],
        "field335_missing_manifest_unknown": case["special_metadata_flags"]["field335_missing_manifest_unknown"],
        "historical_alias_unresolved": case["special_metadata_flags"]["historical_alias_unresolved"],
        "manifest_path": (case["manifest"] or {}).get("path"),
        "xmf_path": (case["xmf"] or {}).get("path"),
        "trajectory_path": (case["trajectory"] or {}).get("path"),
        "raw_root_path": (case["raw_root"] or {}).get("path"),
    }


def markdown_report(catalog: dict[str, Any]) -> str:
    counts = catalog["counts"]
    lines = [
        "# M3 七族 / 336 例范围目录（元数据限定）",
        "",
        "本目录只整理 2026-10-10 stage2 收尾包中的 JSON/Markdown 证明。构建器没有打开 HDF5、BI4、JSONL、XMF、CSV 或 solver-output；这些路径只作为元数据指针保留。历史 78 扫描和 117 native join 的数字来自已有 proof JSON，不是本次新扫描。",
        "",
        "## 计数与边界",
        "",
        f"- {counts['cases']} 例，{counts['families']} 族，每族 48 例。",
        f"- {counts['saved_mask_cases']} 例有实际 saved-mask/lifecycle 证明；{counts['saved_mask_unresolved_alias_cases']} 例历史别名保持 UNKNOWN。",
        f"- {counts['field_scan_cases']} 例有进一步字段扫描证明；ROOT434 仍记录 {counts['field_scan_remaining_executable_cases']} 例未扫描。",
        f"- 原 118 例遗漏范围中 {counts['native_cause_join_cases']} 例有 per-fluid-ID native-cause / typed-saved-frame join；这不是合法通量、物理去向或动力学证明。",
        f"- 独立的 field335 metadata preflight 为 {counts['field335_preflight_pass_cases']} PASS、{counts['field335_preflight_blocked_cases']} BLOCKED；缺失引用是 \x60{MISSING_MANIFEST_CASE_ID}\x60。",
        "- 当前所有家族 QI/QN/QE 为 UNKNOWN，目录不授予科学资格或 split-safe 状态。",
        "",
        "## 七族范围",
        "",
        "| 族 | 机制 | 例数 | mask | 字段扫描 | native join | 任务范围 | 资格 |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for family in FAMILIES:
        scope = catalog["family_scopes"][family]
        tasks = "; ".join(item.get("task", "") for item in scope["task_subsets"])
        qualifiers = "/".join(
            scope["qualification"].get(key, "UNKNOWN") for key in ("QI", "QN", "QE")
        )
        lines.append(
            f"| {family} | {scope['physical_mechanism']} | {scope['case_count']} | {scope['evidence_counts']['saved_mask_cases']} | {scope['evidence_counts']['actual_field_scan_cases']} | {scope['evidence_counts']['native_cause_join_cases']} | {tasks} | {qualifiers} |"
        )
    lines += [
        "",
        "## 证明来源",
        "",
        "| ID | 作用 | schema | 文件 | SHA-256 |",
        "|---|---|---|---|---|",
    ]
    source_items = catalog["proof_sources"]
    source_order = [
        "current336",
        "final_report_20261010",
        "saved_mask_proof",
        "field_scan_proof",
        "native_join_proof",
        "native_join_scope",
        "missing_manifest_preflight",
        "family_source_proof_v21",
    ]
    source_labels = {
        "current336": "E001",
        "saved_mask_proof": "E002",
        "field_scan_proof": "E003",
        "native_join_proof": "E004",
    }
    for source_id in source_order:
        source = source_items[source_id]
        lines.append(
            f"| {source_labels.get(source_id, source_id)} | {source['role']} | {source.get('schema', '—')} | \x60{source['path']}\x60 | \x60{source['sha256']}\x60 |"
        )
    lines += [
        "",
        "## 保留的例外与未知",
        "",
        f"- 未解析历史别名：\x60{ALIAS_CASE_ID}\x60（F2，CURRENT index 78）。E002、E004 及 canonical 118-row scope 都要求保留 UNKNOWN，不借用其他规范例的证据。",
        f"- 缺失 manifest 引用：\x60{MISSING_MANIFEST_CASE_ID}\x60（F2）。field335 preflight 的明确原因是 \x60case manifest reference is missing\x60；这是 field-scan producer chain 的 UNKNOWN。CURRENT336 行仍有一个 manifest 元数据指针，但该指针不能替代缺失的 field335 引用闭合。",
        "- native join 的 physical_fate、legal_flux、dynamics、QI/QN/QE 仍 UNKNOWN；mask 也不授予这些信用。",
        "- 解析度、窗口、恢复转移及跨族等价性仍 UNKNOWN，所有家族卡 split_safe=false。",
        "",
        "## 机器可读输出",
        "",
        "- \x60scope_catalog.json\x60：完整元数据范围目录及来源/边界。",
        "- \x60scope_catalog.csv\x60：336 行 case/task 索引，保留 manifest、XMF、trajectory 和 raw-root 指针但不读取其目标。",
        "- \x60build_scope_catalog.py\x60：可从同一 stage2 快照重复生成；只打开本报告列出的元数据文件。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(__file__).resolve().parent
    )
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog = build_catalog(source_root)
    json_path = output_dir / "scope_catalog.json"
    csv_path = output_dir / "scope_catalog.csv"
    md_path = output_dir / "scope_catalog.md"
    json_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rows = [csv_row(case) for case in catalog["cases"]]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    md_path.write_text(markdown_report(catalog), encoding="utf-8")
    print(
        json.dumps(
            {
                "json": str(json_path),
                "csv": str(csv_path),
                "markdown": str(md_path),
                "case_count": catalog["counts"]["cases"],
                "family_count": catalog["counts"]["families"],
                "payload_content_opened": catalog["source_snapshot"][
                    "payload_content_opened_by_builder"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
