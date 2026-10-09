#!/usr/bin/env python3
"""Prepare and run a generic parent-guarded native extractor.

The lifecycle producer is deliberately decoupled from native cause intake.
This worker accepts an exact F4/F6 lifecycle request and either ROOT253 or
ROOT256 (or a later request with the same ``ds02.request.v1`` contract).  It
does not contain a frozen ROOT245 case list.  The request's case IDs are the
only selected population; every ID is checked for uniqueness against CURRENT,
the optional historical-118 inventory, prior consumed reports, and the
terminal proof.

``prepare`` reads bounded JSON/source metadata and file statistics only.  H5,
JSONL, BI4/OBI4, PartOut, and RunPARTs payloads remain deferred.  Once the
parent supplies a completed terminal proof, ``audit`` streams the typed
records, invokes the ORIGINAL official PartVTKOut and joins exact ``(Zone,
Idp)`` rows to RunPARTs saved brackets.  The output is a numerical saved-frame
diagnostic; physical fate, legal flux, continuous event time, dynamics, and
QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
ORIGINAL_PRIMARY = Path("/home/jade/Projects/DualSPHysics")
OFFICIAL_LAB = ORIGINAL_PRIMARY / "lagrangian-fluid-lab"
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
SCRIPTS = PRIMARY / "lagrangian-fluid-lab/scripts"
INTAKE = SCRIPTS / "ds_data02_stage2_f6_root245_native_cause_intake_v1.py"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
INVENTORY_DEFAULT = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
PARTVTKOUT = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
PARTVTKOUT_SHA = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
CONFIG = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml"
VENV = OFFICIAL_LAB / ".venv/bin/python"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
REQUEST_SCHEMA = "ds02.request.v1"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
INVENTORY_SCHEMA = "ds02.stage2.historical118-source-inventory.v1"
MANIFEST_SCHEMA = "ds02.stage2.generic-native-extract.v1"
CONTRACT_SCHEMA = "ds02.stage2.generic-native-extract-contract.v1"
REPORT_SCHEMA = "ds02.stage2.generic-native-extract-report.v1"
MAX_CASES = 8
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_TYPED_BYTES = 4 * 1024 * 1024 * 1024
MAX_NATIVE_CSV_BYTES = 64 * 1024 * 1024
MAX_PARTVTK_TIMEOUT = 900
PAYLOAD_SUFFIXES = {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}
CASE_STATUS = {
    "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
    "COMPLETED",
    "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT",
}


class GenericExtractError(ValueError):
    """Raised for a stale identity or unsafe native extraction contract."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise GenericExtractError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise GenericExtractError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise GenericExtractError(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if directory and not path.is_dir():
        raise GenericExtractError(f"{label} directory is missing: {path}")
    if not directory and not path.is_file():
        raise GenericExtractError(f"{label} file is missing: {path}")
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
        raise GenericExtractError(f"{label} exceeds bounded read")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise GenericExtractError(f"{label} exceeds small JSON bound")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GenericExtractError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise GenericExtractError(f"{label} must be an object")
    return value


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    value = _stat(path, label)
    if value["bytes"] > MAX_SMALL_BYTES:
        raise GenericExtractError(f"{label} exceeds small source bound")
    actual = _digest(path, label, max_bytes=MAX_SMALL_BYTES)
    if expected is not None and expected != "PARENT_GUARD_COMPUTED" and actual != _sha(expected, f"{label} expected SHA"):
        raise GenericExtractError(f"{label} SHA differs")
    value.update({"sha256": actual, "content_opened": True})
    return value


def _deferred(path: Path, label: str, declared: dict[str, Any] | None = None, *, directory: bool = False, expected: str | None = None) -> dict[str, Any]:
    value = _stat(path, label, directory=directory)
    if isinstance(declared, dict):
        for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if declared.get(field) is not None and int(declared[field]) != value[field]:
                raise GenericExtractError(f"{label} stat differs at {field}")
    value.update({"sha256": expected or "PARENT_GUARD_COMPUTED", "content_opened_by_preparer": False, "read_after_parent_reservation": True, "deferred": True})
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise GenericExtractError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise GenericExtractError(f"{path} exceeds output limit")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha_from_ref(value: Any, label: str) -> str | None:
    if isinstance(value, dict):
        candidate = value.get("sha256") or value.get("recomputed_sha256") or value.get("producer_declared_sha256")
    else:
        candidate = value
    if candidate is None:
        return None
    return _sha(candidate, label)


