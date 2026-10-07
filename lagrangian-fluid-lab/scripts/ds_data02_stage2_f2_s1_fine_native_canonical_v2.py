#!/usr/bin/env python3
"""Prepare the root-launchable, source-bound fine F2 PartVTKOut request.

The v1 request is retained byte-for-byte.  This forward-only generator makes
an explicitly versioned v2 request from that request and the no-H5 raw-input
scope sidecar.  It does not run PartVTKOut, read trajectory ``Part_*.bi4``
content, or launch a solver.  The only exclusion-particle input is the native
``PartOut_000.obi4`` container; ``RunPARTs.csv`` and ``Run.out`` are bound for
the time and printed-position cross-check.  A full raw-directory pre/post
hash is reported as a cost when a guard policy requests it, but is never
performed by this preparation step.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V1_CASE = "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V1"
V2_CASE = "F2_S1_FINE_NATIVE_IMPACT_AUDIT_V2"
V2_ATTEMPT = "f2-s1-fine-native-impact-v2"
PHYSICAL_CASE = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
FINE_CASE = "F2_S1_FINE_FULL_REFERENCE_DP00855_T4_SAME_CFL_DENSE"
SCOPE_SCHEMA = "ds02.stage2.f2-s1-fine-native-input-scope.v1"


class CanonicalError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise CanonicalError(f"{label} is missing: {path}")
    return path


def require_dir(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise CanonicalError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CanonicalError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CanonicalError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _command_value(command: list[Any], flag: str) -> str:
    try:
        index = command.index(flag)
        return str(command[index + 1])
    except (ValueError, IndexError) as exc:
        raise CanonicalError(f"fine request command lacks {flag}") from exc


def build(v1_path: Path, scope_path: Path, output: Path, evidence: Path | None) -> dict[str, Any]:
    v1_path, v1 = read_json(v1_path, "fine v1 request")
    scope_path, scope = read_json(scope_path, "fine input-scope sidecar")
    if v1.get("schema") != "ds02.request.v1" or v1.get("case_id") != V1_CASE:
        raise CanonicalError("input request is not the preserved fine PartVTKOut v1 request")
    if v1.get("family_id") != "F2" or v1.get("physical_case_id") != PHYSICAL_CASE:
        raise CanonicalError("fine v1 physical identity differs")
    command = v1.get("command")
    if not isinstance(command, list) or not command or Path(str(command[0])).name != "PartVTKOut_linux64":
        raise CanonicalError("fine v1 command is not official PartVTKOut")
    if "-threads:1" in command or "-threads" in command:
        raise CanonicalError("unsupported PartVTKOut threads flag is present")
    if command != [
        command[0], "-dirdata", _command_value(command, "-dirdata"),
        "-savecsv", "{attempt_root}/PartOut.csv",
        "-saveresume", "{attempt_root}/resume.csv",
        "-createdirs:1", "-csvsep:1",
    ]:
        raise CanonicalError("fine v1 command differs from the registered native argv")
    if scope.get("schema") != SCOPE_SCHEMA or scope.get("status") != "CANONICAL_READY_METADATA_SCOPE":
        raise CanonicalError("input-scope sidecar is not the completed no-H5 scope")
    if scope.get("request", {}).get("sha256") != sha256(v1_path):
        raise CanonicalError("scope sidecar is bound to a different v1 request")
    if scope.get("source_solver_case_id") != FINE_CASE or scope.get("physical_case_id") != PHYSICAL_CASE:
        raise CanonicalError("scope sidecar source identity differs")
    raw_root = require_dir(_command_value(command, "-dirdata"), "fine raw data root")
    source_receipt = require_file(v1.get("source_solver_receipt", ""), "fine solver receipt")
    solver = json.loads(source_receipt.read_text(encoding="utf-8"))
    if solver.get("schema") != "ds02.execution-receipt.v1" or solver.get("status") != "completed" or solver.get("returncode") != 0:
        raise CanonicalError("fine source solver receipt is not completed code 0")
    solver_request = solver.get("request", {})
    if solver_request.get("family_id") != "F2" or solver_request.get("request_case_id", solver_request.get("case_id")) != FINE_CASE:
        raise CanonicalError("fine source solver request identity differs")
    required = scope.get("required_decoder_inputs")
    if not isinstance(required, list) or {str(item.get("role")) for item in required} != {"PartOut_000.obi4", "RunPARTs.csv", "Run.out"}:
        raise CanonicalError("scope sidecar does not describe the three bound native inputs")
    input_files = [str(item) for item in v1.get("input_files", [])]
    input_digests = dict(v1.get("input_sha256", {}))
    # The v1 request's small-file bindings are rechecked.  This is deliberate:
    # the v2 request cannot turn an unrelated raw run with the same IDs into a
    # valid join.
    for item in required:
        path = require_file(item.get("path", ""), str(item.get("role", "small raw input")));
        key = str(path)
        if key not in input_files or input_digests.get(key) != sha256(path):
            raise CanonicalError(f"v1 small raw binding differs: {path}")
    trajectory = scope.get("trajectory_inventory", {})
    trajectory_bytes = int(trajectory.get("total_bytes", -1))
    trajectory_count = int(trajectory.get("file_count", -1))
    if trajectory_count != 801 or trajectory_bytes < 0 or trajectory.get("content_hash_performed") is not False:
        raise CanonicalError("trajectory inventory is not the registered 801-file no-hash inventory")
    scope_path = scope_path.resolve()
    script_key = str(SCRIPT)
    scope_key = str(scope_path)
    if script_key not in input_files:
        input_files.append(script_key)
    if scope_key not in input_files:
        input_files.append(scope_key)
    input_digests[script_key] = sha256(SCRIPT)
    input_digests[scope_key] = sha256(scope_path)
    request = copy.deepcopy(v1)
    request.update({
        "case_id": V2_CASE,
        "attempt_id": V2_ATTEMPT,
        "request_version": 2,
        "canonical_ready": True,
        "input_files": input_files,
        "input_sha256": input_digests,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_disabled": False,
        "foreign_process_protection_required": True,
        "shared_lease_required": True,
        "supersedes": {"path": str(v1_path), "sha256": sha256(v1_path), "reason": "preserved v1; v2 adds explicit raw scope and root launch metadata"},
        "raw_input_scope": {
            "required_excluded_particles": {
                "path": next(str(item["path"]) for item in required if item.get("role") == "PartOut_000.obi4"),
                "role": "official PartVTKOut native PartOut exclusion container",
                "content_hash_required_by_request": True,
            },
            "required_crosscheck_files": [
                next(str(item["path"]) for item in required if item.get("role") == role)
                for role in ("RunPARTs.csv", "Run.out")
            ],
            "trajectory_inventory": {
                "glob": "Part_*.bi4",
                "file_count": trajectory_count,
                "total_bytes": trajectory_bytes,
                "content_hash_performed": False,
                "content_hash_cost_if_guard_pre_hashes_raw_tree_bytes": trajectory_bytes,
                "content_hash_cost_if_guard_pre_post_hashes_raw_tree_bytes": trajectory_bytes * 2,
                "request_input_files_include_trajectory": False,
            },
            "scope_sidecar": {"path": str(scope_path), "sha256": sha256(scope_path)},
        },
        "request_note": (
            "Canonical-ready root-owned official PartVTKOut audit for the completed fine F2 run. "
            "Only PartOut_000.obi4 is the native exclusion-particle input; RunPARTs.csv and Run.out "
            "are bound cross-check sources. No H5, solver, CFD, or model is run. Full raw trajectory "
            "pre/post hashing is not performed here and its byte cost is recorded explicitly."
        ),
    })
    request["input_files"] = sorted(set(request["input_files"]))
    request["input_sha256"] = {str(key): input_digests[str(key)] for key in request["input_files"]}
    request["qualification_claim"] = "none; native exclusion accounting and typed mass visibility lower bound only"
    request["physical_fate"] = "UNKNOWN"
    request["dynamical_impact"] = "UNKNOWN"
    if output.exists():
        old = json.loads(output.read_text(encoding="utf-8"))
        if old != request:
            raise CanonicalError(f"refusing to overwrite existing canonical request: {output}")
    else:
        atomic_json(output, request)
    report = {
        "schema": "ds02.stage2.f2-s1-fine-native-canonical-v2.v1",
        "status": "CANONICAL_READY",
        "request": {"path": str(output.resolve()), "sha256": sha256(output), "case_id": V2_CASE, "attempt_id": V2_ATTEMPT},
        "preserved_v1_request": {"path": str(v1_path), "sha256": sha256(v1_path)},
        "scope_sidecar": {"path": str(scope_path), "sha256": sha256(scope_path)},
        "native_excluded_particles_input": {
            "path": request["raw_input_scope"]["required_excluded_particles"]["path"],
            "sha256": input_digests[request["raw_input_scope"]["required_excluded_particles"]["path"]],
        },
        "crosscheck_inputs": [
            {"path": path, "sha256": input_digests[path]}
            for path in request["raw_input_scope"]["required_crosscheck_files"]
        ],
        "trajectory_inventory": request["raw_input_scope"]["trajectory_inventory"],
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "solver_started": False, "partvtkout_started": False},
        "qualification": {"physical_fate": "UNKNOWN", "dynamical_impact": "UNKNOWN", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
    }
    if evidence is not None:
        atomic_json(evidence, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-request", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        report = build(args.v1_request, args.scope, args.output, args.evidence)
    except CanonicalError as exc:
        raise SystemExit(f"CanonicalError: {exc}")
    print(json.dumps({"status": report["status"], "request": report["request"], "evidence": str(args.evidence.resolve()) if args.evidence else None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
