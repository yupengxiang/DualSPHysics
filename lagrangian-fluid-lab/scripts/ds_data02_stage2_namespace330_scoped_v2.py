#!/usr/bin/env python3
"""Additive namespace330 scoped-proof catalog (v2).

The consumed namespace330 catalog intentionally kept native and mass proof
references global.  That is safe as a provenance list, but it is not a
case-level observation.  This forward builder joins only exact canonical
``physical_case_id`` rows from a proof's case-verification table.  A proof
with only family/top-level totals therefore contributes no per-case number.
Failed rows, absent fields, aliases, and conflicting proof rows remain
explicitly NULL/UNKNOWN.  No qualification is promoted and no payload
(H5/BI4/raw/trajectory) is opened.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_V1_SPEC = importlib.util.spec_from_file_location(
    "namespace330_v1_for_scoped_v2", SCRIPT_DIR / "ds_data02_stage2_namespace330_qualification.py")
if _V1_SPEC is None or _V1_SPEC.loader is None:  # pragma: no cover - import-time contract
    raise ImportError("namespace330 v1 source is unavailable")
_V1 = importlib.util.module_from_spec(_V1_SPEC)
_V1_SPEC.loader.exec_module(_V1)


CATALOG_SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v2"
CARD_SCHEMA = "ds02.stage2.namespace330.scoped-family-card.v2"
REQUEST_SCHEMA = "ds02.stage2.namespace330.scoped-source-request.v2"
UNKNOWN_QUALIFICATION = dict(_V1.UNKNOWN_QUALIFICATION)
FAMILIES = tuple(_V1.FAMILIES)
CASE_COUNT = _V1.CASE_COUNT
CASES_PER_FAMILY = _V1.CASES_PER_FAMILY
MAX_METADATA_BYTES = _V1.MAX_METADATA_BYTES


class Namespace330ScopedError(ValueError):
    """A malformed proof scope or stale scoped catalog."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key not in {"sha256", "request_sha256"}}
    return hashlib.sha256(_canonical(body).encode()).hexdigest()


def sha256_file(path: Path | str, *, maximum: int = MAX_METADATA_BYTES) -> str:
    try:
        return _V1.sha256_file(path, maximum=maximum)
    except Exception as error:
        raise Namespace330ScopedError(str(error)) from error


def _read_json(path: Path | str, role: str) -> dict[str, Any]:
    try:
        value = _V1._read_json(path, role, maximum=MAX_METADATA_BYTES)
    except Exception as error:
        raise Namespace330ScopedError(str(error)) from error
    return value


