#!/usr/bin/env python3
"""Construct a conservative effective-condition index for all 336 CURRENT rows.

The v25 cards describe one raw anchor per family.  This forward source-only
builder expands the semantic directory to every CURRENT row while retaining
the evidence boundary: source owner JSON, generated GenCase XML and bounded
receipt metadata are inspected; H5/BI4/raw arrays, JSONL and solver output
are never opened.  The catalog already contains header shape/stat metadata,
so those fields are carried as declarations rather than decoded payload.

An effective group is formed only when the available geometry, control,
initial-state, resolution, window and recovery-lineage metadata are all
bounded and comparable.  Missing axes produce an explicit unassigned
unknown group.  Resolution/window/recovery are part of the group key, so
same physics under a different resolution, recovery lineage or time window
cannot silently share a group.  Owner SHA values are retained as provenance
only and are never identity keys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Mapping


FAMILIES = tuple(f"F{i}" for i in range(1, 8))
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
INDEX_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v26"
CASE_SCHEMA = "ds02.stage2.effective-condition-case.v26"
REQUEST_SCHEMA = "ds02.stage2.effective-condition-metadata-request.v26"
V25_SCHEMA = "ds02.stage2.seven-family-effective-physical-source-index.v25"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_CATALOG_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
MAX_XML_BYTES = 128 * 1024


class EffectiveConditionV26Error(ValueError):
    """Malformed or over-promoted source-only metadata."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({k: v for k, v in value.items()
                                     if k != "sha256"}).encode()).hexdigest()


