#!/usr/bin/env python3
"""Convert DS-DATA-01 canary BI4 outputs and run native HDF5 audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from typing import Any

import h5py
import numpy as np

from trajectory_io import convert_streaming, read_frame


LAB_ROOT = Path(__file__).resolve().parents[1]
BIN_ROOT = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
PARTVTK = BIN_ROOT / "PartVTK_linux64"
CANARY_ROOT = LAB_ROOT / "campaigns" / "ds-data-01" / "d02" / "canaries"
NORMALIZED_ROOT = LAB_ROOT / "campaigns" / "ds-data-01" / "d02" / "normalized"


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def partvtk(case_id: str, run_root: Path) -> tuple[list[Path], Path]:
    csv_root = run_root / "csv"
    csv_root.mkdir(parents=True, exist_ok=True)
    prefix = csv_root / "Particles"
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{BIN_ROOT}:{env.get('LD_LIBRARY_PATH', '')}"
    log_path = run_root.parent / "partvtk.stdout.log"
    data_root = run_root / "data" if (run_root / "data").is_dir() else run_root
    command = [
        str(PARTVTK),
        "-dirdata",
        str(data_root),
        "-savecsv",
        str(prefix),
        "-onlytype:-all,+fluid,+floating",
        "-vars:-all,+idp,+vel,+rhop,+press,+type,+mk,+mass,+zone",
        "-csvsep:1",
    ]
    if not list(csv_root.glob("Particles_[0-9][0-9][0-9][0-9].csv")):
        proc = subprocess.run(command, cwd=LAB_ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        log_path.write_text(proc.stdout, encoding="utf-8")
        if proc.returncode:
            raise RuntimeError(f"PartVTK failed for {case_id}: {proc.stdout[-1000:]}")
    frames = sorted(csv_root.glob("Particles_[0-9][0-9][0-9][0-9].csv"))
    if len(frames) < 2:
        raise RuntimeError(f"fewer than two converted frames for {case_id}")
    return frames, log_path


def audit(path: Path) -> dict[str, Any]:
    with h5py.File(path, "r") as h5:
        required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk"}
        missing = sorted(required - set(h5.keys()))
        if missing:
            return {"status": "schema_incomplete", "missing": missing, "sha256": digest(path)}
        time = h5["time"][:]
        valid = h5["valid"][:]
        active = valid
        position = h5["position"][:]
        velocity = h5["velocity"][:]
        density = h5["density"][:]
        pressure = h5["pressure"][:]
        mass = h5["mass"][:]
        initial = valid[0]
        final = valid[-1]
        common = initial & final
        finite = {
            "position": bool(np.isfinite(position[active]).all()),
            "velocity": bool(np.isfinite(velocity[active]).all()),
            "density": bool(np.isfinite(density[active]).all()),
            "pressure": bool(np.isfinite(pressure[active]).all()),
        }
        displacement = np.linalg.norm(position[-1, common] - position[0, common], axis=1) if common.any() else np.empty(0)
        speed = np.linalg.norm(velocity[active], axis=1) if active.any() else np.empty(0)
        return {
            "status": "Q-I-structure-pass" if np.all(np.diff(time) > 0) and all(finite.values()) and bool(np.all(mass[active] > 0)) else "Q-I-structure-fail",
            "sha256": digest(path),
            "time_count": int(len(time)),
            "time_start": float(time[0]),
            "time_end": float(time[-1]),
            "identity_count": int(len(h5["particle_id"])),
            "valid_shape": list(valid.shape),
            "active_initial": int(initial.sum()),
            "active_final": int(final.sum()),
            "identity_retention": float(common.sum() / max(1, initial.sum())),
            "introduced_after_initial": int((~initial & valid.any(axis=0)).sum()),
            "initial_missing_at_final": int((initial & ~final).sum()),
            "zones": sorted(int(value) for value in np.unique(h5["particle_zone"])),
            "finite_active": finite,
            "positive_active_mass": bool(np.all(mass[active] > 0)),
            "density_min": float(np.nanmin(density[active])) if active.any() else None,
            "density_max": float(np.nanmax(density[active])) if active.any() else None,
            "max_speed": float(np.nanmax(speed)) if speed.size else None,
            "mean_displacement_common": float(displacement.mean()) if displacement.size else None,
            "max_displacement_common": float(displacement.max()) if displacement.size else None,
        }


def existing_receipts(by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect every valid conversion receipt for the current canary run.

    Conversion may be run in subsets while the campaign is being built.  The
    manifest must remain cumulative rather than silently shrinking to the last
    subset passed on the command line.
    """
    receipts: dict[str, dict[str, Any]] = {}
    for receipt_path in sorted(CANARY_ROOT.glob("*/conversion-receipt.json")):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        case_id = receipt.get("case_id")
        if case_id in by_id:
            receipts[case_id] = receipt
    return [receipts[case_id] for case_id in by_id if case_id in receipts]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="*", required=True)
    args = parser.parse_args()
    run_summary = json.loads((CANARY_ROOT / "run-summary.json").read_text(encoding="utf-8"))
    by_id = {item["case_id"]: item for item in run_summary["cases"]}
    NORMALIZED_ROOT.mkdir(parents=True, exist_ok=True)
    for case_id in args.cases:
        if case_id not in by_id:
            raise SystemExit(f"case missing from run summary: {case_id}")
        case = by_id[case_id]
        if case["status"] != "completed":
            raise SystemExit(f"case is not completed: {case_id}")
        run_root = LAB_ROOT / case["raw_output_root"]
        frames, partvtk_log = partvtk(case_id, run_root)
        record = {"id": case_id, "family": case["family"], "mechanism": case["mechanism"], "shifting": 0}
        out_path = NORMALIZED_ROOT / f"{case_id}.h5"
        convert_streaming(record, frames, out_path)
        result = {
            "case_id": case_id,
            "family": case["family"],
            "mechanism": case["mechanism"],
            "partvtk_log": str(partvtk_log.relative_to(LAB_ROOT)),
            "partvtk_log_sha256": digest(partvtk_log),
            "csv_frame_count": len(frames),
            "csv_source_fingerprint": digest(frames[0]),
            "normalized_hdf5": str(out_path.relative_to(LAB_ROOT)),
            "audit": audit(out_path),
            "converted_at_utc": datetime.now(timezone.utc).isoformat(),
            "learning_attempts": 0,
        }
        (CANARY_ROOT / case_id / "conversion-receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(case_id, result["audit"]["status"], result["audit"]["valid_shape"])
    results = existing_receipts(by_id)
    if not results:
        raise SystemExit("no conversion receipts found")
    summary = {
        "schema": "ds-data-01.d02.canary-conversion.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "learning_attempts": 0,
        "cases": results,
    }
    output = CANARY_ROOT / "conversion-summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": len(results), "q_i_pass": sum(item["audit"]["status"] == "Q-I-structure-pass" for item in results)}, ensure_ascii=False, indent=2))
    return 0 if all(item["audit"]["status"] == "Q-I-structure-pass" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
