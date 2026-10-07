#!/usr/bin/env python3
"""Prepare a bounded F2-S1 GenCase-only spacing bracket near dp=0.0085.

The four candidates differ only in ``definition@dp``.  Continuous geometry,
fill, motion, source target, and all declared dependencies remain bound to the
same CURRENT F2-S1 source.  This module emits CPU-only v4 guard requests; it
does not start a solver, open HDF5, or rescale particle mass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


REPO = Path(__file__).resolve().parents[5]
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
REVIEW = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/review-source/SENTINEL_MATRIX.json"
CURRENT = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
SOURCE_DEF = REFERENCE / "f2_s1_coarse_phase_probe_inputs_v2/dp0p01258/F2_S1_COARSE_PHASE_PROBE_DP01258_Def.xml"
SOURCE_MOTION = REFERENCE / "f2_s1_coarse_phase_probe_inputs_v2/dp0p01258/F2_S1_COARSE_PHASE_PROBE_DP01258_motion.dat"
PREDECESSOR_ROOT = DATA_ROOT / "families/F2/F2_S1_PREFLIGHT_FINE_DP008/f2_s1_preflight_fine_dp008-003"
INPUT_ROOT = REFERENCE / "stage2_f2_mass_fit_probe_inputs_v4"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f2-mass-fit-probe-v4"
MiB = 1024 * 1024
TARGET_MASS_KG = 21.114
SOURCE_DP_M = 0.01

CANDIDATES = (
    ("F2_S1_MASSFIT_V4_NEAR_DP0p008400", 0.0084, "lower neighbor of the consumed dp0.0085 probe; resolves lattice/count jump without changing continuous fill"),
    ("F2_S1_MASSFIT_V4_NEAR_DP0p008450", 0.00845, "inner lower neighbor of the consumed dp0.0085 probe; bounded phase bracket"),
    ("F2_S1_MASSFIT_V4_NEAR_DP0p008550", 0.00855, "inner upper neighbor of the consumed dp0.0085 probe; bounded phase bracket"),
    ("F2_S1_MASSFIT_V4_NEAR_DP0p008600", 0.0086, "upper neighbor of the consumed dp0.0085 probe; resolves lattice/count jump without changing continuous fill"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path.resolve()), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256_file(path)}


def atomic_write(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def normalized_geometry_hash(data: bytes) -> str:
    normalized, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+(" )', rb'\1<DP>\2', data, count=1)
    if count != 1:
        # The source file has no whitespace before the closing quote in some
        # historical variants; keep the replacement expression explicit.
        normalized, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+(")', rb'\1<DP>\2', data, count=1)
    if count != 1:
        raise ValueError("expected exactly one definition@dp")
    return hashlib.sha256(normalized).hexdigest()


def replace_dp(source: bytes, dp: float) -> bytes:
    updated, count = re.subn(
        rb'(<definition\b[^>]*\bdp=")[^"]+(\")',
        lambda match: match.group(1) + f"{dp:.15g}".encode("ascii") + match.group(2),
        source,
        count=1,
    )
    if count != 1:
        raise ValueError("source Def has no unique definition@dp")
    return updated


def prepare() -> dict[str, Any]:
    if INPUT_ROOT.exists():
        raise FileExistsError(INPUT_ROOT)
    source_head = git_commit()
    for path in (SOURCE_DEF, SOURCE_MOTION, CURRENT, REVIEW, QUALITY, GENCASE,
                 PREDECESSOR_ROOT / "execution-receipt.json", PREDECESSOR_ROOT / "generated.xml"):
        if not path.is_file():
            raise FileNotFoundError(path)
    source_bytes = SOURCE_DEF.read_bytes()
    source_geometry_hash = normalized_geometry_hash(source_bytes)
    INPUT_ROOT.mkdir(parents=True)
    records = []
    for case_id, dp, rationale in CANDIDATES:
        case_dir = INPUT_ROOT / "F2_S1" / "near_dp0085" / case_id.split("DP")[1]
        case_dir.mkdir(parents=True)
        definition = case_dir / f"{case_id}_Def.xml"
        atomic_write(definition, replace_dp(source_bytes, dp))
        derived_geometry_hash = normalized_geometry_hash(definition.read_bytes())
        motion = case_dir / SOURCE_MOTION.name
        shutil.copyfile(SOURCE_MOTION, motion)
        if sha256_file(motion) != sha256_file(SOURCE_MOTION):
            raise ValueError("motion dependency changed")
        candidate = {
            "schema": "ds02.stage2.f2-mass-fit-probe.v4",
            "case_id": case_id,
            "sentinel_id": "F2-S1",
            "family_id": "F2",
            "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
            "label": "near_dp0085",
            "candidate_dp_m": dp,
            "source_dp_m": SOURCE_DP_M,
            "source_mass_target_kg": TARGET_MASS_KG,
            "search_rationale": rationale,
            "source_binding": {
                "source_definition": record(SOURCE_DEF),
                "motion": record(SOURCE_MOTION),
                "predecessor_artifacts": [record(PREDECESSOR_ROOT / "execution-receipt.json"), record(PREDECESSOR_ROOT / "generated.xml")],
                "source_producer_vs_current_head": source_head,
            },
            "derived_inputs": {
                "definition": record(definition),
                "motion": record(motion),
                "only_definition_dp_changed": True,
                "normalized_geometry_hash_source": source_geometry_hash,
                "normalized_geometry_hash_derived": derived_geometry_hash,
            },
            "continuous_vs_intentional": {
                "continuous_geometry_unchanged": True,
                "continuous_fill_and_control_unchanged": True,
                "motion_or_acceleration_changed": False,
                "motion_dependency_byte_identical": True,
                "intentional_variations": ["dp_m", "derived h/massfluid/count/lattice phase measured from generated XML"],
                "particle_mass_rescale": False,
            },
            "status": "PREPARED_GENCACE_INPUT_NOT_RUN",
            "solver_started": False,
            "full_time_hdf5_read": False,
            "gpu_lease": "none",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "estimated_storage_bytes": 128 * MiB,
        }
        records.append({"candidate": candidate, "definition": record(definition), "motion": record(motion)})
    manifest = {
        "schema": "ds02.stage2.f2-mass-fit-probe-inputs.v4",
        "status": "PREPARED_GENCACE_INPUTS_NOT_RUN",
        "generated_at_commit": source_head,
        "quality_source": record(QUALITY),
        "review_source": record(REVIEW),
        "current_source": record(CURRENT),
        "candidate_count": len(records),
        "policy": {
            "scope": "F2-S1 four-point bracket around consumed dp0.0085; source geometry/fill/motion unchanged",
            "only_definition_change": True,
            "whole_initial_source_mass_target_kg": TARGET_MASS_KG,
            "mass_gate": "target <=1%; marginal >1% and <=2%; hard >2%; no post-result relaxation",
            "per_mk": "diagnostic rows retained separately; no per-MK rescaling or automatic acceptance",
            "no_mass_rescale": True,
            "no_solver_or_hdf5": True,
        },
        "records": records,
        "solver_started": False,
        "full_time_hdf5_read": False,
        "gpu_lease": "none",
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
    }
    write_json(INPUT_ROOT / "manifest.json", manifest)
    return manifest


def request_for(item: dict[str, Any], manifest_path: Path, source_head: str) -> dict[str, Any]:
    c = item["candidate"]
    source = c["source_binding"]
    definition = Path(item["definition"]["path"])
    motion = Path(item["motion"]["path"])
    paths = [
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py",
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py",
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py",
        PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py",
        REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_mass_fit_probe_v4.py",
        GENCASE, CURRENT, REVIEW, QUALITY, manifest_path, definition, motion,
        SOURCE_DEF, SOURCE_MOTION, PREDECESSOR_ROOT / "execution-receipt.json", PREDECESSOR_ROOT / "generated.xml",
    ]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) in seen:
            continue
        if not path.is_file():
            raise FileNotFoundError(path)
        seen.add(str(path)); unique.append(path)
    hashes = {str(path): sha256_file(path) for path in unique}
    return {
        "schema": "ds02.request.v1",
        "family_id": "F2",
        "case_id": c["case_id"],
        "attempt_id": c["case_id"].lower() + "-001",
        "kind": "cpu", "cpu_task_kind": "gencase", "cpu_threads": 2,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": c["estimated_storage_bytes"],
        "worktree_root": str(REPO), "cwd": str(definition.parent),
        "command": [str(GENCASE), str(definition.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "input_files": [str(path) for path in unique],
        "input_hashes": hashes, "input_sha256": hashes,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"),
            "strict_guard": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"),
            "runtime": str(PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"),
            "launch_commit": source_head, "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden",
            "estimated_cpu_core_hours": 0.5, "estimated_new_storage_bytes": c["estimated_storage_bytes"],
        },
        "source_binding": source,
        "scope": {
            "sentinel_id": c["sentinel_id"], "physical_case_id": c["physical_case_id"], "label": c["label"],
            "continuous_geometry_control": c["continuous_vs_intentional"],
            "mass_gate": "UNKNOWN_UNTIL_GENERATED_XML",
            "whole_initial_source_mass_target_kg": TARGET_MASS_KG,
            "report_per_mk_relative_diagnostic": True,
            "gencase_only": True, "solver_started": False, "full_time_hdf5_read": False, "gpu_uuid_lease": "none",
            "scientific_qualification": "UNKNOWN",
        },
        "preparation_manifest": str(manifest_path.resolve()),
        "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
    }


def emit(manifest: dict[str, Any]) -> int:
    if REQUEST_ROOT.exists():
        raise FileExistsError(REQUEST_ROOT)
    REQUEST_ROOT.mkdir(parents=True)
    manifest_path = INPUT_ROOT / "manifest.json"
    for item in manifest["records"]:
        write_json(REQUEST_ROOT / f"{item['candidate']['case_id'].lower()}.json", request_for(item, manifest_path, manifest["generated_at_commit"]))
    return len(manifest["records"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--emit-requests", action="store_true")
    args = parser.parse_args()
    if not args.prepare and not args.emit_requests:
        raise SystemExit("choose --prepare and/or --emit-requests")
    manifest = prepare() if args.prepare else json.loads((INPUT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    requests = emit(manifest) if args.emit_requests else 0
    print(json.dumps({"status": "PASS", "candidates": manifest["candidate_count"], "requests": requests, "manifest": str(INPUT_ROOT / "manifest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
