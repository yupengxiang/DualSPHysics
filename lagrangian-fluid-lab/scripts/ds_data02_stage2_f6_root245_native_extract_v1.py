#!/usr/bin/env python3
"""Prepare and execute the guarded ROOT245 F6 native extraction.

This forward worker closes the source edge that is intentionally absent from
the ROOT245 lifecycle request: the seven exact F6 cases already have indexed
``PartOut_000.obi4`` and ``RunPARTs.csv`` paths in the immutable 118-case
inventory.  ``prepare`` reads only the inventory, request, terminal proof
metadata, file statistics, and small tool/source files.  It does not read an
OBI4/BI4/H5/JSONL payload and never starts a solver.

After ROOT245 has a completed terminal proof, the parent can run ``audit``
under a shared reservation.  It hashes the OBI4 before and after, invokes the
official ORIGINAL ``PartVTKOut_linux64`` once per case, then delegates exact
typed ``(Zone, Idp)``/PartOut/RunPARTs joining to the reviewed intake parser.
Native Motive is a numerical saved-output diagnostic only; fate, flux,
continuous event time, dynamics, and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
INTAKE_SCRIPT = SCRIPT.with_name("ds_data02_stage2_f6_root245_native_cause_intake_v1.py")
ORIGINAL_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
PARTVTKOUT = ORIGINAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
PARTVTKOUT_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
CONFIG = ORIGINAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
INVENTORY_DEFAULT = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
PLAN_DEFAULT = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT232_V4.json"
ROOT245_PLAN_SHA = "960725604c7978c67516ff38d60718d9eb732f18d3b8cb8cde3049ace67fb295"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
MAX_SMALL = 10 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
ROOT245_CASES = (
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0875_YAWP06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1125_YAWP12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1375_YAWP18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1625_YAWM18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0375_YAWM12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0625_YAWM06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0875_YAWP06_DP025",
)
ROOT245_SET = set(ROOT245_CASES)
REQUEST_SCHEMA = "ds02.request.v1"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
MANIFEST_SCHEMA = "ds02.stage2.f6-root245-native-extract.v1"
CONTRACT_SCHEMA = "ds02.stage2.f6-root245-native-extract-contract.v1"
REPORT_SCHEMA = "ds02.stage2.f6-root245-native-extract-report.v1"


class ExtractError(ValueError):
    """Raised for a missing source edge or unsafe deferred contract."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ExtractError(f"{label} must be SHA-256")
    value = value.lower()
    if any(c not in "0123456789abcdef" for c in value):
        raise ExtractError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool = False, allow_missing: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise ExtractError(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if allow_missing:
        return path
    if directory and not path.is_dir():
        raise ExtractError(f"{label} directory is missing: {path}")
    if not directory and not path.is_file():
        raise ExtractError(f"{label} file is missing: {path}")
    return path


def _stat(path: Path, label: str, *, directory: bool = False) -> dict[str, Any]:
    path = _path(path, label, directory=directory)
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _digest(path: Path, label: str, *, max_bytes: int | None = None) -> str:
    path = _path(path, label)
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ExtractError(f"{label} exceeds bounded read")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _json(path: Path, label: str, *, max_bytes: int = MAX_SMALL) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise ExtractError(f"{label} exceeds small JSON bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExtractError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExtractError(f"{label} must be an object")
    return value


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    value = _stat(path, label)
    if value["bytes"] > MAX_SMALL:
        raise ExtractError(f"{label} exceeds small source bound")
    actual = _digest(path, label, max_bytes=MAX_SMALL)
    if expected is not None and expected != "PARENT_GUARD_COMPUTED" and actual != _sha(expected, f"{label} expected SHA"):
        raise ExtractError(f"{label} SHA differs")
    value.update({"sha256": actual, "content_opened": True})
    return value


def _deferred(path: Path, label: str, declared: dict[str, Any] | None = None, *, directory: bool = False, expected_sha: str | None = None) -> dict[str, Any]:
    value = _stat(path, label, directory=directory)
    if declared is not None:
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if declared.get(field) is not None and int(declared[field]) != value[field]:
                raise ExtractError(f"{label} stat differs at {field}")
    value.update({"sha256": expected_sha or "PARENT_GUARD_COMPUTED", "content_opened_by_preparer": False, "read_after_parent_reservation": True, "deferred": True})
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ExtractError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if tmp.stat().st_size > limit:
            raise ExtractError(f"output exceeds {limit} bytes")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _load_inventory(path: Path) -> dict[str, dict[str, Any]]:
    inventory = _json(path, "historical 118 inventory")
    if inventory.get("schema") != "ds02.stage2.historical118-source-inventory.v1":
        raise ExtractError("historical inventory schema differs")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise ExtractError("historical inventory must expose 118 rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise ExtractError("inventory row identity is malformed")
        case_id = row["physical_case_id"]
        if case_id in result:
            raise ExtractError(f"duplicate inventory case: {case_id}")
        result[case_id] = row
    return result


def _validate_request(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _json(path, "ROOT245 lifecycle request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("family_id") != "F6" or request.get("case_id") != "STAGE2_TYPED_LIFECYCLE_BATCH_F6_ROOT245":
        raise ExtractError("ROOT245 lifecycle request identity differs")
    if request.get("physical_case_ids") != list(ROOT245_CASES):
        raise ExtractError("ROOT245 lifecycle request case set/order differs")
    group = request.get("continuation_group")
    if not isinstance(group, dict) or group.get("group_id") != "F6-typed-lifecycle-continuation-000" or int(group.get("declared_source_bytes", -1)) != 19_557_244_116:
        raise ExtractError("ROOT245 lifecycle source group differs")
    if int(group.get("actual_saved_mask_cases_excluded", -1)) != 87 or int(group.get("historical_alias_cases_excluded", -1)) != 1:
        raise ExtractError("ROOT245 no-overlap boundary differs")
    manifest = request.get("manifest_contract")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("path"), str):
        raise ExtractError("ROOT245 manifest contract is missing")
    manifest_path = _path(manifest["path"], "ROOT245 lifecycle manifest")
    manifest_ref = _small_ref(manifest_path, "ROOT245 lifecycle manifest", manifest.get("sha256"))
    return request, {"request": _small_ref(path, "ROOT245 lifecycle request"), "manifest": manifest_ref}


def _validate_proof(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    proof = _json(path, "ROOT245 terminal proof")
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise ExtractError("ROOT245 proof is not an actual terminal proof")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or int(counts.get("completed", -1)) != 7 or int(counts.get("failed", -1)) != 0:
        raise ExtractError("ROOT245 proof is not a completed seven-case proof")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != 7:
        raise ExtractError("ROOT245 proof does not contain seven cases")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("physical_case_id") in result:
            raise ExtractError("ROOT245 proof has duplicate/malformed case")
        case_id = row.get("physical_case_id")
        if case_id not in ROOT245_SET or row.get("family_id") != "F6" or row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
            raise ExtractError(f"ROOT245 proof case is outside exact saved-mask scope: {case_id}")
        if row.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
            raise ExtractError(f"ROOT245 H5 source closure is not proven: {case_id}")
        for role in ("summary", "records_stat_only"):
            value = row.get(role)
            if not isinstance(value, dict) or not isinstance(value.get("path"), str):
                raise ExtractError(f"ROOT245 proof lacks {role}: {case_id}")
        result[case_id] = row
    if set(result) != ROOT245_SET:
        raise ExtractError("ROOT245 proof case set is incomplete")
    return proof, result


def _native_edges(row: dict[str, Any], case_id: str) -> dict[str, Any]:
    artifacts = row.get("source_artifacts", {}).get("artifacts", {})
    index = artifacts.get("native_part_directory_stat_index") if isinstance(artifacts, dict) else None
    if not isinstance(index, dict) or not isinstance(index.get("path"), str):
        raise ExtractError(f"{case_id} native data index is missing")
    samples = index.get("entry_samples")
    if not isinstance(samples, list):
        raise ExtractError(f"{case_id} native data samples are missing")
    partout = next((item for item in samples if isinstance(item, dict) and item.get("role") == "native_part_directory:PartOut_000.obi4"), None)
    if not isinstance(partout, dict) or not isinstance(partout.get("path"), str):
        raise ExtractError(f"{case_id} PartOut_000.obi4 is not indexed")
    solver = artifacts.get("solver_output")
    entries = solver.get("artifacts") if isinstance(solver, dict) else None
    if not isinstance(entries, list):
        raise ExtractError(f"{case_id} solver output index is missing")
    runparts = next((item for item in entries if isinstance(item, dict) and item.get("role") == "solver_output:RunPARTs.csv"), None)
    runout = next((item for item in entries if isinstance(item, dict) and item.get("role") == "solver_output:Run.out"), None)
    receipt = next((item for item in entries if isinstance(item, dict) and item.get("role") == "solver_receipt"), None)
    if not all(isinstance(item, dict) and isinstance(item.get("path"), str) for item in (runparts, runout, receipt)):
        raise ExtractError(f"{case_id} solver RunPARTs/Run.out/receipt edges are incomplete")
    prior = row.get("original_omission_evidence", {}).get("report")
    if not isinstance(prior, dict) or not isinstance(prior.get("path"), str) or not isinstance(prior.get("declared_sha256"), str):
        raise ExtractError(f"{case_id} prior omission report edge is incomplete")
    source_dir = _deferred(Path(index["path"]), f"{case_id} native data directory", index.get("stat"), directory=True)
    return {
        "data_dir": source_dir,
        "partout_obi4": _deferred(Path(partout["path"]), f"{case_id} PartOut_000.obi4", partout.get("stat")),
        "runparts_csv": _deferred(Path(runparts["path"]), f"{case_id} RunPARTs.csv", runparts.get("stat")),
        "run_out": _deferred(Path(runout["path"]), f"{case_id} Run.out", runout.get("stat")),
        "solver_receipt": _deferred(Path(receipt["path"]), f"{case_id} solver receipt", receipt.get("stat"), expected_sha=receipt.get("declared_sha256")),
        "prior_native_report": _deferred(Path(prior["path"]), f"{case_id} prior native report", prior.get("stat"), expected_sha=prior.get("declared_sha256")),
        "native_index_scope": index.get("index_scope"),
        "entry_counts": index.get("entry_counts"),
    }


def _source_tool_refs() -> dict[str, Any]:
    if not PARTVTKOUT.is_file() or not os.access(PARTVTKOUT, os.X_OK):
        raise ExtractError(f"official PartVTKOut is missing/not executable: {PARTVTKOUT}")
    tool_sha = _digest(PARTVTKOUT, "official PartVTKOut", max_bytes=MAX_SMALL)
    if tool_sha != PARTVTKOUT_SHA:
        raise ExtractError(f"official PartVTKOut SHA differs: {tool_sha}")
    config_ref = _small_ref(CONFIG, "official DsphConfig.xml")
    return {"partvtkout": {**_stat(PARTVTKOUT, "official PartVTKOut"), "sha256": tool_sha, "source_namespace": "ORIGINAL_LAB_VENDOR", "executable": True, "content_opened_by_preparer": True}, "config": config_ref, "tool_command_template": [str(PARTVTKOUT), "-dirdata", "{native_data_dir}", "-savecsv", "{attempt_root}/PartOut.csv", "-saveresume", "{attempt_root}/resume.csv", "-createdirs:1", "-csvsep:1"]}


def _load_intake() -> Any:
    spec = importlib.util.spec_from_file_location("root245_native_intake_for_extract", INTAKE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ExtractError("cannot load ROOT245 intake parser")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    request, request_edges = _validate_request(args.root245_request)
    inventory_ref = _small_ref(args.inventory, "historical 118 inventory")
    inventory = _load_inventory(args.inventory)
    for case_id in ROOT245_CASES:
        row = inventory.get(case_id)
        if not isinstance(row, dict) or row.get("family_id") != "F6" or row.get("historical_118_membership") is not True:
            raise ExtractError(f"ROOT245 case is not an exact F6 historical inventory row: {case_id}")
    plan_ref = _small_ref(args.plan, "ROOT245 continuation plan", ROOT245_PLAN_SHA)
    plan = _json(args.plan, "ROOT245 continuation plan")
    if plan.get("current_catalog", {}).get("sha256") != CURRENT_SHA or plan.get("scientific_audit", {}).get("sha256") != AUDIT_SHA:
        raise ExtractError("ROOT245 plan CURRENT/audit binding differs")
    tool_refs = _source_tool_refs()
    proof_ref = None
    proof_rows: dict[str, dict[str, Any]] = {}
    if args.terminal_proof is not None:
        _proof, proof_rows = _validate_proof(args.terminal_proof)
        proof_ref = _small_ref(args.terminal_proof, "ROOT245 terminal proof")
    contracts: list[dict[str, Any]] = []
    for case_id in ROOT245_CASES:
        native = _native_edges(inventory[case_id], case_id)
        contract: dict[str, Any] = {"schema": CONTRACT_SCHEMA, "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT_NOT_LAUNCHED", "physical_case_id": case_id, "family_id": "F6", "root245_terminal_required": proof_ref is None, "root245_terminal_proof": proof_ref, "native_deferred": native, "official_tool": tool_refs["partvtkout"], "config": tool_refs["config"], "claim_boundary": {"native_motive": "OFFICIAL_PARTVTKOUT_MOTIVE_ONLY_AFTER_EXACT_PARTOUT_ID_JOIN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
        if proof_rows:
            summary = proof_rows[case_id]["summary"]
            records = proof_rows[case_id]["records_stat_only"]
            contract["typed_deferred"] = {"summary": _deferred(Path(summary["path"]), f"{case_id} typed summary", summary.get("stat"), expected_sha=summary.get("sha256")), "records": _deferred(Path(records["path"]), f"{case_id} typed records", records.get("stat"), expected_sha=records.get("sha256"))}
        else:
            contract["typed_deferred"] = None
        contracts.append(contract)
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise ExtractError(f"refusing to reuse output root: {output_root}")
    contract_dir = output_root / "case-contracts"
    entries: list[dict[str, Any]] = []
    for contract in contracts:
        path = contract_dir / f"{contract['physical_case_id']}.json"
        _atomic(path, contract)
        entries.append({"physical_case_id": contract["physical_case_id"], "family_id": "F6", "path": str(path), "sha256": _digest(path, "case contract", max_bytes=MAX_OUTPUT), "bytes": path.stat().st_size})
    manifest = {"schema": MANIFEST_SCHEMA, "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT_NOT_LAUNCHED", "batch_id": "ROOT245_F6_NATIVE_EXTRACT_V1", "family_id": "F6", "root245_request": request_edges["request"], "root245_manifest": request_edges["manifest"], "root245_plan": plan_ref, "inventory": inventory_ref, "terminal_proof": proof_ref, "official_sources": tool_refs, "cases": entries, "case_count": 7, "declared_native_index_scope": "inventory stat/index only; PartOut/RunPARTs/Run.out content deferred", "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "one_case_at_a_time": True, "typed_jsonl_passes_per_case": 1, "native_obi4_hash_passes": 2, "partvtkout_passes": 1, "runparts_passes": 1, "h5_content_read": False, "solver_launch": False}, "claim_boundary": {"native_motive": "exact official PartOut Motive only", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "launch_allowed": proof_ref is not None, "execution_allowed": proof_ref is not None, "launch_owner": "root", "read_policy": {"prepare_opened_h5": False, "prepare_opened_jsonl": False, "prepare_opened_bi4": False, "prepare_opened_obi4": False, "prepare_opened_partout_csv": False, "prepare_opened_runparts": False, "solver_started": False}}
    manifest_path = output_root / "f6-root245-native-extract-manifest.json"
    _atomic(manifest_path, manifest)
    command = [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/f6-root245-native-extract.json"]
    # The worker opens each case contract after the parent reservation.  Bind
    # those small JSON files explicitly; a manifest entry alone would leave
    # a mutable source edge outside the request's input SHA closure.
    input_refs = [request_edges["request"], request_edges["manifest"], plan_ref, inventory_ref, tool_refs["partvtkout"], tool_refs["config"], _small_ref(INTAKE_SCRIPT, "ROOT245 intake parser"), _small_ref(SCRIPT, "ROOT245 extract worker"), _small_ref(manifest_path, "ROOT245 extract manifest"), *entries]
    if proof_ref:
        input_refs.append(proof_ref)
    input_files = sorted({item["path"] for item in input_refs})
    input_sha = {item["path"]: item["sha256"] for item in input_refs}
    request_out = Path(args.request_output).expanduser().resolve()
    deferred_paths: set[str] = set()
    for contract in contracts:
        for ref in contract["native_deferred"].values():
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                deferred_paths.add(ref["path"])
        typed_deferred = contract.get("typed_deferred")
        if isinstance(typed_deferred, dict):
            for ref in typed_deferred.values():
                if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                    deferred_paths.add(ref["path"])
    root_request = {"schema": REQUEST_SCHEMA, "family_id": "F6", "case_id": "ROOT245_F6_NATIVE_EXTRACT_V1", "physical_case_ids": list(ROOT245_CASES), "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "max_memory_bytes": 4 * 1024 * 1024 * 1024, "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_deferred_read_bytes": 7 * 4 * 1024 * 1024 * 1024, "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": command, "input_files": input_files, "input_sha256": input_sha, "deferred_input_files": sorted(deferred_paths), "manifest_contract": {"path": str(manifest_path), "sha256": input_sha[str(manifest_path)]}, "source_read_cost": manifest["resource_policy"], "claim_boundary": manifest["claim_boundary"], "launch_allowed": bool(proof_ref), "execution_allowed": bool(proof_ref), "launch_owner": "root", "request_note": "ROOT245 terminal proof is mandatory; native PartOut/RunPARTs content is opened only after parent reservation. No solver, no H5 content, and no fate/flux credit."}
    _atomic(request_out, root_request)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "extract manifest", max_bytes=MAX_OUTPUT), "request": str(request_out), "request_sha256": _digest(request_out, "extract request", max_bytes=MAX_OUTPUT), "case_ids": list(ROOT245_CASES), "terminal_proof_bound": proof_ref is not None, "launch_allowed": bool(proof_ref), "payload_content_opened": False}


def audit(args: argparse.Namespace) -> dict[str, Any]:
    """Run the parent-reserved official decoder and exact intake join."""
    manifest = _json(args.manifest, "ROOT245 native extract manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("family_id") != "F6":
        raise ExtractError("ROOT245 extract manifest schema/family differs")
    if manifest.get("launch_allowed") is not True:
        raise ExtractError("ROOT245 terminal proof is required before native extraction")
    intake = _load_intake()
    partvtkout = _path(manifest["official_sources"]["partvtkout"]["path"], "official PartVTKOut")
    if _digest(partvtkout, "official PartVTKOut", max_bytes=MAX_SMALL) != PARTVTKOUT_SHA:
        raise ExtractError("official PartVTKOut SHA differs at audit")
    proof_path = _path(manifest["terminal_proof"]["path"], "ROOT245 terminal proof")
    _proof, proof_rows = _validate_proof(proof_path)
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise ExtractError(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for entry in manifest.get("cases", []):
        case_id = entry.get("physical_case_id")
        case_output = output.parent / "cases" / f"{case_id}.json"
        try:
            contract = _json(Path(entry["path"]), f"{case_id} extract contract")
            typed = contract.get("typed_deferred")
            if not isinstance(typed, dict):
                raise ExtractError(f"{case_id} typed terminal refs are missing")
            targets, typed_evidence = intake._typed_targets(_path(typed["records"]["path"], f"{case_id} typed records"), typed["records"])
            data_dir = _path(contract["native_deferred"]["data_dir"]["path"], f"{case_id} native data directory", directory=True)
            obi4 = _path(contract["native_deferred"]["partout_obi4"]["path"], f"{case_id} PartOut_000.obi4")
            before = _stat(obi4, f"{case_id} PartOut pre")
            pre_sha = _digest(obi4, f"{case_id} PartOut pre")
            work_dir = output.parent / "cases" / case_id
            work_dir.mkdir(parents=True, exist_ok=True)
            csv_path = work_dir / "PartOut.csv"
            resume_path = work_dir / "resume.csv"
            command = [str(partvtkout), "-dirdata", str(data_dir), "-savecsv", str(csv_path), "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"]
            completed = subprocess.run(command, check=False, capture_output=True, text=True, cwd=str(work_dir), timeout=900)
            if completed.returncode != 0:
                raise ExtractError(f"{case_id} PartVTKOut failed: {completed.stderr[-1000:]}")
            if not csv_path.is_file():
                raise ExtractError(f"{case_id} PartVTKOut did not create PartOut.csv")
            csv_ref = {**_stat(csv_path, f"{case_id} generated PartOut.csv"), "sha256": _digest(csv_path, f"{case_id} generated PartOut.csv", max_bytes=64 * 1024 * 1024)}
            native_rows, csv_evidence = intake._partout_rows(csv_path, csv_ref, targets)
            run_ref = contract["native_deferred"]["runparts_csv"]
            times, run_evidence = intake._runparts_times(_path(run_ref["path"], f"{case_id} RunPARTs.csv"), run_ref)
            after = _stat(obi4, f"{case_id} PartOut post")
            post_sha = _digest(obi4, f"{case_id} PartOut post")
            if before != after or pre_sha != post_sha:
                raise ExtractError(f"{case_id} PartOut changed during official decode")
            joined = []
            for key in sorted(targets):
                lo, hi = targets[key]["bracket_s"]
                if not any(abs(lo - t) <= 1e-12 for t in times) or not any(abs(hi - t) <= 1e-12 for t in times):
                    raise ExtractError(f"{case_id} saved bracket is outside RunPARTs saved times: {key}")
                native = native_rows[key]
                joined.append({**targets[key], **native, "identity_key": [key[0], key[1]], "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"})
            report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_F6_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY", "physical_case_id": case_id, "family_id": "F6", "typed": typed_evidence, "native": {"official_tool": {"path": str(partvtkout), "sha256": PARTVTKOUT_SHA, "command": command, "returncode": completed.returncode}, "partout_obi4": {"pre_stat": before, "post_stat": after, "pre_sha256": pre_sha, "post_sha256": post_sha}, "partout_csv": csv_evidence, "runparts": run_evidence}, "counts": {"typed_targets": len(targets), "native_rows": len(native_rows), "joined": len(joined)}, "rows": joined, "claim_boundary": manifest["claim_boundary"], "read_policy": {"parent_reserved": True, "typed_jsonl_read": True, "native_obi4_read_by_official_partvtkout": True, "solver_started": False, "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
            _atomic(case_output, report)
            results.append({"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_output), "joined": len(joined)})
        except (ExtractError, OSError, subprocess.SubprocessError, ValueError) as exc:
            results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "saved_mask_credit": False})
    failed = [r for r in results if r["status"] != "COMPLETED"]
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_ALL_CASES", "batch_id": "ROOT245_F6_NATIVE_EXTRACT_V1", "family_id": "F6", "case_results": results, "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed)}, "claim_boundary": manifest["claim_boundary"], "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    _atomic(output, report)
    return {"status": report["status"], "output": str(output), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--root245-request", type=Path, required=True)
    prep.add_argument("--inventory", type=Path, default=INVENTORY_DEFAULT)
    prep.add_argument("--plan", type=Path, default=PLAN_DEFAULT)
    prep.add_argument("--terminal-proof", type=Path)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    sub.add_parser("self-test")
    return parser


def _self_test() -> dict[str, Any]:
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "case_count": 7, "launch_allowed": False, "payload_opened": False, "checks": ["inventory_partout_and_runparts_edges", "terminal_proof_required", "original_partvtkout_sha", "one_case_at_a_time", "unknown_fate"]}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(args)
        elif args.action == "audit":
            result = audit(args)
        else:
            result = _self_test()
    except (ExtractError, OSError, ValueError) as exc:
        print(f"F6_ROOT245_NATIVE_EXTRACT_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
