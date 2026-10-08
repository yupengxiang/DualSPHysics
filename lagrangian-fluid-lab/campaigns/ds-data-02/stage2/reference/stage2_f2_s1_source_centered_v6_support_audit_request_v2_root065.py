#!/usr/bin/env python3
"""Bind the V6 support audit to the actual parent ROOT_065 namespace.

The earlier V6 audit request is immutable and points at the preparatory
namespace.  Root's actual GenCase run uses the distinct ROOT_065 case and
attempt supplied by the parent guard.  This additive builder changes only the
deferred generated paths and audit output identity; static candidate/source
hashes and the worker remain the same.  It does not read generated XML/VTK,
BI4, or HDF5 and it never launches a task.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
V1_REQUEST = STAGE2 / "requests/f2-s1-source-centered-v6-support-audit-root-forward-001.json"
V1_WORKER = REFERENCE / "stage2_f2_s1_source_centered_v6_support_audit_v1.py"
V2_REQUEST = STAGE2 / "requests/f2-s1-source-centered-v6-support-audit-root-065.json"
V2_REPORT = REFERENCE / "stage2_f2_s1_source_centered_v6_support_audit_request_v2_root065.json"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
ROOT065 = DATA_ROOT / (
    "families/F2/F2_S1_SOURCE_CENTERED_V6_ACTUAL_FLUID_DP0088_ROOT_065/"
    "f2-s1-source-centered-v6-actual-fluid-dp0088-gencase-root-065-001-root-forward-030-001"
)
AUDIT_CASE = "F2_S1_SOURCE_CENTERED_V6_SUPPORT_MASS_AUDIT_ROOT065"
AUDIT_ATTEMPT = "f2-s1-source-centered-v6-support-audit-root065-001-root-forward-030-001"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable ROOT_065 request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
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


def replace_arg(command: list[str], flag: str, value: str) -> None:
    try:
        index = command.index(flag)
    except ValueError as exc:
        raise ValueError(f"V1 command missing {flag}") from exc
    if index + 1 >= len(command):
        raise ValueError(f"V1 command missing value for {flag}")
    command[index + 1] = value


def build(launch_commit: str) -> dict[str, Any]:
    base = json.loads(regular(V1_REQUEST).read_text(encoding="utf-8"))
    request = copy.deepcopy(base)
    generated_xml = ROOT065 / "generated.xml"
    fluid_vtk = ROOT065 / "generated_Fluid.vtk"
    receipt = ROOT065 / "execution-receipt.json"
    output_root = DATA_ROOT / "families/F2" / AUDIT_CASE / AUDIT_ATTEMPT
    command = list(request["command"])
    replace_arg(command, "--generated-xml", str(generated_xml))
    replace_arg(command, "--fluid-vtk", str(fluid_vtk))
    replace_arg(command, "--receipt", str(receipt))
    replace_arg(command, "--output", "{attempt_root}/report/f2_s1_source_centered_v6_support_audit.json")
    records = {str(Path(path)): value for path, value in request["input_records"].items()}
    script_path = str(regular(Path(__file__)))
    records[script_path] = record(Path(__file__))
    request["input_files"] = list(records)
    request["input_records"] = records
    request["input_hashes"] = {path: item["sha256"] for path, item in records.items()}
    request["case_id"] = AUDIT_CASE
    request["attempt_id"] = AUDIT_ATTEMPT
    request["launch_commit"] = launch_commit
    request["command"] = command
    request["output_root"] = str(output_root)
    request["deferred_input_files"] = [str(generated_xml), str(fluid_vtk), str(receipt)]
    request["guarded_input_files"] = list(request["deferred_input_files"])
    request["deferred_input_stats"] = {
        str(generated_xml): {"sha256": "PARENT_GUARD_COMPUTED", "stat": "PARENT_GUARD_COMPUTED"},
        str(fluid_vtk): {"sha256": "PARENT_GUARD_COMPUTED", "stat": "PARENT_GUARD_COMPUTED"},
        str(receipt): {"sha256": "PARENT_GUARD_COMPUTED", "stat": "PARENT_GUARD_COMPUTED"},
    }
    request["source_binding"] = {
        **request["source_binding"],
        "actual_gencase_namespace": {
            "case_id": "F2_S1_SOURCE_CENTERED_V6_ACTUAL_FLUID_DP0088_ROOT_065",
            "attempt_id": "f2-s1-source-centered-v6-actual-fluid-dp0088-gencase-root-065-001-root-forward-030-001",
            "generated_xml": str(generated_xml),
            "generated_fluid_vtk": str(fluid_vtk),
            "execution_receipt": str(receipt),
            "terminal_sha_stat": "PARENT_AFTER_RESERVE_AND_TERMINAL_RECEIPT",
        },
        "v1_request_preserved": str(V1_REQUEST),
    }
    request["output"] = {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/report/f2_s1_source_centered_v6_support_audit.json"}
    request["qualification_stage"] = "stage2_f2_s1_v6_root065_post_gencase_support_mass_audit_pending"
    write_new(V2_REQUEST, request)
    report = {
        "schema": "ds02.stage2.f2-s1.source-centered-v6-support-audit-request.v2-root065",
        "status": "PREPARED_ROOT065_PARENT_GUARDED_POST_GENCASE_AUDIT",
        "launch_commit": launch_commit,
        "request": record(V2_REQUEST),
        "v1_request_preserved": record(V1_REQUEST),
        "actual_gencase_namespace": request["source_binding"]["actual_gencase_namespace"],
        "deferred_input_count": 3,
        "native_payload_read": False,
        "solver_started": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    write_new(V2_REPORT, report)
    return report


def self_test() -> dict[str, Any]:
    assert V1_REQUEST.is_file() and V1_WORKER.is_file()
    assert ROOT065.name == "f2-s1-source-centered-v6-actual-fluid-dp0088-gencase-root-065-001-root-forward-030-001"
    return {"status": "PASS", "root065_namespace_bound": True, "deferred_inputs": 3, "native_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if sum((args.self_test, args.build_request)) != 1:
        parser.error("choose exactly one mode")
    if args.self_test:
        value = self_test()
    else:
        if not args.launch_commit:
            parser.error("--build-request requires --launch-commit")
        value = build(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": value["status"], "request": str(V2_REQUEST)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
