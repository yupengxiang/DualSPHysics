#!/usr/bin/env python3
"""Guarded native-cause evidence for exact F4 omission cases (ROOT249 forward V4).

This forward-only worker consumes the small ROOT232 lifecycle manifests and
the immutable 118-case source inventory.  ``prepare`` reads JSON/stat metadata
only.  ``audit`` is the parent-reserved operation: it streams the completed
ROOT232 typed records, runs the official ``PartVTKOut_linux64`` program on
the indexed ``PartOut_000.obi4`` source, and joins exact ``(Zone, Idp)``
first-saved-missing identities to Motive rows and saved RunPARTs brackets.

The join is evidence for a native numerical motive and a saved-frame
bracket.  It does not identify physical fate, legal flux, continuous event
time, or dynamical impact.  The worker never starts a solver or GenCase and
never treats an empty target/global counter as a successful identity join.
Production payloads are deferred until the parent runtime has reserved the
attempt.  The explicit fixture action is parser-only and is never a
scientific result.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Iterable


SCRIPT = Path(__file__).resolve()
LAB_ROOT = SCRIPT.parents[1]
ORIGINAL_LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
STAGE2 = LAB_ROOT / "campaigns/ds-data-02/stage2"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DEFAULT_VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DEFAULT_CONFIG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
PARTVTKOUT = ORIGINAL_LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64"
PARTVTKOUT_SHA256 = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
ROOT232_DEFAULT_PROOF = STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_232.json"
INVENTORY_DEFAULT = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
OVERLAY_DEFAULT = STAGE2 / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT235_ACTUAL_OVERLAY_V5.json"
HISTORICAL_DEFAULT = STAGE2 / "checkpoints/HISTORICAL_118_OMISSION_INDEX_VERIFICATION_001.json"
CURRENT_DEFAULT = STAGE2 / "CURRENT336.json"
ROOT232_MANIFEST_DEFAULT = STAGE2 / "requests/typed-lifecycle-batch-v1-f4-root-prepared-232-001/typed-lifecycle-batch-v1-manifest.json"
ROOT232_REQUEST_DEFAULT = STAGE2 / "requests/typed-lifecycle-batch-v1-f4-root-forward-232-001.json"
ROOT235_DEFAULT_PROOF = STAGE2 / "checkpoints/F4_NATIVE_TYPED_CAUSE_BATCH_V1_ACTUAL_ROOT_VERIFICATION_235.json"
ROOT235_REQUEST_DEFAULT = STAGE2 / "requests/f4-typed-native-cause-batch-v1-root-forward-235-001.json"
BASE_PARTOUT_PARSER = SCRIPT.with_name("ds_data02_stage2_f6_dxyz_typed_native_crosscheck_v3.py")

REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f4-unlocated-native-evidence.v4"
CONTRACT_SCHEMA = "ds02.stage2.f4-unlocated-native-evidence-contract.v4"
REPORT_SCHEMA = "ds02.stage2.f4-unlocated-native-evidence-report.v4"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
ROOT232_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
MAX_SMALL_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_CASE_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_TYPED_RECORDS_BYTES = 512 * 1024 * 1024
MAX_RUNPARTS_BYTES = 32 * 1024 * 1024
MAX_PARTVTK_TIMEOUT = 900

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
MOTIVE_NAMES = {1: "position", 2: "density", 3: "movement"}


class EvidenceError(ValueError):
    """Raised for an open, stale, or semantically ambiguous contract."""


def _validate_official_partvtkout() -> dict[str, Any]:
    """Bind the decoder to the immutable ORIGINAL vendor installation.

    The forensic worktree is allowed to contain the worker source, but it is
    not an implicit vendor installation.  V3 allowed that missing path to
    survive preparation and failed only when the parent entered ``audit``.
    V4 closes that source edge before a request is emitted.  This check is
    bounded to the 6.2 MiB executable and never opens a native payload.
    """
    path = PARTVTKOUT.expanduser().absolute()
    if not path.is_file():
        raise EvidenceError(f"official PartVTKOut tool is missing from ORIGINAL lab tree: {path}")
    if not os.access(path, os.X_OK):
        raise EvidenceError(f"official PartVTKOut tool is not executable: {path}")
    actual = _sha256_file(path, max_bytes=MAX_SMALL_BYTES)
    if actual != PARTVTKOUT_SHA256:
        raise EvidenceError(f"official PartVTKOut SHA differs: {actual} != {PARTVTKOUT_SHA256}")
    stat = _stat(path, "official PartVTKOut tool")
    return {
        **stat,
        "path": str(path),
        "sha256": actual,
        "source_namespace": "ORIGINAL_LAB_VENDOR",
        "executable": True,
        "content_opened_by_preparer": True,
        "native_payload_opened_by_preparer": False,
    }


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise EvidenceError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise EvidenceError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, allow_missing: bool = False, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise EvidenceError(f"{label} lacks a path")
    path = Path(value).expanduser().resolve()
    if not allow_missing and (not path.is_dir() if directory else not path.is_file()):
        raise EvidenceError(f"{label} is missing: {path}")
    return path


def _stat(path: Path, label: str, *, allow_missing: bool = False, directory: bool = False) -> dict[str, Any]:
    path = _path(path, label, allow_missing=allow_missing, directory=directory)
    if allow_missing and not path.exists():
        return {"path": str(path), "status": "DEFERRED_NOT_PRESENT_AT_PREPARE"}
    value = path.stat()
    return {
        "path": str(path), "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev), "st_ino": int(value.st_ino),
    }


def _sha256_file(path: Path, *, max_bytes: int | None = None) -> str:
    size = path.stat().st_size
    if max_bytes is not None and size > max_bytes:
        raise EvidenceError(f"refusing to hash {size} bytes above bound {max_bytes}: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise EvidenceError(f"{label} exceeds bounded JSON size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be a JSON object")
    return value


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    path = _path(path, label)
    stat = _stat(path, label)
    if stat["bytes"] > MAX_SMALL_BYTES:
        raise EvidenceError(f"{label} exceeds small input bound")
    actual = _sha256_file(path, max_bytes=MAX_SMALL_BYTES)
    if expected is not None and expected != "PARENT_GUARD_COMPUTED" and actual != _sha(expected, f"{label} expected SHA"):
        raise EvidenceError(f"{label} SHA differs: expected {expected}, got {actual}")
    return {**stat, "sha256": actual, "content_opened": True}


def _deferred_ref(path: Path, label: str, *, declared_sha: str | None = None, declared_stat: dict[str, Any] | None = None, allow_missing: bool = False, directory: bool = False) -> dict[str, Any]:
    path = _path(path, label, allow_missing=allow_missing, directory=directory)
    result: dict[str, Any] = {
        "path": str(path), "sha256": declared_sha if declared_sha else "PARENT_GUARD_COMPUTED",
        "content_opened_by_preparer": False,
        "read_after_parent_reservation": True,
        "deferred": True,
    }
    if declared_stat:
        for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if declared_stat.get(key) is not None:
                result[key] = int(declared_stat[key])
    elif path.exists():
        # Stat is metadata, not a payload read.  It is retained as a hint only;
        # the worker repeats the full pre/content/post check after reservation.
        result.update(_stat(path, label, directory=directory))
    else:
        result["status"] = "DEFERRED_NOT_PRESENT_AT_PREPARE"
    return result


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise EvidenceError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise EvidenceError(f"output exceeds {limit} bytes: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_partout_parser() -> Any:
    spec = importlib.util.spec_from_file_location("_stage2_official_native_parser", BASE_PARTOUT_PARSER)
    if spec is None or spec.loader is None:
        raise EvidenceError(f"cannot load reviewed native parser: {BASE_PARTOUT_PARSER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _walk_case_rows(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise EvidenceError("native/typed inventory must expose exactly 118 rows")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise EvidenceError("inventory row lacks physical_case_id")
        cid = row["physical_case_id"]
        if cid in result:
            raise EvidenceError(f"duplicate inventory case: {cid}")
        if row.get("historical_118_membership") is not True:
            raise EvidenceError(f"inventory row is not an exact historical member: {cid}")
        result[cid] = row
    return result


def _root232_ids(manifest: dict[str, Any]) -> list[str]:
    if manifest.get("family_id") != "F4" or manifest.get("schema") != "ds02.stage2.typed-lifecycle-batch.v1":
        raise EvidenceError("ROOT232 manifest schema/family differs")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise EvidenceError("ROOT232 manifest must contain exactly eight F4 cases")
    ids: list[str] = []
    for item in cases:
        if not isinstance(item, dict) or not isinstance(item.get("physical_case_id"), str) or item.get("family_id") != "F4":
            raise EvidenceError("ROOT232 case identity is malformed")
        cid = item["physical_case_id"]
        if cid in ids:
            raise EvidenceError(f"ROOT232 duplicate case: {cid}")
        ids.append(cid)
    return ids


def _root235_ids(proof: dict[str, Any]) -> list[str]:
    """Return the already completed ROOT235 joins that ROOT249 must reuse."""
    if proof.get("schema") != ROOT232_PROOF_SCHEMA:
        raise EvidenceError("ROOT235 proof schema differs")
    if proof.get("status") != "VERIFIED_ACTUAL_F4_THREE_CASE_NATIVE_TYPED_FIRST_MISSING_JOINS_NO_NEW_CAUSES_NO_PHYSICAL_CREDIT":
        raise EvidenceError("ROOT235 proof is not the completed no-credit F4 join proof")
    if proof.get("actual_completed_physical_cases") != 3 or proof.get("failed_physical_cases") not in (0, [], None):
        raise EvidenceError("ROOT235 proof does not contain exactly three completed cases")
    rows = proof.get("case_verifications")
    if not isinstance(rows, list) or len(rows) != 3:
        raise EvidenceError("ROOT235 proof case verification count differs")
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("family_id", "F4") != "F4" or not isinstance(row.get("physical_case_id"), str):
            raise EvidenceError("ROOT235 case identity is malformed")
        if row.get("status") not in {None, "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY", "COMPLETED_F4_NATIVE_TYPED_FIRST_MISSING_JOIN_NO_PHYSICAL_CREDIT_V4"}:
            raise EvidenceError(f"ROOT235 case is not a completed diagnostic join: {row.get('physical_case_id')}")
        comparison = row.get("comparison_counts")
        if not isinstance(comparison, dict):
            raise EvidenceError(f"ROOT235 comparison counts are absent: {row.get('physical_case_id')}")
        if any(comparison.get(key) != 0 for key in ("saved_frame_mismatches", "saved_frame_unknown", "typed_times_outside_or_unknown_brackets")):
            raise EvidenceError(f"ROOT235 case has an unresolved saved-frame comparison: {row.get('physical_case_id')}")
        if row["physical_case_id"] in ids:
            raise EvidenceError(f"ROOT235 duplicate case: {row['physical_case_id']}")
        ids.append(row["physical_case_id"])
    return ids


def _inventory_native_edges(row: dict[str, Any], case_id: str) -> dict[str, Any]:
    artifacts = row.get("source_artifacts", {}).get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise EvidenceError(f"{case_id} inventory source artifacts are missing")
    idx = artifacts.get("native_part_directory_stat_index")
    if not isinstance(idx, dict) or not isinstance(idx.get("path"), str):
        raise EvidenceError(f"{case_id} has no native PartOut directory stat index")
    samples = idx.get("entry_samples")
    if not isinstance(samples, list):
        raise EvidenceError(f"{case_id} native directory index has no entry samples")
    obi4 = next((item for item in samples if isinstance(item, dict) and item.get("role") == "native_part_directory:PartOut_000.obi4"), None)
    if not isinstance(obi4, dict) or not isinstance(obi4.get("path"), str):
        raise EvidenceError(f"{case_id} native PartOut_000.obi4 is not indexed")
    report = row.get("original_omission_evidence", {}).get("report")
    if not isinstance(report, dict) or not isinstance(report.get("path"), str) or not isinstance(report.get("declared_sha256"), str):
        raise EvidenceError(f"{case_id} prior native report edge is incomplete")
    data_dir = Path(idx["path"]).expanduser().resolve()
    runparts = data_dir.parent / "RunPARTs.csv"
    generated = artifacts.get("generated_xml")
    conversion = artifacts.get("conversion_report")
    gencase = artifacts.get("gencase_receipt")
    static_artifacts = {}
    for role, ref in (("generated_xml", generated), ("conversion_report", conversion), ("gencase_receipt", gencase)):
        if isinstance(ref, dict) and isinstance(ref.get("path"), str) and isinstance(ref.get("declared_sha256"), str):
            static_artifacts[role] = {"path": ref["path"], "sha256": ref["declared_sha256"], "bytes": ref.get("bytes"), "role": role}
    return {
        "data_dir": _deferred_ref(data_dir, f"{case_id} native data directory", declared_stat=idx.get("stat"), allow_missing=False, directory=True),
        "partout_obi4": _deferred_ref(Path(obi4["path"]), f"{case_id} PartOut_000.obi4", declared_sha="PARENT_GUARD_COMPUTED", declared_stat=obi4.get("stat"), allow_missing=False),
        "runparts_csv": _deferred_ref(runparts, f"{case_id} RunPARTs.csv", declared_sha="PARENT_GUARD_COMPUTED", allow_missing=True),
        "native_report": _deferred_ref(Path(report["path"]), f"{case_id} prior native report", declared_sha=report["declared_sha256"], declared_stat=report.get("stat"), allow_missing=False),
        "native_report_role": report.get("role", "prior_native_omission_report"),
        "static_artifacts": static_artifacts,
    }


def _case_manifest_path(root232_manifest_path: Path, case_id: str) -> Path:
    path = root232_manifest_path.parent / "case-manifests" / case_id / "typed-lifecycle-v4-manifest.json"
    return path


def _root232_lifecycle_ref(proof_case: dict[str, Any], case_id: str, name: str, sha_name: str) -> dict[str, Any]:
    """Return one lifecycle edge from the immutable ROOT232 terminal proof.

    The prepared ROOT232 case manifests contain producer-side placeholder paths
    under ``stage2/requests``.  They describe the request, but they are not the
    paths consumed by the completed run.  V2 therefore requires the completed
    proof's actual edge and its recorded SHA, and refuses to emit a deferred
    edge when either is absent.
    """
    value = proof_case.get(name)
    if isinstance(value, dict):
        ref = dict(value)
    elif isinstance(value, str):
        ref = {"path": value}
    else:
        raise EvidenceError(f"{case_id} ROOT232 proof lacks {name} edge")
    if not isinstance(ref.get("path"), str) or not ref["path"]:
        raise EvidenceError(f"{case_id} ROOT232 proof {name} edge lacks path")
    sha = ref.get("sha256")
    if not isinstance(sha, str):
        sha = proof_case.get(sha_name)
    if not isinstance(sha, str) or sha == "PARENT_GUARD_COMPUTED":
        raise EvidenceError(f"{case_id} ROOT232 proof lacks recorded {name} SHA")
    ref["sha256"] = _sha(sha, f"{case_id} ROOT232 {name} SHA")
    # The proof path is an actual completed output.  V2 must fail during
    # prepare if that deferred edge is stale or points back at the request
    # placeholder rather than silently deferring a nonexistent file.
    _path(ref["path"], f"{case_id} ROOT232 proof {name}")
    return ref


def _case_contract(case_id: str, row: dict[str, Any], root232_manifest_path: Path, root232_proof_case: dict[str, Any], current_path: Path, inventory_path: Path, overlay_path: Path, historical_path: Path) -> dict[str, Any]:
    case_manifest_path = _case_manifest_path(root232_manifest_path, case_id)
    case_manifest = _read_json(case_manifest_path, f"{case_id} ROOT232 case manifest")
    if case_manifest.get("physical_case_id") != case_id or case_manifest.get("family_id") != "F4":
        raise EvidenceError(f"{case_id} ROOT232 case manifest identity differs")
    trajectory = case_manifest.get("trajectory_h5")
    outputs = case_manifest.get("outputs")
    if not isinstance(trajectory, dict) or not isinstance(outputs, dict):
        raise EvidenceError(f"{case_id} ROOT232 deferred lifecycle edges are missing")
    if not isinstance(trajectory.get("path"), str) or not isinstance(trajectory.get("sha256"), str):
        raise EvidenceError(f"{case_id} ROOT232 trajectory edge is incomplete")
    # Do not use outputs.summary/records here.  Those are request-side paths
    # and, for the consumed ROOT232 request, point into the prepared
    # case-manifests tree.  The terminal proof is the authoritative producer
    # of the actual completed summary/records paths.
    summary_ref = _root232_lifecycle_ref(root232_proof_case, case_id, "summary", "summary_sha256")
    records_ref = _root232_lifecycle_ref(root232_proof_case, case_id, "records_stat_only", "records_sha256")
    native = _inventory_native_edges(row, case_id)
    artifacts = row["source_artifacts"]["artifacts"]
    source_edges: dict[str, Any] = {}
    # These paths are source identity edges.  Their contents are not opened by
    # prepare; parent runtime performs the authoritative pre/post checks.
    for role, key in (("generated_xml", "generated_xml"), ("conversion_report", "conversion_report"), ("gencase_receipt", "gencase_receipt"), ("current_case_manifest", "manifest"), ("owner_metadata", "owner_metadata"), ("xmf", "xmf")):
        ref = artifacts.get(key)
        if isinstance(ref, dict) and isinstance(ref.get("path"), str) and isinstance(ref.get("declared_sha256"), str):
            source_edges[role] = {"path": str(Path(ref["path"]).expanduser().resolve()), "sha256": ref["declared_sha256"], "bytes": ref.get("bytes"), "content_opened_by_preparer": False}
    current_row = row.get("identity", {})
    return {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_NATIVE_AUDIT_NOT_LAUNCHED",
        "launchable": True,
        "physical_case_id": case_id,
        "family_id": "F4",
        "historical_118_membership": {"exact": True, "source": str(historical_path), "source_sha256": _sha256_file(historical_path, max_bytes=MAX_SMALL_BYTES)},
        "native_omission_scope": "ORIGINAL118_UNLOCATED_AFTER_COMPLETED_SCAN",
        "root232_case_manifest": {"path": str(case_manifest_path.resolve()), "sha256": _sha256_file(case_manifest_path, max_bytes=MAX_SMALL_BYTES), "content_opened_by_preparer": True},
        "root232_deferred": {
            "summary": _deferred_ref(Path(summary_ref["path"]), f"{case_id} ROOT232 typed summary", declared_sha=summary_ref["sha256"], declared_stat=summary_ref, allow_missing=False),
            "records": _deferred_ref(Path(records_ref["path"]), f"{case_id} ROOT232 typed records", declared_sha=records_ref["sha256"], declared_stat=records_ref, allow_missing=False),
            "trajectory_h5": _deferred_ref(Path(trajectory["path"]), f"{case_id} trajectory H5", declared_sha=trajectory["sha256"], declared_stat=trajectory, allow_missing=False),
            "case_manifest_status": case_manifest.get("status"),
            "terminal_proof_case": {
                "physical_case_id": case_id,
                "summary": summary_ref,
                "records_stat_only": records_ref,
            },
        },
        "source_edges": {
            "current336": {"path": str(current_path.resolve()), "sha256": CURRENT_SHA256, "content_opened_by_preparer": True},
            "inventory": {"path": str(inventory_path.resolve()), "sha256": _sha256_file(inventory_path, max_bytes=MAX_SMALL_BYTES), "content_opened_by_preparer": True},
            "overlay": {"path": str(overlay_path.resolve()), "sha256": _sha256_file(overlay_path, max_bytes=MAX_SMALL_BYTES), "content_opened_by_preparer": True},
            **source_edges,
        },
        "native_deferred": native,
        "official_decoder": {"tool": "PartVTKOut_linux64", "path": str(PARTVTKOUT.resolve()), "sha256": PARTVTKOUT_SHA256, "command_template": ["{partvtkout}", "-dirdata", "{native_data_dir}", "-savecsv", "{attempt_root}/PartOut.csv", "-saveresume", "{attempt_root}/resume.csv", "-createdirs:1", "-csvsep:1"]},
        "typed_native_join": {"identity_key": "(Zone, Idp)", "typed_target_definition": "fluid rows with first_disappeared_frame in completed ROOT232 records", "native_target_definition": "official PartVTKOut rows from this case's PartOut_000.obi4", "zone_policy": "PartOut.csv has no Zone; exact join requires one typed target Zone and reports inferred Zone=0", "empty_target_policy": "reject; no global counter or empty report can pass", "unknown_if": ["native PartOut rows cannot be assigned to exact typed identities", "saved bracket cannot be matched by official RunPARTs", "source changed between pre/content/post"],},
        "claim_boundary": {"native_motive": "SOURCE_BOUND_OFFICIAL_PARTVTKOUT_NUMERICAL_MOTIVE_ONLY", "saved_bracket": "OBSERVED_SAVED_RECORD_BRACKET_ONLY", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare": "bounded JSON and stat metadata only", "audit": "ROOT232 JSONL plus native report/OBI4/RunPARTs after parent reservation; one sequential pass per source", "forbidden": ["H5 content", "Part_*.bi4 content", "solver launch", "GenCase launch", "CFD/model"]},
        "identity_metadata": {"current_physical_case_id": current_row.get("current_physical_case_id", case_id), "current_identity_match": current_row.get("current_identity_match"), "trajectory_sha256": current_row.get("current_trajectory_declared_sha256")},
    }


def _validate_metadata(current_path: Path, inventory_path: Path, overlay_path: Path, historical_path: Path, root232_manifest_path: Path, root235_proof_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[str], set[str], list[str]]:
    if _sha256_file(current_path, max_bytes=MAX_SMALL_BYTES) != CURRENT_SHA256:
        raise EvidenceError("CURRENT336 SHA differs from frozen exact actor")
    current = _read_json(current_path, "CURRENT336")
    if current.get("schema") != CURRENT_SCHEMA:
        raise EvidenceError("CURRENT336 schema differs")
    inventory = _read_json(inventory_path, "historical native/typed inventory")
    rows = _walk_case_rows(inventory)
    overlay = _read_json(overlay_path, "original118 native-cause overlay")
    if overlay.get("physical_case_count") != 118 or overlay.get("native_cause_bound_per_fluid_id_cases") != 65 or overlay.get("cause_not_located_after_completed_scan_cases") != 53:
        raise EvidenceError("original118 overlay counts are not the frozen 65/53 scope")
    unlocated = set(overlay.get("remaining_cause_not_located_case_ids", []))
    if len(unlocated) != 53:
        raise EvidenceError("overlay unlocated membership is not exactly 53")
    historical = _read_json(historical_path, "historical 118 membership index")
    if historical.get("exact_historical118_membership_verified") is not True:
        raise EvidenceError("historical 118 index is not exact")
    root232 = _read_json(root232_manifest_path, "ROOT232 lifecycle manifest")
    root_ids = _root232_ids(root232)
    root235 = _read_json(root235_proof_path, "ROOT235 completed F4 join proof")
    root235_ids = _root235_ids(root235)
    selected = [cid for cid in root_ids if cid in rows and cid in unlocated and cid not in root235_ids]
    if not selected:
        raise EvidenceError("ROOT232 has no exact original118 unlocated F4 case")
    if len(set(selected)) != len(selected):
        raise EvidenceError("selected ROOT232 case IDs are not unique")
    return current, rows, selected, set(root_ids) - set(selected), root235_ids


def _runtime_static_inputs(script: Path, manifest_path: Path, contracts: Iterable[Path], static_edges: Iterable[dict[str, Any]], venv: Path, config: Path) -> tuple[list[Path], dict[str, str]]:
    paths: set[Path] = {script.resolve(), BASE_PARTOUT_PARSER.resolve(), manifest_path.resolve(), PARTVTKOUT.resolve(), venv.resolve(), config.resolve()}
    pyvenv = venv.parent.parent / "pyvenv.cfg"
    paths.add(pyvenv.resolve())
    for path in (STAGE2 / "scripts/ds_data02_runtime_v2.py",):
        if path.is_file():
            paths.add(path.resolve())
    for contract in contracts:
        paths.add(contract.resolve())
    for edge in static_edges:
        try:
            path = Path(str(edge["path"])).expanduser().resolve()
        except (KeyError, TypeError, ValueError):
            continue
        if path.is_file() and path.suffix.lower() not in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl", ".csv"}:
            paths.add(path)
    # Runtime files live beside this script in the lab, not below campaigns.
    for name in ("ds_data02_runtime_v2.py", "ds_data02_runtime_v6.py", "ds_data02_runtime_v8.py", "ds_data02_stage2_dispatch_v8.py", "ds_data02_strict_dispatch_v8.py"):
        path = script.parent / name
        if path.is_file():
            paths.add(path.resolve())
    actual_paths = sorted((path for path in paths if path.is_file()), key=str)
    hashes: dict[str, str] = {}
    for path in actual_paths:
        size = path.stat().st_size
        if size > MAX_SMALL_BYTES:
            raise EvidenceError(f"static source exceeds small closure bound: {path}")
        hashes[str(path)] = _sha256_file(path, max_bytes=MAX_SMALL_BYTES)
    return actual_paths, hashes


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    official_tool_ref = _validate_official_partvtkout()
    current_path = _path(args.current, "CURRENT336")
    inventory_path = _path(args.inventory, "native/typed inventory")
    overlay_path = _path(args.overlay, "original118 overlay")
    historical_path = _path(args.historical, "historical 118 index")
    root232_manifest_path = _path(args.root232_manifest, "ROOT232 manifest")
    root235_proof_path = _path(args.root235_proof, "ROOT235 completed F4 join proof")
    _current, rows, selected, excluded, root235_ids = _validate_metadata(current_path, inventory_path, overlay_path, historical_path, root232_manifest_path, root235_proof_path)
    root232_ids = _root232_ids(_read_json(root232_manifest_path, "ROOT232 manifest"))
    reused_root235_ids = sorted(set(root235_ids) & set(root232_ids))
    # V2 only prepares from a completed ROOT232 terminal proof.  The request
    # manifest's case-manifest output paths are producer placeholders; use the
    # proof's actual completed output edges for every deferred input.
    proof_path = Path(args.root232_proof).expanduser().resolve() if args.root232_proof else ROOT232_DEFAULT_PROOF
    proof_path = _path(proof_path, "ROOT232 terminal proof")
    if proof_path.stat().st_size > MAX_SMALL_BYTES:
        raise EvidenceError("ROOT232 proof exceeds bounded metadata size")
    proof = _read_json(proof_path, "ROOT232 terminal proof")
    proof_cases = {case_id: _proof_case(proof, case_id) for case_id in selected}
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise EvidenceError(f"refusing to overwrite output root: {output_root}")
    contract_dir = output_root / "case-contracts"
    contract_paths: list[Path] = []
    contracts: list[dict[str, Any]] = []
    for cid in selected:
        contract = _case_contract(cid, rows[cid], root232_manifest_path, proof_cases[cid], current_path, inventory_path, overlay_path, historical_path)
        path = contract_dir / f"{cid}.json"
        _atomic(path, contract, limit=MAX_CASE_OUTPUT_BYTES)
        contract_paths.append(path)
        contracts.append(contract)
    contract_entries = [{"physical_case_id": c["physical_case_id"], "family_id": "F4", "path": str(p), "sha256": _sha256_file(p, max_bytes=MAX_CASE_OUTPUT_BYTES), "bytes": p.stat().st_size, "membership": "ORIGINAL118_UNLOCATED"} for c, p in zip(contracts, contract_paths)]
    proof_ref = {"path": str(proof_path), "sha256": _sha256_file(proof_path, max_bytes=MAX_SMALL_BYTES), "content_opened_by_preparer": True, "deferred": False}
    static_edges = []
    for c in contracts:
        static_edges.extend(c.get("source_edges", {}).values())
    static_paths, static_hashes = _runtime_static_inputs(SCRIPT, root232_manifest_path, contract_paths, static_edges, Path(args.python).expanduser(), Path(args.runtime_config).expanduser())
    for extra in (ROOT232_REQUEST_DEFAULT, proof_path, ROOT235_REQUEST_DEFAULT, root235_proof_path):
        if extra is not None and extra.is_file():
            extra = extra.resolve()
            if extra.stat().st_size > MAX_SMALL_BYTES:
                raise EvidenceError(f"ROOT249 static edge exceeds small closure bound: {extra}")
            static_hashes[str(extra)] = _sha256_file(extra, max_bytes=MAX_SMALL_BYTES)
            static_paths.append(extra)
    static_paths = sorted(set(static_paths), key=str)
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "READY_PARENT_GUARDED_NATIVE_AUDIT_NOT_LAUNCHED",
        "batch_id": "ROOT249_F4_UNLOCATED_NATIVE_EVIDENCE_V4", "family_id": "F4",
        "root232_manifest": {"path": str(root232_manifest_path), "sha256": _sha256_file(root232_manifest_path, max_bytes=MAX_SMALL_BYTES)},
        "root232_request": {"path": str((root232_manifest_path.parent.parent / "typed-lifecycle-batch-v1-f4-root-forward-232-001.json")), "sha256": _sha256_file(ROOT232_REQUEST_DEFAULT, max_bytes=MAX_SMALL_BYTES) if ROOT232_REQUEST_DEFAULT.is_file() else "UNKNOWN"},
        "root232_terminal_proof": proof_ref,
        "root235_completed_join_proof": {"path": str(root235_proof_path), "sha256": _sha256_file(root235_proof_path, max_bytes=MAX_SMALL_BYTES), "content_opened_by_preparer": True, "reused_case_ids": reused_root235_ids},
        "root235_request": {"path": str(ROOT235_REQUEST_DEFAULT), "sha256": _sha256_file(ROOT235_REQUEST_DEFAULT, max_bytes=MAX_SMALL_BYTES) if ROOT235_REQUEST_DEFAULT.is_file() else "UNKNOWN"},
        "current336": {"path": str(current_path), "sha256": CURRENT_SHA256},
        "inventory": {"path": str(inventory_path), "sha256": _sha256_file(inventory_path, max_bytes=MAX_SMALL_BYTES)},
        "overlay": {"path": str(overlay_path), "sha256": _sha256_file(overlay_path, max_bytes=MAX_SMALL_BYTES)},
        "historical_index": {"path": str(historical_path), "sha256": _sha256_file(historical_path, max_bytes=MAX_SMALL_BYTES)},
        "contracts": contract_entries,
        "selected_case_ids": sorted(selected),
        "excluded_root232_cases": [{"physical_case_id": cid, "status": "REUSED_ROOT235_COMPLETED_NATIVE_TYPED_JOIN_NO_RERUN" if cid in reused_root235_ids else "NOT_EXACT_ORIGINAL118_UNLOCATED_MEMBER_NO_NATIVE_AUDIT"} for cid in sorted(excluded)],
        "reused_root235_case_ids": reused_root235_ids,
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "one_sequential_case_at_a_time": True, "case_count": len(selected), "typed_jsonl_passes_per_case": 1, "native_obi4_hash_passes": 2, "native_obi4_official_partvtkout_passes": 1, "runparts_passes": 1, "output_cap_bytes": MAX_OUTPUT_BYTES, "solver_started": False, "h5_content_read": False, "part_frames_content_read": False},
        "source_read_cost": {"typed_records_cap_bytes_per_case": 536870912, "native_partout_obi4_bytes_from_inventory": sum(int(c["native_deferred"]["partout_obi4"].get("bytes", 0)) for c in contracts), "native_report_bytes_from_inventory": sum(int(c["native_deferred"]["native_report"].get("bytes", 0)) for c in contracts), "runparts_bytes": "PARENT_GUARD_COMPUTED", "partvtk_output": "bounded_by_case_output_cap", "h5_content_read": False, "large_jsonl_read": "ROOT232 typed records only, one sequential pass per case"},
        "claim_boundary": {"native_motive": "NUMERICAL_PARTVTKOUT_MOTIVE_ONLY", "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "original118_cause_scope": "Only selected exact original118 unlocated cases; no global-count inference", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare": "JSON/stat/source SHA only; no H5/JSONL/BI4/OBI4/CSV content", "audit": "ROOT232 typed JSONL and indexed native report/OBI4/RunPARTs after parent reservation", "forbidden": ["solver", "GenCase", "CFD/model", "Part_*.bi4 frame content", "physical-fate inference from counts"]},
        "source_closure": {"script": str(SCRIPT), "script_sha256": _sha256_file(SCRIPT, max_bytes=MAX_SMALL_BYTES), "static_input_paths": [str(p) for p in static_paths], "static_input_sha256": static_hashes, "official_partvtkout": official_tool_ref, "payload_content_opened_by_preparer": False},
        "launch_allowed": True,
        "launch_owner": "root",
    }
    manifest_path = output_root / "f4-unlocated-native-evidence-v4-manifest.json"
    _atomic(manifest_path, manifest)
    request_path = Path(args.request_output).expanduser().resolve()
    command = [str(Path(args.python).expanduser()), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--root232-proof", str(proof_path), "--output", "{attempt_root}/f4-unlocated-native-evidence-v4.json"]
    input_paths = list(static_hashes)
    input_sha = dict(static_hashes)
    input_paths.extend([str(manifest_path)])
    input_sha[str(manifest_path)] = _sha256_file(manifest_path, max_bytes=MAX_OUTPUT_BYTES)
    deferred: list[dict[str, Any]] = []
    for contract in contracts:
        # The lifecycle H5 is already source-closed by ROOT232 and is only an
        # identity edge here.  It is deliberately absent from deferred
        # payload files so this native audit cannot trigger a second H5 read.
        deferred.extend([contract["root232_deferred"]["summary"], contract["root232_deferred"]["records"], contract["native_deferred"]["native_report"], contract["native_deferred"]["partout_obi4"], contract["native_deferred"]["runparts_csv"]])
    request = {
        "schema": REQUEST_SCHEMA, "shared_runtime_version": "v8", "family_id": "F4", "case_id": "ROOT249_F4_UNLOCATED_NATIVE_EVIDENCE_V4", "physical_case_ids": sorted(selected), "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "max_memory_bytes": 4 * 1024 * 1024 * 1024, "estimated_storage_bytes": MAX_OUTPUT_BYTES, "estimated_cpu_core_hours": 1.0, "estimated_gpu_seconds": 0,
        "cwd": str(LAB_ROOT), "worktree_root": str(LAB_ROOT.parent), "command": command, "input_files": sorted(set(input_paths)), "input_sha256": dict(sorted(input_sha.items())), "deferred_input_files": sorted({str(item["path"]) for item in deferred}), "deferred_input_records": deferred, "output_files": ["{attempt_root}/f4-unlocated-native-evidence-v4.json", "{attempt_root}/cases/*.json"], "manifest_contract": {"path": str(manifest_path), "sha256": input_sha[str(manifest_path)]},
        "interpreter_binding": {"literal_path": str(Path(args.python).expanduser()), "resolved_path": str(Path(args.python).expanduser().resolve()), "sha256": static_hashes.get(str(Path(args.python).expanduser().resolve()), "PARENT_GUARD_COMPUTED"), "pyvenv_cfg_path": str((Path(args.python).expanduser().parent.parent / "pyvenv.cfg").resolve())},
        "guarded_payload_binding": {"ROOT232_typed_records": "deferred_after_parent_reservation_pre_hash_stream_post_hash", "native_omission_report": "deferred_after_parent_reservation_pre_hash_read_post_hash", "native_PartOut_000_obi4": "deferred_after_parent_reservation_pre_hash_official_PartVTKOut_post_hash", "native_RunPARTs": "deferred_after_parent_reservation_pre_hash_read_post_hash", "trajectory_h5": "stat_only_no_content_read", "solver_started": False},
        "source_read_cost": manifest["source_read_cost"], "claim_boundary": manifest["claim_boundary"], "root232_terminal_required": True, "root235_reused_join_required": True, "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "request_note": "Only exact ROOT232 cases that are members of the original118 unlocated set and are not already joined by ROOT235 are audited. ROOT235 overlap is reused without a second PartOut decode. Nonmembers are explicitly excluded. No empty/global target can pass. Physical fate, flux, dynamics, and Q remain UNKNOWN.",
    }
    _atomic(request_path, request)
    result = {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _sha256_file(manifest_path, max_bytes=MAX_OUTPUT_BYTES), "request": str(request_path), "request_sha256": _sha256_file(request_path, max_bytes=MAX_OUTPUT_BYTES), "selected_case_ids": sorted(selected), "excluded_root232_cases": sorted(excluded), "case_count": len(selected), "root232_terminal_proof_present": True, "launch_allowed": True, "payload_content_opened_by_preparer": False, "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    if args.checkpoint:
        checkpoint = Path(args.checkpoint).expanduser().resolve()
        _atomic(checkpoint, {"schema": "ds02.stage2.f4-unlocated-native-evidence-root238.v3", "status": "SOURCE_PREPARED_NO_PAYLOAD_READ", **result})
        result["checkpoint"] = str(checkpoint)
    return result


def _same_stat(actual: dict[str, Any], declared: dict[str, Any], label: str) -> None:
    for field in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if declared.get(field) is not None and actual.get(field) != declared.get(field):
            raise EvidenceError(f"{label} stat differs at {field}")


def _guarded_file(path: Path, label: str, *, expected_sha: str | None = None, max_bytes: int | None = None) -> tuple[dict[str, Any], str]:
    before = _stat(path, f"{label} pre")
    digest = _sha256_file(path, max_bytes=max_bytes)
    if expected_sha and expected_sha != "PARENT_GUARD_COMPUTED" and digest != _sha(expected_sha, f"{label} expected SHA"):
        raise EvidenceError(f"{label} pre SHA differs")
    after = _stat(path, f"{label} post")
    if before != after:
        raise EvidenceError(f"{label} changed during guarded pass")
    return {"pre_stat": before, "post_stat": after, "sha256": digest, "single_pass": True}, digest


def _guarded_json(path: Path, label: str, *, expected_sha: str | None = None, max_bytes: int = MAX_SMALL_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read and hash one small JSON object in the same guarded pass."""
    before = _stat(path, f"{label} pre")
    if before["bytes"] > max_bytes:
        raise EvidenceError(f"{label} exceeds bounded JSON size")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha and expected_sha != "PARENT_GUARD_COMPUTED" and digest != _sha(expected_sha, f"{label} expected SHA"):
        raise EvidenceError(f"{label} pre SHA differs")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be a JSON object")
    after = _stat(path, f"{label} post")
    if before != after:
        raise EvidenceError(f"{label} changed during guarded pass")
    return value, {"pre_stat": before, "post_stat": after, "sha256": digest, "single_pass": True}


