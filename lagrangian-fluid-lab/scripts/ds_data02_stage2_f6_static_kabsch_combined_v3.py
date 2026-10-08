#!/usr/bin/env python3
"""Forward v3 for the failed F6 combined static/Kabsch attempt.

The consumed v2 worker failed before opening either H5 because its bundle rows
contained a ``conversion_report`` binding while ``direct_case`` required an
in-memory ``conversion`` object.  V3 makes that contract explicit: every row
must carry a ``conversion_contract`` binding, and the worker loads that exact
completed report by path and digest before adding the in-memory object for the
already-bound v2 Kabsch implementation.  A row-level ``conversion`` injection
or a missing/ambiguous contract is rejected.

Preparation reuses the v2 terminal input SHA records and never hashes H5
content.  A shared Stage2 v4 runtime must still hash both H5 paths before and
after the new worker, and the worker opens each H5 once for static initial-MK
reconciliation plus direct Kabsch frame fits.  V2 files and its failed
receipt remain immutable.  Physical fate, dynamics, QN, and QE remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
V2_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f6_static_kabsch_combined_v2.py"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME_V4 = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2 = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4 = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4 = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
V2_BUNDLE_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f6-static-kabsch-combined-v2/f6-static-kabsch-combined-bundle.json"
)
V2_REQUEST_PRIMARY_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f6-static-kabsch-combined-v2/f6-static-kabsch-combined-request.json"
)
V2_RECEIPT_DEFAULT = DATA_ROOT / (
    "families/F6/STAGE2_F6_STATIC_KABSCH_COMBINED_V2_PRIMARY/"
    "f6-static-kabsch-combined-v2-primary-001/execution-receipt.json"
)
V2_STDOUT_DEFAULT = DATA_ROOT / (
    "families/F6/STAGE2_F6_STATIC_KABSCH_COMBINED_V2_PRIMARY/"
    "f6-static-kabsch-combined-v2-primary-001/stdout.log"
)
REQUEST_DIR_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f6-static-kabsch-combined-v3"
)

EXPECTED_IDS = (
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
)
V2_BUNDLE_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-bundle.v2"
V3_BUNDLE_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-bundle.v3"
V3_OUTPUT_SCHEMA = "ds02.stage2.f6-static-kabsch-combined.v3"
V3_VALIDATION_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-validation.v3"
CONVERSION_CONTRACT_SCHEMA = "ds02.stage2.f6-conversion-contract.v1"
REQUEST_CASE = "STAGE2_F6_STATIC_KABSCH_COMBINED_V3"
REQUEST_ATTEMPT = "f6-static-kabsch-combined-v3-primary-001"
RUNTIME_SHA_EXPECTED = "fa8e1ec4a95fb3927007a551dc15c9d762ecaaa72ae77f486457bc6d8d91f7b2"
SO3_RMSE_DEG = 2.0
SO3_MAX_DEG = 5.0

sys.path.insert(0, str(SCRIPT.parent))
import ds_data02_stage2_f6_static_kabsch_combined_v2 as v2  # noqa: E402


class CombinedV3Error(RuntimeError):
    """Raised when the forward bundle/request contract is not closed."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise CombinedV3Error(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CombinedV3Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CombinedV3Error(f"{label} is not a JSON object: {path}")
    return path, payload


def file_record(value: str | Path, label: str) -> dict[str, Any]:
    path = require_file(value, label)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def atomic_json(path: Path, payload: dict[str, Any], *, refuse_existing: bool = True) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and path.exists():
        raise CombinedV3Error(f"refuse to overwrite existing file: {path}")
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def binding(value: str | Path, label: str) -> dict[str, Any]:
    return file_record(value, label)