def sha256_file(path: Path, *, maximum: int | None = None) -> str:
    if path.is_symlink() or not path.is_file():
        raise EffectiveConditionV26Error(f"expected regular file: {path}")
    size = path.stat().st_size
    if maximum is not None and size > maximum:
        raise EffectiveConditionV26Error(f"bounded hash limit exceeded: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str, *, maximum: int = MAX_CATALOG_BYTES) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise EffectiveConditionV26Error(f"missing metadata JSON: {target}")
    if target.stat().st_size > maximum:
        raise EffectiveConditionV26Error(f"metadata JSON exceeds bounded limit: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EffectiveConditionV26Error(f"cannot read metadata JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise EffectiveConditionV26Error(f"metadata object required: {target}")
    return value


def read_bounded_json(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise EffectiveConditionV26Error(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _stat(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.exists():
        return {"exists": False}
    st = path.stat()
    return {
        "exists": True,
        "kind": "file" if path.is_file() else "directory",
        "bytes": int(st.st_size) if path.is_file() else None,
        "mode_bits": int(st.st_mode & 0o777),
        "mtime_ns": int(st.st_mtime_ns),
        "st_dev": int(st.st_dev),
        "st_ino": int(st.st_ino),
    }


def _clean(value: Any, *, key: str = "") -> Any:
    """Drop provenance identifiers, keeping condition semantics."""
    normal = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    # ``source_regions`` and ``source_motion`` can be physical declarations,
    # so only remove explicit hash/path/provenance keys here.
    drop_substrings = ("sha", "hash", "path", "uri", "owner", "receipt", "request",
                       "output", "runtime", "git", "pid", "alias")
    drop_exact = {"case_id", "physical_case_id", "family_id", "lineage_group_id"}
    if normal in drop_exact or any(token in normal for token in drop_substrings):
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            kept = _clean(item, key=str(raw_key))
            if kept is not None:
                result[str(raw_key)] = kept
        return result or None
    if isinstance(value, list):
        result = [_clean(item, key=key) for item in value]
        return [item for item in result if item is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _owner_binding(owner_path: Path) -> tuple[dict[str, Any] | None, str]:
    value = read_bounded_json(owner_path)
    if not value:
        return None, "OWNER_METADATA_MISSING_OR_OVER_BOUND"
    binding = value.get("physical_binding")
    if not isinstance(binding, Mapping):
        # F5's historical owner is a conversion scope record without a
        # physical binding.  Keep it unknown instead of guessing from names.
        return None, "OWNER_PHYSICAL_BINDING_ABSENT"
    cleaned = _clean(binding)
    if not isinstance(cleaned, Mapping) or not cleaned:
        return None, "OWNER_PHYSICAL_BINDING_EMPTY"
    return dict(cleaned), "OWNER_PHYSICAL_BINDING_METADATA_ONLY"


def _xml_metadata(path: Path) -> tuple[dict[str, Any] | None, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_XML_BYTES:
        return None, "GENERATED_XML_MISSING_OR_OVER_BOUND"
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ET.ParseError):
        return None, "GENERATED_XML_PARSE_FAILED"
    # Parse metadata attributes only.  Dates, app versions, paths and hashes
    # are excluded, while control/geometry/motion tags remain observable.
    records: list[dict[str, Any]] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else str(element.tag)
        attrs = {}
        for name, value in sorted(element.attrib.items()):
            normal = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            if any(token in normal for token in ("path", "file", "sha", "hash", "date", "app", "comment", "units_comment")):
                continue
            attrs[name] = value
        if attrs and tag not in {"case", "casedef", "geometry"}:
            records.append({"tag": tag, "attributes": attrs})
    if not records:
        return None, "GENERATED_XML_NO_CONDITION_ATTRIBUTES"
    return {"attribute_records": records}, "GENERATED_XML_CONTROL_GEOMETRY_METADATA_ONLY"


def _receipt_metadata(path: Path) -> dict[str, Any]:
    value = read_bounded_json(path)
    if not value:
        return {"status": "RECEIPT_METADATA_MISSING_OR_OVER_BOUND", "content_read": False}
    return {
        "status": value.get("status"),
        "returncode": value.get("returncode"),
        "termination_reason": value.get("termination_reason"),
        "numerical_reference_status": value.get("numerical_reference_status"),
        "production_product_acceptance": value.get("production_product_acceptance"),
        "content_read": True,
        "metadata_only": True,
    }


def _source_binding(case: Mapping[str, Any], role: str) -> Mapping[str, Any] | None:
    source = case.get("source_bindings")
    if isinstance(source, Mapping) and isinstance(source.get(role), Mapping):
        return source[role]
    return None


def _source_record(case: Mapping[str, Any], role: str, item: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
        return {"role": role, "status": "MISSING_DECLARATION"}, [f"source_role_declaration_missing:{role}"]
    path = Path(str(item["path"])).expanduser()
    stat = _stat(path)
    declared_sha = item.get("sha256") or item.get("recomputed_sha256")
    if role == "trajectory" and not declared_sha:
        trajectory = case.get("trajectory")
        if isinstance(trajectory, Mapping):
            declared_sha = trajectory.get("producer_declared_sha256")
    record = {
        "role": role, "path": str(path), "declared_sha256": declared_sha,
        "stat": stat, "content_read_by_v26": False,
        "payload_or_provenance": role == "trajectory",
    }
    gaps: list[str] = []
    if not stat.get("exists"):
        gaps.append(f"source_role_missing:{role}")
    if role == "trajectory":
        gaps.append("trajectory_h5_content_deferred_to_parent_guard")
    elif stat.get("kind") == "file" and stat.get("bytes", 0) > MAX_JSON_BYTES:
        gaps.append(f"source_content_hash_deferred:{role}")
    return record, gaps


def _hash_semantic(value: Any) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _axis(status: str, payload: Any, *, reason: str) -> dict[str, Any]:
    if payload is None:
        return {"status": "UNKNOWN_UNASSIGNED", "key": None, "payload": None, "reason": reason}
    return {"status": status, "key": _hash_semantic(payload), "payload": payload, "reason": reason}


def _owner_axis_payload(owner: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(owner, Mapping):
        return None
    value = owner.get(key)
    if value is None and key == "geometry":
        return owner.get("geometry")
    return value


def _condition_axes(case: Mapping[str, Any], owner: Mapping[str, Any] | None,
                    xml: Mapping[str, Any] | None, source: Mapping[str, Mapping[str, Any]],
                    receipt_meta: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    binding = owner if isinstance(owner, Mapping) else {}
    geometry = {
        "geometry_family_id": binding.get("geometry_family_id"),
        "geometry": _owner_axis_payload(binding, "geometry"),
        "mechanism_id": binding.get("mechanism_id"),
    }
    geometry = _clean(geometry)
    if not isinstance(geometry, Mapping) or not geometry.get("geometry"):
        geometry = None

    controls = {
        "control_family_id": binding.get("control_family_id"),
        "controls": binding.get("controls"),
        "mechanism_id": binding.get("mechanism_id"),
        "known_numeric_physical_parameters": case.get("known_numeric_physical_parameters"),
    }
    controls = _clean(controls)
    if not isinstance(controls, Mapping) or not any(value is not None for value in controls.values()):
        controls = None

    initial = _clean({
        "initial_state": binding.get("initial_state"),
        "known_numeric_physical_parameters": case.get("known_numeric_physical_parameters"),
    })
    if not isinstance(initial, Mapping) or not any(value is not None for value in initial.values()):
        initial = None

    # The generated XML is an independent source observation.  It is retained
    # in the axis payload, but not its SHA, to prevent source owner/hash values
    # from becoming a physical identity.
    xml_condition = xml.get("attribute_records") if isinstance(xml, Mapping) else None
    if geometry is not None and xml_condition is not None:
        geometry = {**geometry, "generated_xml_condition_attributes": xml_condition}
    if controls is not None and xml_condition is not None:
        controls = {**controls, "generated_xml_condition_attributes": xml_condition}

    resolution_payload = {
        "frames": case.get("frames"), "particles": case.get("particles"),
        "owner_resolution": binding.get("resolution"),
        "generated_xml_dp_or_resolution": [
            rec.get("attributes", {}).get("dp") for rec in (xml_condition or [])
            if isinstance(rec, Mapping) and isinstance(rec.get("attributes"), Mapping)
            and rec.get("attributes", {}).get("dp") is not None
        ],
    }
    resolution_payload = _clean(resolution_payload)

    window_payload = {
        "actual_time_window_s": case.get("actual_time_window_s"),
        "declared_event_window": binding.get("event_window"),
        "frames": case.get("frames"),
    }
    window_payload = _clean(window_payload)

    explicit_recovery = None
    for key in ("recovery", "recovery_lineage", "recovery_policy", "restart", "restart_policy"):
        if key in binding:
            explicit_recovery = _clean({key: binding[key]})
            break
    # Recovery is not inferred from a unique receipt or owner hash.  A unique
    # receipt is provenance, not a physical identity.  Only explicit recovery
    # metadata can separate this axis; absent metadata remains UNKNOWN and is
    # kept in one conservative group keyed by the other known axes.
    lineage = {
        "receipt_status": receipt_meta.get("status"),
    }
    recovery_payload = {"explicit": explicit_recovery, "lineage_observation": lineage}
    if explicit_recovery is None:
        recovery_payload = None

    return {
        "geometry": _axis("SOURCE_BOUND_SEMANTIC", geometry, reason="owner geometry plus generated XML metadata"),
        "control": _axis("SOURCE_BOUND_SEMANTIC", controls, reason="owner controls plus known numeric/XML metadata"),
        "initial_state": _axis("SOURCE_BOUND_SEMANTIC", initial, reason="owner initial state and catalog numeric metadata"),
        "resolution": _axis("SOURCE_DECLARED_ONLY", resolution_payload, reason="catalog/header and XML resolution declarations"),
        "window": _axis("SOURCE_DECLARED_ONLY", window_payload, reason="catalog time-window metadata; no trajectory read"),
        "recovery": _axis("LINEAGE_SEPARATION_ONLY" if recovery_payload else "UNKNOWN_UNASSIGNED",
                           recovery_payload,
                           reason="no explicit recovery/restart declaration; receipt lineage remains provenance only"),
    }


def effective_condition_key(family: str, axes: Mapping[str, Mapping[str, Any]]) -> tuple[str | None, str]:
    """Return a deterministic group key; unknown axes remain unassigned."""
    unknown = [axis for axis, value in axes.items() if value.get("status") == "UNKNOWN_UNASSIGNED"]
    payload = {axis: axes[axis].get("key") for axis in sorted(axes)}
    if unknown:
        # Keep unknown cases together when their known dimensions agree.  The
        # group is explicitly unsafe/unknown; it is never a train/test split.
        payload["unknown_axes"] = sorted(unknown)
    digest = hashlib.sha256(canonical({"family": family, "axes": payload}).encode()).hexdigest()
    return (f"{family}:UNKNOWN:{digest[:20]}" if unknown else f"{family}:EFFECTIVE:{digest[:20]}"), (
        "UNKNOWN_CONSERVATIVE_GROUP" if unknown else "SOURCE_BOUND_CONSERVATIVE"
    )


def _component_groups(cases: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    cases = list(cases)
    by_component: dict[tuple[str, str], list[int]] = {}
    for case in cases:
        index = int(case["current_index"])
        for role, source in case.get("source_bindings", {}).items():
            if role not in {"generated_xml", "xmf", "manifest"}:
                continue
            sha = source.get("declared_sha256")
            if isinstance(sha, str) and HEX64.fullmatch(sha):
                by_component.setdefault((role, sha), []).append(index)
    groups = []
    for (role, sha), indexes in sorted(by_component.items()):
        if len(indexes) < 2:
            continue
        groups.append({
            "group_id": f"SHARED_{role}_{sha[:16]}", "kind": "EXACT_SHARED_SOURCE_COMPONENT",
            "role": role, "sha256": sha, "current_indices": sorted(indexes),
            "families": sorted({str(next(c["family_id"] for c in cases if c["current_index"] == i))
                                  for i in indexes}),
            "split_safe": False,
            "owner_sha256_used_as_identity": False,
            "claim_boundary": "source component reuse/leakage observation only; no physical equivalence",
        })
    return groups


def _validate_catalog(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    if catalog.get("schema") != "ds02.stage2.current336.v1":
        # Keep this strict enough to prevent silently consuming an unrelated
        # inventory while accepting the current producer's versioned schema.
        raise EffectiveConditionV26Error(f"unexpected CURRENT catalog schema: {catalog.get('schema')}")
    cases = catalog.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise EffectiveConditionV26Error("CURRENT catalog is not exactly 336 cases")
    counts = {family: 0 for family in FAMILIES}
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping) or case.get("family_id") not in counts:
            raise EffectiveConditionV26Error(f"CURRENT row {index} has invalid family")
        counts[str(case["family_id"])] += 1
    if counts != {family: 48 for family in FAMILIES}:
        raise EffectiveConditionV26Error(f"CURRENT family counts differ: {counts}")
    return [dict(case) for case in cases]


def build(*, stage2_root: Path | str, output_dir: Path | str,
          current_catalog: Path | str | None = None,
          v25_index: Path | str | None = None) -> dict[str, Any]:
    stage2 = Path(stage2_root).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    catalog_path = Path(current_catalog).expanduser().resolve() if current_catalog else Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
    )
    v25_path = Path(v25_index).expanduser().resolve() if v25_index else stage2 / "lineage/v25-effective-physical-source-proof/SEVEN_FAMILY_EFFECTIVE_PHYSICAL_SOURCE_INDEX_V25.json"
    catalog = read_json(catalog_path)
    cases = _validate_catalog(catalog)
    v25 = read_json(v25_path)
    if v25.get("schema") != V25_SCHEMA or v25.get("qualification") != UNKNOWN:
        raise EffectiveConditionV26Error("v25 source index is not conservative")
    if v25.get("sha256") != canonical_sha(v25):
        raise EffectiveConditionV26Error("v25 index canonical SHA differs")

    out_cases: list[dict[str, Any]] = []
    owner_cache: dict[str, tuple[dict[str, Any] | None, str]] = {}
    xml_cache: dict[str, tuple[dict[str, Any] | None, str]] = {}
    receipt_cache: dict[str, dict[str, Any]] = {}
    all_gaps: dict[str, int] = {}

    for index, source_case in enumerate(cases):
        family = str(source_case["family_id"])
        source_bindings: dict[str, dict[str, Any]] = {}
        gaps: list[str] = []
        # Catalog fields are source declarations.  No source payload is read.
        for role in ("manifest", "xmf", "conversion_report", "trajectory",
                     "generated_xml", "gencase_receipt", "solver_receipt", "owner_metadata"):
            item = source_case.get(role) if role in {"manifest", "xmf", "conversion_report", "trajectory"} else _source_binding(source_case, role)
            record, role_gaps = _source_record(source_case, role, item)
            source_bindings[role] = record
            gaps.extend(role_gaps)

        owner_path = Path(source_bindings["owner_metadata"].get("path", ""))
        owner_key = str(owner_path)
        if owner_key not in owner_cache:
            owner_cache[owner_key] = _owner_binding(owner_path)
        owner, owner_status = owner_cache[owner_key]
        source_bindings["owner_metadata"]["semantic_status"] = owner_status
        source_bindings["owner_metadata"]["owner_sha256_is_provenance_only"] = True
        if owner is None:
            gaps.append("owner_physical_semantics_unknown")

        xml_path = Path(source_bindings["generated_xml"].get("path", ""))
        xml_key = str(xml_path)
        if xml_key not in xml_cache:
            xml_cache[xml_key] = _xml_metadata(xml_path)
        xml, xml_status = xml_cache[xml_key]
        source_bindings["generated_xml"]["semantic_status"] = xml_status
        if xml is None:
            gaps.append("generated_xml_semantics_unknown")

        receipt_meta: dict[str, Any] = {}
        for role in ("gencase_receipt", "solver_receipt"):
            path = Path(source_bindings[role].get("path", ""))
            key = str(path)
            if key not in receipt_cache:
                receipt_cache[key] = _receipt_metadata(path)
            source_bindings[role]["metadata"] = receipt_cache[key]
            receipt_meta[role] = receipt_cache[key]
        axes = _condition_axes(source_case, owner, xml,
                               source_bindings, receipt_meta.get("solver_receipt", {}))
        group_id, group_status = effective_condition_key(family, axes)
        if group_id is None:
            gaps.append("effective_condition_group_unassigned_unknown_axis")
        if axes["recovery"]["status"] == "LINEAGE_SEPARATION_ONLY":
            gaps.append("recovery_lineage_separates_only_no_recovery_equivalence")
        if axes["window"]["status"] != "SOURCE_DECLARED_ONLY":
            gaps.append("window_semantics_unknown")
        if not source_bindings["trajectory"].get("payload_or_provenance"):
            gaps.append("trajectory_payload_role_not_explicit")

        case_value: dict[str, Any] = {
            "schema": CASE_SCHEMA, "current_index": index, "family_id": family,
            "physical_case_id": source_case.get("physical_case_id"),
            "runtime_case_alias": source_case.get("runtime_case_alias"),
            "frames": source_case.get("frames"), "particles": source_case.get("particles"),
            "actual_time_window_s": source_case.get("actual_time_window_s"),
            "known_numeric_physical_parameters": source_case.get("known_numeric_physical_parameters"),
            "source_bindings": source_bindings,
            "effective_condition": {
                "group_id": group_id, "group_status": group_status,
                "axes": axes, "owner_sha256_used_as_identity": False,
                "lineage_provenance": {
                    "gencase_receipt_sha256": source_bindings.get("gencase_receipt", {}).get("declared_sha256"),
                    "solver_receipt_sha256": source_bindings.get("solver_receipt", {}).get("declared_sha256"),
                    "owner_metadata_sha256": source_bindings.get("owner_metadata", {}).get("declared_sha256"),
                    "identity_role": "PROVENANCE_ONLY",
                },
                "development_material_only": True,
            },
            "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "model_invoked": False, "cfd_invoked": False,
            "gaps": sorted(set(gaps)),
            "read_scope": {
                "catalog_metadata_opened": True, "owner_json_opened_bounded": owner is not None,
                "generated_xml_opened_bounded": xml is not None,
                "receipt_json_opened_bounded": bool(receipt_meta),
                "hdf5_opened": False, "bi4_opened": False, "raw_arrays_opened": False,
                "jsonl_opened": False, "solver_output_opened": False,
            },
        }
        case_value["sha256"] = canonical_sha(case_value)
        case_file = out / "cases" / family / f"{index:03d}-{family}.json"
        write_new(case_file, case_value)
        out_cases.append({
            "current_index": index, "family_id": family,
            "physical_case_id": source_case.get("physical_case_id"),
            "runtime_case_alias": source_case.get("runtime_case_alias"),
            "case_path": str(case_file), "case_sha256": case_value["sha256"],
            "group_id": group_id, "group_status": group_status,
            "gaps": case_value["gaps"],
        })
        for gap in case_value["gaps"]:
            all_gaps[gap] = all_gaps.get(gap, 0) + 1

    component_groups = _component_groups([{
        "current_index": index, "family_id": case["family_id"],
        "source_bindings": {
            role: {
                "declared_sha256": (
                    (case.get(role) or {}).get("recomputed_sha256")
                    or (case.get("source_bindings", {}).get(role) or {}).get("sha256")
                    or (case.get("source_bindings", {}).get(role) or {}).get("recomputed_sha256")
                )
            } for role in ("generated_xml", "xmf", "manifest")
        },
    } for index, case in enumerate(cases)])
    groups = {}
    for case in out_cases:
        groups.setdefault(case["group_id"] or f"UNASSIGNED:{case['current_index']:03d}", []).append(case["current_index"])
    group_records = []
    for group_id, members in sorted(groups.items()):
        group_records.append({
            "group_id": group_id, "current_indices": members,
            "families": sorted({out_cases[i]["family_id"] for i in members}),
            "status": "UNASSIGNED_UNKNOWN" if group_id.startswith("UNASSIGNED:") else "SOURCE_BOUND_CONSERVATIVE",
            "split_safe": False,
            "claim_boundary": "development material only; no qualification or hidden-test safety",
        })

    index_value: dict[str, Any] = {
        "schema": INDEX_SCHEMA, "status": "DEVELOPMENT_ALL336_SOURCE_INDEX_ONLY",
        "role": "DEVELOPMENT_EFFECTIVE_CONDITION_DIRECTORY",
        "qualification": dict(UNKNOWN), "model_invoked": False, "cfd_invoked": False,
        "versioned_from": {"v25_index_path": str(v25_path), "v25_index_sha256": v25["sha256"]},
        "current_catalog": {
            "path": str(catalog_path), "schema": catalog.get("schema"),
            "declared_sha256": catalog.get("source_catalog_sha256"),
            "observed_file_sha256": sha256_file(catalog_path, maximum=MAX_CATALOG_BYTES),
            "case_count": 336, "family_counts": {family: 48 for family in FAMILIES},
        },
        "coverage": {"all336_identities": True, "case_count": 336,
                     "family_counts": {family: 48 for family in FAMILIES},
                     "anchor_only_v25_not_used_as_case_coverage": True},
        "cases": out_cases, "effective_condition_groups": group_records,
        "source_component_leakage_groups": component_groups,
        "gap_counts": dict(sorted(all_gaps.items())),
        "read_scope": {
            "current_catalog_metadata_opened": True, "owner_xml_receipts_bounded": True,
            "hdf5_opened": False, "bi4_opened": False, "raw_arrays_opened": False,
            "jsonl_opened": False, "solver_output_opened": False,
        },
        "limitations": [
            "Every case is represented, but unknown axes are unassigned and never promoted.",
            "Resolution, window and recovery-lineage observations are group-separating metadata only.",
            "Owner SHA and source file SHA are provenance/component observations, not physical identity.",
            "No QI/QN/QE, physical equivalence, train/test split, or hidden-test safety claim.",
        ],
    }
    index_value["sha256"] = canonical_sha(index_value)
    index_file = out / "EFFECTIVE_PHYSICAL_SPLIT_INDEX_V26.json"
    write_new(index_file, index_value)

    request = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_METADATA_ONLY_PARENT_GUARD",
        "request_id": "ds02-effective-condition-all336-v26-metadata-primary-001",
        "mode": "SOURCE_ONLY_METADATA; NO_PAYLOAD_READ",
        "execution": {
            "python": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            "argv": ["-B", "-I", str(Path(__file__).resolve()), "--stage2-root", str(stage2),
                     "--current-catalog", str(catalog_path), "--v25-index", str(v25_path),
                     "--output-dir", str(out)],
            "cpu_threads": 1, "max_wall_seconds": 900, "memory_max_bytes": 2 * 1024**3,
            "parent_guard_required": True,
        },
        "source_inputs": {
            "current_catalog": {"path": str(catalog_path), "sha256": index_value["current_catalog"]["observed_file_sha256"],
                                 "content_role": "metadata rows/header declarations only"},
            "v25_index": {"path": str(v25_path), "sha256": v25["sha256"], "content_role": "small metadata"},
        },
        "outputs": {"index": str(index_file), "case_directory": str(out / "cases"),
                    "index_sha256": index_value["sha256"]},
        "read_policy": {"hdf5": "FORBID", "bi4": "FORBID", "raw_arrays": "FORBID",
                         "jsonl": "FORBID", "solver_output": "FORBID",
                         "owner_xml_receipts": "BOUNDED_METADATA_ONLY",
                         "original_path_fallback": "REJECT"},
        "qualification": dict(UNKNOWN), "model_invoked": False, "cfd_invoked": False,
    }
    request["sha256"] = canonical_sha(request)
    request_file = out / "effective-condition-metadata-request-v26.json"
    write_new(request_file, request)
    return {"index": str(index_file), "index_sha256": index_value["sha256"],
            "request": str(request_file), "request_sha256": request["sha256"],
            "case_count": 336, "group_count": len(group_records),
            "source_component_group_count": len(component_groups),
            "qualification": dict(UNKNOWN)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--current-catalog", type=Path)
    parser.add_argument("--v25-index", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build(stage2_root=args.stage2_root, output_dir=args.output_dir,
                       current_catalog=args.current_catalog, v25_index=args.v25_index)
    except (EffectiveConditionV26Error, OSError, ValueError) as error:
        print(f"effective conditions v26: {error}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
