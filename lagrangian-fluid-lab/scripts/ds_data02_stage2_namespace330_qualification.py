#!/usr/bin/env python3
"""Build and load the additive namespace330 development catalog.

This module joins bounded metadata only.  It deliberately keeps the 336
canonical CURRENT rows separate from historical aliases, saved-mask lifecycle
observations, native accounting observations, and scientific qualification.
It never opens H5/BI4/raw arrays or solver output.  A generated catalog is a
development product: no row is a hidden test and no QI/QN/QE credit is
manufactured by this tool.

The builder accepts explicit paths because the lifecycle registry and actual
proofs live in the root-owned evidence tree.  A path is an input only when it
is supplied by the caller; there is no latest/glob/fallback lookup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CATALOG_SCHEMA = "ds02.stage2.namespace330.qualification-catalog.v1"
CARD_SCHEMA = "ds02.stage2.namespace330.family-card.v1"
REQUEST_SCHEMA = "ds02.stage2.namespace330.source-request.v1"
V26_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v26"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = tuple(f"F{i}" for i in range(1, 8))
CASE_COUNT = 336
CASES_PER_FAMILY = 48
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_CASE_BYTES = 512 * 1024
SPLIT_STATUSES = {"UNASSIGNED", "ASSIGNED"}
ASSIGNED_ROLES = {"development_train", "development_validation", "development_test"}


class Namespace330Error(ValueError):
    """A source binding, catalog row, or output namespace is unsafe."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    """Hash a JSON object without its self-referential top-level SHA."""
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str, *, maximum: int | None = None) -> str:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise Namespace330Error(f"expected regular non-symlink file: {target}")
    size = target.stat().st_size
    if maximum is not None and size > maximum:
        raise Namespace330Error(f"metadata size bound exceeded: {target} ({size})")
    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.exists():
        return {"exists": False}
    value = path.stat()
    return {
        "exists": True,
        "kind": "file" if path.is_file() else "directory",
        "bytes": int(value.st_size) if path.is_file() else None,
        "mode_bits": int(value.st_mode & 0o7777),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _read_json(path: Path | str, role: str, *, maximum: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise Namespace330Error(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > maximum:
        raise Namespace330Error(f"{role} exceeds metadata bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Namespace330Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Namespace330Error(f"{role} must be a JSON object")
    return value


def _source_ref(path: Path | str, role: str, *, value: Mapping[str, Any] | None = None,
                content_policy: str = "SMALL_METADATA_JSON_ONLY") -> dict[str, Any]:
    target = Path(path).expanduser()
    file_sha = sha256_file(target, maximum=MAX_METADATA_BYTES)
    stat = _stat(target)
    ref: dict[str, Any] = {
        "role": role,
        "path": str(target),
        "file_sha256": file_sha,
        "bytes": stat.get("bytes"),
        "mtime_ns": stat.get("mtime_ns"),
        "ctime_ns": stat.get("ctime_ns"),
        "st_dev": stat.get("st_dev"),
        "st_ino": stat.get("st_ino"),
        "content_policy": content_policy,
        "content_read_by_builder": value is not None,
    }
    if isinstance(value, Mapping):
        ref["schema"] = value.get("schema")
        embedded = value.get("sha256")
        if isinstance(embedded, str):
            ref["embedded_sha256"] = embedded
    return ref


def _read_source(path: Path | str, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    value = _read_json(path, role)
    return value, _source_ref(path, role, value=value)


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _unknown_quality(value: Any) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    upper = value.upper()
    if upper in {"UNKNOWN", "NOT_ASSESSED", "NOT_ASSESSED_UNKNOWN", "NONE", "NULL"}:
        return "UNKNOWN"
    return value


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _role_ref(record: Any, role: str, *, payload: bool = False) -> dict[str, Any]:
    """Carry a CURRENT-declared source without opening it.

    Trajectory/H5 and raw roots are deliberately provenance/stat-only.  The
    catalog records the declared identity and lets a later parent guard do
    content verification; it never follows these paths here.
    """
    if not isinstance(record, Mapping):
        return {"role": role, "status": "UNKNOWN", "content_read": False,
                "content_policy": "NO_DECLARATION"}
    path = record.get("path")
    result: dict[str, Any] = {
        "role": role,
        "status": "DECLARED" if isinstance(path, str) and path else "UNKNOWN",
        "path": path if isinstance(path, str) else None,
        "declared_sha256": (record.get("recomputed_sha256") or record.get("sha256")
                             or record.get("producer_declared_sha256")),
        "producer_declared_sha256": record.get("producer_declared_sha256"),
        "declared_bytes": record.get("bytes"),
        "declared_mtime_ns": record.get("mtime_ns"),
        "accessible_declared": record.get("accessible"),
        "content_read": False,
        "content_policy": "STAT_AND_DECLARED_SHA_ONLY_DEFERRED_PARENT_GUARD" if payload
                           else "DECLARED_PROVENANCE_NO_CONTENT_READ",
        "owner_sha_is_provenance_only": role == "owner_metadata",
    }
    return result


def _proof_ref(value: Mapping[str, Any], role: str) -> dict[str, Any]:
    """Select proof metadata, never proof payload."""
    path = value.get("path")
    result = {
        "role": role,
        "status": value.get("status", "UNKNOWN"),
        "scope": value.get("scope"),
        "path": path,
        "sha256": value.get("sha256"),
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "content_policy": "SMALL_PROOF_SCOPE_METADATA_ONLY",
        "content_read": False,
    }
    if isinstance(value.get("qualification"), Mapping):
        result["qualification_source_value"] = dict(value["qualification"])
    return result


def _map_unique(rows: Iterable[Mapping[str, Any]], key: str, role: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity:
            continue
        if identity in result:
            raise Namespace330Error(f"duplicate {role} identity: {identity}")
        result[identity] = row
    return result


def _validate_current(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if value.get("schema") != "ds02.stage2.current336.v1":
        raise Namespace330Error("CURRENT input schema is not ds02.stage2.current336.v1")
    rows = value.get("cases")
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise Namespace330Error("CURRENT must contain exactly 336 cases")
    ids: set[str] = set()
    families: dict[str, int] = {family: 0 for family in FAMILIES}
    for row in rows:
        if not isinstance(row, Mapping):
            raise Namespace330Error("CURRENT case is not an object")
        case_id = row.get("physical_case_id")
        family = row.get("family_id")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise Namespace330Error(f"CURRENT canonical identity is missing/duplicated: {case_id!r}")
        if family not in families:
            raise Namespace330Error(f"unexpected CURRENT family: {family!r}")
        ids.add(case_id)
        families[family] += 1
    if families != {family: CASES_PER_FAMILY for family in FAMILIES}:
        raise Namespace330Error(f"CURRENT family counts are not 48 each: {families}")
    return rows


def _validate_v26(value: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if value.get("schema") != V26_SCHEMA:
        raise Namespace330Error("V26 input schema mismatch")
    rows = value.get("cases")
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise Namespace330Error("V26 input must contain 336 compact cases")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("physical_case_id"), str):
            raise Namespace330Error("V26 compact case lacks canonical physical_case_id")
        case_id = str(row["physical_case_id"])
        if case_id in result:
            raise Namespace330Error(f"duplicate V26 physical_case_id: {case_id}")
        result[case_id] = row
    return result


def _native_summary(audit: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(audit, Mapping):
        return {"status": "UNKNOWN", "field_failures": None, "omitted_reason": "AUDIT_ROW_MISSING"}
    failures = audit.get("field_failures")
    if not isinstance(failures, list):
        failures = None
    missing = audit.get("fluid_cumulative_unique_missing")
    final_missing = audit.get("fluid_missing_final_count")
    if failures is None and missing is None and final_missing is None:
        return {"status": "UNKNOWN", "field_failures": None,
                "omitted_reason": "NATIVE_NUMERICAL_OMISSION_NOT_REPORTED"}
    return {
        "status": "OBSERVED_METADATA_ONLY",
        "scan_status": audit.get("scan_status"),
        "frames": audit.get("frames"),
        "field_failures": list(failures) if failures is not None else None,
        "field_failure_count": len(failures) if failures is not None else None,
        "fluid_cumulative_unique_missing": missing,
        "fluid_missing_final_count": final_missing,
        "omitted_reason": ("NATIVE_FIELD_FAILURES_OR_MISSING_PARTICLES_REPORTED"
                           if (failures or (isinstance(missing, (int, float)) and missing > 0)
                               or (isinstance(final_missing, (int, float)) and final_missing > 0))
                           else "NO_FIELD_FAILURE_REPORTED; DYNAMICS_UNASSESSED"),
        "source_scan_sha256": audit.get("scan_sha256"),
        "source_receipt_sha256": audit.get("receipt_sha256"),
    }


def _quality_summary(current: Mapping[str, Any], audit: Mapping[str, Any] | None) -> dict[str, Any]:
    old = current.get("quality") if isinstance(current.get("quality"), Mapping) else {}
    return {
        "visual": old.get("visual", "UNKNOWN"),
        "QI": _unknown_quality(audit.get("QI_dynamics") if isinstance(audit, Mapping) else None),
        "QN": _unknown_quality(audit.get("QN") if isinstance(audit, Mapping) else None),
        "QE": _unknown_quality(audit.get("QE") if isinstance(audit, Mapping) else None),
        "source_values": {
            "visual": old.get("visual"),
            "QI": audit.get("QI_dynamics") if isinstance(audit, Mapping) else None,
            "QN": audit.get("QN") if isinstance(audit, Mapping) else None,
            "QE": audit.get("QE") if isinstance(audit, Mapping) else None,
        },
        "impact": {
            "status": "EXACT_METADATA_FIELDS_ONLY" if isinstance(audit, Mapping) else "UNKNOWN",
            "fluid_initial_mass_kg": audit.get("fluid_initial_mass_kg") if isinstance(audit, Mapping) else None,
            "fluid_cumulative_unique_missing": audit.get("fluid_cumulative_unique_missing") if isinstance(audit, Mapping) else None,
            "fluid_missing_final_count": audit.get("fluid_missing_final_count") if isinstance(audit, Mapping) else None,
            "field_failure_count": len(audit.get("field_failures", [])) if isinstance(audit, Mapping) and isinstance(audit.get("field_failures"), list) else None,
            "physical_fate": "UNKNOWN",
            "flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
    }


def _physical_and_split(current: Mapping[str, Any], lifecycle: Mapping[str, Any] | None,
                        v26: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    family = str(current.get("family_id"))
    case_id = str(current.get("physical_case_id"))
    lifecycle_group = lifecycle.get("group_id") if isinstance(lifecycle, Mapping) else None
    v26_group = v26.get("group_id") if isinstance(v26, Mapping) else None
    v26_status = v26.get("group_status") if isinstance(v26, Mapping) else None
    # No owner SHA, generated XML, grid, rerun, recovery, or window marker is
    # ever used as a physical identity here.  Without all semantic axes and a
    # complete lineage join, close the whole family conservatively.
    axes = {
        "physical_condition": None,
        "geometry": None,
        "control": None,
        "initial_state": None,
        "lineage": None,
    }
    completeness = {name: False for name in axes}
    explicit = lifecycle.get("physical_condition") if isinstance(lifecycle, Mapping) else None
    if isinstance(explicit, Mapping):
        for name in axes:
            if explicit.get(name) not in (None, "", "UNKNOWN"):
                axes[name] = explicit[name]
                completeness[name] = True
    semantic_complete = all(completeness.values())
    # v26 groups are retained as diagnostics.  Their resolution/window/
    # recovery variants are forbidden split boundaries.
    diagnostic_group = v26_group or lifecycle_group or f"{family}:NO_EFFECTIVE_GROUP"
    union_group = (f"{family}:PHYSICAL:{hashlib.sha256(_canonical(axes).encode()).hexdigest()[:20]}"
                   if semantic_complete else f"{family}:UNKNOWN_PHYSICAL_LINEAGE")
    if not semantic_complete:
        union_group = f"{family}:UNKNOWN_PHYSICAL_LINEAGE"
    split_role = lifecycle.get("split_role") if isinstance(lifecycle, Mapping) else None
    assigned = bool(semantic_complete and split_role in ASSIGNED_ROLES
                    and v26_status not in (None, "UNKNOWN_CONSERVATIVE_GROUP"))
    split = {
        "status": "ASSIGNED" if assigned else "UNASSIGNED",
        "role": split_role if assigned else None,
        "hidden_test": False,
        "leakage_union_group_id": union_group,
        "diagnostic_effective_condition_group_id": diagnostic_group,
        "forbidden_cross_split_dimensions": ["rerun", "recovery", "grid", "resolution", "window"],
        "assignment_basis": ("complete physical/control/geometry/lineage evidence"
                             if assigned else "missing complete physical/control/geometry/lineage evidence"),
    }
    physical = {
        "condition_axes": axes,
        "axis_completeness": completeness,
        "semantic_assignment_allowed": semantic_complete,
        "physical_fate": lifecycle.get("physical_fate", "UNKNOWN") if isinstance(lifecycle, Mapping) else "UNKNOWN",
        "flux": "UNKNOWN",
        "dynamics": lifecycle.get("dynamical_impact", "UNKNOWN") if isinstance(lifecycle, Mapping) else "UNKNOWN",
        "native_exit_cause": "UNKNOWN",
    }
    return physical, split


def _case_record(current: Mapping[str, Any], audit: Mapping[str, Any] | None,
                 lifecycle: Mapping[str, Any] | None, v26: Mapping[str, Any] | None,
                 native_refs: Sequence[Mapping[str, Any]], mass_refs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    case_id = str(current["physical_case_id"])
    alias = current.get("runtime_case_alias")
    alias_known = isinstance(alias, str) and alias not in ("", "NONE")
    lifecycle_alias = lifecycle.get("historical_alias") if isinstance(lifecycle, Mapping) else None
    historical_unknown = (lifecycle_alias not in (None, "", "NONE")
                          or (isinstance(lifecycle, Mapping)
                              and lifecycle.get("source_join_status") == "SEPARATE_HISTORICAL_ALIAS_UNRESOLVED"))
    physical, split = _physical_and_split(current, lifecycle, v26)
    native = _native_summary(audit)
    lifecycle_status = lifecycle.get("status") if isinstance(lifecycle, Mapping) else None
    saved = bool(lifecycle.get("actual_saved_mask_coverage")) if isinstance(lifecycle, Mapping) else False
    current_source_roles = {
        "manifest": _role_ref(current.get("manifest"), "manifest"),
        "xmf": _role_ref(current.get("xmf"), "xmf"),
        "conversion_report": _role_ref(current.get("conversion_report"), "conversion_report"),
        "trajectory": _role_ref(current.get("trajectory"), "trajectory", payload=True),
        "raw_root": _role_ref(current.get("raw_root"), "raw_root", payload=True),
    }
    current_source_roles["source_bindings"] = {
        role: _role_ref(value, role, payload=False)
        for role, value in (current.get("source_bindings") or {}).items()
        if isinstance(role, str)
    }
    return {
        "current_index": current.get("current_index"),
        "family_id": current.get("family_id"),
        "canonical_case_id": case_id,
        "identity": {
            "canonical_case_id": case_id,
            "runtime_case_alias": alias,
            "runtime_alias_status": "PROVENANCE_ONLY" if alias_known else "NONE",
            "historical_alias_status": "UNKNOWN_IDENTITY" if historical_unknown else "NONE",
            "identity_status": "UNKNOWN_IDENTITY" if historical_unknown else "CANONICAL",
            "canonical_not_replaced_by_alias": True,
        },
        "saved_mask": {
            "status": "ACTUAL_COVERED" if saved else "NOT_OBSERVED",
            "actual_saved_mask_coverage": saved,
            "lifecycle_status": lifecycle_status,
            "attempt_lineage": lifecycle.get("attempt_lineage", []) if isinstance(lifecycle, Mapping) else [],
            "scientific_credit": lifecycle.get("scientific_credit") if isinstance(lifecycle, Mapping) else "NONE",
        },
        "native_numerical": native,
        "quality": _quality_summary(current, audit),
        "physical": physical,
        "split": split,
        "source_access": {
            "current_roles": current_source_roles,
            "audit_row_bound": isinstance(audit, Mapping),
            "lifecycle_row_bound": isinstance(lifecycle, Mapping),
            "v26_row_bound": isinstance(v26, Mapping),
            "native_proof_scopes": list(native_refs),
            "mass_proof_scopes": list(mass_refs),
            "historical_alias_is_not_source_fallback": True,
        },
        "development_material": True,
        "hidden_test": False,
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "qualification_credit": "NONE",
        "status": "DEVELOPMENT_METADATA_ONLY",
    }


def _write_new(path: Path, value: Mapping[str, Any]) -> tuple[str, str]:
    if path.exists() or path.is_symlink():
        raise Namespace330Error(f"refusing to overwrite namespace330 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True,
                               allow_nan=False) + "\n", encoding="utf-8")
    return canonical_sha(value), sha256_file(path)


def _load_input(path: Path | str, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return _read_source(path, role)


def build_namespace330(*, current_path: Path | str, audit_path: Path | str,
                       lifecycle_path: Path | str, v26_path: Path | str,
                       output_dir: Path | str, registry_path: Path | str | None = None,
                       source_access_path: Path | str | None = None,
                       native_proof_paths: Sequence[Path | str] = (),
                       mass_proof_paths: Sequence[Path | str] = (),
                       request_id: str = "namespace330-qualification-001") -> dict[str, Any]:
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise Namespace330Error(f"namespace330 output must be fresh: {output}")
    current, current_ref = _load_input(current_path, "CURRENT336")
    audit, audit_ref = _load_input(audit_path, "scientific_audit_v23")
    lifecycle, lifecycle_ref = _load_input(lifecycle_path, "typed_lifecycle_registry")
    v26, v26_ref = _load_input(v26_path, "effective_condition_v26")
    registry = registry_ref = None
    if registry_path is not None:
        registry, registry_ref = _load_input(registry_path, "lifecycle_evidence_registry")
    source_access = source_access_ref = None
    if source_access_path is not None:
        source_access, source_access_ref = _load_input(source_access_path, "family_source_access_index")
    native_values: list[dict[str, Any]] = []
    native_refs: list[dict[str, Any]] = []
    for index, path in enumerate(native_proof_paths):
        value, ref = _load_input(path, f"native_proof_{index}")
        native_values.append(value)
        native_refs.append(_proof_ref({**value, "path": str(Path(path).expanduser()), "sha256": ref["file_sha256"]},
                                      f"native_proof_{index}"))
        native_refs[-1]["source_file"] = ref
    mass_values: list[dict[str, Any]] = []
    mass_refs: list[dict[str, Any]] = []
    for index, path in enumerate(mass_proof_paths):
        value, ref = _load_input(path, f"actual_mass_proof_{index}")
        mass_values.append(value)
        mass_refs.append(_proof_ref({**value, "path": str(Path(path).expanduser()), "sha256": ref["file_sha256"]},
                                    f"actual_mass_proof_{index}"))
        mass_refs[-1]["source_file"] = ref

    current_rows = _validate_current(current)
    audit_rows = _map_unique(audit.get("verified_cases", []), "physical_case_id", "audit")
    lifecycle_rows = _map_unique(lifecycle.get("case_records", []), "physical_case_id", "lifecycle")
    v26_rows = _validate_v26(v26)
    records: list[dict[str, Any]] = []
    for current_index, row in enumerate(current_rows):
        row_with_index = dict(row)
        row_with_index.setdefault("current_index", current_index)
        case_id = str(row_with_index["physical_case_id"])
        records.append(_case_record(row_with_index, audit_rows.get(case_id), lifecycle_rows.get(case_id),
                                    v26_rows.get(case_id), native_refs, mass_refs))
    if len(records) != CASE_COUNT:
        raise Namespace330Error("namespace330 did not produce 336 records")
    family_records = {family: [record for record in records if record["family_id"] == family]
                      for family in FAMILIES}
    if any(len(rows) != CASES_PER_FAMILY for rows in family_records.values()):
        raise Namespace330Error("namespace330 family cards must contain exactly 48 canonical cases")

    source_refs: list[dict[str, Any]] = [current_ref, audit_ref, lifecycle_ref, v26_ref]
    for ref in (registry_ref, source_access_ref):
        if ref is not None:
            source_refs.append(ref)
    source_refs.extend(ref["source_file"] for ref in native_refs)
    source_refs.extend(ref["source_file"] for ref in mass_refs)
    input_summary = {
        "current_case_count": len(current_rows),
        "audit_rows": len(audit_rows),
        "lifecycle_rows": len(lifecycle_rows),
        "v26_rows": len(v26_rows),
        "lifecycle_registry_bound": registry_ref is not None,
        "audit_rows_missing_from_current": sorted(set(row["physical_case_id"] for row in current_rows) - set(audit_rows)),
        "lifecycle_rows_missing_from_current": sorted(set(row["physical_case_id"] for row in current_rows) - set(lifecycle_rows)),
        "native_proof_count": len(native_refs),
        "mass_proof_count": len(mass_refs),
    }
    catalog: dict[str, Any] = {
        "schema": CATALOG_SCHEMA,
        "namespace": "namespace330",
        "status": "DEVELOPMENT_METADATA_ONLY",
        "role": "336_CASE_QUALIFICATION_CATALOG_AND_SEVEN_FAMILY_CARDS",
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "development_material": True,
        "hidden_test": False,
        "model_invoked": False,
        "cfd_invoked": False,
        "case_count": CASE_COUNT,
        "family_counts": {family: len(family_records[family]) for family in FAMILIES},
        "input_summary": input_summary,
        "source_inputs": source_refs,
        "current_binding": {
            "path": str(Path(current_path).expanduser()),
            "file_sha256": current_ref["file_sha256"],
            "embedded_sha256": current.get("sha256"),
            "source_catalog_sha256": current.get("source_catalog_sha256"),
            "canonical_case_identity": "physical_case_id_exact; runtime_case_alias is provenance only",
        },
        "audit_binding": {
            "schema": audit.get("schema"),
            "path": str(Path(audit_path).expanduser()),
            "file_sha256": audit_ref["file_sha256"],
            "declared_distinct_completed_cases": audit.get("distinct_completed_cases"),
            "qualification_credit": "NONE",
        },
        "lifecycle_binding": {
            "schema": lifecycle.get("schema"),
            "path": str(Path(lifecycle_path).expanduser()),
            "file_sha256": lifecycle_ref["file_sha256"],
            "coverage": lifecycle.get("coverage"),
            "source_read_policy": lifecycle.get("source_read_policy"),
        },
        "lifecycle_registry_binding": ({
            "schema": registry.get("schema"),
            "path": str(Path(registry_path).expanduser()) if registry_path is not None else None,
            "file_sha256": registry_ref["file_sha256"] if registry_ref is not None else None,
            "status": registry.get("status"),
            "claim_boundary": registry.get("claim_boundary"),
        } if isinstance(registry, Mapping) and registry_ref is not None else {
            "status": "PENDING_NOT_BOUND", "path": None, "file_sha256": None,
        }),
        "physical_split_policy": {
            "assign_only_when_complete": ["physical_condition", "geometry", "control", "initial_state", "lineage"],
            "unknown_group_policy": "family-wide conservative leakage union",
            "forbidden_split_dimensions": ["rerun", "recovery", "grid", "resolution", "window"],
            "owner_sha256_is_not_identity": True,
            "split_default": "UNASSIGNED",
        },
        "cases": records,
    }
    catalog["sha256"] = canonical_sha(catalog)
    output.mkdir(parents=True, exist_ok=True)
    catalog_path = output / "namespace330-qualification-catalog.json"
    catalog_canonical_sha, catalog_file_sha = _write_new(catalog_path, catalog)

    card_paths: list[dict[str, Any]] = []
    cards_dir = output / "family-cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    access_summary = {
        "status": "UNKNOWN_UNLESS_BOUND",
        "source_index_schema": source_access.get("schema") if isinstance(source_access, Mapping) else None,
        "repository_license": (source_access.get("dependencies_and_licenses", {}).get("repository_license")
                                if isinstance(source_access, Mapping) and isinstance(source_access.get("dependencies_and_licenses"), Mapping) else None),
        "scientific_rights_status": "UNKNOWN",
        "path_policy": "exact paths only; no latest/glob/fallback",
    }
    for family in FAMILIES:
        rows = family_records[family]
        card = {
            "schema": CARD_SCHEMA,
            "namespace": "namespace330",
            "family_id": family,
            "status": "DEVELOPMENT_METADATA_ONLY",
            "development_material": True,
            "hidden_test": False,
            "case_count": len(rows),
            "canonical_case_ids": [row["canonical_case_id"] for row in rows],
            "case_refs": [
                {
                    "current_index": row["current_index"],
                    "canonical_case_id": row["canonical_case_id"],
                    "identity_status": row["identity"]["identity_status"],
                    "saved_mask_status": row["saved_mask"]["status"],
                    "native_status": row["native_numerical"]["status"],
                    "split_status": row["split"]["status"],
                    "leakage_union_group_id": row["split"]["leakage_union_group_id"],
                    "quality": row["quality"],
                }
                for row in rows
            ],
            "coverage": {
                "actual_saved_mask_cases": sum(row["saved_mask"]["actual_saved_mask_coverage"] for row in rows),
                "audit_rows_bound": sum(row["source_access"]["audit_row_bound"] for row in rows),
                "lifecycle_rows_bound": sum(row["source_access"]["lifecycle_row_bound"] for row in rows),
                "native_observed_metadata_cases": sum(row["native_numerical"]["status"] == "OBSERVED_METADATA_ONLY" for row in rows),
                "alias_unknown_identity_cases": sum(row["identity"]["identity_status"] == "UNKNOWN_IDENTITY" for row in rows),
                "split_unassigned_cases": sum(row["split"]["status"] == "UNASSIGNED" for row in rows),
            },
            "native_omission_summary": {
                "field_failure_cases": sum(bool(row["native_numerical"].get("field_failure_count")) for row in rows),
                "missing_particle_count_exact_rows": sum(row["native_numerical"].get("fluid_missing_final_count") is not None for row in rows),
                "physical_fate": "UNKNOWN",
                "flux": "UNKNOWN",
                "dynamics": "UNKNOWN",
            },
            "quality_summary": {
                "visual": "EXACT_OR_UNKNOWN_SOURCE_FIELD",
                "QI": "UNKNOWN",
                "QN": "UNKNOWN",
                "QE": "UNKNOWN",
                "exact_impact_fields": ["fluid_initial_mass_kg", "fluid_cumulative_unique_missing", "fluid_missing_final_count", "field_failure_count"],
                "null_when_absent": True,
            },
            "evidence_scope": {
                "native_proofs": native_refs,
                "mass_proofs": mass_refs,
                "saved_mask_lifecycle": lifecycle_ref,
                "lifecycle_registry": registry_ref,
                "scientific_audit": audit_ref,
                "qualification_credit": "NONE",
            },
            "physical_split": {
                "only_assign_with_complete_semantic_lineage": True,
                "all_current_family_rows_are_development_material": True,
                "leakage_dimensions_union_before_split": ["rerun", "recovery", "grid", "resolution", "window"],
                "unknown_group_is_conservative": True,
                "assigned_case_count": sum(row["split"]["status"] == "ASSIGNED" for row in rows),
            },
            "access_and_license": access_summary,
            "source_hashes": {
                "current_file_sha256": current_ref["file_sha256"],
                "audit_file_sha256": audit_ref["file_sha256"],
                "lifecycle_file_sha256": lifecycle_ref["file_sha256"],
                "v26_file_sha256": v26_ref["file_sha256"],
            },
        }
        card["sha256"] = canonical_sha(card)
        path = cards_dir / f"{family}-namespace330-family-card.json"
        card_canonical_sha, card_file_sha = _write_new(path, card)
        card_paths.append({"family_id": family, "path": str(path),
                           "canonical_sha256": card_canonical_sha, "file_sha256": card_file_sha})

    request = {
        "schema": REQUEST_SCHEMA,
        "namespace": "namespace330",
        "request_id": request_id,
        "status": "READY_FOR_ROOT_SOURCE_METADATA_GUARD",
        "role": "QUALIFICATION_CATALOG_AND_FAMILY_CARD_METADATA_ONLY",
        "development_material": True,
        "hidden_test": False,
        "qualification": dict(UNKNOWN_QUALIFICATION),
        "model_invoked": False,
        "cfd_invoked": False,
        "builder": {
            "script_role": "ds_data02_stage2_namespace330_qualification.py",
            "input_paths_are_explicit": True,
            "no_latest_or_glob_lookup": True,
            "command_template": "python3 scripts/ds_data02_stage2_namespace330_qualification.py build --current PATH --audit PATH --lifecycle PATH --v26 PATH --output FRESH_NAMESPACE",
        },
        "artifacts": {
            "catalog": {"path": str(catalog_path), "canonical_sha256": catalog_canonical_sha,
                        "file_sha256": catalog_file_sha},
            "family_cards": card_paths,
        },
        "source_inputs": source_refs,
        "input_summary": input_summary,
        "actual335_boundary": {
            "audit_rows_bound": len(audit_rows),
            "audit_rows_expected": CASE_COUNT,
            "lifecycle_exact_audit_rows": lifecycle.get("coverage", {}).get("exact_current_audit_rows") if isinstance(lifecycle.get("coverage"), Mapping) else None,
            "unbound_rows_are_explicit": True,
            "no_sha_invented": True,
        },
        "lifecycle_registry_binding": ({
            "schema": registry.get("schema"),
            "path": str(Path(registry_path).expanduser()),
            "file_sha256": registry_ref["file_sha256"],
        } if isinstance(registry, Mapping) and registry_ref is not None else {
            "status": "PENDING_NOT_BOUND", "path": None, "file_sha256": None,
        }),
        "read_scope": {
            "small_json_and_stat_only": True,
            "h5_opened": False,
            "bi4_opened": False,
            "raw_arrays_opened": False,
            "large_scientific_json_opened": False,
            "source_payload_hashes_deferred_to_parent_guard": True,
        },
        "access_and_license": access_summary,
        "source_identity_policy": {
            "canonical_case_id": "physical_case_id",
            "historical_alias": "UNKNOWN_IDENTITY_PROVENANCE_ONLY",
            "owner_sha256_not_physical_identity": True,
            "original_path_fallback": "FORBIDDEN",
        },
    }
    request["sha256"] = canonical_sha(request)
    request_path = output / "namespace330-source-request.json"
    request_canonical_sha, request_file_sha = _write_new(request_path, request)
    return {
        "schema": CATALOG_SCHEMA,
        "status": catalog["status"],
        "catalog_path": str(catalog_path),
        "catalog_sha256": catalog_canonical_sha,
        "catalog_file_sha256": catalog_file_sha,
        "family_cards": card_paths,
        "request_path": str(request_path),
        "request_sha256": request_canonical_sha,
        "request_file_sha256": request_file_sha,
        "case_count": CASE_COUNT,
        "family_counts": {family: len(rows) for family, rows in family_records.items()},
    }


def load_namespace330(output_dir: Path | str) -> dict[str, Any]:
    """Strictly load a generated namespace; reject stale/mutated sidecars."""
    output = Path(output_dir).expanduser()
    catalog_path = output / "namespace330-qualification-catalog.json"
    request_path = output / "namespace330-source-request.json"
    catalog = _read_json(catalog_path, "namespace330 catalog")
    request = _read_json(request_path, "namespace330 source request")
    if catalog.get("schema") != CATALOG_SCHEMA or catalog.get("sha256") != canonical_sha(catalog):
        raise Namespace330Error("namespace330 catalog schema/SHA mismatch")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise Namespace330Error("namespace330 request schema/SHA mismatch")
    if (catalog.get("case_count") != CASE_COUNT
            or catalog.get("qualification") != UNKNOWN_QUALIFICATION
            or catalog.get("hidden_test") is not False
            or catalog.get("development_material") is not True
            or request.get("qualification") != UNKNOWN_QUALIFICATION):
        raise Namespace330Error("namespace330 count/qualification boundary mismatch")
    artifacts = request.get("artifacts")
    if not isinstance(artifacts, Mapping) or not isinstance(artifacts.get("catalog"), Mapping):
        raise Namespace330Error("namespace330 request lacks catalog artifact binding")
    catalog_artifact = artifacts["catalog"]
    if catalog_artifact.get("canonical_sha256") != catalog["sha256"]:
        raise Namespace330Error("namespace330 request/catalog canonical SHA mismatch")
    if catalog_artifact.get("file_sha256") != sha256_file(catalog_path, maximum=MAX_METADATA_BYTES):
        raise Namespace330Error("namespace330 request/catalog file SHA mismatch")
    source_inputs = catalog.get("source_inputs")
    if not isinstance(source_inputs, list):
        raise Namespace330Error("namespace330 source input table is missing")
    for source in source_inputs:
        if not isinstance(source, Mapping) or not _hex64(source.get("file_sha256")):
            raise Namespace330Error("namespace330 source input SHA is incomplete")
        source_path = source.get("path")
        if isinstance(source_path, str) and source.get("content_policy") == "SMALL_METADATA_JSON_ONLY":
            if sha256_file(Path(source_path), maximum=MAX_METADATA_BYTES) != source["file_sha256"]:
                raise Namespace330Error(f"namespace330 source input changed: {source_path}")
    rows = catalog.get("cases")
    if not isinstance(rows, list) or len(rows) != CASE_COUNT:
        raise Namespace330Error("namespace330 catalog does not contain 336 cases")
    ids: set[str] = set()
    family_counts = {family: 0 for family in FAMILIES}
    for row in rows:
        if not isinstance(row, Mapping):
            raise Namespace330Error("namespace330 case row is not an object")
        case_id = row.get("canonical_case_id")
        family = row.get("family_id")
        if not isinstance(case_id, str) or case_id in ids or family not in family_counts:
            raise Namespace330Error("namespace330 canonical identity/family is invalid")
        ids.add(case_id)
        family_counts[family] += 1
        if row.get("development_material") is not True or row.get("hidden_test") is not False:
            raise Namespace330Error(f"case is not marked development-only: {case_id}")
        if row.get("qualification") != UNKNOWN_QUALIFICATION or row.get("qualification_credit") != "NONE":
            raise Namespace330Error(f"case qualification was promoted: {case_id}")
        identity = row.get("identity")
        if not isinstance(identity, Mapping) or identity.get("canonical_case_id") != case_id:
            raise Namespace330Error(f"canonical/alias identity mismatch: {case_id}")
        split = row.get("split")
        if not isinstance(split, Mapping) or split.get("status") not in SPLIT_STATUSES:
            raise Namespace330Error(f"invalid split status: {case_id}")
        if split.get("status") == "ASSIGNED" and split.get("role") not in ASSIGNED_ROLES:
            raise Namespace330Error(f"invalid assigned split role: {case_id}")
        if split.get("status") == "UNASSIGNED" and split.get("role") is not None:
            raise Namespace330Error(f"unassigned case has a split role: {case_id}")
        if not split.get("hidden_test") is False:
            raise Namespace330Error(f"split hidden-test flag is unsafe: {case_id}")
    if family_counts != {family: CASES_PER_FAMILY for family in FAMILIES}:
        raise Namespace330Error(f"namespace330 family counts mismatch: {family_counts}")
    card_paths = artifacts.get("family_cards")
    if not isinstance(card_paths, list) or len(card_paths) != len(FAMILIES):
        raise Namespace330Error("namespace330 request has incomplete family-card artifacts")
    expected_case_ids = {family: {row["canonical_case_id"] for row in rows
                                  if row.get("family_id") == family}
                         for family in FAMILIES}
    seen_card_families: set[str] = set()
    for item in card_paths:
        if not isinstance(item, Mapping):
            raise Namespace330Error("invalid family-card artifact")
        family_id = item.get("family_id")
        if family_id not in FAMILIES or family_id in seen_card_families:
            raise Namespace330Error("duplicate/invalid namespace330 family-card family")
        seen_card_families.add(str(family_id))
        path = Path(str(item.get("path", "")))
        card = _read_json(path, f"namespace330 {item.get('family_id')} card")
        if card.get("schema") != CARD_SCHEMA or card.get("sha256") != canonical_sha(card):
            raise Namespace330Error(f"family card schema/SHA mismatch: {path}")
        if item.get("canonical_sha256") != card.get("sha256"):
            raise Namespace330Error(f"family-card canonical SHA binding mismatch: {path}")
        if item.get("file_sha256") != sha256_file(path, maximum=MAX_METADATA_BYTES):
            raise Namespace330Error(f"family-card file SHA binding mismatch: {path}")
        if card.get("family_id") != family_id:
            raise Namespace330Error(f"family-card family binding mismatch: {path}")
        if card.get("case_count") != CASES_PER_FAMILY or card.get("hidden_test") is not False:
            raise Namespace330Error(f"family card boundary mismatch: {path}")
        if card.get("qualification", UNKNOWN_QUALIFICATION) != UNKNOWN_QUALIFICATION:
            raise Namespace330Error(f"family card qualification promoted: {path}")
        card_ids = card.get("canonical_case_ids")
        if not isinstance(card_ids, list) or len(card_ids) != CASES_PER_FAMILY or len(set(card_ids)) != CASES_PER_FAMILY:
            raise Namespace330Error(f"family card canonical identity count mismatch: {path}")
        if set(card_ids) != expected_case_ids[str(family_id)]:
            raise Namespace330Error(f"family card/catalog canonical identity mismatch: {path}")
    if seen_card_families != set(FAMILIES):
        raise Namespace330Error("namespace330 family-card set is incomplete")
    return {"schema": CATALOG_SCHEMA, "status": catalog.get("status"),
            "case_count": len(rows), "family_counts": family_counts,
            "catalog_sha256": catalog["sha256"], "request_sha256": request["sha256"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--audit", type=Path, required=True)
    build.add_argument("--lifecycle", type=Path, required=True)
    build.add_argument("--v26", type=Path, required=True)
    build.add_argument("--registry", type=Path)
    build.add_argument("--source-access", type=Path)
    build.add_argument("--native-proof", type=Path, action="append", default=[])
    build.add_argument("--mass-proof", type=Path, action="append", default=[])
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--request-id", default="namespace330-qualification-001")
    validate = sub.add_parser("validate")
    validate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build_namespace330(current_path=args.current, audit_path=args.audit,
                                        lifecycle_path=args.lifecycle, v26_path=args.v26,
                                        output_dir=args.output, registry_path=args.registry,
                                        source_access_path=args.source_access,
                                        native_proof_paths=args.native_proof,
                                        mass_proof_paths=args.mass_proof,
                                        request_id=args.request_id)
        else:
            result = load_namespace330(args.output)
    except (Namespace330Error, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
