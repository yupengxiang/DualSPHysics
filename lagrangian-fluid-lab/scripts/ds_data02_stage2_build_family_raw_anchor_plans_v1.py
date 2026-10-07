#!/usr/bin/env python3
"""Build conservative, CURRENT-bound raw-anchor plans for all seven families.

This is a metadata-only planner.  It reads CURRENT336 and the already
versioned family cards, records the exact raw-root/typed-producer/source
bindings for one deterministic anchor per family, and emits seven plans plus
one index.  It never opens HDF5, BI4, PartOut, RunPARTs, or solver output
content.  A plan is a guard-ready input description; it is not evidence that
the raw converter has run or that any qualification is earned.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "ds02.stage2.family-raw-anchor-plan.v1"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7")
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"


class RawAnchorPlanError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RawAnchorPlanError(f"JSON object required: {path}")
    return value


def _file_ref(value: Mapping[str, Any] | None, role: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        return {"role": role, "path": None, "sha256": None, "status": "UNKNOWN_NOT_BOUND"}
    path = Path(str(value["path"])).expanduser()
    declared = value.get("sha256", value.get("recomputed_sha256"))
    return {
        "role": role,
        "path": str(path),
        "sha256": declared if isinstance(declared, str) else None,
        "bytes": value.get("bytes"),
        "mtime_ns": value.get("mtime_ns"),
        "path_exists": path.is_file(),
        "status": "SOURCE_PATH_BOUND" if path.is_file() else "SOURCE_PATH_MISSING_OR_UNAVAILABLE",
    }


def _select_anchor(rows: list[tuple[int, Mapping[str, Any]]], family: str) -> tuple[int, Mapping[str, Any]]:
    if family == "F2":
        # This is the exact source-bound F2-S1 case already covered by the
        # v2/v4 raw-to-typed reference request.  Selection is by identity,
        # never by latest glob or directory order.
        for index, row in rows:
            if row.get("physical_case_id") == "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090":
                return index, row
    if family == "F6":
        # Prefer a row whose raw directory advertises the native floating
        # telemetry header.  Orientation remains UNKNOWN until its encoding
        # is independently decoded.
        for index, row in rows:
            raw = row.get("raw_root", {})
            path = Path(str(raw.get("path", "")))
            if path.is_dir() and (path / "PartFloatInfo.ibi4").is_file():
                return index, row
    return rows[0]


def _common_closure(repo_root: Path) -> dict[str, Any]:
    scripts = repo_root / "lagrangian-fluid-lab" / "scripts"
    native = scripts / "native" / "bi4_dump.cpp"
    entries = []
    for role, path in (
        ("raw_converter", scripts / "ds_data02_f5_bi4.py"),
        ("native_decoder_source", native),
        ("v15_operator", scripts / "ds_data02_stage2_f2_replay_v15.py"),
        ("v16_operator", scripts / "ds_data02_stage2_f2_flux_v16.py"),
    ):
        entries.append({
            "role": role,
            "path": str(path),
            "sha256": sha256_file(path) if path.is_file() else None,
            "status": "CONTENT_SHA_BOUND" if path.is_file() else "SOURCE_MISSING",
        })
    v4_closure = repo_root / "lagrangian-fluid-lab" / "campaigns" / "ds-data-02" / "stage2" / "native-reconstruction" / "v4" / "f2-s1-native-typed-import-closure-v4-001.json"
    return {
        "common_source_modules": entries,
        "native_decoder_policy": "Part_*.bi4 source arrays are required; PartOut/RunPARTs are provenance only",
        "installed_library_closure": "parent guard must record all loaded __file__ paths and SHA before raw execution",
        "f2_v4_import_closure": {
            "path": str(v4_closure),
            "sha256": sha256_file(v4_closure) if v4_closure.is_file() else None,
            "status": "BOUND_258_PATHS" if v4_closure.is_file() else "PENDING",
        },
    }


def _family_unknowns(family: str) -> list[str]:
    common = [
        "raw-to-typed execution and per-frame comparison are pending parent guard",
        "HDF5 content SHA is producer/parent-guard evidence; this plan does not reread HDF5",
        "recovery/restart equivalence, cross-resolution transfer, and prospective split safety remain UNKNOWN",
        "no QI/QN/QE or hidden-test status is granted",
    ]
    specific = {
        "F1": ["receiver/opening equivalence and physical fate are not inferred from raw files"],
        "F2": ["v4 exact F2-S1 anchor is ready for parent raw/typed guard; receiver labels remain DEVELOPMENT"],
        "F3": ["four solver source-hash closures remain incomplete in the existing audit; each case needs receipt/output binding"],
        "F4": ["GenCase finish support and output closure remain UNKNOWN for the affected legacy cases"],
        "F5": ["actual motion/control and exact solver-output Run.out binding require per-case receipt audit"],
        "F6": ["PartFloatInfo exists on the selected anchor, but orientation encoding and rigid mass/pose credit remain UNKNOWN"],
        "F7": ["quintic control/source-definition equivalence is observed only as provenance; raw typed comparison is pending"],
    }
    return common + specific[family]


def build_plans(current_path: Path, cards_dir: Path, output_dir: Path,
                repo_root: Path) -> dict[str, Any]:
    current = _load(current_path)
    cases = current.get("cases")
    if not isinstance(cases, list) or len(cases) != 336:
        raise RawAnchorPlanError("CURRENT336 must contain exactly 336 cases")
    if sha256_file(current_path) != CURRENT_SHA:
        raise RawAnchorPlanError("CURRENT336 content SHA differs from the frozen source catalog")
    grouped: dict[str, list[tuple[int, Mapping[str, Any]]]] = {family: [] for family in FAMILIES}
    for index, row in enumerate(cases):
        if isinstance(row, Mapping) and row.get("family_id") in grouped:
            grouped[str(row["family_id"])].append((index, row))
    if any(len(grouped[family]) != 48 for family in FAMILIES):
        raise RawAnchorPlanError("each family must have exactly 48 CURRENT rows")
    closure = _common_closure(repo_root)
    plans: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for family in FAMILIES:
        index, row = _select_anchor(grouped[family], family)
        raw_root = Path(str(row.get("raw_root", {}).get("path", ""))).expanduser()
        raw_names = sorted(item.name for item in raw_root.iterdir()) if raw_root.is_dir() else []
        required = ["PartInfo.ibi4", "PartOut_000.obi4", "Part_%04d.bi4" % 0]
        if "PartMotionRef.ibi4" in raw_names:
            required.append("PartMotionRef.ibi4")
        if "PartFloatInfo.ibi4" in raw_names:
            required.append("PartFloatInfo.ibi4")
        source_bindings = row.get("source_bindings", {})
        refs = [
            {"role": "current_catalog", "path": str(current_path), "sha256": CURRENT_SHA,
             "case_index": index, "identity_key": [row.get("family_id"), row.get("physical_case_id")]},
            _file_ref(row.get("manifest"), "manifest"),
            _file_ref(row.get("xmf"), "xmf"),
            _file_ref(row.get("conversion_report"), "conversion_report"),
        ]
        for role in ("generated_xml", "gencase_receipt", "solver_receipt", "owner_metadata"):
            refs.append(_file_ref(source_bindings.get(role), role))
        trajectory = row.get("trajectory", {})
        trajectory_ref = {
            "role": "trajectory_h5",
            "path": trajectory.get("path"),
            "producer_declared_sha256": trajectory.get("producer_declared_sha256"),
            "bytes": trajectory.get("bytes"),
            "mtime_ns": trajectory.get("mtime_ns"),
            "content_sha256": None,
            "status": "PRODUCER_DECLARED_PARENT_GUARD_REQUIRED",
        }
        plan = {
            "schema": SCHEMA,
            "plan_id": f"ds-data-02-{family.lower()}-raw-anchor-v1",
            "status": "DEVELOPMENT_SOURCE_BOUND_PLAN; PARENT_GUARD_REQUIRED",
            "family_id": family,
            "case_count": len(grouped[family]),
            "anchor_case": {
                "current_index": index,
                "physical_case_id": row.get("physical_case_id"),
                "runtime_case_alias": row.get("runtime_case_alias"),
                "frames": row.get("frames"),
                "particles": row.get("particles"),
                "actual_time_window_s": row.get("actual_time_window_s"),
                "known_numeric_physical_parameters": row.get("known_numeric_physical_parameters", {}),
            },
            "selection_policy": {
                "source": "exact CURRENT336 row and physical_case_id predicate",
                "latest_glob": False,
                "arbitrary_Run_out": False,
                "fixed_legacy_case_list": False,
                "anchor_is_hidden_test": False,
            },
            "source_bindings": refs + [trajectory_ref],
            "raw_anchor": {
                "raw_root": str(raw_root),
                "raw_root_exists": raw_root.is_dir(),
                "observed_entry_names_metadata_only": raw_names[:12],
                "required_source_arrays": required,
                "frame_pattern": "Part_%04d.bi4",
                "frame_count_expected": row.get("frames"),
                "partout_runparts_role": "provenance_only_not_frame_input",
                "content_sha_policy": "parent guard hashes exact files before conversion; this planner does not read them",
            },
            "typed_comparison_contract": {
                "identity_key": "(Zone,Idp)",
                "structural_fields": ["time", "particle_id", "particle_zone", "valid", "type", "mk"],
                "numeric_fields": ["position", "velocity", "density", "mass", "pressure"],
                "initial_fields": ["initial_type", "initial_mk", "initial_mass"],
                "lifecycle": "valid=false retains identity and marks state unknown; missing-ID hashes compared every saved frame",
                "body_weight_split": "SPH MassFluid/MassBound and support weight remain separate from rigid massbody/telemetry",
            },
            "label_and_evaluator_scope": {
                "operator": "v15/v16 only after typed comparison and exact source/profile binding",
                "event_scope": "finite receiver/aperture or family-specific observer only when geometry/control source is explicitly bound",
                "manual_predictions": "source/profile/identity/shape errors reject; wrong values score DEVELOPMENT FAIL",
                "qualification": UNKNOWN_QUALIFICATION,
            },
            "code_and_decoder_closure": closure,
            "family_card": {
                "path": str(cards_dir / f"{family}-family-card-v13.json"),
                "status": "existing v13 card remains DEVELOPMENT_ONLY; not rewritten",
            },
            "unknown_scope": _family_unknowns(family),
            "model_invoked": False,
            "cfd_invoked": False,
            "qualification": UNKNOWN_QUALIFICATION,
        }
        target = output_dir / f"{family}-raw-anchor-plan-v1.json"
        target.write_text(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        plans.append({
            "family_id": family,
            "path": str(target),
            "anchor_current_index": index,
            "anchor_physical_case_id": row.get("physical_case_id"),
            "raw_root": str(raw_root),
            "status": plan["status"],
            "qualification": UNKNOWN_QUALIFICATION,
        })
    index_doc = {
        "schema": "ds02.stage2.family-raw-anchor-plan-index.v1",
        "status": "DEVELOPMENT_SOURCE_BOUND_PLANS; NO_RAW_READ",
        "current_catalog": {"path": str(current_path), "sha256": CURRENT_SHA, "case_count": len(cases)},
        "families": plans,
        "raw_read_status": "NONE; parent stage2 guard must schedule each anchor",
        "seven_family_coverage": True,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN_QUALIFICATION,
    }
    (output_dir / "family-raw-anchor-plan-index-v1.json").write_text(
        json.dumps(index_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return index_doc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--cards-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()
    result = build_plans(args.current.expanduser().resolve(), args.cards_dir.expanduser().resolve(),
                         args.output_dir.expanduser().resolve(), args.repo_root.expanduser().resolve())
    print(json.dumps({"schema": result["schema"], "status": result["status"],
                      "families": len(result["families"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
