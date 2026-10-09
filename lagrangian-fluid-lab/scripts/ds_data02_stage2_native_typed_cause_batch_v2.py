#!/usr/bin/env python3
"""Prepare a family-aware native-cause/typed-first-missing batch.

This is a forward-only ROOT226 source adapter.  Preparation consumes bounded
JSON proofs and source metadata and records stat-only references for H5,
JSONL, PartOut and RunPARTs payloads.  It never opens those deferred payloads
and never starts a solver.  F6 and F4 have separate initial-count and target
rules; an empty or aggregate-only F4 report is kept as a source gap.

The eventual guarded worker may dispatch the existing F6 crosscheck parser or
an independently implemented F4 adapter.  This module deliberately does not
turn a source contract into scientific credit: saved-frame joins are
diagnostic and physical fate, flux, dynamics and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT_PATH = STAGE2 / "CURRENT336.json"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
SCOPE_PATH = STAGE2 / "checkpoints/NATIVE_TYPED_CASE_DEPENDENCY_SCOPE_V2_SOURCE_PREPARED.json"
SCOPE_SHA256 = "7d0df4943329a5a1e7e52cc91bc2e8be68a4d039e027d548bd29f079b06b1eb3"
INVENTORY_PATH = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
INVENTORY_SHA256 = "3d274db71d01f680b9997cc364298f9974a2cb09978acfb81f9a152622e75a00"
CONFIG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
RUNTIME_SOURCES = (
    PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py",
    PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py",
    PRIMARY / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py",
)

PROOFS = {
    "F6_203": STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_203.json",
    "F6_210": STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_210.json",
    "F4_201": STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_201.json",
}
PROOF_SHA256 = {
    "F6_203": "e146f0a378f56eccc59c5052aa27703322c40712192f38e9c5edce7acb87793c",
    "F6_210": "4c02c64912a46523d94c71c1836f807508d10079051a74fb5ec65f739ec0f5e5",
    "F4_201": "82705378c70f809543105d9182ebdab16e316de266c23fac699c0e41865dadd5",
}
ROOT220_PROOF = STAGE2 / "checkpoints/F6_TYPED_NATIVE_CAUSE_BATCH_V1_ACTUAL_ROOT_VERIFICATION_220.json"
ROOT220_PROOF_SHA256 = "5234b72328de3e662eb1a2f590bd792eb5919c4bdab3870e5e986e976179be82"
ROOT216_CASE = "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0625_YAWM06_DP025"
ROOT219_CASE = "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0875_YAWP06_DP025"

MAX_SMALL_BYTES = 8 * 1024 * 1024
MAX_CONTRACT_BYTES = 512 * 1024
MAX_BATCH_CASES = 8
MAX_BATCH_SOURCE_BYTES = 20 * 1024 * 1024 * 1024
REQUEST_SCHEMA = "ds02.request.v1"
BATCH_SCHEMA = "ds02.stage2.native-typed-cause-batch.v2"
CONTRACT_SCHEMA = "ds02.stage2.native-typed-cause-contract.v2"
CHECKPOINT_SCHEMA = "ds02.stage2.native-typed-cause-root226.v1"


class CauseBatchError(ValueError):
    """Raised when a source identity or deferred-input contract is incomplete."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CauseBatchError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(c not in "0123456789abcdef" for c in value):
        raise CauseBatchError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise CauseBatchError(f"{label} has no path")
    result = Path(value).expanduser().resolve()
    if directory:
        if not result.is_dir():
            raise CauseBatchError(f"{label} directory is missing: {result}")
    elif not result.is_file():
        raise CauseBatchError(f"{label} file is missing: {result}")
    return result


def _stat(path: Path, label: str, *, directory: bool = False) -> dict[str, Any]:
    path = _path(path, label, directory=directory)
    item = path.stat()
    return {
        "path": str(path),
        "bytes": int(item.st_size),
        "mtime_ns": int(item.st_mtime_ns),
        "ctime_ns": int(item.st_ctime_ns),
        "st_dev": int(item.st_dev),
        "st_ino": int(item.st_ino),
    }


