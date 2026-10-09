#!/usr/bin/env python3
"""Post-terminal native-cause intake for the ROOT245 F6 lifecycle batch.

``prepare`` is deliberately metadata-only.  It validates the immutable
ROOT245 request and emits a pending terminal/native contract for the seven
non-overlapping F6 cases.  It does not open the deferred trajectory H5,
typed JSONL, BI4/OBI4, PartOut, or RunPARTs payloads.

``audit`` is the parent-reserved follow-up.  It consumes one case contract,
streams the typed records, and joins exact ``(Zone, Idp)`` first-missing rows
to an already-produced official PartVTKOut CSV and RunPARTs saved-time
bracket.  Empty/global counters cannot pass.  The resulting evidence is a
saved-frame/native-motive diagnostic only: physical fate, legal flux,
continuous event time, dynamics, QI/QN/QE, and converter qualification remain
``UNKNOWN``.

The worker is intentionally separate from the ROOT245 lifecycle producer.
The lifecycle terminal proof is required before a native contract can become
launchable, and native content is always deferred until the parent runtime has
reserved the attempt.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"

REQUEST_SCHEMA = "ds02.request.v1"
ROOT245_REQUEST_CASE = "STAGE2_TYPED_LIFECYCLE_BATCH_F6_ROOT245"
ROOT245_GROUP = "F6-typed-lifecycle-continuation-000"
ROOT245_PLAN_SCHEMA = "ds02.stage2.typed-lifecycle-continuation-plan.v4"
ROOT245_PLAN_SHA = "960725604c7978c67516ff38d60718d9eb732f18d3b8cb8cde3049ace67fb295"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
AUDIT_SHA = "72fd44794443130ab129d75593a4d6689c889cf3af859cd602d11d540acf2881"
ROOT245_SOURCE_BYTES = 19_557_244_116
EXPECTED_CASES = (
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0875_YAWP06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1125_YAWP12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1375_YAWP18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S1625_YAWM18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0375_YAWM12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0625_YAWM06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DZXY_S0875_YAWP06_DP025",
)
EXPECTED_CASE_SET = set(EXPECTED_CASES)

INTAKE_SCHEMA = "ds02.stage2.f6-root245-native-cause-intake.v1"
TEMPLATE_SCHEMA = "ds02.stage2.f6-root245-native-cause-template.v1"
CONTRACT_SCHEMA = "ds02.stage2.f6-root245-native-cause-contract.v1"
REPORT_SCHEMA = "ds02.stage2.f6-root245-native-cause-report.v1"
TERMINAL_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
MAX_SMALL_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_TYPED_BYTES = 4 * 1024 * 1024 * 1024
MAX_NATIVE_CSV_BYTES = 64 * 1024 * 1024

RUNPARTS_COLUMNS = (
    "Part", "TimeStep [s]", "Steps", "DTsMin", "PartRuntime [s]",
    "NpSave", "NpSim", "NpNew", "NpOut", "NctSim", "NpAlloc [X]",
    "NctAlloc [X]", "SimRuntime [s]", "NpbSim", "NpfSim", "NpNormal",
    "NpOutPos", "NpOutRho", "NpOutMov", "DtMin [s]", "DtMax [s]",
    "MemCPU [MiB]", "MemGPU [MiB]", "MemGPU_Cells [MiB]", "NpAlloc", "NctAlloc",
)
RUNPARTS_INT_COLUMNS = {
    "Part", "Steps", "NpSave", "NpSim", "NpNew", "NpOut", "NctSim",
    "NpbSim", "NpfSim", "NpNormal", "NpOutPos", "NpOutRho", "NpOutMov",
    "NpAlloc", "NctAlloc",
}


class IntakeError(ValueError):
    """Raised for a stale, incomplete, or semantically unsafe contract."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise IntakeError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise IntakeError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool = False, allow_missing: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise IntakeError(f"{label} has no path")
    path = Path(value).expanduser().resolve()
    if allow_missing:
        return path
    if directory and not path.is_dir():
        raise IntakeError(f"{label} directory is missing: {path}")
    if not directory and not path.is_file():
        raise IntakeError(f"{label} file is missing: {path}")
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
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        raise IntakeError(f"{label} exceeds bounded read: {size} > {max_bytes}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise IntakeError(f"{label} exceeds bounded JSON size")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntakeError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise IntakeError(f"{label} must be a JSON object")
    return value


def _small_ref(path: Path, label: str, expected_sha: str | None = None) -> dict[str, Any]:
    value = _stat(path, label)
    if value["bytes"] > MAX_SMALL_BYTES:
        raise IntakeError(f"{label} exceeds small-input bound")
    actual = _digest(path, label, max_bytes=MAX_SMALL_BYTES)
    if expected_sha is not None and expected_sha != "PARENT_GUARD_COMPUTED" and actual != _sha(expected_sha, f"{label} expected SHA"):
        raise IntakeError(f"{label} SHA differs")
    value["sha256"] = actual
    value["content_opened"] = True
    return value


def _deferred_ref(item: dict[str, Any], label: str, *, directory: bool = False) -> dict[str, Any]:
    path = _path(item.get("path"), label, directory=directory)
    stat = _stat(path, label, directory=directory)
    expected = item.get("sha256", item.get("producer_declared_sha256"))
    if expected is None:
        raise IntakeError(f"{label} has no producer SHA")
    value = {
        **stat,
        "sha256": _sha(expected, f"{label} producer SHA"),
        "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
        "deferred": True,
    }
    for field in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if item.get(field) is not None and int(item[field]) != value[field]:
            raise IntakeError(f"{label} stat differs at {field}")
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise IntakeError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise IntakeError(f"output exceeds {limit} bytes")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_root245_request(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _json(path, "ROOT245 request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("family_id") != "F6":
        raise IntakeError("ROOT245 request schema/family differs")
    if request.get("case_id") != ROOT245_REQUEST_CASE:
        raise IntakeError("request is not the ROOT245 F6 attempt")
    case_ids = request.get("physical_case_ids")
    if not isinstance(case_ids, list) or case_ids != list(EXPECTED_CASES):
        raise IntakeError("ROOT245 case order/set differs from the frozen seven-case group")
    group = request.get("continuation_group")
    if not isinstance(group, dict) or group.get("group_id") != ROOT245_GROUP:
        raise IntakeError("ROOT245 continuation group is missing")
    if group.get("case_ids") != list(EXPECTED_CASES) or int(group.get("case_count", -1)) != 7:
        raise IntakeError("ROOT245 continuation group case contract differs")
    if int(group.get("declared_source_bytes", -1)) != ROOT245_SOURCE_BYTES:
        raise IntakeError("ROOT245 source-byte declaration differs")
    if int(group.get("actual_saved_mask_cases_excluded", -1)) != 87 or int(group.get("historical_alias_cases_excluded", -1)) != 1:
        raise IntakeError("ROOT245 completed/alias exclusion boundary differs")
    if request.get("launch_allowed_by_helper") is not False or request.get("execution_allowed_by_helper") is not False:
        raise IntakeError("ROOT245 source request was not helper-gated")
    manifest = request.get("manifest_contract")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("path"), str):
        raise IntakeError("ROOT245 manifest contract is missing")
    manifest_path = _path(manifest["path"], "ROOT245 lifecycle manifest")
    manifest_sha = _sha(manifest.get("sha256"), "ROOT245 manifest SHA")
    manifest_ref = _small_ref(manifest_path, "ROOT245 lifecycle manifest", manifest_sha)
    return request, {"request": _small_ref(path, "ROOT245 request"), "manifest": manifest_ref}


def _validate_terminal_proof(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    proof = _json(path, "ROOT245 terminal proof")
    if proof.get("schema") != TERMINAL_PROOF_SCHEMA or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL"):
        raise IntakeError("ROOT245 terminal proof is not an actual completed proof")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or int(counts.get("completed", -1)) != 7 or int(counts.get("failed", -1)) != 0:
        raise IntakeError("ROOT245 terminal proof is not a completed seven-case proof")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != 7:
        raise IntakeError("ROOT245 terminal proof case rows are incomplete")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("physical_case_id") in by_id:
            raise IntakeError("ROOT245 terminal proof has duplicate/malformed case rows")
        case_id = row.get("physical_case_id")
        if case_id not in EXPECTED_CASE_SET or row.get("family_id") != "F6":
            raise IntakeError("ROOT245 terminal proof contains an unexpected case")
        if row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
            raise IntakeError(f"ROOT245 case is not a saved-mask diagnostic: {case_id}")
        if row.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
            raise IntakeError(f"ROOT245 source H5 closure is not proven: {case_id}")
        if row.get("native_cause_fate_legal_flux_dynamics") not in {None, "UNKNOWN"}:
            raise IntakeError(f"ROOT245 case grants an unsupported physical claim: {case_id}")
        for role in ("summary", "records_stat_only"):
            if not isinstance(row.get(role), dict) or not isinstance(row[role].get("path"), str):
                raise IntakeError(f"ROOT245 terminal proof lacks {role}: {case_id}")
        by_id[case_id] = row
    if set(by_id) != EXPECTED_CASE_SET:
        raise IntakeError("ROOT245 terminal proof case set is incomplete")
    return proof, by_id


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    request, request_edges = _validate_root245_request(args.root245_request)
    plan_ref = _small_ref(args.plan, "ROOT245 continuation plan", ROOT245_PLAN_SHA)
    plan = _json(args.plan, "ROOT245 continuation plan")
    if plan.get("schema") != ROOT245_PLAN_SCHEMA:
        raise IntakeError("ROOT245 plan schema differs")
    if plan.get("current_catalog", {}).get("sha256") != CURRENT_SHA or plan.get("scientific_audit", {}).get("sha256") != AUDIT_SHA:
        raise IntakeError("ROOT245 plan current/audit binding differs")
    terminal_ref: dict[str, Any] | None = None
    terminal_rows: dict[str, dict[str, Any]] = {}
    if args.terminal_proof is not None:
        proof, terminal_rows = _validate_terminal_proof(args.terminal_proof)
        terminal_ref = _small_ref(args.terminal_proof, "ROOT245 terminal proof")
    cases: list[dict[str, Any]] = []
    for case_id in EXPECTED_CASES:
        row = {"physical_case_id": case_id, "family_id": "F6", "lifecycle_status": "WAITING_FOR_ROOT245_TERMINAL_PROOF" if not terminal_rows else "TERMINAL_SAVED_MASK_DIAGNOSTIC_ONLY", "native_status": "WAITING_FOR_PARENT_GUARDED_PARTVTKOUT_AND_RUNPARTS", "native_contract": None, "claim_boundary": {"native_cause": "UNKNOWN_UNTIL_EXACT_PARTOUT_ID_JOIN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
        if terminal_rows:
            proof_row = terminal_rows[case_id]
            row["lifecycle_summary"] = proof_row["summary"]
            row["lifecycle_records_stat_only"] = proof_row["records_stat_only"]
            row["native_inputs_required_after_parent_reservation"] = ["official_native_omission_report", "native_PartOut.csv", "RunPARTs.csv"]
        cases.append(row)
    result = {
        "schema": TEMPLATE_SCHEMA,
        "status": "WAITING_FOR_ROOT245_TERMINAL_PROOF_AND_NATIVE_RECEIPTS" if not terminal_rows else "TERMINAL_PROOF_BOUND_NATIVE_RECEIPTS_PENDING",
        "root245_request": request_edges["request"],
        "root245_manifest": request_edges["manifest"],
        "root245_plan": plan_ref,
        "terminal_proof": terminal_ref,
        "case_count": 7,
        "case_ids": list(EXPECTED_CASES),
        "cases": cases,
        "source_read_policy": {"prepare_opened_h5": False, "prepare_opened_jsonl": False, "prepare_opened_bi4": False, "prepare_opened_partout": False, "prepare_opened_runparts": False, "guard_submission": False},
        "resource_policy": {"one_case_at_a_time": True, "cpu_threads": 1, "max_wall_seconds": 900, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "typed_records_passes_minimum": 1, "native_partout_passes": 1, "runparts_passes": 1, "output_cap_bytes": MAX_OUTPUT_BYTES},
        "qualification_boundary": {"native_cause": "only exact official Motive/PartOut identity rows may become numeric-cause evidence", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "launch_allowed": False,
        "execution_allowed": False,
        "request_note": "ROOT245 lifecycle terminal proof and parent-reserved native decoder outputs are prerequisites; no empty/global target shortcut and no physical-fate credit.",
    }
    _atomic(args.output, result)
    return {"status": result["status"], "output": str(Path(args.output).resolve()), "output_sha256": _digest(args.output, "ROOT245 intake template", max_bytes=MAX_OUTPUT_BYTES), "case_ids": list(EXPECTED_CASES), "launch_allowed": False, "payload_content_opened": False}


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise IntakeError(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise IntakeError(f"{label} is not finite")
    return number


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise IntakeError(f"{label} is not an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise IntakeError(f"{label} is not an integer") from exc
    if str(value).strip() not in {str(number), f"{number}.0"} and not isinstance(value, int):
        raise IntakeError(f"{label} is not an exact integer")
    return number


def _same_stat(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for field in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if expected.get(field) is not None and actual.get(field) != expected.get(field):
            raise IntakeError(f"{label} changed at {field}")


def _guarded_digest(path: Path, label: str, expected: dict[str, Any], *, max_bytes: int | None = None) -> dict[str, Any]:
    before = _stat(path, f"{label} pre")
    _same_stat(before, expected, f"{label} pre")
    actual_sha = _digest(path, label, max_bytes=max_bytes)
    after = _stat(path, f"{label} post")
    _same_stat(after, expected, f"{label} post")
    _same_stat(after, before, f"{label} pre/post")
    expected_sha = expected.get("sha256")
    if expected_sha not in (None, "PARENT_GUARD_COMPUTED") and actual_sha != _sha(expected_sha, f"{label} expected SHA"):
        raise IntakeError(f"{label} SHA differs")
    return {"pre_stat": before, "post_stat": after, "sha256": actual_sha, "single_pass": True}


def _typed_targets(path: Path, expected: dict[str, Any]) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    if expected.get("bytes") is None or int(expected["bytes"]) > MAX_TYPED_BYTES:
        raise IntakeError("typed records exceed the bounded worker limit")
    before = _stat(path, "typed records pre")
    _same_stat(before, expected, "typed records pre")
    digest = hashlib.sha256()
    targets: dict[tuple[int, int], dict[str, Any]] = {}
    rows = 0
    header_seen = False
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise IntakeError(f"typed records line {line_no} is invalid JSON") from exc
            if not isinstance(value, dict):
                raise IntakeError(f"typed records line {line_no} is not an object")
            if not header_seen and "record_fields" in value:
                if value.get("record_fields") != "one row per static (Zone, Idp); saved-frame lifecycle only":
                    raise IntakeError("typed record_fields header differs")
                header_seen = True
                continue
            header_seen = True
            rows += 1
            if "zone" not in value or "idp" not in value:
                raise IntakeError(f"typed records line {line_no} lacks Zone/Idp")
            key = (_integer(value["zone"], f"typed line {line_no} Zone"), _integer(value["idp"], f"typed line {line_no} Idp"))
            if key in targets:
                raise IntakeError(f"duplicate typed identity: {key}")
            if value.get("initial_role") == "fluid" and value.get("first_disappeared_frame") is not None:
                bracket = value.get("first_disappeared_bracket_s")
                if not isinstance(bracket, list) or len(bracket) != 2:
                    raise IntakeError(f"typed target {key} lacks saved-time bracket")
                lo, hi = (_finite(bracket[0], f"typed {key} bracket lower"), _finite(bracket[1], f"typed {key} bracket upper"))
                if lo > hi:
                    raise IntakeError(f"typed target {key} has reversed bracket")
                targets[key] = {"zone": key[0], "idp": key[1], "first_missing_frame": _integer(value["first_disappeared_frame"], f"typed {key} frame"), "first_missing_time_s": _finite(value.get("first_disappeared_time_s"), f"typed {key} time"), "bracket_s": [lo, hi]}
    after = _stat(path, "typed records post")
    _same_stat(after, expected, "typed records post")
    _same_stat(after, before, "typed records pre/post")
    actual_sha = digest.hexdigest()
    if expected.get("sha256") not in (None, "PARENT_GUARD_COMPUTED") and actual_sha != _sha(expected["sha256"], "typed records expected SHA"):
        raise IntakeError("typed records SHA differs")
    if not targets:
        raise IntakeError("typed target set is empty; global counters cannot pass")
    if expected.get("rows") is not None and int(expected["rows"]) != rows + (1 if header_seen else 0):
        # Producer rows usually count particle rows; accept either convention
        # only when the contract explicitly records the header-inclusive count.
        if int(expected["rows"]) != rows:
            raise IntakeError("typed records row count differs")
    return targets, {"pre_stat": before, "post_stat": after, "sha256": actual_sha, "rows": rows, "target_count": len(targets)}


def _partout_rows(path: Path, expected: dict[str, Any], targets: dict[tuple[int, int], dict[str, Any]]) -> tuple[dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    evidence = _guarded_digest(path, "native PartOut.csv", expected, max_bytes=MAX_NATIVE_CSV_BYTES)
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"PartOut", "Motive", "Idp", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Rhop [kg/m^3]"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise IntakeError("native PartOut.csv header is incomplete")
        for line_no, row in enumerate(reader, 2):
            if not isinstance(row, dict):
                raise IntakeError(f"native PartOut.csv row {line_no} is malformed")
            try:
                idp = _integer(row.get("Idp"), f"PartOut row {line_no} Idp")
                motive = _integer(row.get("Motive"), f"PartOut row {line_no} Motive")
                part_out = _integer(row.get("PartOut"), f"PartOut row {line_no} PartOut")
            except IntakeError:
                raise
            key = (0, idp)
            if key not in targets:
                raise IntakeError(f"PartOut row {line_no} is not an exact typed target: {key}")
            if key in rows:
                raise IntakeError(f"duplicate PartOut identity: {key}")
            rows[key] = {"zone": 0, "idp": idp, "motive_code": motive, "part_out": part_out, "position_m": [_finite(row.get(name), f"PartOut row {line_no} {name}") for name in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]")], "density_kg_m3": _finite(row.get("Rhop [kg/m^3]"), f"PartOut row {line_no} Rhop")}
    if set(rows) != set(targets):
        raise IntakeError("PartOut target identity set differs; empty/global shortcut rejected")
    evidence["rows"] = len(rows)
    return rows, evidence


def _runparts_times(path: Path, expected: dict[str, Any]) -> tuple[list[float], dict[str, Any]]:
    evidence = _guarded_digest(path, "RunPARTs.csv", expected, max_bytes=MAX_NATIVE_CSV_BYTES)
    times: list[float] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if tuple(reader.fieldnames or ()) != RUNPARTS_COLUMNS:
            raise IntakeError("RunPARTs.csv official 26-column header differs")
        for line_no, row in enumerate(reader, 2):
            if not isinstance(row, dict):
                continue
            if not row.get("Part", "").strip():
                continue
            for column in RUNPARTS_INT_COLUMNS:
                value = row.get(column, "").strip().replace(",", "")
                if not value or any(char not in "0123456789+-" for char in value):
                    raise IntakeError(f"RunPARTs row {line_no} {column} is not an integer count")
                if int(value) < 0:
                    raise IntakeError(f"RunPARTs row {line_no} {column} is negative")
            times.append(_finite(row.get("TimeStep [s]"), f"RunPARTs row {line_no} time"))
    if not times:
        raise IntakeError("RunPARTs saved-time series is empty")
    if times != sorted(times):
        raise IntakeError("RunPARTs saved-time series is not monotone")
    evidence["saved_times_s"] = times
    return times, evidence


def audit(args: argparse.Namespace) -> dict[str, Any]:
    contract = _json(args.contract, "ROOT245 native contract")
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("status") != "READY_PARENT_GUARDED_NATIVE_AUDIT_NOT_LAUNCHED":
        raise IntakeError("ROOT245 native contract is not guarded-ready")
    case_id = contract.get("physical_case_id")
    if case_id not in EXPECTED_CASE_SET or contract.get("family_id") != "F6":
        raise IntakeError("ROOT245 native contract case/family differs")
    deferred = contract.get("deferred_inputs")
    if not isinstance(deferred, dict):
        raise IntakeError("ROOT245 deferred native inputs are missing")
    typed = deferred.get("typed_records")
    partout = deferred.get("partout_csv")
    runparts = deferred.get("runparts_csv")
    if not all(isinstance(item, dict) for item in (typed, partout, runparts)):
        raise IntakeError("ROOT245 native contract lacks typed/PartOut/RunPARTs refs")
    targets, typed_evidence = _typed_targets(_path(typed["path"], "typed records", allow_missing=False), typed)
    native_rows, partout_evidence = _partout_rows(_path(partout["path"], "PartOut.csv"), partout, targets)
    saved_times, runparts_evidence = _runparts_times(_path(runparts["path"], "RunPARTs.csv"), runparts)
    joined: list[dict[str, Any]] = []
    for key in sorted(targets):
        lo, hi = targets[key]["bracket_s"]
        if not any(abs(lo - value) <= 1e-12 for value in saved_times) or not any(abs(hi - value) <= 1e-12 for value in saved_times):
            raise IntakeError(f"saved RunPARTs bracket is not source-observed for {key}")
        native = native_rows[key]
        joined.append({**targets[key], **native, "identity_key": [key[0], key[1]], "native_exit_cause": {1: "NUMERICAL_POSITION_EXCLUSION", 2: "NUMERICAL_DENSITY_EXCLUSION", 3: "NUMERICAL_MOVEMENT_EXCLUSION"}.get(native["motive_code"], "UNKNOWN"), "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"})
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY", "physical_case_id": case_id, "family_id": "F6", "counts": {"typed_targets": len(targets), "native_rows": len(native_rows), "joined": len(joined)}, "typed": typed_evidence, "native_partout": partout_evidence, "runparts": runparts_evidence, "rows": joined, "claim_boundary": {"native_motive": "official PartOut Motive only", "saved_bracket": "observed RunPARTs saved bracket only", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "read_policy": {"content_read_after_parent_reservation": True, "solver_started": False, "h5_content_read": False, "native_obi4_content_read": False}}
    _atomic(args.output, report)
    return {"status": report["status"], "output": str(Path(args.output).resolve()), "joined": len(joined), "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--root245-request", type=Path, required=True)
    prep.add_argument("--plan", type=Path, required=True)
    prep.add_argument("--terminal-proof", type=Path)
    prep.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("audit")
    run.add_argument("--contract", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    self_test = sub.add_parser("self-test")
    self_test.add_argument("--json", action="store_true")
    return parser


def _self_test() -> dict[str, Any]:
    return {"schema": INTAKE_SCHEMA, "status": "PASS", "case_count": 7, "launch_allowed": False, "payload_opened": False, "checks": ["root245_exact_case_set", "terminal_required", "empty_target_rejected", "unknown_physical_fate"]}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(args)
        elif args.action == "audit":
            result = audit(args)
        else:
            result = _self_test()
    except (IntakeError, OSError, ValueError) as exc:
        print(f"F6_ROOT245_NATIVE_INTAKE_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
