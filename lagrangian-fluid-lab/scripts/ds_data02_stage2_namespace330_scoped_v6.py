#!/usr/bin/env python3
"""Build a conservative ROOT307 catalog with aliases excluded from identity.

This is an additive successor to namespace330 V5.  V5 is retained as a
diagnostic artifact, but its ``canonical_case_id`` field was populated from
``physical_case_id`` even for the one unresolved historical alias.  V6 keeps
that physical lookup value as a historical reference and sets the canonical
identity to ``None`` for that row.  The seven cards therefore expose 335
current saved-mask identities and one explicit historical reference.  No
scientific, event, quality, split, or qualification credit is introduced.

The implementation delegates the bounded metadata join to V5 in a temporary
directory, then emits a new immutable V6 namespace.  It never edits V5 or
reads HDF5, BI4, raw arrays, JSONL, or solver output.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V5_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_namespace330_scoped_v5.py"
CATALOG_SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v6"
CARD_SCHEMA = "ds02.stage2.namespace330.scoped-family-card.v6"
REQUEST_SCHEMA = "ds02.stage2.namespace330.scoped-source-request.v6"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
CASE_COUNT = 336
ALIAS_STATUS = "HISTORICAL_ALIAS_UNRESOLVED"
ACTUAL_STATUS = "ACTUAL_SAVED_MASK_COMPLETED"


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load dependency: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V5 = _load_module(V5_SCRIPT, "ds02_namespace330_v5_for_v6")


class Namespace330ScopedV6Error(ValueError):
    """Malformed or over-promoted V6 metadata."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({key: item for key, item in value.items()
                                     if key != "sha256"}).encode()).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, role: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise Namespace330ScopedV6Error(f"{role} is not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Namespace330ScopedV6Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Namespace330ScopedV6Error(f"{role} must be a JSON object")
    return value


def write_new(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    if path.exists() or path.is_symlink():
        raise Namespace330ScopedV6Error(f"refusing to overwrite V6 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                      allow_nan=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return canonical_sha(value), hashlib.sha256(text.encode()).hexdigest()


def _alias(row: Mapping[str, Any]) -> bool:
    return row.get("lifecycle", {}).get("status") == ALIAS_STATUS


def _transform_record(row: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(row))
    physical = str(record.get("physical_case_id"))
    if _alias(record):
        record["canonical_case_id"] = None
        record["identity"] = {
            "status": "HISTORICAL_ALIAS_UNRESOLVED",
            "canonical_case_id": None,
            "historical_reference_case_id": physical,
            "identity_credit": False,
            "source_join_credit": False,
            "reason": "CURRENT physical_case_id is a historical lookup only; no saved-mask producer is bound",
        }
        record["claim_boundary"] = (
            "historical alias provenance only; no canonical identity, source, "
            "physical, event, quality, split, or qualification credit"
        )
    else:
        if record.get("lifecycle", {}).get("status") != ACTUAL_STATUS:
            raise Namespace330ScopedV6Error(
                f"unsupported non-alias lifecycle status for {physical}: "
                f"{record.get('lifecycle', {}).get('status')}"
            )
        record["canonical_case_id"] = physical
        record["identity"] = {
            "status": "CANONICAL_CURRENT_SAVED_MASK",
            "canonical_case_id": physical,
            "historical_reference_case_id": None,
            "identity_credit": True,
            "source_join_credit": record.get("source_join_status") == "EXACT_CURRENT_AUDIT_METADATA_JOIN",
            "reason": "current catalog row has one completed saved-mask producer; scientific labels remain unknown",
        }
    return record


def _card(rows: list[dict[str, Any]], family: str) -> dict[str, Any]:
    canonical_ids = [str(row["canonical_case_id"]) for row in rows
                     if row.get("canonical_case_id") is not None]
    historical_ids = [str(row["physical_case_id"]) for row in rows
                      if row.get("canonical_case_id") is None]
    refs = []
    for row in rows:
        refs.append({
            "canonical_case_id": row.get("canonical_case_id"),
            "historical_reference_case_id": (
                row["physical_case_id"] if row.get("canonical_case_id") is None else None
            ),
            "physical_case_id_lookup": row["physical_case_id"],
            "identity_status": row["identity"]["status"],
            "lifecycle_status": row["lifecycle"]["status"],
            "historical_alias": row["lifecycle"].get("historical_alias"),
            "actual_saved_mask_coverage": row["lifecycle"].get("actual_saved_mask_coverage"),
            "attempt_id": row["lifecycle"].get("attempt_id"),
            "producer_id": row["lifecycle"].get("producer_id"),
            "failed_retry_history_count": row["lifecycle"].get("failed_history_count"),
            "source_join_status": row.get("source_join_status"),
            "physical_union_group_id_v27": row.get("split", {}).get("physical_union_group_id_v27"),
            "split_safe": False,
            "physical_fate": "UNKNOWN",
            "event_labels": "UNKNOWN",
            "region_owner": "UNKNOWN",
            "control": "UNKNOWN",
            "quality": dict(UNKNOWN),
        })
    return {
        "schema": CARD_SCHEMA,
        "namespace": "namespace330-v6-root307",
        "family_id": family,
        "status": "DEVELOPMENT_SAVED_MASK_METADATA_ONLY",
        "development_material": True,
        "hidden_test": False,
        "qualification": dict(UNKNOWN),
        "case_count": len(rows),
        "canonical_case_count": len(canonical_ids),
        "canonical_case_ids": canonical_ids,
        "historical_reference_case_count": len(historical_ids),
        "historical_reference_case_ids": historical_ids,
        "case_refs": refs,
        "claim_boundary": (
            "canonical saved-mask identity only; historical aliases are references "
            "and no event/physical/quality/qualification credit is granted"
        ),
    }


def _make_v6(v5_catalog: Mapping[str, Any], v5_request: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    old_rows = v5_catalog.get("cases")
    if not isinstance(old_rows, list) or len(old_rows) != CASE_COUNT:
        raise Namespace330ScopedV6Error("V5 catalog does not contain 336 cases")
    rows = [_transform_record(row) for row in old_rows if isinstance(row, Mapping)]
    if len(rows) != CASE_COUNT:
        raise Namespace330ScopedV6Error("V5 catalog contains malformed case rows")
    aliases = [row for row in rows if row.get("canonical_case_id") is None]
    actual = [row for row in rows if row.get("canonical_case_id") is not None]
    if len(aliases) != 1 or len(actual) != 335:
        raise Namespace330ScopedV6Error(
            f"expected 335 canonical cases and one alias, got {len(actual)} and {len(aliases)}"
        )
    family_rows = {family: [row for row in rows if row.get("family_id") == family]
                   for family in FAMILIES}
    if any(len(items) != 48 for items in family_rows.values()):
        raise Namespace330ScopedV6Error("V6 family cards must contain 48 lookup rows")
    cards = {family: _card(family_rows[family], family) for family in FAMILIES}
    for family, card in cards.items():
        card["sha256"] = canonical_sha(card)
    summary = {
        "current_cases": CASE_COUNT,
        "canonical_current_saved_mask_cases": len(actual),
        "historical_alias_unresolved": len(aliases),
        "failed_retry_history_entries": sum(
            int(row["lifecycle"].get("failed_history_count", 0)) for row in rows
        ),
        "pending_no_credit_cases": 0,
        "unscheduled_cases": 0,
        "family_lookup_counts": {family: len(items) for family, items in family_rows.items()},
        "family_canonical_counts": {family: len(card["canonical_case_ids"])
                                    for family, card in cards.items()},
        "family_historical_reference_counts": {
            family: len(card["historical_reference_case_ids"])
            for family, card in cards.items()
        },
    }
    catalog = {
        "schema": CATALOG_SCHEMA,
        "namespace": "namespace330-v6-root307",
        "status": "DEVELOPMENT_SAVED_MASK_METADATA_ONLY",
        "development_material": True,
        "hidden_test": False,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "case_count": CASE_COUNT,
        "coverage": summary,
        "identity_policy": {
            "canonical_key": "canonical_case_id",
            "lookup_key": "physical_case_id_lookup",
            "unresolved_alias_canonical_case_id": None,
            "historical_aliases_are_canonical": False,
            "identity_credit_requires": [
                "CURRENT336 membership",
                "ACTUAL_SAVED_MASK_COMPLETED",
                "EXACT_CURRENT_AUDIT_METADATA_JOIN",
                "one completed terminal producer",
            ],
        },
        "current_binding": copy.deepcopy(v5_catalog.get("current_binding", {})),
        "lifecycle_binding": copy.deepcopy(v5_catalog.get("lifecycle_binding", {})),
        "source_inputs": copy.deepcopy(v5_catalog.get("source_inputs", [])),
        "claim_boundary": {
            "canonical_identity": "335 current saved-mask identities",
            "historical_alias": "one unresolved lookup reference with identity credit false",
            "physical_fate": "UNKNOWN",
            "event_labels": "UNKNOWN",
            "region_owner": "UNKNOWN",
            "control": "UNKNOWN",
            "quality": dict(UNKNOWN),
            "split_safe": False,
            "qualification_credit": "NONE",
        },
        "cards": cards,
        "cases": rows,
    }
    catalog["sha256"] = canonical_sha(catalog)
    request = {
        "schema": REQUEST_SCHEMA,
        "namespace": "namespace330-v6-root307",
        "request_id": "namespace330-scoped-v6-root307-001",
        "status": "READY_FOR_ROOT_SOURCE_METADATA_GUARD",
        "development_material": True,
        "hidden_test": False,
        "qualification": dict(UNKNOWN),
        "model_invoked": False,
        "builder": {
            "script": str(SCRIPT),
            "upstream_diagnostic": "namespace330 V5; historical alias correction only",
            "identity_join": "canonical_case_id only for non-alias current saved-mask rows",
            "failed_retry_history": "provenance only",
            "split": "V27 physical union groups remain split_safe=false",
        },
        "artifacts": {"catalog": {}, "family_cards": []},
        "source_inputs": copy.deepcopy(v5_request.get("source_inputs", catalog["source_inputs"])),
        "coverage": summary,
        "qualification_boundary": dict(UNKNOWN),
        "read_scope": {
            "bounded_json_only": True,
            "h5_opened": False,
            "bi4_opened": False,
            "raw_arrays_opened": False,
            "jsonl_opened": False,
            "solver_output_opened": False,
            "payload_hashes_deferred_to_parent_guard": True,
        },
        "identity_boundary": catalog["identity_policy"],
    }
    return catalog, request, cards


def build_namespace330_scoped_v6(*, current_path: Path | str, plan_path: Path | str,
                                 registry_path: Path | str, output_dir: Path | str,
                                 split_index_path: Path | str | None = None,
                                 source_access_path: Path | str | None = None) -> dict[str, Any]:
    """Build fresh V6 artifacts while leaving V5 and all inputs immutable."""
    output = Path(output_dir).expanduser().absolute()
    if output.exists() and any(output.iterdir()):
        raise Namespace330ScopedV6Error(f"V6 output must be a fresh directory: {output}")
    with tempfile.TemporaryDirectory(prefix="namespace330-v6-upstream-") as temp:
        upstream = Path(temp) / "v5"
        V5.build_namespace330_scoped_v5(
            current_path=current_path, plan_path=plan_path,
            registry_path=registry_path, output_dir=upstream,
            split_index_path=split_index_path, source_access_path=source_access_path,
            request_id="namespace330-v5-diagnostic-upstream-for-v6",
        )
        v5_catalog = read_json(upstream / "namespace330-scoped-v5-root307-catalog.json", "upstream V5 catalog")
        v5_request = read_json(upstream / "namespace330-scoped-v5-root307-source-request.json", "upstream V5 request")
        catalog, request, cards = _make_v6(v5_catalog, v5_request)
    output.mkdir(parents=True, exist_ok=True)
    catalog_path = output / "namespace330-scoped-v6-root307-catalog.json"
    catalog_canonical, catalog_file = write_new(catalog_path, catalog)
    cards_dir = output / "family-cards"
    card_refs = []
    for family in FAMILIES:
        card_path = cards_dir / f"{family}-namespace330-scoped-family-card-v6-root307.json"
        card = cards[family]
        card_canonical, card_file = write_new(card_path, card)
        card_refs.append({"family_id": family, "path": str(card_path),
                          "canonical_sha256": card_canonical, "file_sha256": card_file})
    request["artifacts"] = {
        "catalog": {"path": str(catalog_path), "canonical_sha256": catalog_canonical,
                    "file_sha256": catalog_file},
        "family_cards": card_refs,
    }
    request["sha256"] = canonical_sha(request)
    request_path = output / "namespace330-scoped-v6-root307-source-request.json"
    request_canonical, request_file = write_new(request_path, request)
    return {
        "schema": CATALOG_SCHEMA,
        "catalog_path": str(catalog_path),
        "catalog_sha256": catalog_canonical,
        "catalog_file_sha256": catalog_file,
        "request_path": str(request_path),
        "request_sha256": request_canonical,
        "request_file_sha256": request_file,
        "case_count": CASE_COUNT,
        "coverage": catalog["coverage"],
        "family_cards": card_refs,
    }


def load_namespace330_scoped_v6(output_dir: Path | str) -> dict[str, Any]:
    output = Path(output_dir).expanduser()
    catalog = read_json(output / "namespace330-scoped-v6-root307-catalog.json", "V6 catalog")
    request = read_json(output / "namespace330-scoped-v6-root307-source-request.json", "V6 request")
    if catalog.get("schema") != CATALOG_SCHEMA or catalog.get("sha256") != canonical_sha(catalog):
        raise Namespace330ScopedV6Error("V6 catalog schema/canonical SHA differs")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise Namespace330ScopedV6Error("V6 request schema/canonical SHA differs")
    rows = catalog.get("cases")
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise Namespace330ScopedV6Error("V6 catalog case count differs")
    aliases = [row for row in rows if isinstance(row, Mapping) and row.get("canonical_case_id") is None]
    canonical_rows = [row for row in rows if isinstance(row, Mapping) and row.get("canonical_case_id") is not None]
    if len(aliases) != 1 or len(canonical_rows) != 335:
        raise Namespace330ScopedV6Error("V6 canonical/alias cardinality differs")
    if request.get("artifacts", {}).get("catalog", {}).get("canonical_sha256") != catalog.get("sha256"):
        raise Namespace330ScopedV6Error("V6 request/catalog binding differs")
    for family in FAMILIES:
        path = output / "family-cards" / f"{family}-namespace330-scoped-family-card-v6-root307.json"
        card = read_json(path, f"V6 {family} card")
        if card.get("schema") != CARD_SCHEMA or card.get("sha256") != canonical_sha(card):
            raise Namespace330ScopedV6Error(f"V6 {family} card schema/canonical SHA differs")
        if card.get("case_count") != 48:
            raise Namespace330ScopedV6Error(f"V6 {family} card lookup count differs")
        if len(card.get("canonical_case_ids", [])) + len(card.get("historical_reference_case_ids", [])) != 48:
            raise Namespace330ScopedV6Error(f"V6 {family} card identity partition differs")
    return {
        "schema": CATALOG_SCHEMA,
        "case_count": CASE_COUNT,
        "coverage": catalog["coverage"],
        "catalog_sha256": catalog["sha256"],
        "request_sha256": request["sha256"],
        "canonical_case_count": len(canonical_rows),
        "historical_alias_count": len(aliases),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--plan", type=Path, required=True)
    build.add_argument("--registry", type=Path, required=True)
    build.add_argument("--split-index", type=Path)
    build.add_argument("--source-access", type=Path)
    build.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_namespace330_scoped_v6(
                current_path=args.current, plan_path=args.plan, registry_path=args.registry,
                split_index_path=args.split_index, source_access_path=args.source_access,
                output_dir=args.output)
        else:
            result = load_namespace330_scoped_v6(args.output)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 0
    except (OSError, Namespace330ScopedV6Error, json.JSONDecodeError, ValueError) as error:
        print(f"namespace330 V6: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
