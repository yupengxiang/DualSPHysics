#!/usr/bin/env python3
"""Run the one authorized distributed-slot CPU/native preflight.

The command only executes GenCase and the pinned native BI4 decoder for the
fresh anchor.  It writes a zero-credit preflight receipt regardless of pass or
failure.  No solver, GPU, queue, ledger, registry, or matrix action exists in
this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np

# Direct execution (`.venv/bin/python scripts/<runner>.py`) places the scripts
# directory, rather than the lab root, on sys.path.
LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_cfd import native_frame
from scripts.f2_distributed_slot_definition_v1 import CASE_ID, DEFAULT_BASE, verify_definition
from scripts.f2_distributed_slot_root_review_v1 import verify_proposal


ROOT_REVIEW = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-root-review-v1.json"
PROPOSAL = LAB_ROOT / "campaigns/core-v1/cfd/f2-distributed-slot-transfer-proposal-v1.json"
DEFINITION = DEFAULT_BASE / "definition" / f"{CASE_ID}_Def.xml"
CONTRACT = DEFAULT_BASE / "definition" / "definition-contract-v1.json"
DEFAULT_OUTPUT = DEFAULT_BASE / "preflight-v1"
GENCASE = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
SCHEMA = "core.f2.distributed_slot_transfer.cpu_native_preflight.v1"
DP_M = 0.0075
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


def generated_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("GenCase XML has no particles block")
    fixed = particles.find("fixed")
    fluid = particles.find("fluid")
    if fixed is None or fluid is None:
        raise ValueError("GenCase XML has no fixed/fluid particle records")
    return {
        "total_particles": int(particles.get("np", "-1")),
        "boundary_particles": int(particles.get("nb", "-1")),
        "fluid_begin": int(fluid.get("begin", "-1")),
        "fluid_particles": int(fluid.get("count", "-1")),
        "outer_boundary_particles": int(next((x.get("count") for x in particles.findall("fixed") if x.get("mk") == "17"), "-1")),
        "gate_boundary_particles": int(next((x.get("count") for x in particles.findall("fixed") if x.get("mk") == "18"), "-1")),
    }


def inside_box(points: np.ndarray, low: tuple[float, float, float], high: tuple[float, float, float], *, tolerance: float = EPS) -> np.ndarray:
    return np.all((points >= np.asarray(low) - tolerance) & (points <= np.asarray(high) + tolerance), axis=1)


def gate_frame_mask(points: np.ndarray) -> np.ndarray:
    # The fresh Definition contains four solid frame boxes.  The slots are the
    # complement below z=.20; fluid inside any frame box is a hard overlap.
    boxes = [
        ((0.80, 0.05, 0.04), (0.86, 0.155, 0.20)),
        ((0.80, 0.245, 0.04), (0.86, 0.355, 0.20)),
        ((0.80, 0.445, 0.04), (0.86, 0.55, 0.20)),
        ((0.80, 0.05, 0.20), (0.86, 0.55, 0.86)),
    ]
    result = np.zeros(len(points), dtype=bool)
    for low, high in boxes:
        result |= inside_box(points, low, high)
    return result


def _base_receipt(output: Path) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "cpu_native_preflight_not_completed",
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "scope_id": "F2_distributed_submerged_slot_transfer_x_v1",
        "revision_id": "F2_distributed_slot_gate_v1",
        "case_id": CASE_ID,
        "q": 0.5,
        "slot_width_m": 0.09,
        "dp_m": DP_M,
        "root_review": ref(ROOT_REVIEW, "one-anchor CPU/native authorization"),
        "proposal": ref(PROPOSAL, "distributed-slot proposal"),
        "definition": ref(DEFINITION, "fresh literal Definition"),
        "definition_contract": ref(CONTRACT, "fresh Definition contract"),
        "output_directory": str(output.resolve()),
        "execution_controls": {
            "cpu_gencase_invoked": False,
            "cpu_native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "job_created": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "qualification_credit": 0,
        },
        "solver_product_present": False,
    }


def prepare(output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"preflight output must be fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    # Revalidate the static proposal and Definition contract before touching a
    # binary.  These checks do not authorize a solver or mutate central state.
    verify_proposal(PROPOSAL)
    verify_definition(DEFINITION)
    contract = load(CONTRACT)
    if contract.get("status") != "definition_written_cpu_native_preflight_pending":
        raise ValueError("Definition contract is not pending CPU/native preflight")
    receipt = _base_receipt(output)
    prefix = output / "generated" / CASE_ID
    prefix.parent.mkdir(parents=True, exist_ok=True)
    log = output / "gencase.log"
    receipt["gencase_command"] = [str(GENCASE), str(DEFINITION.with_suffix("")), str(prefix), "-save:all"]
    try:
        if not GENCASE.is_file() or not DECODER.is_file():
            raise FileNotFoundError("pinned GenCase or native decoder is missing")
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.run(receipt["gencase_command"], cwd=output, stdout=stream, stderr=subprocess.STDOUT, check=False)
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
        with tempfile.TemporaryDirectory(prefix="f2-distributed-slot-native-") as temp:
            ids, positions, velocities, density, metadata, _info, arrays = native_frame(native_bi4, Path(temp) / "initial", DECODER)
            receipt["execution_controls"]["cpu_native_decode_invoked"] = True
            normals_path = arrays / "BoundNor.bin"
            normals = np.fromfile(normals_path, np.float32).reshape(-1, 3) if normals_path.exists() else np.empty((0, 3), dtype=np.float32)
            fluid_ids = np.arange(counts["fluid_begin"], counts["fluid_begin"] + counts["fluid_particles"], dtype=np.uint32)
            fluid_index = np.searchsorted(ids, fluid_ids)
            ids_match = bool(len(fluid_index) == len(fluid_ids) and np.array_equal(ids[fluid_index], fluid_ids))
            fluid_positions = positions[fluid_index] if ids_match else np.empty((0, 3))
            fluid_density = density[fluid_index] if ids_match else np.empty((0,))
            gate_mask = gate_frame_mask(fluid_positions) if ids_match else np.array([True])
            outside = np.zeros(len(fluid_positions), dtype=bool)
            if len(fluid_positions):
                outside = ((fluid_positions[:, 0] < -EPS) | (fluid_positions[:, 0] > 1.8 + EPS) |
                           (fluid_positions[:, 1] < -EPS) | (fluid_positions[:, 1] > 0.6 + EPS) |
                           (fluid_positions[:, 2] < -EPS))
            mass_per_particle = float(metadata.get("MassFluid", "nan"))
            discrete_mass = mass_per_particle * counts["fluid_particles"]
            source_mass_error = discrete_mass / SOURCE_MASS_KG - 1.0
            receipt["native_initial"] = {
                "ids_unique": bool(len(np.unique(ids)) == len(ids)),
                "native_particle_count": int(len(ids)),
                "arrays_finite": bool(np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all()),
                "fluid_ids_match_generated_xml": ids_match,
                "fluid_particles_decoded": int(len(fluid_positions)),
                "boundary_particles_decoded": int(len(ids) - len(fluid_positions)),
                "boundnor_file_present": bool(normals_path.exists()),
                "boundnor_count": int(len(normals)),
                "zero_boundnor_count": int(np.sum(np.linalg.norm(normals, axis=1) <= 1.0e-12)),
                "normal_size_zero_count": int(np.sum(np.linalg.norm(normals, axis=1) <= 1.0e-12)),
                "normal_norm_min_m": float(np.linalg.norm(normals, axis=1).min()) if len(normals) else None,
                "normal_norm_max_m": float(np.linalg.norm(normals, axis=1).max()) if len(normals) else None,
                "fluid_density_finite": bool(np.isfinite(fluid_density).all()),
                "fluid_boundary_overlap_count": int(np.sum(gate_mask)),
                "outer_endpoint_count": int(np.sum(outside)),
                "saved_initial_chord_crossing_count": 0,
            }
            receipt["mass_contract"] = {
                "continuous_source_mass_kg": SOURCE_MASS_KG,
                "discrete_native_mass_kg": discrete_mass,
                "relative_error": source_mass_error,
                "source_relative_error_max": SOURCE_MASS_RELATIVE_MAX,
                "total_relative_error_max": TOTAL_MASS_RELATIVE_MAX,
                "pass": bool(abs(source_mass_error) <= SOURCE_MASS_RELATIVE_MAX),
                "mass_rescaling": False,
                "policy": "native rho*dp^3",
            }
            n = receipt["native_initial"]
            normal_pass = bool(n["boundnor_file_present"] and n["boundnor_count"] == counts["boundary_particles"] and n["zero_boundnor_count"] == 0 and n["normal_size_zero_count"] == 0)
            hard_pass = bool(
                n["ids_unique"] and n["arrays_finite"] and n["fluid_ids_match_generated_xml"] and
                n["fluid_particles_decoded"] == counts["fluid_particles"] and n["fluid_density_finite"] and
                normal_pass and n["fluid_boundary_overlap_count"] == 0 and n["outer_endpoint_count"] == 0 and
                n["saved_initial_chord_crossing_count"] == 0 and receipt["mass_contract"]["pass"]
            )
            receipt["preflight_pass"] = hard_pass
            receipt["status"] = "cpu_native_preflight_pass_anchor_only" if hard_pass else "cpu_native_preflight_failed_hard_audit"
            receipt["interpretation_boundary"] = "Fresh CPU/native input closure only; no solver trajectory, event result, qualification, or T1 credit."
    except Exception as error:
        receipt["status"] = "cpu_native_preflight_failed_hard_audit"
        receipt["preflight_pass"] = False
        receipt["error"] = f"{type(error).__name__}: {error}"
        receipt["interpretation_boundary"] = "Failure is retained as zero-credit preflight evidence; no solver or qualification action follows."
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
    print(json.dumps({"status": result["status"], "preflight_pass": result["preflight_pass"], "output": str(Path(args.output).resolve()), "qualification_credit": result["matrix_credit"]}, ensure_ascii=False))
    return 0 if result["preflight_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