def h5_paths_from_receipt(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    launch = receipt.get("input_hashes_at_launch")
    finish = receipt.get("input_hashes_after_run")
    if not isinstance(launch, dict) or not isinstance(finish, dict):
        raise CombinedV3Error("consumed v2 receipt lacks terminal input hashes")
    rows: dict[str, dict[str, Any]] = {}
    for path_text, digest in launch.items():
        path = Path(path_text).expanduser().resolve()
        if path.name != "trajectory.h5":
            continue
        if finish.get(path_text) != digest or not isinstance(digest, str) or len(digest) != 64:
            raise CombinedV3Error(f"consumed v2 H5 pre/post digest is not stable: {path}")
        if not path.is_file():
            raise CombinedV3Error(f"consumed v2 H5 path is missing: {path}")
        rows[str(path)] = {"path": str(path), "sha256": digest, "bytes": path.stat().st_size,
                           "pre_sha256": digest, "post_sha256": finish.get(path_text)}
    if len(rows) != 2:
        raise CombinedV3Error(f"expected two consumed v2 H5 terminal bindings, found {len(rows)}")
    return rows


def locate_v2_request(receipt: dict[str, Any], explicit: Path | None) -> Path:
    if explicit is not None:
        return require_file(explicit, "consumed v2 request")
    request = receipt.get("request", {})
    files = request.get("input_files", []) if isinstance(request, dict) else []
    matches = [Path(value) for value in files if isinstance(value, str) and Path(value).name == "f6-static-kabsch-combined-request.json"]
    if len(matches) != 1:
        raise CombinedV3Error(f"cannot locate unique consumed v2 request from receipt: {len(matches)}")
    return require_file(matches[0], "consumed v2 request")


def validate_consumed_failure(bundle_path: Path, bundle: dict[str, Any], request_path: Path,
                              receipt_path: Path, receipt: dict[str, Any], stdout_path: Path) -> dict[str, Any]:
    if bundle.get("schema") != V2_BUNDLE_SCHEMA or bundle.get("status") != "PREPARED_COMBINED_H5_SOURCE_BOUND":
        raise CombinedV3Error("consumed source bundle is not immutable v2 prepared bundle")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "failed" or receipt.get("returncode") == 0:
        raise CombinedV3Error("consumed source receipt is not the failed v2 attempt")
    # The shared launcher wrapped the source request with a primary case and
    # strace argv before writing the terminal receipt.  Therefore the receipt
    # request_sha256 identifies that wrapper object, while the immutable source
    # request is identified by its launch input hash.  Require both identities
    # explicitly; never silently equate the two byte streams.
    launch_hashes = receipt.get("input_hashes_at_launch", {})
    source_request_key = str(request_path.resolve())
    if launch_hashes.get(source_request_key) != sha256(request_path):
        raise CombinedV3Error("consumed v2 source request is not terminal-bound by launch input hash")
    source_request = read_json(request_path, "consumed v2 source request")[1]
    if source_request.get("case_id") != "STAGE2_F6_STATIC_KABSCH_COMBINED_V2" or source_request.get("attempt_id") != "f6-static-kabsch-combined-v2":
        raise CombinedV3Error("consumed v2 source request identity differs")
    request = receipt.get("request", {})
    if request.get("case_id") != "STAGE2_F6_STATIC_KABSCH_COMBINED_V2_PRIMARY" or request.get("attempt_id") != "f6-static-kabsch-combined-v2-primary-001":
        raise CombinedV3Error("consumed v2 terminal wrapper identity differs")
    stdout = require_file(stdout_path, "consumed v2 stdout")
    stdout_text = stdout.read_text(encoding="utf-8", errors="replace")
    if "KeyError" not in stdout_text or "conversion" not in stdout_text:
        raise CombinedV3Error("consumed v2 stdout does not record the conversion contract failure")
    if receipt.get("output_root") and Path(str(receipt["output_root"])).resolve() != stdout.parent.resolve():
        raise CombinedV3Error("consumed v2 stdout is outside the failed output root")
    terminal_h5 = h5_paths_from_receipt(receipt)
    bundle_ids = {row.get("physical_case_id") for row in bundle.get("source_cases", [])}
    if bundle_ids != set(EXPECTED_IDS):
        raise CombinedV3Error("consumed v2 bundle does not cover the exact two F6 cases")
    for row in bundle["source_cases"]:
        h5 = row.get("trajectory_h5", {})
        path = str(Path(str(h5.get("path", ""))).expanduser().resolve())
        terminal = terminal_h5.get(path)
        if terminal is None or terminal["sha256"] != h5.get("sha256") or int(terminal["bytes"]) != int(h5.get("bytes")):
            raise CombinedV3Error(f"consumed v2 bundle H5 binding differs for {path}")
    return {
        "bundle": binding(bundle_path, "consumed v2 bundle"),
        "request": binding(request_path, "consumed v2 request"),
        "execution_receipt": binding(receipt_path, "consumed v2 failed receipt"),
        "stdout": binding(stdout, "consumed v2 stdout"),
        "status": "failed_before_worker_h5_open",
        "failure_signature": "KeyError: conversion in ds_data02_stage2_f6_static_kabsch_combined_v2.direct_case",
        "receipt_request_sha256": receipt.get("request_sha256"),
        "source_request_sha256": sha256(request_path),
        "h5_terminal_bindings": terminal_h5,
        "terminal_input_hashes": {
            "at_launch": receipt["input_hashes_at_launch"],
            "after_run": receipt["input_hashes_after_run"],
        },
    }


def conversion_contract(row: dict[str, Any]) -> dict[str, Any]:
    """Build the explicit v3 contract from one immutable v2 source row."""
    old_report = row.get("conversion_report")
    if not isinstance(old_report, dict):
        raise CombinedV3Error("consumed v2 source row lacks conversion_report binding")
    report_path = require_file(old_report.get("path", ""), "conversion report")
    report_sha = old_report.get("sha256")
    if not isinstance(report_sha, str) or sha256(report_path) != report_sha:
        raise CombinedV3Error(f"conversion report digest differs: {report_path}")
    report = read_json(report_path, "conversion report")[1]
    if report.get("conversion_status") != "completed":
        raise CombinedV3Error(f"conversion report is not completed: {report_path}")
    output_hdf5 = Path(str(report.get("output_hdf5", ""))).expanduser().resolve()
    h5 = row.get("trajectory_h5", {})
    expected_h5 = Path(str(h5.get("path", ""))).expanduser().resolve()
    if output_hdf5 != expected_h5:
        raise CombinedV3Error("conversion output H5 differs from bound source H5")
    if str(report.get("output_sha256")) != str(h5.get("sha256")):
        raise CombinedV3Error("conversion output SHA differs from bound source H5 SHA")
    provenance = report.get("source_provenance", {})
    solver_provenance = provenance.get("solver_receipt", {})
    solver_binding = row.get("solver_receipt", {})
    if str(solver_provenance.get("path", "")).strip() != str(solver_binding.get("path", "")).strip():
        raise CombinedV3Error("conversion solver receipt path differs from source row")
    if str(solver_provenance.get("sha256", "")) != str(solver_binding.get("sha256", "")):
        raise CombinedV3Error("conversion solver receipt SHA differs from source row")
    typed = report.get("typed_identity")
    if not isinstance(typed, dict) or not isinstance(typed.get("blocks"), list):
        raise CombinedV3Error("conversion report lacks typed_identity blocks")
    return {
        "schema": CONVERSION_CONTRACT_SCHEMA,
        "report": file_record(report_path, "conversion report"),
        "conversion_status": "completed",
        "output_hdf5": {
            "path": str(expected_h5),
            "sha256": str(h5["sha256"]),
            "bytes": int(h5["bytes"]),
        },
        "source_provenance": {
            "data_root": str(Path(str(provenance.get("data_root", ""))).expanduser().resolve()),
            "solver_receipt": dict(solver_provenance),
        },
        "typed_identity": {"required": True, "key": "typed_identity", "block_count": len(typed["blocks"])},
        "contract_rule": "worker loads report by this exact path/SHA; no row conversion object is accepted",
    }


def validate_v3_row_shape(row: dict[str, Any]) -> None:
    if "conversion" in row:
        raise CombinedV3Error("v3 source row must not carry an unbound conversion object")
    if not isinstance(row.get("conversion_contract"), dict) or row["conversion_contract"].get("schema") != CONVERSION_CONTRACT_SCHEMA:
        raise CombinedV3Error("v3 source row lacks explicit conversion_contract")
    required = ("sentinel_id", "physical_case_id", "trajectory_h5", "small_sources", "solver_receipt", "conversion_contract")
    missing = [key for key in required if key not in row]
    if missing:
        raise CombinedV3Error(f"v3 source row lacks required fields {missing}")
    if row.get("physical_case_id") not in EXPECTED_IDS:
        raise CombinedV3Error("v3 source row physical identity is outside selected F6 pair")


def load_conversion(row: dict[str, Any]) -> dict[str, Any]:
    validate_v3_row_shape(row)
    contract = row["conversion_contract"]
    report_binding = contract.get("report", {})
    report_path = require_file(report_binding.get("path", ""), "v3 bound conversion report")
    if report_binding.get("sha256") != sha256(report_path):
        raise CombinedV3Error(f"v3 conversion report digest changed: {report_path}")
    report = read_json(report_path, "v3 bound conversion report")[1]
    if report.get("conversion_status") != "completed" or contract.get("conversion_status") != "completed":
        raise CombinedV3Error("v3 conversion contract/report is not completed")
    output = contract.get("output_hdf5", {})
    h5 = row["trajectory_h5"]
    if str(Path(str(output.get("path", ""))).expanduser().resolve()) != str(Path(str(h5["path"])).expanduser().resolve()):
        raise CombinedV3Error("v3 conversion output path differs from H5 row")
    if output.get("sha256") != h5.get("sha256") or report.get("output_sha256") != h5.get("sha256"):
        raise CombinedV3Error("v3 conversion/H5 SHA contract differs")
    provenance = report.get("source_provenance", {})
    contract_provenance = contract.get("source_provenance", {})
    if str(provenance.get("data_root", "")).strip() != str(contract_provenance.get("data_root", "")).strip():
        raise CombinedV3Error("v3 conversion data_root differs from contract")
    if provenance.get("solver_receipt") != contract_provenance.get("solver_receipt"):
        raise CombinedV3Error("v3 conversion solver receipt differs from contract")
    return report


def prepare(v2_bundle_path: Path, v2_request_path: Path | None, v2_receipt_path: Path,
            v2_stdout_path: Path, output_manifest: Path, output_request: Path) -> dict[str, Any]:
    bundle_path, v2_bundle = read_json(v2_bundle_path, "consumed v2 bundle")
    receipt_path, receipt = read_json(v2_receipt_path, "consumed v2 failed receipt")
    request_path = locate_v2_request(receipt, v2_request_path)
    stdout_path = require_file(v2_stdout_path, "consumed v2 stdout")
    failure = validate_consumed_failure(bundle_path, v2_bundle, request_path, receipt_path, receipt, stdout_path)
    rows = []
    source_paths: list[Path] = []
    for old_row in v2_bundle["source_cases"]:
        contract = conversion_contract(old_row)
        new_row = copy.deepcopy(old_row)
        new_row.pop("conversion_report", None)
        new_row["conversion_contract"] = contract
        validate_v3_row_shape(new_row)
        rows.append(new_row)
        source_paths.append(Path(contract["report"]["path"]))
        source_paths.extend(Path(value["path"]) for value in old_row.get("small_sources", {}).values())
        source_paths.append(Path(old_row["solver_receipt"]["path"]))
    h5_terminal = failure["h5_terminal_bindings"]
    h5_paths = {Path(value["path"]).resolve() for value in h5_terminal.values()}
    source_paths.extend([
        V2_SCRIPT, SCRIPT, VENV, RUNTIME_V2, RUNTIME_V4, DISPATCH_V4, STRICT_V4,
        bundle_path, request_path, receipt_path, stdout_path,
    ])
    # Bind the existing v2 request's non-H5 inputs too, while retaining its
    # terminal H5 SHA values as immutable source evidence.  This closes the
    # consumed attempt without manually hashing either multi-gigabyte H5 now.
    v2_request = read_json(request_path, "consumed v2 request")[1]
    source_paths.extend(Path(value) for value in v2_request.get("input_files", []) if Path(value).resolve() not in h5_paths)
    unique: list[Path] = []
    seen: set[str] = set()
    for value in source_paths:
        path = require_file(value, "v3 source input")
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    # Write a new bundle before computing its request hash.  H5 bytes/digests
    # are copied from the consumed terminal receipt; no H5 content is opened.
    manifest = {
        "schema": V3_BUNDLE_SCHEMA,
        "status": "PREPARED_COMBINED_V3_H5_SOURCE_BOUND",
        "selected_case_ids": list(EXPECTED_IDS),
        "consumed_v2_failure": failure,
        "source_cases": rows,
        "hash_ownership": {
            "owner": "single_combined_v3_attempt",
            "h5_paths_registered_once": True,
            "h5_hash_pre_post_required_by_runtime": True,
            "h5_hash_reused_from_consumed_v2_terminal": True,
            "static_and_kabsch_share_same_h5_open": True,
            "child_static_pre_post_forbidden": True,
            "h5_content_hashed_during_prepare": False,
            "terminal_bindings": h5_terminal,
        },
        "execution_contract": {
            "conversion_schema": CONVERSION_CONTRACT_SCHEMA,
            "conversion_object_in_row": False,
            "worker_loads_conversion_by_path_and_sha": True,
            "one_open_per_h5": True,
            "static_initial_datasets_and_floating_frames_same_handle": True,
            "kabsch_source": "direct SO(3) from H5 type=2 (Zone,Idp) positions",
            "snapshot_json_written": False,
            "so3_tolerances_deg": {"rmse": SO3_RMSE_DEG, "max": SO3_MAX_DEG},
            "body_mass_kg": 128.0,
            "support_sample_mass_kg": 256.0,
        },
        "runtime_binding": binding(RUNTIME_V4, "Stage2 v4 runtime"),
        "read_policy": {"h5_opened": False, "solver_started": False, "kabsch_started": False},
    }
    output_manifest = output_manifest.resolve()
    atomic_json(output_manifest, manifest)
    manifest_sha = sha256(output_manifest)
    # Include the new manifest in the guarded source set.  H5 hashes come only
    # from the immutable consumed terminal receipt in this preparation path.
    input_hashes: dict[str, str] = {str(path): sha256(path) for path in unique}
    for path in h5_paths:
        record = h5_terminal[str(path)]
        input_hashes[str(path)] = record["sha256"]
    input_hashes[str(output_manifest)] = manifest_sha
    manifest["guard_input_files"] = sorted(input_hashes)
    # The guard input list is part of the bundle, so update it atomically and
    # recompute the manifest hash before building the request.
    atomic_json(output_manifest, manifest, refuse_existing=False)
    manifest_sha = sha256(output_manifest)
    input_hashes[str(output_manifest)] = manifest_sha
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F6",
        "case_id": REQUEST_CASE,
        "attempt_id": REQUEST_ATTEMPT,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "cwd": str(SCRIPT.parent),
        "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "run", "--manifest", str(output_manifest), "--output", "{attempt_root}/f6-static-kabsch-combined.json"],
        "input_files": sorted(input_hashes),
        "input_sha256": dict(sorted(input_hashes.items())),
        "runtime_binding": binding(RUNTIME_V4, "Stage2 v4 runtime"),
        "source_policy": {
            "h5_read_by_worker": True,
            "h5_hash_by_runtime_pre_post": True,
            "h5_hash_reused_from_consumed_v2_terminal": True,
            "h5_hash_by_prepare": False,
            "h5_hash_owner": "single_combined_v3_attempt",
            "static_and_kabsch_same_attempt": True,
            "snapshot_json": "not written; in-process frame stream",
        },
        "source_cases": [{
            "sentinel_id": row["sentinel_id"],
            "physical_case_id": row["physical_case_id"],
            "trajectory_h5_path": row["trajectory_h5"]["path"],
            "trajectory_h5_sha256": row["trajectory_h5"]["sha256"],
            "trajectory_h5_bytes": row["trajectory_h5"]["bytes"],
            "terminal_pre_sha256": h5_terminal[row["trajectory_h5"]["path"]]["pre_sha256"],
            "terminal_post_sha256": h5_terminal[row["trajectory_h5"]["path"]]["post_sha256"],
        } for row in rows],
        "source_read_cost": {
            "h5_total_bytes": sum(int(row["trajectory_h5"]["bytes"]) for row in rows),
            "runtime_pre_post_hash_bytes": sum(int(row["trajectory_h5"]["bytes"]) for row in rows) * 2,
            "worker_frame_reads": "all time/valid/position rows for type=2 support samples; no duplicate child",
            "output_json_estimate_bytes": 256 * 1024 * 1024,
        },
        "consumed_v2_failure": failure,
        "canonical_ready": True,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "launch_commit": git_head(),
        "request_note": "Forward v3 fixes consumed v2 conversion-contract KeyError by exact report path/SHA loading; it preserves the failed v2 bytes, reuses terminal H5 SHA evidence, and requires one shared runtime pre/post hash around static plus Kabsch H5 reads.",
    }
    output_request = output_request.resolve()
    atomic_json(output_request, request)
    return {
        "status": "prepared",
        "bundle": str(output_manifest),
        "bundle_sha256": manifest_sha,
        "request": str(output_request),
        "request_sha256": sha256(output_request),
        "h5_pre_post_hash_bytes": request["source_read_cost"]["runtime_pre_post_hash_bytes"],
        "input_count": len(input_hashes),
        "consumed_v2_failure": failure["failure_signature"],
    }


