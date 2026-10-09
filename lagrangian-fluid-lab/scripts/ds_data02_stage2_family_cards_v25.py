#!/usr/bin/env python3
"""Build the v25 source-only family cards and effective split index.

v25 is a forward metadata join over the immutable v24 cards, v14 anchor
plans, and v22/v23 evidence indexes.  It fixes one concrete v24 gap: the
all118 label-calibration record was written under the old consumer worktree
path, while the immutable v22 producer record and the actual output are
available at the infra path.  The join preserves both paths and proves the
same declared/content SHA before rebinding the evidence.

The split part is deliberately conservative.  It reads only bounded owner,
GenCase XML, receipt, and lineage metadata.  Owner hashes, case IDs, and
lineage labels are provenance; they are never used as physical identity.
Only exact shared physical source components (for example an identical
generated XML SHA or an explicitly shared control/geometry family) are
reported as candidate leakage groups.  Unknown controls, geometry,
recovery, and windows remain in an unknown group.  One raw anchor per family
does not establish all 48 semantic cases, so the remaining 47 cases stay
unassigned and every split remains unsafe.

This module never opens H5/BI4/raw arrays/JSONL/solver output.  It may hash
the bounded calibration JSON and receipt because those are metadata evidence
records, and it may parse small owner/XML/receipt files for source semantics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any, Mapping


FAMILIES = tuple(f"F{i}" for i in range(1, 8))
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
CARD_SCHEMA = "ds02.stage2.family-card.v25-effective-physical-source-proof"
INDEX_SCHEMA = "ds02.stage2.seven-family-effective-physical-source-index.v25"
V24_SCHEMA = "ds02.stage2.seven-family-effective-split-rights-index.v24"
V24_CARD_SCHEMA = "ds02.stage2.family-card.v24-effective-source-proof"
V22_SCHEMA = "ds02.stage2.seven-family-source-access-index.v22"
V23_SCHEMA = "ds02.stage2.seven-family-source-access-index.v23"
PLAN_SCHEMA = "ds02.stage2.family-raw-anchor-plan.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SMALL_SOURCE_BYTES = 256 * 1024
MAX_CALIBRATION_BYTES = 8 * 1024 * 1024
MAX_XML_BYTES = 128 * 1024


class FamilyCardV25Error(ValueError):
    """Malformed, stale, or over-promoted source-only input."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({k: v for k, v in value.items()
                                     if k != "sha256"}).encode()).hexdigest()