def _validate_request(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[str], str]:
    request = _json(path, "lifecycle request")
    if request.get("schema") != REQUEST_SCHEMA:
        raise GenericExtractError("lifecycle request schema differs")
    family = request.get("family_id")
    if not isinstance(family, str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,15}", family):
        raise GenericExtractError("lifecycle family id is malformed")
    case_ids = request.get("physical_case_ids")
    if not isinstance(case_ids, list) or not (1 <= len(case_ids) <= MAX_CASES) or any(not isinstance(item, str) or not item for item in case_ids):
        raise GenericExtractError("lifecycle case list is malformed")
    if len(case_ids) != len(set(case_ids)):
        raise GenericExtractError("lifecycle request contains duplicate case IDs")
    group = request.get("continuation_group")
    if isinstance(group, dict) and group.get("case_ids") is not None and group.get("case_ids") != case_ids:
        raise GenericExtractError("lifecycle continuation group case IDs differ")
    manifest = request.get("manifest_contract")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("path"), str):
        raise GenericExtractError("lifecycle manifest contract is missing")
    manifest_ref = _small_ref(Path(manifest["path"]), "lifecycle manifest", manifest.get("sha256"))
    request_ref = _small_ref(path, "lifecycle request")
    for source in request.get("input_files", []):
        if isinstance(source, str) and Path(source).suffix.lower() in PAYLOAD_SUFFIXES:
            raise GenericExtractError(f"payload entered static lifecycle closure: {source}")
    return request, {"request": request_ref, "manifest": manifest_ref}, list(case_ids), family