def _source_ref(path: Path | str, role: str) -> dict[str, Any]:
    try:
        value = _V1._source_ref(path, role, content_policy="SMALL_METADATA_JSON_ONLY")
    except Exception as error:
        raise Namespace330ScopedError(str(error)) from error
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    if path.exists() or path.is_symlink():
        raise Namespace330ScopedError(f"refusing to overwrite scoped artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                               allow_nan=False) + "\n", encoding="utf-8")
    return canonical_sha(value), sha256_file(path)


def _finite_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _first(value: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _case_id(row: Mapping[str, Any]) -> str | None:
    for key in ("physical_case_id", "canonical_case_id", "case_id", "case_identity"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, Mapping):
            for nested in ("physical_case_id", "canonical_case_id", "case_id"):
                candidate = value.get(nested)
                if isinstance(candidate, str) and candidate:
                    return candidate
    return None


def _case_rows(value: Any, *, depth: int = 0) -> list[Mapping[str, Any]]:
    """Find bounded case rows without treating family/top-level totals as rows."""
    if depth > 4:
        return []
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if _case_id(value) is not None:
            found.append(value)
        for key, child in value.items():
            if key in {"case_verifications", "verified_cases", "case_results", "cases",
                       "rows", "results", "observations", "verification_rows", "case_records"}:
                if isinstance(child, list):
                    for item in child:
                        if isinstance(item, Mapping) and _case_id(item) is not None:
                            found.append(item)
                elif isinstance(child, Mapping):
                    found.extend(_case_rows(child, depth=depth + 1))
            elif isinstance(child, Mapping) and depth < 3 and key in {"verification", "details", "evidence"}:
                found.extend(_case_rows(child, depth=depth + 1))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping) and _case_id(item) is not None:
                found.append(item)
    # Preserve source order while de-duplicating object identities encountered
    # through a named list and its enclosing mapping.
    unique: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for row in found:
        if id(row) not in seen:
            seen.add(id(row))
            unique.append(row)
    return unique


def _proof_scope(value: Mapping[str, Any], ref: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    rows = _case_rows(value)
    scope_id = _first(value, ("scope_id", "verification_scope_id", "proof_id", "scope"))
    if not isinstance(scope_id, str) or not scope_id:
        scope_id = f"{kind}:{ref['file_sha256'][:16]}"
    return {
        "kind": kind,
        "path": ref["path"],
        "file_sha256": ref["file_sha256"],
        "schema": value.get("schema"),
        "scope_id": scope_id,
        "top_level_status": value.get("status", value.get("verification_status", "UNKNOWN")),
        "case_row_count": len(rows),
        "row_case_ids": [_case_id(row) for row in rows],
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "content_policy": "SMALL_PROOF_METADATA_ONLY",
    }, rows


def _row_status(row: Mapping[str, Any], proof: Mapping[str, Any]) -> str:
    value = _first(row, ("status", "verification_status", "result", "outcome", "scan_status"))
    if value is None:
        value = proof.get("top_level_status", "UNKNOWN")
    if not isinstance(value, str):
        return "UNKNOWN"
    upper = value.upper()
    if any(token in upper for token in ("FAIL", "ERROR", "MISMATCH", "UNKNOWN")):
        return "FAILED_OR_UNKNOWN"
    if any(token in upper for token in ("PASS", "COMPLETE", "SUCCESS", "VERIFIED")):
        return "COMPLETED"
    return value


def _native_observation(entries: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]], case_id: str) -> dict[str, Any]:
    if not entries:
        return {
            "status": "UNKNOWN_NO_EXACT_CASE_ROW", "case_id": case_id,
            "scope_ids": [], "initial_mass_kg": None, "native_exit_cause": "UNKNOWN",
            "exact_counts": {}, "field_failures": None,
            "matching_case_row_count": 0,
        }
    normalized: list[dict[str, Any]] = []
    for proof, row in entries:
        row_status = _row_status(row, proof)
        mass = _finite_or_none(_first(row, ("fluid_initial_mass_kg", "initial_mass_kg",
                                             "selected_initial_mass_kg", "mass_kg")))
        # A failed/unknown verification is not an exact initial-mass
        # observation.  Keep the row and its status, but expose NULL for the
        # per-case numeric value.
        if row_status != "COMPLETED":
            mass = None
        cause = _first(row, ("native_exit_cause", "exit_cause", "terminal_cause", "cause"))
        normalized.append({
            "status": row_status,
            "scope_id": proof["scope_id"],
            "source_file_sha256": proof["file_sha256"],
            "initial_mass_kg": mass,
            "native_exit_cause": cause if isinstance(cause, str) and cause else "UNKNOWN",
            "exact_counts": {
                key: _first(row, (key,)) for key in
                ("frames", "fluid_cumulative_unique_missing", "fluid_missing_final_count",
                 "field_failure_count") if _first(row, (key,)) is not None
            },
            "field_failures": list(row["field_failures"])
            if isinstance(row.get("field_failures"), list) else None,
        })
    distinct = {json.dumps(item, sort_keys=True, default=str) for item in normalized}
    conflict = len(distinct) > 1
    first = normalized[0]
    return {
        "status": "AMBIGUOUS_CONFLICT" if conflict else first["status"],
        "case_id": case_id,
        "scope_ids": [item["scope_id"] for item in normalized],
        "source_file_sha256s": [item["source_file_sha256"] for item in normalized],
        "initial_mass_kg": None if conflict else first["initial_mass_kg"],
        "native_exit_cause": "UNKNOWN" if conflict else first["native_exit_cause"],
        "exact_counts": {} if conflict else first["exact_counts"],
        "field_failures": None if conflict else first["field_failures"],
        "matching_case_row_count": len(normalized),
        "conflict_reason": "multiple exact proof rows disagree" if conflict else None,
    }


