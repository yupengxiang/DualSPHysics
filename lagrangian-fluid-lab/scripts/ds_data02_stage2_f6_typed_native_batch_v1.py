#!/usr/bin/env python3
"""Prepare and run a sequential, source-bound F6 typed/native join batch.

This module is the ROOT220 forward batch wrapper.  Preparation reads only the
CURRENT catalog, the completed ROOT203/210 proof objects, bounded JSON/XML
source records, and filesystem metadata for deferred payloads.  The guarded
worker processes one physical case at a time after the parent reservation.  It
streams that case's typed JSONL once and reads the already completed native
PartOut/RunPARTs CSV once; it never invokes PartVTKOut, opens BI4/H5, or runs
a solver.  A case result is written atomically before the next case starts and
a case failure is retained in the batch summary.

The historical native omission report is an evidence edge.  Its numerical
position/density category is kept separate from this saved-frame join, and
physical fate, continuous event time, legal flux, dynamics, and QI/QN/QE stay
UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
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

PROOF_PATHS = {
    "203": STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_203.json",
    "210": STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_210.json",
}
PROOF_SHA256 = {
    "203": "e146f0a378f56eccc59c5052aa27703322c40712192f38e9c5edce7acb87793c",
    "210": "4c02c64912a46523d94c71c1836f807508d10079051a74fb5ec65f739ec0f5e5",
}
ROOT216_CASE = "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0625_YAWM06_DP025"
ROOT219_CASE = "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0875_YAWP06_DP025"
ROOT220_CASES = (
    "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0875_YAWP06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S1125_YAWP12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S1375_YAWP18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S1625_YAWM18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S1125_YAWP12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S1375_YAWP18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S1625_YAWM18_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0375_YAWM12_DP025",
)
PARTVTKOUT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
PARTVTKOUT_SHA256 = "62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00"
CONFIG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
BASE_WORKER = SCRIPT.with_name("ds_data02_stage2_f6_dxyz_typed_native_crosscheck_v3.py")
MAX_SMALL_BYTES = 8 * 1024 * 1024
MAX_CASE_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_BATCH_OUTPUT_BYTES = 64 * 1024 * 1024
CONTRACT_SCHEMA = "ds02.stage2.f6-dxyz-typed-native-crosscheck-contract.v1"
BATCH_SCHEMA = "ds02.stage2.f6-typed-native-batch.v1"
REQUEST_SCHEMA = "ds02.request.v1"
FAMILY_ID = "F6"
SUMMARY_SCHEMA = "ds02.stage2.typed-lifecycle-sidecar.v4"


class BatchError(ValueError):
    """Raised when a batch source or identity contract is incomplete."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise BatchError(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(c not in "0123456789abcdef" for c in value):
        raise BatchError(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise BatchError(f"{label} has no path")
    result = Path(value).expanduser().resolve()
    if directory:
        if not result.is_dir():
            raise BatchError(f"{label} directory is missing: {result}")
    elif not result.is_file():
        raise BatchError(f"{label} file is missing: {result}")
    return result


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


def _hash_file(path: Path, label: str, *, max_bytes: int | None = None) -> str:
    path = _path(path, label)
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise BatchError(f"{label} exceeds bounded hash size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise BatchError(f"{label} exceeds bounded JSON read size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BatchError(f"{label} must be a JSON object")
    return value


def _small_ref(path: Path, label: str, expected: str) -> dict[str, Any]:
    stat = _stat(path, label)
    if stat["bytes"] > MAX_SMALL_BYTES:
        raise BatchError(f"{label} is above the small-input limit")
    actual = _hash_file(path, label, max_bytes=MAX_SMALL_BYTES)
    expected = _sha(expected, f"{label} expected SHA")
    if actual != expected:
        raise BatchError(f"{label} SHA differs: expected {expected}, got {actual}")
    return {**stat, "sha256": actual, "content_opened": True}


def _deferred_ref(path: Path, label: str, expected: str, expected_bytes: int, rows: int | None = None) -> dict[str, Any]:
    path = _path(path, label)
    stat = _stat(path, label)
    if stat["bytes"] != int(expected_bytes):
        raise BatchError(f"{label} byte count differs from its producer record")
    return {**stat, "sha256": _sha(expected, f"{label} expected SHA"), "rows": rows, "content_opened": False,
            "hash_checked": False, "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION_SINGLE_PASS"}


def _atomic(path: Path, value: dict[str, Any], *, max_bytes: int = MAX_BATCH_OUTPUT_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise BatchError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temp.stat().st_size > max_bytes:
            raise BatchError(f"output exceeds {max_bytes} bytes: {path}")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _load_base():
    """Load the consumed single-case parser without changing its source."""
    target = SCRIPT.with_name("ds_data02_stage2_f6_dxyz_typed_native_crosscheck_v3.py")
    spec = importlib.util.spec_from_file_location("_root220_crosscheck_base", target)
    if spec is None or spec.loader is None:
        raise BatchError(f"cannot load shared crosscheck source: {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json_proof(path: Path, expected_sha: str) -> dict[str, Any]:
    actual = _small_ref(path, "typed batch proof", expected_sha)
    return _read_json(path, "typed batch proof")


def _proof_case(proof: dict[str, Any], case_id: str) -> dict[str, Any]:
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise BatchError("typed batch proof schema differs")
    if proof.get("status") != "VERIFIED_ACTUAL_F6_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT":
        raise BatchError("typed batch proof status differs")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or counts.get("completed") != 7 or counts.get("failed") != 0:
        raise BatchError("typed batch proof is not a completed seven-case batch")
    matches = [r for r in proof.get("case_verifications", []) if isinstance(r, dict) and r.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise BatchError(f"typed batch proof case is not unique: {case_id}")
    case = matches[0]
    if case.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY" or case.get("family_id") != FAMILY_ID:
        raise BatchError(f"typed batch case is not a verified saved-mask diagnostic: {case_id}")
    if case.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
        raise BatchError(f"typed batch source closure is not proven: {case_id}")
    if case.get("native_cause_fate_legal_flux_dynamics") != "UNKNOWN":
        raise BatchError(f"typed batch physical boundary was widened: {case_id}")
    return case


def _load_inventory() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    inventory_ref = _small_ref(INVENTORY_PATH, "historical 118 source inventory", _inventory_sha())
    inventory = _read_json(INVENTORY_PATH, "historical 118 source inventory")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or len(rows) != 118:
        raise BatchError("historical inventory must contain exactly 118 rows")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("physical_case_id"), str):
            raise BatchError("historical inventory row is malformed")
        case_id = row["physical_case_id"]
        if case_id in by_id:
            raise BatchError(f"duplicate historical inventory case: {case_id}")
        by_id[case_id] = row
    return inventory, by_id


def _inventory_sha() -> str:
    # This is deliberately a checked-in producer digest, rather than a digest
    # guessed from the current directory.  It makes a changed source inventory
    # fail preparation instead of silently changing the case set.
    return "3d274db71d01f680b9997cc364298f9974a2cb09978acfb81f9a152622e75a00"


def _case_root_report(row: dict[str, Any]) -> tuple[Path, str, dict[str, Any]]:
    edge = row.get("original_omission_evidence", {}).get("report")
    if not isinstance(edge, dict):
        raise BatchError("case has no prior native omission report edge")
    path = _path(edge.get("path"), "native omission report")
    expected = _sha(edge.get("declared_sha256"), "native omission report SHA")
    ref = _small_ref(path, "native omission report", expected)
    return path, expected, _read_json(path, "native omission report")


def _scan_edges(case_id: str, current_index: int) -> tuple[Path, Path]:
    root = DATA / "families/F6/STAGE2_CURRENT336_SCIENCE" / f"scan-F6-{current_index}-001"
    scan = root / "scientific-scan.json"
    receipt = root / "execution-receipt.json"
    if not scan.is_file() or not receipt.is_file():
        raise BatchError(f"scientific scan/receipt is missing for {case_id}")
    return scan, receipt


def _validate_scan_receipt(receipt: dict[str, Any], receipt_path: Path, case_id: str, scan_path: Path, current_path: Path, trajectory_path: Path) -> None:
    if receipt.get("schema") != "ds02.execution-receipt.v1" or str(receipt.get("status", "")).lower() != "completed" or receipt.get("returncode") != 0:
        raise BatchError(f"scan receipt is not a completed successful receipt: {case_id}")
    request = receipt.get("request")
    if not isinstance(request, dict) or request.get("family_id") != FAMILY_ID or request.get("case_id") != "STAGE2_CURRENT336_SCIENCE":
        raise BatchError(f"scan receipt request identity differs: {case_id}")
    command = request.get("command")
    if not isinstance(command, list) or case_id not in [str(v) for v in command]:
        raise BatchError(f"scan receipt command does not bind case: {case_id}")
    if not _same_path(receipt.get("output_root"), scan_path.parent):
        raise BatchError(f"scan receipt output root differs: {case_id}")
    hashes = request.get("input_sha256")
    if not isinstance(hashes, dict):
        raise BatchError(f"scan receipt input hashes are missing: {case_id}")
    if hashes.get(str(current_path.resolve())) != CURRENT_SHA256:
        raise BatchError(f"scan receipt does not bind CURRENT: {case_id}")
    trajectory_sha = None
    current = _read_json(current_path, "CURRENT336")
    for row in current.get("cases", []):
        if isinstance(row, dict) and row.get("physical_case_id") == case_id:
            trajectory_sha = row.get("trajectory", {}).get("producer_declared_sha256")
            break
    if not isinstance(trajectory_sha, str) or hashes.get(str(trajectory_path.resolve())) != trajectory_sha:
        raise BatchError(f"scan receipt does not bind CURRENT trajectory: {case_id}")


def _same_path(value: Any, path: Path) -> bool:
    try:
        return Path(value).expanduser().resolve() == path.expanduser().resolve()
    except (TypeError, ValueError, OSError):
        return False


def _validate_completed_receipt(path: Path, expected_sha: str, label: str, case_id: str) -> dict[str, Any]:
    ref = _small_ref(path, label, expected_sha)
    receipt = _read_json(path, label)
    status = str(receipt.get("status", "")).lower()
    if receipt.get("returncode") != 0 or status not in {"completed", "success", "succeeded"}:
        raise BatchError(f"{label} is not a successful completed receipt for {case_id}")
    return receipt


def _case_scope_row(scope: dict[str, Any], case_id: str) -> dict[str, Any]:
    matches = [r for r in scope.get("case_rows", []) if isinstance(r, dict) and r.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise BatchError(f"scope case is not unique: {case_id}")
    row = matches[0]
    if row.get("family_id") != FAMILY_ID or row.get("classification") != "CAUSE_NOT_LOCATED_AFTER_COMPLETED_SCAN":
        raise BatchError(f"ROOT220 only accepts an unlocated F6 case: {case_id}")
    if row.get("physical_fate_legal_flux_dynamics") != "UNKNOWN" or any(row.get(key) != "UNKNOWN" for key in ("QI", "QN", "QE")):
        raise BatchError(f"scope qualification boundary is not unknown: {case_id}")
    return row


def _target_keys(native: dict[str, Any], case_id: str) -> set[tuple[int, int]]:
    """Return an exact non-empty per-case target identity set.

    This small helper is deliberately separate from the global batch planner:
    Idp values may repeat in different physical cases, but a duplicate
    ``(Zone, Idp)`` inside one report is never admissible.
    """
    rows = native.get("excluded_particles")
    if not isinstance(rows, list) or not rows:
        raise BatchError(f"native report has an empty target set: {case_id}")
    result: set[tuple[int, int]] = set()
    for index, item in enumerate(rows):
        if not isinstance(item, dict) or not isinstance(item.get("zone"), int) or not isinstance(item.get("idp"), int):
            raise BatchError(f"native target row {index} is malformed: {case_id}")
        key = (int(item["zone"]), int(item["idp"]))
        if key in result:
            raise BatchError(f"native target identity is duplicated: {case_id} {key}")
        result.add(key)
    return result


def _validate_fluid_target_count(summary: dict[str, Any], target_count: int, case_id: str) -> None:
    """Reject aggregate-only or empty evidence before any deferred read."""
    fluid = summary.get("role_ledgers", {}).get("fluid", {})
    if int(fluid.get("initial_count", -1)) != 327680 or int(fluid.get("first_disappearance_count", -1)) != target_count or target_count <= 0:
        raise BatchError(f"typed summary/native target count is not a non-empty exact per-ID contract: {case_id}")
    final_counts = fluid.get("active_count_by_frame")
    if not isinstance(final_counts, list) or not final_counts or int(final_counts[-1]) > 327680 - target_count:
        raise BatchError(f"typed summary final active count cannot cover target IDs: {case_id}")


def _base_contract(case_id: str, proof_path: Path, proof_sha: str, proof: dict[str, Any], row: dict[str, Any], scope: dict[str, Any], native_path: Path, native_sha: str, native: dict[str, Any], inventory_path: Path) -> dict[str, Any]:
    """Build one contract using the consumed single-case validators."""
    base = _load_base()
    base.CASE_ID = case_id
    base.FAMILY_ID = FAMILY_ID
    base.CURRENT_SHA256 = CURRENT_SHA256
    base.SCRIPT = SCRIPT
    base.VENV = VENV

    current_ref = _small_ref(CURRENT_PATH, "CURRENT336", CURRENT_SHA256)
    current = _read_json(CURRENT_PATH, "CURRENT336")
    current_row = base._current_case(current, case_id)
    proof_case = _proof_case(proof, case_id)
    summary_path = _path(proof_case["summary"], "typed summary")
    summary_sha = _sha(proof_case.get("summary_sha256"), "typed summary SHA")
    summary_ref = _small_ref(summary_path, "typed summary", summary_sha)
    summary = _read_json(summary_path, "typed summary")
    trajectory, records_ref = base._validate_summary(summary, summary_path, current_row, case_id, CURRENT_SHA256)
    target_count = len(native.get("excluded_particles", []))
    _validate_fluid_target_count(summary, target_count, case_id)
    proof_case = base._validate_proof(proof, proof_path, summary_path, summary_sha, records_ref, case_id, CURRENT_SHA256)
    native_ids = base._validate_native_report(native, current_row, case_id)

    scan_path, scan_receipt_path = _scan_edges(case_id, int(row["current336_index"]))
    scan_ref = _small_ref(scan_path, "scientific scan", _sha_from_scan(scan_path))
    scan_receipt_ref = _small_ref(scan_receipt_path, "scientific scan receipt", _hash_file(scan_receipt_path, "scientific scan receipt", max_bytes=MAX_SMALL_BYTES))
    scan = _read_json(scan_path, "scientific scan")
    base._validate_scan(scan, current_row, native_ids)
    _validate_scan_receipt(_read_json(scan_receipt_path, "scientific scan receipt"), scan_receipt_path, case_id, scan_path, CURRENT_PATH, Path(str(current_row["trajectory"]["path"])))

    artifacts = row["source_artifacts"]["artifacts"]
    conversion_path = _path(artifacts["conversion_report"]["path"], "conversion report")
    conversion_ref = _small_ref(conversion_path, "conversion report", artifacts["conversion_report"]["declared_sha256"])
    conversion = _read_json(conversion_path, "conversion report")
    source = native.get("source_provenance")
    if not isinstance(source, dict):
        raise BatchError(f"native source provenance is missing: {case_id}")
    data_root = _path(source.get("data_root"), "native solver output data root", directory=True)
    xml_path = _path(artifacts["generated_xml"]["path"], "generated XML")
    xml_ref = _small_ref(xml_path, "generated XML", artifacts["generated_xml"]["declared_sha256"])
    base._validate_conversion(conversion, current_row, xml_path, xml_ref["sha256"], data_root)

    gencase_path = _path(artifacts["gencase_receipt"]["path"], "GenCase receipt")
    gencase_ref = _small_ref(gencase_path, "GenCase receipt", artifacts["gencase_receipt"]["declared_sha256"])
    solver_path = _path(source["solver_receipt"]["path"], "solver receipt")
    solver_ref = _small_ref(solver_path, "solver receipt", source["solver_receipt"]["sha256"])
    decoder_edge = native.get("native_decode", {}).get("receipt", {})
    decoder_path = _path(decoder_edge.get("path"), "native decoder receipt")
    decoder_ref = _small_ref(decoder_path, "native decoder receipt", decoder_edge.get("sha256"))
    _validate_completed_receipt(gencase_path, gencase_ref["sha256"], "GenCase receipt", case_id)
    _validate_completed_receipt(solver_path, solver_ref["sha256"], "solver receipt", case_id)
    _validate_completed_receipt(decoder_path, decoder_ref["sha256"], "native decoder receipt", case_id)

    scope_ref = _small_ref(SCOPE_PATH, "native scope V2", SCOPE_SHA256)
    scope_info = base._validate_scope(scope, SCOPE_PATH, case_id, native_path, native_sha)
    scope_row = _case_scope_row(scope, case_id)
    manifest_path = _path(artifacts["manifest"]["path"], "CURRENT case manifest")
    manifest_ref = _small_ref(manifest_path, "CURRENT case manifest", artifacts["manifest"]["declared_sha256"])
    manifest = _read_json(manifest_path, "CURRENT case manifest")
    if manifest.get("physical_case_id") != case_id or manifest.get("family_id") != FAMILY_ID:
        raise BatchError(f"CURRENT case manifest identity differs: {case_id}")
    owner_path = _path(artifacts["owner_metadata"]["path"], "owner metadata")
    owner_ref = _small_ref(owner_path, "owner metadata", artifacts["owner_metadata"]["declared_sha256"])

    h5_path = _path(current_row["trajectory"]["path"], "CURRENT trajectory")
    h5_stat = _stat(h5_path, "CURRENT trajectory")
    if h5_stat["bytes"] != int(current_row["trajectory"]["bytes"]):
        raise BatchError(f"CURRENT trajectory stat differs: {case_id}")
    native_decode = native["native_decode"]
    partout_edge = native_decode.get("partout")
    runparts_edge = native_decode.get("runparts")
    partout_path = _path(partout_edge.get("path"), "native PartOut.csv")
    runparts_path = _path(runparts_edge.get("path"), "native RunPARTs.csv")
    partout_ref = base._deferred_csv_ref(partout_path, "native PartOut.csv", partout_edge.get("sha256"), int(partout_edge.get("bytes", -1)), expected_rows=target_count)
    runparts_ref = base._deferred_csv_ref(runparts_path, "native RunPARTs.csv", runparts_edge.get("sha256"), int(runparts_edge.get("bytes", -1)), expected_rows=int(native_decode.get("runparts_row_count", -1)))
    records_ref = {**records_ref, "rows": int(summary["records"]["rows"])}

    _target_keys(native, case_id)
    target_ids = [dict(item) for item in sorted(native.get("excluded_particles", []), key=lambda value: (int(value["zone"]), int(value["idp"]))) ]
    source_artifact_refs = {}
    for role in ("conversion_report", "gencase_receipt", "generated_xml", "manifest", "owner_metadata"):
        source_artifact_refs[role] = {
            "path": str(Path(artifacts[role]["path"]).expanduser().resolve()),
            "sha256": artifacts[role]["declared_sha256"],
            "bytes": int(artifacts[role]["stat"]["bytes"]),
            "content_opened_prepare": True,
        }
    source_artifact_refs["raw_solver_root_stat_only"] = {"path": artifacts["raw_solver_root"]["path"], "stat": artifacts["raw_solver_root"]["stat"], "content_opened_prepare": False}
    tool_stat = _stat(PARTVTKOUT, "official PartVTKOut binary")
    data_stat = _stat(data_root, "native data root", directory=True)
    base_worker_stat = _stat(BASE_WORKER, "shared single-case crosscheck worker")
    base_worker_sha = _hash_file(BASE_WORKER, "shared single-case crosscheck worker", max_bytes=MAX_SMALL_BYTES)

    contract = {
        "schema": CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "physical_case_id": case_id,
        "family_id": FAMILY_ID,
        "expected_current_sha256": CURRENT_SHA256,
        "batch_namespace": "ROOT220",
        "inputs": {
            "current336": current_ref,
            "root203_proof": {**_small_ref(proof_path, "typed proof", proof_sha), "proof_batch": "203" if proof_path == PROOF_PATHS["203"] else "210"},
            "root203_summary": summary_ref,
            "native_omission_report": _small_ref(native_path, "native omission report", native_sha),
            "scientific_scan": scan_ref,
            "scientific_scan_receipt": scan_receipt_ref,
            "conversion_report": conversion_ref,
            "generated_xml": xml_ref,
            "gencase_receipt": gencase_ref,
            "solver_receipt": solver_ref,
            "native_decoder_receipt": decoder_ref,
            "scope_v2": scope_ref,
            "historical_inventory": _small_ref(inventory_path, "historical source inventory", _inventory_sha()),
            "case_manifest": manifest_ref,
            "owner_metadata": owner_ref,
        },
        "deferred_inputs": {"typed_records": records_ref, "partout_csv": partout_ref, "runparts_csv": runparts_ref},
        "source_edges": {
            "current_row": {"current336_index": int(row["current336_index"]), "frames": int(current_row["frames"]), "particles": int(current_row["particles"]), "trajectory_path": current_row["trajectory"]["path"], "trajectory_sha256": current_row["trajectory"]["producer_declared_sha256"], "trajectory_stat": h5_stat},
            "typed_proof": {"proof_path": str(proof_path), "proof_sha256": proof_sha, "status": proof_case["status"], "summary_path": str(summary_path), "summary_sha256": summary_ref["sha256"], "records_stat_only": records_ref},
            "historical_scope_v2": {"classification": scope_row["classification"], "report_category_observed": scope_row.get("report_category_observed"), "credit_reason": scope_row.get("credit_reason"), "typed_native_first_missing_join_scope": scope_row.get("typed_native_first_missing_join_scope")},
            "native_report": {"path": str(native_path), "sha256": native_sha, "identity_key": "(Zone,Idp)", "excluded_ids": [[int(item["zone"]), int(item["idp"])] for item in target_ids], "native_exit_cause_counts": scope_row.get("report_native_exit_cause_counts"), "historical_cause_credit": "SOURCE_BOUND_PRIOR_REPORT_ONLY", "physical_fate": native.get("physical_fate")},
            "scientific_scan": {"path": str(scan_path), "sha256": scan_ref["sha256"], "receipt": {"path": str(scan_receipt_path), "sha256": scan_receipt_ref["sha256"]}, "missing_id_count": target_count, "content_opened_prepare": True},
            "native_decode": {"receipt": decoder_ref, "tool": native_decode.get("tool"), "tool_binary": {"path": str(PARTVTKOUT), "sha256": PARTVTKOUT_SHA256, "stat": tool_stat, "content_opened_prepare": False}, "data_root": str(data_root), "data_root_stat": data_stat, "partout_csv": partout_ref, "runparts_csv": runparts_ref, "content_opened_prepare": False},
            "crosscheck_worker_dependency": {"path": str(BASE_WORKER), "sha256": base_worker_sha, "stat": base_worker_stat, "content_opened_prepare": True, "role": "shared_single_case_parser_loaded_by_batch_worker"},
            "source_artifacts": source_artifact_refs,
            "roles": {"fluid_partition": {"count": 327680, "type": 3, "mkfluid": 0, "source": "conversion report typed_identity block"}, "target_identity": "(Zone,Idp)", "target_role": "fluid", "owner_and_control_semantics": "metadata edge only; physical owner/contact remains UNKNOWN"},
        },
        "target_ids": target_ids,
        "comparison": {"identity_key": "(Zone,Idp)", "typed_key_source": "ROOT203/210 V4 JSONL after parent reservation", "native_key_source": "completed source-bound PartOut.csv/omission report after parent reservation", "native_zone_scope": "Zone=0 is source-bound; PartOut.csv has no Zone column", "typed_first_missing_semantics": "first saved frame valid-mask active-to-inactive", "native_first_missing_semantics": "saved PartVTKOut/RunPARTs bracket", "saved_frame_or_bracket_match": "diagnostic bounded join only", "continuous_event_time": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"},
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 900, "memory_max_bytes": 1024 * 1024 * 1024, "case_output_cap_bytes": MAX_CASE_OUTPUT_BYTES, "batch_output_cap_bytes": MAX_BATCH_OUTPUT_BYTES, "typed_records_passes_minimum": 1, "partout_passes_minimum": 1, "runparts_passes_minimum": 1, "scientific_scan_passes_minimum": 1, "typed_records_bytes": int(records_ref["bytes"]), "partout_bytes": int(partout_ref["bytes"]), "runparts_bytes": int(runparts_ref["bytes"]), "scientific_scan_bytes": int(scan_ref["bytes"]), "estimated_deferred_read_bytes": int(records_ref["bytes"] + partout_ref["bytes"] + runparts_ref["bytes"] + scan_ref["bytes"]), "h5_content_read": False, "native_bi4_read": False, "solver_launch": False},
        "claim_boundary": {"historical_native_cause": "SOURCE_BOUND_HISTORICAL_REPORT_ONLY", "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "native_category_counts": "not an ID-level substitute", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "launch_allowed": False,
        "launch_owner": "root",
        "request_note": "Parent creates a fresh guarded attempt. Preparation opens only bounded metadata. Typed JSONL, PartOut.csv and RunPARTs.csv are deferred and read once per case after reservation; H5/BI4/solver are never opened by this worker.",
    }
    return contract


def _sha_from_scan(path: Path) -> str:
    # The scan is a small JSON producer artifact; preparation may hash it.
    return _hash_file(path, "scientific scan", max_bytes=MAX_SMALL_BYTES)


def _build_case_contracts(case_ids: Iterable[str]) -> list[dict[str, Any]]:
    case_ids = list(case_ids)
    if len(case_ids) == 0 or len(case_ids) > 8:
        raise BatchError("ROOT220 batch must contain one through eight cases")
    if len(set(case_ids)) != len(case_ids):
        raise BatchError("ROOT220 case IDs must be unique")
    forbidden = {ROOT216_CASE, ROOT219_CASE}
    if forbidden.intersection(case_ids):
        raise BatchError("ROOT220 overlaps an already consumed/pending single-case namespace")
    if set(case_ids) != set(ROOT220_CASES):
        raise BatchError("ROOT220 first batch must use the exact eight non-overlapping F6 cases")
    _, inventory_rows = _load_inventory()
    current = _read_json(CURRENT_PATH, "CURRENT336")
    scope = _read_json(SCOPE_PATH, "native scope V2")
    proof_objects: dict[str, tuple[Path, str, dict[str, Any]]] = {}
    for name, path in PROOF_PATHS.items():
        proof_objects[name] = (path, PROOF_SHA256[name], _load_json_proof(path, PROOF_SHA256[name]))
    contracts: list[dict[str, Any]] = []
    seen_current: set[str] = set()
    # Idp values are only unique inside a physical case.  The same fluid Idp
    # may legitimately occur in two different CURRENT runs, so the dedupe key
    # must include case_id (a cross-case Idp collision is not an identity
    # collision).
    seen_targets: set[tuple[str, int, int]] = set()
    for case_id in case_ids:
        row = inventory_rows.get(case_id)
        if not isinstance(row, dict) or row.get("family_id") != FAMILY_ID or row.get("current_identity_match") is False:
            raise BatchError(f"case is not an exact F6 CURRENT inventory row: {case_id}")
        if case_id in seen_current:
            raise BatchError(f"duplicate CURRENT physical case: {case_id}")
        current_matches = [r for r in current.get("cases", []) if isinstance(r, dict) and r.get("physical_case_id") == case_id]
        if len(current_matches) != 1:
            raise BatchError(f"CURRENT case is absent or ambiguous: {case_id}")
        scope_row = _case_scope_row(scope, case_id)
        report_path, report_sha, native = _case_root_report(row)
        target_set = _target_keys(native, case_id)
        scoped_targets = {(case_id, zone, idp) for zone, idp in target_set}
        if seen_targets.intersection(scoped_targets):
            raise BatchError(f"target identity is duplicated inside physical case: {case_id}")
        seen_targets.update(scoped_targets)
        proof_name = "203" if case_id.startswith("F6_STAGE1_ANGULAR_RELEASE_DXYZ_") else "210"
        proof_path, proof_sha, proof = proof_objects[proof_name]
        proof_case = _proof_case(proof, case_id)
        # The proof row's source summary is the authoritative typed producer
        # edge.  It is not accepted merely because a same-named file exists.
        contract = _base_contract(case_id, proof_path, proof_sha, proof, row, scope, report_path, report_sha, native, INVENTORY_PATH)
        contract["batch_case_index"] = len(contracts)
        contract["batch_case_source_classification"] = scope_row["classification"]
        contracts.append(contract)
        seen_current.add(case_id)
    if len(seen_current) != 8:
        raise BatchError("ROOT220 exact case set was not closed")
    return contracts


def _request_from_manifest(manifest_path: Path, request_path: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path, "ROOT220 batch manifest")
    contracts = manifest.get("case_contracts")
    if not isinstance(contracts, list) or len(contracts) != 8:
        raise BatchError("ROOT220 manifest must contain eight case contracts")
    input_paths: list[Path] = [SCRIPT, BASE_WORKER, manifest_path, CURRENT_PATH, SCOPE_PATH, INVENTORY_PATH, CONFIG]
    runtime_dir = PRIMARY / "lagrangian-fluid-lab/scripts"
    for name in ("ds_data02_runtime_v8.py", "ds_data02_stage2_dispatch_v8.py", "ds_data02_strict_dispatch_v8.py"):
        input_paths.append(runtime_dir / name)
    for item in contracts:
        contract_path = _path(item["contract_path"], "case contract")
        input_paths.append(contract_path)
        contract = _read_json(contract_path, "case contract")
        for ref in contract.get("inputs", {}).values():
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                path = Path(ref["path"]).expanduser().resolve()
                if path.is_file() and path.stat().st_size <= MAX_SMALL_BYTES:
                    input_paths.append(path)
        input_paths.append(Path(contract["source_edges"]["native_decode"]["tool_binary"]["path"]))
    unique = sorted({p.expanduser().resolve() for p in input_paths if p.is_file() and p.suffix.lower() not in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}})
    input_sha = {}
    deferred: list[str] = []
    for path in unique:
        if path == PARTVTKOUT:
            deferred.append(str(path))
            continue
        if path.stat().st_size > MAX_SMALL_BYTES:
            raise BatchError(f"request static input exceeds small bound: {path}")
        input_sha[str(path)] = _hash_file(path, "ROOT220 request input", max_bytes=MAX_SMALL_BYTES)
    for item in contracts:
        c = _read_json(_path(item["contract_path"], "case contract"), "case contract")
        for role in ("typed_records", "partout_csv", "runparts_csv"):
            deferred.append(str(Path(c["deferred_inputs"][role]["path"]).expanduser().resolve()))
        # H5 is declared source context, not a worker input.  It is never
        # content-read by this batch and is therefore intentionally omitted
        # from deferred_input_files.
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "task_kind": "audit",
        "family_id": FAMILY_ID,
        "batch_id": "ROOT220",
        "worker_version": "f6-typed-native-batch.v1",
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path.expanduser().absolute()), "--output", "{attempt_root}/f6-typed-native-batch-summary.json"],
        "input_files": [str(path) for path in unique if path != PARTVTKOUT],
        "input_sha256": input_sha,
        "deferred_input_files": sorted(set(deferred)),
        "deferred_input_policy": "ONE_SEQUENTIAL_PASS_PER_CASE_AFTER_PARENT_RESERVATION",
        "source_payload_declarations": [
            {"role": "current_trajectory_h5", "policy": "STAT_ONLY_NO_CONTENT_READ", "cases": [c["physical_case_id"] for c in [ _read_json(_path(x["contract_path"], "case contract"), "case contract") for x in contracts ]]},
            {"role": "native_bi4_solver_payload", "policy": "NO_READ; reuse completed PartOut.csv only"},
        ],
        "resource_policy": manifest["resource_policy"],
        "claim_boundary": manifest["claim_boundary"],
        "launch_allowed": False,
        "launch_owner": "root",
        "source_closure": {"manifest": str(manifest_path.resolve()), "manifest_sha256": _hash_file(manifest_path, "ROOT220 manifest", max_bytes=MAX_BATCH_OUTPUT_BYTES), "partvtkout_sha256_declared": PARTVTKOUT_SHA256, "partvtkout_content_opened_prepare": False},
    }
    _atomic(request_path, request)
    return request


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    case_ids = list(ROOT220_CASES) if args.case_id is None else list(args.case_id)
    contracts = _build_case_contracts(case_ids)
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise BatchError(f"ROOT220 output root already exists: {output_root}")
    contract_dir = output_root / "case-contracts"
    contract_paths: list[Path] = []
    for contract in contracts:
        safe = contract["physical_case_id"].replace("/", "_")
        path = contract_dir / f"{safe}.json"
        _atomic(path, contract, max_bytes=MAX_CASE_OUTPUT_BYTES)
        contract_paths.append(path)
    total_records = sum(int(c["resource_policy"]["typed_records_bytes"]) for c in contracts)
    total_deferred = sum(int(c["resource_policy"]["estimated_deferred_read_bytes"]) for c in contracts)
    manifest = {
        "schema": BATCH_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "batch_id": "ROOT220",
        "family_id": FAMILY_ID,
        "case_ids": [c["physical_case_id"] for c in contracts],
        "case_contracts": [{"physical_case_id": c["physical_case_id"], "contract_path": str(p), "contract_sha256": _hash_file(p, "case contract", max_bytes=MAX_CASE_OUTPUT_BYTES), "target_identity_count": len(c["target_ids"]), "source_classification": c["batch_case_source_classification"]} for c, p in zip(contracts, contract_paths)],
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "case_count": len(contracts), "max_cases_per_batch": 8, "max_deferred_source_bytes": 20 * 1024 * 1024 * 1024, "typed_records_total_bytes": total_records, "estimated_deferred_read_bytes": total_deferred, "one_sequential_case_at_a_time": True, "case_output_cap_bytes": MAX_CASE_OUTPUT_BYTES, "batch_output_cap_bytes": MAX_BATCH_OUTPUT_BYTES, "h5_content_read": False, "native_bi4_read": False, "solver_launch": False},
        "claim_boundary": {"historical_native_category": "per-case source-bound prior report only", "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY_AFTER_GUARDED_RUN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "target_identity_is_not_physical_case": True},
        "overlap_exclusions": {"ROOT216": ROOT216_CASE, "ROOT219": ROOT219_CASE, "original_bound_case_count": 53, "pending_or_consumed_single_case_namespaces": ["ROOT216", "ROOT219"]},
        "source_policy": "small JSON/XML/source receipts are checked at prepare; typed JSONL and CSV content are deferred until parent reservation; no H5/BI4/solver read",
        "launch_allowed": False,
    }
    manifest_path = output_root / "f6-typed-native-batch-v1-manifest.json"
    _atomic(manifest_path, manifest)
    request_path = Path(args.request_output).expanduser().resolve() if args.request_output else None
    result = {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _hash_file(manifest_path, "ROOT220 manifest", max_bytes=MAX_BATCH_OUTPUT_BYTES), "case_contracts": [str(p) for p in contract_paths], "case_count": len(contracts), "estimated_deferred_read_bytes": total_deferred, "launch_allowed": False}
    if request_path is not None:
        req = _request_from_manifest(manifest_path, request_path)
        result.update({"request": str(request_path), "request_sha256": _hash_file(request_path, "ROOT220 request", max_bytes=MAX_BATCH_OUTPUT_BYTES)})
    if args.checkpoint:
        checkpoint = Path(args.checkpoint).expanduser().resolve()
        _atomic(checkpoint, {"schema": "ds02.stage2.f6-typed-native-batch-root220.v1", "status": "SOURCE_PREPARED_NO_LAUNCH", "batch_id": "ROOT220", "manifest": str(manifest_path), "manifest_sha256": result["manifest_sha256"], "request": str(request_path) if request_path else None, "request_sha256": result.get("request_sha256"), "case_ids": manifest["case_ids"], "target_identity_count": sum(int(x["target_identity_count"]) for x in manifest["case_contracts"]), "estimated_deferred_read_bytes": total_deferred, "physical_case_count": len(contracts), "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "h5_content_read": False, "native_bi4_read": False, "solver_launch": False})
        result["checkpoint"] = str(checkpoint)
    return result


def _configure_base(base: Any, contract: dict[str, Any]) -> None:
    base.CASE_ID = contract["physical_case_id"]
    base.FAMILY_ID = contract["family_id"]
    base.CURRENT_SHA256 = contract["expected_current_sha256"]
    base.SCRIPT = SCRIPT
    base.VENV = VENV


def _generic_loader(base: Any, contract_path: Path):
    """A parameterized equivalent of the consumed loader without its old count assumption."""
    contract = _read_json(contract_path, "F6 case contract")
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("status") != "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED":
        raise BatchError("case contract is not guarded-ready")
    inputs = contract.get("inputs")
    if not isinstance(inputs, dict):
        raise BatchError("case contract inputs are missing")
    checked: dict[str, tuple[Path, dict[str, Any]]] = {}
    for role, item in inputs.items():
        if role in {"partvt_out_binary"}:
            continue
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise BatchError(f"case input role is malformed: {role}")
        path = _path(item["path"], role)
        # Extra role files are small source references.  No deferred suffix is
        # accepted in the static input map.
        ref = _small_ref(path, role, item.get("sha256"))
        if int(item.get("bytes", -1)) != ref["bytes"]:
            raise BatchError(f"case input stat differs: {role}")
        checked[role] = (path, ref)
    dependency = contract.get("source_edges", {}).get("crosscheck_worker_dependency")
    if not isinstance(dependency, dict):
        raise BatchError("shared single-case parser dependency is not bound")
    dependency_path = _path(dependency.get("path"), "shared single-case parser dependency")
    dependency_ref = _small_ref(dependency_path, "shared single-case parser dependency", dependency.get("sha256"))
    if dependency_ref["bytes"] != int(dependency.get("stat", {}).get("bytes", -1)):
        raise BatchError("shared single-case parser dependency stat differs")
    current_path, current_ref = checked["current336"]
    current = _read_json(current_path, "CURRENT336")
    if current_ref["sha256"] != contract.get("expected_current_sha256"):
        raise BatchError("case CURRENT SHA differs")
    case_id = contract["physical_case_id"]
    current_row = base._current_case(current, case_id)
    summary_path, summary_ref = checked["root203_summary"]
    summary = _read_json(summary_path, "typed summary")
    trajectory, records_ref = base._validate_summary(summary, summary_path, current_row, case_id, current_ref["sha256"])
    native_path, native_ref = checked["native_omission_report"]
    native = _read_json(native_path, "native omission report")
    native_ids = base._validate_native_report(native, current_row, case_id)
    _validate_fluid_target_count(summary, len(native_ids["excluded"]), case_id)
    proof_path, proof_ref = checked["root203_proof"]
    proof = _read_json(proof_path, "typed batch proof")
    base._validate_proof(proof, proof_path, summary_path, summary_ref["sha256"], records_ref, case_id, current_ref["sha256"])
    scan_path, scan_ref = checked["scientific_scan"]
    scan = _read_json(scan_path, "scientific scan")
    base._validate_scan(scan, current_row, native_ids)
    conversion_path, conversion_ref = checked["conversion_report"]
    conversion = _read_json(conversion_path, "conversion report")
    data_root = Path(str(native.get("source_provenance", {}).get("data_root"))).expanduser().resolve()
    generated_xml_path, generated_xml_ref = checked["generated_xml"]
    base._validate_conversion(conversion, current_row, generated_xml_path, generated_xml_ref["sha256"], data_root)
    scope_path, scope_ref = checked["scope_v2"]
    scope = _read_json(scope_path, "native scope V2")
    base._validate_scope(scope, scope_path, case_id, native_path, native_ref["sha256"])
    deferred = contract.get("deferred_inputs")
    if not isinstance(deferred, dict):
        raise BatchError("case deferred input map is missing")
    typed_item = deferred.get("typed_records")
    if not isinstance(typed_item, dict):
        raise BatchError("typed records deferred input is missing")
    typed_path = _path(typed_item["path"], "typed records")
    typed_stat = _stat(typed_path, "typed records")
    for field in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
        if typed_stat.get(field) != typed_item.get(field):
            raise BatchError(f"typed records deferred stat differs at {field}")
    if typed_stat["bytes"] != int(typed_item.get("bytes", -1)) or int(typed_item.get("rows", -1)) != int(summary["records"]["rows"]):
        raise BatchError("typed records deferred metadata differs")
    for role in ("partout_csv", "runparts_csv"):
        item = deferred.get(role)
        if not isinstance(item, dict):
            raise BatchError(f"{role} deferred input is missing")
        path = _path(item["path"], role)
        stat = _stat(path, role)
        for field in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino"):
            if stat.get(field) != item.get(field):
                raise BatchError(f"{role} deferred stat differs at {field}")
    return contract, current, summary, native, native_ids


def _audit_one(base: Any, contract_path: Path, output_path: Path) -> dict[str, Any]:
    contract = _read_json(contract_path, "case contract")
    _configure_base(base, contract)
    original_loader = base._load_static_contract
    base._load_static_contract = lambda path: _generic_loader(base, Path(path).expanduser().resolve())
    try:
        return base.audit(contract_path, output_path)
    finally:
        base._load_static_contract = original_loader


def audit_batch(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = _path(args.manifest, "ROOT220 batch manifest")
    manifest = _read_json(manifest_path, "ROOT220 batch manifest")
    if manifest.get("schema") != BATCH_SCHEMA or manifest.get("status") != "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED":
        raise BatchError("ROOT220 manifest is not guarded-ready")
    items = manifest.get("case_contracts")
    if not isinstance(items, list) or len(items) != 8:
        raise BatchError("ROOT220 manifest must contain eight case contracts")
    case_ids = [item.get("physical_case_id") for item in items if isinstance(item, dict)]
    if len(case_ids) != len(set(case_ids)) or set(case_ids) != set(ROOT220_CASES):
        raise BatchError("ROOT220 manifest case IDs are not the exact non-overlapping set")
    base = _load_base()
    output_path = Path(args.output).expanduser().resolve()
    if output_path.exists():
        raise BatchError(f"refusing to overwrite batch output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    case_results: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        case_id = item["physical_case_id"]
        contract_path = _path(item.get("contract_path"), f"case contract {case_id}")
        expected_contract_sha = _sha(item.get("contract_sha256"), f"case contract SHA {case_id}")
        actual_contract_sha = _hash_file(contract_path, f"case contract {case_id}", max_bytes=MAX_CASE_OUTPUT_BYTES)
        if actual_contract_sha != expected_contract_sha:
            raise BatchError(f"case contract SHA differs before case {case_id}")
        case_out = output_path.parent / "cases" / f"{case_id}.json"
        try:
            result = _audit_one(base, contract_path, case_out)
            case_results.append({"physical_case_id": case_id, "case_index": index, "status": "COMPLETED", "result": result, "output": str(case_out), "output_sha256": _hash_file(case_out, f"case output {case_id}", max_bytes=MAX_CASE_OUTPUT_BYTES)})
        except Exception as exc:
            case_results.append({"physical_case_id": case_id, "case_index": index, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "output": str(case_out), "saved_mask_credit": False})
    summary = {"schema": "ds02.stage2.f6-typed-native-batch-execution.v1", "status": "COMPLETED_WITH_PER_CASE_RESULTS" if all(x["status"] == "COMPLETED" for x in case_results) else "COMPLETED_WITH_CASE_FAILURES", "batch_id": "ROOT220", "manifest": str(manifest_path), "manifest_sha256": _hash_file(manifest_path, "ROOT220 manifest", max_bytes=MAX_BATCH_OUTPUT_BYTES), "case_count": len(case_results), "completed": sum(x["status"] == "COMPLETED" for x in case_results), "failed": sum(x["status"] == "FAILED" for x in case_results), "case_results": case_results, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    _atomic(output_path, summary)
    return {"status": summary["status"], "output": str(output_path), "completed": summary["completed"], "failed": summary["failed"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="build ROOT220 source-only batch metadata")
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path)
    prep.add_argument("--checkpoint", type=Path)
    prep.add_argument("--case-id", action="append", default=None)
    audit = sub.add_parser("audit", help="run sequential per-case audit after parent reservation")
    audit.add_argument("--manifest", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = prepare(args) if args.command == "prepare" else audit_batch(args)
    except (BatchError, OSError, ValueError) as exc:
        print(f"ROOT220 ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
