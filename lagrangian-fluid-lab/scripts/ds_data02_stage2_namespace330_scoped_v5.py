#!/usr/bin/env python3
"""Build the latest ROOT307-bound namespace330 catalog and family cards.

This is a metadata-only successor to namespace330 v4.  It consumes the
current 336 catalog, the v4 lifecycle plan and its v4 producer registry.  It
selects one successful saved-mask producer per covered case, retains failed
retry history as provenance, and keeps the one unresolved historical alias
unassigned.  The resulting seven cards are development material: physical
fate, event labels, owner/source roles, QI/QN/QE and split safety remain
UNKNOWN.  No H5, BI4, raw array, JSONL or solver output is opened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

CURRENT_SCHEMA = "ds02.stage2.current336.v1"
PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
REGISTRY_SCHEMA = "ds02.stage2.typed-lifecycle-evidence-registry.v4"
CATALOG_SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v5"
CARD_SCHEMA = "ds02.stage2.namespace330.scoped-family-card.v5"
REQUEST_SCHEMA = "ds02.stage2.namespace330.scoped-source-request.v5"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
CASE_COUNT = 336
CASES_PER_FAMILY = 48
MAX_METADATA_BYTES = 8 * 1024 * 1024
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
ACTUAL_STATUS = "ACTUAL_SAVED_MASK_COMPLETED"
ALIAS_STATUS = "HISTORICAL_ALIAS_UNRESOLVED"
SOURCE_JOIN = "EXACT_CURRENT_AUDIT_METADATA_JOIN"


class Namespace330ScopedV5Error(ValueError):
    """Latest lifecycle metadata is malformed or not safely joined."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({key: item for key, item in value.items()
                                     if key != "sha256"}).encode()).hexdigest()