def _mass_observation(entries: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]], case_id: str) -> dict[str, Any]:
    if not entries:
        return {
            "status": "UNKNOWN_NO_EXACT_CASE_ROW", "case_id": case_id,
            "scope_ids": [], "initial_mass_kg": None, "expected_initial_mass_kg": None,
            "observed_initial_mass_kg": None, "mass_match": None,
            "matching_case_row_count": 0,
        }
    normalized: list[dict[str, Any]] = []
    for proof, row in entries:
        row_status = _row_status(row, proof)
        actual = _finite_or_none(_first(row, ("observed_initial_mass_kg", "actual_initial_mass_kg",
                                               "fluid_initial_mass_kg", "initial_mass_kg", "mass_kg")))
        expected = _finite_or_none(_first(row, ("expected_initial_mass_kg", "declared_initial_mass_kg",
                                                 "expected_mass_kg")))
        match = _first(row, ("mass_match", "initial_mass_match", "exact_mass_match"))
        match_bool = bool(match) if isinstance(match, bool) else (
            abs(actual - expected) <= 1e-12 * max(1.0, abs(expected))
            if actual is not None and expected is not None else None)
        normalized.append({"status": row_status, "scope_id": proof["scope_id"],
                           "source_file_sha256": proof["file_sha256"],
                           "initial_mass_kg": (actual if actual is not None else expected)
                           if row_status == "COMPLETED" else None,
                           "expected_initial_mass_kg": expected,
                           "observed_initial_mass_kg": actual,
                           "mass_match": match_bool,
                           "failure_reason": _first(row, ("failure_reason", "error", "reason"))})
    distinct = {json.dumps(item, sort_keys=True, default=str) for item in normalized}
    conflict = len(distinct) > 1
    first = normalized[0]
    return {
        "status": "AMBIGUOUS_CONFLICT" if conflict else first["status"],
        "case_id": case_id,
        "scope_ids": [item["scope_id"] for item in normalized],
        "source_file_sha256s": [item["source_file_sha256"] for item in normalized],
        "initial_mass_kg": None if conflict else first["initial_mass_kg"],
        "expected_initial_mass_kg": None if conflict else first["expected_initial_mass_kg"],
        "observed_initial_mass_kg": None if conflict else first["observed_initial_mass_kg"],
        "mass_match": None if conflict else first["mass_match"],
        "failure_reason": "multiple exact proof rows disagree" if conflict else first["failure_reason"],
        "matching_case_row_count": len(normalized),
    }


def _collect_scoped_proofs(paths: Sequence[Path | str], kind: str,
                           canonical_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]], dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    by_case: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    summary = {"proof_count": 0, "proofs_with_case_rows": 0, "matching_case_rows": 0,
               "unmatched_case_rows": 0, "unscoped_top_level_proofs": 0,
               "unmatched_ids": []}
    for index, path in enumerate(paths):
        value = _read_json(path, f"{kind}_proof_{index}")
        ref = _source_ref(path, f"{kind}_proof_{index}")
        proof, rows = _proof_scope(value, ref, kind=kind)
        refs.append(proof)
        summary["proof_count"] += 1
        if rows:
            summary["proofs_with_case_rows"] += 1
        else:
            summary["unscoped_top_level_proofs"] += 1
        for row in rows:
            row_case_id = _case_id(row)
            if row_case_id not in canonical_ids:
                summary["unmatched_case_rows"] += 1
                if isinstance(row_case_id, str):
                    summary["unmatched_ids"].append(row_case_id)
                continue
            summary["matching_case_rows"] += 1
            by_case.setdefault(row_case_id, []).append((proof, row))
    summary["unmatched_ids"] = sorted(set(summary["unmatched_ids"]))
    return refs, by_case, summary


def _case_record(base: Mapping[str, Any], native_entries: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
                 mass_entries: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, Any]:
    record = copy.deepcopy(dict(base))
    case_id = str(record["canonical_case_id"])
    native = _native_observation(native_entries, case_id)
    mass = _mass_observation(mass_entries, case_id)
    record["native_proof_observation"] = native
    record["mass_proof_observation"] = mass
    record["source_access"]["native_proof_scopes"] = [
        {"scope_id": value["scope_id"], "path": value["path"],
         "file_sha256": value["file_sha256"], "kind": value["kind"]}
        for value in native_entries[0:0]  # proof refs are copied below by caller
    ]
    record["source_access"]["mass_proof_scopes"] = []
    # No aggregate proof row can supply per-case physics.  Preserve the v1
    # audit summary, but replace the physical cause with the exact row result.
    record["physical"]["native_exit_cause"] = native["native_exit_cause"]
    record["quality"]["impact"]["native_initial_mass_kg"] = mass["initial_mass_kg"]
    record["quality"]["impact"]["mass_match"] = mass["mass_match"]
    record["status"] = "DEVELOPMENT_SCOPED_METADATA_ONLY"
    return record


