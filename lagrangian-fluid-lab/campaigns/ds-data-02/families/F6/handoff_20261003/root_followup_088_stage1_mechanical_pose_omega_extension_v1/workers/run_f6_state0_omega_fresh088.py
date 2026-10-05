#!/usr/bin/env python3
"""Root-only FloatingInfo state-0 corroboration for fresh088 F6 cases.

This runner is disabled source metadata until each Root229 native receipt is
terminal completed/0. It invokes the official FloatingInfo binary and the
bounded audit worker only after Root enables the request. It never launches a
solver, reads BI4/H5/particle arrays, or infers angular state from GenCase V0.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, subprocess
from pathlib import Path
from typing import Any

AUDIT_WORKER = Path(__file__).with_name("audit_f6_endpoint_floatinginfo_state0_fresh088.py")
EXPECTED_SCHEMA = "ds02.f6.endpoint-floatinginfo-state0-omega-binding.v1"
EXPECTED_STATUS = "source_only_disabled"

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict): raise RuntimeError(f"expected JSON object: {path}")
    return value

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--binding", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--floating-info-exe", type=Path)
    args = ap.parse_args()
    binding = load(args.binding)
    if binding.get("schema") != EXPECTED_SCHEMA or binding.get("status") != EXPECTED_STATUS:
        raise RuntimeError("fresh088 state0 binding schema/status mismatch")
    if binding.get("launch_allowed") is not False or binding.get("execution_allowed") is not False:
        raise RuntimeError("fresh088 state0 binding is launchable")
    binary = args.floating_info_exe or Path(str(binding["floatinginfo_binary"]))
    if not binary.is_file(): raise RuntimeError(f"FloatingInfo binary is missing: {binary}")
    expected = str(binding.get("floatinginfo_binary_sha256", ""))
    if expected and sha256(binary) != expected: raise RuntimeError("FloatingInfo binary hash mismatch")
    spec = importlib.util.spec_from_file_location("f6_state0_audit_fresh088", AUDIT_WORKER)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {AUDIT_WORKER}")
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    output_dir = args.output_dir
    output_dir.mkdir(parents=False, exist_ok=False)
    rows = []
    for case in binding["cases"]:
        case_id = str(case["case_id"]); case_dir = output_dir / case_id; case_dir.mkdir()
        command = [str(binary), "-dirdata", str(case["native_data"]), "-first:0", "-last:1", "-onlymk:60", "-savemotion:1", "-csvsep:0", "-savedata", str(case_dir / "FloatingInfo")]
        subprocess.run(command, cwd=case_dir, check=True)
        csvs = sorted(case_dir.glob("*.csv"))
        if len(csvs) != 1: raise RuntimeError(f"expected one official FloatingInfo CSV for {case_id}, found {csvs}")
        result = worker.audit(csvs[0], Path(str(case["endpoint_xml"])), Path(str(case["canonical_owner"])), Path(str(case["solver_receipt"])), max_rows=4, omega_tolerance=worker.OMEGA_TOLERANCE_DEFAULT)
        result["official_export_command"] = command; result["case_id"] = case_id
        audit_path = case_dir / "state0-omega-audit.json"
        audit_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if result.get("status") != "pass": raise RuntimeError(f"state0 omega audit failed for {case_id}: {result.get('checks')}")
        rows.append({"case_id": case_id, "status": result["status"], "expected_omega_rad_s": result["expected_angular_velocity_rad_s"], "observed_omega_rad_s": result["observed_state0_angular_velocity_rad_s"], "audit": str(audit_path), "audit_sha256": sha256(audit_path)})
    summary = {"schema": "ds02.f6.stage1-omega-full241-state0-summary.v1", "cases": rows, "all_cases_passed": True, "q_n": "not_granted", "precision_status": "not_accepted", "production_approval": "none", "independent_case_count_increment": 0, "claim_boundary": "case-specific FloatingInfo state0 corroboration only; V0=0 does not establish zero angular velocity"}
    (output_dir / "eight-endpoint-omega-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0
if __name__ == "__main__": raise SystemExit(main())
