#!/usr/bin/env python3
"""Build root-only dp=.025 RIGID003 solver requests after CPU preflight."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V27 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v27.py")
V28 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v28.py")
SPEC = importlib.util.spec_from_file_location("f6_handoff_dp025_rigid003_v27_for_requests", V27)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load RIGID003 mother module: {V27}")
V27_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V27_MODULE)

FAMILY_ROOT = V27_MODULE.FAMILY_ROOT
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
RAW_ROOT = DATA_ROOT / "families/F6"
REQUEST_ROOT = FAMILY_ROOT / "qualification_requests_001"
PREflight = FAMILY_ROOT / "preflight_001.json"
RUNTIME_V2 = V27_MODULE.MODULE.RUNTIME_V2
SOLVER = V27_MODULE.MODULE.SOLVER
GENCASE = V27_MODULE.MODULE.GENCASE
FLOATING_INFO = V27_MODULE.MODULE.FLOATING_INFO
COMPUTE_FORCES = V27_MODULE.MODULE.COMPUTE_FORCES
PARTVTK = V27_MODULE.MODULE.PARTVTK
WINDOW_S = [0.0, 12.0]
OUTPUT_DT_S = 0.05
ESTIMATED_STORAGE_BYTES = 10 * 1024**3
ESTIMATED_GPU_MIB = 8192


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _case_request(case: dict[str, Any], preflight: dict[str, Any], preflight_row: dict[str, Any]) -> dict[str, Any]:
    cid = str(case["case_id"])
    gen_attempt = str(case["request"]["attempt_id"])
    gen_root = RAW_ROOT / cid / gen_attempt
    prefix = gen_root / cid
    receipt = gen_root / "execution-receipt.json"
    xml = prefix.with_suffix(".xml")
    bi4 = prefix.with_suffix(".bi4")
    all_vtk = prefix.with_name(prefix.name + "_All.vtk")
    fluid_vtk = prefix.with_name(prefix.name + "_Fluid.vtk")
    bound_vtk = prefix.with_name(prefix.name + "_Bound.vtk")
    definition = Path(case["definition"]["path"])
    control = Path(case["control"]["path"])
    native = Path(case["native"]["path"])
    normal = Path(case["normal"]["path"])
    template = Path(case["official_template"]["path"])
    required = [receipt, xml, bi4, all_vtk, fluid_vtk, bound_vtk, definition, control, native, normal, template, SOLVER, GENCASE, FLOATING_INFO, COMPUTE_FORCES, PARTVTK, RUNTIME_V2, PREflight]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"{cid} solver request source missing: " + ", ".join(missing))
    actual = preflight_row["generated_native_contract"]
    if not preflight_row.get("preflight_pass"):
        raise RuntimeError(f"{cid} actual GenCase preflight is not passing")
    input_files = [SCRIPT, V27, V28, RUNTIME_V2, SOLVER, GENCASE, FLOATING_INFO, COMPUTE_FORCES, PARTVTK, definition, control, native, normal, template, receipt, xml, bi4, all_vtk, fluid_vtk, bound_vtk, PREflight, FAMILY_ROOT / "manifest.json", FAMILY_ROOT / "scope.json"]
    input_files = [path for path in input_files if path.is_file()]
    input_hashes = {str(path.resolve()): sha256(path) for path in input_files}
    attempt = f"{cid}_SOLVER_QUAL_DP025_001"
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F6",
        "case_id": cid,
        "attempt_id": attempt,
        "kind": "qualification",
        "command": [str(SOLVER.resolve()), str(prefix.resolve()), "{attempt_root}/solver_output", "-tmax:12", "-tout:0.05"],
        "cwd": str(gen_root.resolve()),
        "max_wall_seconds": 1200,
        "cpu_threads": 4,
        "estimated_peak_gpu_mib": ESTIMATED_GPU_MIB,
        "estimated_storage_bytes": ESTIMATED_STORAGE_BYTES,
        "input_files": [str(path.resolve()) for path in input_files],
        "worktree_root": str(V27_MODULE.MODULE.REPO_ROOT.resolve()),
        "generator_version": "ds_data02_f6_handoff_20261002.commensurate_dp025_rigid003.v1",
        "mechanism_id": case["mechanism_id"],
        "resolution_id": case["resolution_id"],
        "purpose": "root-only 0-12 s dp=.025 native qualification candidate after actual XML/Bound.vtk preflight; no production claim",
        "solver_dimension_required": 3,
        "window_s": WINDOW_S,
        "output_interval_s": OUTPUT_DT_S,
        "actual_gencase_prefix": str(prefix.resolve()),
        "gencase_cwd": str(gen_root.resolve()),
        "gencase_receipt": str(receipt.resolve()),
        "gencase_receipt_sha256": sha256(receipt),
        "gencase_actual_particles": {"total": int(actual["particle_np"]), "fluid": int(actual["type_counts"]["fluid"]), "fixed": int(actual["type_counts"]["fixed"]), "moving": int(actual["type_counts"]["moving"]), "floating": int(actual["type_counts"]["floating"])},
        "source_contract": {
            "definition_sha256": sha256(definition),
            "control_sha256": sha256(control),
            "native_sha256": sha256(native),
            "normal_sha256": sha256(normal),
            "generated_xml_sha256": sha256(xml),
            "generated_bi4_sha256": sha256(bi4),
            "generated_all_vtk_sha256": sha256(all_vtk),
            "generated_fluid_vtk_sha256": sha256(fluid_vtk),
            "generated_bound_vtk_sha256": sha256(bound_vtk),
            "continuous_fluid_mass_kg": 5120.0,
            "aggregate_massbody_kg": 128.0,
            "aggregate_center_m": [2.4, 1.2, 1.08],
            "aggregate_inertia_diag_kg_m2": [8.533333333333335, 8.533333333333335, 13.653333333333336],
            "source_input_hashes": input_hashes,
        },
        "postprocessing_plan": {
            "floating_info": [str(FLOATING_INFO.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savedata", "{attempt_root}/solver_output/floatinginfo/FloatingMotion"],
            "compute_forces": [str(COMPUTE_FORCES.resolve()), "-dirdata", "{attempt_root}/solver_output/data", "-onlymk:50", "-savecsv", "{attempt_root}/solver_output/forces/FloatingForce"],
            "required_state_fields": ["pose", "orientation_quaternion", "linear_velocity", "angular_velocity", "massbody", "inertia", "fluid_force", "fluid_torque"],
            "native_torque_semantics": "FloatingInfo fluidforceang is current COM at force accumulation; ComputeForces moment remains separate fixed reference [2.4,1.2,1.08]",
            "labels_pending_shared_cpu": True,
        },
        "cost_estimate": {
            "basis": "actual fine raw native trees scaled by fluid-particle ratio 327680/80000=4.096; reserve 10 GiB per case",
            "estimated_peak_gpu_mib": ESTIMATED_GPU_MIB,
            "estimated_storage_bytes": ESTIMATED_STORAGE_BYTES,
            "estimated_native_particles": int(actual["particle_np"]),
            "estimated_gpu_seconds": 1200,
        },
        "qualification_claim": "none_until_root_dispatch_and_complete_native_postprocessing",
        "q_n_status": "pending",
        "gpu_launch": "root_only",
        "root_review_required": True,
        "launch_commit_required": "root records the dispatch commit; request and all source hashes are frozen here",
    }
    return request


def prepare() -> dict[str, Any]:
    preflight = read_json(PREflight)
    manifest = read_json(FAMILY_ROOT / "manifest.json")
    by_case = {row["case_id"]: row for row in preflight["cases"]}
    requests = []
    for case in manifest["cases"]:
        request = _case_request(case, preflight, by_case[case["case_id"]])
        path = REQUEST_ROOT / f"{case['case_id']}.json"
        write_json(path, request)
        requests.append({"case_id": case["case_id"], "path": str(path.resolve()), "sha256": sha256(path), "attempt_id": request["attempt_id"]})
    result = {
        "schema": "ds-data-02.f6.commensurate_dp025_rigid003.qualification_requests.v1",
        "family_id": "F6",
        "scope_id": "F6_HANDOFF_20261002_COMMENSURATE_DP025_RIGID003",
        "status": "root_dispatch_pending",
        "gpu_launch": False,
        "source_preflight": {"path": str(PREflight.resolve()), "sha256": sha256(PREflight)},
        "requests": requests,
        "qualification_claim": "none",
        "q_n_status": "pending root review",
        "storage_reservation_per_case_bytes": ESTIMATED_STORAGE_BYTES,
    }
    write_json(REQUEST_ROOT / "request_manifest.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare"])
    args = parser.parse_args()
    result = prepare() if args.action == "prepare" else None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
