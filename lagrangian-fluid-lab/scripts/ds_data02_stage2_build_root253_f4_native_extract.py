#!/usr/bin/env python3
"""Prepare the parent-guarded native extractor for the ROOT253 F4 group.

The lifecycle batch and the native cause audit are separate attempts.  This
source-only preparer binds the exact eight-case ROOT253 request to the current
F4 native ``PartOut_000.obi4``/``RunPARTs.csv`` edges, the original vendor
``PartVTKOut_linux64`` and ``DsphConfig.xml``.  It can be run before the
lifecycle terminal proof (``launch_allowed=false``), or rerun with that proof
once it is complete.  The proof normalizer deliberately accepts the actual
producer shape: ``summary`` is a path string with a sibling
``summary_sha256`` and ``records_stat_only`` is a path/stat dictionary.

``audit`` is the only payload operation.  It must be launched by the parent
runtime after reservation.  It streams the completed typed records, invokes
the official decoder once per case, and joins exact ``(Zone, Idp)`` identities
to the saved RunPARTs bracket.  It never credits physical fate, legal flux,
continuous event time, dynamics, or QI/QN/QE.  Non-members of the historical
118 omission set remain diagnostic-only even when their native join succeeds.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
SCRIPTS = SCRIPT.parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
INVENTORY_DEFAULT = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
PLAN_DEFAULT = STAGE2 / "checkpoints/CURRENT336_TYPED_LIFECYCLE_ROOT245_PENDING_V4.json"
ROOT253_REQUEST_DEFAULT = Path("/tmp/ds02-root253-f4-v1-1791565225772571551/typed-lifecycle-batch-v1-f4-root-forward-253-001.json")
ROOT235_PROOF_DEFAULT = STAGE2 / "checkpoints/F4_NATIVE_TYPED_CAUSE_BATCH_V1_ACTUAL_ROOT_VERIFICATION_235.json"
ROOT250_PROOF_DEFAULT = STAGE2 / "checkpoints/F4_UNLOCATED_NATIVE_EVIDENCE_V4_ACTUAL_ROOT_VERIFICATION_250.json"
OFFICIAL_LAB = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
PARTVTKOUT = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
PARTVTKOUT_SHA256 = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
CONFIG = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
VENV = OFFICIAL_LAB / ".venv/bin/python"
LEGACY_F4_WORKER = SCRIPTS / "ds_data02_stage2_f4_unlocated_native_evidence_v4.py"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
PLAN_SHA256 = "9f3983305503753bc0d7f29ca3ac9cd64a8e0af8dd6452c51176439f1b7d3bf7"
REQUEST_SCHEMA = "ds02.request.v1"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
MANIFEST_SCHEMA = "ds02.stage2.root253-f4-native-extract.v1"
CONTRACT_SCHEMA = "ds02.stage2.root253-f4-native-extract-contract.v1"
REPORT_SCHEMA = "ds02.stage2.root253-f4-native-extract-report.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_TYPED_RECORDS_BYTES = 512 * 1024 * 1024
MAX_CASE_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_PARTVTK_TIMEOUT = 900
F4_GROUP = "F4-typed-lifecycle-continuation-000"
F4_CASES = (
    "F4_DROP_B08_gap0p20000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4_DROP_B08_gap0p21000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4_DROP_gap0p24000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p24000_xoff0p08000_yoffm0p04000_uz0p60000",
    "F4_DROP_gap0p22000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p22000_xoff0p08000_yoffm0p04000_uz0p60000",
    "F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p60000",
)
F4_SET = set(F4_CASES)


class ExtractError(ValueError):
    """Raised for an open source edge or malformed terminal contract."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ExtractError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise ExtractError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise ExtractError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if directory and not path.is_dir():
        raise ExtractError(f"{label} directory is missing: {path}")
    if not directory and not path.is_file():
        raise ExtractError(f"{label} file is missing: {path}")
    return path


