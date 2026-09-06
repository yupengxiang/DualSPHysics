#!/usr/bin/env python3
"""Normalize and audit the coarse probes derived from official examples."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

try:
    from .postprocess_cases import LAB_ROOT, normalize
except ImportError:  # Direct script execution.
    from postprocess_cases import LAB_ROOT, normalize


RUN_ROOT = LAB_ROOT / "runs-official"
DATA_ROOT = LAB_ROOT / "data-official"
RUN_SUMMARY = LAB_ROOT / "reports" / "runtime" / "official-run-summary.json"
PREPARE_SUMMARY = LAB_ROOT / "reports" / "runtime" / "official-prepare-summary.json"
AUDIT_REPORT = LAB_ROOT / "reports" / "runtime" / "official-trajectory-audit.json"
BIN = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
PARTVTK = BIN / "PartVTK_linux64"


def convert(record):
    run_dir = RUN_ROOT / record["id"]
    input_dir = run_dir if record.get("solver_flags") == ["-vres"] else run_dir / "data"
    prefix = run_dir / "csv" / "Particles"
    prefix.parent.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN}:{env.get('LD_LIBRARY_PATH', '')}"
    proc = subprocess.run([
        str(PARTVTK), "-dirdata", str(input_dir), "-savecsv", str(prefix),
        "-onlytype:-all,+fluid,+floating",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone", "-csvsep:1",
    ], cwd=LAB_ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (run_dir / "partvtk.stdout.log").write_text(proc.stdout)
    if proc.returncode:
        raise RuntimeError(f"PartVTK failed for {record['id']}: see {run_dir / 'partvtk.stdout.log'}")
    return sorted(prefix.parent.glob("Particles_[0-9][0-9][0-9][0-9].csv"))


def main():
    runs = json.loads(RUN_SUMMARY.read_text())
    prepared = json.loads(PREPARE_SUMMARY.read_text())
    prepared_by_id = {record["id"]: record for record in prepared["cases"]}
    audits = []
    for record in runs["cases"]:
        if record["status"] != "completed":
            continue
        record = {**record, "shifting": prepared_by_id.get(record["id"], {}).get("shifting")}
        csv_paths = convert(record)
        audit = normalize(record, csv_paths, run_root=RUN_ROOT, data_root=DATA_ROOT)
        audits.append(audit)
        print(f"{record['id']:26s} frames={audit['frames']:2d} ids={audit['particle_ids']:6d} "
              f"ret={audit['identity_retention']:.3f} mean_dx={audit['mean_displacement']:.3f}")
    report = {
        "schema_version": 1,
        "case_count": len(audits),
        "all_identity_retained": all(a["identity_retention"] == 1.0 for a in audits),
        "cases": audits,
    }
    AUDIT_REPORT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"normalized={len(audits)} all_identity_retained={report['all_identity_retained']}")


if __name__ == "__main__":
    main()
