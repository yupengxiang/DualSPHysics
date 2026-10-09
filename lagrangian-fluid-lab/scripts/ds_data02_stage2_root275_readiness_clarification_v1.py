#!/usr/bin/env python3
"""Record the bounded readiness status of the seven ROOT275 F4 cases.

This is a metadata-only clarification.  It reads CURRENT/plans, lifecycle
registries, and the already prepared ROOT275/ROOT296/ROOT297 JSON contracts.
It never opens a deferred H5/JSONL/BI4/OBI4/PartOut/RunPARTs payload and it
never submits a job.  The output is deliberately explicit that the seven
cases are source-prepared future work, not typed lifecycle producers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
QUEUE = STAGE2 / "requests/root282-root307-lifecycle-source-queue-001"

CURRENT = STAGE2 / "CURRENT336.json"
PLAN_269 = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT269_V4.json"
PLAN_280 = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT280_V4.json"
REGISTRY_269 = STAGE2 / "requests/typed-lifecycle-evidence-registry-v4-after-root269-001.json"
REGISTRY_280 = STAGE2 / "requests/typed-lifecycle-evidence-registry-v4-after-root280-001.json"
ROOT275_REQUEST = STAGE2 / "requests/root275-f4-lifecycle-subset-root-forward-275-001.json"
ROOT275_NATIVE_REQUEST = STAGE2 / "requests/root275-f4-native-source-prepared-001/generic-native-extract-v1-root-forward-275-source-only.json"
ROOT275_MANIFEST = STAGE2 / "requests/root275-f4-native-source-prepared-001/generic-native-extract/generic-native-extract-manifest.json"

CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
PLAN_269_SHA = "216a18effda38687614ebbf536606912761628b04b832cd7be1185afa99d2f0c"
PLAN_280_SHA = "24202edc188a1f82a8fba4a2bffddc226843a954df5e0c7393c070d76b286900"
REGISTRY_269_SHA = "b78522c5d4e237b185ab2a3de262e0e6e3b77ce58bf0e8e622abda400c78e517"
REGISTRY_280_SHA = "4778b7ffbf6ed672bb6d604a776c55038f01ca9cdb090f7e73742816fa0ce5cf"
MAX_SMALL_BYTES = 10 * 1024 * 1024

TARGET_CASES = (
    "F4_DROP_gap0p20000_xoffm0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p20000_xoffm0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p25000_xoff0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p26000_xoff0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p26000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p26000_xoff0p08000_yoffm0p04000_uz0p60000",
    "F4_DROP_gap0p26000_xoffm0p08000_yoffm0p04000_uz0p60000",
)

ROOT_PARENT_CASES = {
    "ROOT296": QUEUE / "root296-f4-lifecycle-prepared-001/delegated/typed-lifecycle-batch-v1-manifest.json",
    "ROOT297": QUEUE / "root297-f4-lifecycle-prepared-001/delegated/typed-lifecycle-batch-v1-manifest.json",
}


class ReadinessError(ValueError):
    pass


def _path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise ReadinessError(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ReadinessError(f"{label} is missing: {path}")
    return path


def _ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    path = _path(path, label)
    stat = path.stat()
    if stat.st_size > MAX_SMALL_BYTES:
        raise ReadinessError(f"{label} exceeds bounded metadata read: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is not None and digest != expected:
        raise ReadinessError(f"{label} SHA differs: {path}: {digest} != {expected}")
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": digest,
        "content_opened_by_preparer": True,
    }


def _json(path: Path, label: str) -> dict[str, Any]:
    _ref(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReadinessError(f"{label} must be a JSON object")
    return value


def _plan_rows(plan: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    if plan.get("status") != "PREPARED_METADATA_ONLY_NO_LAUNCH":
        raise ReadinessError(f"{label} is not metadata-only")
    rows = plan.get("case_records")
    if not isinstance(rows, list):
        raise ReadinessError(f"{label} has no case_records")
    mapped = {row.get("physical_case_id"): row for row in rows if isinstance(row, dict)}
    if len(mapped) != 336 or any(not isinstance(key, str) for key in mapped):
        raise ReadinessError(f"{label} does not expose 336 unique case records")
    return mapped


def _registry_case_ids(registry: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for producer in registry.get("producers", []):
        if isinstance(producer, dict):
            values = producer.get("case_ids", [])
            if isinstance(values, list):
                ids.update(value for value in values if isinstance(value, str))
    return ids


def _load_parent_manifests() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    parents: dict[str, dict[str, Any]] = {}
    selected: dict[str, str] = {}
    for parent, path in ROOT_PARENT_CASES.items():
        manifest = _json(path, f"{parent} delegated lifecycle manifest")
        if manifest.get("status") != "READY_FOR_GUARDED_BATCH":
            raise ReadinessError(f"{parent} is not a source-only lifecycle manifest")
        cases = manifest.get("cases")
        if not isinstance(cases, list):
            raise ReadinessError(f"{parent} has no cases")
        ids = [row.get("physical_case_id") for row in cases if isinstance(row, dict)]
        if len(ids) != 8 or len(set(ids)) != 8:
            raise ReadinessError(f"{parent} does not contain eight unique cases")
        for case_id in ids:
            if case_id in selected:
                raise ReadinessError(f"case appears in both parent manifests: {case_id}")
            selected[case_id] = parent
        parents[parent] = {
            "manifest": _ref(path, f"{parent} delegated lifecycle manifest"),
            "status": manifest.get("status"),
            "case_ids": ids,
            "case_count": len(ids),
            "source_read_policy": manifest.get("source_read_policy"),
        }
    if set(TARGET_CASES) - set(selected):
        raise ReadinessError(f"ROOT296/297 do not cover targets: {sorted(set(TARGET_CASES) - set(selected))}")
    return parents, {case_id: {"parent": parent} for case_id, parent in selected.items()}


def _atomic(path: Path, value: dict[str, Any]) -> dict[str, Any]:
    path = Path(path).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise ReadinessError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _ref(path, "new ROOT275 readiness clarification")


def build(output: Path) -> dict[str, Any]:
    current_ref = _ref(CURRENT, "CURRENT336", CURRENT_SHA)
    plans = {
        "after_root269": (PLAN_269, PLAN_269_SHA),
        "after_root280": (PLAN_280, PLAN_280_SHA),
    }
    plan_values: dict[str, dict[str, Any]] = {}
    plan_refs: dict[str, dict[str, Any]] = {}
    rows_by_plan: dict[str, dict[str, dict[str, Any]]] = {}
    for name, (path, expected) in plans.items():
        plan_refs[name] = _ref(path, f"{name} continuation plan", expected)
        plan_values[name] = _json(path, f"{name} continuation plan")
        rows_by_plan[name] = _plan_rows(plan_values[name], name)

    registry_values = {}
    registry_refs = {}
    for name, path, expected in (
        ("after_root269", REGISTRY_269, REGISTRY_269_SHA),
        ("after_root280", REGISTRY_280, REGISTRY_280_SHA),
    ):
        registry_refs[name] = _ref(path, f"{name} lifecycle registry", expected)
        registry_values[name] = _json(path, f"{name} lifecycle registry")

    parents, parent_by_case = _load_parent_manifests()
    root275_request_ref = _ref(ROOT275_REQUEST, "ROOT275 lifecycle subset request")
    root275_request = _json(ROOT275_REQUEST, "ROOT275 lifecycle subset request")
    root275_native_request_ref = _ref(ROOT275_NATIVE_REQUEST, "ROOT275 native source request")
    root275_native_request = _json(ROOT275_NATIVE_REQUEST, "ROOT275 native source request")
    root275_manifest_ref = _ref(ROOT275_MANIFEST, "ROOT275 native source manifest")
    root275_manifest = _json(ROOT275_MANIFEST, "ROOT275 native source manifest")
    if root275_request.get("physical_case_ids") != list(TARGET_CASES):
        raise ReadinessError("ROOT275 lifecycle subset order or identity differs")
    if root275_native_request.get("physical_case_ids") != list(TARGET_CASES):
        raise ReadinessError("ROOT275 native request order or identity differs")
    if root275_manifest.get("physical_case_ids") != list(TARGET_CASES):
        raise ReadinessError("ROOT275 native manifest order or identity differs")
    for doc, label in ((root275_request, "ROOT275 lifecycle subset"), (root275_native_request, "ROOT275 native request"), (root275_manifest, "ROOT275 native manifest")):
        if doc.get("launch_allowed") is not False or doc.get("execution_allowed") is not False:
            raise ReadinessError(f"{label} is launchable")

    latest_rows = rows_by_plan["after_root280"]
    baseline_rows = rows_by_plan["after_root269"]
    target_rows = []
    for case_id in TARGET_CASES:
        row = latest_rows.get(case_id)
        if not isinstance(row, dict):
            raise ReadinessError(f"missing target in latest plan: {case_id}")
        if row.get("family_id") != "F4" or row.get("status") != "UNSCHEDULED_EXACT_CURRENT_AUDIT":
            raise ReadinessError(f"target is no longer unscheduled exact CURRENT: {case_id}")
        if row.get("actual_saved_mask_coverage") is not False or row.get("producer_evidence") is not None or row.get("scientific_credit") != "NONE":
            raise ReadinessError(f"target has unexpected actual credit: {case_id}")
        base = baseline_rows.get(case_id)
        if not isinstance(base, dict) or base.get("status") != "UNSCHEDULED_EXACT_CURRENT_AUDIT":
            raise ReadinessError(f"target was not unscheduled in ROOT269 baseline: {case_id}")
        target_rows.append({
            "physical_case_id": case_id,
            "current_index": row.get("current_index"),
            "family_id": row.get("family_id"),
            "plan_group_id": row.get("group_id"),
            "plan_status": row.get("status"),
            "source_join_status": row.get("source_join_status"),
            "actual_saved_mask_coverage": row.get("actual_saved_mask_coverage"),
            "scientific_credit": row.get("scientific_credit"),
            "historical_alias": row.get("historical_alias"),
            "source_parent": parent_by_case[case_id]["parent"],
            "typed_terminal_proof": False,
            "native_extraction_allowed": False,
        })

    baseline_ids = _registry_case_ids(registry_values["after_root269"])
    latest_ids = _registry_case_ids(registry_values["after_root280"])
    if baseline_ids.intersection(TARGET_CASES) or latest_ids.intersection(TARGET_CASES):
        raise ReadinessError("a ROOT275 target appears in a completed registry producer")

    target_groups = {}
    for row in target_rows:
        target_groups.setdefault(row["plan_group_id"], 0)
        target_groups[row["plan_group_id"]] += 1

    result = {
        "schema": "ds02.stage2.root275-readiness-clarification.v1",
        "status": "SOURCE_PREPARED_NOT_TYPED_NOT_TERMINAL",
        "as_of": {
            "current_catalog": current_ref,
            "plan_after_root269": plan_refs["after_root269"],
            "plan_after_root280": plan_refs["after_root280"],
            "registry_after_root269": registry_refs["after_root269"],
            "registry_after_root280": registry_refs["after_root280"],
        },
        "target_count": len(TARGET_CASES),
        "targets": target_rows,
        "future_parent_groups": target_groups,
        "parent_manifests": parents,
        "root275_prepared_contracts": {
            "lifecycle_request": root275_request_ref,
            "native_request": root275_native_request_ref,
            "native_manifest": root275_manifest_ref,
            "launch_allowed": False,
            "execution_allowed": False,
            "terminal_typed_proof_present": False,
        },
        "coverage_context": {
            "after_root269_actual_saved_mask_cases": plan_values["after_root269"]["coverage"]["actual_saved_mask_cases"],
            "after_root280_actual_saved_mask_cases": plan_values["after_root280"]["coverage"]["actual_saved_mask_cases"],
            "after_root280_target_actual_saved_mask_cases": 0,
            "after_root280_remaining_exact_unscheduled_cases": plan_values["after_root280"]["coverage"]["remaining_exact_unscheduled_cases"],
            "registry_target_producers": 0,
        },
        "claim_boundary": {
            "saved_mask_lifecycle": "NOT_AVAILABLE_FOR_THESE_SEVEN_CASES",
            "native_cause": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamics": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
        },
        "read_policy": {
            "metadata_json_opened": True,
            "deferred_h5_content_opened": False,
            "jsonl_content_opened": False,
            "bi4_or_obi4_opened": False,
            "partout_or_runparts_opened": False,
            "solver_started": False,
        },
        "correction_note": "ROOT275 must not be described as seven completed typed cases. ROOT296/ROOT297 are source-only future lifecycle manifests; a later current-registry refresh and terminal proof are required before native extraction.",
    }
    return {"output": _atomic(output, result), "result": result}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "self-test":
            value = {"status": "PASS", "target_count": len(TARGET_CASES), "payload_content_opened": False, "launch_allowed": False}
        else:
            value = build(args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ROOT275_READINESS_ERROR: {exc}")
        return 2
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
