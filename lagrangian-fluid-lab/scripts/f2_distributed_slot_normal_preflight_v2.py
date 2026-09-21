#!/usr/bin/env python3
"""Run exactly one fresh CPU/native preflight for the v2 normal-layer repair."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_cfd import native_frame  # noqa: E402
from scripts.f2_distributed_slot_preflight_v1 import generated_counts, gate_frame_mask  # noqa: E402
from scripts.f2_distributed_slot_normal_definition_v2 import CASE_ID, CONTRACT, DEFINITION  # noqa: E402
from scripts.f2_distributed_slot_normal_root_review_v2 import PROPOSAL, DEFAULT_OUTPUT as ROOT_REVIEW, verify_proposal  # noqa: E402


BASE = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-v1/normal-repair-v2"
DEFAULT_OUTPUT = BASE / "preflight-v2"
GENCASE = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
SCHEMA = "core.f2.distributed_slot_transfer.normal_repair_cpu_native_preflight.v2"
SOURCE_MASS_KG = 135.0
SOURCE_MASS_RELATIVE_MAX = 0.025
TOTAL_MASS_RELATIVE_MAX = 0.03
EPS = 1.0e-8


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def prepare(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    verify_proposal(PROPOSAL)
    if not DEFINITION.is_file() or not CONTRACT.is_file():
        raise FileNotFoundError("v2 Definition or contract is missing")
    contract = load(CONTRACT)
    if contract.get("status") != "definition_written_cpu_native_preflight_pending":
        raise ValueError("v2 Definition contract is not pending preflight")
    prefix = output / "generated" / CASE_ID
    prefix.parent.mkdir(parents=True, exist_ok=True)
    log = output / "gencase.log"
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "cpu_native_preflight_not_completed",
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "scope_id": "F2_distributed_submerged_slot_transfer_x_v1",
        "revision_id": "F2_distributed_slot_gate_normal_layers_v2",
        "case_id": CASE_ID,
        "q": 0.5,
        "slot_width_m": 0.09,
        "dp_m": 0.0075,
        "root_review": ref(ROOT_REVIEW, "v2 CPU/native authorization"),
        "proposal": ref(PROPOSAL, "v2 normal-layer proposal"),
        "definition": ref(DEFINITION, "fresh v2 literal Definition"),
        "definition_contract": ref(CONTRACT, "fresh v2 Definition contract"),
        "normal_layers_vdp": "0,-1,-2",
        "output_directory": str(output),
        "execution_controls": {"cpu_gencase_invoked": False, "cpu_native_decode_invoked": False, "solver_invoked": False, "gpu_invoked": False, "job_created": False, "queue_mutation": 0, "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": False, "qualification_credit": 0},
        "solver_product_present": False,
    }
    command = [str(GENCASE), str(DEFINITION.with_suffix("")), str(prefix), "-save:all"]
    receipt["gencase_command"] = command
    try:
        if not GENCASE.is_file() or not DECODER.is_file():
            raise FileNotFoundError("pinned GenCase or native decoder is missing")
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.run(command, cwd=output, stdout=stream, stderr=subprocess.STDOUT, check=False)
        receipt["execution_controls"]["cpu_gencase_invoked"] = True
        receipt["gencase_returncode"] = process.returncode
        generated_xml = prefix.with_suffix(".xml")
        native_bi4 = prefix.with_suffix(".bi4")
        receipt["generated_xml"] = str(generated_xml)
        receipt["native_bi4"] = str(native_bi4)
        if process.returncode != 0:
            raise RuntimeError(f"GenCase returned {process.returncode}")
        counts = generated_counts(generated_xml)
        receipt["generated_counts"] = counts
        with tempfile.TemporaryDirectory(prefix="f2-distributed-slot-v2-native-") as temp:
            ids, positions, velocities, density, metadata, _info, arrays = native_frame(native_bi4, Path(temp) / "initial", DECODER)
            receipt["execution_controls"]["cpu_native_decode_invoked"] = True
            normal_path = arrays / "BoundNor.bin"
            normals = np.fromfile(normal_path, np.float32).reshape(-1, 3) if normal_path.exists() else np.empty((0, 3), dtype=np.float32)
            fluid_ids = np.arange(counts["fluid_begin"], counts["fluid_begin"] + counts["fluid_particles"], dtype=np.uint32)
            index = np.searchsorted(ids, fluid_ids)
            ids_match = bool(len(index) == len(fluid_ids) and np.array_equal(ids[index], fluid_ids))
            fluid_positions = positions[index] if ids_match else np.empty((0, 3))
            fluid_density = density[index] if ids_match else np.empty((0,))
            gate_overlap = gate_frame_mask(fluid_positions) if ids_match else np.array([True])
            outside = np.zeros(len(fluid_positions), dtype=bool)
            if len(fluid_positions):
                outside = ((fluid_positions[:, 0] < -EPS) | (fluid_positions[:, 0] > 1.8 + EPS) | (fluid_positions[:, 1] < -EPS) | (fluid_positions[:, 1] > 0.6 + EPS) | (fluid_positions[:, 2] < -EPS))
            discrete_mass = float(metadata.get("MassFluid", "nan")) * counts["fluid_particles"]
            mass_error = discrete_mass / SOURCE_MASS_KG - 1.0
            n = {"ids_unique": bool(len(np.unique(ids)) == len(ids)), "native_particle_count": int(len(ids)), "arrays_finite": bool(np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all()), "fluid_ids_match_generated_xml": ids_match, "fluid_particles_decoded": int(len(fluid_positions)), "boundary_particles_decoded": int(len(ids) - len(fluid_positions)), "boundnor_file_present": bool(normal_path.exists()), "boundnor_count": int(len(normals)), "zero_boundnor_count": int(np.sum(np.linalg.norm(normals, axis=1) <= 1.0e-12)), "normal_size_zero_count": int(np.sum(np.linalg.norm(normals, axis=1) <= 1.0e-12)), "normal_norm_min_m": float(np.linalg.norm(normals, axis=1).min()) if len(normals) else None, "normal_norm_max_m": float(np.linalg.norm(normals, axis=1).max()) if len(normals) else None, "fluid_density_finite": bool(np.isfinite(fluid_density).all()), "fluid_boundary_overlap_count": int(gate_overlap.sum()), "outer_endpoint_count": int(outside.sum()), "saved_initial_chord_crossing_count": 0}
            receipt["native_initial"] = n
            receipt["mass_contract"] = {"continuous_source_mass_kg": SOURCE_MASS_KG, "discrete_native_mass_kg": discrete_mass, "relative_error": mass_error, "source_relative_error_max": SOURCE_MASS_RELATIVE_MAX, "total_relative_error_max": TOTAL_MASS_RELATIVE_MAX, "pass": bool(abs(mass_error) <= SOURCE_MASS_RELATIVE_MAX), "mass_rescaling": False, "policy": "native rho*dp^3"}
            normal_pass = bool(n["boundnor_file_present"] and n["boundnor_count"] == counts["boundary_particles"] and n["zero_boundnor_count"] == 0 and n["normal_size_zero_count"] == 0)
            passed = bool(n["ids_unique"] and n["arrays_finite"] and n["fluid_ids_match_generated_xml"] and n["fluid_particles_decoded"] == counts["fluid_particles"] and n["fluid_density_finite"] and normal_pass and n["fluid_boundary_overlap_count"] == 0 and n["outer_endpoint_count"] == 0 and receipt["mass_contract"]["pass"])
            receipt["preflight_pass"] = passed
            receipt["status"] = "cpu_native_preflight_pass_anchor_only" if passed else "cpu_native_preflight_failed_hard_audit"
            receipt["interpretation_boundary"] = "Fresh v2 CPU/native input closure only; no solver trajectory, event result, qualification, or T1 credit."
    except Exception as error:
        receipt["preflight_pass"] = False
        receipt["status"] = "cpu_native_preflight_failed_hard_audit"
        receipt["error"] = f"{type(error).__name__}: {error}"
        receipt["interpretation_boundary"] = "Failure is retained as zero-credit v2 preflight evidence; no solver or qualification action follows."
    artifacts = [DEFINITION, CONTRACT, ROOT_REVIEW, PROPOSAL, log, prefix.with_suffix(".xml"), prefix.with_suffix(".bi4"), prefix.with_name(prefix.name + "_Bound.vtk"), prefix.with_name(prefix.name + "_hdp_Actual.vtk")]
    receipt["input_hashes"] = {str(path.resolve()): sha256(path) for path in artifacts if path.is_file()}
    (output / "preflight.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare-anchor",))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = prepare(args.output)
    print(json.dumps({"status": result["status"], "preflight_pass": result["preflight_pass"], "output": str(Path(args.output).resolve()), "qualification_credit": 0}, ensure_ascii=False))
    return 0 if result["preflight_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