def _regular(path: Path, role: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise Namespace330ScopedV5Error(f"{role} must be a regular non-symlink file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise Namespace330ScopedV5Error(f"{role} exceeds bounded metadata size: {path}")


def file_sha(path: Path, role: str) -> str:
    _regular(path, role)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path).expanduser()
    observed = file_sha(target, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Namespace330ScopedV5Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Namespace330ScopedV5Error(f"{role} must be a JSON object")
    stat = target.stat()
    return value, {"path": str(target.resolve()), "file_sha256": observed,
                   "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                   "ctime_ns": stat.st_ctime_ns, "st_dev": stat.st_dev,
                   "st_ino": stat.st_ino, "role": role,
                   "content_policy": "bounded JSON metadata only"}


def _ref_equal(left: Any, right: Any, role: str) -> None:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise Namespace330ScopedV5Error(f"{role} reference is missing")
    try:
        lp = Path(str(left["path"])).expanduser().resolve()
        rp = Path(str(right["path"])).expanduser().resolve()
    except (KeyError, OSError) as error:
        raise Namespace330ScopedV5Error(f"{role} path is malformed") from error
    if lp != rp or left.get("sha256", left.get("file_sha256")) != right.get("sha256", right.get("file_sha256")):
        raise Namespace330ScopedV5Error(f"{role} path/SHA differs")


def _source_ref(meta: Mapping[str, Any], role: str) -> dict[str, Any]:
    return {"path": meta["path"], "file_sha256": meta["file_sha256"],
            "bytes": meta["bytes"], "role": role,
            "content_policy": "bounded JSON metadata only"}


def _validate_current(current: Mapping[str, Any], current_meta: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise Namespace330ScopedV5Error("CURRENT catalog schema is not current336.v1")
    if current_meta.get("file_sha256") != CURRENT_SHA256:
        raise Namespace330ScopedV5Error("CURRENT catalog is not the pinned df7e...c62b catalog")
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise Namespace330ScopedV5Error("CURRENT catalog must contain exactly 336 cases")
    seen: set[str] = set()
    family_counts = {family: 0 for family in FAMILIES}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise Namespace330ScopedV5Error(f"CURRENT case {index} is not an object")
        case_id = row.get("physical_case_id")
        family = row.get("family_id")
        if not isinstance(case_id, str) or case_id in seen:
            raise Namespace330ScopedV5Error("CURRENT case identity is missing or duplicated")
        if family not in family_counts:
            raise Namespace330ScopedV5Error(f"CURRENT case {case_id} has unknown family")
        seen.add(case_id)
        family_counts[family] += 1
    if family_counts != {family: CASES_PER_FAMILY for family in FAMILIES}:
        raise Namespace330ScopedV5Error(f"CURRENT family counts are not seven groups of 48: {family_counts}")
    return rows


def _validate_plan_and_registry(plan: Mapping[str, Any], plan_meta: Mapping[str, Any],
                                registry: Mapping[str, Any], registry_meta: Mapping[str, Any],
                                current: Mapping[str, Any], current_meta: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise Namespace330ScopedV5Error("lifecycle plan is not typed-lifecycle-continuation-plan.v4")
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise Namespace330ScopedV5Error("evidence registry is not typed-lifecycle-evidence-registry.v4")
    _ref_equal(plan.get("current_catalog"), {"path": current_meta["path"], "sha256": CURRENT_SHA256}, "plan CURRENT catalog")
    _ref_equal(registry.get("current"), {"path": current_meta["path"], "sha256": CURRENT_SHA256}, "registry CURRENT catalog")
    _ref_equal(plan.get("evidence_registry"), {"path": registry_meta["path"], "sha256": registry_meta["file_sha256"]}, "plan evidence registry")
    rows = plan.get("case_records")
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise Namespace330ScopedV5Error("lifecycle plan must contain exactly 336 case records")
    current_ids = {str(row["physical_case_id"]) for row in current["cases"]}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise Namespace330ScopedV5Error("lifecycle plan case record is not an object")
        case_id = row.get("physical_case_id")
        if not isinstance(case_id, str) or case_id not in current_ids or case_id in seen:
            raise Namespace330ScopedV5Error(f"lifecycle plan identity is missing/duplicated: {case_id}")
        seen.add(case_id)
    if seen != current_ids:
        raise Namespace330ScopedV5Error("lifecycle plan and CURRENT identities differ")
    return rows


def _producer_for_case(registry: Mapping[str, Any], case_id: str, selected_id: str) -> tuple[dict[str, Any], int]:
    candidates = [item for item in registry.get("producers", [])
                  if isinstance(item, Mapping) and case_id in item.get("case_ids", [])]
    selected = [item for item in candidates if item.get("producer_id") == selected_id and item.get("status") == "COMPLETED"]
    if len(selected) != 1:
        raise Namespace330ScopedV5Error(f"{case_id} has no unique selected completed producer {selected_id}")
    completed = [item for item in candidates if item.get("status") == "COMPLETED"]
    if len(completed) != 1:
        raise Namespace330ScopedV5Error(f"{case_id} has ambiguous completed producer history")
    return dict(selected[0]), sum(1 for item in candidates if item.get("status") == "FAILED")


def _selected_record(plan_row: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(plan_row["physical_case_id"])
    status = plan_row.get("status")
    alias = plan_row.get("historical_alias")
    if status == ALIAS_STATUS:
        if alias == "NONE" or plan_row.get("actual_saved_mask_coverage") is True or plan_row.get("attempt_lineage"):
            raise Namespace330ScopedV5Error(f"{case_id} unresolved alias has covered producer metadata")
        return {"status": ALIAS_STATUS, "historical_alias": alias or ALIAS_STATUS,
                "attempt_id": None, "producer_id": None, "failed_history_count": 0,
                "producer_refs": [], "source_join_status": plan_row.get("source_join_status"),
                "actual_saved_mask_coverage": False}
    if status != ACTUAL_STATUS or alias != "NONE" or plan_row.get("actual_saved_mask_coverage") is not True:
        raise Namespace330ScopedV5Error(f"{case_id} has unsupported lifecycle status {status}")
    if plan_row.get("source_join_status") != SOURCE_JOIN:
        raise Namespace330ScopedV5Error(f"{case_id} lacks exact CURRENT source join")
    evidence = plan_row.get("producer_evidence")
    lineage = plan_row.get("attempt_lineage")
    if not isinstance(evidence, Mapping) or not isinstance(lineage, list):
        raise Namespace330ScopedV5Error(f"{case_id} lacks producer evidence/lineage")
    attempt = evidence.get("attempt_id")
    terminal = [item for item in lineage if isinstance(item, Mapping)
                and item.get("status") == ACTUAL_STATUS
                and item.get("actual_saved_mask_coverage") is True]
    if not isinstance(attempt, str) or len(terminal) != 1 or terminal[0].get("attempt_id") != attempt:
        raise Namespace330ScopedV5Error(f"{case_id} has no unique successful terminal attempt")
    producer_id = terminal[0].get("producer_id")
    if not isinstance(producer_id, str):
        raise Namespace330ScopedV5Error(f"{case_id} terminal producer is missing")
    producer, failed_count = _producer_for_case(registry, case_id, producer_id)
    bound_refs: dict[str, Mapping[str, Any]] = {}
    for key in ("request", "manifest", "proof"):
        ref = producer.get(key)
        # ROOT192's legacy single-case registry row predates the explicit
        # registry manifest field.  The immutable plan producer_evidence
        # carries the same case manifest binding; retain that distinction in
        # the output rather than silently inventing a registry reference.
        if key == "manifest" and not isinstance(ref, Mapping):
            ref = evidence.get("case_manifest")
        if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str):
            if key == "manifest":
                # ROOT192 is a valid saved-mask lifecycle producer, but its
                # single-case proof predates the explicit manifest binding.
                # Keep this as an honest missing-ref diagnostic; V5 does not
                # turn it into a scientific or portable source claim.
                continue
            raise Namespace330ScopedV5Error(f"{case_id} producer {key} reference is incomplete")
        bound_refs[key] = ref
    return {"status": ACTUAL_STATUS, "historical_alias": "NONE", "attempt_id": attempt,
            "producer_id": producer_id, "failed_history_count": failed_count,
            "producer_refs": [{"role": key, "path": bound_refs[key]["path"],
                                "file_sha256": bound_refs[key]["sha256"],
                                "content_policy": "proof/manifest/request metadata ref; payload deferred"}
                               for key in bound_refs],
            "missing_producer_refs": [key for key in ("request", "manifest", "proof") if key not in bound_refs],
            "source_join_status": SOURCE_JOIN, "actual_saved_mask_coverage": True}


def _optional_split(path: Path | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if path is None:
        return None, None
    value, meta = read_json(path, "effective-condition split index")
    if value.get("schema") != "ds02.stage2.all336-effective-condition-source-index.v27":
        raise Namespace330ScopedV5Error("split index is not V27")
    if value.get("sha256") != canonical_sha(value):
        raise Namespace330ScopedV5Error("split index canonical SHA mismatch")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != CASE_COUNT:
        raise Namespace330ScopedV5Error("split index must contain 336 cases")
    return value, meta


def _write_new(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    if path.exists() or path.is_symlink():
        raise Namespace330ScopedV5Error(f"refusing to overwrite scoped v5 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return canonical_sha(value), file_sha(path, "new scoped v5 artifact")


def build_namespace330_scoped_v5(*, current_path: Path | str, plan_path: Path | str,
                                 registry_path: Path | str, output_dir: Path | str,
                                 split_index_path: Path | str | None = None,
                                 source_access_path: Path | str | None = None,
                                 request_id: str = "namespace330-scoped-v5-root307-001") -> dict[str, Any]:
    current, current_meta = read_json(current_path, "CURRENT336 catalog")
    plan, plan_meta = read_json(plan_path, "ROOT307 lifecycle plan")
    registry, registry_meta = read_json(registry_path, "ROOT307 evidence registry")
    current_rows = _validate_current(current, current_meta)
    plan_rows = _validate_plan_and_registry(plan, plan_meta, registry, registry_meta, current, current_meta)
    split, split_meta = _optional_split(Path(split_index_path).expanduser() if split_index_path else None)
    split_rows = {str(row.get("physical_case_id")): row for row in split.get("cases", [])} if split else {}
    access = access_meta = None
    if source_access_path is not None:
        access, access_meta = read_json(source_access_path, "family source access metadata")
    plan_by_id = {str(row["physical_case_id"]): row for row in plan_rows}
    split_meta_by_id = {case_id: {
        "physical_union_group_id_v27": split_rows[case_id].get("physical_union_group_id_v27"),
        "physical_union_status": split_rows[case_id].get("physical_union_status"),
        "forbidden_cross_split_dimensions": split_rows[case_id].get("forbidden_cross_split_dimensions", ["resolution", "window", "recovery"]),
        "split_safe": False,
    } for case_id in split_rows}
    records: list[dict[str, Any]] = []
    for index, current_row in enumerate(current_rows):
        case_id = str(current_row["physical_case_id"])
        selected = _selected_record(plan_by_id[case_id], registry)
        record = {
            "current_index": index, "family_id": current_row["family_id"],
            "physical_case_id": case_id, "canonical_case_id": case_id,
            "runtime_case_alias": current_row.get("runtime_case_alias"),
            "lifecycle": selected,
            "source_join_status": selected["source_join_status"],
            "physical": {"fate": "UNKNOWN", "dynamics": "UNKNOWN", "event_labels": "UNKNOWN",
                          "region_owner": "UNKNOWN", "control": "UNKNOWN"},
            "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
                        "mass": "UNKNOWN", "native": "UNKNOWN", "visual": "UNKNOWN"},
            "split": split_meta_by_id.get(case_id, {
                "physical_union_group_id_v27": None,
                "physical_union_status": "UNKNOWN_UNASSIGNED",
                "forbidden_cross_split_dimensions": ["resolution", "window", "recovery"],
                "split_safe": False,
            }),
            "claim_boundary": "saved-mask lifecycle identity only; no scientific/event/qualification credit",
        }
        records.append(record)
    if len(records) != CASE_COUNT:
        raise Namespace330ScopedV5Error("v5 catalog did not produce 336 records")
    family_records = {family: [row for row in records if row["family_id"] == family] for family in FAMILIES}
    if any(len(rows) != CASES_PER_FAMILY for rows in family_records.values()):
        raise Namespace330ScopedV5Error("v5 family cards must contain exactly 48 cases")
    actual_count = sum(row["lifecycle"]["status"] == ACTUAL_STATUS for row in records)
    alias_count = sum(row["lifecycle"]["status"] == ALIAS_STATUS for row in records)
    failed_history = sum(row["lifecycle"]["failed_history_count"] for row in records)
    source_inputs = [_source_ref(current_meta, "CURRENT336"),
                     _source_ref(plan_meta, "ROOT307 typed lifecycle plan"),
                     _source_ref(registry_meta, "ROOT307 evidence registry")]
    if split_meta is not None:
        source_inputs.append(_source_ref(split_meta, "V27 leakage-safe physical split index"))
    if access_meta is not None:
        source_inputs.append(_source_ref(access_meta, "family source access metadata"))
    summary = {"current_cases": CASE_COUNT, "actual_saved_mask_cases": actual_count,
               "historical_alias_unresolved": alias_count, "failed_retry_history_entries": failed_history,
               "pending_no_credit_cases": 0, "unscheduled_cases": 0,
               "family_counts": {family: len(rows) for family, rows in family_records.items()}}
    catalog = {
        "schema": CATALOG_SCHEMA, "namespace": "namespace330-v5-root307", "status": "DEVELOPMENT_SAVED_MASK_METADATA_ONLY",
        "development_material": True, "hidden_test": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN), "case_count": CASE_COUNT, "coverage": summary,
        "current_binding": {"path": current_meta["path"], "file_sha256": current_meta["file_sha256"],
                             "schema": CURRENT_SCHEMA, "canonical_case_identity": "physical_case_id exact"},
        "lifecycle_binding": {"plan": _source_ref(plan_meta, "ROOT307 typed lifecycle plan"),
                               "registry": _source_ref(registry_meta, "ROOT307 evidence registry"),
                               "plan_schema": PLAN_SCHEMA, "registry_schema": REGISTRY_SCHEMA},
        "source_inputs": source_inputs,
        "claim_boundary": {
            "saved_mask_identity": "actual saved-mask lifecycle only; selected proof refs remain metadata-bound",
            "physical_fate": "UNKNOWN", "event_labels": "UNKNOWN", "region_owner": "UNKNOWN", "control": "UNKNOWN",
            "quality": dict(UNKNOWN), "split_safe": False, "qualification_credit": "NONE",
        },
        "cases": records,
    }
    catalog["sha256"] = canonical_sha(catalog)
    out = Path(output_dir).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise Namespace330ScopedV5Error(f"v5 output must be a fresh directory: {out}")
    out.mkdir(parents=True, exist_ok=True)
    catalog_path = out / "namespace330-scoped-v5-root307-catalog.json"
    catalog_canonical, catalog_file = _write_new(catalog_path, catalog)
    cards_dir = out / "family-cards"
    card_refs: list[dict[str, Any]] = []
    for family in FAMILIES:
        rows = family_records[family]
        card = {
            "schema": CARD_SCHEMA, "namespace": "namespace330-v5-root307", "family_id": family,
            "status": "DEVELOPMENT_SAVED_MASK_METADATA_ONLY", "development_material": True,
            "hidden_test": False, "qualification": dict(UNKNOWN), "case_count": len(rows),
            "canonical_case_ids": [row["canonical_case_id"] for row in rows],
            "case_refs": [{"canonical_case_id": row["canonical_case_id"],
                           "physical_case_id": row["physical_case_id"],
                           "lifecycle_status": row["lifecycle"]["status"],
                           "historical_alias": row["lifecycle"]["historical_alias"],
                           "actual_saved_mask_coverage": row["lifecycle"]["actual_saved_mask_coverage"],
                           "attempt_id": row["lifecycle"]["attempt_id"],
                           "producer_id": row["lifecycle"]["producer_id"],
                           "failed_retry_history_count": row["lifecycle"]["failed_history_count"],
                           "source_join_status": row["source_join_status"],
                           "physical_union_group_id_v27": row["split"]["physical_union_group_id_v27"],
                           "split_safe": False, "physical_fate": "UNKNOWN", "event_labels": "UNKNOWN",
                           "region_owner": "UNKNOWN", "control": "UNKNOWN", "quality": dict(UNKNOWN)}
                          for row in rows],
            "claim_boundary": "seven-family development card; no event/physical/Q credit",
        }
        card["sha256"] = canonical_sha(card)
        path = cards_dir / f"{family}-namespace330-scoped-family-card-v5-root307.json"
        card_canonical, card_file = _write_new(path, card)
        card_refs.append({"family_id": family, "path": str(path), "canonical_sha256": card_canonical, "file_sha256": card_file})
    request = {
        "schema": REQUEST_SCHEMA, "namespace": "namespace330-v5-root307", "request_id": request_id,
        "status": "READY_FOR_ROOT_SOURCE_METADATA_GUARD", "development_material": True,
        "hidden_test": False, "qualification": dict(UNKNOWN), "model_invoked": False,
        "builder": {"script": str(Path(__file__).resolve()), "plan": "ROOT307 v4", "join": "exact physical_case_id + selected terminal producer",
                     "failed_retry_history": "provenance only", "split": "V27 groups remain split_safe=false"},
        "artifacts": {"catalog": {"path": str(catalog_path), "canonical_sha256": catalog_canonical, "file_sha256": catalog_file},
                      "family_cards": card_refs},
        "source_inputs": source_inputs, "coverage": summary, "qualification_boundary": dict(UNKNOWN),
        "read_scope": {"bounded_json_only": True, "h5_opened": False, "bi4_opened": False,
                        "raw_arrays_opened": False, "jsonl_opened": False, "solver_output_opened": False,
                        "payload_hashes_deferred_to_parent_guard": True},
    }
    request["sha256"] = canonical_sha(request)
    request_path = out / "namespace330-scoped-v5-root307-source-request.json"
    request_canonical, request_file = _write_new(request_path, request)
    return {"schema": CATALOG_SCHEMA, "catalog_path": str(catalog_path), "catalog_sha256": catalog_canonical,
            "catalog_file_sha256": catalog_file, "request_path": str(request_path),
            "request_sha256": request_canonical, "request_file_sha256": request_file,
            "case_count": CASE_COUNT, "coverage": summary, "family_cards": card_refs}


def load_namespace330_scoped_v5(output_dir: Path | str) -> dict[str, Any]:
    out = Path(output_dir).expanduser()
    catalog, _ = read_json(out / "namespace330-scoped-v5-root307-catalog.json", "v5 catalog")
    request, _ = read_json(out / "namespace330-scoped-v5-root307-source-request.json", "v5 request")
    if catalog.get("schema") != CATALOG_SCHEMA or catalog.get("sha256") != canonical_sha(catalog):
        raise Namespace330ScopedV5Error("v5 catalog schema/SHA mismatch")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise Namespace330ScopedV5Error("v5 request schema/SHA mismatch")
    if catalog.get("case_count") != CASE_COUNT or len(catalog.get("cases", [])) != CASE_COUNT:
        raise Namespace330ScopedV5Error("v5 catalog case count is not 336")
    if request.get("artifacts", {}).get("catalog", {}).get("canonical_sha256") != catalog.get("sha256"):
        raise Namespace330ScopedV5Error("v5 request/catalog binding differs")
    return {"schema": CATALOG_SCHEMA, "case_count": CASE_COUNT, "coverage": catalog["coverage"],
            "catalog_sha256": catalog["sha256"], "request_sha256": request["sha256"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--registry", type=Path, required=True)
    build.add_argument("--split-index", type=Path)
    build.add_argument("--source-access", type=Path)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--request-id", default="namespace330-scoped-v5-root307-001")
    validate = sub.add_parser("validate")
    validate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = (build_namespace330_scoped_v5(current_path=args.current, plan_path=args.plan,
                                                registry_path=args.registry, split_index_path=args.split_index,
                                                source_access_path=args.source_access, output_dir=args.output,
                                                request_id=args.request_id)
                  if args.command == "build" else load_namespace330_scoped_v5(args.output))
    except (OSError, Namespace330ScopedV5Error, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
