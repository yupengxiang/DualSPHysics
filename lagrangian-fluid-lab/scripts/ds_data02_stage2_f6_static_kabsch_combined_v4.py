#!/usr/bin/env python3
"""Forward v4 for the F6 combined static/Kabsch attempt.

The consumed v2 worker failed before opening either H5 because its bundle rows
contained a ``conversion_report`` binding while ``direct_case`` required an
in-memory ``conversion`` object.  V4 consumes the prepared v3 bundle and makes
that contract explicit: every row
must carry a ``conversion_contract`` binding, and the worker loads that exact
completed report by path and digest before adding the in-memory object for the
already-bound v2 Kabsch implementation.  A row-level ``conversion`` injection
or a missing/ambiguous contract is rejected.

Preparation reuses the v3 source-bound H5 SHA records and never hashes H5
content.  The shared Stage2 v6 runtime must still hash both H5 paths before and
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
V3_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f6_static_kabsch_combined_v3.py"
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNTIME_V6 = SCRIPT.parent / "ds_data02_runtime_v6.py"
RUNTIME_V2 = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V6 = SCRIPT.parent / "ds_data02_stage2_dispatch_v6.py"
STRICT_V6 = SCRIPT.parent / "ds_data02_strict_dispatch_v6.py"
DISPATCH_V4 = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4 = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
V3_BUNDLE_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f6-static-kabsch-combined-v3/f6-static-kabsch-combined-bundle.json"
)
V3_REQUEST_DEFAULT = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "f6-static-kabsch-combined-v3/f6-static-kabsch-combined-request.json"
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
    "f6-static-kabsch-combined-v4"
)

EXPECTED_IDS = (
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S095_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025",
)
V2_BUNDLE_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-bundle.v2"
V3_BUNDLE_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-bundle.v3"
V4_BUNDLE_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-bundle.v4"
V4_OUTPUT_SCHEMA = "ds02.stage2.f6-static-kabsch-combined.v4"
V4_VALIDATION_SCHEMA = "ds02.stage2.f6-static-kabsch-combined-validation.v4"
CONVERSION_CONTRACT_SCHEMA = "ds02.stage2.f6-conversion-contract.v1"
REQUEST_CASE = "STAGE2_F6_STATIC_KABSCH_COMBINED_V4"
REQUEST_ATTEMPT = "f6-static-kabsch-combined-v4-primary-001"
RUNTIME_SHA_EXPECTED = ""  # resolved and bound from the shared v6 source at prepare time
SO3_RMSE_DEG = 2.0
SO3_MAX_DEG = 5.0

sys.path.insert(0, str(SCRIPT.parent))
import ds_data02_stage2_f6_static_kabsch_combined_v2 as v2  # noqa: E402


class CombinedV4Error(RuntimeError):
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
        raise CombinedV4Error(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CombinedV4Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CombinedV4Error(f"{label} is not a JSON object: {path}")
    return path, payload


def file_record(value: str | Path, label: str) -> dict[str, Any]:
    path = require_file(value, label)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def atomic_json(path: Path, payload: dict[str, Any], *, refuse_existing: bool = True) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and path.exists():
        raise CombinedV4Error(f"refuse to overwrite existing file: {path}")
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
        raise CombinedV4Error("consumed v2 receipt lacks terminal input hashes")
    rows: dict[str, dict[str, Any]] = {}
    for path_text, digest in launch.items():
        path = Path(path_text).expanduser().resolve()
        if path.name != "trajectory.h5":
            continue
        if finish.get(path_text) != digest or not isinstance(digest, str) or len(digest) != 64:
            raise CombinedV4Error(f"consumed v2 H5 pre/post digest is not stable: {path}")
        if not path.is_file():
            raise CombinedV4Error(f"consumed v2 H5 path is missing: {path}")
        rows[str(path)] = {"path": str(path), "sha256": digest, "bytes": path.stat().st_size,
                           "pre_sha256": digest, "post_sha256": finish.get(path_text)}
    if len(rows) != 2:
        raise CombinedV4Error(f"expected two consumed v2 H5 terminal bindings, found {len(rows)}")
    return rows


def locate_v2_request(receipt: dict[str, Any], explicit: Path | None) -> Path:
    if explicit is not None:
        return require_file(explicit, "consumed v2 request")
    request = receipt.get("request", {})
    files = request.get("input_files", []) if isinstance(request, dict) else []
    matches = [Path(value) for value in files if isinstance(value, str) and Path(value).name == "f6-static-kabsch-combined-request.json"]
    if len(matches) != 1:
        raise CombinedV4Error(f"cannot locate unique consumed v2 request from receipt: {len(matches)}")
    return require_file(matches[0], "consumed v2 request")


def validate_consumed_failure(bundle_path: Path, bundle: dict[str, Any], request_path: Path,
                              receipt_path: Path, receipt: dict[str, Any], stdout_path: Path) -> dict[str, Any]:
    if bundle.get("schema") != V2_BUNDLE_SCHEMA or bundle.get("status") != "PREPARED_COMBINED_H5_SOURCE_BOUND":
        raise CombinedV4Error("consumed source bundle is not immutable v2 prepared bundle")
    if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "failed" or receipt.get("returncode") == 0:
        raise CombinedV4Error("consumed source receipt is not the failed v2 attempt")
    # The shared launcher wrapped the source request with a primary case and
    # strace argv before writing the terminal receipt.  Therefore the receipt
    # request_sha256 identifies that wrapper object, while the immutable source
    # request is identified by its launch input hash.  Require both identities
    # explicitly; never silently equate the two byte streams.
    launch_hashes = receipt.get("input_hashes_at_launch", {})
    source_request_key = str(request_path.resolve())
    if launch_hashes.get(source_request_key) != sha256(request_path):
        raise CombinedV4Error("consumed v2 source request is not terminal-bound by launch input hash")
    source_request = read_json(request_path, "consumed v2 source request")[1]
    if source_request.get("case_id") != "STAGE2_F6_STATIC_KABSCH_COMBINED_V2" or source_request.get("attempt_id") != "f6-static-kabsch-combined-v2":
        raise CombinedV4Error("consumed v2 source request identity differs")
    request = receipt.get("request", {})
    if request.get("case_id") != "STAGE2_F6_STATIC_KABSCH_COMBINED_V2_PRIMARY" or request.get("attempt_id") != "f6-static-kabsch-combined-v2-primary-001":
        raise CombinedV4Error("consumed v2 terminal wrapper identity differs")
    stdout = require_file(stdout_path, "consumed v2 stdout")
    stdout_text = stdout.read_text(encoding="utf-8", errors="replace")
    if "KeyError" not in stdout_text or "conversion" not in stdout_text:
        raise CombinedV4Error("consumed v2 stdout does not record the conversion contract failure")
    if receipt.get("output_root") and Path(str(receipt["output_root"])).resolve() != stdout.parent.resolve():
        raise CombinedV4Error("consumed v2 stdout is outside the failed output root")
    terminal_h5 = h5_paths_from_receipt(receipt)
    bundle_ids = {row.get("physical_case_id") for row in bundle.get("source_cases", [])}
    if bundle_ids != set(EXPECTED_IDS):
        raise CombinedV4Error("consumed v2 bundle does not cover the exact two F6 cases")
    for row in bundle["source_cases"]:
        h5 = row.get("trajectory_h5", {})
        path = str(Path(str(h5.get("path", ""))).expanduser().resolve())
        terminal = terminal_h5.get(path)
        if terminal is None or terminal["sha256"] != h5.get("sha256") or int(terminal["bytes"]) != int(h5.get("bytes")):
            raise CombinedV4Error(f"consumed v2 bundle H5 binding differs for {path}")
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
    """Build the explicit v4 contract from one immutable v2 source row."""
    old_report = row.get("conversion_report")
    if not isinstance(old_report, dict):
        raise CombinedV4Error("consumed v2 source row lacks conversion_report binding")
    report_path = require_file(old_report.get("path", ""), "conversion report")
    report_sha = old_report.get("sha256")
    if not isinstance(report_sha, str) or sha256(report_path) != report_sha:
        raise CombinedV4Error(f"conversion report digest differs: {report_path}")
    report = read_json(report_path, "conversion report")[1]
    if report.get("conversion_status") != "completed":
        raise CombinedV4Error(f"conversion report is not completed: {report_path}")
    output_hdf5 = Path(str(report.get("output_hdf5", ""))).expanduser().resolve()
    h5 = row.get("trajectory_h5", {})
    expected_h5 = Path(str(h5.get("path", ""))).expanduser().resolve()
    if output_hdf5 != expected_h5:
        raise CombinedV4Error("conversion output H5 differs from bound source H5")
    if str(report.get("output_sha256")) != str(h5.get("sha256")):
        raise CombinedV4Error("conversion output SHA differs from bound source H5 SHA")
    provenance = report.get("source_provenance", {})
    solver_provenance = provenance.get("solver_receipt", {})
    solver_binding = row.get("solver_receipt", {})
    if str(solver_provenance.get("path", "")).strip() != str(solver_binding.get("path", "")).strip():
        raise CombinedV4Error("conversion solver receipt path differs from source row")
    if str(solver_provenance.get("sha256", "")) != str(solver_binding.get("sha256", "")):
        raise CombinedV4Error("conversion solver receipt SHA differs from source row")
    typed = report.get("typed_identity")
    if not isinstance(typed, dict) or not isinstance(typed.get("blocks"), list):
        raise CombinedV4Error("conversion report lacks typed_identity blocks")
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


def validate_v4_row_shape(row: dict[str, Any]) -> None:
    if "conversion" in row:
        raise CombinedV4Error("v4 source row must not carry an unbound conversion object")
    if not isinstance(row.get("conversion_contract"), dict) or row["conversion_contract"].get("schema") != CONVERSION_CONTRACT_SCHEMA:
        raise CombinedV4Error("v4 source row lacks explicit conversion_contract")
    required = ("sentinel_id", "physical_case_id", "trajectory_h5", "small_sources", "solver_receipt", "conversion_contract")
    missing = [key for key in required if key not in row]
    if missing:
        raise CombinedV4Error(f"v4 source row lacks required fields {missing}")
    if row.get("physical_case_id") not in EXPECTED_IDS:
        raise CombinedV4Error("v4 source row physical identity is outside selected F6 pair")


def load_conversion(row: dict[str, Any]) -> dict[str, Any]:
    validate_v4_row_shape(row)
    contract = row["conversion_contract"]
    report_binding = contract.get("report", {})
    report_path = require_file(report_binding.get("path", ""), "v4 bound conversion report")
    if report_binding.get("sha256") != sha256(report_path):
        raise CombinedV4Error(f"v4 conversion report digest changed: {report_path}")
    report = read_json(report_path, "v4 bound conversion report")[1]
    if report.get("conversion_status") != "completed" or contract.get("conversion_status") != "completed":
        raise CombinedV4Error("v4 conversion contract/report is not completed")
    output = contract.get("output_hdf5", {})
    h5 = row["trajectory_h5"]
    if str(Path(str(output.get("path", ""))).expanduser().resolve()) != str(Path(str(h5["path"])).expanduser().resolve()):
        raise CombinedV4Error("v4 conversion output path differs from H5 row")
    if output.get("sha256") != h5.get("sha256") or report.get("output_sha256") != h5.get("sha256"):
        raise CombinedV4Error("v4 conversion/H5 SHA contract differs")
    provenance = report.get("source_provenance", {})
    contract_provenance = contract.get("source_provenance", {})
    if str(provenance.get("data_root", "")).strip() != str(contract_provenance.get("data_root", "")).strip():
        raise CombinedV4Error("v4 conversion data_root differs from contract")
    if provenance.get("solver_receipt") != contract_provenance.get("solver_receipt"):
        raise CombinedV4Error("v4 conversion solver receipt differs from contract")
    return report


def _validate_v3_source(v3_bundle_path: Path, v3_request_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[Path], dict[str, dict[str, Any]]]:
    """Validate the immutable prepared-v3 contract without opening either H5."""
    bundle_path, bundle = read_json(v3_bundle_path, "consumed v3 bundle")
    request_path, request = read_json(v3_request_path, "consumed v3 request")
    if bundle.get("schema") != V3_BUNDLE_SCHEMA or bundle.get("status") != "PREPARED_COMBINED_V3_H5_SOURCE_BOUND":
        raise CombinedV4Error("consumed v3 bundle is not the prepared source-bound bundle")
    if request.get("schema") != "ds02.request.v1" or request.get("case_id") != "STAGE2_F6_STATIC_KABSCH_COMBINED_V3" or request.get("attempt_id") != "f6-static-kabsch-combined-v3-primary-001":
        raise CombinedV4Error("consumed v3 request identity differs")
    declared = request.get("input_sha256")
    input_files = request.get("input_files")
    if not isinstance(declared, dict) or not isinstance(input_files, list):
        raise CombinedV4Error("consumed v3 request lacks registered input bindings")
    bundle_key = str(v3_bundle_path.resolve())
    if bundle_key not in input_files or declared.get(bundle_key) != sha256(v3_bundle_path):
        raise CombinedV4Error("consumed v3 request does not bind its exact bundle")
    terminal = bundle.get("hash_ownership", {}).get("terminal_bindings")
    if not isinstance(terminal, dict) or set(terminal) != {str(Path(row.get("trajectory_h5", {}).get("path", "")).expanduser().resolve()) for row in bundle.get("source_cases", [])}:
        raise CombinedV4Error("consumed v3 bundle lacks exact two terminal H5 bindings")
    if {row.get("physical_case_id") for row in bundle.get("source_cases", [])} != set(EXPECTED_IDS):
        raise CombinedV4Error("consumed v3 bundle does not cover the exact F6 pair")
    h5_paths = set(terminal)
    # Verify every small v3 request input now.  H5 content is represented only
    # by the immutable terminal digest and is deliberately not rehashed here.
    source_paths: list[Path] = []
    for raw in input_files:
        path = require_file(raw, "consumed v3 source input")
        key = str(path.resolve())
        expected = declared.get(key)
        if not isinstance(expected, str) or len(expected) != 64:
            raise CombinedV4Error(f"consumed v3 input lacks SHA: {path}")
        if key in h5_paths:
            record = terminal[key]
            if expected != record.get("sha256"):
                raise CombinedV4Error(f"consumed v3 H5 declaration differs: {path}")
        elif sha256(path) != expected:
            raise CombinedV4Error(f"consumed v3 source input changed: {path}")
        source_paths.append(path)
    rows = bundle.get("source_cases", [])
    for row in rows:
        validate_v4_row_shape(row)
        h5 = row["trajectory_h5"]
        key = str(Path(h5["path"]).expanduser().resolve())
        record = terminal.get(key)
        if record is None or record.get("sha256") != h5.get("sha256") or int(record.get("bytes", -1)) != int(h5.get("bytes", -2)):
            raise CombinedV4Error(f"consumed v3 row H5 differs from terminal binding: {key}")
        load_conversion(row)
    return bundle, request, source_paths, terminal


def prepare(v3_bundle_path: Path, v3_request_path: Path,
            output_manifest: Path, output_request: Path) -> dict[str, Any]:
    """Forward the prepared v3 source into one shared-v6 guarded attempt."""
    bundle_path, request_path = v3_bundle_path.resolve(), v3_request_path.resolve()
    v3_bundle, v3_request, inherited_paths, h5_terminal = _validate_v3_source(bundle_path, request_path)
    rows = copy.deepcopy(v3_bundle["source_cases"])
    h5_paths = {Path(value["path"]).resolve() for value in h5_terminal.values()}
    # inherited_paths includes H5 paths from the consumed request; never
    # rehash those during preparation. Their terminal SHA is copied below.
    source_paths: list[Path] = [path for path in inherited_paths if path not in h5_paths]
    source_paths.extend([
        V2_SCRIPT, V3_SCRIPT, SCRIPT, VENV, RUNTIME_V2, RUNTIME_V6,
        DISPATCH_V6, STRICT_V6,
    ])
    # Keep the consumed v3 runtime stack and source request in the closure;
    # v4's execution authority is nevertheless exclusively shared v6.
    for raw in v3_request.get("input_files", []):
        path = Path(raw).expanduser().resolve()
        if path not in h5_paths:
            source_paths.append(path)
    unique: list[Path] = []
    seen: set[str] = set()
    for value in source_paths:
        path = require_file(value, "v4 source input")
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    runtime_binding = binding(RUNTIME_V6, "shared Stage2 v6 runtime")
    dispatch_binding = binding(DISPATCH_V6, "shared Stage2 v6 dispatch")
    strict_binding = binding(STRICT_V6, "shared Stage2 v6 strict dispatch")
    manifest = {
        "schema": V4_BUNDLE_SCHEMA,
        "status": "PREPARED_COMBINED_V4_H5_SOURCE_BOUND",
        "selected_case_ids": list(EXPECTED_IDS),
        "consumed_v3_source": {
            "bundle": binding(bundle_path, "consumed v3 bundle"),
            "request": binding(request_path, "consumed v3 request"),
            "bundle_schema": V3_BUNDLE_SCHEMA,
            "request_case": v3_request["case_id"],
            "consumed_v2_failure_preserved": v3_bundle.get("consumed_v2_failure"),
        },
        "source_cases": rows,
        "hash_ownership": {
            "owner": "single_combined_v4_attempt",
            "h5_paths_registered_once": True,
            "h5_hash_pre_post_required_by_runtime": True,
            "h5_hash_reused_from_consumed_v3_terminal": True,
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
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "runtime_stack": {
            "shared_v6_runtime": runtime_binding,
            "shared_v6_dispatch": dispatch_binding,
            "shared_v6_strict_dispatch": strict_binding,
            "v6_entry_is_the_only_ledger_owner": True,
        },
        "runtime_binding": runtime_binding,
        "read_policy": {"h5_opened": False, "solver_started": False, "kabsch_started": False},
    }
    output_manifest = output_manifest.resolve()
    atomic_json(output_manifest, manifest)
    manifest_sha = sha256(output_manifest)
    input_hashes: dict[str, str] = {str(path): sha256(path) for path in unique}
    # Preserve terminal H5 SHA values without opening H5 in preparation.
    for path in h5_paths:
        input_hashes[str(path)] = h5_terminal[str(path)]["sha256"]
    input_hashes[str(output_manifest)] = manifest_sha
    manifest["guard_input_files"] = sorted(input_hashes)
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
        "runtime_binding": runtime_binding,
        "dispatch_binding": dispatch_binding,
        "strict_dispatch_binding": strict_binding,
        "shared_runtime_version": "v6",
        "source_policy": {
            "h5_read_by_worker": True,
            "h5_hash_by_runtime_pre_post": True,
            "h5_hash_reused_from_consumed_v3_terminal": True,
            "h5_hash_by_prepare": False,
            "h5_hash_owner": "single_combined_v4_attempt",
            "static_and_kabsch_same_attempt": True,
            "snapshot_json": "not written; in-process frame stream",
            "nested_ledger_owner": "forbidden",
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
        "consumed_v3_source": {"bundle": str(bundle_path), "request": str(request_path), "bundle_sha256": sha256(bundle_path), "request_sha256": sha256(request_path)},
        "consumed_v2_failure": v3_bundle.get("consumed_v2_failure"),
        "canonical_ready": False,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "launch": False,
        "launch_allowed": False,
        "execution_allowed": False,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "physical_fate": "UNKNOWN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "launch_commit": git_head(),
        "request_note": "Forward v4 consumes immutable prepared v3 source rows, fixes the v3 conversion contract before worker entry, and binds shared v6 runtime/dispatch/strict/batch sources. Do not launch until the parent confirms the corrected v6 guard commit; one outer v6 attempt owns both H5 pre/post hashes around static plus Kabsch reads.",
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
        "launch_allowed": False,
        "shared_runtime": "v6",
    }

def direct_case_v4(row: dict[str, Any]) -> dict[str, Any]:
    """Use v2's tested H5/Kabsch implementation after v4 contract loading."""
    conversion = load_conversion(row)
    enriched = copy.deepcopy(row)
    # This object exists only in memory after exact v4 contract validation; it
    # is never accepted from or written back into the bundle.
    enriched["conversion"] = conversion
    result = v2.direct_case(enriched)
    result["conversion_contract"] = row["conversion_contract"]
    result["conversion_object_source"] = "loaded_from_exact_v4_report_binding_in_worker"
    return result


