#!/usr/bin/env python3
"""Build an explicit evidence-dimension inventory for the fourteen sentinels.

This is a source-bound inventory, not a scientific qualification report.  It
requires each dimension to be declared in a catalog record; it never infers a
dimension from a status string, filename, or free-text note.  Small proof or
report JSON files may be read and checked by this builder.  Native/VTK/HDF5
payloads are always deferred and cannot be marked as actual evidence by this
metadata-only command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


SCHEMA = "ds02.stage2.fourteen-reference-evidence-dimension-inventory.v1"
CATALOG_SCHEMA = "ds02.stage2.fourteen-reference-evidence-dimension-catalog.v1"
SENTINELS = tuple(f"F{family}-S{sentinel}" for family in range(1, 8) for sentinel in (1, 2))
DIMENSIONS = (
    "spatial_three_grid", "time_step", "output_sampling", "initial_support",
    "control_initial", "native_fields", "external_anchor",
    "integral_vs_output_separated",
)
SCOPES = {"small_proof", "source_plan", "deferred_parent_guard"}
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".vtu", ".h5", ".hdf5", ".part", ".hdf"}
SMALL_CAP = 16 * 1024 * 1024
EXPECTED_RECORDS = 41
UNKNOWN = "UNKNOWN"


class InventoryFailure(RuntimeError):
    pass


def _absolute(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _absolute(path)
    if path.is_symlink() or not path.is_file():
        raise InventoryFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > SMALL_CAP:
        raise InventoryFailure(f"{label} exceeds bounded catalog/report cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise InventoryFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise InventoryFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha_bytes(raw), "stat": after,
                   "read_scope": "bounded_small_json"}


def _concrete_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise InventoryFailure(f"{label} must contain a concrete SHA-256")
    return value.lower()


def _record_source(item: dict[str, Any], label: str) -> dict[str, Any]:
    path_value = item.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise InventoryFailure(f"{label} has no source path")
    path = _absolute(Path(path_value))
    mode = item.get("read_mode")
    if mode not in {"small_read", "deferred_parent"}:
        raise InventoryFailure(f"{label} read_mode must be explicit")
    declared_sha = _concrete_sha(item.get("sha256"), f"{label} sha256")
    declared_stat = item.get("stat")
    if not isinstance(declared_stat, dict):
        raise InventoryFailure(f"{label} needs a complete stat record")
    stat_fields = ("device", "inode", "bytes", "mtime_ns", "ctime_ns")
    if any(field not in declared_stat for field in stat_fields):
        raise InventoryFailure(f"{label} stat record is incomplete")
    expected_stat = {field: int(declared_stat[field]) for field in stat_fields}
    suffix = path.suffix.lower()
    if mode == "small_read":
        if suffix in PAYLOAD_SUFFIXES:
            raise InventoryFailure(f"{label} cannot read a native/VTK/HDF payload")
        if path.is_symlink() or not path.is_file():
            raise InventoryFailure(f"{label} small source is absent: {path}")
        before = _stat(path)
        if before["bytes"] > SMALL_CAP:
            raise InventoryFailure(f"{label} small source exceeds cap")
        raw = path.read_bytes()
        after = _stat(path)
        if before != after or len(raw) != before["bytes"]:
            raise InventoryFailure(f"{label} small source changed during read")
        if _sha_bytes(raw) != declared_sha:
            raise InventoryFailure(f"{label} small source SHA differs")
        if before != expected_stat:
            raise InventoryFailure(f"{label} small source stat differs")
        status = "SOURCE_READ_STABLE"
        read_by_builder = True
    else:
        if path.is_file() and not path.is_symlink():
            current = _stat(path)
            # A deferred source may be stat-checked without opening it.  It is
            # still not promoted to actual evidence by this builder.
            if current != expected_stat:
                raise InventoryFailure(f"{label} deferred source stat differs")
        status = "PARENT_AFTER_RESERVATION_REQUIRED"
        read_by_builder = False
    return {"path": str(path), "sha256": declared_sha, "stat": expected_stat,
            "read_mode": mode, "status": status,
            "payload_read_by_builder": read_by_builder}


def _validate_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise InventoryFailure("catalog schema mismatch")
    records = catalog.get("records")
    if not isinstance(records, list) or len(records) != EXPECTED_RECORDS:
        raise InventoryFailure(f"catalog must contain exactly {EXPECTED_RECORDS} explicit records")
    seen_ids: set[str] = set()
    seen_dimensions: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        label = f"catalog record {index}"
        if not isinstance(item, dict):
            raise InventoryFailure(f"{label} is not an object")
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in seen_ids:
            raise InventoryFailure(f"{label} has a duplicate/missing evidence_id")
        seen_ids.add(evidence_id)
        sentinel = item.get("sentinel_id")
        dimension = item.get("dimension")
        if sentinel not in SENTINELS:
            raise InventoryFailure(f"{label} has an invalid sentinel_id")
        if dimension not in DIMENSIONS:
            raise InventoryFailure(f"{label} must declare one fixed dimension")
        pair = (sentinel, dimension)
        if pair in seen_dimensions:
            raise InventoryFailure(f"{label} duplicates sentinel/dimension {pair}")
        seen_dimensions.add(pair)
        if not isinstance(item.get("actual"), bool) or not isinstance(item.get("observed"), bool):
            raise InventoryFailure(f"{label} must declare boolean actual and observed")
        scope = item.get("scope")
        if scope not in SCOPES:
            raise InventoryFailure(f"{label} has an invalid explicit scope")
        if item.get("status") is not None:
            # Status can describe a result, but it must never be the source of
            # actual/dimension classification.
            if not isinstance(item["status"], str):
                raise InventoryFailure(f"{label} status must be text when supplied")
        source = _record_source(item, label)
        if item["actual"] and item["observed"] and source["read_mode"] != "small_read":
            raise InventoryFailure(f"{label} actual evidence must be a guarded small proof/report")
        normalized.append({"evidence_id": evidence_id, "sentinel_id": sentinel,
                           "dimension": dimension, "actual": item["actual"],
                           "observed": item["observed"], "scope": scope,
                           "note": item.get("note", ""), "source": source})
    return normalized


def build(catalog_path: Path, output_path: Path) -> dict[str, Any]:
    catalog, catalog_record = _read_json(catalog_path, "fourteen-sentinel evidence catalog")
    records = _validate_catalog(catalog)
    by_sentinel: dict[str, dict[str, list[dict[str, Any]]]] = {
        sentinel: {dimension: [] for dimension in DIMENSIONS} for sentinel in SENTINELS
    }
    for record in records:
        by_sentinel[record["sentinel_id"]][record["dimension"]].append(record)
    rows: list[dict[str, Any]] = []
    for sentinel in SENTINELS:
        dimensions: dict[str, Any] = {}
        for dimension in DIMENSIONS:
            evidence = by_sentinel[sentinel][dimension]
            actual = [item for item in evidence if item["actual"] and item["observed"] and item["source"]["read_mode"] == "small_read"]
            plans = [item for item in evidence if not (item["actual"] and item["observed"])]
            if actual:
                status = "ACTUAL_DIAGNOSTIC_EVIDENCE"
            elif plans:
                status = "SOURCE_PLAN_ONLY"
            else:
                status = "UNAVAILABLE"
            dimensions[dimension] = {"status": status, "evidence": evidence,
                                    "actual_evidence_count": len(actual),
                                    "plan_or_unresolved_count": len(plans)}
        rows.append({"sentinel_id": sentinel, "dimensions": dimensions,
                     "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN},
                     "scientific_credit": 0})
    result = {"schema": SCHEMA, "status": "COMPLETE_EXPLICIT_FOURTEEN_DIMENSION_INVENTORY",
              "catalog": catalog_record, "record_count": len(records),
              "dimension_vocabulary": list(DIMENSIONS), "sentinels": rows,
              "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN},
              "scientific_credit": 0,
              "read_scope": {"catalog_and_small_proofs_only": True,
                             "native_vtk_hdf_payload_read": False,
                             "solver_launch": False, "dimension_inferred_from_status": False}}
    output_path = _absolute(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise InventoryFailure(f"refusing overwrite: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def _self_test_catalog(root: Path) -> Path:
    records: list[dict[str, Any]] = []
    for index in range(EXPECTED_RECORDS):
        sentinel = SENTINELS[index % len(SENTINELS)]
        dimension = DIMENSIONS[index % len(DIMENSIONS)]
        # Ensure each sentinel/dimension pair is unique while keeping exactly
        # 41 records for the real inventory contract.
        if any(item["sentinel_id"] == sentinel and item["dimension"] == dimension for item in records):
            sentinel = SENTINELS[(index + 1) % len(SENTINELS)]
            dimension = DIMENSIONS[(index + 3) % len(DIMENSIONS)]
        path = root / f"proof-{index:02d}.json"
        path.write_text(json.dumps({"evidence_id": f"fixture-{index:02d}", "index": index}), encoding="utf-8")
        stat = _stat(path)
        records.append({"evidence_id": f"fixture-{index:02d}", "sentinel_id": sentinel,
                        "dimension": dimension, "actual": index < 14,
                        "observed": index < 14, "scope": "small_proof" if index < 14 else "source_plan",
                        "status": "words_do_not_classify", "path": str(path),
                        "sha256": _sha_bytes(path.read_bytes()), "stat": stat,
                        "read_mode": "small_read"})
    path = root / "catalog.json"
    path.write_text(json.dumps({"schema": CATALOG_SCHEMA, "records": records}), encoding="utf-8")
    return path


def self_test() -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="fourteen-dimension-inventory-") as directory:
        root = Path(directory); catalog = _self_test_catalog(root); output = root / "inventory.json"
        result = build(catalog, output)
        assert result["record_count"] == EXPECTED_RECORDS
        assert len(result["sentinels"]) == len(SENTINELS)
        assert all(row["scientific_credit"] == 0 for row in result["sentinels"])
        bad = json.loads(catalog.read_text(encoding="utf-8"))
        bad["records"][0].pop("dimension")
        bad_path = root / "bad.json"; bad_path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            build(bad_path, root / "bad-out.json")
        except InventoryFailure:
            pass
        else:
            raise AssertionError("catalog without explicit dimension was accepted")
    print("PASS_FOURTEEN_EXPLICIT_EVIDENCE_DIMENSION_INVENTORY_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        try:
            self_test()
        except Exception as exc:
            print(f"FAILED_FOURTEEN_EXPLICIT_EVIDENCE_DIMENSION_INVENTORY_SELFTEST: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.catalog is None or args.output is None:
        parser.error("--build requires --catalog and --output")
    try:
        result = build(args.catalog, args.output)
    except (InventoryFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_EXPLICIT_EVIDENCE_DIMENSION_INVENTORY: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "record_count": result["record_count"],
                      "output": str(_absolute(args.output)), "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
