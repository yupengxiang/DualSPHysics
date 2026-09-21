#!/usr/bin/env python3
"""Run the single authorized v2 CPU/native input preflight.

Only the official CPU GenCase executable and the native ``bi4_dump`` decoder
are called.  This module has no solver, GPU, queue, registry, ledger, or
qualification-matrix entry point.  The fresh output namespace is one-shot:
any existing product prevents another call, including after a hard failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.core_cfd import environment, native_frame  # noqa: E402
from scripts import f2_receiver_ballistic_catch_release010_v2_definition as definition  # noqa: E402
from scripts import f2_receiver_ballistic_catch_release010_v2_observer as observer  # noqa: E402
from scripts import f2_receiver_ballistic_catch_release010_v2_root_review as admission  # noqa: E402


BASE = definition.BASE
PREFLIGHT_DIR = BASE / "preflight-v2"
GENERATED_PREFIX = PREFLIGHT_DIR / "generated" / definition.CASE_ID
PREFLIGHT_RECEIPT = PREFLIGHT_DIR / "preflight-v2.json"
GENCASE = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
SCHEMA = "core.f2.receiver_ballistic_catch.cpu_native_preflight.v2"
ENDPOINT_TOLERANCE_M = 1.0e-8
RECEIVER_SURFACE_TOLERANCE_M = definition.DP_M
SOURCE_DENSITY_KG_M3 = 1000.0
MASS_RELATIVE_ERROR_MAX = 0.025


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
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


def _generated_counts(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles = root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML has no particles section")
    total = int(particles.get("np", "-1"))
    boundary = int(particles.get("nb", "-1"))
    fixed = particles.findall("fixed")
    fluids = particles.findall("fluid")
    if len(fixed) != 2 or len(fluids) != 1:
        raise ValueError("generated XML must contain two fixed blocks and one fluid block")
    blocks = [*fixed, *fluids]
    spans = []
    for block in blocks:
        begin, count = int(block.get("begin", "-1")), int(block.get("count", "-1"))
        if begin < 0 or count <= 0:
            raise ValueError("generated XML block span is invalid")
        spans.append((begin, count))
    expected = np.concatenate([
        np.arange(begin, begin + count, dtype=np.uint32) for begin, count in spans
    ])
    if len(expected) != total or not np.array_equal(expected, np.arange(total, dtype=np.uint32)):
        raise ValueError("generated XML IDs are not contiguous")
    if boundary != sum(count for _, count in spans[:2]):
        raise ValueError("generated XML boundary count mismatch")
    return {
        "total_particles": total,
        "boundary_particles": boundary,
        "fluid_particles": spans[2][1],
        "fluid_begin": spans[2][0],
        "outer_boundary_particles": spans[0][1],
        "receiver_boundary_particles": spans[1][1],
        "xml_ids_contiguous": True,
    }


def _receiver_surface_overlap(positions: np.ndarray) -> int:
    pos = np.asarray(positions, dtype=float)
    low = np.array(definition.RECEIVER_LOW)
    high = low + np.array(definition.RECEIVER_SIZE)
    tol = RECEIVER_SURFACE_TOLERANCE_M
    inside_xy = (
        (pos[:, 0] >= low[0] - tol) & (pos[:, 0] <= high[0] + tol) &
        (pos[:, 1] >= low[1] - tol) & (pos[:, 1] <= high[1] + tol)
    )
    side_z = (pos[:, 2] >= low[2] - tol) & (pos[:, 2] <= high[2] + tol)
    bottom = inside_xy & (np.abs(pos[:, 2] - low[2]) <= tol)
    left = side_z & (np.abs(pos[:, 0] - low[0]) <= tol) & (pos[:, 1] >= low[1] - tol) & (pos[:, 1] <= high[1] + tol)
    right = side_z & (np.abs(pos[:, 0] - high[0]) <= tol) & (pos[:, 1] >= low[1] - tol) & (pos[:, 1] <= high[1] + tol)
    front = side_z & (np.abs(pos[:, 1] - low[1]) <= tol) & (pos[:, 0] >= low[0] - tol) & (pos[:, 0] <= high[0] + tol)
    back = side_z & (np.abs(pos[:, 1] - high[1]) <= tol) & (pos[:, 0] >= low[0] - tol) & (pos[:, 0] <= high[0] + tol)
    return int(np.count_nonzero(bottom | left | right | front | back))


def _runtime_outside(positions: np.ndarray) -> int:
    low = np.array(definition.RUNTIME_LOW)
    high = np.array(definition.RUNTIME_HIGH)
    outside = np.any((positions < low[None, :] - ENDPOINT_TOLERANCE_M) |
                     (positions > high[None, :] + ENDPOINT_TOLERANCE_M), axis=1)
    return int(np.count_nonzero(outside))


def _audit_native(ids: np.ndarray, positions: np.ndarray, velocity: np.ndarray,
                  density: np.ndarray, metadata: dict[str, str], counts: dict[str, Any]) -> dict[str, Any]:
    total = counts["total_particles"]
    fluid_begin = counts["fluid_begin"]
    fluid_count = counts["fluid_particles"]
    expected = np.arange(total, dtype=np.uint32)
    ids_unique = len(np.unique(ids)) == len(ids)
    ids_match = len(ids) == total and np.array_equal(ids, expected)
    fluid_ids_match = ids_match and np.array_equal(
        ids[fluid_begin:fluid_begin + fluid_count],
        np.arange(fluid_begin, fluid_begin + fluid_count, dtype=np.uint32),
    )
    arrays_finite = bool(all(np.isfinite(array).all() for array in (positions, velocity, density)))
    fluid_pos = positions[fluid_begin:fluid_begin + fluid_count]
    outer_low = np.array(definition.OUTER_LOW)
    outer_high = outer_low + np.array(definition.OUTER_SIZE)
    outer_endpoint = np.any(
        (fluid_pos < outer_low[None, :] - ENDPOINT_TOLERANCE_M) |
        (fluid_pos > outer_high[None, :] + ENDPOINT_TOLERANCE_M), axis=1
    )
    outer_endpoint_count = int(np.count_nonzero(outer_endpoint))
    receiver_overlap_count = _receiver_surface_overlap(fluid_pos)
    runtime_outside_count = _runtime_outside(fluid_pos)
    mass_fluid = float(metadata.get("MassFluid", "nan"))
    discrete_mass = mass_fluid * fluid_count
    continuous_mass = float(np.prod(definition.SOURCE_SIZE) * SOURCE_DENSITY_KG_M3)
    mass_error = discrete_mass / continuous_mass - 1.0 if np.isfinite(mass_fluid) else float("inf")
    mass_pass = bool(np.isfinite(mass_error) and abs(mass_error) <= MASS_RELATIVE_ERROR_MAX)
    hard = {
        "ids": {
            "unique": bool(ids_unique),
            "match_generated_xml": bool(ids_match),
            "fluid_span_match": bool(fluid_ids_match),
            "pass": bool(ids_unique and ids_match and fluid_ids_match),
        },
        "finite": {
            "positions": bool(np.isfinite(positions).all()),
            "velocity": bool(np.isfinite(velocity).all()),
            "density": bool(np.isfinite(density).all()),
            "pass": arrays_finite,
        },
        "mass": {
            "continuous_source_mass_kg": continuous_mass,
            "discrete_native_mass_kg": discrete_mass,
            "relative_error": mass_error,
            "max_relative_error": MASS_RELATIVE_ERROR_MAX,
            "pass": mass_pass,
        },
        "outer_wall_endpoints": {
            "count": outer_endpoint_count,
            "tolerance_m": ENDPOINT_TOLERANCE_M,
            "pass": outer_endpoint_count == 0,
        },
        "receiver_surface_overlap": {
            "count": receiver_overlap_count,
            "tolerance_m": RECEIVER_SURFACE_TOLERANCE_M,
            "pass": receiver_overlap_count == 0,
        },
        "runtime_domain": {
            "outside_count": runtime_outside_count,
            "tolerance_m": ENDPOINT_TOLERANCE_M,
            "pass": runtime_outside_count == 0,
        },
    }
    return {
        "native_particle_count": int(len(ids)),
        "fluid_particle_count": int(fluid_count),
        "boundary_particle_count": int(counts["boundary_particles"]),
        "ids_unique": bool(ids_unique),
        "ids_match_generated_xml": bool(ids_match),
        "fluid_ids_match_generated_xml": bool(fluid_ids_match),
        "arrays_finite": arrays_finite,
        "outer_wall_endpoint_count": outer_endpoint_count,
        "receiver_surface_overlap_count": receiver_overlap_count,
        "runtime_domain_outside_count": runtime_outside_count,
        "hard_gates": hard,
        "all_hard_gates_pass": bool(all(item["pass"] for item in hard.values())),
        "mass_fluid_kg_per_particle": mass_fluid,
    }


def _fresh_guard() -> None:
    if PREFLIGHT_RECEIPT.exists():
        raise FileExistsError("v2 preflight receipt exists; same-input retry is forbidden")
    if PREFLIGHT_DIR.exists() and any(PREFLIGHT_DIR.iterdir()):
        raise FileExistsError("v2 preflight namespace is not empty; one-shot guard closed")
    if GENERATED_PREFIX.exists() or GENERATED_PREFIX.with_suffix(".xml").exists() or GENERATED_PREFIX.with_suffix(".bi4").exists():
        raise FileExistsError("v2 generated prefix already exists")


def _base_receipt(root_review: dict[str, Any], log: Path) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "cpu_native_preflight_not_completed",
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "scope_id": definition.SCOPE_ID,
        "revision_id": definition.REVISION_ID,
        "case_id": definition.CASE_ID,
        "q": definition.Q,
        "dp_m": definition.DP_M,
        "root_review": ref(admission.ROOT_RECEIPT, "v2 root-review/admission receipt"),
        "definition": ref(definition.DEFAULT_DEFINITION, "fresh v2 literal Definition"),
        "definition_contract": ref(definition.DEFAULT_CONTRACT, "fresh v2 Definition contract"),
        "observer_contract": ref(observer.OUTPUT, "fresh receiver/contact/spill/q observer contract"),
        "implementation": ref(Path(__file__).resolve(), "v2 CPU/native preflight implementation"),
        "output_directory": str(PREFLIGHT_DIR.resolve()),
        "gencase_log": str(log.resolve()),
        "execution_controls": {
            "cpu_gencase_invoked": False,
            "cpu_native_decode_invoked": False,
            "solver_invoked": False,
            "gpu_invoked": False,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_submission": False,
            "T1_denominator_mutation": 0,
            "T2_denominator_mutation": 0,
            "qualification_credit": 0,
        },
        "denominator": {
            "parent_scope_rows": 15,
            "executed_rows": 0,
            "preflight_credit": 0,
            "qualification_credit": 0,
            "same_input_retry": False,
            "parent_denominator_changed": False,
        },
        "solver_product_present": False,
        "event_observation": "not assessed; no trajectory opened",
    }


def run_preflight() -> dict[str, Any]:
    admission.verify_receipt(admission.ROOT_RECEIPT)
    definition.inspect_definition(definition.DEFAULT_DEFINITION)
    observer.verify_contract(observer.OUTPUT)
    contract = load(definition.DEFAULT_CONTRACT)
    if contract.get("definition_sha256") != sha256(definition.DEFAULT_DEFINITION):
        raise ValueError("Definition contract does not bind exact XML")
    _fresh_guard()
    PREFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
    generated_dir = GENERATED_PREFIX.parent
    generated_dir.mkdir(parents=True, exist_ok=True)
    log = PREFLIGHT_DIR / "gencase.stdout.log"
    receipt = _base_receipt(admission.load(admission.ROOT_RECEIPT), log)
    command = [str(GENCASE), str(definition.DEFAULT_DEFINITION.with_suffix("")), str(GENERATED_PREFIX), "-save:all"]
    receipt["gencase_command"] = command
    try:
        if not GENCASE.is_file() or not DECODER.is_file():
            raise FileNotFoundError("pinned CPU GenCase or native decoder is missing")
        env = environment(LAB)
        env["CUDA_VISIBLE_DEVICES"] = ""
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.run(command, cwd=PREFLIGHT_DIR, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
        receipt["execution_controls"]["cpu_gencase_invoked"] = True
        receipt["gencase_returncode"] = int(process.returncode)
        if process.returncode != 0:
            raise RuntimeError(f"GenCase returned {process.returncode}")
        generated_xml = GENERATED_PREFIX.with_suffix(".xml")
        generated_bi4 = GENERATED_PREFIX.with_suffix(".bi4")
        counts = _generated_counts(generated_xml)
        receipt["generated_counts"] = counts
        with tempfile.TemporaryDirectory(prefix="f2-release010-v2-native-") as folder:
            ids, positions, velocity, density, metadata, info, arrays = native_frame(
                generated_bi4, Path(folder) / "initial", DECODER
            )
            receipt["execution_controls"]["cpu_native_decode_invoked"] = True
            audit = _audit_native(ids, positions, velocity, density, metadata, counts)
        receipt.update({
            "generated_xml": ref(generated_xml, "v2 GenCase generated XML"),
            "generated_bi4": ref(generated_bi4, "v2 GenCase initial native frame"),
            "gencase_log": ref(log, "v2 GenCase log"),
            "native_metadata": metadata,
            "native_audit": audit,
            "preflight_pass": bool(audit["all_hard_gates_pass"]),
            "status": "cpu_native_preflight_pass_anchor_only" if audit["all_hard_gates_pass"] else "cpu_native_preflight_failed_hard_audit",
        })
        receipt["interpretation_boundary"] = "Fresh v2 CPU/native input closure only; no trajectory, event result, solver, qualification, or T1 credit."
    except Exception as error:
        receipt.update({
            "preflight_pass": False,
            "status": "cpu_native_preflight_failed_hard_audit",
            "error": f"{type(error).__name__}: {error}",
            "interpretation_boundary": "Failure is retained as zero-credit v2 preflight evidence; no solver, GPU, queue, or qualification action follows.",
        })
        if log.is_file():
            receipt["gencase_log"] = ref(log, "v2 GenCase log")
    receipt["input_hashes"] = {
        str(path.resolve()): sha256(path)
        for path in (definition.DEFAULT_DEFINITION, definition.DEFAULT_CONTRACT, observer.OUTPUT, admission.ROOT_RECEIPT, log)
        if path.is_file()
    }
    PREFLIGHT_RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def verify_preflight(path: Path = PREFLIGHT_RECEIPT) -> dict[str, Any]:
    value = load(Path(path))
    if value.get("schema") != SCHEMA or value.get("qualification_claim") != "none" or value.get("matrix_credit") != 0:
        raise ValueError("preflight schema/credit mismatch")
    if value.get("denominator", {}).get("preflight_credit") != 0 or value.get("denominator", {}).get("qualification_credit") != 0:
        raise ValueError("preflight credit opened")
    controls = value.get("execution_controls", {})
    for key in ("solver_invoked", "gpu_invoked"):
        if controls.get(key) is not False:
            raise ValueError(f"preflight opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "T1_denominator_mutation", "T2_denominator_mutation", "qualification_credit"):
        if controls.get(key) != 0:
            raise ValueError(f"preflight mutation opened {key}")
    if value.get("status") == "cpu_native_preflight_pass_anchor_only" and not value.get("native_audit", {}).get("all_hard_gates_pass"):
        raise ValueError("preflight claims pass without all hard gates")
    for key in ("root_review", "definition", "definition_contract", "observer_contract", "implementation", "gencase_log", "generated_xml", "generated_bi4"):
        item = value.get(key)
        if item and (sha256(Path(item["path"])) != item.get("sha256") or Path(item["path"]).stat().st_size != item.get("bytes")):
            raise ValueError(f"preflight binding changed: {key}")
    return {
        "status": "ok",
        "preflight_status": value.get("status"),
        "preflight_pass": value.get("preflight_pass"),
        "qualification_claim": value.get("qualification_claim"),
        "matrix_credit": value.get("matrix_credit"),
        "native_decode_invoked": value.get("execution_controls", {}).get("cpu_native_decode_invoked", False),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-preflight")
    p = sub.add_parser("verify-preflight")
    p.add_argument("--receipt", type=Path, default=PREFLIGHT_RECEIPT)
    args = parser.parse_args()
    result = run_preflight() if args.command == "run-preflight" else verify_preflight(args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.command == "verify-preflight" or result.get("preflight_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
