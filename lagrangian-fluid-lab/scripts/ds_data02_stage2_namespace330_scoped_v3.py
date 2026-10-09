#!/usr/bin/env python3
"""Schema-aware, case-scoped namespace330 proof consumer (v3).

This forward consumer keeps the v2 producer immutable and fixes two schema
boundaries found in the small ROOT proof reports.  Native verification rows
are represented by the structured ``native_cause_categories``,
``target_fluid_identity_count``, ``saved_frame_matches`` and
``exact_join_rows`` fields.  Typed mass rows keep selected sum/count/status
separate from an expected mass; an expected value is never promoted to an
observed value.  Scope ids and source paths are provenance and do not make
otherwise identical observations conflict.

Only bounded JSON metadata is read.  This module does not open H5, BI4,
trajectory or raw scientific arrays and it never grants qualification credit.
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
_SPEC = importlib.util.spec_from_file_location(
    "namespace330_scoped_v2_for_v3",
    SCRIPT_DIR / "ds_data02_stage2_namespace330_scoped_v2.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace330 v2 source is unavailable")
_V2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V2)
_V1 = _V2._V1


CATALOG_SCHEMA = "ds02.stage2.namespace330.scoped-proof-catalog.v3"
CARD_SCHEMA = "ds02.stage2.namespace330.scoped-family-card.v3"
REQUEST_SCHEMA = "ds02.stage2.namespace330.scoped-source-request.v3"
UNKNOWN_QUALIFICATION = dict(_V2.UNKNOWN_QUALIFICATION)
FAMILIES = tuple(_V2.FAMILIES)
CASE_COUNT = _V2.CASE_COUNT
CASES_PER_FAMILY = _V2.CASES_PER_FAMILY
MAX_METADATA_BYTES = _V2.MAX_METADATA_BYTES


class Namespace330ScopedV3Error(ValueError):
    """Malformed or semantically ambiguous v3 proof metadata."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in value.items()
                                     if k not in {"sha256", "request_sha256"}}).encode()).hexdigest()


def _read_json(path: Path | str, role: str) -> dict[str, Any]:
    try:
        return _V2._read_json(path, role)
    except Exception as error:
        raise Namespace330ScopedV3Error(str(error)) from error


def _sha_file(path: Path | str) -> str:
    try:
        return _V2.sha256_file(path)
    except Exception as error:
        raise Namespace330ScopedV3Error(str(error)) from error


