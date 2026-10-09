#!/usr/bin/env python3
"""Build a conservative physical-condition union index from V26 metadata.

V26's effective subgroup key contains resolution, time-window and recovery
lineage observations.  Those dimensions are useful diagnostics, but using
them as the top-level split boundary can leak the same physical condition
across development partitions.  V27 keeps the V26 subgroup as detail and
adds a family-scoped physical union keyed only by geometry, control and
initial-state observations.  Every union remains development material with
``split_safe=false``; unknown physical axes stay conservative and are never
promoted.

This forward transform consumes only the bounded V26 JSON index.  It does not
open H5, BI4, raw arrays, JSONL or solver output, and never mutates V26 files.
The caller must provide a fresh output directory for the new request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


V26_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v26"
INDEX_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v27"
REQUEST_SCHEMA = "ds02.stage2.effective-condition-metadata-request.v27"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_INDEX_BYTES = 8 * 1024 * 1024
PHYSICAL_AXES = ("geometry", "control", "initial_state")
SUBGROUP_AXES = ("resolution", "window", "recovery")


class EffectiveConditionV27Error(ValueError):
    """Malformed V26 input or an unsafe output collision."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({key: item for key, item in value.items()
                                     if key != "sha256"}).encode()).hexdigest()


def sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise EffectiveConditionV27Error(f"expected regular metadata file: {path}")
    if path.stat().st_size > MAX_INDEX_BYTES:
        raise EffectiveConditionV27Error(f"V26 index exceeds bounded size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_index(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INDEX_BYTES:
        raise EffectiveConditionV27Error(f"invalid V26 index path: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EffectiveConditionV27Error(f"cannot read V26 index: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != V26_SCHEMA:
        raise EffectiveConditionV27Error("input is not the immutable V26 effective-condition index")
    if value.get("sha256") != canonical_sha(value):
        raise EffectiveConditionV27Error("V26 index canonical SHA mismatch")
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise EffectiveConditionV27Error("V26 index must contain exactly 336 cases")
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping) or int(case.get("current_index", -1)) != index:
            raise EffectiveConditionV27Error(f"V26 case order/index mismatch at {index}")
        if case.get("case_sha256") is None:
            raise EffectiveConditionV27Error(f"V26 case lacks immutable SHA at {index}")
        if not isinstance(case.get("case_path"), str):
            raise EffectiveConditionV27Error(f"V26 case lacks bounded detail path at {index}")
    return value


def read_case_detail(path: Path, expected_sha: str, expected_index: int) -> tuple[dict[str, Any], str]:
    """Read one V26 case record; this is metadata, never a payload role."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise EffectiveConditionV27Error(f"invalid bounded V26 case detail: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EffectiveConditionV27Error(f"cannot read V26 case detail {path}: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != "ds02.stage2.effective-condition-case.v26":
        raise EffectiveConditionV27Error(f"unexpected V26 case schema: {path}")
    if int(value.get("current_index", -1)) != expected_index:
        raise EffectiveConditionV27Error(f"V26 case detail index mismatch: {path}")
    if value.get("sha256") != canonical_sha(value) or value.get("sha256") != expected_sha:
        raise EffectiveConditionV27Error(f"V26 case detail SHA mismatch: {path}")
    return value, sha256_file(path)


def _axis_value(case: Mapping[str, Any], axis: str) -> Mapping[str, Any]:
    condition = case.get("effective_condition")
    if isinstance(condition, Mapping):
        axes = condition.get("axes")
        if isinstance(axes, Mapping) and isinstance(axes.get(axis), Mapping):
            return axes[axis]
    # V26's case directory stores only the compact index row.  Missing axes
    # therefore remain explicit unknowns rather than inferred from names.
    return {"status": "UNKNOWN_UNASSIGNED", "key": None, "reason": "axis_missing"}


def _physical_payload(value: Any) -> Any:
    """Remove observations that V26 intentionally assigns to subgroups.

    V26 embeds generated XML attributes in the geometry/control payloads.
    Those attributes contain ``dp`` and time/control declarations, so using
    the V26 axis digest verbatim would still split a physical condition by
    resolution.  Geometry/control declarations that are not XML observations
    remain part of the physical key; missing declarations remain unknown.
    """
    if isinstance(value, Mapping):
        return {
            str(key): cleaned
            for key, item in value.items()
            if str(key) != "generated_xml_condition_attributes"
            and (cleaned := _physical_payload(item)) is not None
        }
    if isinstance(value, list):
        return [_physical_payload(item) for item in value]
    return value


def _physical_key(case: Mapping[str, Any]) -> tuple[str, bool, dict[str, Any]]:
    family = str(case.get("family_id", "UNKNOWN_FAMILY"))
    axes: dict[str, Any] = {}
    unknown: list[str] = []
    for axis in PHYSICAL_AXES:
        value = _axis_value(case, axis)
        status = str(value.get("status", "UNKNOWN_UNASSIGNED"))
        payload = _physical_payload(value.get("payload"))
        if not isinstance(payload, Mapping) or not payload or status.startswith("UNKNOWN"):
            unknown.append(axis)
            axes[axis] = {"status": "UNKNOWN", "key": None}
        else:
            key = hashlib.sha256(canonical(payload).encode()).hexdigest()
            axes[axis] = {"status": status, "key": key, "payload": payload}
    payload = {"family_id": family, "physical_axes": axes}
    if unknown:
        payload["unknown_physical_axes"] = sorted(unknown)
    digest = hashlib.sha256(canonical(payload).encode()).hexdigest()[:20]
    prefix = f"{family}:PHYSICAL_UNKNOWN" if unknown else f"{family}:PHYSICAL_UNION"
    return f"{prefix}:{digest}", bool(unknown), payload


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise EffectiveConditionV27Error(f"refusing to overwrite V27 output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                    encoding="utf-8")


def build_from_index(*, v26_index: Path | str, output_dir: Path | str,
                     request_id: str = "ds02-effective-condition-all336-v27-metadata-primary-001") -> dict[str, Any]:
    source = Path(v26_index).expanduser().resolve()
    out = Path(output_dir).expanduser().resolve()
    index = read_index(source)
    if out.exists() and any(out.iterdir()):
        raise EffectiveConditionV27Error(
            f"output directory must be a fresh namespace with no existing artifacts: {out}")

    cases_out: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    subgroup_groups: dict[str, list[int]] = {}
    case_inputs: list[dict[str, Any]] = []
    for raw in index["cases"]:
        compact = dict(raw)
        current_index = int(compact["current_index"])
        case, case_file_sha = read_case_detail(
            Path(str(compact["case_path"])).expanduser().resolve(),
            str(compact["case_sha256"]), current_index)
        case_inputs.append({
            "path": str(Path(str(compact["case_path"])).expanduser().resolve()),
            "sha256": compact["case_sha256"],
            "file_sha256": case_file_sha,
            "bytes": Path(str(compact["case_path"])).expanduser().stat().st_size,
            "content_role": "bounded V26 case metadata; no payload arrays",
        })
        physical_id, unknown, physical_payload = _physical_key(case)
        condition = case.get("effective_condition")
        subgroup_id = str(condition.get("group_id")) if isinstance(condition, Mapping) else str(compact.get("group_id"))
        subgroup_groups.setdefault(subgroup_id, []).append(current_index)
        record = {
            "current_index": current_index,
            "family_id": case.get("family_id"),
            "physical_case_id": case.get("physical_case_id"),
            "runtime_case_alias": case.get("runtime_case_alias"),
            "subgroup_id_v26": subgroup_id,
            "physical_union_group_id_v27": physical_id,
            "physical_union_status": "UNKNOWN_PHYSICAL_UNASSIGNED" if unknown else "SOURCE_BOUND_PHYSICAL_UNION",
            "physical_union_axes": physical_payload["physical_axes"],
            "forbidden_cross_split_dimensions": list(SUBGROUP_AXES),
            "source_case_sha256_v26": compact.get("case_sha256"),
            "gaps": sorted(set(case.get("gaps", [])) | ({"physical_axis_unknown"} if unknown else set())),
        }
        cases_out.append(record)
        group = groups.setdefault(physical_id, {
            "group_id": physical_id,
            "current_indices": [],
            "families": [],
            "status": record["physical_union_status"],
            "split_safe": False,
            "claim_boundary": "development material only; physical union forbids cross-split leakage; no qualification or hidden-test safety",
            "physical_axes": physical_payload["physical_axes"],
            "forbidden_cross_split_dimensions": list(SUBGROUP_AXES),
            "subgroup_ids_v26": [],
        })
        group["current_indices"].append(current_index)
        if case.get("family_id") not in group["families"]:
            group["families"].append(case.get("family_id"))
        if subgroup_id not in group["subgroup_ids_v26"]:
            group["subgroup_ids_v26"].append(subgroup_id)

    for group in groups.values():
        group["current_indices"].sort()
        group["families"].sort()
        group["subgroup_ids_v26"].sort()
    subgroup_records = [
        {
            "subgroup_id_v26": subgroup_id,
            "current_indices": sorted(indices),
            "physical_union_group_ids_v27": sorted({cases_out[i]["physical_union_group_id_v27"] for i in indices}),
            "split_safe": False,
            "claim_boundary": "V26 resolution/window/recovery detail only; cannot define a split boundary",
        }
        for subgroup_id, indices in sorted(subgroup_groups.items())
    ]

    out_index: dict[str, Any] = {
        "schema": INDEX_SCHEMA,
        "status": "DEVELOPMENT_ALL336_PHYSICAL_UNION_SOURCE_INDEX_ONLY",
        "role": "DEVELOPMENT_PHYSICAL_UNION_AND_SUBGROUP_DIRECTORY",
        "qualification": dict(UNKNOWN),
        "model_invoked": False,
        "cfd_invoked": False,
        "versioned_from": {
            "v26_index_path": str(source),
            "v26_index_sha256": index["sha256"],
            "v26_index_file_sha256": sha256_file(source),
        },
        "coverage": {"all336_identities": True, "case_count": 336,
                     "family_counts": {f"F{i}": 48 for i in range(1, 8)},
                     "physical_union_groups": len(groups),
                     "v26_subgroups": len(subgroup_records)},
        "cases": cases_out,
        "physical_union_groups": [groups[key] for key in sorted(groups)],
        "v26_effective_subgroups": subgroup_records,
        "leakage_policy": {
            "physical_union_is_upper_boundary": True,
            "same_physics_across_resolution_window_recovery_stays_together": True,
            "resolution_window_recovery_are_diagnostic_subgroups_only": True,
            "owner_sha_is_provenance_only": True,
            "unknown_axes_remain_unassigned": True,
            "split_safe": False,
        },
        "read_scope": {
            "v26_index_metadata_opened": True,
            "hdf5_opened": False, "bi4_opened": False, "raw_arrays_opened": False,
            "jsonl_opened": False, "solver_output_opened": False,
        },
        "limitations": [
            "Physical union uses only V26 geometry/control/initial-state metadata keys.",
            "Resolution, window and recovery lineage remain detailed subgroup observations.",
            "Unknown physical axes stay in explicit unsafe groups and are never promoted.",
            "No QI/QN/QE, physical equivalence, train/test split, or hidden-test safety claim.",
        ],
    }
    out_index["sha256"] = canonical_sha(out_index)
    index_path = out / "EFFECTIVE_PHYSICAL_UNION_INDEX_V27.json"
    _write_new(index_path, out_index)

    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_METADATA_ONLY_PARENT_GUARD",
        "request_id": request_id,
        "mode": "V26_INDEX_TRANSFORM_ONLY; NO_PAYLOAD_READ",
        "execution": {
            "python": "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            "argv": ["-B", "-I", str(Path(__file__).resolve()), "--v26-index", str(source),
                     "--output-dir", str(out)],
            "cpu_threads": 1, "max_wall_seconds": 900,
            "memory_max_bytes": 512 * 1024 * 1024,
            "parent_guard_required": True,
        },
        "source_inputs": {
            "v26_index": {"path": str(source), "sha256": index["sha256"],
                          "file_sha256": sha256_file(source),
                          "content_role": "bounded V26 metadata only"},
            "v26_case_details": case_inputs,
        },
        "outputs": {"index": str(index_path), "index_sha256": out_index["sha256"],
                    "physical_union_groups": len(groups), "case_count": 336},
        "read_policy": {"hdf5": "FORBID", "bi4": "FORBID", "raw_arrays": "FORBID",
                         "jsonl": "FORBID", "solver_output": "FORBID",
                         "v26_index": "BOUNDED_METADATA_ONLY", "original_path_fallback": "REJECT"},
        "qualification": dict(UNKNOWN), "model_invoked": False, "cfd_invoked": False,
    }
    request["sha256"] = canonical_sha(request)
    request_path = out / "effective-condition-metadata-request-v27.json"
    _write_new(request_path, request)
    return {"index": str(index_path), "index_sha256": out_index["sha256"],
            "request": str(request_path), "request_sha256": request["sha256"],
            "case_count": len(cases_out), "physical_union_group_count": len(groups),
            "v26_subgroup_count": len(subgroup_records), "qualification": dict(UNKNOWN)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v26-index", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--request-id", default="ds02-effective-condition-all336-v27-metadata-primary-001")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print(json.dumps(build_from_index(v26_index=args.v26_index, output_dir=args.output_dir,
                                           request_id=args.request_id), indent=2, sort_keys=True))
        return 0
    except (EffectiveConditionV27Error, OSError, ValueError, KeyError) as error:
        print(f"effective conditions v27: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