def _stat(path: Path, label: str, *, directory: bool = False) -> dict[str, Any]:
    path = _path(path, label, directory=directory)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _digest(path: Path, label: str, *, max_bytes: int | None = None) -> str:
    path = _path(path, label)
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ExtractError(f"{label} exceeds bounded content size")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise ExtractError(f"{label} exceeds bounded JSON size")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExtractError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExtractError(f"{label} must be an object")
    return value


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    stat = _stat(path, label)
    if stat["bytes"] > MAX_SMALL_BYTES:
        raise ExtractError(f"{label} exceeds bounded small source size")
    actual = _digest(path, label, max_bytes=MAX_SMALL_BYTES)
    if expected is not None and expected != "PARENT_GUARD_COMPUTED" and actual != _sha(expected, f"{label} expected SHA"):
        raise ExtractError(f"{label} SHA differs")
    return {**stat, "sha256": actual, "content_opened": True}


def _deferred(path: Path, label: str, *, declared: dict[str, Any] | None = None, expected_sha: str | None = None, directory: bool = False) -> dict[str, Any]:
    stat = _stat(path, label, directory=directory)
    if declared is not None:
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if declared.get(field) is not None and int(declared[field]) != stat[field]:
                raise ExtractError(f"{label} stat differs at {field}")
    return {
        **stat,
        "sha256": expected_sha or "PARENT_GUARD_COMPUTED",
        "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
        "deferred": True,
    }


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise ExtractError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise ExtractError(f"output exceeds {limit} bytes")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_legacy() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_f4_native_legacy_v4", LEGACY_F4_WORKER)
    if spec is None or spec.loader is None:
        raise ExtractError(f"cannot load reviewed F4 parser: {LEGACY_F4_WORKER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _producer_case_ids(path: Path) -> set[str]:
    proof = _json(path, "consumed F4 proof")
    ids: set[str] = set()
    for key in ("case_verifications", "cases", "case_results"):
        rows = proof.get(key)
        if isinstance(rows, list):
            ids.update(row.get("physical_case_id") for row in rows if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str))
    return ids


def _normalize_typed_edge(row: dict[str, Any], case_id: str, name: str) -> dict[str, Any]:
    """Normalize the actual proof's string/dict edge without guessing paths."""
    value = row.get(name)
    if name == "summary" and isinstance(value, str):
        path = value
        expected = row.get("summary_sha256")
    elif isinstance(value, dict):
        path = value.get("path")
        expected = value.get("sha256") or value.get("sha256_hex")
        if expected is None and name == "summary":
            expected = row.get("summary_sha256")
    else:
        raise ExtractError(f"{case_id} terminal proof {name} must be a path string/dict")
    if not isinstance(path, str) or not path:
        raise ExtractError(f"{case_id} terminal proof {name} path is missing")
    if not isinstance(expected, str) or expected == "PARENT_GUARD_COMPUTED":
        raise ExtractError(f"{case_id} terminal proof {name} SHA is missing")
    expected = _sha(expected, f"{case_id} terminal proof {name} SHA")
    declared = value if isinstance(value, dict) else {}
    if name == "records_stat_only" and not isinstance(value, dict):
        raise ExtractError(f"{case_id} records_stat_only must remain a stat dictionary")
    if name == "records_stat_only":
        if not isinstance(declared.get("bytes"), int) or declared["bytes"] <= 0:
            raise ExtractError(f"{case_id} records_stat_only bytes are missing")
        if not isinstance(declared.get("rows"), int) or declared["rows"] <= 0:
            raise ExtractError(f"{case_id} records_stat_only rows are missing")
    # Stat only.  This never opens summary/records content during prepare.
    stat = _stat(Path(path), f"{case_id} terminal proof {name}")
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if declared.get(field) is not None and int(declared[field]) != stat[field]:
            raise ExtractError(f"{case_id} terminal proof {name} stat differs at {field}")
    return {**stat, "sha256": expected, "source_shape": "string" if isinstance(value, str) else "stat_dict", "content_opened_by_preparer": False, "read_after_parent_reservation": True, "deferred": True}


