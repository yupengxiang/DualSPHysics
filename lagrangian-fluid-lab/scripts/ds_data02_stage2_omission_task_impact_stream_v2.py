#!/usr/bin/env python3
"""Forward all-118 typed-mass impact audit with scan-source closure.

The consumed v1 stream already joins completed scan, typed identity, and
native-cause evidence.  This version adds a strict producer closure before
reusing that result: each scan's trajectory path must be the exact H5 input
declared by its completed scan receipt, with equal launch/end digest records,
matching byte/mtime metadata, exact case command, and exact output root.
The H5 files are never opened or hashed here.  The product remains a mass
visibility screen; physical fate, dynamics, QN, and QE remain UNKNOWN.
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
WORKTREE_ROOT = SCRIPT.parents[2]
LAB_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab")
VENV = LAB_ROOT / ".venv/bin/python"
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_omission_task_impact_stream_v1.py"
V1_MANIFEST = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "omission-task-impact-stream-v1/impact-stream-v1-manifest.json"
)
V1_REQUEST = WORKTREE_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "omission-task-impact-stream-v1/omission-task-impact-stream-v1-request.json"
)
RUNTIME_V4 = SCRIPT.parent / "ds_data02_runtime_v4.py"
RUNTIME_V2 = SCRIPT.parent / "ds_data02_runtime_v2.py"
DISPATCH_V4 = SCRIPT.parent / "ds_data02_stage2_dispatch_v4.py"
STRICT_V4 = SCRIPT.parent / "ds_data02_strict_dispatch_v4.py"
MANIFEST_SCHEMA = "ds02.stage2.omission-task-impact-stream-v2-manifest.v1"
OUTPUT_SCHEMA = "ds02.stage2.omission-task-impact-stream.v2"
REQUEST_CASE = "STAGE2_OMISSION_TASK_IMPACT_STREAM_118_V2"
REQUEST_ATTEMPT = "omission-task-impact-stream-v2-primary-001"
PHYSICAL_CASE = "F2_F4_F6_HISTORICAL_118"
EXPECTED_FAMILIES = {"F2": 48, "F4": 22, "F6": 48}


class ImpactStreamV2Error(RuntimeError):
    """Raised when an immutable 118-case source contract is open."""


def sha256(value: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(value).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: Path | str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ImpactStreamV2Error(f"{label} is missing: {path}")
    return path


def read_json(value: Path | str, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImpactStreamV2Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ImpactStreamV2Error(f"{label} is not an object: {path}")
    return path, payload


def record(value: Path | str, label: str) -> dict[str, Any]:
    path = require_file(value, label)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ImpactStreamV2Error(f"refuse to overwrite existing output: {path}")
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def load_v1():
    spec = importlib.util.spec_from_file_location("stage2_impact_stream_v1", V1_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImpactStreamV2Error("cannot load v1 impact stream module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable_h5_producer(scan_path: Path, scan: dict[str, Any], receipt_path: Path, receipt: dict[str, Any], entry: dict[str, Any], immutable_inputs: dict[str, str]) -> dict[str, Any]:
    """Validate H5 identity from receipt metadata without reading H5 bytes."""
    trajectory_text = scan.get("trajectory")
    if not isinstance(trajectory_text, str) or not trajectory_text.lower().endswith((".h5", ".hdf5")):
        raise ImpactStreamV2Error(f"scan trajectory is not an H5 path: {scan_path}")
    trajectory = require_file(trajectory_text, "scan trajectory metadata path")
    request = receipt.get("request", {})
    input_files = [Path(str(value)).expanduser().resolve() for value in request.get("input_files", [])]
    h5_inputs = [path for path in input_files if path == trajectory]
    if len(h5_inputs) != 1:
        raise ImpactStreamV2Error(f"scan trajectory is not the unique receipt H5 input: {scan_path}")
    key = str(trajectory)
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise ImpactStreamV2Error(f"scan H5 receipt launch/end digest closure is open: {scan_path}")
    # Metadata-only checks.  The H5 content is deliberately not opened or
    # hashed; the producer receipt's equal launch/end digest is the source
    # identity evidence consumed by this audit.
    stat = trajectory.stat()
    if int(scan.get("source_bytes", -1)) != stat.st_size or int(scan.get("source_mtime_ns", -1)) != stat.st_mtime_ns:
        raise ImpactStreamV2Error(f"scan H5 size/mtime metadata differs: {trajectory}")
    command = request.get("command", [])
    if not isinstance(command, list) or "--case-id" not in command:
        raise ImpactStreamV2Error(f"scan receipt lacks exact case command: {scan_path}")
    index = command.index("--case-id")
    if index + 1 >= len(command) or command[index + 1] != scan.get("physical_case_id"):
        raise ImpactStreamV2Error(f"scan receipt case command differs: {scan_path}")
    if Path(receipt.get("output_root", "")).resolve() != scan_path.parent.resolve():
        raise ImpactStreamV2Error(f"scan receipt output root differs: {scan_path}")
    catalog = None
    if "--catalog" in command:
        cindex = command.index("--catalog")
        if cindex + 1 < len(command):
            catalog = require_file(command[cindex + 1], "scan CURRENT catalog")
    return {
        "trajectory": {"path": str(trajectory), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                       "receipt_declared_sha256": declared, "content_hash_performed": False},
        "catalog": record(catalog, "scan CURRENT catalog") if catalog else None,
        "receipt_output_root": str(scan_path.parent.resolve()),
    }


def validate_manifest(manifest_path: Path = V1_MANIFEST) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "v1 118 impact manifest")
    if manifest.get("schema") != "ds02.stage2.omission-task-impact-stream-manifest.v1" or manifest.get("status") != "IMMUTABLE_SOURCE_SET":
        raise ImpactStreamV2Error("v1 source manifest schema/status differs")
    if int(manifest.get("case_count", -1)) != 118 or manifest.get("family_case_counts") != EXPECTED_FAMILIES:
        raise ImpactStreamV2Error("v1 source membership is not exact F2=48/F4=22/F6=48")
    for path_text, expected in manifest.get("inputs", {}).items():
        path = require_file(path_text, "v1 immutable input")
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise ImpactStreamV2Error(f"H5 content entered v2 input set: {path}")
        if sha256(path) != expected:
            raise ImpactStreamV2Error(f"v1 immutable input changed: {path}")
    source_records: list[dict[str, Any]] = []
    for entry in manifest.get("entries", []):
        family = entry.get("family_id")
        if family not in EXPECTED_FAMILIES:
            raise ImpactStreamV2Error(f"unexpected family in 118 source: {family}")
        scan_path, scan = read_json(entry["scan_path"], f"{entry['case_key']} scan")
        receipt_path, receipt = read_json(entry["scan_receipt_path"], f"{entry['case_key']} scan receipt")
        if receipt.get("schema") != "ds02.execution-receipt.v1" or receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise ImpactStreamV2Error(f"scan receipt is not completed: {entry['case_key']}")
        if scan.get("family_id") != family or scan.get("physical_case_id") != entry.get("physical_case_id") or scan.get("scan_status") != "SCANNED":
            raise ImpactStreamV2Error(f"scan identity/status differs: {entry['case_key']}")
        source_records.append({"case_key": entry["case_key"], "family_id": family,
                               "scan_path": str(scan_path), "receipt_path": str(receipt_path),
                               "producer": stable_h5_producer(scan_path, scan, receipt_path, receipt, entry, manifest.get("inputs", {}))})
    if len(source_records) != 118:
        raise ImpactStreamV2Error("v2 source manifest did not produce 118 records")
    return {"manifest_path": manifest_path, "manifest": manifest, "source_records": source_records,
            "h5_content_hash_performed": False}


def prepare(output_dir: Path) -> dict[str, Any]:
    closure = validate_manifest()
    output_dir = output_dir.resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    files = [SCRIPT, V1_SCRIPT, V1_MANIFEST, V1_REQUEST, RUNTIME_V4, RUNTIME_V2, DISPATCH_V4, STRICT_V4]
    files.extend(Path(path) for path in closure["manifest"].get("inputs", {}))
    files.extend(Path(row["producer"]["catalog"]["path"]) for row in closure["source_records"] if row["producer"].get("catalog"))
    unique: list[Path] = []; seen: set[str] = set()
    for value in files:
        path = require_file(value, f"v2 request input {Path(value).name}")
        if path.suffix.lower() in {".h5", ".hdf5"}:
            raise ImpactStreamV2Error(f"H5 input is forbidden in v2 request: {path}")
        if str(path) not in seen:
            seen.add(str(path)); unique.append(path)
    hashes = {str(path): sha256(path) for path in unique}
    manifest_path = output_dir / "omission-task-impact-stream-v2-manifest.json"
    request_path = output_dir / "omission-task-impact-stream-v2-request.json"
    manifest = {
        "schema": MANIFEST_SCHEMA, "status": "PREPARED_118_SOURCE_CLOSED_NO_H5",
        "physical_case_id": PHYSICAL_CASE, "case_count": 118, "family_case_counts": EXPECTED_FAMILIES,
        "source_v1_manifest": record(V1_MANIFEST, "v1 impact manifest"),
        "source_records": closure["source_records"], "input_files": sorted(hashes), "input_sha256": dict(sorted(hashes.items())),
        "read_policy": {"h5_opened": False, "h5_content_hash_performed": False, "trajectory_content_opened": False, "solver_started": False, "partvtkout_started": False},
        "qualification": {"mass_screen_only": True, "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    atomic_json(manifest_path, manifest)
    request_hashes = dict(hashes); request_hashes[str(manifest_path)] = sha256(manifest_path)
    request = {
        "schema": "ds02.request.v1", "family_id": "infra", "case_id": REQUEST_CASE,
        "physical_case_id": PHYSICAL_CASE, "attempt_id": REQUEST_ATTEMPT,
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 900, "estimated_storage_bytes": 256 * 1024 * 1024,
        "cwd": str(SCRIPT.parent), "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "run", "--manifest", str(manifest_path), "--output", "{attempt_root}/omission-task-impact-stream-v2.json"],
        "input_files": sorted(request_hashes), "input_sha256": dict(sorted(request_hashes.items())),
        "source_case_membership": {"F2": 48, "F4": 22, "F6": 48, "native_ids": {"F2": 1078, "F4": 51, "F6": 199}},
        "source_scope": {"v1_typed_impact_reused": True, "producer_scan_receipts_revalidated": True, "h5_content_read": False, "h5_content_hash_performed": False, "solver_or_decoder_started": False},
        "source_read_cost": {"h5_bytes_read": 0, "trajectory_bytes_read": 0, "h5_content_hash_bytes": 0, "runtime_pre_post_hash_bytes": sum(path.stat().st_size for path in unique) * 2, "estimated_output_bytes": 256 * 1024 * 1024},
        "runtime_binding": {"runtime_v4": record(RUNTIME_V4, "runtime v4"), "runtime_v2": record(RUNTIME_V2, "runtime v2"), "dispatch_v4": record(DISPATCH_V4, "dispatch v4"), "strict_v4": record(STRICT_V4, "strict v4")},
        "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "canonical_ready": True, "launch": True, "launch_allowed": True, "execution_allowed": True, "launch_owner": "root", "primary_launch_owner": "root", "shared_lease_required": True, "foreign_process_protection_required": True,
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "request_note": "Forward all-118 typed mass impact stream. Revalidates each completed scan receipt exact H5 path, launch/end digest metadata, size/mtime, case command, and output root without opening or hashing H5. Uses existing typed/native joins; 0.003 is only a mass visibility screen; per-MK/static and dynamics remain UNKNOWN.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": sha256(manifest_path), "request": str(request_path), "request_sha256": sha256(request_path), "source_input_count": len(unique), "guard_input_count": len(request_hashes), "h5_content_hash_performed": False}


def run(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path, manifest = read_json(manifest_path, "v2 impact manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_118_SOURCE_CLOSED_NO_H5":
        raise ImpactStreamV2Error("v2 manifest schema/status differs")
    for path_text, expected in manifest.get("input_sha256", {}).items():
        path = require_file(path_text, "v2 source input")
        if path.suffix.lower() in {".h5", ".hdf5"} or sha256(path) != expected:
            raise ImpactStreamV2Error(f"v2 source input changed or forbidden: {path}")
    closure = validate_manifest(Path(manifest["source_v1_manifest"]["path"]))
    v1 = load_v1()
    with tempfile.TemporaryDirectory(prefix="ds02-impact-stream-v2-") as directory:
        v1_output = Path(directory) / "v1.json"
        v1_result = v1.audit(closure["manifest_path"], v1_output)
        typed_impact = json.loads(v1_output.read_text(encoding="utf-8"))
    result = {
        "schema": OUTPUT_SCHEMA, "status": "TASK_IMPACT_STREAM_V2_SCAN_SOURCE_CLOSED_TYPED_MASS_SCREEN",
        "source_manifest": record(manifest_path, "v2 manifest"),
        "source_v1_audit": typed_impact,
        "producer_closure": {"case_count": len(closure["source_records"]), "family_case_counts": EXPECTED_FAMILIES, "h5_content_hash_performed": False, "h5_content_opened": False, "records": closure["source_records"]},
        "mass_screen": {"registered_gate_fraction": 0.003, "interpretation": "missing source-visible mass lower bound only; below gate is not dynamics credit and above gate is not a bounded error", "acceptance_granted": False},
        "per_mk_status": "UNKNOWN_REQUIRES_BOUND_STATIC_MK_AUDIT",
        "physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        "read_policy": {"h5_opened": False, "h5_content_hash_performed": False, "trajectory_content_opened": False, "solver_started": False, "partvtkout_started": False},
    }
    atomic_json(output_path.resolve(), result)
    return {"status": result["status"], "output": str(output_path.resolve()), "case_count": 118, "h5_content_hash_performed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare"); prep.add_argument("--output-dir", type=Path, required=True)
    runner = sub.add_parser("run"); runner.add_argument("--manifest", type=Path, required=True); runner.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.output_dir) if args.action == "prepare" else run(args.manifest, args.output)
    except ImpactStreamV2Error as exc:
        raise SystemExit(f"ImpactStreamV2Error: {exc}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