def _write_new(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    if path.exists() or path.is_symlink():
        raise Namespace330ScopedV3Error(f"refusing to overwrite scoped artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                               allow_nan=False) + "\n", encoding="utf-8")
    return canonical_sha(value), _sha_file(path)


def _finite(value: Any) -> float | None:
    return _V2._finite_or_none(value)


def _first(value: Mapping[str, Any], keys: Sequence[str]) -> Any:
    return _V2._first(value, keys)


def _scope_semantic(value: Mapping[str, Any]) -> str:
    """Canonical semantic value used for cross-scope agreement.

    Scope ids, source file identities and paths are deliberately excluded:
    they identify provenance, not the observation itself.
    """
    excluded = {"scope_id", "source_file_sha256", "path", "file_sha256",
                "source_path", "proof_id", "verification_scope_id"}
    return _canonical({k: v for k, v in value.items() if k not in excluded})


def _native_row(proof: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    status = _V2._row_status(row, proof)
    categories = row.get("native_cause_categories")
    if categories is None:
        categories_value: list[str] | None = None
    elif isinstance(categories, list) and all(isinstance(item, str) and item for item in categories):
        categories_value = sorted(set(categories))
    else:
        categories_value = None

    observed_mass = _finite(_first(row, (
        "observed_initial_mass_kg", "actual_initial_mass_kg",
        "fluid_initial_mass_kg", "selected_initial_mass_kg",
    )))
    if status != "COMPLETED":
        observed_mass = None
    cause = row.get("native_exit_cause")
    if not isinstance(cause, str) or not cause:
        # A list of categories is not silently coerced into the old scalar
        # native_exit_cause field.
        cause = "UNKNOWN"
    exact_counts: dict[str, Any] = {}
    for key in (
        "target_fluid_identity_count", "saved_frame_matches", "exact_join_rows",
        "frames", "fluid_cumulative_unique_missing", "fluid_missing_final_count",
        "field_failure_count",
    ):
        if key in row:
            exact_counts[key] = row[key]
    return {
        "status": status,
        "scope_id": proof["scope_id"],
        "source_file_sha256": proof["file_sha256"],
        "initial_mass_kg": observed_mass,
        "native_exit_cause": cause,
        "native_cause_categories": categories_value,
        "target_fluid_identity_count": row.get("target_fluid_identity_count"),
        "saved_frame_matches": row.get("saved_frame_matches"),
        "exact_join_rows": row.get("exact_join_rows"),
        "exact_counts": exact_counts,
        "field_failures": list(row["field_failures"])
        if isinstance(row.get("field_failures"), list) else None,
    }


def _selected_mass(row: Mapping[str, Any]) -> tuple[float | None, int | None, str | None, float | None]:
    """Read the explicit selected typed-mass tuple.

    The producer has used both flat fields and a nested selected object.  The
    tuple remains absent when the producer only supplied an expected mass.
    """
    selected = row.get("selected_typed_initial_mass")
    if not isinstance(selected, Mapping):
        selected = row.get("selected_initial_mass")
    selected = selected if isinstance(selected, Mapping) else {}
    total = _finite(_first(selected, ("sum_kg", "sum", "mass_sum_kg", "selected_sum_kg",
                                      "initial_mass_sum_kg", "total_kg", "mass_kg")))
    if total is None:
        total = _finite(_first(row, (
            "selected_initial_mass_sum_kg", "selected_typed_initial_mass_sum_kg",
            "selected_initial_mass_sum", "selected_typed_initial_mass_sum",
            "selected_initial_mass_kg",
        )))
    count_value = _first(selected, ("count", "selected_count", "particle_count"))
    if count_value is None:
        count_value = _first(row, ("selected_initial_mass_count",
                                   "selected_typed_initial_mass_count"))
    count: int | None = None
    if isinstance(count_value, int) and not isinstance(count_value, bool) and count_value >= 0:
        count = count_value
    status = _first(selected, ("status", "selection_status", "verification_status"))
    if status is None:
        status = _first(row, ("selected_initial_mass_status",
                              "selected_typed_initial_mass_status"))
    if isinstance(status, str):
        upper = status.upper()
        if any(token in upper for token in ("PASS", "COMPLETE", "VERIFIED", "MATCH")):
            status = "COMPLETED"
        elif any(token in upper for token in ("FAIL", "ERROR", "UNKNOWN", "MISMATCH")):
            status = "FAILED_OR_UNKNOWN"
        else:
            status = status
    else:
        status = None
    exclusion = _finite(_first(selected, ("excluded_mass_kg", "exclusion_mass_kg",
                                          "selected_exclusion_mass_kg", "excluded_mass",
                                          "exclusion_mass")))
    if exclusion is None:
        exclusion = _finite(_first(row, ("selected_exclusion_mass_kg",
                                         "excluded_initial_mass_kg",
                                         "selected_excluded_mass_kg",
                                         "selected_exclusion_mass")))
    return total, count, status, exclusion


def _mass_row(proof: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    status = _V2._row_status(row, proof)
    selected_sum, selected_count, selected_status, selected_exclusion = _selected_mass(row)
    expected = _finite(_first(row, ("expected_initial_mass_kg", "declared_initial_mass_kg",
                                    "expected_mass_kg")))
    case_total = _finite(_first(row, ("case_total_initial_mass_kg",
                                      "observed_case_initial_mass_kg",
                                      "total_initial_mass_kg", "case_initial_mass_kg")))
    observed = _finite(_first(row, ("observed_initial_mass_kg", "actual_initial_mass_kg",
                                    "fluid_initial_mass_kg")))
    mass_match = _first(row, ("mass_match", "initial_mass_match", "exact_mass_match"))
    if not isinstance(mass_match, bool) and selected_sum is not None and expected is not None:
        mass_match = abs(selected_sum - expected) <= 1e-12 * max(1.0, abs(expected))
    if not isinstance(mass_match, bool):
        mass_match = None
    # The selected tuple is the only source that can become an exact observed
    # case mass.  In particular, expected_initial_mass_kg alone stays NULL.
    exact_mass = selected_sum if status == "COMPLETED" and selected_status == "COMPLETED" else None
    if status != "COMPLETED":
        observed = None
        exact_mass = None
    return {
        "status": status,
        "scope_id": proof["scope_id"],
        "source_file_sha256": proof["file_sha256"],
        "initial_mass_kg": exact_mass,
        "selected_initial_mass_sum_kg": selected_sum,
        "selected_initial_mass_count": selected_count,
        "selected_initial_mass_status": selected_status,
        "selected_exclusion_mass_kg": selected_exclusion,
        "case_total_initial_mass_kg": case_total,
        "expected_initial_mass_kg": expected,
        "observed_initial_mass_kg": observed,
        "mass_match": mass_match,
        "failure_reason": _first(row, ("failure_reason", "error", "reason")),
    }


def _combine(entries: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
             case_id: str, *, kind: str) -> dict[str, Any]:
    if not entries:
        if kind == "native":
            return {"status": "UNKNOWN_NO_EXACT_CASE_ROW", "case_id": case_id,
                    "scope_ids": [], "source_file_sha256s": [], "initial_mass_kg": None,
                    "native_exit_cause": "UNKNOWN", "native_cause_categories": None,
                    "target_fluid_identity_count": None, "saved_frame_matches": None,
                    "exact_join_rows": None, "exact_counts": {}, "field_failures": None,
                    "matching_case_row_count": 0}
        return {"status": "UNKNOWN_NO_EXACT_CASE_ROW", "case_id": case_id,
                "scope_ids": [], "source_file_sha256s": [], "initial_mass_kg": None,
                "selected_initial_mass_sum_kg": None, "selected_initial_mass_count": None,
                "selected_initial_mass_status": None, "selected_exclusion_mass_kg": None,
                "case_total_initial_mass_kg": None,
                "expected_initial_mass_kg": None, "observed_initial_mass_kg": None,
                "mass_match": None, "matching_case_row_count": 0}
    normalized = [_native_row(proof, row) if kind == "native" else _mass_row(proof, row)
                  for proof, row in entries]
    semantic = {_scope_semantic(item) for item in normalized}
    conflict = len(semantic) > 1
    first = normalized[0]
    result = copy.deepcopy(first)
    result.update({
        "case_id": case_id,
        "scope_ids": [item["scope_id"] for item in normalized],
        "source_file_sha256s": [item["source_file_sha256"] for item in normalized],
        "matching_case_row_count": len(normalized),
        "status": "AMBIGUOUS_CONFLICT" if conflict else first["status"],
        "conflict_reason": "semantic proof rows disagree" if conflict else None,
    })
    if conflict:
        for key in list(result):
            if key not in {"case_id", "scope_ids", "source_file_sha256s",
                           "matching_case_row_count", "status", "conflict_reason"}:
                if key in {"field_failures"}:
                    result[key] = None
                elif key in {"native_exit_cause"}:
                    result[key] = "UNKNOWN"
                elif key in {"exact_counts"}:
                    result[key] = {}
                else:
                    result[key] = None
    return result


def _collect(paths: Sequence[Path | str], kind: str,
             canonical_ids: set[str]) -> tuple[list[dict[str, Any]],
                                                dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]],
                                                dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    by_case: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
    summary = {"proof_count": 0, "proofs_with_case_rows": 0,
               "matching_case_rows": 0, "unmatched_case_rows": 0,
               "unscoped_top_level_proofs": 0, "unmatched_ids": []}
    for index, path in enumerate(paths):
        value = _read_json(path, f"{kind}_proof_{index}")
        ref = _V2._V1._source_ref(path, f"{kind}_proof_{index}",
                                  content_policy="SMALL_PROOF_METADATA_ONLY")
        proof, rows = _V2._proof_scope(value, ref, kind=kind)
        refs.append(proof)
        summary["proof_count"] += 1
        summary["proofs_with_case_rows"] += bool(rows)
        summary["unscoped_top_level_proofs"] += not bool(rows)
        for row in rows:
            row_id = _V2._case_id(row)
            if row_id not in canonical_ids:
                summary["unmatched_case_rows"] += 1
                if isinstance(row_id, str):
                    summary["unmatched_ids"].append(row_id)
                continue
            summary["matching_case_rows"] += 1
            by_case.setdefault(row_id, []).append((proof, row))
    summary["unmatched_ids"] = sorted(set(summary["unmatched_ids"]))
    return refs, by_case, summary


def build_namespace330_scoped_v3(*, current_path: Path | str, audit_path: Path | str,
                                 lifecycle_path: Path | str, v26_path: Path | str,
                                 output_dir: Path | str, registry_path: Path | str | None = None,
                                 source_access_path: Path | str | None = None,
                                 native_proof_paths: Sequence[Path | str] = (),
                                 mass_proof_paths: Sequence[Path | str] = (),
                                 request_id: str = "namespace330-scoped-v3-001") -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise Namespace330ScopedV3Error(f"scoped namespace output must be fresh: {output}")
    current, current_ref = _V1._load_input(current_path, "CURRENT336")
    audit, audit_ref = _V1._load_input(audit_path, "scientific_audit_v23")
    lifecycle, lifecycle_ref = _V1._load_input(lifecycle_path, "typed_lifecycle_registry")
    v26, v26_ref = _V1._load_input(v26_path, "effective_condition_v26")
    registry = registry_ref = source_access = source_access_ref = None
    if registry_path is not None:
        registry, registry_ref = _V1._load_input(registry_path, "lifecycle_evidence_registry")
    if source_access_path is not None:
        source_access, source_access_ref = _V1._load_input(source_access_path, "family_source_access_index")
    current_rows = _V1._validate_current(current)
    canonical_ids = {str(row["physical_case_id"]) for row in current_rows}
    audit_rows = _V1._map_unique(audit.get("verified_cases", []), "physical_case_id", "audit")
    lifecycle_rows = _V1._map_unique(lifecycle.get("case_records", []), "physical_case_id", "lifecycle")
    v26_rows = _V1._validate_v26(v26)
    native_refs, native_by_case, native_summary = _collect(native_proof_paths, "native", canonical_ids)
    mass_refs, mass_by_case, mass_summary = _collect(mass_proof_paths, "mass", canonical_ids)
    records: list[dict[str, Any]] = []
    for index, row in enumerate(current_rows):
        base_row = dict(row)
        base_row.setdefault("current_index", index)
        case_id = str(base_row["physical_case_id"])
        base = _V1._case_record(base_row, audit_rows.get(case_id), lifecycle_rows.get(case_id),
                                v26_rows.get(case_id), (), ())
        native = _combine(native_by_case.get(case_id, ()), case_id, kind="native")
        mass = _combine(mass_by_case.get(case_id, ()), case_id, kind="mass")
        record = copy.deepcopy(base)
        record["native_proof_observation"] = native
        record["mass_proof_observation"] = mass
        record["source_access"]["native_proof_scopes"] = [
            {"scope_id": ref["scope_id"], "path": ref["path"],
             "file_sha256": ref["file_sha256"], "kind": ref["kind"]}
            for ref, _ in native_by_case.get(case_id, ())
        ]
        record["source_access"]["mass_proof_scopes"] = [
            {"scope_id": ref["scope_id"], "path": ref["path"],
             "file_sha256": ref["file_sha256"], "kind": ref["kind"]}
            for ref, _ in mass_by_case.get(case_id, ())
        ]
        record["physical"]["native_exit_cause"] = native.get("native_exit_cause", "UNKNOWN")
        record["physical"]["native_cause_categories"] = native.get("native_cause_categories")
        record["quality"]["impact"]["native_initial_mass_kg"] = native.get("initial_mass_kg")
        record["quality"]["impact"]["mass_match"] = mass.get("mass_match")
        record["quality"]["impact"]["selected_initial_mass_sum_kg"] = mass.get("selected_initial_mass_sum_kg")
        record["quality"]["impact"]["selected_exclusion_mass_kg"] = mass.get("selected_exclusion_mass_kg")
        record["quality"]["impact"]["case_total_initial_mass_kg"] = mass.get("case_total_initial_mass_kg")
        record["status"] = "DEVELOPMENT_SCOPED_METADATA_ONLY"
        records.append(record)
    if len(records) != CASE_COUNT:
        raise Namespace330ScopedV3Error("scoped catalog did not produce 336 records")
    family_records = {family: [row for row in records if row["family_id"] == family]
                      for family in FAMILIES}
    if any(len(rows) != CASES_PER_FAMILY for rows in family_records.values()):
        raise Namespace330ScopedV3Error("scoped family counts must be exactly 48")
    source_inputs = [current_ref, audit_ref, lifecycle_ref, v26_ref]
    for ref in (registry_ref, source_access_ref):
        if ref is not None:
            source_inputs.append(ref)
    source_inputs.extend({"path": ref["path"], "file_sha256": ref["file_sha256"],
                          "role": ref["kind"] + "_proof", "bytes": ref.get("bytes"),
                          "content_policy": ref["content_policy"]}
                         for ref in native_refs + mass_refs)
    scope_policy = {
        "match_key": "physical_case_id exact canonical CURRENT identity",
        "family_or_top_level_aggregate_fallback": False,
        "owner_sha256_is_identity": False,
        "scope_id_is_provenance_only": True,
        "native_schema": "native_cause_categories + target_fluid_identity_count + saved_frame_matches + exact_join_rows",
        "mass_schema": "selected typed initial-mass sum/count/status; expected mass remains separate",
        "failed_or_missing_fields": "NULL_OR_UNKNOWN",
        "qualification_credit": "NONE",
    }
    catalog: dict[str, Any] = {
        "schema": CATALOG_SCHEMA, "namespace": "namespace330-v3",
        "status": "DEVELOPMENT_SCOPED_METADATA_ONLY", "development_material": True,
        "hidden_test": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN_QUALIFICATION), "case_count": CASE_COUNT,
        "family_counts": {family: len(rows) for family, rows in family_records.items()},
        "proof_scope_policy": scope_policy,
        "input_summary": {"audit_rows": len(audit_rows), "lifecycle_rows": len(lifecycle_rows),
                           "v26_rows": len(v26_rows), "native": native_summary, "mass": mass_summary},
        "source_inputs": source_inputs,
        "current_binding": {"path": str(Path(current_path).expanduser()),
                             "file_sha256": current_ref["file_sha256"],
                             "canonical_case_identity": "physical_case_id_exact"},
        "cases": records,
    }
    catalog["sha256"] = canonical_sha(catalog)
    output.mkdir(parents=True, exist_ok=True)
    catalog_path = output / "namespace330-scoped-v3-catalog.json"
    catalog_canonical, catalog_file = _write_new(catalog_path, catalog)
    cards_dir = output / "family-cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    card_paths: list[dict[str, Any]] = []
    for family in FAMILIES:
        rows = family_records[family]
        card = {
            "schema": CARD_SCHEMA, "namespace": "namespace330-v3", "family_id": family,
            "status": "DEVELOPMENT_SCOPED_METADATA_ONLY", "development_material": True,
            "hidden_test": False, "qualification": dict(UNKNOWN_QUALIFICATION),
            "case_count": len(rows), "canonical_case_ids": [r["canonical_case_id"] for r in rows],
            "case_refs": [{
                "canonical_case_id": row["canonical_case_id"],
                "native_proof_status": row["native_proof_observation"]["status"],
                "native_cause_categories": row["native_proof_observation"].get("native_cause_categories"),
                "target_fluid_identity_count": row["native_proof_observation"].get("target_fluid_identity_count"),
                "saved_frame_matches": row["native_proof_observation"].get("saved_frame_matches"),
                "exact_join_rows": row["native_proof_observation"].get("exact_join_rows"),
                "mass_proof_status": row["mass_proof_observation"]["status"],
                "selected_initial_mass_sum_kg": row["mass_proof_observation"].get("selected_initial_mass_sum_kg"),
                "selected_initial_mass_count": row["mass_proof_observation"].get("selected_initial_mass_count"),
                "selected_initial_mass_status": row["mass_proof_observation"].get("selected_initial_mass_status"),
                "selected_exclusion_mass_kg": row["mass_proof_observation"].get("selected_exclusion_mass_kg"),
                "case_total_initial_mass_kg": row["mass_proof_observation"].get("case_total_initial_mass_kg"),
                "mass_initial_mass_kg": row["mass_proof_observation"].get("initial_mass_kg"),
                "expected_initial_mass_kg": row["mass_proof_observation"].get("expected_initial_mass_kg"),
                "mass_match": row["mass_proof_observation"].get("mass_match"),
                "qualification": dict(UNKNOWN_QUALIFICATION),
            } for row in rows],
            "scope_policy": scope_policy,
        }
        card["sha256"] = canonical_sha(card)
        card_path = cards_dir / f"{family}-namespace330-scoped-family-card-v3.json"
        card_canonical, card_file = _write_new(card_path, card)
        card_paths.append({"family_id": family, "path": str(card_path),
                           "canonical_sha256": card_canonical, "file_sha256": card_file})
    request = {
        "schema": REQUEST_SCHEMA, "namespace": "namespace330-v3", "request_id": request_id,
        "status": "READY_FOR_ROOT_SOURCE_METADATA_GUARD", "development_material": True,
        "hidden_test": False, "qualification": dict(UNKNOWN_QUALIFICATION), "model_invoked": False,
        "builder": {"script": "ds_data02_stage2_namespace330_scoped_v3.py",
                     "proof_join": "exact physical_case_id; scope ids are provenance only",
                     "native_fields": ["native_cause_categories", "target_fluid_identity_count",
                                        "saved_frame_matches", "exact_join_rows"],
                     "mass_fields": ["selected_initial_mass_sum_kg", "selected_initial_mass_count",
                                     "selected_initial_mass_status", "selected_exclusion_mass_kg"],
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
    request_path = output / "namespace330-scoped-v3-source-request.json"
    request_canonical, request_file = _write_new(request_path, request)
    return {"schema": CATALOG_SCHEMA, "catalog_path": str(catalog_path),
            "catalog_sha256": catalog_canonical, "catalog_file_sha256": catalog_file,
            "request_path": str(request_path), "request_sha256": request_canonical,
            "request_file_sha256": request_file, "case_count": CASE_COUNT,
            "family_counts": {family: len(rows) for family, rows in family_records.items()},
            "native_summary": native_summary, "mass_summary": mass_summary}


def load_namespace330_scoped_v3(output_dir: Path | str) -> dict[str, Any]:
    output = Path(output_dir).expanduser()
    catalog_path = output / "namespace330-scoped-v3-catalog.json"
    request_path = output / "namespace330-scoped-v3-source-request.json"
    catalog = _read_json(catalog_path, "scoped v3 catalog")
    request = _read_json(request_path, "scoped v3 request")
    if catalog.get("schema") != CATALOG_SCHEMA or catalog.get("sha256") != canonical_sha(catalog):
        raise Namespace330ScopedV3Error("scoped v3 catalog schema/SHA mismatch")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise Namespace330ScopedV3Error("scoped v3 request schema/SHA mismatch")
    rows = catalog.get("cases")
    if catalog.get("case_count") != CASE_COUNT or not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise Namespace330ScopedV3Error("scoped v3 catalog must contain 336 cases")
    ids: set[str] = set()
    for row in rows:
        case_id = row.get("canonical_case_id") if isinstance(row, Mapping) else None
        if not isinstance(case_id, str) or case_id in ids:
            raise Namespace330ScopedV3Error("scoped v3 canonical identity is missing/duplicated")
        ids.add(case_id)
        if row.get("qualification") != UNKNOWN_QUALIFICATION:
            raise Namespace330ScopedV3Error(f"qualification was promoted: {case_id}")
        for field in ("native_proof_observation", "mass_proof_observation"):
            if not isinstance(row.get(field), Mapping):
                raise Namespace330ScopedV3Error(f"{case_id} lacks {field}")
    artifacts = request.get("artifacts")
    if not isinstance(artifacts, Mapping) or not isinstance(artifacts.get("catalog"), Mapping):
        raise Namespace330ScopedV3Error("request lacks catalog artifact")
    if artifacts["catalog"].get("canonical_sha256") != catalog["sha256"]:
        raise Namespace330ScopedV3Error("request/catalog canonical SHA mismatch")
    if artifacts["catalog"].get("file_sha256") != _sha_file(catalog_path):
        raise Namespace330ScopedV3Error("request/catalog file SHA mismatch")
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
    build.add_argument("--request-id", default="namespace330-scoped-v3-001")
    validate = sub.add_parser("validate")
    validate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build_namespace330_scoped_v3(
                current_path=args.current, audit_path=args.audit, lifecycle_path=args.lifecycle,
                v26_path=args.v26, registry_path=args.registry, source_access_path=args.source_access,
                native_proof_paths=args.native_proof, mass_proof_paths=args.mass_proof,
                output_dir=args.output, request_id=args.request_id)
        else:
            result = load_namespace330_scoped_v3(args.output)
    except (OSError, json.JSONDecodeError, Namespace330ScopedV3Error) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
