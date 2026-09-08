#!/usr/bin/env python3
"""N4 same-CFL matrix completion and h10 difference diagnostics.

The N4 plan has two deliberately separate states: CPU-side preparation and
analysis may run while the owner budget is pending; a new solver attempt is
refused unless the caller supplies explicit owner-approval evidence.  The
runner is limited to the four missing h09/h11 coarse/medium cells and reuses
the five completed N3 cells without relabelling old-CFL data.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Sequence
import uuid
import xml.etree.ElementTree as ET

import h5py
import numpy as np

try:
    from scripts import r6_n2_campaign as r6
    from scripts import r6_n3_bridge as n3_bridge
    from scripts import r6_n3_followup as n3_endpoint
    from scripts.boundary_sidecars import read_binary_vtk_polydata, write_sidecar
    from scripts.campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from scripts.r5_f1_solver_gate import WALL_SPECS
    from scripts.trajectory_io import convert_streaming
    from scripts.w02_semantics import partvtk_csv
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import r6_n2_campaign as r6
    import r6_n3_bridge as n3_bridge
    import r6_n3_followup as n3_endpoint
    from boundary_sidecars import read_binary_vtk_polydata, write_sidecar
    from campaign_runner import execute_attempt, query_gpus, require_idle_allowed_gpu
    from r5_f1_solver_gate import WALL_SPECS
    from trajectory_io import convert_streaming
    from w02_semantics import partvtk_csv


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "v0.1-candidate"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
GENCASE = BIN / "GenCase_linux64"
SOLVER = BIN / "DualSPHysics5.4_linux64"
SOURCE_DEFINITION = n3_endpoint.SOURCE_DEFINITION

CASE_ROOT = CAMPAIGN / "cases" / "n4-f1-same-cfl"
ARTIFACT_ROOT = CAMPAIGN / "artifacts" / "n4-f1-same-cfl"
RUN_ROOT = CAMPAIGN / "runs" / "n4-f1-same-cfl"
DATA_ROOT = CAMPAIGN / "data" / "n4-f1-same-cfl"
SIDECAR_ROOT = CAMPAIGN / "sidecars" / "n4-f1-same-cfl"

MATRIX_REPORT = CAMPAIGN / "N4-COMPARABLE-MATRIX.json"
MATRIX_MARKDOWN = CAMPAIGN / "N4-COMPARABLE-MATRIX.md"
DIFFERENCE_REPORT = CAMPAIGN / "N4-H10-DIFFERENCE.json"
DIFFERENCE_MARKDOWN = CAMPAIGN / "N4-H10-DIFFERENCE.md"
RESOURCE_REPORT = CAMPAIGN / "N4-RESOURCE-LEDGER.json"
DECISION_REPORT = CAMPAIGN / "N4-DECISION.json"
DECISION_MARKDOWN = CAMPAIGN / "N4-DECISION.md"
APPROVAL_RECORD = CAMPAIGN / "N4-OWNER-APPROVAL.json"
OWNER_APPROVAL_ORIGINAL = CAMPAIGN / "N4-OWNER-APPROVAL-ORIGINAL.md"
BATCH_LOCK_FILE = RUN_ROOT / ".n4-batch.lock"
HANDOFF_MARKDOWN = CAMPAIGN / "N4-LATEST-HANDOFF.md"
REVIEW_PACKET_MARKDOWN = CAMPAIGN / "N4-REVIEW-PACKET.md"

GPU_IDS = (4, 5, 6, 7)
PROTECTED_GPU_IDS = (0, 1, 2, 3)
HEIGHTS_M = {"h09": 0.414, "h10": 0.460, "h11": 0.506}
DP_M = {"coarse": 0.035, "medium": 0.024, "fine": 0.014}
CFL_NUMBER = 0.1
TIME_MAX_S = 1.5
TIME_OUT_S = 0.001
REGISTERED_TIMES_S = tuple(float(value) for value in np.linspace(0.0, TIME_MAX_S, 21))
MAX_NEW_SOLVER_ATTEMPTS = 4
PROPOSED_GPU_HOURS = 0.5
PROPOSED_GPU_SECONDS = PROPOSED_GPU_HOURS * 3600.0
# Leave a small accounting margin below the owner-proposed cap.  Four
# concurrent attempts can therefore never consume more than the 0.5 GPU-hour
# budget even when the timeout boundary and wall-clock sampling have jitter.
SOLVER_ATTEMPT_TIMEOUT_SECONDS = (PROPOSED_GPU_SECONDS / MAX_NEW_SOLVER_ATTEMPTS) * 0.98
BASELINE_COMMIT = "d721473f524c71bd85ba88064f66026de8306989"
SOURCE_RECIPE_ID = "N4_F1_plain_dam_break_cfl010_v1"
AUTHORIZATION_REFERENCE_COMMIT = "6db8158"

NEW_CASES = (
    ("N4_F1_plain_h09_coarse_cfl010", "h09", "coarse", 4),
    ("N4_F1_plain_h09_medium_cfl010", "h09", "medium", 5),
    ("N4_F1_plain_h11_coarse_cfl010", "h11", "coarse", 6),
    ("N4_F1_plain_h11_medium_cfl010", "h11", "medium", 7),
)

REUSED_CASES = (
    ("h09", "fine", "R6_N3_F1_plain_dam_break_h09_fine_cfl010", "r6-n3-endpoint"),
    ("h10", "coarse", "R6_N3_F1_plain_dam_break_h10_coarse_cfl010", "r6-n3-bridge"),
    ("h10", "medium", "R6_N3_F1_plain_dam_break_h10_medium_cfl010", "r6-n3-bridge"),
    ("h10", "fine", "R6_N3_F1_plain_dam_break_h10_fine_cfl010", "r6-n3-bridge"),
    ("h11", "fine", "R6_N3_F1_plain_dam_break_h11_fine_cfl010", "r6-n3-endpoint"),
)


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(LAB.resolve()))
    except ValueError:
        return str(path.resolve())


def lab_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else LAB / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=True) + "\n")
    os.replace(temporary, path)


def read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def git_value(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=LAB.parent, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def environment(*, cpu: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    if cpu:
        env["OMP_NUM_THREADS"] = "1"
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
    return env


def allowed_uuids() -> list[str]:
    inventory = read_json(CAMPAIGN / "w00-inventory.json", {})
    return list(inventory.get("execution_policy", {}).get("allowed_gpu_uuids", []))


def records() -> list[dict[str, Any]]:
    result = []
    for case_id, height_label, resolution, gpu in NEW_CASES:
        result.append({
            "case_id": case_id,
            "family": "F1",
            "background_id": "plain_dam_break",
            "mechanism": "collapse-runup-return",
            "height_label": height_label,
            "height_m": HEIGHTS_M[height_label],
            "continuous_initial_fluid_z_bounds_m": list(r6.SOURCE_Z_BOUNDS_BY_HEIGHT[height_label]),
            "resolution": resolution,
            "dp_m": DP_M[resolution],
            "cfl_number": CFL_NUMBER,
            "time_max_s": TIME_MAX_S,
            "time_out_s": TIME_OUT_S,
            "source_definition": str(SOURCE_DEFINITION),
            "gpu": gpu,
            "registered_absorbing_exit_faces": [],
            "wall_spec": WALL_SPECS["plain_dam_break"],
            "source_recipe_id": SOURCE_RECIPE_ID,
        })
    return result


def record_hash(record: dict[str, Any]) -> str:
    stable = {
        key: value for key, value in record.items()
        if key not in {
            "candidate_definition", "generated_prefix", "record_hash",
            "candidate_definition_sha256", "generated_xml_sha256", "generated_bi4_sha256", "gencase",
        }
    }
    stable["source_definition_sha256"] = sha256(SOURCE_DEFINITION)
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fluid_drawbox(root: ET.Element) -> ET.Element:
    fluid_seen = False
    for node in root.iter():
        if node.tag == "setmkfluid":
            fluid_seen = True
        elif fluid_seen and node.tag == "drawbox":
            if (node.findtext("./boxfill") or "").strip() == "solid":
                return node
    raise ValueError("could not locate initial fluid drawbox")


def _set_parameter(root: ET.Element, key: str, value: Any) -> None:
    parent = root.find(".//execution/parameters")
    if parent is None:
        raise ValueError("source definition has no execution/parameters")
    node = parent.find(f"./parameter[@key='{key}']")
    if node is None:
        node = ET.SubElement(parent, "parameter", key=key)
    node.set("value", str(value))


def load_matrix_report() -> dict[str, Any]:
    return read_json(MATRIX_REPORT, {
        "schema_version": "n4-comparable-matrix-v1",
        "round": "N4",
        "baseline_commit": BASELINE_COMMIT,
        "source_recipe_id": SOURCE_RECIPE_ID,
        "execution_status": "awaiting_owner_budget_approval",
        "formal_release": False,
        "development_authorized": False,
        "authorization": {
            "owner_budget_status": "pending_owner_approval",
            "owner_approval_evidence": None,
            "authorization_reference_commit": AUTHORIZATION_REFERENCE_COMMIT,
            "owner_approval_original": relpath(OWNER_APPROVAL_ORIGINAL),
            "new_solver_authorized": False,
            "additional_gpu_hours_cap_proposed": PROPOSED_GPU_HOURS,
            "maximum_new_solver_attempts": MAX_NEW_SOLVER_ATTEMPTS,
            "failed_attempts_consume_budget": True,
        },
    })


def _approval_record(evidence: str) -> dict[str, Any]:
    source = "inline"
    text = evidence.strip()
    try:
        candidate = Path(text)
        if candidate.is_file():
            source = relpath(candidate.resolve())
            text = candidate.read_text(errors="replace").strip()
    except OSError:
        pass
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "owner approval must be a JSON object or a path to one; it must "
            "explicitly bind the exact N4 scope"
        ) from error
    expected = {
        "schema_version": "n4-owner-approval-v1",
        "owner": str,
        "decision": "approve",
        "authorization_reference_commit": AUTHORIZATION_REFERENCE_COMMIT,
        "gpu_hours_max": PROPOSED_GPU_HOURS,
        "solver_attempts_max": MAX_NEW_SOLVER_ATTEMPTS,
        "case_ids": [item[0] for item in NEW_CASES],
        "gpu_indices": list(GPU_IDS),
        "recipe_id": SOURCE_RECIPE_ID,
        "baseline_commit": BASELINE_COMMIT,
        "failed_attempts_consume_budget": True,
        "formal_release": False,
        "development_authorized": False,
        "g4": "not_launched",
    }
    if not isinstance(payload, dict) or set(payload) != set(expected):
        raise RuntimeError("owner approval JSON has extra or missing scope fields")
    for key, value in expected.items():
        if value is str:
            if not isinstance(payload.get(key), str) or not payload[key].strip():
                raise RuntimeError(f"owner approval field {key!r} must be non-empty text")
        elif payload.get(key) != value:
            raise RuntimeError(f"owner approval field {key!r} is not the exact N4 scope")
    canonical_text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical_text.encode()).hexdigest()
    if not OWNER_APPROVAL_ORIGINAL.is_file():
        raise RuntimeError(
            f"exact owner authorization original is missing: {relpath(OWNER_APPROVAL_ORIGINAL)}"
        )
    return {
        "schema_version": "n4-owner-approval-v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE_COMMIT,
        "authorization_reference_commit": AUTHORIZATION_REFERENCE_COMMIT,
        "evidence_source": source,
        "evidence_text": canonical_text,
        "evidence_sha256": digest,
        "original_authorization": {
            "path": relpath(OWNER_APPROVAL_ORIGINAL),
            "sha256": sha256(OWNER_APPROVAL_ORIGINAL),
        },
        "scope": {
            "gpu_hours_max": PROPOSED_GPU_HOURS,
            "gpu_seconds_max": PROPOSED_GPU_SECONDS,
            "solver_attempts_max": MAX_NEW_SOLVER_ATTEMPTS,
            "case_ids": [item[0] for item in NEW_CASES],
            "gpu_indices": list(GPU_IDS),
            "recipe_id": SOURCE_RECIPE_ID,
            "baseline_commit": BASELINE_COMMIT,
            "authorization_reference_commit": AUTHORIZATION_REFERENCE_COMMIT,
        },
    }


@contextmanager
def _exclusive_batch_lock():
    BATCH_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = BATCH_LOCK_FILE.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("an N4 solver batch is already active") from error
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _with_exclusive_batch_lock(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _exclusive_batch_lock():
            return function(*args, **kwargs)
    return wrapped


def _validate_prepared_for_launch(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical = {item["case_id"]: item for item in records()}
    supplied = {item.get("case_id"): item for item in prepared}
    if set(supplied) != set(canonical) or len(prepared) != len(canonical):
        raise RuntimeError("N4 launch set must be exactly the four canonical h09/h11 coarse/medium cells")
    validated: list[dict[str, Any]] = []
    for case_id in [item[0] for item in NEW_CASES]:
        expected = canonical[case_id]
        actual = supplied.get(case_id)
        expected_hash = record_hash(expected)
        if actual is None or actual.get("record_hash") != expected_hash or record_hash(actual) != expected_hash:
            raise RuntimeError(f"N4 launch record hash mismatch for {case_id}")
        expected_candidate = CASE_ROOT / case_id / f"{case_id}_Def.xml"
        expected_prefix = ARTIFACT_ROOT / case_id / "generated" / case_id
        candidate = lab_path(actual.get("candidate_definition", ""))
        prefix = lab_path(actual.get("generated_prefix", ""))
        if candidate.resolve() != expected_candidate.resolve() or prefix.resolve() != expected_prefix.resolve():
            raise RuntimeError(f"N4 launch paths are not canonical for {case_id}")
        generated_xml = prefix.with_suffix(".xml")
        generated_bi4 = prefix.with_suffix(".bi4")
        if not candidate.is_file() or not generated_xml.is_file() or not generated_bi4.is_file():
            raise RuntimeError(f"N4 launch artifacts are missing for {case_id}")
        if actual.get("candidate_definition_sha256") != sha256(candidate):
            raise RuntimeError(f"N4 candidate definition hash mismatch for {case_id}")
        if actual.get("generated_xml_sha256") != sha256(generated_xml):
            raise RuntimeError(f"N4 generated XML hash mismatch for {case_id}")
        if actual.get("generated_bi4_sha256") != sha256(generated_bi4):
            raise RuntimeError(f"N4 generated BI4 hash mismatch for {case_id}")
        validated.append(actual)
    return validated


def _durable_attempt_summary() -> dict[str, Any]:
    entries = []
    if RUN_ROOT.is_dir():
        for case_dir in sorted(RUN_ROOT.iterdir()):
            attempts_dir = case_dir / "attempts"
            if not attempts_dir.is_dir():
                continue
            for attempt_dir in sorted(attempts_dir.iterdir()):
                if not attempt_dir.is_dir() or not attempt_dir.name.endswith((".complete", ".failed", ".partial")):
                    continue
                payload = read_json(attempt_dir / "attempt.json", {})
                suffix_status = (
                    "completed" if attempt_dir.name.endswith(".complete") else
                    "failed" if attempt_dir.name.endswith(".failed") else "running"
                )
                entries.append({
                    "case_id": payload.get("case_id", case_dir.name),
                    "attempt_id": payload.get("attempt_id", attempt_dir.name.rsplit(".", 1)[0]),
                    "status": payload.get("status", suffix_status),
                    "directory": str(attempt_dir),
                    "elapsed_seconds": payload.get("elapsed_seconds"),
                })
    completed = [item for item in entries if item["status"] == "completed"]
    failed = [item for item in entries if item["status"] == "failed"]
    return {
        "attempts_started": len(entries),
        "attempts_completed": len(completed),
        "attempts_failed": len(failed),
        "partial_attempts": sum(item["status"] == "running" for item in entries),
        "device_seconds": sum(float(item.get("elapsed_seconds") or 0.0) for item in entries),
        "entries": entries,
    }


def prepare_one(record: dict[str, Any]) -> dict[str, Any]:
    case_id = record["case_id"]
    case_dir = CASE_ROOT / case_id
    generated_dir = ARTIFACT_ROOT / case_id / "generated"
    case_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    candidate = case_dir / f"{case_id}_Def.xml"
    tree = ET.parse(SOURCE_DEFINITION)
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    if definition is None:
        raise ValueError("plain source has no geometry definition")
    definition.set("dp", str(record["dp_m"]))
    _fluid_drawbox(root).find("./size").set("z", str(record["height_m"]))
    cfl = root.find(".//constantsdef/cflnumber")
    if cfl is None:
        raise ValueError("plain source has no cflnumber")
    cfl.set("value", str(record["cfl_number"]))
    for key, value in (("SavePosDouble", 2), ("StepAlgorithm", 1), ("VerletSteps", 40),
                       ("Boundary", 1), ("Shifting", 0), ("TimeMax", TIME_MAX_S),
                       ("TimeOut", TIME_OUT_S)):
        _set_parameter(root, key, value)
    ET.indent(tree, space="    ")
    tree.write(candidate, encoding="utf-8", xml_declaration=True)
    prefix = generated_dir / case_id
    started = time.perf_counter()
    process = subprocess.run(
        [str(GENCASE), str(candidate.with_suffix("")), str(prefix), "-save:all"],
        cwd=generated_dir, env=environment(cpu=True), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    elapsed = time.perf_counter() - started
    stdout_path = generated_dir / "gencase.stdout.log"
    stdout_path.write_text(process.stdout)
    if process.returncode != 0 or not prefix.with_suffix(".xml").is_file() or not prefix.with_suffix(".bi4").is_file():
        raise RuntimeError(f"GenCase failed for {case_id}: {process.stdout[-1500:]}")
    match = re.search(r"Fluid\.{3,}:\s*([0-9,]+)", process.stdout)
    return {
        **record,
        "candidate_definition": relpath(candidate),
        "candidate_definition_sha256": sha256(candidate),
        "generated_prefix": relpath(prefix),
        "generated_xml_sha256": sha256(prefix.with_suffix(".xml")),
        "generated_bi4_sha256": sha256(prefix.with_suffix(".bi4")),
        "gencase": {
            "returncode": process.returncode,
            "fluid_particles": int(match.group(1).replace(",", "")) if match else None,
            "elapsed_seconds": elapsed,
            "stdout": relpath(stdout_path),
        },
        "record_hash": record_hash(record),
    }


def prepare() -> list[dict[str, Any]]:
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(records())) as pool:
        prepared = list(pool.map(prepare_one, records()))
    report = load_matrix_report()
    report.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "preparation_status": "completed",
        "execution_status": "awaiting_owner_budget_approval",
        "prepared_cases": prepared,
        "preparation_elapsed_seconds": time.perf_counter() - started,
    })
    atomic_json(MATRIX_REPORT, report)
    return prepared


def latest_attempt(record: dict[str, Any]) -> Path | None:
    latest = RUN_ROOT / record["case_id"] / "latest.json"
    if not latest.is_file():
        return None
    payload = read_json(latest, {})
    try:
        attempt = Path(payload["attempt_directory"])
    except (KeyError, TypeError):
        return None
    if not attempt.is_dir() or not attempt.name.endswith(".complete"):
        return None
    if payload.get("record_hash") and payload["record_hash"] != record_hash(record):
        return None
    attempts_dir = RUN_ROOT / record["case_id"] / "attempts"
    if attempts_dir.is_dir():
        newer_failures = [
            item for item in attempts_dir.iterdir()
            if item.is_dir() and item.name > attempt.name and item.name.endswith((".failed", ".partial"))
        ]
        if newer_failures:
            return None
    return attempt


def _current_successful_attempt(record: dict[str, Any]) -> Path | None:
    report = load_matrix_report()
    run = next((item for item in report.get("solver_runs", []) if item.get("case_id") == record["case_id"]), None)
    if run is None or run.get("execution_status") not in {"completed", "reused_completed"}:
        return None
    if run.get("record_hash") != record_hash(record):
        return None
    attempt = latest_attempt(record)
    if attempt is None:
        return None
    if run.get("attempt_directory") and Path(run["attempt_directory"]).resolve() != attempt.resolve():
        return None
    return attempt


def _approval_guard(evidence: str | None) -> str:
    if not evidence or not evidence.strip():
        raise RuntimeError(
            "N4 new solver is blocked: supply --owner-approval-evidence with explicit "
            "owner authorization for at most 0.5 GPU-hours / 4 attempts"
        )
    approval = _approval_record(evidence)
    report = load_matrix_report()
    authorization = report.setdefault("authorization", {})
    authorization.update({
        "owner_budget_status": "approved_for_bounded_n4",
        "owner_approval_evidence": approval["evidence_text"],
        "owner_approval_evidence_sha256": approval["evidence_sha256"],
        "authorization_reference_commit": AUTHORIZATION_REFERENCE_COMMIT,
        "owner_approval_original": approval["original_authorization"]["path"],
        "owner_approval_original_sha256": approval["original_authorization"]["sha256"],
        "owner_approval_record": relpath(APPROVAL_RECORD),
        "new_solver_authorized": True,
        "additional_gpu_hours_cap_proposed": PROPOSED_GPU_HOURS,
        "maximum_new_solver_attempts": MAX_NEW_SOLVER_ATTEMPTS,
    })
    report["authorization"] = authorization
    atomic_json(APPROVAL_RECORD, approval)
    atomic_json(MATRIX_REPORT, report)
    return approval["evidence_text"]


def run_one(record: dict[str, Any], *, gpu_record: dict[str, Any] | None = None, rerun: bool = False) -> dict[str, Any]:
    latest = RUN_ROOT / record["case_id"] / "latest.json"
    expected_hash = record_hash(record)
    if latest.is_file() and not rerun:
        payload = read_json(latest, {})
        if payload.get("status") == "completed" and payload.get("record_hash") == expected_hash:
            return {**payload, "execution_status": "reused_completed", "attempt_started": False}
    gpu = int(record["gpu"])
    if gpu_record is None:
        gpu_record = require_idle_allowed_gpu(gpu, allowed_uuids())
    prefix = lab_path(record["generated_prefix"])
    result = execute_attempt(
        record["case_id"], [str(SOLVER), f"-gpu:{gpu}", str(prefix), "{output}"], RUN_ROOT,
        cwd=prefix.parent, env=environment(), evidence_glob="data/Part_*.bi4",
        required_text="Finished execution (code=0)",
        timeout_seconds=SOLVER_ATTEMPT_TIMEOUT_SECONDS,
    )
    attempt_directory = Path(result["attempt_directory"])
    attempt_manifest = attempt_directory / "attempt.json"
    generated_xml_sha256 = sha256(prefix.with_suffix(".xml"))
    generated_bi4_sha256 = sha256(prefix.with_suffix(".bi4"))
    authorization = load_matrix_report().get("authorization", {})
    approval_sha256 = authorization.get("owner_approval_evidence_sha256")
    approval_original_sha256 = authorization.get("owner_approval_original_sha256")
    manifest = read_json(attempt_manifest, {})
    manifest.update({
        "record_hash": expected_hash,
        "owner_approval_evidence_sha256": approval_sha256,
        "owner_approval_original_sha256": approval_original_sha256,
        "input_generated_xml_sha256": generated_xml_sha256,
        "input_generated_bi4_sha256": generated_bi4_sha256,
    })
    atomic_json(attempt_manifest, manifest)
    payload = {
        **result,
        "record_hash": expected_hash,
        "source_recipe_id": SOURCE_RECIPE_ID,
        "execution_status": "completed" if result.get("status") == "completed" else "solver_failed",
        "gpu_at_launch": gpu_record,
        "gpu_index_requested": gpu,
        "protected_gpu_indices": list(PROTECTED_GPU_IDS),
        "input_generated_xml_sha256": generated_xml_sha256,
        "input_generated_bi4_sha256": generated_bi4_sha256,
        "owner_approval_evidence_sha256": approval_sha256,
        "owner_approval_original_sha256": approval_original_sha256,
        "device_seconds_accounting": "solver_wall_elapsed_seconds_proxy",
        "device_seconds": result.get("elapsed_seconds"),
        "attempt_timeout_seconds": SOLVER_ATTEMPT_TIMEOUT_SECONDS,
        "attempt_sha256": sha256(attempt_manifest) if attempt_manifest.is_file() else None,
    }
    payload["attempt_started"] = True
    if result.get("status") == "completed":
        atomic_json(RUN_ROOT / record["case_id"] / "latest.json", payload)
    return payload


def _solver_result_accounting(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    started = [item for item in results if item.get("attempt_started", item.get("execution_status") != "reused_completed")]
    completed = [item for item in started if item.get("execution_status") == "completed"]
    failed = [item for item in started if item.get("execution_status") == "solver_failed"]
    return {
        "attempts_started": len(started),
        "attempts_completed": len(completed),
        "attempts_failed": len(failed),
        "device_seconds": sum(float(item.get("device_seconds") or 0.0) for item in started),
    }


def _persist_solver_batch(
    base_ledger: dict[str, Any],
    batch: dict[str, Any],
    results: Sequence[dict[str, Any]],
    *,
    status: str,
    resource_snapshot: Any = None,
) -> dict[str, Any]:
    report = load_matrix_report()
    authorization = report.get("authorization", {})
    approval_sha256 = authorization.get("owner_approval_evidence_sha256")
    approval_original_sha256 = authorization.get("owner_approval_original_sha256")
    if not approval_sha256:
        raise RuntimeError("N4 approval digest is missing; refusing to launch")
    if batch.get("owner_approval_evidence_sha256") != approval_sha256:
        raise RuntimeError("N4 batch approval digest does not match the authorized record")
    if batch.get("owner_approval_original_sha256") != approval_original_sha256:
        raise RuntimeError("N4 batch original-authorization digest does not match the authorized record")
    result_accounting = _solver_result_accounting(results)
    durable = _durable_attempt_summary()
    started = max(
        int(base_ledger.get("solver_attempts_started", 0)) + result_accounting["attempts_started"],
        durable["attempts_started"],
    )
    completed = max(
        int(base_ledger.get("solver_attempts_completed", 0)) + result_accounting["attempts_completed"],
        durable["attempts_completed"],
    )
    failed = max(
        int(base_ledger.get("solver_attempts_failed", 0)) + result_accounting["attempts_failed"],
        durable["attempts_failed"],
    )
    device_seconds = max(
        float(base_ledger.get("solver_device_seconds", 0.0)) + result_accounting["device_seconds"],
        durable["device_seconds"],
    )
    report.update({
        "solver_runs": list(results),
        "solver_batch": {
            **batch,
            "status": status,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "results_recorded": len(results),
            "durable_attempt_summary": durable,
        },
        "resource_ledger": {
            **base_ledger,
            "solver_attempts_started": started,
            "solver_attempts_completed": completed,
            "solver_attempts_failed": failed,
            "solver_device_seconds": device_seconds,
            "gpu_seconds_cap": PROPOSED_GPU_SECONDS,
            "solver_attempt_timeout_seconds": SOLVER_ATTEMPT_TIMEOUT_SECONDS,
        },
    })
    if status == "running":
        report["execution_status"] = "solver_running"
    elif status == "completed":
        report["execution_status"] = "completed"
    elif status in {"completed_with_findings", "resource_cap_exceeded", "interrupted"}:
        report["execution_status"] = "completed_with_findings"
    if resource_snapshot is not None:
        report["resource_snapshot_after_solver"] = resource_snapshot
    atomic_json(MATRIX_REPORT, report)
    return report


@_with_exclusive_batch_lock
def run_solver(prepared: Sequence[dict[str, Any]], *, evidence: str, rerun: bool = False) -> list[dict[str, Any]]:
    active_batch = load_matrix_report().get("solver_batch", {})
    if active_batch.get("status") in {"reserved", "running"}:
        raise RuntimeError("an active N4 solver batch is already recorded; reconcile it before relaunch")
    _approval_guard(evidence)
    prepared = _validate_prepared_for_launch(prepared)
    if len(prepared) != MAX_NEW_SOLVER_ATTEMPTS:
        raise ValueError("N4 solver phase must contain exactly the four planned cells")
    report = load_matrix_report()
    approval_sha256 = report.get("authorization", {}).get("owner_approval_evidence_sha256")
    approval_original_sha256 = report.get("authorization", {}).get("owner_approval_original_sha256")
    if not approval_sha256:
        raise RuntimeError("N4 approval digest is missing; refusing to launch")
    resource_ledger = report.get("resource_ledger", {})
    previous = int(resource_ledger.get("solver_attempts_started", resource_ledger.get("new_solver_attempts_started", 0)))
    previous_completed = int(resource_ledger.get("solver_attempts_completed", resource_ledger.get("new_solver_attempts_completed", 0)))
    previous_failed = int(resource_ledger.get("solver_attempts_failed", resource_ledger.get("new_solver_attempts_failed", 0)))
    previous_seconds = float(resource_ledger.get("solver_device_seconds", resource_ledger.get("new_solver_device_seconds", 0.0)))
    durable = _durable_attempt_summary()
    previous = max(previous, int(durable["attempts_started"]))
    previous_completed = max(previous_completed, int(durable["attempts_completed"]))
    previous_failed = max(previous_failed, int(durable["attempts_failed"]))
    previous_seconds = max(previous_seconds, float(durable["device_seconds"]))
    if durable["partial_attempts"]:
        raise RuntimeError("N4 has durable partial attempts; reconcile them before any new batch")
    if previous + len(prepared) > MAX_NEW_SOLVER_ATTEMPTS:
        raise RuntimeError("N4 attempt cap would be exceeded; failed attempts count")
    if previous_seconds >= PROPOSED_GPU_SECONDS:
        raise RuntimeError("N4 GPU-hour cap is already exhausted; no new attempt may start")
    allowed = allowed_uuids()
    # Validate the complete launch set before any solver starts.  This avoids
    # a partial four-way launch when one candidate GPU becomes busy between
    # the owner's approval and the execution command.
    preflight = [require_idle_allowed_gpu(int(item["gpu"]), allowed) for item in prepared]
    batch = {
        "batch_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8],
        "status": "reserved",
        "reserved_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_ids": [item["case_id"] for item in prepared],
        "gpu_indices": [item["gpu"] for item in prepared],
        "gpu_preflight": preflight,
        "starting_ledger": {
            "solver_attempts_started": previous,
            "solver_attempts_completed": previous_completed,
            "solver_attempts_failed": previous_failed,
            "solver_device_seconds": previous_seconds,
        },
        "gpu_seconds_cap": PROPOSED_GPU_SECONDS,
        "solver_attempt_timeout_seconds": SOLVER_ATTEMPT_TIMEOUT_SECONDS,
        "owner_approval_evidence_sha256": approval_sha256,
        "owner_approval_original_sha256": approval_original_sha256,
    }
    base_ledger = {
        **resource_ledger,
        "solver_attempts_started": previous,
        "solver_attempts_completed": previous_completed,
        "solver_attempts_failed": previous_failed,
        "solver_device_seconds": previous_seconds,
    }
    # Reservation is durable before the first solver process is launched.
    report.update({"solver_batch": batch, "resource_ledger": base_ledger, "gpu_preflight_before_launch": preflight})
    atomic_json(MATRIX_REPORT, report)
    batch["status"] = "running"
    results: list[dict[str, Any]] = []
    try:
        _persist_solver_batch(base_ledger, batch, results, status="running")
        with ThreadPoolExecutor(max_workers=len(prepared)) as pool:
            futures = {
                pool.submit(run_one, item, gpu_record=preflight[index], rerun=rerun): item
                for index, item in enumerate(prepared)
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                except Exception as error:
                    result = {
                        "case_id": item["case_id"],
                        "execution_status": "solver_exception",
                        "attempt_started": False,
                        "error": repr(error),
                    }
                results.append(result)
                _persist_solver_batch(base_ledger, batch, results, status="running")
    except BaseException:
        _persist_solver_batch(base_ledger, batch, results, status="interrupted")
        raise
    result_accounting = _solver_result_accounting(results)
    total_device_seconds = max(
        previous_seconds + result_accounting["device_seconds"],
        _durable_attempt_summary()["device_seconds"],
    )
    if total_device_seconds > PROPOSED_GPU_SECONDS + 1e-6:
        _persist_solver_batch(base_ledger, batch, results, status="resource_cap_exceeded")
        raise RuntimeError(
            f"N4 GPU-hour cap exceeded: {total_device_seconds:.3f} device seconds "
            f"> {PROPOSED_GPU_SECONDS:.3f}"
        )
    try:
        snapshot = query_gpus()
    except Exception as error:
        snapshot = {"status": "query_failed", "error": repr(error)}
    _persist_solver_batch(
        base_ledger, batch, results,
        status="completed" if all(item.get("execution_status") in {"completed", "reused_completed"} for item in results) else "completed_with_findings",
        resource_snapshot=snapshot,
    )
    return results


def normalize_one(record: dict[str, Any]) -> dict[str, Any]:
    attempt = _current_successful_attempt(record)
    if attempt is None:
        return {"case_id": record["case_id"], "normalization_status": "blocked_missing_attempt"}
    output = DATA_ROOT / f"{record['case_id']}.h5"
    started = time.perf_counter()
    try:
        complete = False
        if output.is_file():
            with h5py.File(output, "r") as h5:
                complete = bool(h5.attrs.get("conversion_complete", True))
        if not complete:
            csv_paths = partvtk_csv(attempt / "data", attempt / "csv", "-all,+fluid")
            convert_streaming(
                {"id": record["case_id"], "family": "F1", "mechanism": record["mechanism"], "shifting": 0},
                csv_paths, output,
            )
        with h5py.File(output, "r+") as h5:
            h5.attrs["continuous_initial_fluid_z_bounds_m"] = np.asarray(record["continuous_initial_fluid_z_bounds_m"], dtype=np.float64)
            h5.attrs["r6_n3_cfl_number"] = float(record["cfl_number"])
            h5.attrs["n4_source_recipe_id"] = SOURCE_RECIPE_ID
            h5.attrs["n4_record_hash"] = record_hash(record)
            h5.attrs["source_definition_sha256"] = sha256(SOURCE_DEFINITION)
        prefix = lab_path(record["generated_prefix"])
        vtk = prefix.with_name(prefix.name + "_MkCells.vtk")
        sidecar = SIDECAR_ROOT / f"{record['case_id']}.h5"
        sidecar_summary = write_sidecar(
            sidecar, record["case_id"], output, read_binary_vtk_polydata(vtk),
            source_vtk_label=relpath(vtk), source_hdf5_label=relpath(output),
        )
        return {
            "case_id": record["case_id"],
            "normalization_status": "completed",
            "elapsed_seconds": time.perf_counter() - started,
            "hdf5": relpath(output),
            "hdf5_sha256": sha256(output),
            "sidecar": relpath(sidecar),
            "sidecar_sha256": sha256(sidecar),
            "sidecar_audit": sidecar_summary,
        }
    except Exception as error:
        return {"case_id": record["case_id"], "normalization_status": "failed", "elapsed_seconds": time.perf_counter() - started, "error": repr(error)}


def normalize(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    results = [normalize_one(item) for item in prepared]
    report = load_matrix_report()
    report["normalization"] = results
    report["normalization_status"] = "completed" if all(item.get("normalization_status") == "completed" for item in results) else "partial_with_findings"
    atomic_json(MATRIX_REPORT, report)
    return results


def _native_exclusion_reconciliation(audit: dict[str, Any], attempt: Path | None) -> dict[str, Any]:
    evidence = audit.get("solver_exclusion_evidence") or {}
    log_count = audit.get("excluded_particles_from_solver_log")
    rows = evidence.get("rows") or []
    if evidence.get("status") == "available":
        if log_count is None:
            return {
                "status": "failed",
                "reason": "solver_log_exclusion_count_missing",
                "partout_row_count": len(rows),
                "solver_log_exclusion_count": None,
            }
        if int(log_count) != len(rows):
            return {
                "status": "failed",
                "reason": "partout_rows_do_not_match_solver_log_count",
                "partout_row_count": len(rows),
                "solver_log_exclusion_count": int(log_count),
            }
        return {
            "status": "pass",
            "method": "PartOut_rows_reconciled_to_solver_log",
            "partout_row_count": len(rows),
            "solver_log_exclusion_count": int(log_count),
            "reason_counts": evidence.get("reason_counts", {}),
        }
    if (
        int(log_count or 0) == 0
        and attempt is not None
        and (attempt / "RunPARTs.csv").is_file()
    ):
        return {
            "status": "pass",
            "method": "RunPARTs_native_zero_exclusion_record",
            "partout_row_count": 0,
            "solver_log_exclusion_count": 0,
        }
    return {
        "status": "failed",
        "reason": "native_exclusion_or_zero_exclusion_evidence_unavailable",
        "partout_evidence_status": evidence.get("status", "unavailable"),
        "solver_log_exclusion_count": log_count,
    }


def _new_audits(prepared: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for record in prepared:
        path = DATA_ROOT / f"{record['case_id']}.h5"
        attempt = latest_attempt(record)
        started = time.perf_counter()
        if not path.is_file() or attempt is None:
            results.append({"case_id": record["case_id"], "r6_full_time_audit_status": "missing_input", "r6_hard_failures": ["normalized_hdf5_or_attempt_missing"], "audit_elapsed_seconds": time.perf_counter() - started})
            continue
        try:
            item = r6.full_time_audit(record, path, attempt)
            reconciliation = _native_exclusion_reconciliation(item, attempt)
            item["native_exclusion_reconciliation"] = reconciliation
            if reconciliation.get("status") != "pass":
                item.setdefault("r6_hard_failures", []).append("native_exclusion_evidence_not_reconciled")
                item["r6_hard_failures"] = sorted(set(item["r6_hard_failures"]))
                item["r6_full_time_audit_status"] = "failed_or_unknown"
            item["audit_elapsed_seconds"] = time.perf_counter() - started
            results.append(item)
        except Exception as error:
            results.append({"case_id": record["case_id"], "r6_full_time_audit_status": "audit_exception", "r6_hard_failures": [repr(error)], "audit_elapsed_seconds": time.perf_counter() - started})
    return results


def _n3_reports() -> tuple[dict[str, Any], dict[str, Any]]:
    return read_json(CAMPAIGN / "r6-n3-endpoint-closure.json", {}), read_json(CAMPAIGN / "r6-n3-bridge-h10.json", {})


def _reused_audit_map() -> dict[str, dict[str, Any]]:
    endpoint, bridge = _n3_reports()
    result = {}
    for item in [*endpoint.get("audits", []), *bridge.get("audits", [])]:
        if item.get("case_id"):
            result[item["case_id"]] = item
    return result


def _reused_provenance() -> dict[str, dict[str, Any]]:
    endpoint, bridge = _n3_reports()
    result: dict[str, dict[str, Any]] = {}
    for source_name, report in (("r6-n3-endpoint", endpoint), ("r6-n3-bridge", bridge)):
        prepared = {item.get("case_id"): item for item in report.get("prepared_cases", [])}
        runs = {item.get("case_id"): item for item in report.get("solver_runs", [])}
        normal = {item.get("case_id"): item for item in report.get("normalization", [])}
        for item in report.get("prepared_cases", []):
            case_id = item.get("case_id")
            if not case_id:
                continue
            run = runs.get(case_id, {})
            normalization = normal.get(case_id, {})
            attempt = Path(run["attempt_directory"]) if run.get("attempt_directory") else None
            attempt_json = attempt / "attempt.json" if attempt and (attempt / "attempt.json").is_file() else None
            generated_prefix = lab_path(item["generated_prefix"]) if item.get("generated_prefix") else None
            raw_files = sorted(attempt.glob("data/Part_*.bi4")) if attempt and attempt.is_dir() else []
            result[case_id] = {
                "case_id": case_id,
                "role": "reused_n3",
                "reuse": True,
                "source_report": source_name,
                "source_recipe_id": "R6_N3_F1_plain_dam_break_cfl010_v1",
                "height_label": item.get("height_label"),
                "height_m": item.get("height_m"),
                "resolution": item.get("resolution"),
                "dp_m": item.get("dp_m"),
                "cfl_number": item.get("cfl_number", 0.1),
                "candidate_definition": item.get("candidate_definition"),
                "candidate_definition_sha256": item.get("candidate_definition_sha256"),
                "generated_xml": relpath(generated_prefix.with_suffix(".xml")) if generated_prefix else None,
                "generated_xml_sha256": item.get("generated_xml_sha256"),
                "generated_bi4": relpath(generated_prefix.with_suffix(".bi4")) if generated_prefix else None,
                "generated_bi4_sha256": run.get("input_generated_bi4_sha256"),
                "attempt_id": run.get("attempt_id"),
                "attempt_directory": str(attempt) if attempt else None,
                "attempt_sha256": sha256(attempt_json) if attempt_json else None,
                "solver_status": run.get("execution_status", run.get("status")),
                "solver_wall_seconds": run.get("elapsed_seconds"),
                "raw_output": {"file_count": len(raw_files), "bytes": sum(path.stat().st_size for path in raw_files) if raw_files else None},
                "hdf5": normalization.get("hdf5") or next((a.get("hdf5") for a in report.get("audits", []) if a.get("case_id") == case_id), None),
                "hdf5_sha256": normalization.get("hdf5_sha256"),
                "sidecar": normalization.get("sidecar"),
                "sidecar_sha256": normalization.get("sidecar_sha256"),
                "audit_status": next((a.get("r6_full_time_audit_status") for a in report.get("audits", []) if a.get("case_id") == case_id), "unknown"),
            }
    return result


def matrix_cells(prepared: Sequence[dict[str, Any]] | None = None, audits: Sequence[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    persisted = load_matrix_report()
    if prepared is None:
        prepared = persisted.get("prepared_cases") or records()
    if audits is None:
        audits = persisted.get("audits") or []
    provenance = _reused_provenance()
    audit_map = _reused_audit_map()
    prepared_map = {item["case_id"]: item for item in (prepared or [])}
    audit_map.update({item["case_id"]: item for item in (audits or []) if item.get("case_id")})
    cells = []
    for height, resolution, case_id, source_name in REUSED_CASES:
        item = dict(provenance.get(case_id, {"case_id": case_id, "role": "reused_n3", "reuse": True}))
        item.update({"height_label": height, "resolution": resolution, "matrix_status": "reused_completed", "audit": audit_map.get(case_id, {})})
        cells.append(item)
    for record in prepared or records():
        item = dict(prepared_map.get(record["case_id"], record))
        audit = audit_map.get(record["case_id"], {})
        run = next((x for x in load_matrix_report().get("solver_runs", []) if x.get("case_id") == record["case_id"]), {})
        normal = next((x for x in load_matrix_report().get("normalization", []) if x.get("case_id") == record["case_id"]), {})
        item.update({
            "role": "new_n4",
            "reuse": False,
            "source_recipe_id": SOURCE_RECIPE_ID,
            "matrix_status": "completed" if run.get("execution_status") == "completed" and normal.get("normalization_status") == "completed" else "awaiting_owner_budget_approval",
            "solver_status": run.get("execution_status", "not_started"),
            "solver_wall_seconds": run.get("elapsed_seconds"),
            "attempt_id": run.get("attempt_id"),
            "attempt_sha256": sha256(Path(run["attempt_directory"]) / "attempt.json") if run.get("attempt_directory") and (Path(run["attempt_directory"]) / "attempt.json").is_file() else None,
            "hdf5": normal.get("hdf5"),
            "hdf5_sha256": normal.get("hdf5_sha256"),
            "sidecar": normal.get("sidecar"),
            "sidecar_sha256": normal.get("sidecar_sha256"),
            "audit": audit,
        })
        cells.append(item)
    order = {"h09": 0, "h10": 1, "h11": 2}
    return sorted(cells, key=lambda item: (order.get(item.get("height_label"), 9), list(DP_M).index(item.get("resolution", "fine"))))


def _height_comparisons(cells: Sequence[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for height in ("h09", "h10", "h11"):
        by_level = {item.get("resolution"): item.get("audit", {}) for item in cells if item.get("height_label") == height}
        comparisons = {}
        for left, right, label in (("coarse", "medium", "coarse_to_medium"), ("medium", "fine", "medium_to_fine")):
            if left not in by_level or right not in by_level or not by_level[left].get("fixed_time_grid") or not by_level[right].get("fixed_time_grid"):
                comparisons[label] = {"status": "unknown", "reason": "missing_same_cfl_cell"}
            else:
                comparisons[label] = r6._pair_comparison(by_level[left], by_level[right])
        audits_present = [item for item in by_level.values() if item]
        complete = len(by_level) == 3 and all(item.get("r6_full_time_audit_status") == "pass" for item in audits_present)
        comparison_pass = bool(comparisons) and all(item.get("status") == "pass_diagnostic" for item in comparisons.values())
        result[height] = {
            "height_m": HEIGHTS_M[height],
            "resolution_status": {level: by_level.get(level, {}).get("r6_full_time_audit_status", "missing") for level in DP_M},
            "comparisons": comparisons,
            "status": "qualified_t1_height_candidate" if complete and comparison_pass else "blocked_or_incomplete",
        }
    return result


def build_matrix(prepared: Sequence[dict[str, Any]] | None = None, audits: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    cells = matrix_cells(prepared, audits)
    comparisons = _height_comparisons(cells)
    report = load_matrix_report()
    report.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cells": cells,
        "height_comparisons": comparisons,
        "execution_status": "completed" if all(item.get("matrix_status") == "completed" or item.get("reuse") for item in cells) else report.get("execution_status", "awaiting_owner_budget_approval"),
        "formal_release": False,
        "development_authorized": False,
        "h10_blocker_preserved": True,
        "registered_time_grid_s": list(REGISTERED_TIMES_S),
        "comparison_thresholds": {"distribution_tv": 0.05, "com_l2_m": 0.06, "front_q90_abs_delta_m": 0.06},
    })
    atomic_json(MATRIX_REPORT, report)
    return report


def _h5_metrics(path: Path, requested_time: float) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing", "path": relpath(path)}
    with h5py.File(path, "r") as h5:
        times = np.asarray(h5["time"][:], dtype=np.float64)
        frame = int(np.argmin(np.abs(times - requested_time)))
        valid = np.asarray(h5["valid"][frame], dtype=bool)
        positions = np.asarray(h5["position"][frame], dtype=np.float64)
        velocity = np.asarray(h5["velocity"][frame], dtype=np.float64)
        density = np.asarray(h5["density"][frame], dtype=np.float64)
        mass = np.asarray(h5["mass"][frame], dtype=np.float64)
        initial_valid = np.asarray(h5["valid"][0], dtype=bool)
        initial_mass = float(np.sum(np.asarray(h5["mass"][0], dtype=np.float64)[initial_valid], dtype=np.float64))
        current = np.flatnonzero(valid)
        if not len(current):
            return {"status": "empty", "path": relpath(path), "frame": frame, "actual_time_s": float(times[frame])}
        base = r6._frame_metrics(h5, frame, initial_mass)
        points = positions[current]
        finite_density = density[current][np.isfinite(density[current])]
        wall_distances = np.column_stack([
            points[:, 0], 1.2 - points[:, 0], points[:, 1], 0.4 - points[:, 1], points[:, 2],
        ])
        base.update({
            "status": "complete",
            "path": relpath(path),
            "frame": frame,
            "actual_time_s": float(times[frame]),
            "initial_particles": int(initial_valid.sum()),
            "initial_mass_kg": initial_mass,
            "density_min_kg_m3": float(finite_density.min()) if len(finite_density) else None,
            "density_max_kg_m3": float(finite_density.max()) if len(finite_density) else None,
            "wall_effective_position_m": {
                "min_closed_wall_distance_m": float(wall_distances.min()),
                "q01_closed_wall_distance_m": float(np.quantile(wall_distances.min(axis=1), 0.01)),
                "open_top": True,
            },
        })
        return base


def _distribution_tv(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    if left.get("distribution") is None or right.get("distribution") is None:
        return None
    return float(r6.r5_gate.mass_fraction_tv(r6._closed_distribution(left["distribution"]), r6._closed_distribution(right["distribution"])))


def _compare_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if left.get("status") != "complete" or right.get("status") != "complete":
        return {"status": "missing"}
    com_delta = float(np.linalg.norm(np.asarray(left["com_m"]) - np.asarray(right["com_m"])))
    q = {name: abs(float(left["front_quantiles_m"][name]) - float(right["front_quantiles_m"][name])) for name in ("q50", "q90", "q99")}
    energy_left = float(left["kinetic_energy_proxy_j"])
    energy_right = float(right["kinetic_energy_proxy_j"])
    return {
        "status": "complete",
        "requested_time_s": left.get("requested_time_s", right.get("requested_time_s")),
        "actual_time_left_s": left.get("actual_time_s"),
        "actual_time_right_s": right.get("actual_time_s"),
        "distribution_tv": _distribution_tv(left, right),
        "com_l2_m": com_delta,
        "front_quantile_abs_delta_m": q,
        "kinetic_energy_relative_delta": abs(energy_left - energy_right) / max(abs(energy_left), abs(energy_right), 1e-12),
        "mass_fraction_left": left.get("mass_fraction"),
        "mass_fraction_right": right.get("mass_fraction"),
        "initial_mass_relative_delta": abs(float(left["initial_mass_kg"]) - float(right["initial_mass_kg"])) / max(abs(float(left["initial_mass_kg"])), abs(float(right["initial_mass_kg"])), 1e-30),
    }


def build_difference() -> dict[str, Any]:
    bridge = read_json(CAMPAIGN / "r6-n3-bridge-h10.json", {})
    bridge_audits = {item.get("resolution"): item for item in bridge.get("audits", [])}
    new_cells = []
    for resolution in ("coarse", "medium", "fine"):
        item = bridge_audits.get(resolution, {})
        path = lab_path(item.get("hdf5", "")) if item.get("hdf5") else Path("/nonexistent")
        new_cells.append((resolution, path))
    old_root = CAMPAIGN / "data" / "r5-f1-solver-gate"
    old_cells = [(resolution, old_root / f"R4_F1_plain_dam_break_{resolution}.h5") for resolution in ("coarse", "medium", "fine")]
    peak = max(bridge.get("comparisons", {}).get("coarse_to_medium", {}).get("series", []), key=lambda row: row.get("distribution_tv", -1.0), default={})
    peak_time = float(peak.get("requested_time_s", 1.05))
    n3_at_peak = {resolution: _h5_metrics(path, peak_time) for resolution, path in new_cells}
    old_at_peak = {resolution: _h5_metrics(path, peak_time) for resolution, path in old_cells}
    for item in [*n3_at_peak.values(), *old_at_peak.values()]:
        item["requested_time_s"] = peak_time
    region_delta = {}
    if n3_at_peak.get("coarse", {}).get("status") == "complete" and n3_at_peak.get("medium", {}).get("status") == "complete":
        coarse_dist = n3_at_peak["coarse"]["distribution"]
        medium_dist = n3_at_peak["medium"]["distribution"]
        region_delta = {
            name: {"coarse": coarse_dist.get(name), "medium": medium_dist.get(name), "medium_minus_coarse": float(medium_dist.get(name, 0.0) - coarse_dist.get(name, 0.0))}
            for name in sorted(set(coarse_dist) | set(medium_dist))
        }
    sensitivity = {}
    for resolution, new_path in new_cells:
        old_path = dict(old_cells)[resolution]
        series = []
        for requested in REGISTERED_TIMES_S:
            left = _h5_metrics(new_path, requested)
            right = _h5_metrics(old_path, requested)
            left["requested_time_s"] = requested
            right["requested_time_s"] = requested
            series.append(_compare_metrics(left, right))
        sensitivity[resolution] = {"old_recipe": "R4_F1_plain_dam_break_cfl020", "new_recipe": SOURCE_RECIPE_ID, "series": series}
    tv_series = bridge.get("comparisons", {}).get("coarse_to_medium", {}).get("series", [])
    near_peak = [row for row in tv_series if row.get("distribution_tv", 0.0) >= 0.9 * float(peak.get("distribution_tv", 1.0))]
    event_classification = "registered_grid_localized_peak" if len(near_peak) <= 3 else "persistent_or_broad_grid_difference"
    report = {
        "schema_version": "n4-h10-difference-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE_COMMIT,
        "source_recipe_id": SOURCE_RECIPE_ID,
        "execution_status": "completed_cpu_analysis",
        "primary_gate_unchanged": {"max_tv": 0.05, "h10_coarse_medium_tv": 0.056904761904761875},
        "peak": {
            "requested_time_s": peak_time,
            "registered_grid_index": list(REGISTERED_TIMES_S).index(min(REGISTERED_TIMES_S, key=lambda value: abs(value - peak_time))),
            "bridge_series_row": peak,
            "near_peak_registered_points": near_peak,
            "classification": event_classification,
        },
        "n3_same_cfl_at_peak": n3_at_peak,
        "region_contribution_at_peak": region_delta,
        "old_cfl020_at_peak": old_at_peak,
        "cfl020_vs_cfl010_same_resolution": sensitivity,
        "interpretation": {
            "supported": [
                "The coarse-to-medium TV maximum is localized on the registered 21-point grid around 1.05 s.",
                "The initial distribution is upstream-dominated for all h10 resolutions; region deltas are reported without changing the primary gate.",
                "CFL=0.2 versus CFL=0.1 is a time-step sensitivity diagnostic, not a causal attribution of the resolution failure.",
            ],
            "not_supported": [
                "A single peak does not prove a transient-only physical cause.",
                "Initial mass/discretization differences do not by themselves explain the terminal TV difference.",
                "Auxiliary smoothing, phase alignment, or alternative region boundaries cannot replace the primary gate.",
            ],
        },
    }
    atomic_json(DIFFERENCE_REPORT, report)
    return report


def update_resource_ledger() -> dict[str, Any]:
    report = load_matrix_report()
    prepared = report.get("prepared_cases", [])
    endpoint, bridge = _n3_reports()
    reused_runs = [*endpoint.get("solver_runs", []), *bridge.get("solver_runs", [])]
    existing = report.get("resource_ledger", {})
    fallback_runs = [
        item for item in report.get("solver_runs", [])
        if item.get("execution_status") != "reused_completed"
    ]
    ledger = {
        "schema_version": "n4-resource-ledger-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE_COMMIT,
        "authorization": report.get("authorization", {}),
        "authorization_source": (
            "owner authorization recorded in N4-OWNER-APPROVAL.json"
            if report.get("authorization", {}).get("new_solver_authorized")
            else "N4 attachment proposed plan; owner approval is intentionally not inferred"
        ),
        "new_n4": {
            "solver_attempts_started": int(existing.get("solver_attempts_started", sum(1 for item in fallback_runs))),
            "solver_attempts_completed": int(existing.get("solver_attempts_completed", sum(1 for item in fallback_runs if item.get("execution_status") == "completed"))),
            "solver_attempts_failed": int(existing.get("solver_attempts_failed", sum(1 for item in fallback_runs if item.get("execution_status") == "solver_failed"))),
            "solver_device_seconds": float(existing.get("solver_device_seconds", sum(float(item.get("device_seconds") or item.get("elapsed_seconds") or 0.0) for item in fallback_runs))),
            "gpu_seconds_cap": PROPOSED_GPU_SECONDS,
            "solver_attempt_timeout_seconds": SOLVER_ATTEMPT_TIMEOUT_SECONDS,
            "gencase_cpu_seconds": sum(float(item.get("gencase", {}).get("elapsed_seconds") or 0.0) for item in prepared),
            "normalization_seconds": sum(float(item.get("elapsed_seconds") or 0.0) for item in report.get("normalization", [])),
            "audit_seconds": sum(float(item.get("audit_elapsed_seconds") or 0.0) for item in report.get("audits", [])),
        },
        "reused_n3": {
            "cells": len(REUSED_CASES),
            "solver_wall_seconds_not_charged_to_n4": sum(float(item.get("elapsed_seconds") or 0.0) for item in reused_runs),
            "source_reports": ["r6-n3-endpoint-closure.json", "r6-n3-bridge-h10.json"],
        },
        "gpu_policy": {"protected_gpu_indices": list(PROTECTED_GPU_IDS), "candidate_gpu_indices": list(GPU_IDS), "no_external_jobs_terminated": True},
        "storage_policy": "raw BI4 and run directories remain ignored/local; compact reports and sidecars are the review artifacts",
    }
    atomic_json(RESOURCE_REPORT, ledger)
    report["resource_ledger"] = ledger["new_n4"]
    atomic_json(MATRIX_REPORT, report)
    return ledger


def write_decision(matrix: dict[str, Any] | None = None, difference: dict[str, Any] | None = None, ledger: dict[str, Any] | None = None) -> dict[str, Any]:
    matrix = matrix or load_matrix_report()
    difference = difference or read_json(DIFFERENCE_REPORT, {})
    ledger = ledger or read_json(RESOURCE_REPORT, {})
    new_cells = [item for item in matrix.get("cells", []) if item.get("role") == "new_n4"]
    new_complete = sum(1 for item in new_cells if item.get("matrix_status") == "completed")
    new_audits_pass = len(new_cells) == MAX_NEW_SOLVER_ATTEMPTS and all(
        item.get("audit", {}).get("r6_full_time_audit_status") == "pass" for item in new_cells
    )
    comparisons = matrix.get("height_comparisons", {})
    h10_cm = comparisons.get("h10", {}).get("comparisons", {}).get("coarse_to_medium", {})
    required_pair_pass = all(
        comparisons.get(height, {}).get("comparisons", {}).get(pair, {}).get("status") == "pass_diagnostic"
        for height in ("h09", "h11")
        for pair in ("coarse_to_medium", "medium_to_fine")
    )
    same_cfl_matrix_complete = new_complete == MAX_NEW_SOLVER_ATTEMPTS and new_audits_pass and required_pair_pass
    decision = {
        "schema_version": "n4-decision-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_commit": BASELINE_COMMIT,
        "execution_status": "awaiting_owner_budget_approval" if new_complete == 0 else "completed_with_findings",
        "new_n4_cells_completed": new_complete,
        "new_n4_cells_expected": 4,
        "new_n4_full_time_audits_passed": new_audits_pass,
        "h09_h11_pair_gates_passed": required_pair_pass,
        "same_cfl_matrix_complete": same_cfl_matrix_complete,
        "formal_release": False,
        "development_authorized": False,
        "g4": "not_launched",
        "h10_coarse_medium_blocker": {
            "status": h10_cm.get("status", "fail_diagnostic"),
            "max_tv": h10_cm.get("maxima", {}).get("distribution_tv", 0.056904761904761875),
            "gate": 0.05,
            "disposition": "blocking",
            "must_remain_blocking": True,
        },
        "completion_requirements": {
            "all_four_new_full_time_audits_pass": True,
            "native_exclusion_reconciliation_required": True,
            "h09_and_h11_both_resolution_pairs_pass": True,
        },
        "old_three_resolution_recipe": "not_admitted",
        "next_gate": (
            "Obtain explicit owner approval for at most 0.5 GPU-hours and four attempts, then run only h09/h11 coarse/medium."
            if new_complete == 0 else
            "Review all four new cells; h10 coarse-to-medium remains a separate blocker."
        ),
        "difference_interpretation": difference.get("peak", {}).get("classification"),
        "resource_ledger": relpath(RESOURCE_REPORT),
    }
    atomic_json(DECISION_REPORT, decision)
    markdown = f"""# N4 decision\n\nGenerated: {decision['generated_at_utc']}\nBaseline: `{BASELINE_COMMIT}`\n\n## Decision\n\n- Execution status: `{decision['execution_status']}`\n- New N4 cells: `{new_complete}/4`\n- Same-CFL 3×3 matrix complete: `{decision['same_cfl_matrix_complete']}`\n- Formal release: `false`\n- Development tranche: `false`\n- G4: `not_launched`\n\nThe h10 coarse-to-medium blocker is retained: max TV `{decision['h10_coarse_medium_blocker']['max_tv']}` against gate `{decision['h10_coarse_medium_blocker']['gate']}`. Four h09/h11 cells cannot erase or override that failure.\n\n## Authorization\n\nThe N4 plan proposes a maximum of `0.5 GPU·h` and four solver attempts, but the attached plan is not itself owner authorization. New solver execution remains guarded by explicit `--owner-approval-evidence`.\n\n## Evidence\n\n- Comparable matrix: `N4-COMPARABLE-MATRIX.md` / `.json`\n- h10 difference analysis: `N4-H10-DIFFERENCE.md` / `.json`\n- Resource ledger: `N4-RESOURCE-LEDGER.json`\n- Next action: {decision['next_gate']}\n"""
    markdown += "\nProduct completion alone does not qualify N4: all four new full-time audits, native exclusion reconciliation, and both h09/h11 resolution-pair gates must pass.\n"
    markdown += "The attached planning document is not authorization; the runner requires an exact-scope structured approval JSON and records its SHA-256 digest in the batch and attempt manifests.\n"
    DECISION_MARKDOWN.write_text(markdown)
    return decision


