#!/usr/bin/env python3
"""Run exactly one fresh F5 v3 CPU/GenCase/native preflight.

The root-review receipt authorizes this one static preflight only.  The base
F5 preflight implementation is reused for GenCase, native decoding, finite
arrays, identity, mass, and generated geometry checks.  This wrapper captures
the single native decode and adds the root-reviewed fluid-only frame-0 slope
and block endpoint gates.  It never invokes the solver or CUDA and never
mutates the Core registry, ledger, or qualification matrix.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))
from scripts import f5_wave_runup_preflight_v1 as base  # noqa: E402
from scripts.f5_wave_runup_solver_anchor_scientific_review_v1 import (  # noqa: E402
    points_inside_mesh,
    read_binary_stl,
    transform_wave_stl,
)


ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1"
INPUT = ROOT / "input"
REVIEW = ROOT / "root-review-receipt-v1.json"
CONTRACT = INPUT / "geometry-repair-contract-v1.json"
DEFINITION = INPUT / "F5_wave_runup_q0p50_dp0p0075_geomrepair_v3_Def.xml"
MOTION = INPUT / "Mov_piston_q0p50_scaled_geomrepair_v3.dat"
SLOPE = INPUT / "Slope_geomrepair_v3.stl"
BLOCKS = INPUT / "Blocks_3D_scaled_geomrepair_v3.stl"
OUTPUT = ROOT / "preflight-v3"
CASE_ID = "F5_wave_runup_q0p50_dp0p0075_geomrepair_v3"
RUNNER = LAB / "scripts/f5_wave_runup_geometry_repair_preflight_v1.py"
ROOT_REVIEW_RUNNER = LAB / "scripts/f5_wave_runup_geometry_repair_root_review_v1.py"
WRITER = LAB / "scripts/f5_wave_runup_geometry_repair_writer_v1.py"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
GENCASE = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"


def sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(LAB))


def bind(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _verify_contract() -> dict[str, Any]:
    review = load(REVIEW)
    if review.get("schema") != "core.f5.third_t1.geometry_repair_root_review_receipt.v1":
        raise ValueError("wrong geometry repair root-review schema")
    decision = review.get("review_decision", {})
    if review.get("status") != "authorized_one_fresh_cpu_native_preflight_only" or decision.get("authorized_cpu_native_preflight") is not True:
        raise ValueError("v3 CPU/native preflight is not authorized")
    if any(decision.get(key) for key in ("authorized_solver", "authorized_gpu", "authorized_queue", "authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("v3 root review opens a forbidden path")
    contract = load(CONTRACT)
    if contract.get("schema") != "core.f5.third_t1.geometry_repair_materialization.v1":
        raise ValueError("wrong v3 materialization contract schema")
    if contract.get("status") not in {"v3_definition_written_preflight_pending", "v3_definition_written_preflight_pending_after_static_repair"}:
        raise ValueError("v3 materialization is not pending preflight")
    if contract.get("qualification_claim") != "none" or contract.get("fixed_contract", {}).get("same_input_retry") is not False:
        raise ValueError("v3 contract carries credit or opens retry")
    candidate = contract.get("candidate", {})
    if candidate.get("case_id") != CASE_ID or candidate.get("dp_m") != 0.0075 or candidate.get("q") != 0.5:
        raise ValueError("v3 candidate identity changed")
    root_binding = contract.get("repair_lineage", {}).get("root_review")
    if not root_binding or root_binding.get("path") != rel(REVIEW) or root_binding.get("sha256") != sha256(REVIEW):
        raise ValueError("v3 contract is not bound to the current root review")
    definition_binding = contract.get("fresh_identity", {}).get("definition", {}).get("output", contract.get("fresh_identity", {}).get("definition"))
    motion_binding = contract.get("fresh_identity", {}).get("motion", {}).get("output", contract.get("fresh_identity", {}).get("motion"))
    for item in [definition_binding, motion_binding, *contract.get("fresh_identity", {}).get("definition_adjacent_assets", [])]:
        path = LAB / item["path"]
        if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
            raise ValueError(f"stale v3 input binding: {path}")
    if not DEFINITION.is_file() or not MOTION.is_file() or not SLOPE.is_file() or not BLOCKS.is_file():
        raise FileNotFoundError("v3 input identity is incomplete")
    if not GENCASE.is_file() or not DECODER.is_file():
        raise FileNotFoundError("pinned GenCase or native decoder is missing")
    return {"review": review, "contract": contract}


def _geometry_repair_gate(native_result: tuple, generated: dict[str, Any]) -> dict[str, Any]:
    ids, positions, _velocity, _density, metadata, _info, _arrays = native_result
    fluid_first_id = int(generated["boundary_particles"])
    fluid_mask = ids >= fluid_first_id
    fluid_positions = positions[fluid_mask]
    if len(fluid_positions) != int(generated["fluid_particles"]):
        raise ValueError("generated boundary count cannot identify the generated fluid axis")
    slope = transform_wave_stl(read_binary_stl(SLOPE))
    blocks = transform_wave_stl(read_binary_stl(BLOCKS))
    slope_inside = points_inside_mesh(fluid_positions, slope)
    blocks_inside = points_inside_mesh(fluid_positions, blocks)
    return {
        "scope": "frame0_fluid_only",
        "fluid_first_id": fluid_first_id,
        "fluid_particles": int(len(fluid_positions)),
        "slope_endpoint_inside_count": int(slope_inside.sum()),
        "blocks_endpoint_inside_count": int(blocks_inside.sum()),
        "endpoint_tolerance_m": 1.0e-8,
        "slope_gate_pass": int(slope_inside.sum()) == 0,
        "blocks_gate_pass": int(blocks_inside.sum()) == 0,
        "pass": bool(not slope_inside.any() and not blocks_inside.any()),
        "source_meshes": {"slope": bind(SLOPE, "v3 slope source used for exact fluid endpoint gate"),
                          "blocks": bind(BLOCKS, "v3 blocks source used for exact fluid endpoint gate")},
    }


def _base_verify_receipt() -> dict[str, Any]:
    _verify_contract()
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"v3 preflight output already materialized: {OUTPUT}")
    return load(REVIEW)


def run_once() -> dict[str, Any]:
    _verify_contract()
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"v3 preflight output already materialized: {OUTPUT}")
    captured: dict[str, tuple] = {}
    original_native_frame = base.native_frame

    def capture_native_frame(*args: Any, **kwargs: Any) -> tuple:
        result = original_native_frame(*args, **kwargs)
        captured["frame0"] = result
        return result

    original_receipt = base._verify_receipt
    original_bind = base.bind
    base.native_frame = capture_native_frame
    base._verify_receipt = _base_verify_receipt
    base.ROOT = INPUT
    base.REVIEW = REVIEW
    base.DEFINITION = DEFINITION
    base.OUTPUT = OUTPUT
    base.CASE_ID = CASE_ID
    base.GENCASE = GENCASE
    base.DECODER = DECODER

    def bind_motion_alias(path: Path, role: str) -> dict[str, Any]:
        if Path(path).name == "Mov_piston_q0p50_scaled.dat":
            return original_bind(MOTION, role)
        return original_bind(path, role)

    base.bind = bind_motion_alias
    try:
        result = base.run_once()
    finally:
        base.native_frame = original_native_frame
        base._verify_receipt = original_receipt
        base.bind = original_bind
    if result.get("gencase", {}).get("return_code") == 0 and result.get("generated") and "frame0" in captured:
        result["geometry_repair"] = _geometry_repair_gate(captured["frame0"], result["generated"])
    else:
        result["geometry_repair"] = {"pass": False, "status": "not_evaluated_before_gencase_or_native_failure", "scope": "frame0_fluid_only"}
    gates = result.setdefault("hard_gates", {})
    gates["frame0_fluid_endpoint_inside_slope"] = bool(result["geometry_repair"].get("slope_gate_pass", False))
    gates["frame0_fluid_endpoint_inside_blocks"] = bool(result["geometry_repair"].get("blocks_gate_pass", False))
    result["preflight_pass"] = bool(result.get("preflight_pass", False) and result["geometry_repair"].get("pass", False))
    result["qualified"] = False
    result["matrix_credit"] = 0
    result["qualification_claim"] = "none"
    result["status"] = "cpu_native_preflight_passed_static_only" if result["preflight_pass"] else "cpu_native_preflight_failed_geometry_repair_gate"
    result["execution_controls"].update({"solver_invoked": False, "gpu_started": False, "queue_mutation": 0,
                                          "ledger_mutation": 0, "registry_mutation": 0, "matrix_mutation": 0, "qualification_credit": 0})
    result["repair_bindings"] = {"root_review": bind(REVIEW, "v3 geometry repair root review"),
                                  "contract": bind(CONTRACT, "v3 geometry repair materialization contract"),
                                  "runner": bind(RUNNER, "v3 CPU/native preflight runner"),
                                  "root_review_runner": bind(ROOT_REVIEW_RUNNER, "v3 root-review implementation"),
                                  "writer": bind(WRITER, "v3 input writer")}
    output_path = OUTPUT / "preflight.json"
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    result.setdefault("artifacts", {}).setdefault("preflight", {})["sha256"] = sha256(output_path)
    return result


def verify_materialized() -> dict[str, Any]:
    record = load(OUTPUT / "preflight.json")
    if record.get("schema") != "core.f5.third_t1.preflight.v1":
        raise ValueError("wrong v3 preflight schema")
    if record.get("qualification_claim") != "none" or record.get("qualified") is not False or record.get("matrix_credit") != 0:
        raise ValueError("v3 preflight carries scientific credit")
    controls = record.get("execution_controls", {})
    if controls.get("solver_invoked") is not False or controls.get("gpu_started") is not False:
        raise ValueError("v3 preflight claims solver/GPU execution")
    gate = record.get("geometry_repair", {})
    if gate.get("scope") != "frame0_fluid_only":
        raise ValueError("v3 geometry gate scope changed")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run-once", "verify-preflight"))
    args = parser.parse_args()
    result = run_once() if args.command == "run-once" else verify_materialized()
    print(json.dumps({"status": result.get("status"), "preflight_pass": result.get("preflight_pass"),
                      "geometry_repair": result.get("geometry_repair"), "qualified": result.get("qualified"),
                      "matrix_credit": result.get("matrix_credit", 0), "output": rel(OUTPUT / "preflight.json")},
                     indent=2, ensure_ascii=False))
    return 0 if args.command == "verify-preflight" or result.get("preflight_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
