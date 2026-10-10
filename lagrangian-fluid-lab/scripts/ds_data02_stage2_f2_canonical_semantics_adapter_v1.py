#!/usr/bin/env python3
"""Fail-closed semantic adapter for canonical F2 CURRENT row 65.

This module is the explicit boundary between the canonical row-65 request and
the immutable historical v14/v15 operators.  It validates identity and the
stage ABI without changing, importing, or relabelling those operators.  A
caller must provide a copied canonical reader/restorer/label pipeline; the
adapter rejects a request that tries to send row 65 through the historical
row-78 gate.

It intentionally has no raw/BI4/HDF5 reader.  Its successful result means
"canonical semantics are bound and the next parent stage may run", while
scientific conversion, labels, portability, and qualification remain
deferred until the guarded worker has actual source hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.f2-canonical-semantics-binding.v1"
RESULT_SCHEMA = "ds02.stage2.f2-canonical-semantics-result.v1"
CANONICAL_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"
HISTORICAL_ALIAS_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
STAGE_ORDER = ("canonical_adapter", "raw_converter", "reader", "restorer",
               "worker", "label_producer", "portable_scorer")
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024


class SemanticsError(ValueError):
    """Canonical identity or pipeline semantics are unsafe."""


def _json(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise SemanticsError(f"{role} must be a regular non-symlink file")
    if target.stat().st_size > MAX_JSON_BYTES:
        raise SemanticsError(f"{role} exceeds the bounded JSON limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SemanticsError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise SemanticsError(f"{role} must be an object")
    return value


def _canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True).encode("utf-8")).hexdigest()


def _source_sha(path: Path, role: str, namespace: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise SemanticsError(f"{role} source is not a regular copied file")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(namespace)
    except ValueError as error:
        raise SemanticsError(f"{role} source escapes the copied namespace") from error
    if resolved.stat().st_size > MAX_SOURCE_BYTES:
        raise SemanticsError(f"{role} source exceeds the bounded source limit")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(binding: Mapping[str, Any]) -> dict[str, Any]:
    if binding.get("schema") != SCHEMA:
        raise SemanticsError("unsupported canonical semantics binding schema")
    identity = binding.get("case_identity")
    current = binding.get("current_binding")
    if not isinstance(identity, Mapping) or not isinstance(current, Mapping):
        raise SemanticsError("case_identity and current_binding are required")
    if identity.get("current_case_index") != 65:
        raise SemanticsError("canonical semantics require CURRENT row 65")
    if identity.get("physical_case_id") != CANONICAL_ID:
        raise SemanticsError("canonical semantics require the RX047/ROT075 case")
    if identity.get("physical_case_id") == HISTORICAL_ALIAS_ID:
        raise SemanticsError("historical unresolved alias is not canonical")
    if current.get("case_index") == 78 or current.get("sha256") != CURRENT_SHA:
        raise SemanticsError("current binding is not the pinned canonical source")
    if identity.get("runtime_case_alias") == HISTORICAL_ALIAS_ID:
        raise SemanticsError("runtime alias is the historical row-78 identity")
    legacy = binding.get("legacy_operator")
    if legacy is not None:
        if not isinstance(legacy, Mapping):
            raise SemanticsError("legacy_operator must be an object")
        if legacy.get("case_index") == 78 or legacy.get("physical_case_id") == HISTORICAL_ALIAS_ID:
            raise SemanticsError("row-78 operator cannot be used as the canonical reader")
        if legacy.get("fallback") not in {None, "REJECT"}:
            raise SemanticsError("legacy operator fallback must be rejected")
    stages = binding.get("stages")
    if not isinstance(stages, list) or [item.get("role") for item in stages if isinstance(item, Mapping)] != list(STAGE_ORDER):
        raise SemanticsError("pipeline stage order is not canonical converter/reader/restorer/label/scorer ABI")
    namespace_value = binding.get("namespace_root")
    if not isinstance(namespace_value, str):
        raise SemanticsError("canonical stages require a copied namespace_root")
    namespace = Path(namespace_value).expanduser().resolve(strict=False)
    if not namespace.is_absolute() or not namespace.is_dir():
        raise SemanticsError("canonical namespace_root must be an existing directory")
    if any(not isinstance(item, Mapping) or not isinstance(item.get("path"), str) or
           not isinstance(item.get("sha256"), str) or len(item["sha256"]) != 64 for item in stages):
        raise SemanticsError("every canonical stage needs a source path and SHA")
    for item in stages:
        actual_sha = _source_sha(Path(str(item["path"])).expanduser(), str(item["role"]), namespace)
        if actual_sha != item["sha256"]:
            raise SemanticsError(f"{item['role']} source SHA differs from target")
    if len({item["path"] for item in stages}) != len(stages):
        raise SemanticsError("canonical stages must be distinct copied sources")
    if binding.get("source_fallback") not in {"REJECT", "FORBIDDEN"}:
        raise SemanticsError("canonical source fallback must be forbidden")
    result = {
        "schema": RESULT_SCHEMA,
        "status": "CANONICAL65_SEMANTICS_BOUND_PARENT_GUARD_REQUIRED",
        "case_identity": {"current_case_index": 65, "physical_case_id": CANONICAL_ID,
                          "historical_alias_rejected": HISTORICAL_ALIAS_ID},
        "stage_order": list(STAGE_ORDER),
        "namespace_root": str(namespace),
        "source_hashes_verified": True,
        "legacy_operator": {"row78_reused": False, "fallback": "REJECT",
                             "canonical_adapter_required": True},
        "raw_payload_read": False,
        "typed_or_label_payload_read": False,
        "scientific_credit": "NONE",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    result["sha256"] = _canonical(result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(_json(args.binding, "canonical semantics binding"))
        if args.output.exists():
            raise SemanticsError(f"refusing to overwrite {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, SemanticsError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "sha256": result["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