def write_matrix_markdown(report: dict[str, Any]) -> None:
    rows = []
    for item in report.get("cells", []):
        audit = item.get("audit", {})
        rows.append(
            f"| `{item.get('height_label')}` | `{item.get('resolution')}` | `{item.get('case_id')}` | "
            f"{'reuse' if item.get('reuse') else 'new'} | `{item.get('matrix_status')}` | "
            f"`{audit.get('r6_full_time_audit_status', 'not_audited')}` | "
            f"{audit.get('initial_identities_missing_at_final', 'n/a')} |"
        )
    comparison_rows = []
    for height, item in report.get("height_comparisons", {}).items():
        for label, comparison in item.get("comparisons", {}).items():
            maxima = comparison.get("maxima", {})
            comparison_rows.append(
                f"| `{height}` | `{label}` | `{comparison.get('status')}` | "
                f"{maxima.get('distribution_tv', 'n/a')} | {maxima.get('com_l2_m', 'n/a')} | {maxima.get('front_q90_abs_delta_m', 'n/a')} |"
            )
    text = f"""# N4 comparable matrix\n\nBaseline: `{BASELINE_COMMIT}`  Recipe: `{SOURCE_RECIPE_ID}`\n\nThis table keeps the five N3 CFL=0.1 cells as explicit reuse and reserves four new h09/h11 coarse/medium cells for owner-authorized solver attempts. Old CFL=0.2 data are not in the primary matrix.\n\n| height | resolution | case | source | matrix status | full-time audit | final missing identities |\n|---|---|---|---|---|---|---:|\n{chr(10).join(rows)}\n\n## Pair gates\n\nThresholds: TV ≤ `0.05`, COM ≤ `0.06 m`, q90 ≤ `0.06 m`; all use the registered 21-time grid.\n\n| height | pair | status | max TV | max COM (m) | max q90 (m) |\n|---|---|---|---:|---:|---:|\n{chr(10).join(comparison_rows)}\n\nThe h10 coarse→medium failure is preserved and cannot be overridden by endpoint completion.\n"""
    text += "\nProduct completion alone does not qualify N4: all four new full-time audits, native exclusion reconciliation, and both h09/h11 resolution-pair gates must pass.\n"
    MATRIX_MARKDOWN.write_text(text)