def direct_case_v3(row: dict[str, Any]) -> dict[str, Any]:
    """Use v2's tested H5/Kabsch implementation after v3 contract loading."""
    conversion = load_conversion(row)
    enriched = copy.deepcopy(row)
    # This object exists only in memory after exact v3 contract validation; it
    # is never accepted from or written back into the bundle.
    enriched["conversion"] = conversion
    result = v2.direct_case(enriched)
    result["conversion_contract"] = row["conversion_contract"]
    result["conversion_object_source"] = "loaded_from_exact_v3_report_binding_in_worker"
    return result


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path, bundle = read_json(manifest_path, "F6 combined v3 bundle")
    if bundle.get("schema") != V3_BUNDLE_SCHEMA or bundle.get("status") != "PREPARED_COMBINED_V3_H5_SOURCE_BOUND":
        raise CombinedV3Error("combined v3 bundle is not prepared")
    if bundle.get("execution_contract", {}).get("conversion_object_in_row") is not False:
        raise CombinedV3Error("v3 bundle does not forbid unbound conversion objects")
    rows = bundle.get("source_cases")
    if not isinstance(rows, list) or {row.get("physical_case_id") for row in rows} != set(EXPECTED_IDS):
        raise CombinedV3Error("combined v3 worker does not cover exact F6 pair")
    results = [direct_case_v3(row) for row in rows]
    result = {
        "schema": V3_OUTPUT_SCHEMA,
        "status": "completed",
        "bundle": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
        "consumed_v2_failure": bundle["consumed_v2_failure"],
        "cases": results,
        "runtime_binding_expected": bundle["runtime_binding"],
        "h5_hash_coverage": bundle["hash_ownership"],
        "source_policy": {
            "h5_opened": True,
            "h5_open_mode": "one_handle_per_case_shared_static_and_kabsch",
            "h5_rehashed_by_worker": False,
            "h5_pre_post_owner": "shared_runtime_v4",
            "snapshot_json_written": False,
            "solver_started": False,
            "cfd_or_model_run": False,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(output, result)
    return result


def validate(manifest_path: Path, output_path: Path, receipt_path: Path) -> dict[str, Any]:
    manifest_path, bundle = read_json(manifest_path, "F6 combined v3 bundle")
    output_path, result = read_json(output_path, "F6 combined v3 output")
    receipt_path, receipt = read_json(receipt_path, "F6 combined v3 execution receipt")
    if bundle.get("schema") != V3_BUNDLE_SCHEMA or result.get("schema") != V3_OUTPUT_SCHEMA:
        raise CombinedV3Error("v3 schema mismatch")
    if result.get("status") != "completed" or receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise CombinedV3Error("v3 output/receipt is not completed code 0")
    if receipt.get("request", {}).get("case_id") != REQUEST_CASE or receipt.get("request", {}).get("attempt_id") != REQUEST_ATTEMPT:
        raise CombinedV3Error("v3 receipt request identity differs")
    runtime = bundle["runtime_binding"]
    if receipt.get("runner_source") != runtime["path"] or receipt.get("runner_sha256") != runtime["sha256"]:
        raise CombinedV3Error("execution receipt is not from bound Stage2 v4 runtime")
    request = receipt.get("request", {})
    input_files = {str(Path(path).resolve()) for path in request.get("input_files", [])}
    declared = request.get("input_sha256", {})
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    expected_files = set(str(Path(path).resolve()) for path in bundle.get("guard_input_files", []))
    expected_files.add(str(manifest_path.resolve()))
    if not expected_files <= input_files:
        raise CombinedV3Error("runtime request omits a v3 source input")
    for key in expected_files:
        expected = declared.get(key)
        if not expected or launch.get(key) != expected or finish.get(key) != expected:
            raise CombinedV3Error(f"runtime receipt lacks stable v3 source binding: {key}")
    for row in bundle["source_cases"]:
        validate_v3_row_shape(row)
        h5 = row["trajectory_h5"]
        key = str(Path(h5["path"]).resolve())
        if key not in input_files or declared.get(key) != h5["sha256"] or launch.get(key) != h5["sha256"] or finish.get(key) != h5["sha256"]:
            raise CombinedV3Error(f"runtime receipt lacks stable pre/post H5 binding: {key}")
        contract = row["conversion_contract"]
        if contract["output_hdf5"]["sha256"] != h5["sha256"]:
            raise CombinedV3Error(f"v3 conversion/H5 contract differs: {key}")
    if {row.get("physical_case_id") for row in result.get("cases", [])} != set(EXPECTED_IDS):
        raise CombinedV3Error("v3 output has wrong case union")
    for row in result["cases"]:
        if row.get("h5_read_ledger", {}).get("opened_once") is not True:
            raise CombinedV3Error(f"{row.get('physical_case_id')} lacks one-open ledger")
        if row.get("static", {}).get("trajectory", {}).get("frame_datasets_read") is not True:
            raise CombinedV3Error(f"{row.get('physical_case_id')} did not record frame reads")
        if row.get("kabsch", {}).get("status") != "completed":
            raise CombinedV3Error(f"{row.get('physical_case_id')} lacks Kabsch result")
        if row.get("kabsch", {}).get("frozen_contract", {}).get("so3_error_tolerances_deg") != {"rmse": SO3_RMSE_DEG, "max": SO3_MAX_DEG}:
            raise CombinedV3Error("v3 SO3 tolerance contract differs")
        if row.get("conversion_object_source") != "loaded_from_exact_v3_report_binding_in_worker":
            raise CombinedV3Error("v3 output lacks exact conversion contract provenance")
    checked = {
        "schema": V3_VALIDATION_SCHEMA,
        "status": "completed",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "output": {"path": str(output_path), "sha256": sha256(output_path)},
        "execution_receipt": {"path": str(receipt_path), "sha256": sha256(receipt_path)},
        "consumed_v2_failure_preserved": bundle["consumed_v2_failure"],
        "runtime_h5_pre_post_verified": True,
        "cases": sorted(row["physical_case_id"] for row in result["cases"]),
        "source_policy": {"h5_opened": True, "shared_attempt": True, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN"},
    }
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--v2-bundle", type=Path, default=V2_BUNDLE_DEFAULT)
    prep.add_argument("--v2-request", type=Path)
    prep.add_argument("--v2-receipt", type=Path, default=V2_RECEIPT_DEFAULT)
    prep.add_argument("--v2-stdout", type=Path, default=V2_STDOUT_DEFAULT)
    prep.add_argument("--output-manifest", type=Path, required=True)
    prep.add_argument("--output-request", type=Path, required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--manifest", type=Path, required=True)
    runner.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.v2_bundle, args.v2_request, args.v2_receipt, args.v2_stdout, args.output_manifest, args.output_request)
        elif args.action == "run":
            result = run(args.manifest, args.output)
        else:
            result = validate(args.manifest, args.output, args.receipt)
    except CombinedV3Error as exc:
        raise SystemExit(f"CombinedV3Error: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
