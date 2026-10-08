#!/usr/bin/env python3
"""Build a conservative, component-level development split audit.

The CURRENT336 rows and lineage-v19 cards are metadata inputs.  This worker
does not open trajectory HDF5/BI4 files, read solver output, or infer a split
from a producer-declared trajectory digest.  It keeps the semantic physical,
control, and geometry payload separate from numerical/window/recovery
variations, so aliases and different resolutions/windows cannot leak across
roles.  A component is assigned one exposed development role, while every
unproved dimension remains an explicit promotion exclusion.

``development_test`` is an exposed development partition.  It is never a
hidden test set and does not grant QN/QE, physical-fate, or dynamics credit.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.equivalence-split-audit.v1"
REQUEST_SCHEMA = "ds02.stage2.equivalence-split-request.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
LINEAGE_SCHEMA = "ds02.stage2.current336-effective-lineage.v19-source-closure"
ROOT_PROOF_SCHEMA = "ds02.stage2.current336-development-lineage-metadata-independent.v1"
ROLES = ("development_train", "development_validation", "development_test")
UNRESOLVED_ROLE = "development_unresolved_excluded"


class SplitAuditError(RuntimeError):
    """Raised when source identity or split evidence is malformed."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise SplitAuditError(f"{label} must be a non-empty path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise SplitAuditError(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(str(value), label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SplitAuditError(f"{label} is invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise SplitAuditError(f"{label} must be a JSON object")
    return path, payload


def _canonical(value: Any, *, omitted: frozenset[str] = frozenset()) -> Any:
    """Return JSON-compatible canonical content without opaque metadata."""
    if isinstance(value, dict):
        return {
            str(key): _canonical(item, omitted=omitted)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in omitted
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item, omitted=omitted) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise SplitAuditError(f"unsupported metadata value type: {type(value).__name__}")


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _case_key(row: dict[str, Any]) -> tuple[str, str]:
    family = row.get("family_id")
    physical = row.get("physical_case_id")
    if not isinstance(family, str) or not family or not isinstance(physical, str) or not physical:
        raise SplitAuditError("CURRENT row lacks exact family_id/physical_case_id")
    return family, physical


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema") != CURRENT_SCHEMA:
        raise SplitAuditError("CURRENT schema is not ds02.stage2.current336.v1")
    rows = payload.get("cases")
    if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
        raise SplitAuditError("CURRENT cases must be a non-empty list of objects")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = _case_key(row)
        if key in seen:
            raise SplitAuditError(f"duplicate CURRENT identity: {key}")
        seen.add(key)
    return rows


def _links(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema") != LINEAGE_SCHEMA:
        raise SplitAuditError("lineage is not the v19 source-closure report")
    links = payload.get("case_source_links")
    if not isinstance(links, list) or not links or not all(isinstance(link, dict) for link in links):
        raise SplitAuditError("lineage case_source_links must be a non-empty list of objects")
    seen: set[tuple[str, str]] = set()
    for link in links:
        key = _case_key(link)
        if key in seen:
            raise SplitAuditError(f"duplicate lineage identity: {key}")
        seen.add(key)
    return links


def _verify_membership(current_path: Path, current: dict[str, Any],
                       lineage: dict[str, Any], rows: list[dict[str, Any]],
                       links: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    binding = lineage.get("catalog_binding")
    if not isinstance(binding, dict):
        raise SplitAuditError("lineage lacks catalog_binding")
    actual_current_sha = sha256_file(current_path)
    declared_current_sha = binding.get("current_json_sha256")
    if declared_current_sha != actual_current_sha:
        raise SplitAuditError("lineage catalog binding does not match CURRENT bytes")
    if binding.get("catalog_case_count") != len(rows):
        raise SplitAuditError("lineage catalog count differs from CURRENT")
    if lineage.get("status") not in {"DEVELOPMENT_ONLY; SEMANTIC_CLOSURE_PARTIAL", "DEVELOPMENT_ONLY; PROVISIONAL; QUALIFICATION_UNKNOWN"}:
        # The v19 producer may use a more specific status in a forward copy,
        # but a missing status is never silently accepted.
        if not isinstance(lineage.get("status"), str) or not lineage.get("status"):
            raise SplitAuditError("lineage status is missing")
    current_by_key = {_case_key(row): row for row in rows}
    lineage_by_key = {_case_key(link): link for link in links}
    if set(current_by_key) != set(lineage_by_key):
        missing = sorted(set(current_by_key) - set(lineage_by_key))
        extra = sorted(set(lineage_by_key) - set(current_by_key))
        raise SplitAuditError(f"CURRENT/lineage membership differs; missing={missing[:3]} extra={extra[:3]}")
    for key, row in current_by_key.items():
        link = lineage_by_key[key]
        # The exact CURRENT identity is authoritative.  Alias is metadata and
        # cannot repair an identity mismatch.
        if link.get("runtime_case_alias") != row.get("runtime_case_alias"):
            raise SplitAuditError(f"runtime alias differs for exact identity {key}")
        index = link.get("case_index")
        if isinstance(index, int) and (index < 0 or index >= len(rows) or _case_key(rows[index]) != key):
            raise SplitAuditError(f"lineage case_index is not bound to CURRENT row {key}")
    return current_by_key, lineage_by_key


def _guard_case_proofs(root: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Extract only explicit per-case content proofs.

    The v19 root verification report is a metadata membership proof and has no
    per-case H5 proof.  Generic ``current_sha256`` or ``report_file_sha256``
    fields are deliberately ignored here.
    """
    candidates: list[Any] = []
    for key in ("case_proofs", "trajectory_guard_hashes", "guard_hashes", "proofs"):
        value = root.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            candidates.extend(value.values())
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        family = item.get("family_id")
        physical = item.get("physical_case_id")
        if not isinstance(family, str) or not isinstance(physical, str):
            continue
        trajectory = item.get("trajectory")
        if not isinstance(trajectory, dict):
            trajectory = item.get("trajectory_h5")
        if not isinstance(trajectory, dict):
            trajectory = item
        declared = trajectory.get("declared_sha256") or trajectory.get("producer_declared_sha256")
        actual = trajectory.get("actual_sha256") or trajectory.get("recomputed_sha256")
        status = trajectory.get("status")
        read = trajectory.get("h5_read") is True or trajectory.get("content_read") is True
        if (isinstance(declared, str) and len(declared) == 64 and
                isinstance(actual, str) and len(actual) == 64 and actual == declared and
                status in {"GUARD_HASH_VERIFIED", "ACTUAL_HASH_VERIFIED", "CONTENT_HASH_VERIFIED"} and read):
            result[(family, physical)] = {
                "status": "guard_verified",
                "declared_sha256": declared,
                "actual_sha256": actual,
                "proof": item.get("proof_path") or item.get("receipt_path"),
            }
    return result


def _trajectory_evidence(row: dict[str, Any], link: dict[str, Any],
                         root: dict[str, Any] | None,
                         root_path: Path | None) -> dict[str, Any]:
    trajectory = row.get("trajectory") if isinstance(row.get("trajectory"), dict) else {}
    declared = trajectory.get("producer_declared_sha256")
    lineage_roles = link.get("source_closure", {}).get("roles", {})
    lineage_trajectory = lineage_roles.get("trajectory", {}) if isinstance(lineage_roles, dict) else {}
    lineage_declared = lineage_trajectory.get("expected_sha256")
    if declared and lineage_declared and declared != lineage_declared:
        raise SplitAuditError(f"producer trajectory digest differs for {_case_key(row)}")
    declared = declared or lineage_declared
    if not isinstance(declared, str) or len(declared) != 64:
        status = "unresolved"
    elif root is None:
        status = "producer_declared_only"
    else:
        status = "metadata_membership_only"
        proof = _guard_case_proofs(root).get(_case_key(row))
        if proof and proof.get("declared_sha256") == declared:
            status = "guard_verified"
    return {
        "declared_sha256": declared,
        "status": status,
        "root_verification_path": str(root_path) if root_path else None,
        "content_rehashed_by_this_worker": False,
    }


def _physical_semantics(link: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    group = link.get("physical_group")
    if not isinstance(group, dict):
        return None, {"status": "UNKNOWN", "provided_key": None}, ["physical_group_missing"]
    payload = group.get("semantic_payload")
    reasons: list[str] = []
    if not isinstance(payload, dict):
        reasons.append("physical_semantic_payload_missing")
        payload = None
    status = group.get("status")
    if status == "PROVISIONAL_UNKNOWN" or "UNKNOWN" in str(group.get("key", "")):
        reasons.append("physical_group_provisional_unknown")
    if group.get("split_safe") is not False and group.get("split_safe") is not True:
        reasons.append("split_safe_not_explicit")
    if group.get("split_safe") is False:
        reasons.append("split_safe_false")
    if payload is None:
        return None, {"status": "UNKNOWN", "provided_key": group.get("key")}, reasons
    # v19's physical key is a semantic payload digest.  Recompute it so an
    # opaque/edited key cannot silently create an equivalence.
    canonical_hash = _digest(payload)
    expected_key = f"{link.get('family_id')}:physical:{canonical_hash}"
    provided_key = group.get("key")
    if not isinstance(provided_key, str) or provided_key != expected_key:
        # A supplied semantic payload and its group key are an integrity pair.
        # Treat a mismatch as malformed evidence instead of silently making a
        # new component from whichever half happens to look convenient.
        raise SplitAuditError(
            f"physical_key_payload_mismatch for {_case_key(link)}: {provided_key!r} != {expected_key!r}"
        )
    if status != "SOURCE_SUPPORTED_DEVELOPMENT_GROUP":
        reasons.append("physical_status_not_source_supported")
    return payload, {
        "status": "PROVEN" if not any(reason in reasons for reason in (
            "physical_semantic_payload_missing", "physical_group_provisional_unknown",
            "physical_key_payload_mismatch", "physical_status_not_source_supported")) else "UNKNOWN",
        "provided_key": provided_key,
        "canonical_key": expected_key,
        "split_safe": group.get("split_safe"),
        "lineage_group_id": payload.get("lineage_group_id"),
    }, reasons


def _variation_dimensions(link: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    variation = link.get("variation_dimensions")
    if not isinstance(variation, dict):
        variation = {}
    window = variation.get("time_window_s")
    if window is None:
        window = row.get("actual_time_window_s")
    recovery_group = (
        link.get("recovery_group_id") or variation.get("recovery_group_id") or
        link.get("source_closure", {}).get("recovery_group_id")
    )
    recovery_value = variation.get("recovery")
    recovery_known = isinstance(recovery_group, str) and bool(recovery_group)
    if not recovery_known and isinstance(recovery_value, str) and "UNKNOWN" not in recovery_value.upper():
        recovery_group = recovery_value
        recovery_known = True
    window_group = link.get("window_group_id") or variation.get("window_group_id")
    window_known = isinstance(window_group, str) and bool(window_group)
    return {
        "frame_count": variation.get("frame_count", row.get("frames")),
        "particle_count": variation.get("particle_count", row.get("particles")),
        "resolution": variation.get("resolution"),
        "owner_resolution": variation.get("owner_resolution"),
        "solver_parameters_present": variation.get("owner_solver_parameters_present"),
        "time_window_s": window,
        "recovery_value": recovery_value,
        "recovery_group": recovery_group,
        "recovery_status": "PROVEN_GROUP" if recovery_known else "UNKNOWN",
        "window_group": window_group,
        "window_status": "PROVEN_GROUP" if window_known else "UNKNOWN_ACROSS_WINDOWS",
    }


def _dimension_keys(payload: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    controls = {
        "controls": payload.get("controls"),
        "gravity_m_s2": payload.get("gravity_m_s2"),
        "initial_state": payload.get("initial_state"),
        "periodic_boundary": payload.get("periodic_boundary"),
        "mechanism_id": payload.get("mechanism_id"),
    }
    geometry = {
        "geometry": payload.get("geometry"),
        "parameters": payload.get("parameters"),
        "physical_top_open": payload.get("parameters", {}).get("physical_top_open")
        if isinstance(payload.get("parameters"), dict) else None,
    }
    control_key = _digest(controls)
    geometry_key = _digest(geometry)
    return control_key, geometry_key


def _component_key(family: str, physical: dict[str, Any], physical_info: dict[str, Any],
                   control_key: str | None, geometry_key: str | None,
                   identity: tuple[str, str]) -> tuple[str, bool]:
    # Numerical dp, frame count, saved window, and recovery are intentionally
    # absent.  Their variation stays attached to one component and cannot be
    # split into separate roles without a new explicit lineage proof.
    if physical is not None and physical_info.get("canonical_key"):
        basis = {
            "family_id": family,
            "physical_key": physical_info["canonical_key"],
            "control_key": control_key,
            "geometry_key": geometry_key,
        }
        return "component:" + _digest(basis), True
    # An explicitly named UNKNOWN_CONSERVATIVE_GROUP is itself a conservative
    # component.  It is never promotion-eligible, but keeping its members
    # together prevents accidental leakage.
    provided = physical_info.get("provided_key")
    if isinstance(provided, str) and provided:
        return "component:" + _digest({"family_id": family, "provided_key": provided}), False
    return "component:" + _digest({"identity": identity}), False


def _role_for_component(component_id: str, ordinal: int) -> str:
    # Stable ordering by component id is independent of CURRENT row order and
    # case aliases.  Ordinal is only a deterministic tie breaker.
    return ROLES[ordinal % len(ROLES)]


def audit(current_path: Path | str, lineage_path: Path | str,
          root_verification_path: Path | str | None = None) -> dict[str, Any]:
    current_path, current = read_json(current_path, "CURRENT336")
    lineage_path, lineage = read_json(lineage_path, "lineage-v19")
    rows = _rows(current)
    links = _links(lineage)
    current_by_key, lineage_by_key = _verify_membership(current_path, current, lineage, rows, links)
    root_path: Path | None = None
    root: dict[str, Any] | None = None
    if root_verification_path is not None:
        root_path, root = read_json(root_verification_path, "root metadata verification")
        if root.get("schema") != ROOT_PROOF_SCHEMA:
            raise SplitAuditError("root verification has unsupported schema")
        if root.get("current_sha256") != sha256_file(current_path):
            raise SplitAuditError("root verification CURRENT digest differs")
        if root.get("cases") != len(rows):
            raise SplitAuditError("root verification case count differs")
        if root.get("root_h5_bi4_read") is True:
            # This audit still does not consume raw content.  The flag is
            # informational, but an unexpected broader scope is a hard error
            # so the request cannot be mistaken for a metadata-only worker.
            raise SplitAuditError("equivalence audit expects root metadata proof without H5/BI4 reads")

    root_case_proofs = _guard_case_proofs(root) if root is not None else {}
    records: list[dict[str, Any]] = []
    components: dict[str, dict[str, Any]] = {}
    for key, row in current_by_key.items():
        link = lineage_by_key[key]
        payload, physical_info, unresolved = _physical_semantics(link)
        control_key, geometry_key = _dimension_keys(payload)
        dimensions = _variation_dimensions(link, row)
        if control_key is None:
            unresolved.append("control_semantics_missing")
        if geometry_key is None:
            unresolved.append("geometry_semantics_missing")
        if dimensions["recovery_status"] != "PROVEN_GROUP":
            unresolved.append("recovery_equivalence_unknown")
        if dimensions["window_status"] != "PROVEN_GROUP":
            unresolved.append("window_equivalence_unknown")
        trajectory = _trajectory_evidence(row, link, root, root_path)
        if trajectory["status"] != "guard_verified":
            unresolved.append("trajectory_content_guard_not_verified")
        component_id, semantic_component = _component_key(
            key[0], payload, physical_info, control_key, geometry_key, key
        )
        if not semantic_component:
            unresolved.append("physical_component_not_semantically_proven")
        # Preserve a known false.  A v19 false split_safe may only produce an
        # exclusion, never a derived true value.
        if physical_info.get("split_safe") is False and "split_safe_false" not in unresolved:
            unresolved.append("split_safe_false")
        unresolved = sorted(set(unresolved))
        component = components.setdefault(component_id, {
            "component_id": component_id,
            "member_keys": [],
            "families": set(),
            "physical_keys": set(),
            "control_keys": set(),
            "geometry_keys": set(),
            "variation_signatures": [],
            "unresolved_reasons": set(),
            "trajectory_evidence_statuses": set(),
            "split_safe_values": set(),
        })
        component["member_keys"].append(key)
        component["families"].add(key[0])
        if physical_info.get("canonical_key"):
            component["physical_keys"].add(physical_info["canonical_key"])
        if control_key:
            component["control_keys"].add(control_key)
        if geometry_key:
            component["geometry_keys"].add(geometry_key)
        component["variation_signatures"].append({
            "physical_case_id": key[1],
            "runtime_case_alias": row.get("runtime_case_alias"),
            "frame_count": dimensions["frame_count"],
            "particle_count": dimensions["particle_count"],
            "resolution": dimensions["resolution"],
            "owner_resolution": dimensions["owner_resolution"],
            "time_window_s": dimensions["time_window_s"],
            "recovery_value": dimensions["recovery_value"],
            "recovery_group": dimensions["recovery_group"],
        })
        component["unresolved_reasons"].update(unresolved)
        component["trajectory_evidence_statuses"].add(trajectory["status"])
        component["split_safe_values"].add(physical_info.get("split_safe"))
        records.append({
            "family_id": key[0],
            "physical_case_id": key[1],
            "runtime_case_alias": row.get("runtime_case_alias"),
            "component_id": component_id,
            "component_basis": {
                "family_id": key[0],
                "physical_key": physical_info.get("canonical_key") or physical_info.get("provided_key"),
                "control_key": control_key,
                "geometry_key": geometry_key,
                "recovery_and_window_policy": "same_component; transfer unresolved unless explicit group evidence",
            },
            "dimensions": {
                "physical": physical_info.get("status", "UNKNOWN"),
                "control": "PROVEN" if control_key else "UNKNOWN",
                "geometry": "PROVEN" if geometry_key else "UNKNOWN",
                "recovery": dimensions["recovery_status"],
                "window": dimensions["window_status"],
                "numerical_resolution": dimensions["resolution"],
                "observed_time_window_s": dimensions["time_window_s"],
            },
            "trajectory_evidence": trajectory,
            "unresolved_exclusion": bool(unresolved),
            "unresolved_reasons": unresolved,
            "known_split_safe_value": physical_info.get("split_safe"),
        })

    ordered_components = sorted(components.values(), key=lambda item: item["component_id"])
    role_by_component: dict[str, str] = {}
    for ordinal, component in enumerate(ordered_components):
        role_by_component[component["component_id"]] = _role_for_component(component["component_id"], ordinal)
    for record in records:
        record["development_role"] = role_by_component[record["component_id"]]
    component_outputs: list[dict[str, Any]] = []
    for component in ordered_components:
        unresolved = sorted(component["unresolved_reasons"])
        role = role_by_component[component["component_id"]]
        component_outputs.append({
            "component_id": component["component_id"],
            "development_role": role,
            "promotion_status": "PROMOTION_ELIGIBLE" if not unresolved else "UNRESOLVED_EXCLUDED",
            "unresolved_exclusion": bool(unresolved),
            "unresolved_reasons": unresolved,
            "member_count": len(component["member_keys"]),
            "members": [{"family_id": family, "physical_case_id": physical}
                        for family, physical in sorted(component["member_keys"])],
            "families": sorted(component["families"]),
            "physical_keys": sorted(component["physical_keys"]),
            "control_keys": sorted(component["control_keys"]),
            "geometry_keys": sorted(component["geometry_keys"]),
            "variation_signatures": sorted(component["variation_signatures"],
                                            key=lambda item: item["physical_case_id"]),
            "trajectory_evidence_statuses": sorted(component["trajectory_evidence_statuses"]),
            "known_split_safe_values": sorted(component["split_safe_values"], key=lambda value: str(value)),
        })

    records.sort(key=lambda item: (item["family_id"], item["physical_case_id"]))
    split_counts = {role: sum(record["development_role"] == role for record in records) for role in ROLES}
    promoted_counts = {role: sum(
        record["development_role"] == role and not record["unresolved_exclusion"] for record in records
    ) for role in ROLES}
    component_roles = {component["component_id"]: component["development_role"] for component in component_outputs}
    component_not_split = all(
        len({record["development_role"] for record in records if record["component_id"] == component_id}) == 1
        for component_id in component_roles
    )
    known_false_preserved = all(
        record["known_split_safe_value"] is not False or record["unresolved_exclusion"]
        for record in records
    )
    return {
        "schema": SCHEMA,
        "status": "PASS_DEVELOPMENT_COMPONENT_AUDIT_WITH_EXPLICIT_UNRESOLVED_EXCLUSIONS",
        "inputs": {
            "current": {"path": str(current_path), "sha256": sha256_file(current_path), "schema": current.get("schema")},
            "lineage_v19": {"path": str(lineage_path), "sha256": sha256_file(lineage_path), "payload_sha256": lineage.get("sha256"), "schema": lineage.get("schema")},
            "root_metadata_verification": {
                "path": str(root_path) if root_path else None,
                "sha256": sha256_file(root_path) if root_path else None,
                "scope": "metadata_membership_only; no H5/BI4 content proof" if root else "not_supplied",
            },
        },
        "universe": {
            "current_case_count": len(records),
            "current_case_membership_exact": True,
            "all_current_cases_development_exposed": True,
            "hidden_test_claim": False,
            "exposure": "ALL_CURRENT336_DEVELOPMENT_EXPOSED",
        },
        "component_policy": {
            "identity": "exact (family_id, physical_case_id); runtime alias and trajectory digest are provenance only",
            "component_basis": ["family_id", "semantic physical payload", "control payload", "geometry payload"],
            "same_component_variations": ["dp/resolution", "particle_count", "frame_count", "time_window_s", "recovery window"],
            "window_recovery_rule": "variation is held in one component; without explicit continuity proof promotion remains unresolved",
            "cross_family_templates": "conservative boundary; no implicit cross-family equivalence",
            "role_assignment": "deterministic component order; one component has one exposed development role",
            "promotion_rule": "only components with no unresolved reason may be promoted; current v19 false/unknown evidence stays excluded",
        },
        "components": component_outputs,
        "cases": records,
        "diagnostics": {
            "component_count": len(component_outputs),
            "role_case_counts": split_counts,
            "promotion_eligible_case_counts": promoted_counts,
            "component_not_split": component_not_split,
            "trajectory_digest_not_used_as_component_identity": True,
            "producer_declared_h5_sha_is_not_guard_credit": True,
            "known_false_split_safe_preserved": known_false_preserved,
            "guard_verified_trajectory_case_count": sum(
                record["trajectory_evidence"]["status"] == "guard_verified" for record in records
            ),
            "metadata_only_trajectory_case_count": sum(
                record["trajectory_evidence"]["status"] == "metadata_membership_only" for record in records
            ),
            "producer_declared_only_trajectory_case_count": sum(
                record["trajectory_evidence"]["status"] == "producer_declared_only" for record in records
            ),
        },
        "claim_boundary": {
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "split_role": "development exposure only; development_test is not hidden",
        },
    }


def write_json(payload: dict[str, Any], output: Path | str, label: str) -> Path:
    path = Path(output).expanduser().resolve()
    if path.exists():
        raise SplitAuditError(f"refusing to overwrite {label}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def make_request(current_path: Path | str, lineage_path: Path | str,
                 root_verification_path: Path | str | None, output: Path | str,
                 worktree_root: Path | str, runtime_paths: Iterable[Path | str] | None = None) -> dict[str, Any]:
    current_path, current = read_json(current_path, "CURRENT336")
    lineage_path, lineage = read_json(lineage_path, "lineage-v19")
    rows = _rows(current)
    links = _links(lineage)
    _verify_membership(current_path, current, lineage, rows, links)
    root_path: Path | None = None
    if root_verification_path is not None:
        root_path, root = read_json(root_verification_path, "root metadata verification")
        if root.get("schema") != ROOT_PROOF_SCHEMA or root.get("current_sha256") != sha256_file(current_path):
            raise SplitAuditError("root verification is not bound to CURRENT")
    root = Path(worktree_root).expanduser().resolve()
    worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_equivalence_split_audit_v1.py"
    if runtime_paths is None:
        runtime_paths = (
            root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
            root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
            root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
        )
    runtime = [Path(path).expanduser().resolve() for path in runtime_paths]
    required = [worker, *runtime, current_path, lineage_path]
    if root_path:
        required.append(root_path)
    missing = [str(path) for path in required if not path.is_file()]
    input_files = []
    seen: set[str] = set()
    for path in required:
        if path.is_file() and str(path) not in seen:
            input_files.append(path)
            seen.add(str(path))
    input_hashes = {str(path): sha256_file(path) for path in input_files}
    source_bytes = sum(path.stat().st_size for path in input_files)
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": REQUEST_SCHEMA,
        "attempt_id": "equivalence-split-audit-v1",
        "case_id": "DS02_STAGE2_CURRENT336_EQUIVALENCE_SPLIT_AUDIT_V1",
        "family_id": "F1_F2_F3_F4_F5_F6_F7",
        "kind": "cpu",
        # Stage2 runner allowlists the generic metadata audit kind; the
        # scientific scope is carried separately in request_schema/note.
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(root / "lagrangian-fluid-lab/scripts"),
        "worktree_root": str(root),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker), "run", "--current", str(current_path), "--lineage", str(lineage_path),
            *( ["--root-verification", str(root_path)] if root_path else [] ),
            "--output", "{attempt_root}/equivalence-split-audit-v1.json",
        ],
        "input_files": [str(path) for path in input_files],
        "input_sha256": input_hashes,
        "launch_allowed": not missing,
        "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {
            "small_metadata_bytes_read": source_bytes,
            "original_trajectory_h5_bytes_read": 0,
            "part_bi4_bytes_read": 0,
            "solver_started": False,
            "cfd_or_model_run": False,
            "h5_content_hash_deferred": False,
        },
        "missing_guard_sources": missing,
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
        "split_policy": {
            "all_current_cases_exposed": True,
            "hidden_test_claim": False,
            "component_unit": "semantic physical/control/geometry component",
            "unresolved_exclusion": True,
        },
        "request_note": "Metadata-only CURRENT336/v19 equivalence audit; trajectory producer SHA is indexed but never treated as a guard content hash. No H5/BI4/solver/model is opened.",
    }
    write_json(request, output, "equivalence split request")
    return request


def _cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "audit"):
        command = sub.add_parser(name)
        command.add_argument("--current", required=True, type=Path)
        command.add_argument("--lineage", required=True, type=Path)
        command.add_argument("--root-verification", type=Path)
        command.add_argument("--output", required=True, type=Path)
    request = sub.add_parser("make-request")
    request.add_argument("--current", required=True, type=Path)
    request.add_argument("--lineage", required=True, type=Path)
    request.add_argument("--root-verification", type=Path)
    request.add_argument("--output", required=True, type=Path)
    request.add_argument("--worktree-root", required=True, type=Path)
    request.add_argument("--runtime", action="append", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _cli().parse_args(argv)
    if args.command in {"run", "audit"}:
        result = audit(args.current, args.lineage, args.root_verification)
        write_json(result, args.output, "equivalence split audit")
        return 0
    make_request(args.current, args.lineage, args.root_verification, args.output,
                 args.worktree_root, args.runtime)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
