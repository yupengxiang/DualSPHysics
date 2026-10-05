#!/usr/bin/env python3
"""Root-only official FloatingInfo state-0 corroboration for five F6 Root146 variants."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

AUDIT_WORKER = Path(__file__).with_name("audit_f6_endpoint_floatinginfo_state0_fresh075.py")
EXPECTED_SCHEMA = "ds02.f6.stage1-omega-internal-floatinginfo-state0-binding.v3"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--floating-info-exe", type=Path)
    args = parser.parse_args()
    binding = load(args.binding)
    if binding.get("schema") != EXPECTED_SCHEMA or binding.get("status") != "source_only_disabled_actual_root146_bound":
        raise RuntimeError("state0 binding is not the disabled fresh075 Root146 contract")
    if binding.get("launch_allowed") is not False:
        raise RuntimeError("state0 binding is launchable")
    binary = args.floating_info_exe or Path(str(binding["floatinginfo_binary"]))
    if not binary.is_file():
        raise RuntimeError(f"FloatingInfo binary is missing: {binary}")
    expected_binary_hash = str(binding.get("floatinginfo_binary_sha256", ""))
    if expected_binary_hash and sha256(binary) != expected_binary_hash:
        raise RuntimeError("FloatingInfo binary hash mismatch")
    spec = importlib.util.spec_from_file_location("f6_state0_audit", AUDIT_WORKER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load state0 audit worker: {AUDIT_WORKER}")
    audit_worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_worker)
    output_dir = args.output_dir
    output_dir.mkdir(parents=False, exist_ok=False)
    results = []
    for case in binding["cases"]:
        case_id = str(case["case_id"])
        case_dir = output_dir / case_id
        case_dir.mkdir()
        command = [
            str(binary), "-dirdata", str(case["native_data"]),
            "-first:0", "-last:1", "-onlymk:60", "-savemotion:1",
            "-csvsep:0", "-savedata", str(case_dir / "FloatingInfo"),
        ]
        subprocess.run(command, cwd=case_dir, check=True)
        csvs = sorted(case_dir.glob("*.csv"))
        if len(csvs) != 1:
            raise RuntimeError(f"expected one official FloatingInfo CSV for {case_id}, found {csvs}")
        audit_path = case_dir / "state0-omega-audit.json"
        result = audit_worker.audit(
            csvs[0],
            Path(str(case["endpoint_xml"])),
            Path(str(case["canonical_owner"])),
            Path(str(case["solver_receipt"])),
            max_rows=4,
            omega_tolerance=audit_worker.OMEGA_TOLERANCE_DEFAULT,
        )
        result["official_export_command"] = command
        result["case_id"] = case_id
        audit_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if result.get("status") != "pass":
            raise RuntimeError(f"state0 omega audit failed for {case_id}: {result.get('checks')}")
        results.append({
            "case_id": case_id,
            "status": result["status"],
            "expected_omega_rad_s": result["expected_angular_velocity_rad_s"],
            "observed_omega_rad_s": result["observed_state0_angular_velocity_rad_s"],
            "audit": str(audit_path),
            "audit_sha256": sha256(audit_path),
        })
    summary = {
        "schema": "ds02.f6.stage1-omega-internal-state0-summary.v1",
        "cases": results,
        "all_cases_passed": True,
        "q_n": "not_granted",
        "precision_status": "not_accepted",
        "production_approval": "none",
        "independent_case_count_increment": 0,
        "claim_boundary": "case-specific FloatingInfo state0 corroboration only; V0=0 is not used to infer zero angular velocity",
    }
    (output_dir / "five-endpoint-omega-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