def _digest(path: Path, label: str, *, max_bytes: int | None = None) -> str:
    path = _path(path, label)
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise CauseBatchError(f"{label} exceeds bounded content limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise CauseBatchError(f"{label} exceeds bounded JSON limit: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CauseBatchError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CauseBatchError(f"{label} must be an object")
    return value


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_SMALL_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise CauseBatchError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise CauseBatchError(f"output exceeds bounded limit: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _small_ref(path: Path, label: str, expected_sha: Any | None = None) -> dict[str, Any]:
    path = _path(path, label)
    stat = _stat(path, label)
    if stat["bytes"] > MAX_SMALL_BYTES:
        raise CauseBatchError(f"{label} is not a bounded source file: {path}")
    actual = _digest(path, label, max_bytes=MAX_SMALL_BYTES)
    if expected_sha is not None and actual != _sha(expected_sha, f"{label} expected SHA"):
        raise CauseBatchError(f"{label} SHA differs")
    return {**stat, "sha256": actual, "content_opened": True, "read_policy": "BOUNDED_SOURCE_METADATA"}


def _deferred_ref(path: Path, label: str, expected_sha: Any | None, expected_bytes: Any | None) -> dict[str, Any]:
    """Record a producer declaration and stat without opening or hashing content."""
    path = _path(path, label)
    stat = _stat(path, label)
    if expected_bytes is not None and int(expected_bytes) != stat["bytes"]:
        raise CauseBatchError(f"{label} byte count differs from producer declaration")
    result = {**stat, "content_opened": False, "hash_checked": False,
              "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION_SINGLE_PASS"}
    if expected_sha is not None:
        result["producer_declared_sha256"] = _sha(expected_sha, f"{label} producer SHA")
    return result


def _declared_ref(value: Any, label: str, *, deferred: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CauseBatchError(f"{label} declaration is malformed")
    raw_path = value.get("path", value.get("canonical_path"))
    if deferred:
        return _deferred_ref(Path(str(raw_path)), label, value.get("sha256", value.get("declared_sha256")),
                             value.get("bytes", value.get("declared_bytes")))
    expected = value.get("recomputed_sha256", value.get("sha256", value.get("declared_sha256")))
    return _small_ref(_path(raw_path, label), label, expected)


def _load_verified_json(path: Path, label: str, expected_sha: str) -> dict[str, Any]:
    _small_ref(path, label, expected_sha)
    return _json(path, label)


def _current() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current = _load_verified_json(CURRENT_PATH, "CURRENT336", CURRENT_SHA256)
    rows: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(current.get("cases", [])):
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise CauseBatchError(f"CURRENT336 case row {index} is malformed")
        cid = row["physical_case_id"]
        if cid in rows:
            raise CauseBatchError(f"CURRENT336 duplicate physical case: {cid}")
        copied = dict(row)
        copied["current336_index"] = index
        rows[cid] = copied
    if len(rows) != 336:
        raise CauseBatchError(f"CURRENT336 case count is not 336: {len(rows)}")
    return current, rows


def _scope() -> dict[str, dict[str, Any]]:
    value = _load_verified_json(SCOPE_PATH, "native typed scope V2", SCOPE_SHA256)
    result: dict[str, dict[str, Any]] = {}
    for row in value.get("case_rows", []):
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise CauseBatchError("native scope row is malformed")
        cid = row["physical_case_id"]
        if cid in result:
            raise CauseBatchError(f"native scope duplicate case: {cid}")
        result[cid] = row
    return result


def _inventory() -> dict[str, dict[str, Any]]:
    value = _load_verified_json(INVENTORY_PATH, "historical 118 inventory", INVENTORY_SHA256)
    result: dict[str, dict[str, Any]] = {}
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise CauseBatchError("historical inventory must contain 118 rows")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise CauseBatchError("historical inventory row is malformed")
        cid = row["physical_case_id"]
        if cid in result:
            raise CauseBatchError(f"historical inventory duplicate case: {cid}")
        result[cid] = row
    return result


def _proof_cases(proof_key: str) -> dict[str, dict[str, Any]]:
    proof = _load_verified_json(PROOFS[proof_key], f"{proof_key} typed proof", PROOF_SHA256[proof_key])
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise CauseBatchError(f"{proof_key} proof schema differs")
    if not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL_"):
        raise CauseBatchError(f"{proof_key} proof is not verified")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or counts.get("failed") != 0 or counts.get("completed") != counts.get("cases_requested"):
        raise CauseBatchError(f"{proof_key} proof is not a complete batch")
    result: dict[str, dict[str, Any]] = {}
    for case in proof.get("case_verifications", []):
        if not isinstance(case, dict) or not isinstance(case.get("physical_case_id"), str):
            raise CauseBatchError(f"{proof_key} case row is malformed")
        cid = case["physical_case_id"]
        if cid in result:
            raise CauseBatchError(f"{proof_key} duplicate case: {cid}")
        if case.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
            raise CauseBatchError(f"{proof_key} case is not a saved-mask diagnostic: {cid}")
        if case.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
            raise CauseBatchError(f"{proof_key} H5 closure is not proven: {cid}")
        if case.get("native_cause_fate_legal_flux_dynamics") != "UNKNOWN":
            raise CauseBatchError(f"{proof_key} widened physical claim: {cid}")
        result[cid] = case
    return result


def _all_proof_cases() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    combined: dict[str, dict[str, Any]] = {}
    family_proof: dict[str, str] = {}
    for key in PROOFS:
        for cid, case in _proof_cases(key).items():
            if cid in combined:
                raise CauseBatchError(f"typed proof case overlaps proof batches: {cid}")
            combined[cid] = case
            family_proof[cid] = key
    return combined, family_proof


def _root220_cases() -> set[str]:
    if not ROOT220_PROOF.is_file():
        return set()
    proof = _load_verified_json(ROOT220_PROOF, "ROOT220 actual cause proof", ROOT220_PROOF_SHA256)
    result = set()
    for case in proof.get("case_verifications", []):
        if isinstance(case, dict) and isinstance(case.get("physical_case_id"), str):
            result.add(case["physical_case_id"])
    if len(result) != 8:
        raise CauseBatchError(f"ROOT220 actual proof does not contain eight distinct cases: {len(result)}")
    return result


def _native_edge(inventory_row: dict[str, Any] | None, case_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    if inventory_row is None:
        return None, None, "NO_HISTORICAL_NATIVE_REPORT_EDGE"
    report = inventory_row.get("original_omission_evidence", {}).get("report")
    if not isinstance(report, dict):
        return None, None, "NO_HISTORICAL_NATIVE_REPORT_EDGE"
    report_path = _path(report.get("path"), f"{case_id} native omission report")
    report_sha = _sha(report.get("declared_sha256"), f"{case_id} native omission report SHA")
    report_ref = _small_ref(report_path, f"{case_id} native omission report", report_sha)
    native = _json(report_path, f"{case_id} native omission report")
    if native.get("physical_case_id") != case_id or native.get("status") != "CAUSES_RECONCILED":
        raise CauseBatchError(f"{case_id} native omission report identity/status differs")
    excluded = native.get("excluded_particles")
    if not isinstance(excluded, list):
        raise CauseBatchError(f"{case_id} native omission report has no excluded_particles list")
    keys: set[tuple[int, int]] = set()
    for item in excluded:
        if not isinstance(item, dict) or not isinstance(item.get("zone"), int) or not isinstance(item.get("idp"), int):
            raise CauseBatchError(f"{case_id} native target identity is malformed")
        key = (int(item["zone"]), int(item["idp"]))
        if key in keys:
            raise CauseBatchError(f"{case_id} native target identity is duplicated")
        keys.add(key)
    native_decode = native.get("native_decode")
    deferred: dict[str, Any] = {}
    if isinstance(native_decode, dict):
        for name in ("partout", "runparts"):
            edge = native_decode.get(name)
            if isinstance(edge, dict) and edge.get("path"):
                deferred[name] = _deferred_ref(Path(str(edge["path"])), f"{case_id} native {name}", edge.get("sha256"), edge.get("bytes"))
    return {"report": report_ref, "path": str(report_path), "sha256": report_sha, "excluded_count": len(excluded),
            "identity_keys": [[int(item["zone"]), int(item["idp"])] for item in excluded],
            "physical_fate": native.get("physical_fate", "UNKNOWN"), "dynamical_impact": native.get("dynamical_impact", "UNKNOWN")}, deferred, "PER_ID_NATIVE_REPORT_PRESENT"


def _source_refs(current_row: dict[str, Any], case_id: str) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    conversion = current_row.get("conversion_report")
    if isinstance(conversion, dict):
        artifacts["conversion_report"] = _declared_ref(conversion, f"{case_id} conversion report")
    bindings = current_row.get("source_bindings")
    if isinstance(bindings, dict):
        for role, value in bindings.items():
            if isinstance(value, dict) and value.get("path"):
                artifacts[role] = _declared_ref(value, f"{case_id} {role}")
    manifest = current_row.get("manifest")
    if isinstance(manifest, dict):
        artifacts["current_case_manifest"] = _declared_ref(manifest, f"{case_id} CURRENT case manifest")
    raw_root = current_row.get("raw_root")
    if isinstance(raw_root, dict) and raw_root.get("path"):
        artifacts["raw_solver_root"] = {**_stat(Path(str(raw_root["path"])), f"{case_id} raw solver root", directory=True),
                                         "content_opened": False, "hash_checked": False}
    return artifacts


def _proof_ref(case: dict[str, Any], case_id: str) -> dict[str, Any]:
    summary_path = _path(case.get("summary"), f"{case_id} typed summary")
    summary_sha = _sha(case.get("summary_sha256"), f"{case_id} typed summary SHA")
    summary_ref = _small_ref(summary_path, f"{case_id} typed summary", summary_sha)
    records = case.get("records_stat_only")
    if not isinstance(records, dict):
        raise CauseBatchError(f"{case_id} typed records stat is missing")
    records_ref = _deferred_ref(Path(str(records.get("path"))), f"{case_id} typed records", records.get("sha256"), records.get("bytes"))
    records_ref["rows"] = records.get("rows")
    trajectory = case.get("source_trajectory")
    if not isinstance(trajectory, dict):
        raise CauseBatchError(f"{case_id} typed source trajectory edge is missing")
    trajectory_ref = _deferred_ref(Path(str(trajectory.get("path"))), f"{case_id} typed source H5", trajectory.get("known_sha256"), trajectory.get("pre_stat", {}).get("bytes"))
    for key in ("pre_sha256", "post_sha256"):
        if trajectory.get(key) != trajectory.get("known_sha256"):
            raise CauseBatchError(f"{case_id} typed source {key} differs")
    return {"summary": summary_ref, "records": records_ref, "trajectory": trajectory_ref,
            "trajectory_declared_sha256": _sha(trajectory.get("known_sha256"), f"{case_id} typed source SHA"),
            "actual_timeline": {"frames": case.get("actual_timeline", {}).get("frames"), "particles": case.get("actual_timeline", {}).get("particles"), "time_s": case.get("actual_timeline", {}).get("time_s")},
            "fluid_ledger": case.get("actual_role_ledgers", {}).get("fluid", {})}


def _contract(case_id: str, current_row: dict[str, Any], scope_row: dict[str, Any] | None,
              inventory_row: dict[str, Any] | None, proof: dict[str, Any], proof_key: str,
              native: dict[str, Any] | None, native_deferred: dict[str, Any] | None, native_status: str,
              consumed: set[str]) -> dict[str, Any]:
    family = current_row.get("family_id")
    if family not in {"F4", "F6"}:
        raise CauseBatchError(f"{case_id} is not an F4/F6 case")
    typed = _proof_ref(proof, case_id)
    current_trajectory = current_row.get("trajectory")
    if not isinstance(current_trajectory, dict):
        raise CauseBatchError(f"{case_id} CURRENT trajectory is missing")
    if typed["trajectory_declared_sha256"] != current_trajectory.get("producer_declared_sha256"):
        raise CauseBatchError(f"{case_id} typed H5 SHA differs from CURRENT")
    if typed["trajectory"]["bytes"] != int(current_trajectory.get("bytes")):
        raise CauseBatchError(f"{case_id} typed H5 bytes differ from CURRENT")
    trajectory_stat = typed["trajectory"]
    ledger = typed["fluid_ledger"] if isinstance(typed["fluid_ledger"], dict) else {}
    initial_count = int(ledger.get("initial_count", -1))
    first_count = int(ledger.get("first_disappearance_count", -1))
    expected_initial = 327680 if family == "F6" else 59072
    if initial_count != expected_initial:
        raise CauseBatchError(f"{case_id} fluid initial count {initial_count} does not match {family} contract {expected_initial}")
    if case_id in consumed:
        raise CauseBatchError(f"{case_id} overlaps a consumed typed/native attempt")
    launchable = family == "F6" and first_count > 0 and native_status == "PER_ID_NATIVE_REPORT_PRESENT" and native is not None and int(native["excluded_count"]) == first_count
    if family == "F6" and native_status == "PER_ID_NATIVE_REPORT_PRESENT" and first_count <= 0:
        raise CauseBatchError(f"{case_id} F6 has native target but no typed first-disappearance target")
    if family == "F4":
        if native_status == "PER_ID_NATIVE_REPORT_PRESENT" and first_count > 0 and scope_row and scope_row.get("classification") == "NATIVE_CAUSE_BOUND_PER_FLUID_ID":
            reason = "ALREADY_SOURCE_BOUND_NATIVE_CAUSE_NO_NEW_UNLOCATED_TARGET"
        else:
            reason = "NO_PER_ID_NATIVE_TARGET_SOURCE_GAP" if first_count == 0 else "TYPED_PROOF_OR_NATIVE_TARGET_NOT_CLOSED"
    else:
        reason = "READY_PARENT_GUARDED_TYPED_NATIVE_JOIN" if launchable else "F6_TYPED_OR_NATIVE_SOURCE_GAP"
    return {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED" if launchable else "SOURCE_GAP_NOT_RUNNABLE",
        "physical_case_id": case_id,
        "family_id": family,
        "current336_index": int(current_row["current336_index"]),
        "proof_batch": proof_key,
        "current_identity": {"path": str(CURRENT_PATH), "sha256": CURRENT_SHA256, "family_id": family,
                              "runtime_case_alias": current_row.get("runtime_case_alias"),
                              "frames": current_row.get("frames"), "particles": current_row.get("particles"),
                              "trajectory": trajectory_stat},
        "typed_evidence": typed,
        "native_evidence": native,
        "native_deferred_inputs": native_deferred or {},
        "source_artifacts": _source_refs(current_row, case_id),
        "historical_scope": {"classification": scope_row.get("classification") if scope_row else "NOT_IN_HISTORICAL_118_SCOPE",
                             "report_native_exit_cause_counts": scope_row.get("report_native_exit_cause_counts") if scope_row else None,
                             "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
        "native_status": native_status,
        "first_disappearance_count": first_count,
        "expected_fluid_initial_count": expected_initial,
        "launchable": launchable,
        "blocked_reason": None if launchable else reason,
        "claim_boundary": {"typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "native_numerical_cause": "PRIOR_SOURCE_BOUND_EVIDENCE_ONLY" if native else "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare": "small proof/source JSON and stat only", "deferred": "typed JSONL, PartOut.csv and RunPARTs.csv after parent reservation", "forbidden": ["H5 content", "BI4/OBI4 content", "solver launch", "PartVTKOut re-decode"]},
    }


def _default_case_ids(proofs: dict[str, dict[str, Any]], consumed: set[str]) -> list[str]:
    candidates = [cid for cid, case in proofs.items() if case.get("family_id") == "F6" and cid not in consumed]
    # The first four are the only current typed F6 cases not represented by
    # ROOT216/219/220.  Keep this explicit so future proof batches cannot
    # silently enlarge ROOT226.
    expected = [
        "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025",
        "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025",
        "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0375_YAWM12_DP025",
        "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0625_YAWM06_DP025",
    ]
    if set(candidates) != set(expected):
        raise CauseBatchError(f"ROOT226 F6 remainder changed: {sorted(candidates)}")
    return expected


def _consumed_cases() -> set[str]:
    consumed = {ROOT216_CASE, ROOT219_CASE}
    if ROOT220_PROOF.is_file():
        consumed.update(_root220_cases())
    return consumed


def _build_contracts(case_ids: Iterable[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    case_ids = list(case_ids)
    if not (1 <= len(case_ids) <= MAX_BATCH_CASES):
        raise CauseBatchError("ROOT226 batch must contain one through eight case IDs")
    if len(set(case_ids)) != len(case_ids):
        raise CauseBatchError("ROOT226 physical case IDs must be unique")
    current, current_rows = _current()
    scope = _scope()
    inventory = _inventory()
    proof_cases, proof_keys = _all_proof_cases()
    consumed = _consumed_cases()
    contracts: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for cid in case_ids:
        row = current_rows.get(cid)
        proof = proof_cases.get(cid)
        if row is None:
            raise CauseBatchError(f"case is absent from CURRENT336: {cid}")
        if proof is None:
            gaps.append({"physical_case_id": cid, "family_id": row.get("family_id"), "status": "SOURCE_GAP_NOT_RUNNABLE", "reason": "NO_COMPLETED_TYPED_PROOF_FOR_THIS_CASE", "current336_index": row["current336_index"]})
            continue
        native, deferred, native_status = _native_edge(inventory.get(cid), cid)
        contract = _contract(cid, row, scope.get(cid), inventory.get(cid), proof, proof_keys[cid], native, deferred, native_status, consumed)
        contracts.append(contract)
        if not contract["launchable"]:
            gaps.append({"physical_case_id": cid, "family_id": row.get("family_id"), "status": contract["status"], "reason": contract["blocked_reason"], "current336_index": row["current336_index"], "first_disappearance_count": contract["first_disappearance_count"], "native_status": native_status})
    if not contracts and not gaps:
        raise CauseBatchError("ROOT226 has no contracts")
    return contracts, gaps


def _gap_descriptor(contract: dict[str, Any]) -> dict[str, Any]:
    """Keep blocked F4 evidence useful without making it executable."""
    typed = contract.get("typed_evidence", {})
    summary = typed.get("summary", {}) if isinstance(typed, dict) else {}
    native = contract.get("native_evidence")
    return {
        "physical_case_id": contract["physical_case_id"],
        "family_id": contract["family_id"],
        "current336_index": contract["current336_index"],
        "status": contract["status"],
        "reason": contract.get("blocked_reason"),
        "first_disappearance_count": contract.get("first_disappearance_count"),
        "expected_fluid_initial_count": contract.get("expected_fluid_initial_count"),
        "native_status": contract.get("native_status"),
        "typed_summary": {"path": summary.get("path"), "sha256": summary.get("sha256"), "bytes": summary.get("bytes")},
        "native_report": {"path": native.get("path"), "sha256": native.get("sha256"), "excluded_count": native.get("excluded_count")} if isinstance(native, dict) else None,
        "native_deferred_paths": sorted(str(item.get("path")) for item in contract.get("native_deferred_inputs", {}).values() if isinstance(item, dict) and item.get("path")),
        "physical_fate": "UNKNOWN",
        "legal_flux": "UNKNOWN",
        "dynamics": "UNKNOWN",
        "QI": "UNKNOWN",
        "QN": "UNKNOWN",
        "QE": "UNKNOWN",
        "read_policy": "source metadata only; no payload content opened",
    }


def _request(manifest_path: Path, manifest: dict[str, Any], request_path: Path) -> dict[str, Any]:
    # Keep the literal venv symlink in the command and bind its resolved
    # interpreter plus pyvenv.cfg as separate source roles.  A parent may
    # rebase these paths, but it must retain both path identities and bytes.
    pyvenv_cfg = VENV.parent.parent / "pyvenv.cfg"
    input_paths: list[Path] = [SCRIPT, manifest_path, CURRENT_PATH, SCOPE_PATH, INVENTORY_PATH, VENV, pyvenv_cfg, CONFIG, *RUNTIME_SOURCES]
    deferred: list[str] = []
    for contract_item in manifest["contracts"]:
        contract_path = _path(contract_item["path"], "ROOT226 case contract")
        input_paths.append(contract_path)
        contract = _json(contract_path, "ROOT226 case contract")
        for ref in contract.get("source_artifacts", {}).values():
            if isinstance(ref, dict) and isinstance(ref.get("path"), str) and ref.get("content_opened") is True:
                p = Path(ref["path"]).expanduser().resolve()
                if p.is_file() and p.stat().st_size <= MAX_SMALL_BYTES:
                    input_paths.append(p)
        typed = contract.get("typed_evidence", {})
        trajectory = typed.get("trajectory", {}) if isinstance(typed, dict) else {}
        if isinstance(trajectory, dict) and isinstance(trajectory.get("path"), str):
            deferred.append(str(Path(trajectory["path"]).expanduser().resolve()))
        records = typed.get("records", {}) if isinstance(typed, dict) else {}
        if isinstance(records, dict) and isinstance(records.get("path"), str):
            deferred.append(str(Path(records["path"]).expanduser().resolve()))
        for ref in contract.get("native_deferred_inputs", {}).values():
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                deferred.append(str(Path(ref["path"]).expanduser().resolve()))
    unique = sorted({p.expanduser().resolve() for p in input_paths if p.is_file() and p.suffix.lower() not in {".h5", ".hdf5", ".jsonl", ".bi4", ".obi4"}})
    input_sha: dict[str, str] = {}
    for p in unique:
        input_sha[str(p)] = _digest(p, "ROOT226 static request input", max_bytes=MAX_SMALL_BYTES)
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "task_kind": "audit",
        "family_id": "F4_F6",
        "batch_id": "ROOT226",
        "worker_version": "native-typed-cause-batch.v2",
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path.absolute()), "--output", "{attempt_root}/native-typed-cause-batch-v2-summary.json"],
        "input_files": [str(p) for p in unique],
        "input_sha256": input_sha,
        "interpreter_binding": {"literal_command_path": str(VENV), "resolved_path": str(VENV.resolve()), "sha256": input_sha[str(VENV.resolve())], "pyvenv_cfg": {"path": str(pyvenv_cfg.resolve()), "sha256": input_sha[str(pyvenv_cfg.resolve())]}},
        "deferred_input_files": sorted(set(deferred)),
        "deferred_input_policy": "ONE_SEQUENTIAL_PASS_PER_CASE_AFTER_PARENT_RESERVATION; F4_ADAPTER_MUST_BE_FAMILY_SPECIFIC",
        "resource_policy": manifest["resource_policy"],
        "claim_boundary": manifest["claim_boundary"],
        "launch_allowed": False,
        "launch_owner": "root",
        "source_closure": {"manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT226 manifest", max_bytes=MAX_SMALL_BYTES), "current_sha256": CURRENT_SHA256, "payload_content_opened_prepare": False},
        "source_gap_cases": manifest["source_gap_cases"],
    }
    _atomic(request_path, request)
    return request


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    proof_cases, _ = _all_proof_cases()
    consumed = _consumed_cases()
    case_ids = list(args.case_id) if args.case_id else _default_case_ids(proof_cases, consumed)
    contracts, gaps = _build_contracts(case_ids)
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise CauseBatchError(f"ROOT226 output root already exists: {output_root}")
    contract_dir = output_root / "case-contracts"
    contract_items: list[dict[str, Any]] = []
    for contract in contracts:
        path = contract_dir / f"{contract['physical_case_id']}.json"
        _atomic(path, contract, limit=MAX_CONTRACT_BYTES)
        contract_items.append({"physical_case_id": contract["physical_case_id"], "family_id": contract["family_id"], "path": str(path), "sha256": _digest(path, "ROOT226 case contract", max_bytes=MAX_CONTRACT_BYTES), "launchable": contract["launchable"]})
    launchable = [item for item in contract_items if item["launchable"]]
    deferred_bytes = 0
    for contract in contracts:
        if not contract["launchable"]:
            continue
        deferred_bytes += int(contract["typed_evidence"]["records"]["bytes"])
        for ref in contract.get("native_deferred_inputs", {}).values():
            deferred_bytes += int(ref["bytes"])
    if deferred_bytes > MAX_BATCH_SOURCE_BYTES:
        raise CauseBatchError("ROOT226 deferred source estimate exceeds 20 GiB")
    f4_root201 = [cid for cid, case in proof_cases.items() if case.get("family_id") == "F4"]
    f4_contracts, f4_gaps = _build_contracts(f4_root201)
    f4_gap_by_id = {item["physical_case_id"]: _gap_descriptor(item) for item in f4_contracts}
    for item in f4_gaps:
        f4_gap_by_id.setdefault(item["physical_case_id"], item)
    selected_gap_ids = {item["physical_case_id"] for item in gaps}
    for item in f4_gap_by_id.values():
        if item["physical_case_id"] not in selected_gap_ids:
            gaps.append(item)
            selected_gap_ids.add(item["physical_case_id"])
    manifest = {
        "schema": BATCH_SCHEMA,
        "status": "SOURCE_PREPARED_NO_LAUNCH",
        "batch_id": "ROOT226",
        "case_ids": [item["physical_case_id"] for item in contract_items],
        "contracts": contract_items,
        "source_gap_cases": gaps,
        "candidate_scope": {"root220_consumed_cases": sorted(_root220_cases()), "root216_case": ROOT216_CASE, "root219_case": ROOT219_CASE, "f4_root201_cases": f4_root201},
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "max_cases_per_batch": MAX_BATCH_CASES, "case_count": len(contract_items), "launchable_case_count": len(launchable), "max_deferred_source_bytes": MAX_BATCH_SOURCE_BYTES, "estimated_deferred_source_bytes": deferred_bytes, "one_sequential_case_at_a_time": True, "case_output_cap_bytes": 8 * 1024 * 1024, "batch_output_cap_bytes": 64 * 1024 * 1024, "h5_content_read": False, "native_bi4_read": False, "solver_launch": False},
        "claim_boundary": {"native_cause": "prior source-bound report only; new join pending guarded run", "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "target_identity_is_not_physical_case": True, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_policy": "Read bounded proofs/source JSON and stat-only deferred files at prepare. H5, typed JSONL, PartOut, RunPARTs and BI4 content are not opened; no solver or PartVTKOut is launched.",
        "launch_allowed": False,
    }
    manifest_path = output_root / "native-typed-cause-batch-v2-manifest.json"
    _atomic(manifest_path, manifest, limit=MAX_SMALL_BYTES)
    result: dict[str, Any] = {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT226 manifest", max_bytes=MAX_SMALL_BYTES), "contract_count": len(contracts), "source_gap_count": len(manifest["source_gap_cases"]), "launchable_case_ids": [x["physical_case_id"] for x in launchable], "estimated_deferred_source_bytes": deferred_bytes, "launch_allowed": False}
    if args.request_output:
        request_path = Path(args.request_output).expanduser().resolve()
        _request(manifest_path, manifest, request_path)
        result.update({"request": str(request_path), "request_sha256": _digest(request_path, "ROOT226 request", max_bytes=MAX_SMALL_BYTES)})
    if args.checkpoint:
        checkpoint = Path(args.checkpoint).expanduser().resolve()
        _atomic(checkpoint, {"schema": CHECKPOINT_SCHEMA, "status": "SOURCE_PREPARED_NO_LAUNCH", "batch_id": "ROOT226", "manifest": str(manifest_path), "manifest_sha256": result["manifest_sha256"], "request": result.get("request"), "request_sha256": result.get("request_sha256"), "case_ids": manifest["case_ids"], "launchable_case_ids": result["launchable_case_ids"], "source_gap_cases": manifest["source_gap_cases"], "physical_case_count": len(contracts), "typed_native_physical_cases_prepared": 0, "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "payload_content_opened": False, "solver_launch": False})
        result["checkpoint"] = str(checkpoint)
    return result


def audit(args: argparse.Namespace) -> dict[str, Any]:
    # The guarded implementation is intentionally not silently substituted by
    # this source preparer.  Root must forward a family adapter and new worker
    # SHA before any payload is opened.  This fail-closed path also prevents a
    # future F4 contract from being accidentally sent through an F6 parser.
    manifest = _json(_path(args.manifest, "ROOT226 manifest"), "ROOT226 manifest")
    if manifest.get("schema") != BATCH_SCHEMA or manifest.get("batch_id") != "ROOT226":
        raise CauseBatchError("ROOT226 manifest schema differs")
    raise CauseBatchError("ROOT226 source adapter is prepared only; guarded family adapter must be explicitly forwarded before audit")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="prepare bounded ROOT226 source contracts")
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path)
    prep.add_argument("--checkpoint", type=Path)
    prep.add_argument("--case-id", action="append", default=None)
    run = sub.add_parser("audit", help="fail closed until Root forwards a guarded family adapter")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = prepare(args) if args.command == "prepare" else audit(args)
    except (CauseBatchError, OSError, ValueError) as exc:
        print(f"ROOT226 ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
