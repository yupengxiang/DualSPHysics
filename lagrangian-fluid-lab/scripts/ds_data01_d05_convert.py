#!/usr/bin/env python3
"""Convert completed D05 internal-batch BI4 outputs to audited HDF5.

This stage is read-only with respect to the solver: it invokes PartVTK only
after a completed D05 receipt, then writes a local normalized trajectory and a
compact conversion receipt.  It never starts a learner or a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any

import h5py
import numpy as np

from trajectory_io import convert_streaming


LAB_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_ROOT = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4"
BIN_ROOT = OFFICIAL_ROOT / "bin" / "linux"
PARTVTK = BIN_ROOT / "PartVTK_linux64"
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01" / "d05"
NORMALIZED_ROOT = CAMPAIGN_ROOT / "normalized"
RUN_SUMMARY = CAMPAIGN_ROOT / "run-summary.json"
CONVERSION_SUMMARY = CAMPAIGN_ROOT / "conversion-summary.json"


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def tree_digest(root: Path, ignored_top: tuple[str, ...] = ()) -> tuple[str | None, int, int]:
    if not root.exists():
        return None, 0, 0
    value = hashlib.sha256()
    count = 0
    size = 0
    ignored = set(ignored_top)
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in ignored:
            continue
        value.update(relative.as_posix().encode())
        value.update(b"\0")
        value.update((digest(path) or "").encode())
        count += 1
        size += path.stat().st_size
    return value.hexdigest(), count, size


def plan_sha256() -> str:
    value = digest(LAB_ROOT / "campaigns" / "ds-data-01" / "D05_BATCH_PLAN.json")
    if value is None:
        raise RuntimeError("D05_BATCH_PLAN.json is missing")
    return value


def validate_run_record(case_id: str, run: dict[str, Any]) -> Path:
    if run.get("schema") != "ds-data-01.d05.run.v1":
        raise RuntimeError(f"{case_id}: unexpected run receipt schema")
    if run.get("release_role") != "internal_development_only":
        raise RuntimeError(f"{case_id}: run receipt is outside the D05 internal scope")
    if run.get("plan_sha256") != plan_sha256():
        raise RuntimeError(f"{case_id}: run receipt does not bind the current D05 plan")
    raw_value = run.get("raw_output_root")
    if not raw_value:
        raise RuntimeError(f"{case_id}: run receipt has no raw_output_root")
    root = (LAB_ROOT / raw_value).resolve()
    campaign_root = CAMPAIGN_ROOT.resolve()
    if not root.is_relative_to(campaign_root):
        raise RuntimeError(f"{case_id}: raw_output_root escapes the D05 evidence root")
    if not root.is_dir():
        raise RuntimeError(f"{case_id}: raw output directory is missing: {root}")
    raw_hash = tree_digest(root, ignored_top=("csv",))[0]
    if run.get("raw_tree_sha256") != raw_hash:
        raise RuntimeError(f"{case_id}: raw output hash changed or is not bound to the run receipt")
    return root


def partvtk(case_id: str, run_root: Path) -> tuple[list[Path], Path]:
    csv_root = run_root / "csv"
    csv_root.mkdir(parents=True, exist_ok=True)
    prefix = csv_root / "Particles"
    data_root = run_root / "data" if (run_root / "data").is_dir() else run_root
    log_path = run_root.parent / "partvtk.stdout.log"
    frames = sorted(csv_root.glob("Particles_[0-9][0-9][0-9][0-9].csv"))
    if not frames:
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = f"{BIN_ROOT}:{env.get('LD_LIBRARY_PATH', '')}"
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
        proc = subprocess.run(command, cwd=LAB_ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        log_path.write_text(proc.stdout, encoding="utf-8")
        if proc.returncode:
            raise RuntimeError(f"PartVTK failed for {case_id}: {proc.stdout[-1000:]}")
        frames = sorted(csv_root.glob("Particles_[0-9][0-9][0-9][0-9].csv"))
    if len(frames) < 2:
        raise RuntimeError(f"fewer than two converted frames for {case_id}")
    return frames, log_path


def audit(path: Path) -> dict[str, Any]:
    required = {"time", "particle_id", "particle_zone", "valid", "position", "velocity", "density", "mass", "pressure", "type", "mk"}
    with h5py.File(path, "r") as h5:
        missing = sorted(required - set(h5.keys()))
        if missing:
            return {"status": "schema_incomplete", "missing": missing, "sha256": digest(path)}
        time = h5["time"][:]
        valid = h5["valid"][:].astype(bool)
        position = h5["position"][:]
        velocity = h5["velocity"][:]
        density = h5["density"][:]
        pressure = h5["pressure"][:]
        mass = h5["mass"][:]
        active = valid
        finite = {
            "position": bool(np.isfinite(position[active]).all()),
            "velocity": bool(np.isfinite(velocity[active]).all()),
            "density": bool(np.isfinite(density[active]).all()),
            "pressure": bool(np.isfinite(pressure[active]).all()),
        }
        initial = valid[0]
        final = valid[-1]
        common = initial & final
        speed = np.linalg.norm(velocity[active], axis=1) if active.any() else np.empty(0)
        displacement = np.linalg.norm(position[-1, common] - position[0, common], axis=1) if common.any() else np.empty(0)
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
            "finite_active": finite,
            "positive_active_mass": bool(np.all(mass[active] > 0)),
            "density_min": float(np.nanmin(density[active])) if active.any() else None,
            "density_max": float(np.nanmax(density[active])) if active.any() else None,
            "max_speed": float(np.nanmax(speed)) if speed.size else None,
            "mean_displacement_common": float(displacement.mean()) if displacement.size else None,
            "max_displacement_common": float(displacement.max()) if displacement.size else None,
        }


def all_receipts(case_ids: list[str]) -> list[dict[str, Any]]:
    return [
        json.loads((CAMPAIGN_ROOT / case_id / "conversion-receipt.json").read_text(encoding="utf-8"))
        for case_id in case_ids
        if (CAMPAIGN_ROOT / case_id / "conversion-receipt.json").is_file()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="*", default=None)
    args = parser.parse_args()
    if not RUN_SUMMARY.is_file():
        raise SystemExit(f"missing completed D05 run summary: {RUN_SUMMARY}")
    run_summary = json.loads(RUN_SUMMARY.read_text(encoding="utf-8"))
    by_id = {item["case_id"]: item for item in run_summary["cases"]}
    case_ids = args.cases or list(by_id)
    NORMALIZED_ROOT.mkdir(parents=True, exist_ok=True)
    for case_id in case_ids:
        if case_id not in by_id:
            raise SystemExit(f"case missing from D05 run summary: {case_id}")
        run = by_id[case_id]
        if run.get("status") == "reference_reuse_only":
            result = {
                "schema": "ds-data-01.d05.conversion.v1",
                "case_id": case_id,
                "family": run.get("family", "F2"),
                "status": "reference_reuse_only",
                "release_role": "internal_development_only",
                "plan_sha256": plan_sha256(),
                "run_receipt_sha256": digest(CAMPAIGN_ROOT / case_id / "run-receipt.json"),
                "scientific_acceptance": "not_assessed",
                "split": "unassigned",
                "learning_attempts": 0,
            }
            receipt = CAMPAIGN_ROOT / case_id / "conversion-receipt.json"
            if receipt.exists():
                raise FileExistsError(f"refusing to overwrite existing D05 conversion receipt: {receipt}")
            atomic_write_json(receipt, result)
            print(case_id, result["status"])
            continue
        if run.get("status") != "completed":
            raise SystemExit(f"case is not completed: {case_id} ({run.get('status')})")
        run_root = validate_run_record(case_id, run)
        output = NORMALIZED_ROOT / f"{case_id}.h5"
        receipt = CAMPAIGN_ROOT / case_id / "conversion-receipt.json"
        if output.exists() or receipt.exists():
            raise FileExistsError(f"refusing to overwrite existing D05 conversion output for {case_id}")
        frames, log_path = partvtk(case_id, run_root)
        record = {"id": case_id, "family": run["family"], "mechanism": run["mechanism"], "shifting": 0}
        convert_streaming(record, frames, output)
        result = {
            "schema": "ds-data-01.d05.conversion.v1",
            "case_id": case_id,
            "family": run["family"],
            "mechanism": run["mechanism"],
            "release_role": "internal_development_only",
            "plan_sha256": plan_sha256(),
            "run_receipt_sha256": digest(CAMPAIGN_ROOT / case_id / "run-receipt.json"),
            "run_raw_tree_sha256": run.get("raw_tree_sha256"),
            "partvtk_binary_sha256": digest(PARTVTK),
            "partvtk_log": str(log_path.relative_to(LAB_ROOT)),
            "partvtk_log_sha256": digest(log_path),
            "csv_tree_sha256": tree_digest(run_root / "csv")[0],
            "csv_frame_count": len(frames),
            "normalized_hdf5": str(output.relative_to(LAB_ROOT)),
            "audit": audit(output),
            "scientific_acceptance": "not_assessed",
            "split": "unassigned",
            "converted_at_utc": datetime.now(timezone.utc).isoformat(),
            "learning_attempts": 0,
        }
        atomic_write_json(receipt, result)
        print(case_id, result["audit"]["status"], result["audit"]["valid_shape"])
    records = all_receipts(case_ids)
    atomic_write_json(CONVERSION_SUMMARY, {
        "schema": "ds-data-01.d05.conversion-summary.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "internal_development_only",
        "learning_attempts": 0,
        "cases": records,
    })
    q_i_pass = sum(item.get("audit", {}).get("status") == "Q-I-structure-pass" for item in records)
    print(json.dumps({"output": str(CONVERSION_SUMMARY), "cases": len(records), "q_i_structure_pass": q_i_pass}, ensure_ascii=False, indent=2))
    return 0 if all(item.get("status") == "reference_reuse_only" or item.get("audit", {}).get("status") == "Q-I-structure-pass" for item in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