def write_difference_markdown(report: dict[str, Any]) -> None:
    peak = report.get("peak", {})
    rows = []
    for name, item in report.get("region_contribution_at_peak", {}).items():
        rows.append(f"| `{name}` | {item.get('coarse')} | {item.get('medium')} | {item.get('medium_minus_coarse')} |")
    text = f"""# N4 h10 difference analysis\n\nBaseline: `{BASELINE_COMMIT}`\n\n## Primary peak\n\n- Registered requested time: `{peak.get('requested_time_s')} s`\n- Registered grid index: `{peak.get('registered_grid_index')}`\n- Max coarse→medium TV: `{report.get('primary_gate_unchanged', {}).get('h10_coarse_medium_tv')}`\n- Gate: `{report.get('primary_gate_unchanged', {}).get('max_tv')}`\n- Grid classification: `{peak.get('classification')}`\n\n| region | coarse mass fraction | medium mass fraction | medium − coarse |\n|---|---:|---:|---:|\n{chr(10).join(rows)}\n\n## Interpretation\n\nThe peak is localized on the registered diagnostic grid, but this does not prove a transient-only cause. Initial mass/discretization and CFL=0.2 vs CFL=0.1 are reported as diagnostics; neither is used to rewrite the primary gate. Alternative smoothing, phase alignment, or region boundaries cannot replace the registered comparison.\n\nThe full numerical series and same-resolution CFL sensitivity are in `N4-H10-DIFFERENCE.json`.\n"""
    DIFFERENCE_MARKDOWN.write_text(text)


