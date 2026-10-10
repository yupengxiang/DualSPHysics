#!/usr/bin/env python3
"""Validate V27 physical-condition unions without granting split safety.

V27 is the source of truth for the physical union key.  This additive audit
checks every one of its 336 records and group rows: resolution, time-window
and recovery remain forbidden cross-split dimensions; all members of a union
have the same geometry/control/initial-state signature; and unknown axes stay
unsafe.  The output is a small metadata audit only and cannot be used as a
qualification or train/test approval.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "effective_conditions_v27_for_v29", SCRIPT_DIR / "ds_data02_stage2_effective_conditions_v27.py")
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("V27 effective-condition source is unavailable")
_V27 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V27)

V27_SCHEMA = _V27.INDEX_SCHEMA
AUDIT_SCHEMA = "ds02.stage2.all336-effective-condition-leakage-audit.v29"
REQUEST_SCHEMA = "ds02.stage2.effective-condition-leakage-audit-request.v29"
MAX_METADATA_BYTES = 8 * 1024 * 1024
FORBIDDEN = ("resolution", "window", "recovery")
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class EffectiveConditionV29Error(ValueError):
    """The physical union index is inconsistent or unsafe to consume."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({key: item for key, item in value.items() if key != "sha256"}).encode()).hexdigest()