def _validate_terminal_proof(path: Path, selected: list[str]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    proof = _json(path, "ROOT253 F4 terminal proof")
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise ExtractError("ROOT253 proof is not a verified actual terminal proof")
    counts = proof.get("counts")
    if isinstance(counts, dict) and int(counts.get("completed", -1)) != len(selected):
        raise ExtractError("ROOT253 proof completed count differs")
    rows: list[dict[str, Any]] = []
    for key in ("case_verifications", "cases", "case_results"):
        value = proof.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("physical_case_id")
        if case_id in selected:
            if case_id in by_id:
                raise ExtractError(f"ROOT253 proof duplicates {case_id}")
            if row.get("family_id") != "F4" or row.get("status") not in {"VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY", "COMPLETED", "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT"}:
                raise ExtractError(f"ROOT253 proof case is not completed diagnostic-only: {case_id}")
            # Exercise the actual proof shape before emitting the request.
            _normalize_typed_edge(row, case_id, "summary")
            _normalize_typed_edge(row, case_id, "records_stat_only")
            by_id[case_id] = row
    if set(by_id) != set(selected):
        raise ExtractError("ROOT253 proof does not exactly cover selected F4 cases")
    return proof, by_id


def _current_rows(path: Path) -> dict[str, dict[str, Any]]:
    current = _json(path, "CURRENT336")
    if current.get("schema") != CURRENT_SCHEMA:
        raise ExtractError("CURRENT336 schema differs")
    if _digest(path, "CURRENT336", max_bytes=MAX_SMALL_BYTES) != CURRENT_SHA256:
        raise ExtractError("CURRENT336 SHA differs")
    rows = current.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise ExtractError("CURRENT336 must expose 336 cases")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str) or row["physical_case_id"] in by_id:
            raise ExtractError("CURRENT336 identity set is malformed")
        by_id[row["physical_case_id"]] = row
    return by_id