def build_namespace330_scoped_v2(*, current_path: Path | str, audit_path: Path | str,
                                 lifecycle_path: Path | str, v26_path: Path | str,
                                 output_dir: Path | str, registry_path: Path | str | None = None,
                                 source_access_path: Path | str | None = None,
                                 native_proof_paths: Sequence[Path | str] = (),
                                 mass_proof_paths: Sequence[Path | str] = (),
                                 request_id: str = "namespace330-scoped-v2-001") -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise Namespace330ScopedError(f"scoped namespace output must be fresh: {output}")
    current, current_ref = _V1._load_input(current_path, "CURRENT336")
    audit, audit_ref = _V1._load_input(audit_path, "scientific_audit_v23")
    lifecycle, lifecycle_ref = _V1._load_input(lifecycle_path, "typed_lifecycle_registry")
    v26, v26_ref = _V1._load_input(v26_path, "effective_condition_v26")
    registry = registry_ref = None
    if registry_path is not None:
        registry, registry_ref = _V1._load_input(registry_path, "lifecycle_evidence_registry")
    source_access = source_access_ref = None
    if source_access_path is not None:
        source_access, source_access_ref = _V1._load_input(source_access_path, "family_source_access_index")
    current_rows = _V1._validate_current(current)
    canonical_ids = {str(row["physical_case_id"]) for row in current_rows}
    audit_rows = _V1._map_unique(audit.get("verified_cases", []), "physical_case_id", "audit")
    lifecycle_rows = _V1._map_unique(lifecycle.get("case_records", []), "physical_case_id", "lifecycle")
    v26_rows = _V1._validate_v26(v26)
    native_refs, native_by_case, native_summary = _collect_scoped_proofs(native_proof_paths, "native", canonical_ids)
    mass_refs, mass_by_case, mass_summary = _collect_scoped_proofs(mass_proof_paths, "mass", canonical_ids)
    records: list[dict[str, Any]] = []
    for current_index, row in enumerate(current_rows):
        row_with_index = dict(row)
        row_with_index.setdefault("current_index", current_index)
        case_id = str(row_with_index["physical_case_id"])
        base = _V1._case_record(row_with_index, audit_rows.get(case_id), lifecycle_rows.get(case_id),
                                v26_rows.get(case_id), (), ())
        record = _case_record(base, native_by_case.get(case_id, ()), mass_by_case.get(case_id, ()))
        record["source_access"]["native_proof_scopes"] = [
            {"scope_id": ref["scope_id"], "path": ref["path"],
             "file_sha256": ref["file_sha256"], "kind": ref["kind"]}
            for ref, _row in native_by_case.get(case_id, ())
        ]
        record["source_access"]["mass_proof_scopes"] = [
            {"scope_id": ref["scope_id"], "path": ref["path"],
             "file_sha256": ref["file_sha256"], "kind": ref["kind"]}
            for ref, _row in mass_by_case.get(case_id, ())
        ]
        records.append(record)
    if len(records) != CASE_COUNT:
        raise Namespace330ScopedError("scoped catalog did not produce 336 records")
    family_records = {family: [row for row in records if row["family_id"] == family]
                      for family in FAMILIES}
    if any(len(rows) != CASES_PER_FAMILY for rows in family_records.values()):
        raise Namespace330ScopedError("scoped family counts must be exactly 48")
    source_inputs = [current_ref, audit_ref, lifecycle_ref, v26_ref]
    for ref in (registry_ref, source_access_ref):
        if ref is not None:
            source_inputs.append(ref)
    source_inputs.extend({"path": ref["path"], "file_sha256": ref["file_sha256"],
                          "role": ref["kind"] + "_proof", "bytes": ref.get("bytes"),
                          "content_policy": ref["content_policy"]} for ref in native_refs + mass_refs)
    catalog: dict[str, Any] = {
        "schema": CATALOG_SCHEMA, "namespace": "namespace330-v2",
        "status": "DEVELOPMENT_SCOPED_METADATA_ONLY", "development_material": True,
        "hidden_test": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN_QUALIFICATION), "case_count": CASE_COUNT,
        "family_counts": {family: len(rows) for family, rows in family_records.items()},
        "proof_scope_policy": {
            "match_key": "physical_case_id exact canonical CURRENT identity",
            "family_or_top_level_aggregate_fallback": False,
            "owner_sha256_is_identity": False,
            "failed_or_missing_fields": "NULL_OR_UNKNOWN",
            "qualification_credit": "NONE",
        },
        "input_summary": {"audit_rows": len(audit_rows), "lifecycle_rows": len(lifecycle_rows),
                           "v26_rows": len(v26_rows), "native": native_summary,
                           "mass": mass_summary},
        "source_inputs": source_inputs,
        "current_binding": {"path": str(Path(current_path).expanduser()),
                             "file_sha256": current_ref["file_sha256"],
                             "canonical_case_identity": "physical_case_id_exact"},
        "cases": records,
    }
    catalog["sha256"] = canonical_sha(catalog)
    output.mkdir(parents=True, exist_ok=True)
    catalog_path = output / "namespace330-scoped-v2-catalog.json"
    catalog_canonical, catalog_file = _write_new(catalog_path, catalog)
    cards_dir = output / "family-cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    card_paths: list[dict[str, Any]] = []
    for family in FAMILIES:
        rows = family_records[family]
        card = {
            "schema": CARD_SCHEMA, "namespace": "namespace330-v2", "family_id": family,
            "status": "DEVELOPMENT_SCOPED_METADATA_ONLY", "development_material": True,
            "hidden_test": False, "qualification": dict(UNKNOWN_QUALIFICATION),
            "case_count": len(rows), "canonical_case_ids": [row["canonical_case_id"] for row in rows],
            "case_refs": [{"canonical_case_id": row["canonical_case_id"],
                           "native_proof_status": row["native_proof_observation"]["status"],
                           "native_exit_cause": row["native_proof_observation"]["native_exit_cause"],
                           "native_initial_mass_kg": row["native_proof_observation"]["initial_mass_kg"],
                           "mass_proof_status": row["mass_proof_observation"]["status"],
                           "mass_initial_mass_kg": row["mass_proof_observation"]["initial_mass_kg"],
                           "mass_match": row["mass_proof_observation"]["mass_match"],
                           "qualification": dict(UNKNOWN_QUALIFICATION)} for row in rows],
            "scope_policy": catalog["proof_scope_policy"],
        }
        card["sha256"] = canonical_sha(card)
        card_canonical, card_file = _write_new(cards_dir / f"{family}-namespace330-scoped-family-card.json", card)
        card_paths.append({"family_id": family, "path": str(cards_dir / f"{family}-namespace330-scoped-family-card.json"),
                           "canonical_sha256": card_canonical, "file_sha256": card_file})
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA, "namespace": "namespace330-v2", "request_id": request_id,
        "status": "READY_FOR_ROOT_SOURCE_METADATA_GUARD", "development_material": True,
        "hidden_test": False, "qualification": dict(UNKNOWN_QUALIFICATION), "model_invoked": False,
        "builder": {"script": "ds_data02_stage2_namespace330_scoped_v2.py",
                     "proof_join": "exact physical_case_id only; no family aggregate fallback",
                     "content_policy": "small JSON/stat only; H5/BI4/raw deferred"},
        "artifacts": {"catalog": {"path": str(catalog_path), "canonical_sha256": catalog_canonical,
                                    "file_sha256": catalog_file}, "family_cards": card_paths},
        "source_inputs": source_inputs, "input_summary": catalog["input_summary"],
        "qualification_boundary": dict(UNKNOWN_QUALIFICATION),
        "read_scope": {"small_json_and_stat_only": True, "h5_opened": False,
                        "bi4_opened": False, "raw_arrays_opened": False,
                        "large_scientific_json_opened": False,
                        "payload_hashes_deferred_to_parent_guard": True},
    }
    request["sha256"] = canonical_sha(request)
    request_path = output / "namespace330-scoped-v2-source-request.json"
    request_canonical, request_file = _write_new(request_path, request)
    return {"schema": CATALOG_SCHEMA, "catalog_path": str(catalog_path),
            "catalog_sha256": catalog_canonical, "catalog_file_sha256": catalog_file,
            "request_path": str(request_path), "request_sha256": request_canonical,
            "request_file_sha256": request_file, "case_count": CASE_COUNT,
            "family_counts": {family: len(rows) for family, rows in family_records.items()},
            "native_summary": native_summary, "mass_summary": mass_summary}


