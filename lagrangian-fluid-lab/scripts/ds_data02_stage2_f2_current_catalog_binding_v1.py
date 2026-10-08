#!/usr/bin/env python3
"""Join the frozen F2 V15 request to the real CURRENT336 row.

The typed V16 result consumed by the V10 proof contains an inherited
``aabfb...`` current-catalog value.  The frozen V15 request and the actual
CURRENT336 file are the authoritative small-source bindings for this
forward-only audit.  This module records the mismatch explicitly and never
silently upgrades the historical proof to an exact-current claim.

Only JSON metadata is read.  The trajectory HDF5, BI4 files, and the 62 MB
typed result are deliberately outside this module's input surface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-current-catalog-binding.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
FROZEN_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
ACTUAL_CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_RESULT_CURRENT_SHA256 = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
MAX_JSON_BYTES = 8 * 1024 * 1024
HEX64 = set("0123456789abcdef")


class CurrentBindingError(RuntimeError):
    """A CURRENT/V15/proof metadata binding cannot be established."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise CurrentBindingError(f"{name} must be a lowercase SHA-256")
    return value


def _file(value: Any, role: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise CurrentBindingError(f"{role} path is missing")
    target = Path(value).expanduser().resolve()
    if target.is_symlink() or not target.is_file():
        raise CurrentBindingError(f"{role} is not a regular non-symlink file: {target}")
    return target


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    if target.stat().st_size > MAX_JSON_BYTES:
        raise CurrentBindingError(f"{role} exceeds metadata-only bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CurrentBindingError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise CurrentBindingError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise CurrentBindingError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _identity(value: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "current_case_index", "family_id", "manifest_case_id",
        "manifest_physical_case_id", "physical_case_id", "runtime_case_alias",
    )
    result = {key: value.get(key) for key in required}
    if not isinstance(result["current_case_index"], int) or isinstance(result["current_case_index"], bool):
        raise CurrentBindingError("case identity current_case_index must be an integer")
    if any(not isinstance(result[key], str) or not result[key] for key in required[1:]):
        raise CurrentBindingError("case identity contains a missing string")
    return result


def _row_evidence(row: Mapping[str, Any], role: str) -> tuple[str | None, str | None, str]:
    """Return a catalog-row digest/path where CURRENT explicitly represents role."""
    if role == "current_catalog":
        return None, None, "document_level"
    source_bindings = row.get("source_bindings")
    if isinstance(source_bindings, Mapping):
        item = source_bindings.get(role)
        if isinstance(item, Mapping):
            digest = item.get("recomputed_sha256") or item.get("sha256")
            return digest if isinstance(digest, str) else None, item.get("path"), "source_bindings"
    item = row.get(role)
    if isinstance(item, Mapping):
        digest = item.get("recomputed_sha256") or item.get("sha256")
        if digest is None and role == "trajectory":
            digest = item.get("producer_declared_sha256")
        return digest if isinstance(digest, str) else None, item.get("path"), "row_field"
    return None, None, "not_represented"


def _load_inputs(current_catalog: Path | str, frozen_request: Path | str,
                 proof: Path | str) -> tuple[Path, dict[str, Any], Path, dict[str, Any], Path, dict[str, Any]]:
    current_path, current = _json(current_catalog, "CURRENT336 catalog")
    frozen_path, frozen = _json(frozen_request, "frozen V15 request")
    proof_path, proof_value = _json(proof, "historical V10 proof")
    if current.get("schema") != CURRENT_SCHEMA:
        raise CurrentBindingError("CURRENT336 schema differs")
    if len(current.get("cases", [])) != 336 or not isinstance(current.get("cases"), list):
        raise CurrentBindingError("CURRENT336 does not contain exactly 336 cases")
    actual_sha = sha256_file(current_path)
    if actual_sha != ACTUAL_CURRENT_SHA256:
        raise CurrentBindingError(
            f"CURRENT336 SHA differs: observed {actual_sha}, expected {ACTUAL_CURRENT_SHA256}"
        )
    # The historical V15 request is an immutable producer spec without its
    # own top-level canonical ``sha256`` field.  Its file SHA is recorded in
    # the sidecar; if a future copy supplies a canonical field, validate it.
    if frozen.get("schema") != FROZEN_SCHEMA:
        raise CurrentBindingError("frozen request schema differs")
    if "sha256" in frozen and frozen.get("sha256") != canonical_sha(frozen):
        raise CurrentBindingError("frozen request canonical SHA differs")
    if proof_value.get("schema") != PROOF_SCHEMA or proof_value.get("sha256") != canonical_sha(proof_value):
        raise CurrentBindingError("historical proof schema/canonical SHA differs")
    return current_path, current, frozen_path, frozen, proof_path, proof_value


def build_binding(*, current_catalog: Path | str, frozen_request: Path | str,
                  proof: Path | str, output: Path | str) -> dict[str, Any]:
    current_path, current, frozen_path, frozen, proof_path, proof_value = _load_inputs(
        current_catalog, frozen_request, proof
    )
    expected_identity = _identity(frozen.get("case_identity", {}))
    row = current["cases"][expected_identity["current_case_index"]]
    actual_identity = {
        "current_case_index": expected_identity["current_case_index"],
        "family_id": row.get("family_id"),
        "manifest_case_id": expected_identity["manifest_case_id"],
        "manifest_physical_case_id": row.get("physical_case_id"),
        "physical_case_id": row.get("physical_case_id"),
        "runtime_case_alias": row.get("runtime_case_alias"),
    }
    identity_fields = (
        "current_case_index", "family_id", "manifest_physical_case_id",
        "physical_case_id", "runtime_case_alias",
    )
    for field in identity_fields:
        if actual_identity[field] != expected_identity[field]:
            raise CurrentBindingError(f"CURRENT row identity differs for {field}")
    if row.get("manifest", {}).get("path") is None or row.get("xmf", {}).get("path") is None:
        raise CurrentBindingError("CURRENT row lacks manifest/XMF source anchors")

    current_sha = sha256_file(current_path)
    frozen_current = frozen.get("current_binding", {})
    frozen_current_sha = frozen_current.get("sha256")
    if frozen_current_sha != current_sha:
        raise CurrentBindingError("frozen V15 current_binding does not match actual CURRENT336")
    source_files = frozen.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise CurrentBindingError("frozen V15 source_files are missing")
    joins: list[dict[str, Any]] = []
    for item in source_files:
        if not isinstance(item, Mapping):
            raise CurrentBindingError("frozen V15 source_files contains malformed entry")
        role = item.get("role")
        expected_sha = _sha(item.get("sha256"), f"frozen source {role}")
        observed_sha, observed_path, evidence = _row_evidence(row, str(role))
        if role == "current_catalog":
            observed_sha, observed_path, evidence = current_sha, str(current_path), "catalog_file"
        match = observed_sha == expected_sha if observed_sha is not None else None
        if match is False:
            raise CurrentBindingError(f"CURRENT row source evidence differs for role {role}")
        joins.append({
            "role": role, "frozen_path": item.get("path"),
            "frozen_sha256": expected_sha, "current_row_sha256": observed_sha,
            "current_row_path": observed_path, "current_row_evidence": evidence,
            "status": "MATCH" if match is True else "FROZEN_EXPLICIT_NOT_REPEATED_IN_CURRENT_ROW",
        })

    inherited = proof_value.get("source_binding")
    if not isinstance(inherited, Mapping):
        raise CurrentBindingError("historical proof source_binding is missing")
    inherited_sha = inherited.get("current_catalog_sha256")
    _sha(inherited_sha, "historical proof current_catalog_sha256")
    inherited_source_sha = inherited.get("source_files", {}).get("current_catalog") if isinstance(inherited.get("source_files"), Mapping) else None
    _sha(inherited_source_sha, "historical proof source_files.current_catalog")
    if inherited_sha != inherited_source_sha:
        raise CurrentBindingError("historical proof current-catalog fields disagree")
    if inherited_sha != HISTORICAL_RESULT_CURRENT_SHA256:
        raise CurrentBindingError("unexpected historical result current-catalog SHA")

    source_catalog_embedded = current.get("source_catalog")
    source_catalog_embedded_sha = current.get("source_catalog_sha256")
    _sha(source_catalog_embedded_sha, "CURRENT embedded source catalog SHA")
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_FROZEN_V15_CURRENT_JOIN_RESULT_BINDING_STALE",
        "metadata_only": True,
        "current_catalog": {
            "path": str(current_path), "sha256": current_sha,
            "bytes": current_path.stat().st_size, "schema": current.get("schema"),
            "case_count": len(current["cases"]),
            "embedded_source_catalog": source_catalog_embedded,
            "embedded_source_catalog_sha256": source_catalog_embedded_sha,
            "embedded_source_catalog_is_not_current_file_sha": True,
        },
        "frozen_v15_request": {
            "path": str(frozen_path), "sha256": sha256_file(frozen_path),
            "schema": frozen.get("schema"),
            "current_binding": {
                "path": frozen_current.get("path"), "sha256": frozen_current_sha,
                "case_index": frozen_current.get("case_index"),
                "binding_status": frozen_current.get("binding_status"),
            },
        },
        "historical_v10_proof": {
            "path": str(proof_path), "sha256": sha256_file(proof_path),
            "schema": proof_value.get("schema"),
            "declared_binding_status": inherited.get("binding_status"),
            "declared_current_catalog_sha256": inherited_sha,
            "declared_source_files_current_catalog_sha256": inherited_source_sha,
            "current_catalog_sha256_matches_actual": False,
            "historical_binding_is_not_exact_current": True,
        },
        "case_join": {
            "expected_from_frozen_v15": expected_identity,
            "actual_current336_row": actual_identity,
            "current_row_canonical_sha256": hashlib.sha256(json.dumps(
                row, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                allow_nan=False, default=str).encode("utf-8")).hexdigest(),
            "status": "EXACT_CASE_INDEX_PHYSICAL_AND_RUNTIME_ALIAS_JOIN",
        },
        "source_file_join": joins,
        "source_binding_reconciliation": {
            "historical_result_current_catalog_sha256": inherited_sha,
            "actual_current_catalog_sha256": current_sha,
            "frozen_v15_current_catalog_sha256": frozen_current_sha,
            "result_binding_reconciled_by_this_sidecar": True,
            "old_result_and_old_proof_bytes_unchanged": True,
            "no_result_content_read": True,
            "no_hdf5_bi4_raw_content_read": True,
        },
        "credit_boundary": {
            "historical_v10_exact_current_claim": "REJECTED_STALE_CATALOG_BINDING",
            "current_row_join": "DEVELOPMENT_METADATA_ONLY",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "portable_cold_replay": "NOT_CLAIMED",
        },
    }
    value["sha256"] = canonical_sha(value)
    target = _write_new(output, value)
    return {"status": value["status"], "binding": str(target),
            "sha256": value["sha256"], "current_catalog_sha256": current_sha,
            "frozen_v15_current_catalog_sha256": frozen_current_sha,
            "historical_result_current_catalog_sha256": inherited_sha,
            "case_index": expected_identity["current_case_index"],
            "case_id": expected_identity["manifest_case_id"],
            "source_roles": len(joins), "metadata_only": True}


