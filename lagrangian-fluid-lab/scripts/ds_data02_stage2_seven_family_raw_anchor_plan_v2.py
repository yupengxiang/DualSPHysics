#!/usr/bin/env python3
"""Build an alias-safe seven-family raw-anchor metadata plan.

The older family planner selected the historical F2 row 78.  This additive
planner selects the current canonical F2 row 65 explicitly and records the
other six family anchors from CURRENT336 without opening native payloads.  It
separates small declared source hashes/stat from deferred raw-tree/HDF5
content hashes.  The output is a parent-guard input description only: every
family remains DEVELOPMENT/UNKNOWN and no raw reconstruction credit is
created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
FAMILIES = tuple(f"F{index}" for index in range(1, 8))
F2_CANONICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX047_RY014_FILL080_ROT075"
F2_HISTORICAL_ALIAS = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SCHEMA = "ds02.stage2.seven-family-raw-anchor-plan.v2"
INDEX_SCHEMA = "ds02.stage2.seven-family-raw-anchor-plan-index.v2"
PENDING = "PENDING_PARENT_GUARD_CONTENT_SHA256"


class SevenFamilyAnchorError(ValueError):
    """Raised when CURRENT or a source-only anchor binding is unsafe."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _load(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SevenFamilyAnchorError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise SevenFamilyAnchorError(f"{role} must be a JSON object")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise SevenFamilyAnchorError(f"refusing existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _stat_only(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
    except OSError:
        return None
    return {"bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "mode_bits": int(stat.st_mode & 0o777), "content_read": False}


def _declared_ref(value: Any, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        return {"role": role, "path": None, "declared_sha256": None,
                "status": "UNKNOWN_NOT_BOUND", "content_read": False}
    declared = value.get("sha256", value.get("recomputed_sha256"))
    if declared is not None and (not isinstance(declared, str) or len(declared) != 64):
        raise SevenFamilyAnchorError(f"{role} has malformed declared SHA")
    path = Path(str(value["path"])).expanduser()
    return {
        "role": role,
        "path_provenance": str(path),
        "declared_sha256": declared,
        "declared_bytes": value.get("bytes"),
        "source_stat": _stat_only(path),
        "content_read": False,
        "status": "DECLARED_SOURCE_HASH" if declared else "PATH_ONLY_PENDING_SOURCE_HASH",
    }


def _choose(rows: list[tuple[int, Mapping[str, Any]]], family: str) -> tuple[int, Mapping[str, Any]]:
    if family == "F2":
        exact = [(index, row) for index, row in rows
                 if row.get("physical_case_id") == F2_CANONICAL_CASE]
        if len(exact) != 1:
            raise SevenFamilyAnchorError("CURRENT must contain exactly one canonical F2 row 65")
        index, row = exact[0]
        if index != 65:
            raise SevenFamilyAnchorError(f"canonical F2 row moved from frozen index 65 to {index}")
        return index, row
    # The six non-F2 selections are deterministic first rows in CURRENT order.
    # They remain pending until their own family-specific raw/source closure.
    return rows[0]


def _raw_metadata(row: Mapping[str, Any], family: str) -> dict[str, Any]:
    raw = row.get("raw_root") if isinstance(row.get("raw_root"), Mapping) else {}
    root = Path(str(raw.get("path", ""))).expanduser()
    names: list[str] = []
    if root.is_dir():
        try:
            names = sorted(item.name for item in root.iterdir() if not item.is_symlink())
        except OSError:
            names = []
    trajectory = row.get("trajectory") if isinstance(row.get("trajectory"), Mapping) else {}
    return {
        "raw_root_provenance": str(root) if str(root) else None,
        "raw_root_exists": root.is_dir(),
        "observed_entry_count_stat_only": len(names) if root.is_dir() else None,
        "observed_entry_names_sha256": hashlib.sha256("\n".join(names).encode()).hexdigest() if names else None,
        "frame_pattern": "Part_%04d.bi4",
        "frame_count_expected": row.get("frames"),
        "raw_tree_sha256": PENDING,
        "per_frame_content_sha256": PENDING,
        "trajectory_h5": {
            "path_provenance": trajectory.get("path"),
            "producer_declared_sha256": trajectory.get("producer_declared_sha256"),
            "bytes": trajectory.get("bytes"),
            "content_sha256": PENDING,
            "content_read": False,
        },
        "content_hash_phase": "AFTER_PARENT_RESERVATION",
        "unknown_scope": [
            "raw tree and frame bytes pending parent guard",
            "typed arrays/labels and physical owner/fate/dynamics pending",
            f"{family} family-specific source/receipt closure pending",
        ],
    }


def _family_plan(*, family: str, index: int, row: Mapping[str, Any], current_path: Path,
                 repo_root: Path, card_dir: Path) -> dict[str, Any]:
    bindings = row.get("source_bindings") if isinstance(row.get("source_bindings"), Mapping) else {}
    small = [_declared_ref({"path": str(current_path), "sha256": CURRENT_SHA}, "current_catalog")]
    for role in ("manifest", "xmf", "conversion_report", "generated_xml", "gencase_receipt",
                 "solver_receipt", "owner_metadata"):
        value = row.get(role) if role in row else bindings.get(role)
        small.append(_declared_ref(value, role))
    raw = _raw_metadata(row, family)
    case_id = row.get("physical_case_id")
    return {
        "schema": SCHEMA,
        "status": "CANONICAL_SELECTION_READY_PENDING_PARENT_GUARD" if family == "F2" else "PLAN_ONLY_FAMILY_PENDING_PARENT_GUARD",
        "family_id": family,
        "anchor_case": {
            "current_index": index, "physical_case_id": case_id,
            "runtime_case_alias": row.get("runtime_case_alias"),
            "frames": row.get("frames"), "particles": row.get("particles"),
            "actual_time_window_s": row.get("actual_time_window_s"),
            "identity_status": "CANONICAL_CURRENT_ROW" if family == "F2" else "CURRENT_ROW_NOT_PHYSICAL_EQUIVALENCE_PROOF",
        },
        "selection_policy": {
            "current_catalog_sha256": CURRENT_SHA,
            "predicate": "exact CURRENT row; F2 canonical physical_case_id; no latest glob",
            "historical_alias_rejected": family == "F2",
            "hidden_test": False, "qualification": UNKNOWN,
        },
        "source_bindings": small,
        "raw_anchor": raw,
        "copy_roles": {
            "source_inputs": [
                {"role": "current_catalog", "target_relative_path": f"source/{family}/CURRENT336.json"},
                {"role": "generated_xml", "target_relative_path": f"source/{family}/generated.xml"},
                {"role": "solver_receipt", "target_relative_path": f"source/{family}/solver-receipt.json"},
                {"role": "owner_metadata", "target_relative_path": f"source/{family}/owner.json"},
            ],
            "raw_payload": "raw root is an explicit parent-guard input; content is not copied by this planner",
            "target_namespace_policy": "fresh attempt root only; old roots and latest fallback forbidden",
        },
        "typed_comparison_contract": {
            "identity_key": "(Zone,Idp)",
            "required_fields": ["position", "velocity", "density", "mass", "valid", "type", "mk"],
            "raw_hash_passes": 2, "frame_content_hashes": int(row.get("frames") or 0),
            "streaming_particle_chunk": 65536,
            "labels_after_typed_compare": True,
            "quality": UNKNOWN,
        },
        "code_closure": {
            "repo_root_provenance": str(repo_root),
            "literal_pinned_interpreter": "parent must bind literal venv and pyvenv.cfg",
            "runtime_imports": "parent records loaded module paths/SHA; no worktree fallback",
            "source_content_read": False,
        },
        "family_card": {
            "path_provenance": str(card_dir / f"{family}-family-card-v13.json"),
            "status": "DEVELOPMENT_METADATA_ONLY; card is not rewritten",
        },
        "qualification": UNKNOWN,
        "model_invoked": False, "cfd_invoked": False,
    }


def build(*, current: Path, repo_root: Path, card_dir: Path, output_dir: Path) -> dict[str, Any]:
    current = current.expanduser().resolve()
    if not current.is_file() or sha256_file(current) != CURRENT_SHA:
        raise SevenFamilyAnchorError("CURRENT336 must match the frozen source SHA")
    document = _load(current, "CURRENT336")
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise SevenFamilyAnchorError("CURRENT336 must contain 336 cases")
    grouped: dict[str, list[tuple[int, Mapping[str, Any]]]] = {family: [] for family in FAMILIES}
    for index, row in enumerate(cases):
        if isinstance(row, Mapping) and row.get("family_id") in grouped:
            grouped[str(row["family_id"])].append((index, row))
    if any(len(grouped[family]) != 48 for family in FAMILIES):
        raise SevenFamilyAnchorError("each family must contain 48 CURRENT rows")
    plans: list[dict[str, Any]] = []
    for family in FAMILIES:
        index, row = _choose(grouped[family], family)
        plan = _family_plan(family=family, index=index, row=row, current_path=current,
                            repo_root=repo_root.expanduser().resolve(), card_dir=card_dir.expanduser().resolve())
        plan["sha256"] = canonical_sha(plan)
        plans.append(plan)
    result: dict[str, Any] = {
        "schema": INDEX_SCHEMA,
        "status": "SEVEN_FAMILY_CANONICAL_METADATA_PLAN; NO_RAW_CONTENT_READ",
        "current_catalog": {"path_provenance": str(current), "sha256": CURRENT_SHA, "case_count": 336},
        "families": plans,
        "alias_policy": {
            "F2_historical_alias_case_id": F2_HISTORICAL_ALIAS,
            "F2_historical_alias_index": 78,
            "F2_alias_selection": "REJECT",
            "selected_F2_index": 65,
        },
        "execution_boundary": {
            "raw_content_read": False, "typed_arrays_read": False, "hdf5_read": False,
            "parent_reservation_required": True, "source_prepost_required": True,
            "completed_raw_reconstructions": 0, "qualification": UNKNOWN,
        },
        "limitations": [
            "This is a seven-family source-only plan, not a raw reconstruction or typed comparison.",
            "Raw tree/frame/HDF5 bytes are deferred to the same-parent guard and are never inferred from stat/name presence.",
            "Physical equivalence, split safety, event/material labels and QI/QN/QE remain UNKNOWN.",
        ],
    }
    result["sha256"] = canonical_sha(result)
    _write_new(output_dir.expanduser().resolve() / "seven-family-raw-anchor-plan-v2.json", result)
    return result


def validate(path: Path) -> dict[str, Any]:
    value = _load(path, "seven-family plan")
    if value.get("schema") != INDEX_SCHEMA or value.get("sha256") != canonical_sha(value):
        raise SevenFamilyAnchorError("plan schema/canonical SHA differs")
    rows = value.get("families")
    if not isinstance(rows, list) or [row.get("family_id") for row in rows] != list(FAMILIES):
        raise SevenFamilyAnchorError("plan does not contain ordered F1..F7 rows")
    selected = {row["family_id"]: row["anchor_case"] for row in rows}
    f2 = selected["F2"]
    if f2.get("current_index") != 65 or f2.get("physical_case_id") != F2_CANONICAL_CASE:
        raise SevenFamilyAnchorError("F2 canonical row/identity is wrong")
    if value.get("alias_policy", {}).get("F2_alias_selection") != "REJECT":
        raise SevenFamilyAnchorError("historical alias policy is not strict")
    for row in rows:
        if row.get("qualification") != UNKNOWN:
            raise SevenFamilyAnchorError(f"{row.get('family_id')} qualification was promoted")
        raw = row.get("raw_anchor", {})
        if raw.get("raw_tree_sha256") != PENDING or raw.get("per_frame_content_sha256") != PENDING:
            raise SevenFamilyAnchorError(f"{row.get('family_id')} invented raw content hash")
        if row.get("model_invoked") is not False or row.get("cfd_invoked") is not False:
            raise SevenFamilyAnchorError(f"{row.get('family_id')} model/CFD boundary is unsafe")
    return {"status": "VALIDATED_SEVEN_FAMILY_SOURCE_ONLY_PLAN", "families": 7,
            "selected_F2_index": 65, "qualification": UNKNOWN,
            "plan_sha256": value["sha256"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build")
    build_cmd.add_argument("--current", type=Path, required=True)
    build_cmd.add_argument("--repo-root", type=Path, required=True)
    build_cmd.add_argument("--card-dir", type=Path, required=True)
    build_cmd.add_argument("--output-dir", type=Path, required=True)
    validate_cmd = sub.add_parser("validate")
    validate_cmd.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            value = build(current=args.current, repo_root=args.repo_root,
                          card_dir=args.card_dir, output_dir=args.output_dir)
            print(json.dumps({"status": value["status"], "sha256": value["sha256"],
                              "families": len(value["families"])}, sort_keys=True))
        else:
            print(json.dumps(validate(args.plan), sort_keys=True))
    except (SevenFamilyAnchorError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
