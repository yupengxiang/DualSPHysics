#!/usr/bin/env python3
"""Rebind existing official probe runs to DS-DATA-01 without rerunning them.

The old exploratory reports are treated as historical evidence. This script
creates a new hash-bound receipt and performs a read-only HDF5 integrity scan;
it does not invoke a solver, converter, or learner.
"""

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
OFFICIAL_ROOT = LAB_ROOT / "vendor" / "official" / "DualSPHysics_v5.4"
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"
PREPARE = LAB_ROOT / "reports" / "runtime" / "official-prepare-summary.json"
RUN = LAB_ROOT / "reports" / "runtime" / "official-run-summary.json"
AUDIT = LAB_ROOT / "reports" / "runtime" / "official-trajectory-audit.json"
RUN_ROOT = LAB_ROOT / "runs-official"
DATA_ROOT = LAB_ROOT / "data-official"
BIN_ROOT = OFFICIAL_ROOT / "bin" / "linux"

REQUIRED_DATASETS = {
    "time",
    "particle_id",
    "particle_zone",
    "valid",
    "position",
    "velocity",
    "density",
    "mass",
    "pressure",
    "type",
    "mk",
}


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def tree_digest(root: Path) -> tuple[str | None, int, int]:
    if not root.exists():
        return None, 0, 0
    h = hashlib.sha256()
    count = 0
    total = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        file_hash = digest(path)
        if file_hash is None:
            continue
        h.update(relative)
        h.update(b"\0")
        h.update(file_hash.encode())
        count += 1
        total += path.stat().st_size
    return h.hexdigest(), count, total