def validate_binding(path: Path | str, *, current_catalog: Path | str | None = None,
                     frozen_request: Path | str | None = None,
                     proof: Path | str | None = None) -> dict[str, Any]:
    binding_path, value = _json(path, "CURRENT binding sidecar")
    if value.get("schema") != SCHEMA or value.get("sha256") != canonical_sha(value):
        raise CurrentBindingError("CURRENT binding sidecar schema/SHA differs")
    if value.get("status") != "PASS_FROZEN_V15_CURRENT_JOIN_RESULT_BINDING_STALE":
        raise CurrentBindingError("CURRENT binding sidecar status is not conservative")
    current = value.get("current_catalog", {})
    frozen = value.get("frozen_v15_request", {})
    historical = value.get("historical_v10_proof", {})
    if current.get("sha256") != ACTUAL_CURRENT_SHA256:
        raise CurrentBindingError("sidecar does not bind the exact CURRENT336 SHA")
    if frozen.get("current_binding", {}).get("sha256") != ACTUAL_CURRENT_SHA256:
        raise CurrentBindingError("sidecar V15 binding is not exact CURRENT336")
    if historical.get("declared_current_catalog_sha256") != HISTORICAL_RESULT_CURRENT_SHA256:
        raise CurrentBindingError("sidecar historical result binding differs")
    if value.get("case_join", {}).get("status") != "EXACT_CASE_INDEX_PHYSICAL_AND_RUNTIME_ALIAS_JOIN":
        raise CurrentBindingError("sidecar case join is not exact")
    if current_catalog is not None:
        actual_path = _file(current_catalog, "CURRENT336 validation input")
        if sha256_file(actual_path) != ACTUAL_CURRENT_SHA256:
            raise CurrentBindingError("validation CURRENT336 input SHA differs")
    if frozen_request is not None:
        frozen_path = _file(frozen_request, "V15 validation input")
        if sha256_file(frozen_path) != frozen.get("sha256"):
            raise CurrentBindingError("validation V15 request SHA differs")
    if proof is not None:
        proof_path = _file(proof, "proof validation input")
        if sha256_file(proof_path) != historical.get("sha256"):
            raise CurrentBindingError("validation proof SHA differs")
    return {"path": str(binding_path), "sha256": value["sha256"],
            "status": value["status"], "current_catalog_sha256": current["sha256"],
            "historical_result_current_catalog_sha256": historical["declared_current_catalog_sha256"],
            "case_join": value["case_join"], "source_file_join": value["source_file_join"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--current-catalog", type=Path, required=True)
    build.add_argument("--frozen-request", type=Path, required=True)
    build.add_argument("--proof", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--binding", type=Path, required=True)
    validate.add_argument("--current-catalog", type=Path)
    validate.add_argument("--frozen-request", type=Path)
    validate.add_argument("--proof", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            value = build_binding(current_catalog=args.current_catalog,
                                  frozen_request=args.frozen_request,
                                  proof=args.proof, output=args.output)
        else:
            value = validate_binding(args.binding, current_catalog=args.current_catalog,
                                     frozen_request=args.frozen_request, proof=args.proof)
    except (CurrentBindingError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"CURRENT catalog binding: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
