#!/usr/bin/env python3
"""Read-only validator for the fresh194 full336 physical-role audit.

The decision surface is the small family-specific normalized tuple.  Rich
metadata signatures are retained as provenance and collision diagnostics only;
paths, IDs, hashes, resolution, time windows, and view metadata never count as
physical differences.  This validator reads/hashes JSON/XML metadata only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
AUDIT = HERE / "metadata" / "full336-physical-distinctness-audit.json"
SUMMARY = HERE / "metadata" / "physical-distinctness-summary.json"
FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
ALLOWED = {".json", ".xml", ".xmf"}
FORBIDDEN = {".bi4", ".h5", ".csv", ".dat", ".vtk", ".png"}
ABSENT = {
    "F2H10V2_OFFSET_V1",
    "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_BASELINE",
    "F7_OBSTACLE_QUINTIC_B08_A030",
    "F7_OBSTACLE_QUINTIC_B08_A065",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def leaf_values_are_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return bool(value) and all(leaf_values_are_numeric(item) for item in value)
    if isinstance(value, dict):
        return bool(value) and all(leaf_values_are_numeric(item) for item in value.values())
    return False


def forbidden_tuple_key(key: str) -> bool:
    low = key.lower()
    if low in {"id", "alias", "physical_discriminators"} or low.endswith("_id") or low.endswith("_alias"):
        return low != "physical_discriminators"
    return any(token in low for token in (
        "path", "sha", "hash", "receipt", "report", "resolution",
        "frame", "particle", "window", "time_window", "save_interval",
        "view", "camera", "contact",
    ))


def tuple_has_forbidden_keys(value: Any) -> list[str]:
    bad: list[str] = []
    def walk(current: Any, path: str = "") -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                kp = f"{path}.{key}" if path else str(key)
                # ``physical_discriminators`` is a role container from the
                # independent Root1452 proof; its numeric children are valid.
                if forbidden_tuple_key(str(key)) and str(key).lower() != "physical_discriminators":
                    bad.append(kp)
                walk(child, kp)
        elif isinstance(current, list):
            for i, child in enumerate(current):
                walk(child, f"{path}[{i}]")
    walk(value)
    return bad


def collect_metadata_refs(audit: dict[str, Any]) -> dict[str, str | None]:
    refs: dict[str, str | None] = {}
    for row in audit.get("cases", []):
        source = row.get("source_metadata", {})
        for item in source.get("metadata_refs", []):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                refs[item["path"]] = item.get("sha256")
        tuple_meta = row.get("family_physical_tuple", {}).get("metadata_sources", [])
        for item in tuple_meta:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                refs[item["path"]] = item.get("sha256")
    for group in ("authoritative_sources",):
        def walk(value: Any) -> None:
            if isinstance(value, dict):
                path = value.get("path")
                if isinstance(path, str) and Path(path).suffix.lower() in {".json", ".xml"}:
                    refs[path] = value.get("sha256")
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(audit.get(group, {}))
    for key in ("pinned_numeric_family_tuple_proof", "f3_endpoint_forcing_tuple_proof", "actual_lifecycle_omission_supplement"):
        item = audit.get(key, {})
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            refs[item["path"]] = item.get("sha256")
    return refs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=AUDIT)
    parser.add_argument("--summary", type=Path, default=SUMMARY)
    parser.add_argument("--verify-existing-metadata-sha", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    rows = audit.get("cases", [])

    if audit.get("schema") != "ds02.full336.physical-distinctness-role-audit.v1":
        add_error(errors, "wrong audit schema")
    if len(rows) != 336:
        add_error(errors, f"expected 336 rows, got {len(rows)}")
    counts = Counter(row.get("family_id") for row in rows)
    if set(counts) != set(FAMILIES) or any(counts[family] != 48 for family in FAMILIES):
        add_error(errors, f"family counts are not 48 each: {dict(counts)}")
    ids = [row.get("physical_case_id") for row in rows]
    if len(set(ids)) != 336:
        add_error(errors, "physical_case_id values are not globally unique")

    boundaries = audit.get("source_boundaries", {})
    for key in ("scientific_payload_IO", "scientific_payload_hashed", "scientific_payload_copied", "new_jobs", "shared_state_written"):
        if boundaries.get(key) is not False:
            add_error(errors, f"source boundary {key} is not false")
    if boundaries.get("case_credit") != 0 or boundaries.get("Q_N") != 0 or boundaries.get("Q_E") != 0:
        add_error(errors, "audit reports nonzero case credit/Q_N/Q_E")

    observed_absent = {
        row["physical_case_id"]
        for row in rows
        if row.get("native_condition_role", {}).get("true_field_absent")
    }
    if observed_absent != ABSENT:
        add_error(errors, f"native absence set mismatch: {sorted(observed_absent)}")
    if audit.get("native_field_role_closure", {}).get("unresolved_roles_remaining") != 0:
        add_error(errors, "native field-role closure has unresolved roles")

    family_summary = audit.get("family_summary", {})
    tuple_groups = audit.get("family_physical_tuple_collision_groups", {})
    if tuple_groups:
        add_error(errors, f"normalized family tuple collisions remain: {sorted(tuple_groups)}")

    tuple_hashes: dict[str, set[str]] = defaultdict(set)
    tuple_missing: dict[str, list[str]] = defaultdict(list)
    metadata_refs = collect_metadata_refs(audit)
    for row in rows:
        family = row.get("family_id")
        physical = row.get("physical_case_id")
        tuple_status = str(row.get("family_physical_tuple_status", ""))
        tuple_value = row.get("family_physical_tuple", {}).get("tuple_value")
        digest = row.get("family_physical_tuple_sha256")
        if not tuple_status.startswith(("PASS_CASE_BOUND", "UNCERTAIN_REQUIRED")):
            add_error(errors, f"{physical} has invalid tuple status {tuple_status}")
        if digest:
            if not leaf_values_are_numeric(tuple_value):
                add_error(errors, f"{physical} normalized tuple contains nonnumeric values")
            bad_keys = tuple_has_forbidden_keys(tuple_value)
            if bad_keys:
                add_error(errors, f"{physical} normalized tuple contains forbidden keys: {bad_keys}")
            tuple_hashes[family].add(digest)
        elif tuple_status.startswith("UNCERTAIN"):
            if not row.get("family_physical_tuple", {}).get("missing_required_fields"):
                add_error(errors, f"{physical} is uncertain without explicit missing tuple fields")
            tuple_missing[family].append(physical)
        else:
            add_error(errors, f"{physical} lacks normalized tuple SHA without uncertainty status")

        basis = row.get("physical_difference_basis", [])
        if not basis:
            add_error(errors, f"{physical} has no source evidence basis")
        resolution = row.get("source_metadata", {}).get("case_bound_resolution", {})
        if not resolution.get("cross_case_global_index_paths_excluded") or not resolution.get("request_input_owner_selected_by_case_id"):
            add_error(errors, f"{physical} lacks case-bound source resolution")
        for item in row.get("source_metadata", {}).get("metadata_refs", []):
            path = str(item.get("path", ""))
            suffix = Path(path).suffix.lower()
            if suffix not in ALLOWED:
                add_error(errors, f"unallowed metadata reference suffix: {path}")
            if suffix in FORBIDDEN or any(path.lower().endswith(s) for s in FORBIDDEN):
                add_error(errors, f"scientific payload reference leaked into audit: {path}")

    # A digest may recur across families, but not within one family.  The
    # normalized tuple groups emitted by the builder are the authoritative
    # collision check; recheck from rows to catch stale summary edits.
    for family in FAMILIES:
        fs = family_summary.get(family, {})
        membership = fs.get("membership", {})
        frozen8 = set(membership.get("frozen8_physical_case_ids", []))
        actual24 = set(membership.get("actual24_physical_case_ids", []))
        registered48 = set(membership.get("registered48_physical_case_ids", []))
        if len(frozen8) != 8 or len(actual24) != 24 or len(registered48) != 48:
            add_error(errors, f"{family} membership cardinality is not 8/24/48")
        if not frozen8 <= actual24 or not actual24 <= registered48:
            add_error(errors, f"{family} membership subset contract failed")
        if not membership.get("registered_matches_current_index"):
            add_error(errors, f"{family} registered membership does not match current index")
        expected_missing = sorted(tuple_missing.get(family, []))
        actual_missing = sorted(fs.get("family_physical_tuple_missing_case_ids", []))
        if expected_missing != actual_missing:
            add_error(errors, f"{family} tuple missing list disagrees with rows")
        if fs.get("family_physical_tuple_collision_groups"):
            add_error(errors, f"{family} family summary reports tuple collisions")

    if summary.get("schema") != "ds02.full336.physical-distinctness-summary.v2":
        add_error(errors, "wrong summary schema")
    conclusion = summary.get("conclusion", {})
    if conclusion.get("family_physical_tuple_collision_groups") != 0 or conclusion.get("family_physical_tuple_unique_per_family") is not True:
        add_error(errors, "summary does not report unique normalized family tuples")
    if conclusion.get("id_difference_alone_used_as_proof") is not False:
        add_error(errors, "summary does not explicitly reject ID-only proof")
    if conclusion.get("case_credit") != 0 or conclusion.get("Q_N") != 0 or conclusion.get("Q_E") != 0:
        add_error(errors, "summary reports nonzero credit/Q_N/Q_E")

    if args.verify_existing_metadata_sha:
        for path_text, recorded in metadata_refs.items():
            path = Path(path_text)
            if path.suffix.lower() not in {".json", ".xml"} or recorded is None:
                continue
            if not path.exists():
                add_error(errors, f"metadata source missing: {path}")
                continue
            actual = sha256(path)
            if actual != recorded:
                add_error(errors, f"metadata SHA drift: {path}")

    status = "FAIL" if errors else "PASS_WITH_EXPLICIT_MISSING_PHYSICAL_FIELDS" if tuple_missing else "PASS"
    report = {
        "status": status,
        "rows": len(rows),
        "families": dict(counts),
        "normalized_physical_tuples": {family: len(tuple_hashes.get(family, set())) for family in FAMILIES},
        "explicit_tuple_field_missing": {family: sorted(values) for family, values in tuple_missing.items()},
        "rich_signature_collision_groups_retained_not_proof": len(audit.get("signature_collision_groups", {})),
        "native_true_absences": sorted(observed_absent),
        "metadata_references_seen": len(metadata_refs),
        "external_sha_verification": bool(args.verify_existing_metadata_sha),
        "source_payload_IO": False,
        "new_jobs": False,
        "case_credit": 0,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