def hdf5_audit(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path.relative_to(LAB_ROOT)) if path.exists() else str(path),
        "sha256": digest(path),
        "exists": path.is_file(),
        "required_datasets": sorted(REQUIRED_DATASETS),
    }
    if not path.is_file():
        result.update({"status": "missing", "missing_datasets": sorted(REQUIRED_DATASETS)})
        return result
    try:
        with h5py.File(path, "r") as h5:
            present = set(h5.keys())
            missing = sorted(REQUIRED_DATASETS - present)
            result["missing_datasets"] = missing
            result["datasets"] = {
                name: {"shape": list(h5[name].shape), "dtype": str(h5[name].dtype)}
                for name in sorted(present)
                if hasattr(h5[name], "shape")
            }
            if missing:
                result["status"] = "schema_incomplete"
                return result
            time = np.asarray(h5["time"])
            valid = np.asarray(h5["valid"], dtype=bool)
            mass = np.asarray(h5["mass"])
            position = np.asarray(h5["position"])
            velocity = np.asarray(h5["velocity"])
            density = np.asarray(h5["density"])
            pressure = np.asarray(h5["pressure"])
            active = valid
            result.update(
                {
                    "time_monotonic": bool(np.all(np.diff(time) >= 0)),
                    "time_count": int(len(time)),
                    "time_start": float(time[0]) if len(time) else None,
                    "time_end": float(time[-1]) if len(time) else None,
                    "valid_shape": list(valid.shape),
                    "active_count_initial": int(active[0].sum()) if len(active) else 0,
                    "active_count_final": int(active[-1].sum()) if len(active) else 0,
                    "finite_active_position": bool(np.isfinite(position[active]).all()),
                    "finite_active_velocity": bool(np.isfinite(velocity[active]).all()),
                    "finite_active_density": bool(np.isfinite(density[active]).all()),
                    "finite_active_pressure": bool(np.isfinite(pressure[active]).all()),
                    "positive_active_mass": bool(np.all(mass[active] > 0)),
                    "identity_count": int(len(h5["particle_id"])),
                    "zone_values": sorted(int(value) for value in np.unique(h5["particle_zone"])),
                }
            )
            structural = [
                result["time_monotonic"],
                bool(valid.ndim == 2),
                result["finite_active_position"],
                result["finite_active_velocity"],
                result["finite_active_density"],
                result["finite_active_pressure"],
                result["positive_active_mass"],
            ]
            result["status"] = "Q-I-structure-pass" if all(structural) else "Q-I-structure-fail"
    except (OSError, ValueError, KeyError) as exc:
        result.update({"status": "read_error", "error": str(exc)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=CAMPAIGN_ROOT / "D02_OFFICIAL_REUSE_RECEIPT.json")
    args = parser.parse_args()
    prepared = json.loads(PREPARE.read_text(encoding="utf-8"))
    runs = json.loads(RUN.read_text(encoding="utf-8"))
    audits = json.loads(AUDIT.read_text(encoding="utf-8"))
    audit_by_id = {record["id"]: record for record in audits["cases"]}
    prepare_by_id = {record["id"]: record for record in prepared["cases"]}
    records = []
    for run_record in runs["cases"]:
        if run_record.get("status") != "completed":
            continue
        case_id = run_record["id"]
        prepared_record = prepare_by_id[case_id]
        source_root = OFFICIAL_ROOT / prepared_record["source"]
        source_tree_sha256, source_file_count, source_bytes = tree_digest(source_root)
        generated = LAB_ROOT / prepared_record["case_prefix"]
        run_root = RUN_ROOT / case_id
        output = DATA_ROOT / f"{case_id}.h5"
        raw_tree_sha256, raw_file_count, raw_bytes = tree_digest(run_root)
        h5 = hdf5_audit(output)
        prior_audit = audit_by_id.get(case_id, {})
        if h5.get("status") != "Q-I-structure-pass":
            scope_status = "reuse_rejected_schema_or_read_error"
        elif "inletoutlet" in prepared_record.get("source", "").lower() or "open-boundary" in run_record.get("mechanism", "").lower():
            scope_status = "diagnostic_open_lifecycle_requires_flux_audit"
        elif "vres" in prepared_record.get("source", "").lower() or "variable-resolution" in run_record.get("mechanism", "").lower():
            scope_status = "diagnostic_variable_resolution_requires_lineage_audit"
        elif prior_audit.get("identity_retention", 1.0) < 0.95 and prior_audit.get("initial_identities_missing_at_final", 0) > 0:
            scope_status = "diagnostic_closed_scope_exclusion_negative"
        else:
            scope_status = "historical_reuse_candidate_pending_D03"
        records.append(
            {
                "case_id": case_id,
                "family": run_record.get("family"),
                "mechanism": run_record.get("mechanism"),
                "source": prepared_record.get("source"),
                "source_tree_sha256": source_tree_sha256,
                "source_file_count": source_file_count,
                "source_bytes": source_bytes,
                "generated_case_prefix": str(generated.relative_to(LAB_ROOT)),
                "generated_xml_sha256": digest(generated.with_suffix(".xml")),
                "solver_binary_sha256": digest(BIN_ROOT / "DualSPHysics5.4_linux64"),
                "run_tree_sha256": raw_tree_sha256,
                "run_file_count": raw_file_count,
                "run_bytes": raw_bytes,
                "solver_stdout_sha256": digest(run_root / "solver.stdout.log"),
                "normalized_hdf5": h5,
                "prior_trajectory_audit": prior_audit,
                "scope_status": scope_status,
                "provenance_status": "rebound_to_DS-DATA-01; historical_solver_run_not_reexecuted",
            }
        )
    records.sort(key=lambda record: record["case_id"])
    summary = {
        "schema": "ds-data-01.d02.official-reuse-receipt.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_reports": [
            str(PREPARE.relative_to(LAB_ROOT)),
            str(RUN.relative_to(LAB_ROOT)),
            str(AUDIT.relative_to(LAB_ROOT)),
        ],
        "reexecution_count": 0,
        "reused_historical_case_count": len(records),
        "families_observed": sorted({record["family"] for record in records}),
        "families_missing_from_reused_atlas": ["F1", "F2", "F7"],
        "learning_attempts": 0,
        "cases": records,
        "interpretation": "Existing official probes are hash-bound diagnostic evidence. They are not counted as final production until D03 scope-specific acceptance and D04 split registration pass.",
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({
        "reused": len(records),
        "families": summary["families_observed"],
        "missing_families": summary["families_missing_from_reused_atlas"],
        "q_i_pass": sum(record["normalized_hdf5"].get("status") == "Q-I-structure-pass" for record in records),
        "output": str(output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