def _load_current(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    ref = _small_ref(path, "CURRENT336 catalog", CURRENT_SHA)
    value = _json(path, "CURRENT336 catalog")
    if value.get("schema") != CURRENT_SCHEMA:
        raise GenericExtractError("CURRENT336 schema differs")
    rows = value.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise GenericExtractError("CURRENT336 must contain exactly 336 cases")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("physical_case_id") if isinstance(row, dict) else None
        if not isinstance(case_id, str) or case_id in result:
            raise GenericExtractError("CURRENT336 identity set is malformed")
        result[case_id] = row
    return result, ref


def _load_inventory(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    ref = _small_ref(path, "historical 118 inventory")
    value = _json(path, "historical 118 inventory")
    if value.get("schema") != INVENTORY_SCHEMA:
        raise GenericExtractError("historical inventory schema differs")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise GenericExtractError("historical inventory must contain exactly 118 rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("physical_case_id") if isinstance(row, dict) else None
        if not isinstance(case_id, str) or case_id in result:
            raise GenericExtractError("historical inventory identity set is malformed")
        result[case_id] = row
    return result, ref


def _collect_case_ids(value: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    direct = value.get("physical_case_ids")
    if isinstance(direct, list):
        found.update(item for item in direct if isinstance(item, str))
    for key in ("case_verifications", "cases", "case_results", "results"):
        rows = value.get(key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str):
                    found.add(row["physical_case_id"])
    return found


def _consumed_ids(paths: list[Path]) -> tuple[set[str], list[dict[str, Any]]]:
    ids: set[str] = set()
    refs: list[dict[str, Any]] = []
    for path in paths:
        value = _json(path, f"consumed native evidence {path}")
        ref = _small_ref(path, f"consumed native evidence {path}")
        local = _collect_case_ids(value)
        ids.update(local)
        refs.append({**ref, "case_ids": sorted(local)})
    return ids, refs


def _proof_edge(value: Any, row: dict[str, Any], name: str, case_id: str, *, records: bool = False) -> dict[str, Any]:
    if isinstance(value, str):
        path = value
        expected = row.get(f"{name}_sha256")
        declared: dict[str, Any] = {}
    elif isinstance(value, dict):
        path = value.get("path")
        expected = value.get("sha256") or value.get("sha256_hex") or row.get(f"{name}_sha256")
        declared = value
    else:
        raise GenericExtractError(f"{case_id} proof {name} edge is malformed")
    if not isinstance(path, str) or not isinstance(expected, str) or expected == "PARENT_GUARD_COMPUTED":
        raise GenericExtractError(f"{case_id} proof {name} path/SHA is missing")
    expected = _sha(expected, f"{case_id} proof {name} SHA")
    if records:
        stat = _deferred(Path(path), f"{case_id} typed records", declared, expected=expected)
        if not isinstance(declared.get("rows"), int) or int(declared["rows"]) <= 0:
            raise GenericExtractError(f"{case_id} typed records rows are missing")
        stat["rows"] = int(declared["rows"])
        return stat
    return _small_ref(Path(path), f"{case_id} typed summary", expected)


def _proof_output(value: Any, proof: dict[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise GenericExtractError(f"terminal proof {name} must be a path string")
    expected = proof.get(f"{name}_sha256")
    if not isinstance(expected, str) or expected == "PARENT_GUARD_COMPUTED":
        raise GenericExtractError(f"terminal proof {name} SHA is missing")
    path = _path(value, f"terminal proof {name}")
    if path.stat().st_size <= MAX_SMALL_BYTES:
        return _small_ref(path, f"terminal proof {name}", expected)
    return _deferred(path, f"terminal proof {name}", expected=expected)


def _validate_proof(path: Path, selected: list[str], family: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    proof = _json(path, "lifecycle terminal proof")
    if proof.get("schema") != PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise GenericExtractError("terminal proof is not a verified actual proof")
    counts = proof.get("counts")
    completed = counts.get("completed") if isinstance(counts, dict) else None
    if completed is None and isinstance(counts, dict):
        completed = counts.get("cases_completed")
    if int(completed if completed is not None else -1) != len(selected):
        raise GenericExtractError("terminal proof completed count differs from selected request")
    rows: list[dict[str, Any]] = []
    for key in ("case_verifications", "cases", "case_results"):
        value = proof.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("physical_case_id")
        if case_id not in selected:
            continue
        if case_id in by_id:
            raise GenericExtractError(f"terminal proof duplicates case ID: {case_id}")
        if row.get("family_id") != family or row.get("status") not in CASE_STATUS:
            raise GenericExtractError(f"terminal proof case status/family differs: {case_id}")
        if row.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
            raise GenericExtractError(f"terminal proof H5 source closure is not proven: {case_id}")
        if row.get("native_cause_fate_legal_flux_dynamics") not in (None, "UNKNOWN"):
            raise GenericExtractError(f"terminal proof grants unsupported physical credit: {case_id}")
        row_copy = dict(row)
        row_copy["_typed_summary_ref"] = _proof_edge(row.get("summary"), row, "summary", case_id)
        row_copy["_typed_records_ref"] = _proof_edge(row.get("records_stat_only"), row, "records_stat_only", case_id, records=True)
        by_id[case_id] = row_copy
    if set(by_id) != set(selected):
        raise GenericExtractError("terminal proof does not exactly cover selected case IDs")
    batch_edges: dict[str, Any] = {}
    for name in ("batch_summary", "report"):
        if name in proof:
            batch_edges[name] = _proof_output(proof[name], proof, name)
    return proof, by_id, batch_edges


def _source_path(row: dict[str, Any], name: str) -> tuple[Path, str | None, dict[str, Any] | None]:
    value = row.get(name)
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise GenericExtractError(f"CURRENT source edge {name} is missing")
    return Path(value["path"]), _sha_from_ref(value, f"CURRENT {name} SHA"), value.get("stat") if isinstance(value.get("stat"), dict) else value


def _find_artifact(entries: Any, role: str, case_id: str) -> tuple[Path, str | None, dict[str, Any] | None]:
    if not isinstance(entries, list):
        raise GenericExtractError(f"{case_id} native artifact index is missing")
    for item in entries:
        if isinstance(item, dict) and item.get("role") == role and isinstance(item.get("path"), str):
            return Path(item["path"]), _sha_from_ref(item, f"{case_id} {role} SHA"), item.get("stat") if isinstance(item.get("stat"), dict) else item
    raise GenericExtractError(f"{case_id} native artifact role is missing: {role}")


def _native_edges(case_id: str, current: dict[str, Any], inventory: dict[str, Any] | None) -> dict[str, Any]:
    source = inventory.get("source_artifacts", {}).get("artifacts", {}) if isinstance(inventory, dict) else {}
    index = source.get("native_part_directory_stat_index") if isinstance(source, dict) else None
    solver = source.get("solver_output") if isinstance(source, dict) else None
    if isinstance(index, dict) and isinstance(index.get("path"), str):
        directory = _deferred(Path(index["path"]), f"{case_id} native data directory", index.get("stat"), directory=True)
        part_path, part_sha, part_decl = _find_artifact(index.get("entry_samples"), "native_part_directory:PartOut_000.obi4", case_id)
        part = _deferred(part_path, f"{case_id} PartOut_000.obi4", part_decl, expected=part_sha)
        artifacts = solver.get("artifacts") if isinstance(solver, dict) else None
        run_path, run_sha, run_decl = _find_artifact(artifacts, "solver_output:RunPARTs.csv", case_id)
        run = _deferred(run_path, f"{case_id} RunPARTs.csv", run_decl, expected=run_sha)
        runout_path, runout_sha, runout_decl = _find_artifact(artifacts, "solver_output:Run.out", case_id)
        runout = _deferred(runout_path, f"{case_id} Run.out", runout_decl, expected=runout_sha)
        receipt_path, receipt_sha, receipt_decl = _find_artifact(artifacts, "solver_receipt", case_id)
        receipt = _deferred(receipt_path, f"{case_id} solver receipt", receipt_decl, expected=receipt_sha)
        return {"data_dir": directory, "partout_obi4": part, "runparts_csv": run, "run_out": runout, "solver_receipt": receipt, "source_index_scope": index.get("index_scope")}
    raw = current.get("raw_root")
    if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
        raise GenericExtractError(f"{case_id} CURRENT raw_root is missing")
    data_path = Path(raw["path"])
    directory = _deferred(data_path, f"{case_id} native data directory", directory=True)
    part = _deferred(data_path / "PartOut_000.obi4", f"{case_id} PartOut_000.obi4")
    solver_root = data_path.parent
    run = _deferred(solver_root / "RunPARTs.csv", f"{case_id} RunPARTs.csv")
    runout = _deferred(solver_root / "Run.out", f"{case_id} Run.out")
    bindings = current.get("source_bindings") if isinstance(current.get("source_bindings"), dict) else {}
    receipt_value = bindings.get("solver_receipt")
    receipt_path = Path(receipt_value["path"]) if isinstance(receipt_value, dict) and isinstance(receipt_value.get("path"), str) else solver_root.parent / "execution-receipt.json"
    receipt = _deferred(receipt_path, f"{case_id} solver receipt", expected=_sha_from_ref(receipt_value, f"{case_id} solver receipt SHA") if isinstance(receipt_value, dict) else None)
    return {"data_dir": directory, "partout_obi4": part, "runparts_csv": run, "run_out": runout, "solver_receipt": receipt, "source_index_scope": "CURRENT raw_root path only"}


def _static_case_refs(case_id: str, current: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for role, value in (("manifest", current.get("manifest")), ("xmf", current.get("xmf")), ("conversion_report", current.get("conversion_report"))):
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            refs.append({"role": role, "ref": _small_ref(Path(value["path"]), f"{case_id} {role}", _sha_from_ref(value, f"{case_id} {role} SHA"))})
    bindings = current.get("source_bindings")
    if isinstance(bindings, dict):
        for role, value in sorted(bindings.items()):
            if isinstance(value, dict) and isinstance(value.get("path"), str):
                refs.append({"role": role, "ref": _small_ref(Path(value["path"]), f"{case_id} source binding {role}", _sha_from_ref(value, f"{case_id} source binding {role} SHA"))})
    return refs


def _load_intake() -> Any:
    spec = importlib.util.spec_from_file_location("generic_native_intake", INTAKE)
    if spec is None or spec.loader is None:
        raise GenericExtractError("cannot load reviewed native intake parser")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _official_refs() -> list[dict[str, Any]]:
    if not PARTVTKOUT.is_file() or not os.access(PARTVTKOUT, os.X_OK):
        raise GenericExtractError(f"official PartVTKOut is missing/not executable: {PARTVTKOUT}")
    tool = _small_ref(PARTVTKOUT, "official PartVTKOut")
    if tool["sha256"] != PARTVTKOUT_SHA:
        raise GenericExtractError("official PartVTKOut SHA differs")
    return [tool, _small_ref(CONFIG, "official DsphConfig.xml"), _small_ref(INTAKE, "reviewed native intake parser"), _small_ref(SCRIPT, "generic native extractor"), _small_ref(VENV, "original literal Python interpreter"), _small_ref(VENV.parent.parent / "pyvenv.cfg", "original Python pyvenv.cfg")]


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(r"ROOT(?:257|258|[0-9]{3,})", args.namespace):
        raise GenericExtractError("namespace must be a ROOT257/ROOT258-style immutable attempt label")
    if len(args.exclude_case) != len(set(args.exclude_case)):
        raise GenericExtractError("explicit excluded case IDs contain duplicates")
    lifecycle, lifecycle_refs, case_ids, family = _validate_request(args.lifecycle_request)
    current, current_ref = _load_current(args.current)
    inventory, inventory_ref = _load_inventory(args.inventory)
    if any(case_id not in current for case_id in case_ids):
        raise GenericExtractError("selected lifecycle case is absent from CURRENT336")
    if any(current[case_id].get("family_id") != family for case_id in case_ids):
        raise GenericExtractError("selected lifecycle case family differs from request")
    consumed_ids, consumed_refs = _consumed_ids(args.consumed_report)
    explicit_excluded = set(args.exclude_case)
    overlap = (set(case_ids) & (consumed_ids | explicit_excluded))
    if overlap:
        raise GenericExtractError(f"selected case overlaps consumed/excluded evidence: {sorted(overlap)}")
    terminal_ref = None
    proof_rows: dict[str, dict[str, Any]] = {}
    proof_edges: dict[str, Any] = {}
    if args.terminal_proof is not None:
        proof, proof_rows, proof_edges = _validate_proof(args.terminal_proof, case_ids, family)
        terminal_ref = _small_ref(args.terminal_proof, "lifecycle terminal proof")
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise GenericExtractError(f"refusing to reuse output root: {output_root}")
    contracts: list[dict[str, Any]] = []
    contract_refs: list[dict[str, Any]] = []
    static_refs: list[dict[str, Any]] = [lifecycle_refs["request"], lifecycle_refs["manifest"], current_ref, inventory_ref, *consumed_refs, *_official_refs(), _small_ref(args.current, "CURRENT336 catalog", CURRENT_SHA), _small_ref(args.inventory, "historical 118 inventory")]
    for case_id in case_ids:
        row = current[case_id]
        native = _native_edges(case_id, row, inventory.get(case_id))
        source_refs = _static_case_refs(case_id, row)
        for item in source_refs:
            static_refs.append(item["ref"])
        contract: dict[str, Any] = {
            "schema": CONTRACT_SCHEMA,
            "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT" if terminal_ref else "WAITING_FOR_LIFECYCLE_TERMINAL_PROOF",
            "physical_case_id": case_id,
            "family_id": family,
            "historical_118_membership": inventory.get(case_id, {}).get("historical_118_membership") is True,
            "source_bindings": {item["role"]: item["ref"] for item in source_refs},
            "native_deferred": native,
            "typed_deferred": None,
            "terminal_proof_row": None,
            "official_tool": {"path": str(PARTVTKOUT), "sha256": PARTVTKOUT_SHA},
            "official_config": {"path": str(CONFIG), "sha256": next(item["sha256"] for item in _official_refs() if item["path"] == str(CONFIG))},
            "claim_boundary": {"native_cause": "UNKNOWN_UNTIL_EXACT_OFFICIAL_ID_JOIN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            "read_policy": {"prepare": "bounded JSON/stat/source only; no native payload", "audit": "typed records and native PartOut/RunPARTs only after parent reservation"},
        }
        if case_id in proof_rows:
            row_proof = proof_rows[case_id]
            contract["terminal_proof_row"] = {"case_manifest": row_proof.get("case_manifest"), "receipt": row_proof.get("receipt"), "status": row_proof.get("status")}
            contract["typed_deferred"] = {"summary": row_proof["_typed_summary_ref"], "records": row_proof["_typed_records_ref"]}
        contract_path = output_root / "case-contracts" / f"{case_id}.json"
        _atomic(contract_path, contract)
        contract_ref = {"physical_case_id": case_id, "path": str(contract_path), "sha256": _digest(contract_path, "case contract", max_bytes=MAX_OUTPUT_BYTES), "bytes": int(contract_path.stat().st_size)}
        contract_refs.append(contract_ref)
        static_refs.append(contract_ref)
        contracts.append(contract)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT" if terminal_ref else "READY_SOURCE_ONLY_WAITING_FOR_TERMINAL_PROOF",
        "namespace": args.namespace,
        "family_id": family,
        "physical_case_ids": case_ids,
        "lifecycle_request": lifecycle_refs["request"],
        "lifecycle_manifest": lifecycle_refs["manifest"],
        "current_catalog": current_ref,
        "historical_inventory": inventory_ref,
        "consumed_native_evidence": consumed_refs,
        "explicit_excluded_case_ids": sorted(explicit_excluded),
        "terminal_proof": terminal_ref,
        "terminal_proof_edges": proof_edges,
        "contracts": contract_refs,
        "official_sources": {"partvtkout": next(item for item in _official_refs() if item["path"] == str(PARTVTKOUT)), "config": next(item for item in _official_refs() if item["path"] == str(CONFIG))},
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "one_case_at_a_time": True, "native_obi4_hash_passes": 2, "partvtkout_passes": 1, "runparts_passes": 1, "h5_content_read": False, "solver_started": False},
        "claim_boundary": {"native_cause": "exact official PartOut Motive only", "historical118_cause_credit": "only exact CURRENT/inventory membership plus complete join", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare_opened_h5": False, "prepare_opened_jsonl": False, "prepare_opened_bi4": False, "prepare_opened_obi4": False, "prepare_opened_partout": False, "prepare_opened_runparts": False, "parent_reservation_required_for_audit": True},
        "launch_allowed": terminal_ref is not None,
        "execution_allowed": terminal_ref is not None,
        "launch_owner": "root",
    }
    manifest_path = output_root / "generic-native-extract-manifest.json"
    _atomic(manifest_path, manifest)
    static_refs.append(_small_ref(manifest_path, "generic native manifest"))
    input_sha = {item["path"]: item["sha256"] for item in static_refs}
    deferred: list[dict[str, Any]] = []
    for contract in contracts:
        deferred.extend(contract["native_deferred"].values())
        if isinstance(contract.get("typed_deferred"), dict):
            deferred.extend(contract["typed_deferred"].values())
    request_path = args.request_output.expanduser().resolve()
    command = [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/generic-native-extract.json"]
    request = {
        "schema": REQUEST_SCHEMA,
        "shared_runtime_version": "v8",
        "family_id": family,
        "case_id": f"{args.namespace}_{family}_GENERIC_NATIVE_EXTRACT_V1",
        "attempt_id": f"generic-native-extract-{args.namespace.lower()}-001-root-forward",
        "physical_case_ids": case_ids,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 3600, "max_memory_bytes": 4 * 1024 * 1024 * 1024,
        "estimated_storage_bytes": MAX_OUTPUT_BYTES,
        "estimated_deferred_read_bytes": sum(int(item["native_deferred"]["partout_obi4"]["bytes"]) for item in contracts) + len(contracts) * MAX_TYPED_BYTES,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": command,
        "input_files": sorted(input_sha), "input_sha256": dict(sorted(input_sha.items())),
        "deferred_input_files": sorted({str(item["path"]) for item in deferred if isinstance(item, dict) and isinstance(item.get("path"), str)}),
        "deferred_input_records": deferred,
        "manifest_contract": {"path": str(manifest_path), "sha256": input_sha[str(manifest_path)]},
        "official_tool": manifest["official_sources"]["partvtkout"], "official_config": manifest["official_sources"]["config"],
        "launch_allowed": terminal_ref is not None, "execution_allowed": terminal_ref is not None, "launch_owner": "root",
        "claim_boundary": manifest["claim_boundary"],
        "request_note": "Generic native extraction is parent-gated. Exact case IDs and terminal proof are required; no empty/global target shortcut and no fate/flux/dynamics/Q credit.",
    }
    _atomic(request_path, request)
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "generic native manifest", max_bytes=MAX_OUTPUT_BYTES), "request": str(request_path), "request_sha256": _digest(request_path, "generic native request", max_bytes=MAX_OUTPUT_BYTES), "family_id": family, "case_ids": case_ids, "terminal_proof_bound": terminal_ref is not None, "launch_allowed": terminal_ref is not None, "payload_content_opened": False}


def _audit_one(contract: dict[str, Any], output_dir: Path, intake: Any, tool: Path, claim: dict[str, Any]) -> dict[str, Any]:
    case_id = contract["physical_case_id"]
    typed = contract.get("typed_deferred")
    if not isinstance(typed, dict):
        raise GenericExtractError(f"{case_id} has no terminal typed records")
    targets, typed_evidence = intake._typed_targets(_path(typed["records"]["path"], f"{case_id} typed records"), typed["records"])
    data_dir = _path(contract["native_deferred"]["data_dir"]["path"], f"{case_id} native data directory", directory=True)
    obi4 = _path(contract["native_deferred"]["partout_obi4"]["path"], f"{case_id} PartOut_000.obi4")
    before = _stat(obi4, f"{case_id} PartOut pre")
    pre_sha = _digest(obi4, f"{case_id} PartOut pre")
    case_dir = output_dir / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    csv_path = case_dir / "PartOut.csv"
    resume_path = case_dir / "resume.csv"
    if csv_path.exists() or resume_path.exists():
        raise GenericExtractError(f"{case_id} decoder output already exists")
    command = [str(tool), "-dirdata", str(data_dir), "-savecsv", str(csv_path), "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, cwd=str(case_dir), timeout=MAX_PARTVTK_TIMEOUT)
    if completed.returncode != 0:
        raise GenericExtractError(f"{case_id} official PartVTKOut failed: {completed.stderr[-1000:]}")
    if not csv_path.is_file():
        raise GenericExtractError(f"{case_id} official PartVTKOut did not create PartOut.csv")
    csv_ref = {**_stat(csv_path, f"{case_id} PartOut.csv"), "sha256": _digest(csv_path, f"{case_id} PartOut.csv", max_bytes=MAX_NATIVE_CSV_BYTES)}
    native_rows, native_evidence = intake._partout_rows(csv_path, csv_ref, targets)
    run_ref = contract["native_deferred"]["runparts_csv"]
    saved_times, run_evidence = intake._runparts_times(_path(run_ref["path"], f"{case_id} RunPARTs.csv"), run_ref)
    after = _stat(obi4, f"{case_id} PartOut post")
    post_sha = _digest(obi4, f"{case_id} PartOut post")
    if before != after or pre_sha != post_sha:
        raise GenericExtractError(f"{case_id} PartOut changed during official decoder")
    joined: list[dict[str, Any]] = []
    for key in sorted(targets):
        lo, hi = targets[key]["bracket_s"]
        if not any(abs(lo - value) <= 1e-12 for value in saved_times) or not any(abs(hi - value) <= 1e-12 for value in saved_times):
            raise GenericExtractError(f"{case_id} saved bracket is not source-observed: {key}")
        native = native_rows[key]
        joined.append({**targets[key], **native, "identity_key": [key[0], key[1]], "native_exit_cause": {1: "NUMERICAL_POSITION_EXCLUSION", 2: "NUMERICAL_DENSITY_EXCLUSION", 3: "NUMERICAL_MOVEMENT_EXCLUSION"}.get(native["motive_code"], "UNKNOWN"), "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"})
    return {"schema": REPORT_SCHEMA, "status": "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY", "physical_case_id": case_id, "family_id": contract["family_id"], "historical_118_membership": contract["historical_118_membership"], "typed": typed_evidence, "native": {"official_tool": {"path": str(tool), "returncode": completed.returncode, "command": command}, "partout_obi4": {"pre_stat": before, "post_stat": after, "pre_sha256": pre_sha, "post_sha256": post_sha}, "partout_csv": native_evidence, "runparts": run_evidence}, "counts": {"typed_targets": len(targets), "native_rows": len(native_rows), "joined": len(joined)}, "rows": joined, "claim_boundary": claim, "read_policy": {"parent_reserved": True, "typed_records_read": True, "native_obi4_read_by_official_partvtkout": True, "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _json(args.manifest, "generic native manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("launch_allowed") is not True:
        raise GenericExtractError("generic manifest is not terminal-proof bound")
    family = manifest.get("family_id")
    case_ids = manifest.get("physical_case_ids")
    if not isinstance(family, str) or not isinstance(case_ids, list) or len(case_ids) != len(set(case_ids)):
        raise GenericExtractError("generic manifest identity set is malformed")
    terminal = manifest.get("terminal_proof")
    if not isinstance(terminal, dict) or not isinstance(terminal.get("path"), str):
        raise GenericExtractError("generic manifest terminal proof edge is missing")
    _validate_proof(Path(terminal["path"]), list(case_ids), family)
    tool = _path(manifest["official_sources"]["partvtkout"]["path"], "official PartVTKOut")
    if _digest(tool, "official PartVTKOut", max_bytes=MAX_SMALL_BYTES) != PARTVTKOUT_SHA:
        raise GenericExtractError("official PartVTKOut SHA differs at audit")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise GenericExtractError(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    intake = _load_intake()
    results: list[dict[str, Any]] = []
    for entry in manifest.get("contracts", []):
        case_id = entry.get("physical_case_id") if isinstance(entry, dict) else None
        try:
            contract = _json(Path(entry["path"]), f"{case_id} native contract")
            if contract.get("physical_case_id") != case_id or contract.get("family_id") != family:
                raise GenericExtractError(f"{case_id} contract identity differs")
            case_report = _audit_one(contract, output.parent, intake, tool, manifest["claim_boundary"])
            case_path = output.parent / "cases" / f"{case_id}.json"
            _atomic(case_path, case_report, limit=MAX_OUTPUT_BYTES)
            results.append({"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_path), "joined": case_report["counts"]["joined"]})
        except (GenericExtractError, OSError, subprocess.SubprocessError, ValueError) as exc:
            results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "saved_mask_credit": False})
    failed = [item for item in results if item.get("status") != "COMPLETED"]
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_ALL_CASES", "family_id": family, "case_results": results, "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed)}, "claim_boundary": manifest["claim_boundary"], "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    _atomic(output, report)
    return {"status": report["status"], "output": str(output), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"]}


def _self_test() -> dict[str, Any]:
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "case_cap": MAX_CASES, "payload_opened": False, "launch_allowed": False, "checks": ["dynamic F4/F6 request identity", "ROOT253/ROOT256 proof edge shapes", "exact duplicate case rejection", "consumed evidence exclusion", "official ORIGINAL PartVTKOut/S config closure", "physical fate UNKNOWN"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--namespace", required=True)
    prep.add_argument("--lifecycle-request", type=Path, required=True)
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--inventory", type=Path, default=INVENTORY_DEFAULT)
    prep.add_argument("--terminal-proof", type=Path)
    prep.add_argument("--consumed-report", type=Path, action="append", default=[])
    prep.add_argument("--exclude-case", action="append", default=[])
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args) if args.action == "prepare" else audit(args)
    except (GenericExtractError, OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"GENERIC_NATIVE_EXTRACT_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
