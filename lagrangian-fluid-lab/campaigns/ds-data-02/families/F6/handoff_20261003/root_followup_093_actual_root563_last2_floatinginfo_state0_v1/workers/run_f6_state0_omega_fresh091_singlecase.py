#!/usr/bin/env python3
"""Root-only single-case FloatingInfo state-zero corroboration for F6 fresh091.

The request JSON is disabled in this source package.  Root may execute an
independent enabled copy only after the corresponding Root563 native receipt is
terminal completed/0.  This worker runs the official FloatingInfo binary for
one case, reads a bounded CSV prefix through the fresh091 audit worker, and
records observed omega.  V0=0 does not prove zero angular velocity. It never launches DualSPHysics, opens BI4/H5 files,
or infers angular state from particle V0.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
import subprocess
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA = "ds02.f6.fresh091.floatinginfo-state0-request.v1"
AUDIT_SCHEMA = "ds02.f6.endpoint-floatinginfo-state0-omega-audit-result.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--floating-info-exe", type=Path)
    args = parser.parse_args()
    request = load(args.request)
    require(request.get("schema") == EXPECTED_SCHEMA, "fresh091 request schema mismatch")
    require(request.get("case_count") == 1, "single-case worker requires case_count=1")
    require(request.get("disabled") is False and request.get("execution_allowed") is True,
            "source request is disabled; Root must enable an isolated copy before execution")
    require(request.get("launch_owner") == "root" and request.get("root_only") is True,
            "FloatingInfo worker is Root-only")
    case = request.get("case")
    require(isinstance(case, dict), "request lacks one case object")
    for key in ("case_id", "native_data", "endpoint_xml", "canonical_owner", "solver_receipt", "declared_omega_rad_s", "future_outputs"):
        require(key in case, f"single case lacks {key}")
    contract = request.get("expected_native_contract")
    require(isinstance(contract, dict), "expected native contract missing")
    require(contract.get("dimension") == 3 and contract.get("total") == 417505,
            "unexpected native dimension/count contract")
    require(contract.get("fluid") == 327680 and contract.get("fixed") == 73441 and contract.get("floating") == 16384,
            "unexpected native count contract")
    require(contract.get("floating_type") == 2 and contract.get("floating_mk") == 60,
            "unexpected floating identity contract")
    mass = request.get("mass_policy")
    require(isinstance(mass, dict) and mass.get("physical_mass_kg") == 128.0 and
            mass.get("native_support_mass_kg") == 256.0 and mass.get("normalization") == "none",
            "mass semantics are missing or normalized")
    omega = case["declared_omega_rad_s"]
    require(isinstance(omega, list) and len(omega) == 3 and all(math.isfinite(float(v)) for v in omega),
            "declared angular velocity must be a finite 3-vector")
    receipt_path = Path(str(case["solver_receipt"]))
    require(receipt_path.is_file(), f"native solver receipt is missing: {receipt_path}")
    receipt = load(receipt_path)
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0,
            "Root563 native receipt is not completed/0")
    binary = args.floating_info_exe or Path(str(request["floatinginfo_binary"]))
    require(binary.is_file(), f"official FloatingInfo binary is missing: {binary}")
    expected_binary_sha = request.get("floatinginfo_binary_sha256")
    if expected_binary_sha:
        require(sha256(binary) == expected_binary_sha, "official FloatingInfo binary hash mismatch")
    output_dir = args.output_dir
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=False, exist_ok=False)
    savedata = output_dir / "FloatingInfo"
    command = [str(binary), "-dirdata", str(case["native_data"]), "-first:0", "-last:1",
               "-onlymk:60", "-savemotion:1", "-csvsep:0", "-savedata", str(savedata)]
    subprocess.run(command, cwd=output_dir, check=True)
    csvs = sorted(output_dir.glob("*.csv"))
    require(len(csvs) == 1, f"expected one official FloatingInfo CSV, found {csvs}")
    audit_path = Path(str(case["future_outputs"]["audit"]))
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_worker_path = Path(str(request["audit_worker"]))
    spec = importlib.util.spec_from_file_location("f6_fresh091_state0_audit", audit_worker_path)
    require(spec is not None and spec.loader is not None, "cannot load fresh091 audit worker")
    audit_worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_worker)
    result = audit_worker.audit(csvs[0], Path(str(case["endpoint_xml"])),
                               Path(str(case["canonical_owner"])), receipt_path,
                               max_rows=4, omega_tolerance=audit_worker.OMEGA_TOLERANCE_DEFAULT)
    require(result.get("schema") == AUDIT_SCHEMA, "audit schema mismatch")
    result["case_id"] = case["case_id"]
    result["official_export_command"] = command
    result["source_request"] = str(args.request)
    result["claim_boundary"] = request["claim_boundary"]
    audit_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "schema": "ds02.f6.fresh091.single-case-floatinginfo-state0-summary.v1",
        "case_id": case["case_id"],
        "status": result.get("status"),
        "audit": str(audit_path),
        "audit_sha256": sha256(audit_path),
        "observed_omega_rad_s": result.get("observed_state0_angular_velocity_rad_s"),
        "expected_omega_rad_s": result.get("expected_angular_velocity_rad_s"),
        "claim_boundary": request["claim_boundary"],
    }
    summary_path = Path(str(case["future_outputs"]["summary"]))
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
