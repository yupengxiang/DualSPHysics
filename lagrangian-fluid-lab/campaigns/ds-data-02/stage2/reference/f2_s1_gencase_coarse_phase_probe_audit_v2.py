#!/usr/bin/env python3
"""Audit bounded F2-S1 coarse phase probe XML and guard receipts.

This reads only the generated XML, request, receipt, and the v4 matrix's
recorded target mass.  It computes the initial fluid sample-mass gate and
retains each candidate's real count; it never reads generated.bi4, HDF5, or
starts a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.gencase-coarse-phase-probe-audit.v2"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV_PYTHON = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
MATRIX_OUTPUT = DATA_ROOT / "families/F2/F2_S1_REFERENCE_MATRIX_V4/f2-s1-reference-matrix-v4-001/f2-s1-reference-matrix-v4.json"
MANIFEST = Path(__file__).with_name("f2_s1_coarse_phase_probe_inputs_v2") / "manifest.json"
REQUEST_DIR = Path(__file__).resolve().parents[1] / "requests/f2-s1-coarse-phase-probe-v2"
PASS_RELATIVE = 0.01
HARD_UPPER_RELATIVE = 0.02


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def xml_mass(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    constants = {child.tag.split("}")[-1]: dict(child.attrib) for child in root.findall(".//execution/constants/*")}
    massfluid = float(constants["massfluid"]["value"])
    fluid_nodes = root.findall(".//execution/particles/fluid")
    blocks = [{"mkfluid": node.attrib.get("mkfluid"), "mk": node.attrib.get("mk"), "count": int(node.attrib["count"])} for node in fluid_nodes]
    count = sum(block["count"] for block in blocks)
    return {
        "generated_xml": file_record(path),
        "fluid_particle_count": count,
        "massfluid_kg": massfluid,
        "initial_fluid_sample_mass_kg": count * massfluid,
        "fluid_blocks": blocks,
    }


def gate(actual: dict[str, Any], target_mass: float) -> dict[str, Any]:
    relative = abs(actual["initial_fluid_sample_mass_kg"] - target_mass) / abs(target_mass)
    if relative <= PASS_RELATIVE:
        status = "PASS"
    elif relative <= HARD_UPPER_RELATIVE:
        status = "MARGINAL_OVER_PASS_GATE"
    else:
        status = "FAIL_HARD"
    return {
        "status": status,
        "target_initial_fluid_sample_mass_kg": target_mass,
        "actual_initial_fluid_sample_mass_kg": actual["initial_fluid_sample_mass_kg"],
        "relative_error": relative,
        "pass_relative_tolerance": PASS_RELATIVE,
        "hard_upper_relative_tolerance": HARD_UPPER_RELATIVE,
        "decision": "eligible for parent review only if PASS; no solver credit is granted by this audit",
    }


def build_audit(matrix_path: Path = MATRIX_OUTPUT) -> dict[str, Any]:
    matrix_path = require_file(matrix_path, "v4 matrix output")
    matrix = load_json(matrix_path)
    target_mass = float(matrix["preflight_initial_fluid_sample_mass_gate"]["reference"]["initial_fluid_sample_mass_kg"])
    manifest_path = require_file(MANIFEST, "coarse probe manifest")
    manifest = load_json(manifest_path)
    cases = []
    for record in manifest["cases"]:
        request_path = require_file(REQUEST_DIR / f"{record['case_id'].lower()}.json", "coarse probe request")
        request = load_json(request_path)
        attempt_root = DATA_ROOT / "families/F2" / record["case_id"] / request["attempt_id"]
        receipt_path = require_file(attempt_root / "execution-receipt.json", "coarse probe receipt")
        receipt = load_json(receipt_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
            raise RuntimeError(f"guard receipt not completed successfully: {receipt_path}")
        generated_xml = require_file(attempt_root / "generated.xml", "coarse probe generated XML")
        actual = xml_mass(generated_xml)
        cases.append({
            "case_id": record["case_id"],
            "dp_m": record["dp_m"],
            "physical_case_id": record["physical_case_id"],
            "same_origin_phase_policy": record["phase_policy"],
            "request": file_record(request_path),
            "receipt": file_record(receipt_path),
            "receipt_status": receipt["status"],
            "generated_xml": actual,
            "initial_fluid_sample_mass_gate": gate(actual, target_mass),
            "solver_started": False,
        })
    return {
        "schema": SCHEMA,
        "status": "PASS_AUDIT_COMPLETE",
        "qualification": "PRE_SOLVER_INPUT_EVIDENCE_ONLY",
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": manifest["physical_case_id"],
        "source": {"matrix_output": file_record(matrix_path), "manifest": file_record(manifest_path)},
        "target_initial_fluid_sample_mass_kg": target_mass,
        "gate_rule": {"pass_relative_tolerance": PASS_RELATIVE, "hard_upper_relative_tolerance": HARD_UPPER_RELATIVE},
        "cases": cases,
        "solver_started": False,
        "full_time_hdf5_read": False,
        "full_hdf5_rehash": False,
        "QI_QN_QE": "NOT_ASSESSED",
    }


def request_for(matrix_path: Path, output_path: Path) -> dict[str, Any]:
    root = REPO
    script = Path(__file__).resolve()
    matrix_path = require_file(matrix_path, "v4 matrix output")
    manifest_path = require_file(MANIFEST, "coarse probe manifest")
    inputs = [
        root / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch.py",
        root / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py",
        root / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        script,
        matrix_path,
        manifest_path,
    ]
    for record in load_json(manifest_path)["cases"]:
        request_path = require_file(REQUEST_DIR / f"{record['case_id'].lower()}.json", "coarse probe request")
        request = load_json(request_path)
        attempt_root = DATA_ROOT / "families/F2" / record["case_id"] / request["attempt_id"]
        inputs.extend([request_path, attempt_root / "execution-receipt.json", attempt_root / "generated.xml"])
    unique = []
    seen = set()
    for path in inputs:
        path = path.resolve()
        require_file(path, "audit input")
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    return {
        "schema": REQUEST_SCHEMA,
        "family_id": "F2",
        "case_id": "F2_S1_COARSE_PHASE_PROBE_AUDIT_V2",
        "attempt_id": "f2-s1-coarse-phase-probe-audit-v2-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "worktree_root": str(root),
        "cwd": str(root),
        "command": [VENV_PYTHON, str(script), "--run", "--matrix", str(matrix_path.resolve()), "--output", "{attempt_root}/f2-s1-coarse-phase-probe-audit-v2.json"],
        "input_files": [str(path) for path in unique],
        "input_hashes": {str(path): sha256_file(path) for path in unique},
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "ds_data02_stage2_dispatch.py",
            "strict_guard": "ds_data02_strict_dispatch_v1.py",
            "runtime": "ds_data02_runtime_v2.py",
            "launch_commit": git_commit(),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 2 * 300 / 3600,
        },
        "scope": {"xml_receipt_audit_only": True, "solver_started": False, "full_time_hdf5_read": False, "full_hdf5_hash": "forbidden_by_scope"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-request", type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--matrix", type=Path, default=MATRIX_OUTPUT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.emit_request is not None:
        request = request_for(args.matrix, args.emit_request)
        atomic_json(args.emit_request, request)
        print(json.dumps({"status": "PASS", "request": str(args.emit_request), "inputs": len(request["input_files"])}, ensure_ascii=False), flush=True)
        return 0
    if not args.run or args.output is None:
        raise SystemExit("choose --emit-request or --run with --output")
    value = build_audit(args.matrix)
    atomic_json(args.output, value)
    print(json.dumps({"status": "PASS", "output": str(args.output)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