def run(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path, bundle = read_json(manifest_path, "F6 combined v4 bundle")
    if bundle.get("schema") != V4_BUNDLE_SCHEMA or bundle.get("status") != "PREPARED_COMBINED_V4_H5_SOURCE_BOUND":
        raise CombinedV4Error("combined v4 bundle is not prepared")
    if bundle.get("execution_contract", {}).get("conversion_object_in_row") is not False:
        raise CombinedV4Error("v4 bundle does not forbid unbound conversion objects")
    if bundle.get("runtime_stack", {}).get("shared_v6_runtime", {}).get("path") != str(RUNTIME_V6.resolve()):
        raise CombinedV4Error("v4 bundle is not bound to shared v6 runtime")
    if bundle.get("runtime_stack", {}).get("v6_entry_is_the_only_ledger_owner") is not True:
        raise CombinedV4Error("v4 bundle does not require one shared v6 ledger owner")
    rows = bundle.get("source_cases")
    if not isinstance(rows, list) or {row.get("physical_case_id") for row in rows} != set(EXPECTED_IDS):
        raise CombinedV4Error("combined v4 worker does not cover exact F6 pair")
    results = [direct_case_v4(row) for row in rows]
    result = {
        "schema": V4_OUTPUT_SCHEMA,
        "status": "completed",
        "bundle": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
        "consumed_v2_failure": bundle.get("consumed_v2_failure"),
        "cases": results,
        "runtime_binding_expected": bundle["runtime_binding"],
        "h5_hash_coverage": bundle["hash_ownership"],
        "source_policy": {
            "h5_opened": True,
            "h5_open_mode": "one_handle_per_case_shared_static_and_kabsch",
            "h5_rehashed_by_worker": False,
            "h5_pre_post_owner": "shared_runtime_v6",
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
    manifest_path, bundle = read_json(manifest_path, "F6 combined v4 bundle")
    output_path, result = read_json(output_path, "F6 combined v4 output")
    receipt_path, receipt = read_json(receipt_path, "F6 combined v4 execution receipt")
    if bundle.get("schema") != V4_BUNDLE_SCHEMA or result.get("schema") != V4_OUTPUT_SCHEMA:
        raise CombinedV4Error("v4 schema mismatch")
    if result.get("status") != "completed" or receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise CombinedV4Error("v4 output/receipt is not completed code 0")
    if receipt.get("request", {}).get("case_id") != REQUEST_CASE or receipt.get("request", {}).get("attempt_id") != REQUEST_ATTEMPT:
        raise CombinedV4Error("v4 receipt request identity differs")
    runtime = bundle["runtime_binding"]
    if receipt.get("runner_source") != runtime["path"] or receipt.get("runner_sha256") != runtime["sha256"]:
        raise CombinedV4Error("execution receipt is not from bound Stage2 v6 runtime")
    request = receipt.get("request", {})
    if request.get("shared_runtime_version") != "v6":
        raise CombinedV4Error("execution receipt request is not shared runtime v6")
    if request.get("runtime_binding") != runtime:
        raise CombinedV4Error("execution receipt request runtime binding differs from bundle")
    for field, stack_key in (("dispatch_binding", "shared_v6_dispatch"),
                             ("strict_dispatch_binding", "shared_v6_strict_dispatch")):
        if request.get(field) != bundle.get("runtime_stack", {}).get(stack_key):
            raise CombinedV4Error(f"execution receipt request {field} differs from bundle")
    input_files = {str(Path(path).resolve()) for path in request.get("input_files", [])}
    declared = request.get("input_sha256", {})
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    expected_files = set(str(Path(path).resolve()) for path in bundle.get("guard_input_files", []))
    expected_files.add(str(manifest_path.resolve()))
    if not expected_files <= input_files:
        raise CombinedV4Error("runtime request omits a v4 source input")
    for key in expected_files:
        expected = declared.get(key)
        if not expected or launch.get(key) != expected or finish.get(key) != expected:
            raise CombinedV4Error(f"runtime receipt lacks stable v4 source binding: {key}")
    for row in bundle["source_cases"]:
        validate_v4_row_shape(row)
        h5 = row["trajectory_h5"]
        key = str(Path(h5["path"]).resolve())
        if key not in input_files or declared.get(key) != h5["sha256"] or launch.get(key) != h5["sha256"] or finish.get(key) != h5["sha256"]:
            raise CombinedV4Error(f"runtime receipt lacks stable pre/post H5 binding: {key}")
        contract = row["conversion_contract"]
        if contract["output_hdf5"]["sha256"] != h5["sha256"]:
            raise CombinedV4Error(f"v4 conversion/H5 contract differs: {key}")
    if {row.get("physical_case_id") for row in result.get("cases", [])} != set(EXPECTED_IDS):
        raise CombinedV4Error("v4 output has wrong case union")
    for row in result["cases"]:
        if row.get("h5_read_ledger", {}).get("opened_once") is not True:
            raise CombinedV4Error(f"{row.get('physical_case_id')} lacks one-open ledger")
        if row.get("static", {}).get("trajectory", {}).get("frame_datasets_read") is not True:
            raise CombinedV4Error(f"{row.get('physical_case_id')} did not record frame reads")
        if row.get("kabsch", {}).get("status") != "completed":
            raise CombinedV4Error(f"{row.get('physical_case_id')} lacks Kabsch result")
        if row.get("kabsch", {}).get("frozen_contract", {}).get("so3_error_tolerances_deg") != {"rmse": SO3_RMSE_DEG, "max": SO3_MAX_DEG}:
            raise CombinedV4Error("v4 SO3 tolerance contract differs")
        if row.get("conversion_object_source") != "loaded_from_exact_v4_report_binding_in_worker":
            raise CombinedV4Error("v4 output lacks exact conversion contract provenance")
    checked = {
        "schema": V4_VALIDATION_SCHEMA,
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
    prep.add_argument("--v3-bundle", type=Path, default=V3_BUNDLE_DEFAULT)
    prep.add_argument("--v3-request", type=Path, default=V3_REQUEST_DEFAULT)
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
            result = prepare(args.v3_bundle, args.v3_request, args.output_manifest, args.output_request)
        elif args.action == "run":
            result = run(args.manifest, args.output)
        else:
            result = validate(args.manifest, args.output, args.receipt)
    except CombinedV4Error as exc:
        raise SystemExit(f"CombinedV4Error: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
