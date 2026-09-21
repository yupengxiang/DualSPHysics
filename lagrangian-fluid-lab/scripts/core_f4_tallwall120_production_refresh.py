#!/usr/bin/env python3
"""Refresh a hash-bound F4 production product index from verified archives.

This is a read-only boundary around the F4 production collector.  It scans
only caller supplied archive roots, verifies the immutable archive receipt and
the product hashes, and emits a small product index that can be handed to
``core_f4_tallwall120_production_collector``.  It does not open the runtime
store, submit work, update a ledger, or infer a formal release.

The production denominator is deliberately taken from the frozen design and
is always 32.  Qualification archives are reported in an exclusion list and
never become production product rows.  If the same production case appears
in more than one archive root, identical product hashes are de-duplicated;
conflicting hashes fail closed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

# Keep direct CLI execution equivalent to ``python -m`` from the lab root.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from scripts import core_f4_tallwall120_production_collector as collector


SCHEMA = "core.f4.tallwall120.production_products_refresh.v1"
PRODUCT_SCHEMA = "core.f4.tallwall120.production_products.v1"
ARCHIVE_SCHEMA = "core.verified_archive.v1"
EXECUTION_SCHEMAS = {"core.execution_receipt.v1", ARCHIVE_SCHEMA}
REQUIRED_PRODUCTS = {
    "audit": "audit.json",
    "result": "result.json",
    "observations": "observations.json",
    "trajectory": "trajectory.h5",
}


class RefreshError(collector.CollectionError):
    """Raised when an archive cannot be made into a stable product row."""


def _safe_child(path: Path, root: Path, role: str) -> Path:
    """Resolve a path below ``root`` and reject traversal/absolute entries."""
    path = Path(path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise RefreshError(f"{role} has an unsafe relative path: {path}")
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RefreshError(f"{role} escapes data_root: {path}") from exc
    return target


def _root_path(value: str | Path, root: Path, role: str) -> Path:
    candidate = Path(value).expanduser()
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RefreshError(f"{role} escapes data_root: {target}") from exc
    if not target.is_dir():
        raise RefreshError(f"{role} is not a directory: {target}")
    return target


def _json(path: Path, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RefreshError(f"{role} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise RefreshError(f"{role} must be a JSON object: {path}")
    return value


def _relative_ref(path: Path, root: Path, role: str, *, declared: str | None = None,
                  bytes_declared: int | None = None) -> dict[str, Any]:
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise RefreshError(f"{role} is outside data_root: {path}") from exc
    if not path.is_file():
        raise RefreshError(f"{role} is missing: {path}")
    if bytes_declared is not None and path.stat().st_size != bytes_declared:
        raise RefreshError(
            f"{role} byte count mismatch: {path} ({path.stat().st_size} != {bytes_declared})"
        )
    try:
        return collector._ref(path, root, role=role, declared=declared,
                              require_declared=declared is not None)
    except collector.CollectionError as exc:
        raise RefreshError(str(exc)) from exc


def _archive_marker(archive: Mapping[str, Any], *products: Mapping[str, Any]) -> bool:
    """Recognize qualification-only archives without rejecting production audit prose.

    F4 production audits carry the explanatory claim ``"none; one case ..."``
    even though they are production products.  Only an explicit qualification
    marker, a qualification job/stage/split, or a non-``none`` claim counts.
    """
    for value in (archive, *products):
        if value.get("qualification_only") is True or value.get("qualification_case") is True:
            return True
        if str(value.get("stage", "")).strip().lower() in {
            "qualification", "qualification_only", "canary", "repair_canary",
            "calibration", "diagnostic", "repair", "qualification_canary",
        }:
            return True
        if str(value.get("split", "")).strip().lower() in {"qualification", "qualification_only"}:
            return True
        claim = value.get("qualification_claim")
        if claim not in (None, "", False):
            normalized = str(claim).strip().lower()
            if normalized != "none" and not normalized.startswith("none;"):
                return True
    job_id = str(archive.get("job_id", "")).lower()
    return any(token in job_id for token in ("qualification", "canary", "calibration"))


def _archive_outputs(archive: Mapping[str, Any], execution: Mapping[str, Any],
                     archive_dir: Path, root: Path, case_hint: str) -> dict[str, dict[str, Any]]:
    outputs = archive.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise RefreshError(f"archive {case_hint} has no output index")

    # The verified archive is a subset of the worker artifact index.  Compare
    # both when available so a stale archive cannot silently select swapped
    # product files.
    execution_items: list[Any] = []
    for key in ("outputs", "artifact_index"):
        value = execution.get(key)
        if isinstance(value, list):
            execution_items.extend(value)
    execution_by_path: dict[str, Mapping[str, Any]] = {}
    for item in execution_items:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            continue
        path_value = str(item["path"])
        previous = execution_by_path.get(path_value)
        if previous is not None and (
            previous.get("sha256") != item.get("sha256")
            or previous.get("bytes") != item.get("bytes")
        ):
            raise RefreshError(f"archive {case_hint} execution index conflicts at {path_value}")
        execution_by_path[path_value] = item

    by_path: dict[str, dict[str, Any]] = {}
    for item in outputs:
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise RefreshError(f"archive {case_hint} contains a malformed output entry")
        path_value = str(item["path"])
        if path_value in by_path:
            raise RefreshError(f"archive {case_hint} repeats output {path_value}")
        expected_hash = item.get("sha256")
        expected_bytes = item.get("bytes")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise RefreshError(f"archive {case_hint} output {path_value} lacks SHA-256")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int):
            raise RefreshError(f"archive {case_hint} output {path_value} lacks byte count")
        if path_value in execution_by_path:
            bound = execution_by_path[path_value]
            if bound.get("sha256") != expected_hash or bound.get("bytes") != expected_bytes:
                raise RefreshError(
                    f"archive {case_hint} output {path_value} differs from execution receipt"
                )
        target = _safe_child(path_value, archive_dir, f"archive {case_hint} output")
        by_path[path_value] = _relative_ref(
            target, root, f"case {case_hint} output {path_value}",
            declared=expected_hash, bytes_declared=expected_bytes,
        )

    result: dict[str, dict[str, Any]] = {}
    for key, filename in REQUIRED_PRODUCTS.items():
        matches = [
            (path_value, ref) for path_value, ref in by_path.items()
            if Path(path_value).name == filename
        ]
        if len(matches) != 1:
            raise RefreshError(
                f"archive {case_hint} must contain exactly one product/{filename}; "
                f"found {len(matches)}"
            )
        result[key] = matches[0][1]
    return result


def _archive_row(archive_path: Path, root: Path,
                 design_by_case: Mapping[str, Mapping[str, Any]]) -> tuple[
                     dict[str, Any] | None, dict[str, Any] | None, str]:
    """Read one archive and return (product row, exclusion, classification)."""
    archive = _json(archive_path, "archive manifest")
    if archive.get("schema") != ARCHIVE_SCHEMA:
        return None, {"path": str(archive_path.relative_to(root).as_posix()),
                      "reason": "unsupported_archive_schema",
                      "schema": archive.get("schema")}, "skipped"
    if archive.get("execution_status") != "succeeded":
        return None, {"path": archive_path.relative_to(root).as_posix(),
                      "reason": "archive_not_successful",
                      "execution_status": archive.get("execution_status")}, "skipped"

    archive_dir = archive_path.parent
    job_id = str(archive.get("job_id") or archive_dir.name)
    # Qualification archives are outside the production denominator.  An
    # explicit archive-level marker is enough to exclude them before touching
    # their potentially large trajectory; production archives still take the
    # complete receipt/output/hash path below.  Product-level qualification
    # markers are checked later after their bindings have been verified.
    if _archive_marker(archive):
        archive_ref = _relative_ref(archive_path, root,
                                    f"archive {job_id} manifest")
        return None, {
            "archive": archive_ref,
            "case_id": archive.get("case_id"),
            "job_id": job_id,
            "reason": "qualification_only",
        }, "qualification"
    execution_path = archive_dir / "execution-receipt.json"
    execution_ref = _relative_ref(execution_path, root,
                                  f"archive {job_id} execution receipt")
    execution = _json(execution_path, f"archive {job_id} execution receipt")
    if execution.get("schema") not in EXECUTION_SCHEMAS:
        raise RefreshError(f"archive {job_id} execution receipt schema is unsupported")
    if execution.get("execution_status") != "succeeded":
        raise RefreshError(f"archive {job_id} execution receipt is not succeeded")
    if execution.get("job_id") not in (None, job_id):
        raise RefreshError(f"archive {job_id} execution receipt job identity differs")
    receipt_sha = archive.get("receipt_sha256")
    if not isinstance(receipt_sha, str) or len(receipt_sha) != 64:
        raise RefreshError(f"archive {job_id} lacks receipt_sha256")
    if collector.canonical_sha256(execution) != receipt_sha:
        raise RefreshError(f"archive {job_id} receipt_sha256 does not bind execution receipt")

    products = _archive_outputs(archive, execution, archive_dir, root, job_id)
    documents = {key: _json(
        root / products[key]["path"], f"case {job_id} {key}")
        for key in ("audit", "result", "observations")}
    audit = documents["audit"]
    result = documents["result"]
    observations = documents["observations"]
    case_id = audit.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise RefreshError(f"archive {job_id} audit has no case_id")
    if result.get("case_id") not in (None, case_id):
        raise RefreshError(f"archive {job_id} result case identity differs")

    archive_ref = _relative_ref(archive_path, root, f"archive {job_id} manifest")
    excluded = {
        "archive": archive_ref,
        "case_id": case_id,
        "job_id": job_id,
        "execution_receipt": execution_ref,
        "reason": "qualification_only",
    }
    marker = _archive_marker(archive, execution, audit, result, observations)
    if case_id not in design_by_case:
        if marker:
            return None, excluded, "qualification"
        raise RefreshError(
            f"archive {job_id} contains unknown non-qualification production case {case_id}"
        )
    if marker:
        return None, excluded, "qualification"
    design = design_by_case[case_id]
    structural = audit.get("structural") if isinstance(audit.get("structural"), Mapping) else {}
    attrs = structural.get("attrs") if isinstance(structural, Mapping) else {}
    if not isinstance(attrs, Mapping):
        attrs = {}
    physical = attrs.get("physical_case_id") or result.get("physical_case_id")
    lineage = attrs.get("lineage_group_id") or result.get("lineage_group_id")
    row: dict[str, Any] = {
        "index": design["index"],
        "case_id": case_id,
        "family": collector.FAMILY,
        "split": design["split"],
        "physical_case_id": physical,
        "lineage_group_id": lineage,
        "qualification_only": False,
        "archive": archive_ref,
        "execution": archive_ref,
        "execution_receipt": execution_ref,
        "audit": products["audit"],
        "result": products["result"],
        "observations": products["observations"],
        "trajectory": products["trajectory"],
        "execution_complete": audit.get("requested_horizon_reached") is True,
        "hard_integrity_pass": audit.get("hard_integrity_pass") is True,
        "source_mass_gate_pass": audit.get("source_mass_gate_pass") is True,
        "event_window_complete": audit.get("event_window_complete") is True,
        "reader_eligible": True,
    }
    return row, None, "indexed"


def refresh_product_index(
    production_design: str | Path | Mapping[str, Any],
    archive_roots: Sequence[str | Path],
    data_root: str | Path,
) -> dict[str, Any]:
    """Build a deterministic product index from successful archive manifests.

    The function only reads files.  ``data_root`` is also the trust boundary:
    archive roots and all declared artifact paths must remain below it.
    """
    root = Path(data_root).expanduser().resolve()
    if not root.is_dir():
        raise RefreshError(f"data_root is not a directory: {root}")

    if isinstance(production_design, Mapping):
        design = copy.deepcopy(dict(production_design))
        design_ref = {"path": "<inline>", "sha256": collector.canonical_sha256(design),
                      "role": "production design"}
    else:
        design_path = collector._resolve_path(production_design, root, None, "production design")
        design = collector._read_json(design_path, "production design")
        design_ref = collector._ref(design_path, root, role="production design")
        design_ref["canonical_sha256"] = collector.canonical_sha256(design)
    design_rows, design_summary = collector._validate_design(design)
    design_by_case = {row["case_id"]: row for row in design_rows}

    roots = sorted({_root_path(value, root, "archive root") for value in archive_roots},
                   key=lambda value: value.as_posix())
    if not roots:
        raise RefreshError("at least one archive root is required")

    indexed_by_case: dict[str, dict[str, Any]] = {}
    signatures: dict[str, tuple[str, ...]] = {}
    duplicate_archives: list[dict[str, Any]] = []
    excluded_archives: list[dict[str, Any]] = []
    skipped_archives: list[dict[str, Any]] = []
    scanned = 0
    successful = 0
    for archive_root in roots:
        archive_paths = sorted(
            (path for path in archive_root.rglob("archive.json") if path.is_file()),
            key=lambda path: path.as_posix(),
        )
        for archive_path in archive_paths:
            scanned += 1
            row, excluded, classification = _archive_row(
                archive_path, root, design_by_case)
            if classification == "skipped":
                if excluded is not None:
                    skipped_archives.append(excluded)
                continue
            successful += 1
            if row is None:
                if excluded is not None:
                    excluded_archives.append(excluded)
                continue
            case_id = str(row["case_id"])
            signature = tuple(
                str(row[name].get("sha256"))
                for name in ("audit", "result", "observations", "trajectory", "execution_receipt")
            )
            previous = indexed_by_case.get(case_id)
            if previous is None:
                indexed_by_case[case_id] = row
                signatures[case_id] = signature
                continue
            if signatures[case_id] != signature:
                raise RefreshError(
                    f"production case {case_id} has conflicting archive product hashes"
                )
            duplicate_archives.append({
                "case_id": case_id,
                "kept_archive": previous["archive"],
                "duplicate_archive": row["archive"],
                "artifact_hashes_equal": True,
            })

    rows = [indexed_by_case[row["case_id"]] for row in design_rows
            if row["case_id"] in indexed_by_case]
    # Bind roots by their directory identity without inventing a mutable
    # sentinel file.  Include every selected artifact reference (including
    # its observed hash and byte count), as well as duplicate/exclusion
    # decisions, so replacing bytes at the same archive path changes the
    # source digest and cannot masquerade as the same refresh.
    indexed_bindings = []
    for row in rows:
        indexed_bindings.append({
            "index": row["index"],
            "case_id": row["case_id"],
            "archive": row["archive"],
            "execution_receipt": row["execution_receipt"],
            "products": {
                name: row[name]
                for name in ("audit", "result", "observations", "trajectory")
            },
        })
    source_digest = collector.canonical_sha256({
        "design": design_ref,
        "archive_roots": [path.relative_to(root).as_posix() for path in roots],
        "indexed_products": indexed_bindings,
        "duplicate_archives": duplicate_archives,
        "qualification_excluded_archives": excluded_archives,
        "skipped_archives": skipped_archives,
    })
    split_counts = Counter(row["split"] for row in rows)
    return {
        "schema": SCHEMA,
        "product_schema": PRODUCT_SCHEMA,
        "version": 1,
        "family": collector.FAMILY,
        "scope_id": collector.SCOPE_ID,
        "registered_denominator": collector.EXPECTED_CASE_COUNT,
        "fixed_split_counts": dict(sorted(collector.EXPECTED_SPLITS.items())),
        "indexed_split_counts": dict(sorted(split_counts.items())),
        "production_design": design_ref,
        "design_summary": design_summary,
        "archive_roots": [path.relative_to(root).as_posix() for path in roots],
        "scanned_archive_count": scanned,
        "successful_archive_count": successful,
        "indexed_case_count": len(rows),
        "duplicate_archive_count": len(duplicate_archives),
        "qualification_excluded_archive_count": len(excluded_archives),
        "skipped_archive_count": len(skipped_archives),
        "indexed_case_indices": [row["index"] for row in rows],
        "source_sha256": source_digest,
        "products": rows,
        "duplicate_archives": duplicate_archives,
        "qualification_excluded_archives": excluded_archives,
        "skipped_archives": skipped_archives,
        "read_only": True,
        "central_registry_written": False,
        "ledger_written": False,
        "gpu_started": False,
        "formal_release": False,
    }


def refresh_f4_collection(
    production_design: str | Path | Mapping[str, Any],
    batch_manifest: str | Path | Mapping[str, Any]
    | Sequence[str | Path | Mapping[str, Any]],
    qualification_receipt: str | Path | Mapping[str, Any],
    archive_roots: Sequence[str | Path],
    data_root: str | Path,
    *,
    formal_release_requested: bool = False,
) -> dict[str, Any]:
    """Refresh the product index and collect its current partial view."""
    product_index = refresh_product_index(production_design, archive_roots, data_root)
    collection = collector.collect_f4_production(
        production_design,
        batch_manifest,
        qualification_receipt,
        data_root,
        products=product_index,
        formal_release_requested=formal_release_requested,
    )
    return {
        "schema": "core.f4.tallwall120.production_refresh.v1",
        "product_index": product_index,
        "collection": collection,
        "read_only": True,
        "central_registry_written": False,
        "ledger_written": False,
        "gpu_started": False,
        "formal_release": False,
    }


def write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    """Write a new diagnostic artifact without overwriting a prior refresh."""
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"refresh output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True,
                                    ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")
    temporary.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-design", type=Path, required=True)
    parser.add_argument("--batch-manifest", type=Path, action="append", required=True)
    parser.add_argument("--qualification-receipt", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, action="append", required=True,
                        help="one or more verified archive roots")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--product-index-output", type=Path, required=True)
    parser.add_argument("--collection-output", type=Path, required=True)
    parser.add_argument("--request-formal-release", action="store_true",
                        help="request the collector's formal checks; never changes release state")
    args = parser.parse_args(argv)
    product_index = refresh_product_index(
        args.production_design, args.archive_root, args.data_root)
    collection = collector.collect_f4_production(
        args.production_design,
        args.batch_manifest[0] if len(args.batch_manifest) == 1 else args.batch_manifest,
        args.qualification_receipt,
        args.data_root,
        products=product_index,
        formal_release_requested=args.request_formal_release,
    )
    write_json(args.product_index_output, product_index)
    write_json(args.collection_output, collection)
    print(json.dumps({
        "product_index": str(args.product_index_output.resolve()),
        "collection": str(args.collection_output.resolve()),
        "registered_denominator": collector.EXPECTED_CASE_COUNT,
        "indexed_case_count": product_index["indexed_case_count"],
        "duplicate_archive_count": product_index["duplicate_archive_count"],
        "qualification_excluded_archive_count": product_index["qualification_excluded_archive_count"],
        "reader_case_count": collection["reader_case_count"],
        "formal_eligible": collection["formal_eligible"],
        "read_only": True,
    }, sort_keys=True))
    # Partial refresh is expected while the production batch is running.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