def load_namespace330_scoped_v2(output_dir: Path | str) -> dict[str, Any]:
    output = Path(output_dir).expanduser()
    catalog_path = output / "namespace330-scoped-v2-catalog.json"
    request_path = output / "namespace330-scoped-v2-source-request.json"
    catalog = _read_json(catalog_path, "scoped namespace catalog")
    request = _read_json(request_path, "scoped namespace request")
    if catalog.get("schema") != CATALOG_SCHEMA or catalog.get("sha256") != canonical_sha(catalog):
        raise Namespace330ScopedError("scoped catalog schema/SHA mismatch")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise Namespace330ScopedError("scoped request schema/SHA mismatch")
    if catalog.get("case_count") != CASE_COUNT or catalog.get("qualification") != UNKNOWN_QUALIFICATION:
        raise Namespace330ScopedError("scoped catalog count/qualification boundary mismatch")
    rows = catalog.get("cases")
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise Namespace330ScopedError("scoped catalog must contain 336 cases")
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise Namespace330ScopedError("scoped case is not an object")
        case_id = row.get("canonical_case_id")
        if not isinstance(case_id, str) or case_id in ids:
            raise Namespace330ScopedError("scoped canonical identity is missing/duplicated")
        ids.add(case_id)
        for field in ("native_proof_observation", "mass_proof_observation"):
            observation = row.get(field)
            if not isinstance(observation, Mapping):
                raise Namespace330ScopedError(f"{case_id} lacks {field}")
            if observation.get("status") == "MATCHED_EXACT_CASE" and observation.get("matching_case_row_count") != 1:
                raise Namespace330ScopedError(f"{case_id} has invalid exact row count")
        if row.get("qualification") != UNKNOWN_QUALIFICATION:
            raise Namespace330ScopedError(f"scoped case qualification was promoted: {case_id}")
    artifacts = request.get("artifacts")
    if not isinstance(artifacts, Mapping) or not isinstance(artifacts.get("catalog"), Mapping):
        raise Namespace330ScopedError("scoped request lacks catalog artifact")
    if artifacts["catalog"].get("canonical_sha256") != catalog["sha256"]:
        raise Namespace330ScopedError("scoped request/catalog canonical SHA mismatch")
    if artifacts["catalog"].get("file_sha256") != sha256_file(catalog_path):
        raise Namespace330ScopedError("scoped request/catalog file SHA mismatch")
    return {"schema": CATALOG_SCHEMA, "status": catalog.get("status"),
            "case_count": len(rows), "catalog_sha256": catalog["sha256"],
            "request_sha256": request["sha256"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("current", "audit", "lifecycle", "v26"):
        build.add_argument(f"--{name}", type=Path, required=True)
    build.add_argument("--registry", type=Path)
    build.add_argument("--source-access", type=Path)
    build.add_argument("--native-proof", type=Path, action="append", default=[])
    build.add_argument("--mass-proof", type=Path, action="append", default=[])
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--request-id", default="namespace330-scoped-v2-001")
    validate = sub.add_parser("validate")
    validate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build_namespace330_scoped_v2(
                current_path=args.current, audit_path=args.audit, lifecycle_path=args.lifecycle,
                v26_path=args.v26, registry_path=args.registry, source_access_path=args.source_access,
                native_proof_paths=args.native_proof, mass_proof_paths=args.mass_proof,
                output_dir=args.output, request_id=args.request_id)
        else:
            result = load_namespace330_scoped_v2(args.output)
    except (OSError, json.JSONDecodeError, Namespace330ScopedError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
