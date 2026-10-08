#!/usr/bin/env python3
"""Prepare one F2-S1 owner-centred cell-selector GenCase preflight.

The consumed F2 current/V4/V6 products all used the old ``dp | bound``
selector and rasterized the full drawbox envelope (37x27x10/11 at dp=.0088).
This forward-only candidate follows the already verified F1 owner-centred
representation: the continuous owner boxes stay fixed, each fluid selector is
trimmed by a registered lattice margin, and ``dp | actual | bound`` plus a
pointref places cell centres on the registered phase.  Fixed geometry, motion,
and execution controls are copied byte-for-byte.

The candidate is a single GenCase-only CPU preflight.  Its 37x25x10 count and
18.910848 kg sample mass are a forecast for registration, not a result.  A
parent guard must run GenCase and a subsequent small XML/VTK/BI4 QA before any
solver use.  No BI4, VTK, HDF5, CFD, or solver payload is read here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

SCHEMA = "ds02.stage2.f2-s1.owner-centered-cell-selector-v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"
TEMPLATE = REPO / "doc/xml_format/GenCase_CaseTemplate.xml"
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
SOURCE_DEF = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-gencase-source801-root804/prepared/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml")
SOURCE_MOTION = SOURCE_DEF.parent / "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_motion.dat"
INPUT_ROOT = REFERENCE / "stage2_f2_s1_owner_centered_cell_selector_v1_inputs/F2_S1/dp0p0088"
MANIFEST_PATH = REFERENCE / "stage2_f2_s1_owner_centered_cell_selector_v1_manifest.json"
REQUEST_PATH = STAGE2 / "requests/f2-s1-owner-centered-cell-selector-v1-root-forward-076.json"
REQUEST_DIR = STAGE2 / "requests/stage2-f2-s1-owner-centered-cell-selector-v1"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
CASE_ID = "F2_S1_OWNER_CENTERED_CELL_SELECTOR_DP0P0088"
ATTEMPT_ID = "f2-s1-owner-centered-cell-selector-dp0088-gencase-root-forward-076-001"
OWNER_MASS_KG = 18.876
RHO0 = 1000.0
DP_M = 0.0088
POINTREF = (0.0013, 0.0, 0.0004)
COUNTS = (37, 25, 10)
LAYER_LOWS = ((0.05, -0.11, 0.70), (0.05, -0.11, 0.788), (0.05, -0.11, 0.876))
OWNER_SIZE = (0.325, 0.22, 0.088)
SELECTOR_SIZE = ((COUNTS[0] - 1) * DP_M, (COUNTS[1] - 1) * DP_M, (COUNTS[2] - 1) * DP_M)
SELECTOR_LOWS = tuple(tuple(LAYER_LOWS[layer][axis] + (OWNER_SIZE[axis] - SELECTOR_SIZE[axis]) / 2.0 for axis in range(3)) for layer in range(3))
PREDICTED_COUNT = COUNTS[0] * COUNTS[1] * COUNTS[2] * 3
PARTICLE_MASS_KG = RHO0 * DP_M**3
PREDICTED_MASS_KG = PREDICTED_COUNT * PARTICLE_MASS_KG

F1_SUPPORT_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_OWNER_DP005_V2_SUPPORT_CONTROL_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
F1_QA_PROOF = MAIN / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_TWO_OWNER_RUNGS_INITIAL_NATIVE_QA_V2_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
F2_DIAGNOSTIC = REFERENCE / "f2_s1_coarse_lattice_phase_diagnostic_v1.json"


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path); stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "ctime_ns": int(stat.st_ctime_ns), "sha256": sha256(path)}


def atomic_bytes(path: Path, value: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        if path.read_bytes() == value:
            return
        raise FileExistsError(f"refuse overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1; handle.write(value); handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0: os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def derive_candidate() -> Path:
    source = regular(SOURCE_DEF).read_text(encoding="utf-8")
    if source.count('<definition dp="0.01">') != 1 or source.count('<setshapemode>dp | bound</setshapemode>') != 1:
        raise ValueError("unexpected immutable F2 source definition shape")
    if source.count('<setmkfluid mk="') != 3:
        raise ValueError("expected three F2 fluid drawboxes")
    derived = source.replace('<definition dp="0.01">', '<definition dp="0.0088">\n        <pointref x="0.0013" y="0.0000" z="0.0004" />', 1)
    derived = derived.replace('<setshapemode>dp | bound</setshapemode>', '<setshapemode>dp | actual | bound</setshapemode>', 1)
    old_boxes = (
        '<point x="0.05" y="-0.11" z="0.70" />\n            <size x="0.325" y="0.22" z="0.088" />',
        '<point x="0.05" y="-0.11" z="0.788" />\n            <size x="0.325" y="0.22" z="0.088" />',
        '<point x="0.05" y="-0.11" z="0.876" />\n            <size x="0.325" y="0.22" z="0.088" />',
    )
    new_boxes = tuple(
        f'<point x="{SELECTOR_LOWS[i][0]:.4f}" y="{SELECTOR_LOWS[i][1]:.4f}" z="{SELECTOR_LOWS[i][2]:.4f}" />\n'
        f'            <size x="{SELECTOR_SIZE[0]:.4f}" y="{SELECTOR_SIZE[1]:.4f}" z="{SELECTOR_SIZE[2]:.4f}" />'
        for i in range(3)
    )
    for old, new in zip(old_boxes, new_boxes):
        if derived.count(old) != 1:
            raise ValueError(f"expected one exact fluid selector: {old}")
        derived = derived.replace(old, new, 1)
    if derived == source or derived.count('<pointref x="0.0013" y="0.0000" z="0.0004" />') != 1:
        raise ValueError("candidate did not apply registered representation edits")
    # Reconstructing the expected bytes from the frozen source gives a strict
    # source-diff proof: no boundary, motion, or execution text is silently
    # changed by this candidate.
    candidate = INPUT_ROOT / f"{CASE_ID}_Def.xml"
    atomic_bytes(candidate, derived.encode("utf-8"))
    motion = INPUT_ROOT / SOURCE_MOTION.name
    atomic_bytes(motion, regular(SOURCE_MOTION).read_bytes())
    return candidate


def prepare_inputs() -> dict[str, Any]:
    candidate = derive_candidate(); motion = INPUT_ROOT / SOURCE_MOTION.name
    for path in (GENCASE, GENCASE_CONFIG, TEMPLATE, F1_SUPPORT_PROOF, F1_QA_PROOF, F2_DIAGNOSTIC): regular(path)
    relative = PREDICTED_MASS_KG / OWNER_MASS_KG - 1.0
    manifest = {
        "schema": SCHEMA, "status": "PREPARED_ONE_F2_OWNER_CENTERED_CELL_SELECTOR_GENCASE_PREFLIGHT",
        "family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "source_def": record(SOURCE_DEF), "source_motion": record(SOURCE_MOTION), "candidate_def": record(candidate), "candidate_motion": record(motion),
        "official_support": {"gencase_binary": record(GENCASE), "gencase_config": record(GENCASE_CONFIG), "template": record(TEMPLATE),
                              "template_semantics": {"setshapemode": ["actual", "dp", "all", "bound", "fluid", "void", "null"], "source_claim": "official GenCase template; actual product remains authoritative"}},
        "prior_f1_evidence": {"support_proof": record(F1_SUPPORT_PROOF), "initial_qa_proof": record(F1_QA_PROOF), "reuse_scope": "representation precedent only; no F2 result inferred"},
        "prior_f2_diagnostic": record(F2_DIAGNOSTIC),
        "continuous_owner": {"layer_low_m": [list(v) for v in LAYER_LOWS], "layer_size_m": list(OWNER_SIZE), "layer_count": 3, "volume_m3": 0.018876, "mass_kg": OWNER_MASS_KG, "authority": "frozen CURRENT source drawboxes; unchanged"},
        "representation": {"dp_m": DP_M, "pointref_m": list(POINTREF), "selector_low_m": [list(v) for v in SELECTOR_LOWS], "selector_size_m": list(SELECTOR_SIZE),
                           "forecast_axis_counts": list(COUNTS), "forecast_fluid_count": PREDICTED_COUNT, "drawbox_owner_bounds_unchanged": True,
                           "setshapemode_change": "dp | bound -> dp | actual | bound", "intentional_source_edits": ["definition@dp", "definition/pointref", "setshapemode value", "three fluid selector point/size pairs"],
                           "boundary_motion_execution_controls": "byte-preserved", "mass_rescale": False},
        "forecast_only": {"particle_mass_kg": PARTICLE_MASS_KG, "sample_mass_kg": PREDICTED_MASS_KG, "relative_to_owner_fraction": relative, "relative_to_owner_percent": 100.0 * relative,
                          "gate_preferred_fraction": 0.01, "gate_marginal_fraction": 0.02, "status": "PREDICTED_NOT_ACTUAL_UNTIL_GENCASE_XML_VTK_RECEIPT"},
        "quality_gates": {"preferred_whole_initial_mass_fraction": 0.01, "marginal_whole_initial_mass_fraction": 0.02, "no_mass_rescale": True, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
    }
    atomic_json(MANIFEST_PATH, manifest)
    return manifest


def build_request(launch_commit: str) -> dict[str, Any]:
    if not MANIFEST_PATH.is_file(): prepare_inputs()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")); candidate = Path(manifest["candidate_def"]["path"]); motion = Path(manifest["candidate_motion"]["path"])
    output_root = DATA_ROOT / "families/F2" / CASE_ID / ATTEMPT_ID
    static_paths = [Path(__file__), MANIFEST_PATH, candidate, motion, SOURCE_DEF, SOURCE_MOTION, GENCASE, GENCASE_CONFIG, TEMPLATE, F1_SUPPORT_PROOF, F1_QA_PROOF, F2_DIAGNOSTIC, DISPATCH, STRICT, RUNTIME]
    static_paths = list(dict.fromkeys(regular(path) for path in static_paths)); records = {str(path): record(path) for path in static_paths}
    request = {
        "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "gencase", "family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": CASE_ID, "attempt_id": ATTEMPT_ID, "launch_commit": launch_commit,
        "command": [str(GENCASE), str(candidate.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
        "cwd": str(candidate.parent), "worktree_root": str(REPO), "input_files": list(records), "input_hashes": {key: value["sha256"] for key, value in records.items()}, "input_records": records,
        "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900, "max_memory_bytes": 2 * 1024**3, "max_storage_bytes": 512 * 1024**2,
        "estimated_input_read_bytes": sum(v["bytes"] for v in records.values()), "estimated_storage_bytes": 512 * 1024**2, "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": True, "solver_launch": False, "hdf5_read": False, "bi4_read": False,
        "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
        "source_binding": {"schema": "ds02.stage2.f2-s1.owner-centered-cell-selector-binding.v1", "source_def": records[str(SOURCE_DEF.resolve())], "source_motion": records[str(SOURCE_MOTION.resolve())], "candidate_def": records[str(candidate.resolve())], "candidate_motion": records[str(motion.resolve())],
                           "official_gencase": {"binary": records[str(GENCASE.resolve())], "config": records[str(GENCASE_CONFIG.resolve())], "template": records[str(TEMPLATE.resolve())]},
                           "representation": manifest["representation"], "continuous_owner": manifest["continuous_owner"], "controls_and_boundary_drawboxes_frozen": True,
                           "post_gencase_required": ["generated.xml", "generated.bi4", "generated_Fluid.vtk", "generated_Bound.vtk", "execution-receipt.json"], "initial_native_qa_required": True,
                           "mass_gate": "whole initial fluid mass versus 18.876 kg; per-MK/inside-outside support audit; no rescale", "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "launch_commit": launch_commit, "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "output_tree_charge": "required; new attempt only"},
        "qualification_stage": "stage2_f2_s1_owner_centered_cell_selector_gencase_only_pending_actual_geometry_and_mass_qa", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "status": "READY_FOR_PARENT_CPU_GUARD_REVIEW",
    }
    request_path = REQUEST_DIR / f"{CASE_ID.lower()}.json"; atomic_json(request_path, request)
    report = {"schema": SCHEMA, "status": "REGISTERED_ONE_Gencase_ONLY_REQUEST", "launch_commit": launch_commit, "request": record(request_path), "candidate": record(candidate), "gencase_started": False, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    atomic_json(REFERENCE / "stage2_f2_s1_owner_centered_cell_selector_v1_request_report.json", report)
    return report


def self_test() -> dict[str, Any]:
    assert PREDICTED_COUNT == 27750 and abs(PREDICTED_MASS_KG - 18.910848) < 1e-12
    assert all(abs(SELECTOR_SIZE[i] / DP_M - (COUNTS[i] - 1)) < 1e-12 for i in range(3))
    assert abs(SELECTOR_LOWS[0][0] - 0.0541) < 1e-12 and abs(SELECTOR_LOWS[0][1] + 0.1056) < 1e-12
    return {"status": "PASS", "forecast_count": PREDICTED_COUNT, "forecast_mass_kg": PREDICTED_MASS_KG, "representation": "F1 owner-centered cell-selector precedent", "gencase_started": False, "native_payload_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--self-test", action="store_true"); parser.add_argument("--prepare-inputs", action="store_true"); parser.add_argument("--build-request", action="store_true"); parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if sum((args.self_test, args.prepare_inputs, args.build_request)) != 1: parser.error("choose exactly one mode")
    if args.self_test: value = self_test()
    elif args.prepare_inputs: value = prepare_inputs()
    else:
        if not args.launch_commit: parser.error("--build-request requires --launch-commit")
        value = build_request(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": value.get("status"), "request": str(REQUEST_PATH), "gencase_started": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
