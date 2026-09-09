#!/usr/bin/env python3
"""Capture the L1 W0 inventory without running a solver or changing history."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import h5py


LAB = Path(__file__).resolve().parents[1]
CAMPAIGN = LAB / "campaigns" / "l1-qualification"
REPORT = CAMPAIGN / "L1-W00-INVENTORY.json"
BIN = LAB / "vendor" / "official" / "DualSPHysics_v5.4" / "bin" / "linux"
BASELINE_COMMIT = "dc9533eecf7ee608a1db04ea4e26bb80cd2b456a"
ALLOWED_INDICES = (4, 5, 6, 7)
PROTECTED_INDICES = (0, 1, 2, 3)


def command(*args: str) -> str:
    return subprocess.run(args, cwd=LAB.parent, text=True, check=True, stdout=subprocess.PIPE).stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gpu_snapshot() -> list[dict]:
    output = command(
        "nvidia-smi",
        "--query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    )
    rows = []
    for line in output.splitlines():
        index, uuid, name, used, total, utilization = [value.strip() for value in line.split(",")]
        rows.append({
            "physical_index": int(index), "uuid": uuid, "name": name,
            "memory_used_mib": int(used), "memory_total_mib": int(total),
            "utilization_percent": int(utilization),
            "idle_at_inventory": int(used) < 1024 and int(utilization) < 10,
        })
    return rows


def h5_summary(path: Path) -> dict:
    with h5py.File(path, "r") as h5:
        times = h5["time"][:]
        valid = h5["valid"]
        return {
            "path": str(path.relative_to(LAB)),
            "bytes": path.stat().st_size,
            "normalized_frames": int(len(times)),
            "time_start_s": float(times[0]) if len(times) else None,
            "time_end_s": float(times[-1]) if len(times) else None,
            "particle_axis_count": int(valid.shape[1]),
            "valid_shape": list(valid.shape),
        }


def find_raw_frames(case_id: str) -> list[str]:
    roots = [LAB / "runs", LAB / "runs-official", LAB / "campaigns" / "v0.1-candidate" / "runs"]
    result = []
    for root in roots:
        for path in root.glob(f"**/{case_id}/**/Part_*.bi4"):
            result.append(str(path.relative_to(LAB)))
    return sorted(set(result))


def existing_audit_index() -> dict[str, dict]:
    """Index committed audit rows without treating a report as a solver run."""
    index = {}
    roots = [
        CAMPAIGN.parent / "v0.1-candidate" / "r6-n2-n2-campaign.json",
        CAMPAIGN.parent / "v0.1-candidate" / "r6-n3-endpoint-closure.json",
        CAMPAIGN.parent / "v0.1-candidate" / "r6-n3-bridge-h10.json",
        CAMPAIGN.parent / "v0.1-candidate" / "N4-COMPARABLE-MATRIX.json",
    ]
    for path in roots:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rows = payload.get("audits", [])
        if isinstance(rows, list):
            for row in rows:
                case_id = row.get("case_id")
                if case_id and row.get("frames") is not None:
                    index[str(case_id)] = {
                        "report": str(path.relative_to(LAB)),
                        "hard_audited_frame_count": row.get("frames"),
                        "registered_observation_count": row.get("fixed_time_grid_count"),
                        "status": row.get("r6_full_time_audit_status", row.get("audit_status")),
                    }
    return index


def source_geometry_summary() -> dict:
    tree = ET.parse(LAB / "cases" / "F1" / "F1_dam_break_plain" / "F1_dam_break_plain_Def.xml")
    root = tree.getroot()
    definition = root.find(".//geometry/definition")
    fluid = next(
        node for node in root.findall(".//geometry/commands/mainlist/drawbox")
        if (node.findtext("./boxfill") or "").strip() == "solid"
    )
    wall = next(
        node for node in root.findall(".//geometry/commands/mainlist/drawbox")
        if "bottom" in (node.findtext("./boxfill") or "")
    )
    parameters = {
        node.get("key"): node.get("value")
        for node in root.findall(".//execution/parameters/parameter")
    }
    constants = {
        node.tag: dict(node.attrib)
        for node in root.findall(".//constantsdef/*")
    }
    return {
        "source_definition": "cases/F1/F1_dam_break_plain/F1_dam_break_plain_Def.xml",
        "source_definition_sha256": sha256(LAB / "cases" / "F1" / "F1_dam_break_plain" / "F1_dam_break_plain_Def.xml"),
        "definition_attributes": dict(definition.attrib) if definition is not None else {},
        "fluid_drawbox": {
            "point": dict(fluid.find("./point").attrib),
            "size": dict(fluid.find("./size").attrib),
            "fill": fluid.findtext("./boxfill"),
        },
        "wall_drawbox": {
            "point": dict(wall.find("./point").attrib),
            "size": dict(wall.find("./size").attrib),
            "fill": wall.findtext("./boxfill"),
        },
        "constants_definition": constants,
        "execution_parameters": parameters,
        "l1_interpretation": {
            "fluid_source_bounds_m": "x=0.04..0.38, y=0.04..0.36, z=0.04..height+0.04",
            "closed_wall_faces": ["bottom", "left", "right", "front", "back"],
            "top_policy": "geometric open face; not an absorbing outlet without registered solver evidence",
            "shifting": "disabled in L1 candidate definitions",
        },
    }


def f1_reference_rows() -> list[dict]:
    rows = []
    audit_index = existing_audit_index()
    data_root = LAB / "campaigns" / "v0.1-candidate" / "data"
    for path in sorted(data_root.glob("**/*.h5")):
        if not (path.name.startswith("R6_") or path.name.startswith("N4_")):
            continue
        summary = h5_summary(path)
        case_id = path.stem
        raw = find_raw_frames(case_id)
        audit = audit_index.get(case_id, {})
        rows.append({
            "case_id": case_id,
            "normalized": summary,
            "raw_saved_frame_count": len(raw),
            "raw_evidence_paths": raw[:3],
            "hard_audited_frame_count": audit.get("hard_audited_frame_count"),
            "registered_observation_count": audit.get("registered_observation_count"),
            "audit_coverage_status": audit.get("status", "not_found_in_committed_audit"),
            "audit_source": audit.get("report"),
        })
    return rows


def main() -> None:
    gpus = gpu_snapshot()
    disk = shutil.disk_usage(LAB)
    package = Path("/home/jade/.codex/attachments/dccb306a-7c5e-433a-bdee-c4cf5d5db9c3/Lagrangian_Fluid_L1_Autonomous_dc9533e.zip")
    report = {
        "schema_version": "l1-w00-inventory.v1",
        "campaign_id": "L1_AUTONOMOUS_FLUID_QUALIFICATION",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed_read_only",
        "baseline_commit": BASELINE_COMMIT,
        "current_commit_at_capture": command("git", "rev-parse", "HEAD"),
        "branch": command("git", "branch", "--show-current"),
        "status_porcelain_at_capture": command("git", "status", "--porcelain"),
        "new_activity_before_capture": {
            "solver_attempts": 0,
            "material_configurations": 0,
            "training_attempts": 0,
            "note": "W0 is read-only; existing v0.1-candidate/N4 evidence is not charged to L1.",
        },
        "attachment_provenance": {
            "path": str(package),
            "sha256": sha256(package),
            "expected_sha256": "2140048e019b2074668799aef145314af90eae242498450c069bbdb910aab5e3",
            "plan_sha256": "c6d7d597a087e02eb3e85350cd955990862ad7e4bc406a7b71428fb994cb9d9a",
            "gate_registry_sha256": "66adb75a5cf9298b8aba0cefe1c210db61bbb14d38aadffd4229f79fa108c5c6",
        },
        "gpu_policy": {
            "candidate_indices": list(ALLOWED_INDICES),
            "protected_indices": list(PROTECTED_INDICES),
            "allowed_gpu_uuids": [row["uuid"] for row in gpus if row["physical_index"] in ALLOWED_INDICES],
            "recheck_before_each_batch": True,
            "single_heavy_job_per_gpu": True,
            "unrelated_jobs_must_not_be_killed": True,
        },
        "host": {
            "gpu_count": len(gpus),
            "gpus": gpus,
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
            "minimum_free_bytes_required": max(100 * 1024**3, int(disk.total * 0.1)),
        },
        "binaries": {
            name: {
                "path": str((BIN / name).relative_to(LAB)),
                "bytes": (BIN / name).stat().st_size,
                "sha256": sha256(BIN / name),
            }
            for name in ("DualSPHysics5.4_linux64", "GenCase_linux64", "PartVTK_linux64")
        },
        "source_geometry_and_numerics": source_geometry_summary(),
        "historical_n4": {
            "immutable": True,
            "solver_attempts_reusable": False,
            "fifth_attempt_allowed": False,
            "decision": "NO_GO retained at h10/h11 TV gates",
        },
        "f1_existing_coverage": f1_reference_rows(),
        "coverage_semantics": {
            "raw_saved_frame_count": "count of native Part_*.bi4 files, not a registered-time count",
            "normalized_frame_count": "length of normalized HDF5 time axis",
            "hard_audited_frame_count": "not inferred from file existence; to be populated by L1 audit artifacts",
            "registered_observation_count": "21 requested physical times only when the saved axis covers the L1 0--1.5s grid",
        },
    }
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_name(REPORT.name + ".partial")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(REPORT)
    print(json.dumps({
        "report": str(REPORT.relative_to(LAB)),
        "candidate_gpu_indices": list(ALLOWED_INDICES),
        "idle_candidate_gpu_indices": [row["physical_index"] for row in gpus if row["physical_index"] in ALLOWED_INDICES and row["idle_at_inventory"]],
        "disk_free_gib": round(disk.free / 1024**3, 2),
        "f1_existing_products": len(report["f1_existing_coverage"]),
        "new_solver_attempts": 0,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
