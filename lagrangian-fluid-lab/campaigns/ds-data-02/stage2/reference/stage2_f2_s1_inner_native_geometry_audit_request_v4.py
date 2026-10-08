#!/usr/bin/env python3
"""Build the guarded, XML/Fluid-VTK-only F2 inner result audit request (v4)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[5]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
ROOT050 = DATA / "families/F2/F2_S1_SOURCE_CENTERED_INNER_DP0088_GENCASE_ROOT_050/f2-s1-source-centered-inner-dp0088-gencase-root-050-001-root-forward-030-001"
XML = ROOT050 / "generated.xml"
VTK = ROOT050 / "generated_Fluid.vtk"
RECEIPT = ROOT050 / "execution-receipt.json"
WORKER = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_inner_native_geometry_audit_v4.py"
REQUEST_BUILDER = Path(__file__).resolve()
V3_REQUEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-inner-native-geometry-audit-v3-root-forward-059-001.json"
V2_REQUEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f2-s1-inner-native-geometry-audit-v2-root-forward-054-001.json"
V2_RECEIPT = DATA / "families/F2/F2_S1_SOURCE_CENTERED_INNER_DP0088_NATIVE_GEOMETRY_AUDIT_V2/f2-s1-source-centered-inner-dp0088-native-geometry-audit-v2-root-forward-001-root-forward-030-001/execution-receipt.json"
DISPATCH = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py")
STRICT = DISPATCH.parent / "ds_data02_strict_dispatch_v8.py"
RUNTIME = DISPATCH.parent / "ds_data02_runtime_v8.py"
INNER_SCRIPT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_source_centered_v4_inner_inputs.py"
INNER_MANIFEST = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f2_s1_source_centered_v4_inner_manifest_v1.json"
CURRENT_DEF = DATA / "families/F2/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-gencase-source801-root804/prepared/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010_Def.xml"
CURRENT_MOTION = CURRENT_DEF.with_name(CURRENT_DEF.name.replace("_Def.xml", "_motion.dat"))
F2_ROOT044_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F2_V5_BOUND_MODE_COARSE_GENCASE_ACTUAL_MASS_HARD_FAILURE_ROOT_VERIFICATION_044.json")
EXPECTED_VTK_SHA = "cb919135c5b88374c43674907cfea49468974053e73c3ae5f52d5903124bf274"
V1_FAILURE_RECEIPT = DATA / "families/F2/F2_S1_SOURCE_CENTERED_INNER_DP0088_NATIVE_GEOMETRY_AUDIT_V1/f2-s1-source-centered-inner-dp0088-native-geometry-audit-v1-root-forward-001-root-forward-030-001/execution-receipt.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def build(output: Path) -> dict[str, Any]:
    small = [REQUEST_BUILDER, WORKER, V3_REQUEST, V2_REQUEST, INNER_SCRIPT, INNER_MANIFEST, XML, RECEIPT, V1_FAILURE_RECEIPT, V2_RECEIPT, CURRENT_DEF, CURRENT_MOTION, DISPATCH, STRICT, RUNTIME, F2_ROOT044_PROOF]
    for path in small:
        if not path.is_file():
            raise FileNotFoundError(path)
    input_files = [str(path.resolve()) for path in small] + [str(VTK.resolve())]
    input_hashes = {str(path.resolve()): sha256(path) for path in small}
    # The builder deliberately does not reread/hash the 1.3 MiB VTK.  This
    # terminal SHA was independently recorded from root050; v8 must enforce
    # a fresh pre/post complete-stat+SHA check before invoking the worker.
    input_hashes[str(VTK.resolve())] = EXPECTED_VTK_SHA
    request_name = "f2_s1_inner_dp0088_native_geometry_audit_v4.json"
    request = {
        "schema": "ds02.request.v1",
        "family_id": "F2", "sentinel_id": "F2-S1",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "case_id": "F2_S1_SOURCE_CENTERED_INNER_DP0088_NATIVE_GEOMETRY_AUDIT_V4",
        "attempt_id": "f2-s1-source-centered-inner-dp0088-native-geometry-audit-v4-root-forward-001",
        "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 900, "max_memory_bytes": 1 << 30, "max_storage_bytes": 512 << 20,
        "worktree_root": str(REPO), "cwd": str(REPO),
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python", str(WORKER),
            "--generated-xml", str(XML), "--fluid-vtk", str(VTK), "--receipt", str(RECEIPT),
            "--expected-fluid-count", "30969", "--expected-mass-kg", "18.876",
            "--output", f"{{attempt_root}}/report/{request_name}",
        ],
        "input_files": input_files, "input_hashes": input_hashes,
        "guarded_input_files": [str(XML.resolve()), str(VTK.resolve()), str(RECEIPT.resolve())],
        "guard_policy": {
            "pre_post_complete_stat_and_sha": "required for XML, Fluid.vtk, and receipt before/after worker",
            "worker_reads": "generated.xml + generated_Fluid.vtk + execution-receipt.json only",
            "xml_particles_path": "execution/particles; summary rows are filtered from typed rows",
            "vtk_idp_contract": "SCALARS Idp unsigned_int + LOOKUP_TABLE default + exact big-endian uint32 payload + explicit payload offset/count; no FIELD-after-Idp or first-lookup-table assumption",
            "bi4_read": False, "hdf5_read": False, "solver_launch": False,
            "vtk_builder_hash": "known terminal SHA only; worker/parent performs actual pre/post hash",
        },
        "output": {"path": f"{{attempt_root}}/report/{request_name}", "atomic": True, "refuse_overwrite": True},
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "hdf5_read": False, "bi4_read": False,
        "resource_guard": {
            "owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME),
            "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "source_output_protection": "read-only source; atomic new report",
        },
        "source_binding": {
            "schema": "ds02.stage2.f2-s1.inner-native-geometry-audit.v4",
            "root050_gencase_receipt": record(RECEIPT), "root050_generated_xml": record(XML),
            "root050_fluid_vtk_expected_sha256": EXPECTED_VTK_SHA,
            "candidate_script": record(INNER_SCRIPT), "candidate_manifest": record(INNER_MANIFEST),
            "current_source_def": record(CURRENT_DEF), "current_motion": record(CURRENT_MOTION),
            "root044_mass_failure_proof": record(F2_ROOT044_PROOF),
            "v1_failure_receipt": record(V1_FAILURE_RECEIPT), "v2_failure_receipt": record(V2_RECEIPT), "v2_request": record(V2_REQUEST), "v3_request": record(V3_REQUEST),
            "continuous_owner_mass_kg": 18.876, "expected_root050_fluid_count": 30969,
            "mass_gate": {"preferred_fraction": 0.01, "hard_fraction": 0.02, "no_rescale": True},
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "initial geometry/mass audit only; no CFD or observer qualification"},
    }
    output = output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = build(args.output)
    print(json.dumps({"status": "PASS_REQUEST_BUILT", "output": str(args.output.resolve()), "vtk_sha_bound": request["input_hashes"][str(VTK.resolve())]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