def _inventory_rows(path: Path) -> dict[str, dict[str, Any]]:
    inventory = _json(path, "historical 118 inventory")
    if inventory.get("schema") != "ds02.stage2.historical118-source-inventory.v1":
        raise ExtractError("historical inventory schema differs")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise ExtractError("historical inventory must expose 118 rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str) or row["physical_case_id"] in result:
            raise ExtractError("historical inventory identity set is malformed")
        result[row["physical_case_id"]] = row
    return result


def _validate_root253_request(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _json(path, "ROOT253 F4 lifecycle request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("family_id") != "F4":
        raise ExtractError("ROOT253 lifecycle request schema/family differs")
    if request.get("physical_case_ids") != list(F4_CASES):
        raise ExtractError("ROOT253 lifecycle request case order differs")
    group = request.get("continuation_group")
    if not isinstance(group, dict) or group.get("group_id") != F4_GROUP or group.get("family_id") != "F4" or int(group.get("actual_saved_mask_cases_excluded", -1)) != 87 or int(group.get("historical_alias_cases_excluded", -1)) != 1 or int(group.get("root245_pending_cases_excluded", -1)) != 7:
        raise ExtractError("ROOT253 no-overlap boundary differs")
    manifest = request.get("manifest_contract")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("path"), str):
        raise ExtractError("ROOT253 lifecycle manifest edge is missing")
    manifest_ref = _small_ref(Path(manifest["path"]), "ROOT253 lifecycle manifest", manifest.get("sha256"))
    return request, {"request": _small_ref(path, "ROOT253 lifecycle request"), "manifest": manifest_ref}


def _source_binding_refs(row: dict[str, Any], case_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    bindings = row.get("source_bindings")
    if not isinstance(bindings, dict):
        raise ExtractError(f"{case_id} source_bindings are missing")
    for role in ("generated_xml", "gencase_receipt", "solver_receipt", "owner_metadata"):
        value = bindings.get(role)
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise ExtractError(f"{case_id} source binding {role} is missing")
        expected = value.get("recomputed_sha256") or value.get("sha256")
        refs.append({"role": role, "ref": _small_ref(Path(value["path"]), f"{case_id} {role}", expected)})
    raw = row.get("raw_root")
    if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
        raise ExtractError(f"{case_id} raw_root is missing")
    data_dir = _deferred(Path(raw["path"]), f"{case_id} native data directory", directory=True)
    partout = _deferred(Path(raw["path"]) / "PartOut_000.obi4", f"{case_id} PartOut_000.obi4")
    runparts = _deferred(Path(raw["path"]).parent / "RunPARTs.csv", f"{case_id} RunPARTs.csv")
    static = {"bindings": {item["role"]: item["ref"] for item in refs}, "raw_root": {"path": str(Path(raw["path"]).expanduser().resolve()), "content_opened_by_preparer": False}}
    native = {"data_dir": data_dir, "partout_obi4": partout, "runparts_csv": runparts}
    inventory_membership = {"historical_118_membership": False}
    return refs, {"native": native, "static": static, "membership": inventory_membership}


def _contract(case_id: str, row: dict[str, Any], inventory_row: dict[str, Any] | None, proof_row: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    refs, edge = _source_binding_refs(row, case_id)
    if inventory_row is not None:
        edge["membership"] = {"historical_118_membership": inventory_row.get("historical_118_membership") is True, "evidence_scope": "ORIGINAL118" if inventory_row.get("historical_118_membership") is True else "CURRENT336_ONLY"}
    typed = None
    if proof_row is not None:
        typed = {"summary": _normalize_typed_edge(proof_row, case_id, "summary"), "records": _normalize_typed_edge(proof_row, case_id, "records_stat_only")}
    contract = {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_F4_NATIVE_EXTRACT_NOT_LAUNCHED",
        "physical_case_id": case_id,
        "family_id": "F4",
        "historical_118_membership": edge["membership"],
        "native_deferred": edge["native"],
        "typed_deferred": typed,
        "source_bindings": edge["static"],
        "official_decoder": {"path": str(PARTVTKOUT), "sha256": PARTVTKOUT_SHA256, "config_path": str(CONFIG)},
        "claim_boundary": {"native_motive": "OFFICIAL_PARTVTKOUT_SAVED_NUMERICAL_MOTIVE_ONLY", "saved_bracket": "SAVED_RUNPARTS_BRACKET_ONLY", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare": "small JSON/stat/source files only; no trajectory/OBI4/BI4/CSV payload", "audit": "typed records and native PartOut/RunPARTs only after parent reservation", "solver_started": False},
    }
    return contract, refs


def _source_tool_refs() -> list[dict[str, Any]]:
    tool = _small_ref(PARTVTKOUT, "official PartVTKOut")
    if tool["sha256"] != PARTVTKOUT_SHA256 or not os.access(PARTVTKOUT, os.X_OK):
        raise ExtractError("official PartVTKOut SHA/executable binding differs")
    return [tool, _small_ref(CONFIG, "official DsphConfig.xml"), _small_ref(LEGACY_F4_WORKER, "reviewed F4 parser/worker"), _small_ref(SCRIPT, "ROOT253 F4 native extractor"), _small_ref(VENV, "configured literal interpreter"), _small_ref(VENV.parent.parent / "pyvenv.cfg", "configured pyvenv.cfg")]


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    lifecycle, lifecycle_edges = _validate_root253_request(args.root253_request)
    current = _current_rows(args.current)
    inventory = _inventory_rows(args.inventory)
    if set(F4_CASES) - set(current):
        raise ExtractError("ROOT253 cases are not all in CURRENT336")
    consumed: set[str] = set()
    for proof_path in (args.root235_proof, args.root250_proof):
        if proof_path.is_file():
            consumed.update(_producer_case_ids(proof_path))
    if consumed & F4_SET:
        raise ExtractError(f"ROOT253 group overlaps consumed F4 native evidence: {sorted(consumed & F4_SET)}")
    proof_ref = None
    proof_rows: dict[str, dict[str, Any]] = {}
    if args.terminal_proof is not None:
        proof, proof_rows = _validate_terminal_proof(args.terminal_proof, list(F4_CASES))
        proof_ref = _small_ref(args.terminal_proof, "ROOT253 F4 terminal proof")
    tool_refs = _source_tool_refs()
    contracts: list[dict[str, Any]] = []
    contract_refs: list[dict[str, Any]] = []
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise ExtractError(f"refusing to reuse output root: {output_root}")
    contract_dir = output_root / "case-contracts"
    for case_id in F4_CASES:
        contract, refs = _contract(case_id, current[case_id], inventory.get(case_id), proof_rows.get(case_id))
        path = contract_dir / f"{case_id}.json"
        _atomic(path, contract, limit=MAX_OUTPUT_BYTES)
        contract_ref = {"physical_case_id": case_id, "path": str(path), "sha256": _digest(path, "case contract", max_bytes=MAX_OUTPUT_BYTES), "bytes": int(path.stat().st_size)}
        contracts.append(contract)
        contract_refs.append(contract_ref)
        refs.append({"role": "case_contract", "ref": contract_ref})
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_F4_NATIVE_EXTRACT_NOT_LAUNCHED" if proof_ref is None else "READY_PARENT_GUARDED_F4_NATIVE_EXTRACT",
        "batch_id": "ROOT253_F4_NATIVE_EXTRACT_V1",
        "family_id": "F4",
        "group_id": F4_GROUP,
        "physical_case_ids": list(F4_CASES),
        "root253_lifecycle_request": lifecycle_edges["request"],
        "root253_lifecycle_manifest": lifecycle_edges["manifest"],
        "current336": {"path": str(args.current.expanduser().resolve()), "sha256": CURRENT_SHA256},
        "inventory": {"path": str(args.inventory.expanduser().resolve()), "sha256": _digest(args.inventory, "historical inventory", max_bytes=MAX_SMALL_BYTES)},
        "consumed_f4_evidence_excluded": sorted(consumed & F4_SET),
        "terminal_proof": proof_ref,
        "contracts": contract_refs,
        "official_sources": tool_refs,
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "one_case_at_a_time": True, "typed_records_passes_per_case": 1, "native_obi4_hash_passes": 2, "partvtkout_passes": 1, "runparts_passes": 1, "h5_content_read": False, "solver_started": False},
        "claim_boundary": {"native_motive": "NUMERICAL_PARTVTKOUT_MOTIVE_ONLY", "historical118_cause_credit": "ONLY_IF_CASE_IS_EXACT_ORIGINAL118_MEMBER_AND_JOIN_IS_COMPLETE", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare": "JSON/stat/source SHA only; no H5/BI4/OBI4/PartOut/RunPARTs content", "audit": "parent reservation required before deferred typed/native reads", "payload_content_opened_by_preparer": False},
        "launch_allowed": proof_ref is not None,
        "execution_allowed": proof_ref is not None,
        "launch_owner": "root",
    }
    manifest_path = output_root / "root253-f4-native-extract-manifest.json"
    _atomic(manifest_path, manifest)
    static_refs: list[dict[str, Any]] = [lifecycle_edges["request"], lifecycle_edges["manifest"], _small_ref(args.current, "CURRENT336", CURRENT_SHA256), _small_ref(args.inventory, "historical inventory"), *tool_refs, _small_ref(manifest_path, "ROOT253 native manifest")]
    if proof_ref is not None:
        static_refs.append(proof_ref)
    # Contract JSONs are already complete and bounded.  Bind their immutable
    # bytes; all raw native/typed payloads stay deferred.
    static_refs.extend(contract_refs)
    input_sha = {ref["path"]: ref["sha256"] for ref in static_refs}
    deferred_records: list[dict[str, Any]] = []
    for contract in contracts:
        deferred_records.extend(contract["native_deferred"].values())
        if isinstance(contract.get("typed_deferred"), dict):
            deferred_records.extend(contract["typed_deferred"].values())
    command = [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/root253-f4-native-extract.json"]
    if proof_ref is not None:
        command.extend(["--terminal-proof", str(args.terminal_proof.expanduser().absolute())])
    request = {
        "schema": REQUEST_SCHEMA, "shared_runtime_version": "v8", "family_id": "F4", "case_id": "ROOT253_F4_NATIVE_EXTRACT_V1", "physical_case_ids": list(F4_CASES), "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "max_memory_bytes": 4 * 1024 * 1024 * 1024, "estimated_storage_bytes": MAX_OUTPUT_BYTES, "estimated_deferred_read_bytes": sum(int(c["native_deferred"]["partout_obi4"]["bytes"]) for c in contracts) + 8 * MAX_TYPED_RECORDS_BYTES, "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": command, "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())), "deferred_input_files": sorted({str(ref["path"]) for ref in deferred_records}), "deferred_input_records": deferred_records, "manifest_contract": {"path": str(manifest_path), "sha256": input_sha[str(manifest_path)]}, "official_tool": {"path": str(PARTVTKOUT), "sha256": PARTVTKOUT_SHA256}, "official_config": {"path": str(CONFIG), "sha256": next(ref["sha256"] for ref in tool_refs if ref["path"] == str(CONFIG))}, "launch_allowed": proof_ref is not None, "execution_allowed": proof_ref is not None, "launch_owner": "root", "claim_boundary": manifest["claim_boundary"], "request_note": "ROOT253 F4 native extraction is deferred until the exact terminal proof is bound. Official PartVTKOut and DsphConfig are source-closed; physical fate, flux, dynamics, and Q remain UNKNOWN."}
    request_path = args.request_output.expanduser().resolve()
    _atomic(request_path, request)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT253 native manifest", max_bytes=MAX_OUTPUT_BYTES), "request": str(request_path), "request_sha256": _digest(request_path, "ROOT253 native request", max_bytes=MAX_OUTPUT_BYTES), "case_ids": list(F4_CASES), "terminal_proof_bound": proof_ref is not None, "launch_allowed": proof_ref is not None, "payload_content_opened": False, "historical118_membership_cases": sum(1 for case_id in F4_CASES if current[case_id]["physical_case_id"] in inventory), "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def _audit_one(contract: dict[str, Any], proof: dict[str, Any], output_dir: Path, legacy: Any) -> dict[str, Any]:
    case_id = contract["physical_case_id"]
    rows = [row for key in ("case_verifications", "cases", "case_results") for row in (proof.get(key) if isinstance(proof.get(key), list) else []) if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(rows) != 1:
        raise ExtractError(f"{case_id} terminal proof row is not unique")
    proof_row = rows[0]
    summary_ref = _normalize_typed_edge(proof_row, case_id, "summary")
    records_ref = _normalize_typed_edge(proof_row, case_id, "records_stat_only")
    summary_path = _path(summary_ref["path"], f"{case_id} typed summary")
    summary, summary_evidence = legacy._guarded_json(summary_path, f"{case_id} typed summary", expected_sha=summary_ref["sha256"], max_bytes=MAX_SMALL_BYTES)
    if summary.get("physical_case_id") != case_id or summary.get("family_id") != "F4":
        raise ExtractError(f"{case_id} typed summary identity differs")
    records_path = _path(records_ref["path"], f"{case_id} typed records")
    header, records, typed_evidence = legacy._iter_records(records_path, records_ref["sha256"], summary, case_id)
    target = typed_evidence.get("first_missing")
    if not target:
        raise ExtractError(f"{case_id} has no typed fluid target; empty target is not a pass")
    data_dir = _path(contract["native_deferred"]["data_dir"]["path"], f"{case_id} native data directory", directory=True)
    obi4 = _path(contract["native_deferred"]["partout_obi4"]["path"], f"{case_id} PartOut_000.obi4")
    before = legacy._stat(obi4, f"{case_id} PartOut pre")
    pre_sha = legacy._sha256_file(obi4)
    case_dir = output_dir / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    csv_path = case_dir / "PartOut.csv"
    resume_path = case_dir / "resume.csv"
    if csv_path.exists() or resume_path.exists():
        raise ExtractError(f"{case_id} decoder output already exists")
    command = [str(PARTVTKOUT), "-dirdata", str(data_dir), "-savecsv", str(csv_path), "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, cwd=str(case_dir), timeout=MAX_PARTVTK_TIMEOUT)
    if completed.returncode != 0:
        raise ExtractError(f"{case_id} official PartVTKOut failed: {completed.stderr[-1000:]}")
    if not csv_path.is_file() or not resume_path.is_file():
        raise ExtractError(f"{case_id} official PartVTKOut did not create CSV/resume")
    native_rows, csv_evidence = legacy._partout_csv(csv_path)
    runparts = _path(contract["native_deferred"]["runparts_csv"]["path"], f"{case_id} RunPARTs.csv")
    runparts_evidence = legacy._runparts(runparts, summary)
    after = legacy._stat(obi4, f"{case_id} PartOut post")
    post_sha = legacy._sha256_file(obi4)
    if before != after or pre_sha != post_sha:
        raise ExtractError(f"{case_id} PartOut changed during official decoder")
    zones = {key[0] for key in target}
    if zones != {0}:
        raise ExtractError(f"{case_id} typed target zones cannot be inferred from PartOut.csv")
    native_by_key = {(0, row["idp"]): row for row in native_rows}
    if not set(target).issubset(native_by_key):
        raise ExtractError(f"{case_id} official PartVTKOut lacks exact typed target identity")
    joined = []
    for key in sorted(target):
        typed = target[key]
        native = native_by_key[key]
        joined.append({"zone": key[0], "idp": key[1], "initial_role": typed.get("initial_role"), "first_disappeared_frame": typed.get("first_disappeared_frame"), "first_disappeared_time_s": typed.get("first_disappeared_time_s"), "first_disappeared_bracket_s": typed.get("first_disappeared_bracket_s"), "native_part_out": native["part_out"], "native_motive_code": native["motive_code"], "native_motive": native["motive"], "native_exit_cause": "NUMERICAL_" + native["motive"].upper() if native["motive"] != "UNKNOWN_MOTIVE" else "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"})
    membership = contract["historical_118_membership"]
    typed_report = dict(typed_evidence)
    typed_report["first_missing"] = [{"zone": key[0], "idp": key[1], "record": value} for key, value in sorted(target.items())]
    return {"schema": REPORT_SCHEMA, "status": "COMPLETED_F4_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY", "physical_case_id": case_id, "family_id": "F4", "historical_118_membership": membership, "typed": {"header": header, "summary": summary_evidence, "records": typed_report, "source_summary": summary_ref, "source_records": records_ref}, "native": {"official_tool": {"path": str(PARTVTKOUT), "sha256": PARTVTKOUT_SHA256, "command": command, "returncode": completed.returncode}, "partout_obi4": {"pre_stat": before, "post_stat": after, "pre_sha256": pre_sha, "post_sha256": post_sha}, "partout_csv": csv_evidence, "runparts": runparts_evidence}, "exact_join": {"count": len(joined), "rows": joined, "identity_key": "(Zone, Idp)", "no_empty_target_shortcut": True}, "claim_boundary": contract["claim_boundary"], "read_policy": {"typed_records_opened_after_parent_reservation": True, "native_obi4_opened_by_official_partvtkout": True, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _json(args.manifest, "ROOT253 native manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("family_id") != "F4" or manifest.get("launch_allowed") is not True:
        raise ExtractError("ROOT253 manifest is not terminal-proof bound")
    proof_path = args.terminal_proof or Path(manifest["terminal_proof"]["path"])
    proof, proof_rows = _validate_terminal_proof(proof_path, list(F4_CASES))
    legacy = _load_legacy()
    if _digest(PARTVTKOUT, "official PartVTKOut", max_bytes=MAX_SMALL_BYTES) != PARTVTKOUT_SHA256:
        raise ExtractError("official PartVTKOut SHA differs at audit")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise ExtractError(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for entry in manifest.get("contracts", []):
        case_id = entry.get("physical_case_id")
        try:
            contract = _json(Path(entry["path"]), f"{case_id} case contract")
            if contract.get("physical_case_id") != case_id or contract.get("typed_deferred") is None:
                raise ExtractError(f"{case_id} terminal typed edges are missing")
            case_report = _audit_one(contract, proof, output.parent, legacy)
            case_path = output.parent / "cases" / f"{case_id}.json"
            _atomic(case_path, case_report, limit=MAX_CASE_OUTPUT_BYTES)
            results.append({"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_path), "joined": case_report["exact_join"]["count"]})
        except (ExtractError, OSError, subprocess.SubprocessError, ValueError) as exc:
            results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "saved_mask_credit": False})
    failed = [row for row in results if row["status"] != "COMPLETED"]
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_ALL_CASES", "batch_id": "ROOT253_F4_NATIVE_EXTRACT_V1", "family_id": "F4", "case_results": results, "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed)}, "claim_boundary": manifest["claim_boundary"], "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    _atomic(output, report)
    return {"status": report["status"], "output": str(output), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"]}


def _self_test() -> dict[str, Any]:
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "family_id": "F4", "case_count": 8, "launch_allowed": False, "payload_opened": False, "checks": ["ROOT253 exact eight-case group", "ROOT235/250 non-overlap", "official PartVTKOut and DsphConfig closure", "summary string plus records_stat_only proof shape", "physical fate UNKNOWN"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--root253-request", type=Path, default=ROOT253_REQUEST_DEFAULT)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--inventory", type=Path, default=INVENTORY_DEFAULT)
    prep.add_argument("--terminal-proof", type=Path)
    prep.add_argument("--root235-proof", type=Path, default=ROOT235_PROOF_DEFAULT)
    prep.add_argument("--root250-proof", type=Path, default=ROOT250_PROOF_DEFAULT)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--manifest", type=Path, required=True)
    audit_parser.add_argument("--terminal-proof", type=Path)
    audit_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args) if args.action == "prepare" else audit(args)
    except (ExtractError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"ROOT253_F4_NATIVE_EXTRACT_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