def sha256_file(path: Path, *, maximum: int | None = None) -> str:
    if path.is_symlink() or not path.is_file():
        raise FamilyCardV25Error(f"expected a regular non-symlink file: {path}")
    size = path.stat().st_size
    if maximum is not None and size > maximum:
        raise FamilyCardV25Error(f"file exceeds bounded hash limit ({size}): {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path | str, *, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise FamilyCardV25Error(f"missing JSON metadata: {target}")
    if target.stat().st_size > maximum:
        raise FamilyCardV25Error(f"JSON metadata exceeds bounded limit: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FamilyCardV25Error(f"cannot read JSON metadata {target}: {error}") from error
    if not isinstance(value, dict):
        raise FamilyCardV25Error(f"JSON object required: {target}")
    return value


def read_small_json(path: Path, *, maximum: int = MAX_SMALL_SOURCE_BYTES) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FamilyCardV25Error(f"refusing to overwrite v25 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise FamilyCardV25Error(f"{label} is not a lowercase SHA-256")
    return value


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise FamilyCardV25Error(f"{label} is not an absolute path")
    return Path(value).expanduser()


def _stat(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.exists():
        return {"exists": False}
    st = path.stat()
    return {"exists": True, "kind": "file" if path.is_file() else "directory",
            "bytes": int(st.st_size) if path.is_file() else None,
            "mode_bits": int(st.st_mode & 0o777),
            "mtime_ns": int(st.st_mtime_ns), "st_dev": int(st.st_dev),
            "st_ino": int(st.st_ino)}


def _semantic_clean(value: Any, *, key: str = "") -> Any:
    """Keep physical/control metadata while removing provenance identifiers."""
    normal = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    dropped = ("sha", "hash", "path", "uri", "owner", "receipt", "source",
               "case_id", "physical_case_id", "family_id", "lineage", "alias",
               "request", "output", "runtime", "git", "pid", "time_start",
               "time_end", "window", "resolution", "solver", "gpu", "thread",
               "save", "dt", "cfl", "coef")
    if any(token in normal for token in dropped):
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            cleaned = _semantic_clean(item, key=str(raw_key))
            if cleaned is not None:
                result[str(raw_key)] = cleaned
        return result or None
    if isinstance(value, list):
        result = [_semantic_clean(item, key=key) for item in value]
        return [item for item in result if item is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _owner_semantics(path: Path) -> tuple[dict[str, Any] | None, str]:
    value = read_small_json(path)
    if not value:
        return None, "owner_metadata_missing_or_not_bounded"
    physical = value.get("physical_binding")
    if not isinstance(physical, Mapping):
        # A legacy owner can expose the binding fields at the top level.  Do
        # not manufacture a binding if its required physical dimensions are
        # absent.
        if all(key in value for key in ("geometry", "mechanism_id", "initial_state")):
            physical = value
        else:
            return None, "owner_physical_binding_missing"
    clean = _semantic_clean(physical)
    if not isinstance(clean, Mapping) or not clean:
        return None, "owner_physical_binding_has_no_semantic_fields"
    return dict(clean), "owner_physical_binding_metadata_only"


def _xml_semantics(path: Path) -> tuple[dict[str, Any] | None, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_XML_BYTES:
        return None, "generated_xml_missing_or_over_bound"
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ET.ParseError):
        return None, "generated_xml_parse_failed"
    constants = root.find("./casedef/constantsdef")
    mkconfig = root.find("./casedef/mkconfig")
    definition = root.find("./casedef/geometry/definition")
    control: dict[str, Any] = {}
    if constants is not None:
        for attr in ("gravity", "rhop0", "rhopgradient", "gamma", "cflnumber"):
            node = constants.find(attr)
            if node is not None:
                control[attr] = {str(k): str(v) for k, v in sorted(node.attrib.items())}
    geometry: dict[str, Any] = {}
    if mkconfig is not None:
        geometry["mkconfig"] = {str(k): str(v) for k, v in sorted(mkconfig.attrib.items())}
    if definition is not None:
        geometry["definition"] = {str(k): str(v) for k, v in sorted(definition.attrib.items())
                                   if k in {"dp", "type", "units_comment"}}
    payload = {"control": control, "geometry": geometry}
    return payload, "generated_xml_control_geometry_metadata_only"


def _receipt_semantics(path: Path) -> dict[str, Any]:
    value = read_small_json(path)
    if not value:
        return {"status": "RECEIPT_METADATA_UNAVAILABLE"}
    return {
        "status": value.get("status"),
        "returncode": value.get("returncode"),
        "termination_reason": value.get("termination_reason"),
        "total_particles": value.get("total_particles"),
        "fluid_particles": value.get("fluid_particles"),
        "solver_dimension_from_gencase": value.get("solver_dimension_from_gencase"),
        "metadata_only": True,
    }


def _source_role(plan_binding: Mapping[str, Any], family: str) -> tuple[dict[str, Any], list[str]]:
    role = str(plan_binding.get("role", ""))
    path = _path(plan_binding.get("path"), f"{family}.{role}.path")
    declared_sha = plan_binding.get("sha256")
    # trajectory H5 is explicitly payload/provenance and has no content SHA
    # in the plan; never stat/hash its contents here beyond the bounded stat.
    result: dict[str, Any] = {
        "role": role, "path": str(path), "declared_sha256": declared_sha,
        "declared_bytes": plan_binding.get("bytes"), "declared_status": plan_binding.get("status"),
        "payload_or_provenance": role == "trajectory_h5",
        "observed_stat": _stat(path),
        "content_read_by_v25": False,
    }
    gaps: list[str] = []
    if not result["observed_stat"].get("exists"):
        gaps.append(f"source_role_missing:{role}")
    if role == "trajectory_h5":
        gaps.append("trajectory_h5_content_deferred_to_parent_guard")
        return result, gaps
    if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_SMALL_SOURCE_BYTES:
        result["observed_sha256"] = sha256_file(path, maximum=MAX_SMALL_SOURCE_BYTES)
        result["content_read_by_v25"] = True
        if isinstance(declared_sha, str) and HEX64.fullmatch(declared_sha):
            result["sha_match"] = result["observed_sha256"] == declared_sha
            if not result["sha_match"]:
                gaps.append(f"source_role_sha_mismatch:{role}")
    elif path.is_file():
        result["content_sha_status"] = "DEFERRED_BOUNDED_SOURCE_ONLY"
        gaps.append(f"source_role_content_hash_deferred:{role}")
    return result, gaps


def _validate_v24(index: Mapping[str, Any], cards_dir: Path) -> None:
    if index.get("schema") != V24_SCHEMA or index.get("qualification") != UNKNOWN:
        raise FamilyCardV25Error("v24 index is not the conservative source index")
    if index.get("sha256") != canonical_sha(index):
        raise FamilyCardV25Error("v24 index canonical SHA differs")
    for family in FAMILIES:
        entry = index.get("family_cards", {}).get(family)
        if not isinstance(entry, Mapping):
            raise FamilyCardV25Error(f"v24 card binding missing for {family}")
        card_path = Path(entry.get("path", ""))
        if not card_path.is_file() or card_path.is_symlink():
            card_path = cards_dir / f"{family}-family-card-v24-effective-source-proof.json"
        card = read_json(card_path)
        if card.get("schema") != V24_CARD_SCHEMA or card.get("family_id") != family:
            raise FamilyCardV25Error(f"v24 card schema/family differs for {family}")
        if card.get("sha256") != canonical_sha(card):
            raise FamilyCardV25Error(f"v24 card canonical SHA differs for {family}")
        if card.get("qualification") != UNKNOWN or card.get("case_count") != 48:
            raise FamilyCardV25Error(f"v24 card overclaims {family}")


def _calibration_binding(*, v22: Mapping[str, Any], v23: Mapping[str, Any]) -> dict[str, Any]:
    old = v23.get("evidence_bindings", {}).get("all118_label_calibration")
    actual = v22.get("evidence_bindings", {}).get("all118_label_calibration")
    if not isinstance(old, Mapping) or not isinstance(actual, Mapping):
        raise FamilyCardV25Error("all118 label-calibration binding missing in v22/v23")
    old_sha = require_sha(old.get("sha256"), "v23 calibration SHA")
    actual_sha = require_sha(actual.get("sha256"), "v22 calibration SHA")
    if old_sha != actual_sha:
        raise FamilyCardV25Error("v22/v23 calibration SHA declarations differ")
    actual_path = _path(actual.get("path"), "v22 actual calibration path")
    actual_receipt = _path(actual.get("receipt_path"), "v22 calibration receipt path")
    actual_stat = _stat(actual_path)
    receipt_stat = _stat(actual_receipt)
    if not actual_stat.get("exists") or actual_stat.get("kind") != "file":
        raise FamilyCardV25Error("v22 actual calibration output is missing")
    if actual_stat.get("bytes", 0) > MAX_CALIBRATION_BYTES:
        raise FamilyCardV25Error("v22 calibration exceeds bounded metadata hash limit")
    observed_sha = sha256_file(actual_path, maximum=MAX_CALIBRATION_BYTES)
    if observed_sha != actual_sha:
        raise FamilyCardV25Error("v22 actual calibration SHA does not match declaration")
    receipt_sha = require_sha(actual.get("receipt_sha256"), "v22 calibration receipt SHA")
    if not receipt_stat.get("exists") or receipt_stat.get("kind") != "file":
        raise FamilyCardV25Error("v22 actual calibration receipt is missing")
    if receipt_stat.get("bytes", 0) > MAX_CALIBRATION_BYTES:
        raise FamilyCardV25Error("v22 calibration receipt exceeds bounded hash limit")
    observed_receipt_sha = sha256_file(actual_receipt, maximum=MAX_CALIBRATION_BYTES)
    if observed_receipt_sha != receipt_sha:
        raise FamilyCardV25Error("v22 actual calibration receipt SHA does not match declaration")
    coverage = actual.get("coverage")
    if not isinstance(coverage, Mapping) or coverage.get("selected_case_count") != 118:
        raise FamilyCardV25Error("v22 calibration coverage is not all118")
    families = coverage.get("families")
    if families != {"F2": 48, "F4": 22, "F6": 48}:
        raise FamilyCardV25Error("v22 calibration family coverage differs")
    if actual.get("status") != "LABEL_CALIBRATED_SOURCE_MK_CENSORING_NO_MODEL":
        raise FamilyCardV25Error("v22 calibration status is not source-only")
    return {
        "id": "all118_label_calibration",
        "historical_v23_binding": {
            "path": str(_path(old.get("path"), "v23 calibration path")),
            "declared_sha256": old_sha,
            "status": old.get("status"),
            "actionable": False,
            "reason": "old consumer-worktree path retained as provenance only",
        },
        "actual_v22_binding": {
            "path": str(actual_path), "declared_sha256": actual_sha,
            "observed_sha256": observed_sha, "stat": actual_stat,
            "receipt_path": str(actual_receipt), "receipt_sha256": receipt_sha,
            "receipt_observed_sha256": observed_receipt_sha,
            "receipt_stat": receipt_stat,
            "coverage": dict(coverage), "status": actual.get("status"),
            "claim_boundary": dict(actual.get("claim_boundary", {})),
            "actionable": True,
        },
        "rebind_status": "ACTUAL_V22_INFRA_PATH_REBOUND_SAME_CONTENT_SHA",
        "qualification": dict(UNKNOWN),
    }


def _component_signature(family: str, source_roles: Mapping[str, Mapping[str, Any]],
                         owner_semantic: Mapping[str, Any] | None,
                         xml_semantic: Mapping[str, Any] | None,
                         anchor: Mapping[str, Any]) -> dict[str, Any]:
    # The exact role/SHA values are useful for provenance, but only selected
    # physical source roles participate in cross-family leakage groups.
    physical_roles = ("generated_xml", "xmf")
    exact_components = []
    for role in physical_roles:
        item = source_roles.get(role, {})
        sha = item.get("declared_sha256")
        if isinstance(sha, str) and HEX64.fullmatch(sha):
            exact_components.append({"role": role, "sha256": sha})
    semantic = {}
    if isinstance(owner_semantic, Mapping):
        semantic = dict(owner_semantic)
    # The anchor's numeric parameters are useful control observations, but
    # they are never treated as proof of physical identity on their own.
    numeric = anchor.get("known_numeric_physical_parameters")
    if isinstance(numeric, Mapping):
        semantic["anchor_numeric_parameters"] = dict(numeric)
    if isinstance(xml_semantic, Mapping):
        semantic["generated_xml_metadata"] = dict(xml_semantic)
    return {
        "family_id": family,
        "exact_physical_source_components": exact_components,
        "semantic_control_geometry_observation": semantic or None,
        "owner_sha_used_as_identity": False,
        "identity_status": "SOURCE_METADATA_ONLY; NOT_PHYSICAL_EQUIVALENCE",
    }


def _leakage_groups(signatures: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for family, signature in signatures.items():
        for component in signature.get("exact_physical_source_components", []):
            key = (str(component["role"]), str(component["sha256"]))
            groups.setdefault(key, []).append(family)
    result: list[dict[str, Any]] = []
    for (role, sha), families in sorted(groups.items()):
        families = sorted(set(families))
        if len(families) > 1:
            result.append({
                "group_id": f"EXACT_SHARED_{role}_{sha[:16]}",
                "kind": "EXACT_SHARED_PHYSICAL_SOURCE_COMPONENT",
                "role": role, "sha256": sha, "families": families,
                "split_safe": False,
                "claim_boundary": "candidate leakage group only; no physical equivalence or qualification",
            })
    if not result:
        result.append({
            "group_id": "NO_EXACT_SHARED_PHYSICAL_SOURCE_COMPONENTS_OBSERVED",
            "kind": "NO_CROSS_FAMILY_EXACT_COMPONENT_OBSERVED",
            "families": [], "split_safe": False,
            "claim_boundary": "source-only anchor observations; unknown dimensions remain unassigned",
        })
    return result


def build(*, stage2_root: Path | str, output_dir: Path | str,
          v24_index: Path | str | None = None,
          v24_cards_dir: Path | str | None = None,
          v22_access_index: Path | str | None = None,
          v23_access_index: Path | str | None = None,
          plans_dir: Path | str | None = None) -> dict[str, Any]:
    stage2 = Path(stage2_root).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    old_index_path = Path(v24_index).expanduser().resolve() if v24_index else stage2 / "lineage/v24-effective-source-proof/SEVEN_FAMILY_EFFECTIVE_SPLIT_RIGHTS_INDEX_V24.json"
    old_cards = Path(v24_cards_dir).expanduser().resolve() if v24_cards_dir else stage2 / "lineage/v24-effective-source-proof"
    v22_path = Path(v22_access_index).expanduser().resolve() if v22_access_index else stage2 / "lineage/v22-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V22.json"
    v23_path = Path(v23_access_index).expanduser().resolve() if v23_access_index else stage2 / "lineage/v23-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V23.json"
    plans = Path(plans_dir).expanduser().resolve() if plans_dir else stage2 / "lineage/v14/raw-anchor-plans"

    old_index = read_json(old_index_path)
    _validate_v24(old_index, old_cards)
    v22 = read_json(v22_path)
    if v22.get("schema") != V22_SCHEMA or v22.get("qualification") != UNKNOWN:
        raise FamilyCardV25Error("v22 source access index is not conservative")
    v23 = read_json(v23_path)
    if v23.get("schema") != V23_SCHEMA or v23.get("qualification") != UNKNOWN:
        raise FamilyCardV25Error("v23 source access index is not conservative")
    calibration = _calibration_binding(v22=v22, v23=v23)

    cards: dict[str, str] = {}
    summaries: dict[str, dict[str, Any]] = {}
    signatures: dict[str, dict[str, Any]] = {}
    gaps_by_family: dict[str, list[str]] = {}
    calibration_families = set(calibration["actual_v22_binding"]["coverage"]["families"])

    for family in FAMILIES:
        v24_entry = old_index["family_cards"][family]
        v24_card_path = Path(v24_entry["path"])
        if not v24_card_path.is_file():
            v24_card_path = old_cards / f"{family}-family-card-v24-effective-source-proof.json"
        v24_card = read_json(v24_card_path)
        plan_path = plans / f"{family}-raw-anchor-plan-v1.json"
        plan = read_json(plan_path)
        if plan.get("schema") != PLAN_SCHEMA or plan.get("family_id") != family:
            raise FamilyCardV25Error(f"{family} raw-anchor plan schema/family differs")
        if plan.get("case_count") != 48 or plan.get("qualification") != UNKNOWN:
            raise FamilyCardV25Error(f"{family} raw-anchor plan is not 48/UNKNOWN")
        anchor = plan.get("anchor_case")
        if not isinstance(anchor, Mapping) or not isinstance(anchor.get("current_index"), int):
            raise FamilyCardV25Error(f"{family} anchor metadata is incomplete")
        source_roles: dict[str, dict[str, Any]] = {}
        source_gaps: list[str] = []
        for item in plan.get("source_bindings", []):
            if not isinstance(item, Mapping):
                raise FamilyCardV25Error(f"{family} source binding is not an object")
            summary, item_gaps = _source_role(item, family)
            source_roles[str(item.get("role"))] = summary
            source_gaps.extend(item_gaps)
        owner_binding = source_roles.get("owner_metadata", {})
        owner_path = Path(owner_binding.get("path", ""))
        owner_semantic, owner_status = _owner_semantics(owner_path)
        xml_binding = source_roles.get("generated_xml", {})
        xml_path = Path(xml_binding.get("path", ""))
        xml_semantic, xml_status = _xml_semantics(xml_path)
        source_roles["owner_metadata"]["semantic_status"] = owner_status
        source_roles["owner_metadata"]["owner_sha_identity"] = False
        source_roles["generated_xml"]["semantic_status"] = xml_status
        for role in ("gencase_receipt", "solver_receipt"):
            if role in source_roles:
                source_roles[role]["semantic_metadata"] = _receipt_semantics(Path(source_roles[role]["path"]))

        signature = _component_signature(family, source_roles, owner_semantic, xml_semantic, anchor)
        signatures[family] = signature
        old_gaps = list(old_index.get("gaps_by_family", {}).get(family, []))
        # Drop the stale v23 path gap only for families actually covered by
        # the all118 producer record.  F5, for example, must retain the
        # missing/not-scoped state because the calibration selected F2/F4/F6.
        if family in calibration_families:
            old_gaps = [gap for gap in old_gaps if gap != "evidence_missing:all118_label_calibration"]
        gaps = list(old_gaps) + source_gaps
        if family in calibration_families:
            gaps.append("all118_label_calibration_rebound_from_actual_v22_infra_path")
        else:
            gaps.append("all118_label_calibration_not_scoped_to_this_family")
        gaps.extend([
            "anchor_only_one_of_48_cases_semantic_coverage",
            "unknown_control_geometry_recovery_window_kept_in_same_conservative_group",
            "owner_metadata_sha256_is_provenance_only_not_physical_identity",
            "split_safe_false_development_material_only",
        ])
        summaries[family] = {
            "family_id": family,
            "case_count": 48,
            "anchor_case": {
                "current_index": anchor.get("current_index"),
                "physical_case_id": anchor.get("physical_case_id"),
                "runtime_case_alias": anchor.get("runtime_case_alias"),
                "frames": anchor.get("frames"),
                "particles": anchor.get("particles"),
                "actual_time_window_s": anchor.get("actual_time_window_s"),
                "known_numeric_physical_parameters": dict(anchor.get("known_numeric_physical_parameters", {})),
            },
            "assigned_anchor_case_indices": [anchor.get("current_index")],
            "unassigned_case_count": 47,
            "unknown_case_group": {
                "group_id": f"{family}:UNKNOWN_UNASSIGNED_CASES",
                "case_count": 48,
                "status": "UNKNOWN_SAME_GROUP; NOT_SPLIT",
                "dimensions": ["control", "geometry", "recovery", "window", "cross_resolution"],
            },
            "source_roles": source_roles,
            "owner_semantic_observation": owner_semantic,
            "generated_xml_semantic_observation": xml_semantic,
            "semantic_coverage": "ONE_ANCHOR_ONLY; 47_CASES_UNASSIGNED",
            "split_safe": False,
        }
        gaps_by_family[family] = sorted(set(str(gap) for gap in gaps))

    leakage_groups = _leakage_groups(signatures)
    leakage_by_family = {family: [g["group_id"] for g in leakage_groups if family in g.get("families", [])]
                         for family in FAMILIES}

    for family in FAMILIES:
        value: dict[str, Any] = {
            "schema": CARD_SCHEMA,
            "status": "DEVELOPMENT_ONLY; SOURCE_BOUND; QUALIFICATION_UNKNOWN",
            "role": "DEVELOPMENT_EFFECTIVE_PHYSICAL_SOURCE_INDEX",
            "family_id": family, "case_count": 48, "qualification": dict(UNKNOWN),
            "model_invoked": False, "cfd_invoked": False,
            "versioned_from": {
                "v24_card_path": str(Path(old_index["family_cards"][family]["path"])),
                "v24_card_sha256": old_index["family_cards"][family]["embedded_sha256"],
                "v24_index_path": str(old_index_path), "v24_index_sha256": old_index["sha256"],
            },
            "current_binding": dict(old_index.get("current_binding", {})),
            "calibration_evidence": calibration if family in calibration_families else {
                "scope": "not in actual all118 calibration coverage", "qualification": dict(UNKNOWN)
            },
            "effective_physical_split": {
                "split_safe": False,
                "material_status": "DEVELOPMENT_MATERIAL_ONLY",
                "anchor_only": True,
                "assigned_anchor_case_indices": summaries[family]["assigned_anchor_case_indices"],
                "unassigned_case_count": 47,
                "unknown_group": summaries[family]["unknown_case_group"],
                "leakage_group_ids": leakage_by_family[family],
                "source_component_identity": signatures[family],
                "owner_sha256_used_as_identity": False,
                "unknown_dimensions": ["control", "geometry", "recovery", "window", "cross_resolution"],
                "claim_boundary": "No qualification, physical equivalence, or hidden-test safety claim.",
            },
            "raw_anchor": {
                "plan_path": str(plans / f"{family}-raw-anchor-plan-v1.json"),
                "plan_sha256": sha256_file(plans / f"{family}-raw-anchor-plan-v1.json", maximum=MAX_JSON_BYTES),
                **summaries[family],
            },
            "evidence": [calibration] if family in calibration_families else [],
            "gaps": gaps_by_family[family],
            "read_scope": {
                "v24_v22_v23_metadata_opened": True, "owner_json_opened_bounded": True,
                "generated_xml_opened_bounded": True, "small_receipts_opened_bounded": True,
                "calibration_json_hashed_only": True, "hdf5_opened": False,
                "bi4_opened": False, "raw_arrays_opened": False, "jsonl_opened": False,
                "solver_output_opened": False, "trajectory_h5_content_opened": False,
            },
            "rights_and_dependencies": "INHERITED_V24_DEVELOPMENT_ACCESS_ONLY",
        }
        value["sha256"] = canonical_sha(value)
        output = out / f"{family}-family-card-v25-effective-physical-source-proof.json"
        write_new(output, value)
        cards[family] = str(output)

    report: dict[str, Any] = {
        "schema": INDEX_SCHEMA,
        "status": "DEVELOPMENT_EFFECTIVE_PHYSICAL_SOURCE_INDEX_ONLY",
        "role": "DEVELOPMENT",
        "qualification": dict(UNKNOWN), "model_invoked": False, "cfd_invoked": False,
        "versioned_from": {
            "v24_index_path": str(old_index_path), "v24_index_sha256": old_index["sha256"],
            "v22_index_path": str(v22_path), "v23_index_path": str(v23_path),
        },
        "calibration_rebind": calibration,
        "current_binding": dict(old_index.get("current_binding", {})),
        "family_cards": {family: {
            "path": cards[family], "file_sha256": sha256_file(Path(cards[family]), maximum=MAX_JSON_BYTES),
            "embedded_sha256": json.loads(Path(cards[family]).read_text(encoding="utf-8"))["sha256"],
            "case_count": 48, "split_safe": False, "qualification": dict(UNKNOWN),
        } for family in FAMILIES},
        "effective_physical_split": {
            "split_safe": False, "development_material_only": True,
            "anchor_count": 7, "family_count": 7, "cases_per_family": 48,
            "unassigned_cases_per_family": 47, "owner_sha256_not_identity": True,
            "unknown_dimensions_same_group": ["control", "geometry", "recovery", "window", "cross_resolution"],
            "leakage_groups": leakage_groups,
            "family_signatures": signatures,
        },
        "gaps_by_family": gaps_by_family,
        "read_scope": {
            "v24_v22_v23_metadata_opened": True, "v14_plans_opened": True,
            "owner_xml_receipts_bounded": True, "calibration_metadata_hashed": True,
            "hdf5_opened": False, "bi4_opened": False, "raw_arrays_opened": False,
            "jsonl_opened": False, "solver_output_opened": False,
        },
        "limitations": [
            "The actual calibration path is rebound only because its declared and observed SHA/receipt SHA match v22/v23.",
            "A family anchor is one source observation; the other 47 CURRENT cases remain unassigned.",
            "Unknown control, geometry, recovery, and window dimensions remain in one conservative family group.",
            "Owner hashes and lineage IDs are provenance and are excluded from physical identity.",
            "No QI/QN/QE, physical equivalence, portability, or hidden-test safety credit is granted.",
        ],
    }
    report["sha256"] = canonical_sha(report)
    index_output = out / "SEVEN_FAMILY_EFFECTIVE_PHYSICAL_SOURCE_INDEX_V25.json"
    write_new(index_output, report)
    return {"index": str(index_output), "index_sha256": sha256_file(index_output, maximum=MAX_JSON_BYTES),
            "cards": cards, "gaps_by_family": gaps_by_family, "qualification": dict(UNKNOWN)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--v24-index", type=Path)
    parser.add_argument("--v24-cards-dir", type=Path)
    parser.add_argument("--v22-access-index", type=Path)
    parser.add_argument("--v23-access-index", type=Path)
    parser.add_argument("--plans-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build(stage2_root=args.stage2_root, output_dir=args.output_dir,
                       v24_index=args.v24_index, v24_cards_dir=args.v24_cards_dir,
                       v22_access_index=args.v22_access_index,
                       v23_access_index=args.v23_access_index, plans_dir=args.plans_dir)
    except (FamilyCardV25Error, OSError, ValueError) as error:
        print(f"family cards v25: {error}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