def file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_METADATA_BYTES:
        raise EffectiveConditionV29Error(f"invalid bounded V27 metadata path: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_index(path: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path).expanduser()
    digest = file_sha(target)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EffectiveConditionV29Error(f"cannot read V27 index: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != V27_SCHEMA:
        raise EffectiveConditionV29Error("input is not the V27 physical union index")
    if value.get("sha256") != canonical_sha(value):
        raise EffectiveConditionV29Error("V27 canonical SHA mismatch")
    cases = value.get("cases")
    groups = value.get("physical_union_groups")
    if not isinstance(cases, list) or len(cases) != 336 or not isinstance(groups, list):
        raise EffectiveConditionV29Error("V27 index lacks all 336 cases/groups")
    return value, {"path": str(target.resolve()), "file_sha256": digest,
                   "bytes": target.stat().st_size, "mtime_ns": target.stat().st_mtime_ns,
                   "ctime_ns": target.stat().st_ctime_ns, "st_dev": target.stat().st_dev,
                   "st_ino": target.stat().st_ino, "role": "V27 physical union index",
                   "content_policy": "bounded metadata only"}


def _axis_signature(axes: Any) -> str:
    if not isinstance(axes, Mapping):
        raise EffectiveConditionV29Error("physical_union_axes is missing")
    cleaned = {}
    for axis in ("geometry", "control", "initial_state"):
        value = axes.get(axis)
        if not isinstance(value, Mapping):
            raise EffectiveConditionV29Error(f"physical axis {axis} is missing")
        cleaned[axis] = value
    return canonical(cleaned)


def validate_index(index: Mapping[str, Any]) -> dict[str, Any]:
    cases = index.get("cases")
    groups = index.get("physical_union_groups")
    if not isinstance(cases, list) or len(cases) != 336 or not isinstance(groups, list):
        raise EffectiveConditionV29Error("V27 index does not contain 336 cases/groups")
    by_group: dict[str, list[Mapping[str, Any]]] = {}
    ids: set[str] = set()
    for item in cases:
        if not isinstance(item, Mapping):
            raise EffectiveConditionV29Error("V27 case row is not an object")
        case_id = item.get("physical_case_id")
        group_id = item.get("physical_union_group_id_v27")
        if not isinstance(case_id, str) or case_id in ids or not isinstance(group_id, str):
            raise EffectiveConditionV29Error("V27 case identity/group is missing or duplicated")
        ids.add(case_id)
        forbidden = item.get("forbidden_cross_split_dimensions")
        if not isinstance(forbidden, list) or any(axis not in forbidden for axis in FORBIDDEN):
            raise EffectiveConditionV29Error(f"{case_id} does not retain all forbidden split dimensions")
        if item.get("split_safe") is True:
            raise EffectiveConditionV29Error(f"{case_id} was incorrectly marked split_safe")
        by_group.setdefault(group_id, []).append(item)
    declared_groups: dict[str, Mapping[str, Any]] = {}
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("group_id"), str):
            raise EffectiveConditionV29Error("V27 physical group is malformed")
        group_id = str(group["group_id"])
        if group_id in declared_groups:
            raise EffectiveConditionV29Error(f"duplicate physical group {group_id}")
        declared_groups[group_id] = group
        if group.get("split_safe") is True:
            raise EffectiveConditionV29Error(f"physical group {group_id} was incorrectly marked split_safe")
        forbidden = group.get("forbidden_cross_split_dimensions")
        if not isinstance(forbidden, list) or any(axis not in forbidden for axis in FORBIDDEN):
            raise EffectiveConditionV29Error(f"physical group {group_id} loses a forbidden split dimension")
        members = by_group.get(group_id, [])
        declared_indices = group.get("current_indices")
        actual_indices = sorted(int(row.get("current_index", -1)) for row in members)
        if not isinstance(declared_indices, list) or sorted(declared_indices) != actual_indices:
            raise EffectiveConditionV29Error(f"physical group {group_id} member indices differ")
        signatures = {_axis_signature(row.get("physical_union_axes")) for row in members}
        if len(signatures) != 1:
            raise EffectiveConditionV29Error(f"physical group {group_id} combines different physical axes")
        declared_axes = group.get("physical_axes")
        if _axis_signature(declared_axes) != next(iter(signatures)):
            raise EffectiveConditionV29Error(f"physical group {group_id} declared axes differ from members")
    if set(by_group) != set(declared_groups):
        raise EffectiveConditionV29Error("V27 case/group membership is not closed")
    unknown_cases = sum(row.get("physical_union_status") == "UNKNOWN_PHYSICAL_UNASSIGNED" for row in cases)
    return {"case_count": len(cases), "physical_union_group_count": len(groups),
            "unknown_physical_case_count": unknown_cases,
            "unsafe_group_count": sum(group.get("split_safe") is False for group in groups),
            "forbidden_cross_split_dimensions": list(FORBIDDEN),
            "same_physical_union_across_resolution_window_recovery": True,
            "split_safe": False, "qualification": dict(UNKNOWN)}


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise EffectiveConditionV29Error(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_leakage_audit(*, v27_index: Path | str, output_dir: Path | str,
                        request_id: str = "ds02-effective-condition-leakage-v29-001") -> dict[str, Any]:
    index, source = read_index(v27_index)
    summary = validate_index(index)
    out = Path(output_dir).expanduser().resolve()
    if out.exists() and any(out.iterdir()):
        raise EffectiveConditionV29Error(f"V29 output must be a fresh directory: {out}")
    audit = {
        "schema": AUDIT_SCHEMA, "status": "DEVELOPMENT_LEAKAGE_AUDIT_ONLY",
        "source_index": source, "summary": summary,
        "policy": {"upper_boundary": "physical union", "diagnostic_subgroups": list(FORBIDDEN),
                    "owner_sha_is_provenance_only": True, "unknown_axes_unassigned": True,
                    "qualification_credit": "NONE", "hidden_test_safety": False},
    }
    audit["sha256"] = canonical_sha(audit)
    out.mkdir(parents=True, exist_ok=True)
    audit_path = out / "effective-condition-leakage-audit-v29.json"
    _write_new(audit_path, audit)
    request = {
        "schema": REQUEST_SCHEMA, "status": "READY_FOR_METADATA_ONLY_PARENT_GUARD",
        "request_id": request_id, "source_index": source,
        "output": {"path": str(audit_path), "sha256": audit["sha256"]},
        "execution": {"cpu_threads": 1, "max_wall_seconds": 900, "memory_max_bytes": 512 * 1024 * 1024,
                       "hdf5_opened": False, "bi4_opened": False, "raw_arrays_opened": False,
                       "original_path_fallback": "REJECT"},
        "qualification": dict(UNKNOWN), "split_safe": False,
    }
    request["sha256"] = canonical_sha(request)
    request_path = out / "effective-condition-leakage-request-v29.json"
    _write_new(request_path, request)
    return {"audit": str(audit_path), "audit_sha256": audit["sha256"],
            "request": str(request_path), "request_sha256": request["sha256"], **summary}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v27-index", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--request-id", default="ds02-effective-condition-leakage-v29-001")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build_leakage_audit(v27_index=args.v27_index, output_dir=args.output_dir,
                                             request_id=args.request_id), indent=2, sort_keys=True))
        return 0
    except (EffectiveConditionV29Error, OSError, ValueError, KeyError) as error:
        print(f"effective conditions v29: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
