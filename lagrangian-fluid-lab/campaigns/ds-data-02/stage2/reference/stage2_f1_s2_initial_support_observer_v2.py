#!/usr/bin/env python3
"""ROOT233 forward worker for F1-S2 frame-0 support diagnostics.

ROOT229's consumed attempt stopped before decoding because its parent-side
manifest used ``grid_label`` while the old worker matched only ``grid``.
This worker normalizes the two explicit spellings at the guarded entry and
then reuses the old component-space support implementation.  It never
accepts a missing/ambiguous grid label, so the compatibility is narrow rather
than a permissive fallback.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import stage2_f1_s2_initial_support_observer_v1 as legacy


SCHEMA = "ds02.stage2.f1-s2.initial-support-observer.v2"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.initial-support-manifest.v2"
PASS_STATUS = "COMPLETE_F1_S2_INITIAL_NATIVE_SUPPORT_DIAGNOSTICS_NO_SCIENTIFIC_Q"
FAIL_STATUS = "FAILED_F1_S2_INITIAL_SUPPORT_GUARD_V2"
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}


def normalize_deferred_records(manifest: dict[str, Any]) -> dict[str, Any]:
    records = manifest.get("deferred_native_records")
    if not isinstance(records, list) or len(records) != 3:
        raise legacy.GuardFailure("ROOT233 requires exactly three deferred frame-0 records")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, original in enumerate(records):
        if not isinstance(original, dict):
            raise legacy.GuardFailure(f"deferred record {index} is not an object")
        labels = [original.get("grid"), original.get("grid_label"), original.get("case_label")]
        present = [str(value) for value in labels if isinstance(value, str) and value]
        if not present or len(set(present)) != 1:
            raise legacy.GuardFailure(f"deferred record {index} has missing or conflicting grid labels")
        label = present[0]
        if label not in {"coarse", "medium", "fine"} or label in seen:
            raise legacy.GuardFailure(f"deferred record {index} has invalid/duplicate grid label {label!r}")
        item = dict(original)
        item["grid"] = label
        item["grid_label"] = label
        seen.add(label)
        normalized.append(item)
    if seen != {"coarse", "medium", "fine"}:
        raise legacy.GuardFailure(f"deferred grid labels are incomplete: {sorted(seen)}")
    copied = dict(manifest)
    copied["deferred_native_records"] = normalized
    copied["deferred_record_label_normalization"] = "grid_and_grid_label_must_agree_or_one_must_be_present"
    return copied


def _failure(output: Path, reason: str) -> None:
    output = output.expanduser().absolute()
    if output.exists():
        return
    value = {
        "schema": SCHEMA,
        "status": FAIL_STATUS,
        "reason": reason,
        "scientific_qualification": QUALIFICATION,
        "read_scope": {"native_payload_read": "UNKNOWN_OR_PARTIAL", "solver_launch": False},
    }
    legacy._write_once(output, value)


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = args.manifest.expanduser().absolute()
    manifest, manifest_record = legacy._read_json(manifest_path, "ROOT233 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_NOT_RUN_ROOT233_INITIAL_SUPPORT_SOURCE_AUDIT":
        raise legacy.GuardFailure("ROOT233 manifest schema/status mismatch")
    manifest = normalize_deferred_records(manifest)
    legacy._verify_static_sources(manifest)
    joins = legacy._verify_provenance(manifest)
    grids = manifest.get("grids")
    if not isinstance(grids, list) or len(grids) != 3 or {item.get("label") for item in grids} != {"coarse", "medium", "fine"}:
        raise legacy.GuardFailure("ROOT233 requires coarse/medium/fine grid records")
    attempt_root = args.attempt_root.expanduser().absolute()
    outputs = [legacy._run_case(case, manifest, attempt_root, joins) for case in grids]
    result = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "producer_join": {key: value for key, value in joins.items() if key not in {"child", "calibration"}},
        "owner_continuum": {"mass_kg": 340.0, "volume_m3": 0.34, "density_kg_m3": 1000.0, "mass_source": "ROOT227 owner closure"},
        "deferred_record_label_normalization": "grid_and_grid_label_bound_to_same_frozen_grid",
        "grids": outputs,
        "read_scope": {"native_payload_read_count": 3, "native_payload_read": "three selected frame-0 Part_0000.bi4 files only", "hdf5_read": False, "vtk_read": False, "full_native_tree_scan": False, "solver_launch": False},
        "scientific_qualification": QUALIFICATION,
        "qualification_limits": ["position tolerance is binary support containment only, not a QN task tolerance", "native sample mass remains separate from 340 kg continuous owner mass", "producer world-axis calibration remains UNKNOWN", "no interpolation, integration, spatial-truth, or external-validation credit"],
    }
    legacy._write_once(args.output.expanduser().absolute(), result)
    return result


def self_test() -> None:
    base = {"deferred_native_records": [{"grid_label": "coarse"}, {"grid": "medium"}, {"grid": "fine", "grid_label": "fine"}]}
    normalized = normalize_deferred_records(base)
    assert [item["grid"] for item in normalized["deferred_native_records"]] == ["coarse", "medium", "fine"]
    for bad in (
        {"deferred_native_records": [{"grid": "coarse"}, {"grid": "coarse"}, {"grid": "fine"}]},
        {"deferred_native_records": [{"grid": "coarse", "grid_label": "fine"}, {"grid": "medium"}, {"grid": "fine"}]},
        {"deferred_native_records": [{"grid": "coarse"}, {"grid": "medium"}]},
    ):
        try:
            normalize_deferred_records(bad)
        except legacy.GuardFailure:
            pass
        else:
            raise AssertionError("invalid deferred grid manifest was accepted")
    print("PASS_F1_S2_INITIAL_SUPPORT_OBSERVER_V2_MANIFEST_ENTRY_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--manifest, --attempt-root, and --output are required unless --self-test is used")
    try:
        result = run(args)
    except Exception as exc:
        _failure(args.output, str(exc))
        print(f"FAIL_F1_S2_INITIAL_SUPPORT_OBSERVER_V2: {exc}")
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().absolute())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
