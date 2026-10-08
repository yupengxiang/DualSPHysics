#!/usr/bin/env python3
"""Forward quality audit for source-bound family label products.

The v2 artifact-quality worker remains immutable.  This version fixes one
contract edge exposed by the actual F2 recovery product: recovery reports use
``source_contract`` and therefore do not repeat the top-level ``family_id``.
The validator compares manifest identity with the normalized binding returned
by the v2 binding checker, while retaining strict trajectory/output hashes.
It also records whether cohorts are native initial-MK or initial-spatial.

This worker reads a materialized label H5 and its small report.  It never opens
an original trajectory H5, BI4, solver output, or starts a model.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable

SCRIPT = Path(__file__).resolve()
_V2_PATH = SCRIPT.with_name("ds_data02_stage2_family_label_quality_v2.py")
_SPEC = importlib.util.spec_from_file_location("_ds02_quality_v2_for_v3", _V2_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot load {_V2_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)

SCHEMA = "ds02.stage2.family-label-quality.v3"
MANIFEST_SCHEMA = "ds02.stage2.family-label-quality-manifest.v3"
SPLITS = {"development", "development_validation", "development_test", "unresolved_excluded"}
SOURCE_ROLES = {"native_initial_mk", "initial_spatial_region", "unknown"}


class QualityV3Error(RuntimeError):
    pass


sha256_file = _BASE.sha256_file
require_file = _BASE.require_file
read_json = _BASE.read_json


def _source_role(report: dict[str, Any]) -> tuple[str, str]:
    """Derive source role from the bound producer config, never an entry label."""
    if report.get("schema") == _BASE.RECOVERY_REPORT_SCHEMA:
        contract = report.get("source_contract")
        config = contract.get("config") if isinstance(contract, dict) else None
        semantics = config.get("moving_source_semantics") if isinstance(config, dict) else None
        role = semantics.get("source_assignment") if isinstance(semantics, dict) else None
        source_labels = semantics.get("source_labels") if isinstance(semantics, dict) else None
        if role == "native_initial_mk" or (
                isinstance(source_labels, str) and "native initial MK" in source_labels):
            role = "native_initial_mk"
            return role, "recovery source_contract.config.moving_source_semantics"
        return "unknown", "recovery source assignment is not an explicit native_initial_mk"
    source_join = report.get("source_join")
    config = source_join.get("config_json") if isinstance(source_join, dict) else None
    role = config.get("source_assignment") if isinstance(config, dict) else None
    if role == "native_initial_mk":
        return role, "source_join.config_json.source_assignment"
    if role == "initial_regions":
        return "initial_spatial_region", "source_join.config_json.source_assignment=initial_regions"
    return "unknown", "producer config lacks a supported source assignment"


def _bindings(report: dict[str, Any], labels_h5: Path, *, verify_h5: bool) -> dict[str, Any]:
    try:
        binding = _BASE._report_bindings(report, labels_h5, verify_h5=verify_h5)
    except _BASE.QualityError as error:
        raise QualityV3Error(str(error)) from error
    role, role_basis = _source_role(report)
    family = binding.get("family_id")
    physical = binding.get("physical_case_id")
    if not isinstance(family, str) or not family or not isinstance(physical, str) or not physical:
        raise QualityV3Error("normalized report binding lacks exact family/case identity")
    return {**binding, "source_role": role, "source_role_basis": role_basis}


def _validate_policy(manifest: dict[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise QualityV3Error("unsupported family label quality v3 manifest schema")
    policy = manifest.get("split_policy")
    if not isinstance(policy, dict) or policy.get("unit") != "complete_physical_case":
        raise QualityV3Error("manifest split policy is not complete-physical-case based")
    if policy.get("identity_level_split") is not False:
        raise QualityV3Error("manifest permits identity-level splitting")
    if policy.get("effective_component_audit_external") is not True:
        raise QualityV3Error("effective split proof must remain external")
    if policy.get("recovery_safe") is not False:
        raise QualityV3Error("quality audit cannot declare recovery_safe")


def _validate_manifest_payload(manifest: dict[str, Any], *, check_paths: bool = True,
                               verify_artifacts: bool = True) -> list[dict[str, Any]]:
    _validate_policy(manifest)
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise QualityV3Error("manifest entries are required")
    seen_cases: set[tuple[str, str]] = set()
    seen_trajectories: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise QualityV3Error(f"manifest entry {index} is not an object")
        split = entry.get("split")
        if split not in SPLITS:
            raise QualityV3Error(f"manifest entry {index} has unsupported split")
        if check_paths:
            report_path = require_file(entry.get("report"), f"entry {index} report")
            labels_h5 = require_file(entry.get("labels_h5"), f"entry {index} labels H5")
            report_path, report = read_json(report_path, f"entry {index} report")
            binding = _bindings(report, labels_h5, verify_h5=verify_artifacts)
        else:
            report_path = Path(str(entry.get("report", ""))).expanduser().resolve()
            labels_h5 = Path(str(entry.get("labels_h5", ""))).expanduser().resolve()
            report = {}
            binding = {
                "family_id": entry.get("family_id"),
                "physical_case_id": entry.get("physical_case_id"),
                "trajectory_sha256": entry.get("trajectory_sha256"),
                "source_role": entry.get("source_role", "unknown"),
                "materialization_sha256": entry.get("labels_h5_sha256"),
            }
        family = entry.get("family_id", binding.get("family_id"))
        physical = entry.get("physical_case_id", binding.get("physical_case_id"))
        if not isinstance(family, str) or not isinstance(physical, str):
            raise QualityV3Error(f"entry {index} lacks exact family/case identity")
        # Compare against normalized producer identity.  A recovery report is
        # intentionally allowed to omit report.family_id, but an explicitly
        # supplied wrong value is rejected.
        if family != binding.get("family_id") or physical != binding.get("physical_case_id"):
            raise QualityV3Error(f"entry {index} identity differs from normalized producer binding")
        key = (family, physical)
        if key in seen_cases:
            raise QualityV3Error("manifest repeats a family/case identity")
        seen_cases.add(key)
        trajectory = binding.get("trajectory_sha256")
        if not isinstance(trajectory, str) or len(trajectory) != 64:
            raise QualityV3Error(f"entry {index} lacks source trajectory digest")
        if trajectory in seen_trajectories:
            raise QualityV3Error("manifest repeats a trajectory identity")
        seen_trajectories.add(trajectory)
        declared_role = entry.get("source_role")
        if declared_role is not None and declared_role != binding.get("source_role"):
            raise QualityV3Error(f"entry {index} source_role differs from producer config")
        role = binding.get("source_role")
        if role not in SOURCE_ROLES:
            raise QualityV3Error(f"entry {index} has unsupported source role {role!r}")
        normalized.append({
            "entry_key": entry.get("entry_key", physical),
            "family_id": family,
            "physical_case_id": physical,
            "split": split,
            "report": str(report_path),
            "labels_h5": str(labels_h5),
            "report_sha256": sha256_file(report_path) if check_paths else entry.get("report_sha256"),
            "labels_h5_sha256": binding.get("materialization_sha256"),
            "trajectory_sha256": trajectory,
            "source_role": role,
            "source_role_basis": binding.get("source_role_basis"),
            "recovery_policy": entry.get("recovery_policy"),
        })
    if not any(row["split"] == "development" for row in normalized):
        raise QualityV3Error("manifest has no development case")
    return normalized


def _quality_run(manifest_path: Path | str, output: Path | str) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "family label quality v3 manifest")
    entries = _validate_manifest_payload(manifest, check_paths=True, verify_artifacts=True)
    results = []
    for entry in entries:
        report_path = Path(entry["report"])
        labels_h5 = Path(entry["labels_h5"])
        try:
            item = _BASE._audit_entry(report_path, labels_h5, entry["split"], entry_key=entry["entry_key"])
        except _BASE.QualityError as error:
            raise QualityV3Error(str(error)) from error
        item["source_role"] = entry["source_role"]
        item["source_role_basis"] = entry["source_role_basis"]
        item["normalized_identity"] = {"family_id": entry["family_id"], "physical_case_id": entry["physical_case_id"]}
        results.append(item)
    result = {
        "schema": SCHEMA,
        "status": "FAMILY_LABEL_QUALITY_V3_PASS_MASS_CENSOR_ARTIFACT_SOURCE_BOUND",
        "manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path), "entry_count": len(entries)},
        "cases": results,
        "source_roles": {"native_initial_mk": sum(x["source_role"] == "native_initial_mk" for x in results),
                         "initial_spatial_region": sum(x["source_role"] == "initial_spatial_region" for x in results),
                         "unknown": sum(x["source_role"] == "unknown" for x in results)},
        "splits": {split: sum(x["split"] == split for x in results) for split in sorted(SPLITS)},
        "claim_boundary": {
            "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN",
            "continuous_first_arrival": "UNKNOWN", "hidden_recrossings": "UNKNOWN",
            "split_safe": "NOT_ASSESSED", "recovery_safe": "NOT_ASSESSED",
        },
        "read_policy": {
            "original_trajectory_h5_opened": False,
            "part_bi4_opened": False,
            "solver_started": False,
            "model_invoked": False,
            "materialized_label_h5_opened": True,
        },
    }
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise QualityV3Error(f"refusing to overwrite quality v3 report: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def make_manifest(entries: Iterable[dict[str, Any]], output: Path | str) -> dict[str, Any]:
    payload = {
        "schema": MANIFEST_SCHEMA,
        "split_policy": {
            "unit": "complete_physical_case",
            "identity_level_split": False,
            "trajectory_digest_leakage_forbidden": True,
            "effective_component_audit_external": True,
            "recovery_safe": False,
            "purpose": "materialized label artifact quality and source-role diagnostics only",
        },
        "entries": list(entries),
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "split_safe": "NOT_ASSESSED"},
    }
    _validate_manifest_payload(payload, check_paths=True, verify_artifacts=False)
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise QualityV3Error(f"refusing to overwrite manifest: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def make_request(manifest_path: Path | str, output: Path | str, worktree_root: Path | str) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "family label quality v3 manifest")
    entries = _validate_manifest_payload(manifest, check_paths=True, verify_artifacts=False)
    root = Path(worktree_root).expanduser().resolve()
    worker = root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_v3.py"
    runtime = [root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
               root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
               root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
               root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]
    current_paths: set[Path] = set()
    inputs: list[Path] = [manifest_path, worker, *_BASE_PATHS(root)]
    for entry in entries:
        report = Path(entry["report"])
        labels = Path(entry["labels_h5"])
        inputs.extend([report, labels])
        report_payload = read_json(report, "family label report")[1]
        if report_payload.get("schema") == _BASE.RECOVERY_REPORT_SCHEMA:
            contract = report_payload.get("source_contract")
            current_raw = contract.get("current", {}).get("path") if isinstance(contract, dict) else None
        else:
            current_raw = report_payload.get("source_join", {}).get("source_bindings", {}).get("current_manifest", {}).get("path")
        if current_raw:
            current_paths.add(require_file(current_raw, "CURRENT manifest"))
    inputs.extend(runtime)
    inputs.extend(sorted(current_paths))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in inputs:
        path = Path(path).resolve()
        if str(path) not in seen:
            unique.append(path); seen.add(str(path))
    missing = [str(path) for path in unique if not path.is_file()]
    hashes: dict[str, str] = {}
    for path in unique:
        if path.is_file():
            if path == Path(next((x["labels_h5"] for x in entries if Path(x["labels_h5"]).resolve() == path), "")).resolve():
                expected = next(x["labels_h5_sha256"] for x in entries if Path(x["labels_h5"]).resolve() == path)
                hashes[str(path)] = expected
            else:
                hashes[str(path)] = sha256_file(path)
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": "ds02.stage2.family-label-quality-request.v3",
        "attempt_id": "family-label-quality-v3",
        "case_id": "DS02_STAGE2_FAMILY_LABEL_QUALITY_V3_F1_F2_F3",
        "family_id": "F1_F2_F3",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "max_wall_seconds": 1800,
        "estimated_storage_bytes": 128 * 1024 * 1024,
        "cwd": str(root / "lagrangian-fluid-lab/scripts"), "worktree_root": str(root),
        "command": ["/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(worker), "run", "--manifest", str(manifest_path), "--output", "{attempt_root}/family-label-quality-v3.json"],
        "input_files": [str(path) for path in unique], "input_sha256": hashes,
        "launch_allowed": not missing, "primary_launch_owner": "root",
        "status": "prepared_guard_pending_actual_CPU" if not missing else "prepared_missing_guard_sources",
        "source_cost": {"materialized_label_h5_bytes_read": sum(Path(x["labels_h5"]).stat().st_size for x in entries if Path(x["labels_h5"]).is_file()), "original_trajectory_h5_bytes_read": 0, "part_bi4_bytes_read": 0, "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "split_safe": "NOT_ASSESSED", "recovery_safe": "NOT_ASSESSED"},
        "missing_guard_sources": missing,
    }
    output = Path(output).expanduser().resolve()
    if output.exists(): raise QualityV3Error(f"refusing to overwrite request: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return request


def _BASE_PATHS(root: Path) -> list[Path]:
    # v3 imports the immutable v2 binding/ledger implementation.  Bind that
    # source explicitly so a guard cannot substitute a different sibling.
    return [root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_family_label_quality_v2.py",
            root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py",
            root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
            root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
            root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run"); run.add_argument("--manifest", type=Path, required=True); run.add_argument("--output", type=Path, required=True)
    prep = sub.add_parser("make-manifest"); prep.add_argument("--entries", type=Path, required=True); prep.add_argument("--output", type=Path, required=True)
    req = sub.add_parser("make-request"); req.add_argument("--manifest", type=Path, required=True); req.add_argument("--output", type=Path, required=True); req.add_argument("--worktree-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run": _quality_run(args.manifest, args.output)
    elif args.command == "make-manifest":
        payload = read_json(args.entries, "entries")[1]; make_manifest(payload.get("entries", payload), args.output)
    else: make_request(args.manifest, args.output, args.worktree_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