def _proof_case(proof: dict[str, Any], case_id: str) -> dict[str, Any]:
    if proof.get("schema") != ROOT232_PROOF_SCHEMA:
        raise EvidenceError("ROOT232 terminal proof schema differs")
    candidates: list[dict[str, Any]] = []
    for key in ("case_verifications", "cases", "case_results"):
        value = proof.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    rows = [row for row in candidates if row.get("physical_case_id") == case_id]
    if len(rows) != 1:
        raise EvidenceError(f"ROOT232 terminal proof does not uniquely contain {case_id}")
    row = rows[0]
    if row.get("status") not in {"VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY", "COMPLETED", "COMPLETED_TYPED_LIFECYCLE_NO_PHYSICAL_CREDIT"}:
        raise EvidenceError(f"ROOT232 case is not completed: {case_id}")
    if row.get("family_id") != "F4":
        raise EvidenceError(f"ROOT232 proof family differs: {case_id}")
    return row


def _proof_ref(row: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any] | None:
    for name in names:
        value = row.get(name)
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            return value
        if isinstance(value, str):
            return {"path": value, "sha256": "PARENT_GUARD_COMPUTED"}
    return None


def _iter_records(path: Path, expected_sha: str | None, summary: dict[str, Any], case_id: str) -> tuple[dict[str, Any], dict[tuple[int, int], dict[str, Any]], dict[str, Any]]:
    before = _stat(path, f"{case_id} typed records pre")
    if before["bytes"] > MAX_TYPED_RECORDS_BYTES:
        raise EvidenceError(f"{case_id} typed records exceed bounded 512 MiB audit input")
    digest = hashlib.sha256()
    header: dict[str, Any] | None = None
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    first_missing: dict[tuple[int, int], dict[str, Any]] = {}
    count = 0
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                raise EvidenceError(f"{case_id} typed records blank line {line_no}")
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise EvidenceError(f"{case_id} typed records invalid JSON line {line_no}") from exc
            if line_no == 1:
                if not isinstance(value, dict) or value.get("record_fields") != "one row per static (Zone, Idp); saved-frame lifecycle only":
                    raise EvidenceError(f"{case_id} typed record header is not the ROOT232 v4 contract")
                header = value
                continue
            if not isinstance(value, dict):
                raise EvidenceError(f"{case_id} typed record row is not an object")
            try:
                key = (int(value["zone"]), int(value["idp"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise EvidenceError(f"{case_id} typed record identity is malformed at line {line_no}") from exc
            if key in rows:
                raise EvidenceError(f"{case_id} typed records duplicate identity {key}")
            rows[key] = value
            count += 1
            if value.get("initial_role") == "fluid" and value.get("first_disappeared_frame") is not None:
                first_missing[key] = value
    if header is None:
        raise EvidenceError(f"{case_id} typed records header is missing")
    after = _stat(path, f"{case_id} typed records post")
    actual_sha = digest.hexdigest()
    if before != after:
        raise EvidenceError(f"{case_id} typed records changed during stream")
    if expected_sha and expected_sha != "PARENT_GUARD_COMPUTED" and actual_sha != expected_sha:
        raise EvidenceError(f"{case_id} typed records SHA differs from ROOT232 proof")
    summary_records = summary.get("records") if isinstance(summary.get("records"), dict) else {}
    if summary_records.get("rows") is not None and int(summary_records["rows"]) != count:
        raise EvidenceError(f"{case_id} typed records row count differs from summary")
    return header, rows, {"pre_stat": before, "post_stat": after, "sha256": actual_sha, "rows": count, "first_missing_count": len(first_missing), "first_missing": first_missing}


def _partout_csv(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required = {"PartOut", "Motive", "Idp", "Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Rhop [kg/m^3]"}
    before = _stat(path, "official PartVTKOut CSV pre")
    if before["bytes"] > MAX_CASE_OUTPUT_BYTES:
        raise EvidenceError("official PartVTKOut CSV exceeds bounded case output size")
    digest = hashlib.sha256()
    rows: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        raw = stream.read()
        digest.update(raw)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise EvidenceError("official PartVTKOut CSV header is incomplete")
        seen: set[int] = set()
        for line_no, item in enumerate(reader, 2):
            if not isinstance(item, dict):
                raise EvidenceError(f"official PartVTKOut CSV row {line_no} is malformed")
            try:
                idp = int(item["Idp"]); part = int(item["PartOut"]); motive = int(item["Motive"])
            except (KeyError, TypeError, ValueError) as exc:
                raise EvidenceError(f"official PartVTKOut CSV row {line_no} identity is malformed") from exc
            if idp < 0 or part < 0 or motive < 0 or idp in seen:
                raise EvidenceError(f"official PartVTKOut CSV row {line_no} has invalid/duplicate identity")
            seen.add(idp)
            values: dict[str, float] = {}
            for name in ("Pos.x [m]", "Pos.y [m]", "Pos.z [m]", "Rhop [kg/m^3]"):
                try: value = float(item[name])
                except (KeyError, TypeError, ValueError) as exc: raise EvidenceError(f"official PartVTKOut CSV row {line_no} {name} is malformed") from exc
                if not math.isfinite(value): raise EvidenceError(f"official PartVTKOut CSV row {line_no} {name} is non-finite")
                values[name] = value
            rows.append({"zone": 0, "idp": idp, "part_out": part, "motive_code": motive, "motive": MOTIVE_NAMES.get(motive, "UNKNOWN_MOTIVE"), **values})
    except UnicodeError as exc:
        raise EvidenceError("official PartVTKOut CSV is not UTF-8") from exc
    after = _stat(path, "official PartVTKOut CSV post")
    if before != after:
        raise EvidenceError("official PartVTKOut CSV changed during read")
    return rows, {"pre_stat": before, "post_stat": after, "sha256": digest.hexdigest(), "rows": len(rows), "single_pass": True}


def _number(value: str, label: str, integer: bool = False) -> int | float:
    text = value.strip().replace(",", "").replace("_", "")
    try: result = int(text) if integer else float(text)
    except ValueError as exc: raise EvidenceError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(float(result)) or result < 0: raise EvidenceError(f"{label} is invalid: {value!r}")
    return result


def _runparts(path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    before = _stat(path, "RunPARTs.csv pre")
    if before["bytes"] > MAX_RUNPARTS_BYTES: raise EvidenceError("RunPARTs.csv exceeds bounded audit size")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw)
    rows: list[dict[str, Any]] = []
    header: list[str] | None = None
    footer = 0
    for line_no, fields in enumerate(csv.reader(io.StringIO(raw.decode("utf-8")), delimiter=";"), 1):
        fields = [field.strip().lstrip("\ufeff") for field in fields]
        if not any(fields): continue
        if ";".join(fields).strip().startswith("#"): footer += 1; continue
        if header is None:
            header = fields
            if len(header) != len(RUNPARTS_COLUMNS) or len(set(header)) != len(header) or set(header) != set(RUNPARTS_COLUMNS):
                raise EvidenceError("RunPARTs.csv official 26-column header differs")
            continue
        if len(fields) != len(header): raise EvidenceError(f"RunPARTs.csv row {line_no} has wrong column count")
        values = {name: _number(value, f"RunPARTs row {line_no} {name}", name in RUNPARTS_INT_COLUMNS) for name, value in zip(header, fields)}
        if int(values["Part"]) != len(rows): raise EvidenceError("RunPARTs Part sequence is not contiguous")
        rows.append({"part": int(values["Part"]), "time_s": float(values["TimeStep [s]"]), "NpOut": int(values["NpOut"]), "NpOutPos": int(values["NpOutPos"]), "NpOutRho": int(values["NpOutRho"]), "NpOutMov": int(values["NpOutMov"]), "steps": int(values["Steps"])})
    if header is None: raise EvidenceError("RunPARTs.csv header is missing")
    after = _stat(path, "RunPARTs.csv post")
    if before != after: raise EvidenceError("RunPARTs.csv changed during read")
    timeline = summary.get("timeline", {}).get("time_s") if isinstance(summary.get("timeline"), dict) else None
    if not isinstance(timeline, list) or len(rows) != len(timeline): raise EvidenceError("RunPARTs saved timeline differs from typed summary")
    max_delta = max((abs(item["time_s"] - float(value)) for item, value in zip(rows, timeline)), default=0.0)
    if max_delta > 1e-9: raise EvidenceError(f"RunPARTs saved time differs from typed timeline: {max_delta}")
    totals = {name: sum(item[name] for item in rows) for name in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    return {"pre_stat": before, "post_stat": after, "sha256": digest.hexdigest(), "rows": len(rows), "footer_comment_count": footer, "max_saved_time_delta_s": max_delta, "totals": totals, "last": rows[-1] if rows else None}


def _audit_case(contract: dict[str, Any], proof: dict[str, Any], output_dir: Path, partvtkout: Path = PARTVTKOUT) -> dict[str, Any]:
    case_id = contract["physical_case_id"]
    proof_case = _proof_case(proof, case_id)
    summary_ref = _proof_ref(proof_case, ("summary", "typed_summary"))
    records_ref = _proof_ref(proof_case, ("records_stat_only", "records", "typed_records"))
    if summary_ref is None or records_ref is None: raise EvidenceError(f"{case_id} ROOT232 proof lacks summary/records edges")
    summary_path = _path(summary_ref["path"], f"{case_id} typed summary")
    summary, summary_evidence = _guarded_json(summary_path, f"{case_id} typed summary", expected_sha=summary_ref.get("sha256"), max_bytes=MAX_SMALL_BYTES)
    if summary.get("physical_case_id") != case_id or summary.get("family_id") != "F4": raise EvidenceError(f"{case_id} typed summary identity differs")
    records_path = _path(records_ref["path"], f"{case_id} typed records")
    header, record_rows, typed_evidence = _iter_records(records_path, records_ref.get("sha256"), summary, case_id)
    if not typed_evidence["first_missing"]: raise EvidenceError(f"{case_id} has no typed fluid target; empty target is not a pass")
    native_report_ref = contract["native_deferred"]["native_report"]
    native_report_path = _path(native_report_ref["path"], f"{case_id} native omission report")
    native_report, native_report_evidence = _guarded_json(native_report_path, f"{case_id} native omission report", expected_sha=native_report_ref.get("sha256"), max_bytes=MAX_SMALL_BYTES)
    if native_report.get("physical_case_id") not in (None, case_id) and native_report.get("case_id") not in (None, case_id): raise EvidenceError(f"{case_id} native report identity differs")
    # The inventory edge is a directory.  V2 used the default file check here,
    # so ROOT249 failed after consuming the typed records but before invoking
    # the official decoder.  Keep the directory/file distinction explicit.
    data_dir = _path(contract["native_deferred"]["data_dir"]["path"], f"{case_id} native data directory", directory=True)
    obi4_ref = contract["native_deferred"]["partout_obi4"]
    obi4_path = _path(obi4_ref["path"], f"{case_id} PartOut_000.obi4")
    obi4_pre = _stat(obi4_path, f"{case_id} PartOut_000.obi4 pre")
    obi4_sha_pre = _sha256_file(obi4_path)
    case_dir = output_dir / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    csv_path = case_dir / "PartOut.csv"
    resume_path = case_dir / "resume.csv"
    if csv_path.exists() or resume_path.exists(): raise EvidenceError(f"{case_id} decoder output already exists")
    tool_path = _path(partvtkout, f"{case_id} official PartVTKOut tool")
    tool_sha = PARTVTKOUT_SHA256 if tool_path == PARTVTKOUT.resolve() else _sha256_file(tool_path, max_bytes=MAX_SMALL_BYTES)
    command = [str(tool_path), "-dirdata", str(data_dir), "-savecsv", str(csv_path), "-saveresume", str(resume_path), "-createdirs:1", "-csvsep:1"]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, cwd=str(case_dir), timeout=MAX_PARTVTK_TIMEOUT)
    if completed.returncode != 0: raise EvidenceError(f"{case_id} official PartVTKOut failed: {completed.stderr[-1000:]}")
    if not csv_path.is_file() or not resume_path.is_file(): raise EvidenceError(f"{case_id} official PartVTKOut did not create CSV/resume")
    native_rows, partout_evidence = _partout_csv(csv_path)
    runparts_path = _path(contract["native_deferred"]["runparts_csv"]["path"], f"{case_id} RunPARTs.csv")
    runparts_evidence = _runparts(runparts_path, summary)
    obi4_post = _stat(obi4_path, f"{case_id} PartOut_000.obi4 post")
    obi4_sha_post = _sha256_file(obi4_path)
    if obi4_pre != obi4_post or obi4_sha_pre != obi4_sha_post: raise EvidenceError(f"{case_id} PartOut_000.obi4 changed during decoder")
    target = typed_evidence["first_missing"]
    zones = {key[0] for key in target}
    if len(zones) != 1 or next(iter(zones)) != 0: raise EvidenceError(f"{case_id} typed target zones cannot be inferred for PartOut.csv")
    native_by_key = {(0, row["idp"]): row for row in native_rows}
    missing_keys = set(target)
    if not missing_keys.issubset(native_by_key): raise EvidenceError(f"{case_id} official PartVTKOut lacks exact typed target identities")
    fluid_record_keys = {key for key, row in record_rows.items() if row.get("initial_role") == "fluid"}
    extra_fluid = set(native_by_key) & fluid_record_keys - missing_keys
    if extra_fluid: raise EvidenceError(f"{case_id} official PartVTKOut has fluid identities not marked first-missing: {sorted(extra_fluid)[:4]}")
    joined = []
    for key in sorted(missing_keys):
        typed = target[key]; native = native_by_key[key]
        joined.append({"zone": key[0], "idp": key[1], "initial_role": typed.get("initial_role"), "initial_mass_kg": typed.get("initial_mass_kg"), "first_disappeared_frame": typed.get("first_disappeared_frame"), "first_disappeared_time_s": typed.get("first_disappeared_time_s"), "first_disappeared_bracket_s": typed.get("first_disappeared_bracket_s"), "native_part_out": native["part_out"], "native_motive_code": native["motive_code"], "native_motive": native["motive"], "native_position_m": [native["Pos.x [m]"], native["Pos.y [m]"], native["Pos.z [m]"]], "native_density_kg_m3": native["Rhop [kg/m^3]"], "saved_bracket_semantics": "typed saved-frame first transition joined to RunPARTs saved times; continuous event time UNKNOWN", "native_exit_cause": "NUMERICAL_" + native["motive"].upper() if native["motive"] != "UNKNOWN_MOTIVE" else "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamical_impact": "UNKNOWN"})
    # ``first_missing`` is keyed by (Zone, Idp) tuples for the internal exact
    # join.  Convert that diagnostic map to JSON-safe rows before writing the
    # case report; leaking tuple keys makes a fully completed audit fail during
    # terminal receipt serialization.
    typed_report = dict(typed_evidence)
    typed_report["first_missing"] = [
        {"zone": key[0], "idp": key[1], "record": value}
        for key, value in sorted(typed_evidence["first_missing"].items())
    ]
    return {"schema": REPORT_SCHEMA, "status": "COMPLETED_F4_NATIVE_TYPED_FIRST_MISSING_JOIN_NO_PHYSICAL_CREDIT_V4", "physical_case_id": case_id, "family_id": "F4", "typed": {"header": header, "summary": summary_evidence, "records": typed_report, "source_summary": summary_ref, "source_records": {**records_ref, "observed_sha256": typed_evidence["sha256"]}}, "native": {"prior_report": native_report_evidence, "official_tool": {"path": str(tool_path), "sha256": tool_sha, "command": command, "returncode": completed.returncode, "stdout_tail": completed.stdout[-2000:], "stderr_tail": completed.stderr[-2000:]}, "partout_obi4": {"pre_stat": obi4_pre, "post_stat": obi4_post, "pre_sha256": obi4_sha_pre, "post_sha256": obi4_sha_post, "stable": True}, "partout_csv": partout_evidence, "runparts": runparts_evidence, "rows": native_rows}, "exact_join": {"count": len(joined), "rows": joined, "identity_key": "(Zone, Idp)", "all_typed_targets_present": True, "no_empty_target_shortcut": True}, "claim_boundary": contract["claim_boundary"], "read_policy": {"root232_typed_jsonl_opened_after_reservation": True, "native_obi4_opened_by_official_partvtkout": True, "native_part_frames_opened": False, "solver_started": False, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}


def audit(args: argparse.Namespace) -> dict[str, Any]:
    official_tool_ref = _validate_official_partvtkout()
    if args.partvtkout is not None and Path(args.partvtkout).expanduser().resolve() != PARTVTKOUT.resolve():
        raise EvidenceError("ROOT249 V4 refuses an unbound PartVTKOut replacement")
    manifest_path = _path(args.manifest, "ROOT249 V4 manifest")
    manifest = _read_json(manifest_path, "ROOT249 V4 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA: raise EvidenceError("ROOT249 V4 manifest schema differs")
    if not manifest.get("launch_allowed") and not args.allow_pending_proof: raise EvidenceError("ROOT232 terminal proof is required before audit")
    proof_path = _path(args.root232_proof, "ROOT232 terminal proof")
    proof = _read_json(proof_path, "ROOT232 terminal proof")
    partvtkout = _path(args.partvtkout if args.partvtkout is not None else PARTVTKOUT, "official PartVTKOut tool")
    if str(partvtkout) != official_tool_ref["path"]:
        raise EvidenceError("ROOT249 V4 PartVTKOut path is outside the ORIGINAL vendor binding")
    contract_entries = manifest.get("contracts")
    if not isinstance(contract_entries, list) or not contract_entries: raise EvidenceError("ROOT249 V4 has no selected contracts")
    output_path = Path(args.output).expanduser().resolve()
    if output_path.exists(): raise EvidenceError(f"refusing to overwrite ROOT249 output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in contract_entries:
        case_id = entry.get("physical_case_id")
        try:
            contract_path = _path(entry.get("path"), f"{case_id} ROOT249 contract")
            contract = _read_json(contract_path, f"{case_id} ROOT249 contract")
            result = _audit_case(contract, proof, output_path.parent, partvtkout)
            case_output = output_path.parent / "cases" / f"{case_id}.json"
            _atomic(case_output, result, limit=MAX_CASE_OUTPUT_BYTES)
            results.append({"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_output), "exact_join_count": result["exact_join"]["count"]})
        except (EvidenceError, OSError, subprocess.SubprocessError, ValueError) as exc:
            results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "saved_mask_credit": False})
    failed = [item for item in results if item["status"] != "COMPLETED"]
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_ALL_CASES", "batch_id": manifest.get("batch_id"), "family_id": "F4", "case_results": results, "counts": {"requested": len(results), "completed": len(results) - len(failed), "failed": len(failed)}, "excluded_root232_cases": manifest.get("excluded_root232_cases", []), "claim_boundary": manifest.get("claim_boundary"), "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "source_read_cost": {"sequential_case_execution": True, "root232_h5_content_read": False, "native_obi4_read": True, "solver_started": False}}
    _atomic(output_path, report)
    return {"status": report["status"], "output": str(output_path), "completed": report["counts"]["completed"], "failed": report["counts"]["failed"]}


def fixture(args: argparse.Namespace) -> dict[str, Any]:
    """Run only CSV/RunPARTs parser checks on explicit synthetic files."""
    manifest = _read_json(_path(args.manifest, "fixture manifest"), "fixture manifest")
    if manifest.get("fixture") is not True: raise EvidenceError("fixture mode requires fixture=true")
    rows, csv_evidence = _partout_csv(_path(manifest["partout"], "fixture PartOut"))
    runparts = _runparts(_path(manifest["runparts"], "fixture RunPARTs"), {"timeline": {"time_s": [0.0]}})
    if not rows: raise EvidenceError("fixture target is empty")
    return {"status": "FIXTURE_PARSER_PASS_NO_SCIENTIFIC_CREDIT", "rows": rows, "partout": csv_evidence, "runparts": runparts, "scientific_credit": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--current", type=Path, default=CURRENT_DEFAULT)
    prep.add_argument("--inventory", type=Path, default=INVENTORY_DEFAULT)
    prep.add_argument("--overlay", type=Path, default=OVERLAY_DEFAULT)
    prep.add_argument("--historical", type=Path, default=HISTORICAL_DEFAULT)
    prep.add_argument("--root232-manifest", type=Path, default=ROOT232_MANIFEST_DEFAULT)
    prep.add_argument("--root232-proof", type=Path)
    prep.add_argument("--root235-proof", type=Path, default=ROOT235_DEFAULT_PROOF)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    prep.add_argument("--checkpoint", type=Path)
    prep.add_argument("--python", type=Path, default=DEFAULT_VENV)
    prep.add_argument("--runtime-config", type=Path, default=DEFAULT_CONFIG)
    run = sub.add_parser("audit")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--root232-proof", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--partvtkout", type=Path, help=argparse.SUPPRESS)
    run.add_argument("--allow-pending-proof", action="store_true", help=argparse.SUPPRESS)
    fix = sub.add_parser("fixture")
    fix.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare": result = prepare(args)
        elif args.action == "audit": result = audit(args)
        else: result = fixture(args)
    except (EvidenceError, OSError, ValueError) as exc:
        print(f"F4_UNLOCATED_NATIVE_EVIDENCE_V4_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
