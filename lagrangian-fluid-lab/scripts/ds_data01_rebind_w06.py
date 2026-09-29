#!/usr/bin/env python3
"""Bind the existing W06 rotating-pour exploration to DS-DATA-01 as F2 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np


LAB_ROOT = Path(__file__).resolve().parents[1]
OLD_ROOT = LAB_ROOT / "campaigns" / "v0.1-candidate"
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"
REPORT = OLD_ROOT / "w06-rotating-pour.json"
SCRIPT = LAB_ROOT / "scripts" / "w06_rotating_pour.py"


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def h5_audit(path: Path) -> dict[str, Any]:
    required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk"}
    with h5py.File(path, "r") as h5:
        missing = sorted(required - set(h5.keys()))
        valid = h5["valid"][:]
        mass = h5["mass"][:]
        active = valid
        initial = valid[0]
        final = valid[-1]
        common = initial & final
        return {
            "status": "Q-I-structure-pass" if not missing and np.all(np.diff(h5["time"][:]) > 0) and np.isfinite(h5["position"][:][active]).all() and np.isfinite(h5["velocity"][:][active]).all() and np.isfinite(h5["density"][:][active]).all() and np.isfinite(h5["pressure"][:][active]).all() and np.all(mass[active] > 0) else "Q-I-structure-fail",
            "missing": missing,
            "sha256": digest(path),
            "time_count": int(len(h5["time"])),
            "time_start": float(h5["time"][0]),
            "time_end": float(h5["time"][-1]),
            "valid_shape": list(valid.shape),
            "active_initial": int(initial.sum()),
            "active_final": int(final.sum()),
            "identity_retention": float(common.sum() / max(1, initial.sum())),
            "initial_missing_at_final": int((initial & ~final).sum()),
            "zones": sorted(int(value) for value in np.unique(h5["particle_zone"])),
            "mass_positive_active": bool(np.all(mass[active] > 0)),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=CAMPAIGN_ROOT / "D02_F2_W06_REUSE_RECEIPT.json")
    args = parser.parse_args()
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    cases = []
    for case_id, result in sorted(report["cases"].items()):
        generated = OLD_ROOT / "artifacts" / "w06" / case_id / "generated"
        data = OLD_ROOT / "data" / "w06" / f"{case_id}.h5"
        latest = OLD_ROOT / "runs" / case_id / "latest.json"
        latest_payload = json.loads(latest.read_text(encoding="utf-8"))
        attempt = Path(latest_payload["attempt_directory"])
        if not attempt.is_absolute():
            attempt = OLD_ROOT / attempt
        cases.append(
            {
                "case_id": case_id,
                "family": "F2",
                "mechanism": "derived rotating-cup pour/catch",
                "derivation_status": "custom_derived_not_official_raw_case",
                "geometry": result["geometry"],
                "state": result["state"],
                "control": {
                    "duration_s": result["duration"],
                    "receiver_x_m": result["receiver_x"],
                    "receiver_y_m": result["receiver_y"],
                    "angle_degrees": result["angle"],
                },
                "definition_xml": str((generated / f"{case_id}.xml").relative_to(LAB_ROOT)),
                "definition_sha256": digest(generated / f"{case_id}.xml"),
                "motion_file": str((generated / f"{case_id}_motion.dat").relative_to(LAB_ROOT)),
                "motion_sha256": digest(generated / f"{case_id}_motion.dat"),
                "derivation_script": str(SCRIPT.relative_to(LAB_ROOT)),
                "derivation_script_sha256": digest(SCRIPT),
                "latest_run_receipt": str(latest.relative_to(LAB_ROOT)),
                "latest_run_receipt_sha256": digest(latest),
                "attempt_directory": str(attempt.relative_to(LAB_ROOT)),
                "hdf5": str(data.relative_to(LAB_ROOT)),
                "hdf5_audit": h5_audit(data),
                "mechanism_audit": result,
                "status": "candidate_reuse_pending_D03" if result["final_mass_fraction"]["numerically_missing"] == 0 else "diagnostic_missing_mass_requires_scope_audit",
                "learning_attempts": 0,
            }
        )
    receipt = {
        "schema": "ds-data-01.d02.f2-w06-reuse-receipt.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "historical_scope": report["scope"],
        "source_report": str(REPORT.relative_to(LAB_ROOT)),
        "source_report_sha256": digest(REPORT),
        "derivation_script_sha256": digest(SCRIPT),
        "case_count": len(cases),
        "learning_attempts": 0,
        "interpretation": "The 12 actual rotating-pour runs provide F2 mechanism evidence. They are custom-derived rather than official raw examples and require the DS-DATA-01 D03 closed/open lifecycle audit before production reuse.",
        "cases": cases,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "q_i_pass": sum(c["hdf5_audit"]["status"] == "Q-I-structure-pass" for c in cases), "output": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