def write_handoff(
    matrix: dict[str, Any],
    difference: dict[str, Any],
    ledger: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    cell_rows = []
    for item in matrix.get("cells", []):
        audit = item.get("audit", {})
        cell_rows.append(
            f"| `{item.get('height_label')}` | `{item.get('resolution')}` | "
            f"{'reuse' if item.get('reuse') else 'new'} | `{item.get('matrix_status')}` | "
            f"`{audit.get('r6_full_time_audit_status', 'not_audited')}` | "
            f"{audit.get('initial_identities_missing_at_final', 'n/a')} |"
        )
    comparison_rows = []
    for height, item in matrix.get("height_comparisons", {}).items():
        for label, comparison in item.get("comparisons", {}).items():
            comparison_rows.append(
                f"| `{height}` | `{label}` | `{comparison.get('status')}` | "
                f"{comparison.get('maxima', {}).get('distribution_tv', 'n/a')} |"
            )
    peak = difference.get("peak", {})
    handoff = f"""# N4 latest handoff

Generated: {datetime.now(timezone.utc).isoformat()}
Baseline: `{BASELINE_COMMIT}`
Branch: `{git_value('branch', '--show-current')}`
Code revision used for this handoff: `{git_value('log', '-1', '--format=%H', '--', 'lagrangian-fluid-lab/scripts/r6_n4_matrix.py', 'lagrangian-fluid-lab/scripts/campaign_runner.py')}`

## Current state

`execution_status={decision.get('execution_status')}`; new solver cells
`{decision.get('new_n4_cells_completed')}/{decision.get('new_n4_cells_expected')}`;
`formal_release=false`; `development_authorized=false`; `G4=not_launched`.

The N4 plan is a bounded evidence-completion task, not production data
authorization.  The four new solver attempts remain guarded until the owner
provides a structured approval record binding at most `0.5 GPU·h`, four
attempts, the exact recipe, and GPUs 4–7.

## Stage summary

- Input preparation: four unique h09/h11 coarse/medium CFL=0.1 definitions
  generated and GenCase-checked; no new solver attempt was started.
- Reuse: five N3 CFL=0.1 cells are kept as explicit reuse; old CFL=0.2 data
  are excluded from the primary matrix.
- H10 difference analysis: the registered coarse→medium TV peak is
  `{peak.get('bridge_series_row', {}).get('distribution_tv')}` at requested
  `{peak.get('requested_time_s')} s` (grid index `{peak.get('registered_grid_index')}`),
  classified as `{peak.get('classification')}`.  This classification is
  diagnostic and does not close the blocker.
- Resource ledger: new N4 solver device seconds are
  `{ledger.get('new_n4', {}).get('solver_device_seconds')}`; GenCase CPU seconds
  are `{ledger.get('new_n4', {}).get('gencase_cpu_seconds')}`.  The five reused
  solver wall times are provenance only and are not charged to N4.  If
  authorized, each new attempt is capped at
  `{ledger.get('new_n4', {}).get('solver_attempt_timeout_seconds')}` seconds,
  with a total ledger cap of `{ledger.get('new_n4', {}).get('gpu_seconds_cap')}`
  seconds.

## Same-CFL matrix

| height | resolution | source | status | full-time audit | missing identities |
|---|---|---|---|---|---:|
{chr(10).join(cell_rows)}

| height | pair | status | max TV |
|---|---|---|---:|
{chr(10).join(comparison_rows)}

The h10 coarse→medium result remains `fail_diagnostic`, max TV
`0.056904761904761875 > 0.05`; four new cells cannot override it.

## Review artifacts

- [N4-COMPARABLE-MATRIX.md](N4-COMPARABLE-MATRIX.md)
- [N4-H10-DIFFERENCE.md](N4-H10-DIFFERENCE.md)
- [N4-RESOURCE-LEDGER.json](N4-RESOURCE-LEDGER.json)
- [N4-DECISION.md](N4-DECISION.md)
- [N4-REVIEW-PACKET.md](N4-REVIEW-PACKET.md)
- [N4-REVIEW-ROUND-1.md](N4-REVIEW-ROUND-1.md)
- [N4-REVIEW-ROUND-2.md](N4-REVIEW-ROUND-2.md)
- [N4-REVIEW-ROUND-3.md](N4-REVIEW-ROUND-3.md)

## Next authorized gate

After explicit owner budget approval, run only h09/h11 coarse/medium with the
locked recipe.  Require full-time identity/quality audits and both resolution
pairs per height to pass TV≤0.05, COM≤0.06 m, and q90≤0.06 m.  Keep the h10
coarse→medium blocker even if all four new cells pass.
"""
    review = f"""# N4 reviewer packet

This is the stage handoff for the cloud reviewer.  It is based on baseline
`{BASELINE_COMMIT}` and the locked N4 input plan.  No new N4 solver attempt has
been started while owner budget status is pending.

## Requested review

1. Confirm the N3 five-cell reuse and the four unique N4 input definitions
   (`cflnumber=0.1`, `dp=0.035/0.024`, h09/h11, 1.5 s, 0.001 s output).
2. Review the h10 TV peak at `{peak.get('requested_time_s')} s`: max TV
   `{peak.get('bridge_series_row', {}).get('distribution_tv')}`, with the
   reported region contributions and the same-resolution CFL=0.2 diagnostic.
3. Confirm that the proposed next action is exactly four bounded new solver
   attempts, each governed by the recorded timeout/cap, not a scan, F6/G4 run,
   development tranche, or release.
4. After runs exist, require per-case native exclusion evidence, full-time
   identity audit, and both pair gates for h09 and h11.  Do not let successful
   endpoints override the h10 coarse→medium blocker.
5. Recheck the round-1 P1 corrections: persisted audit propagation, exact
   launch-set/hash binding, durable attempt accounting, process-group timeout,
   native exclusion reconciliation, scoped approval evidence, and round-2
   lock/latest consistency.

## Current disposition

- `owner_budget_status=pending_owner_approval`
- `new_solver_authorized=false`
- `new_n4_cells=0/4`
- `formal_release=false`
- `development_authorized=false`
- `G4=not_launched`

## Evidence files

- `N4-COMPARABLE-MATRIX.json/.md`
- `N4-H10-DIFFERENCE.json/.md`
- `N4-RESOURCE-LEDGER.json`
- `N4-DECISION.json/.md`
- `N4-REVIEW-ROUND-1.md`
- `N4-REVIEW-ROUND-2.md`
- `N4-REVIEW-ROUND-3.md`
"""
    HANDOFF_MARKDOWN.write_text(handoff)
    REVIEW_PACKET_MARKDOWN.write_text(review)


def analyze() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    matrix = build_matrix()
    difference = build_difference()
    ledger = update_resource_ledger()
    decision = write_decision(matrix, difference, ledger)
    write_matrix_markdown(matrix)
    write_difference_markdown(difference)
    write_handoff(matrix, difference, ledger, decision)
    return matrix, difference, ledger, decision


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "analyze", "run", "normalize", "audit", "all"), nargs="?", default="analyze")
    parser.add_argument("--owner-approval-evidence")
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args(argv)

    if args.action in {"prepare", "all"}:
        prepared = prepare()
    else:
        report = load_matrix_report()
        prepared = report.get("prepared_cases") or prepare()
    if args.action == "prepare":
        analyze()
    elif args.action == "analyze":
        analyze()
    elif args.action in {"run", "all"}:
        run_solver(prepared, evidence=args.owner_approval_evidence, rerun=args.rerun)
        normalize(prepared)
        audits = _new_audits(prepared)
        report = load_matrix_report()
        report["audits"] = audits
        report["audit_status"] = "completed" if all(item.get("r6_full_time_audit_status") == "pass" for item in audits) else "completed_with_findings"
        atomic_json(MATRIX_REPORT, report)
        analyze()
    elif args.action == "normalize":
        normalize(prepared)
    elif args.action == "audit":
        audits = _new_audits(prepared)
        report = load_matrix_report()
        report["audits"] = audits
        report["audit_status"] = "completed" if all(item.get("r6_full_time_audit_status") == "pass" for item in audits) else "completed_with_findings"
        atomic_json(MATRIX_REPORT, report)
        analyze()
    print(json.dumps({
        "action": args.action,
        "execution_status": load_matrix_report().get("execution_status"),
        "authorization": load_matrix_report().get("authorization"),
        "decision": read_json(DECISION_REPORT, {}).get("execution_status"),
        "reports": [relpath(MATRIX_REPORT), relpath(DIFFERENCE_REPORT), relpath(RESOURCE_REPORT), relpath(DECISION_REPORT)],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
