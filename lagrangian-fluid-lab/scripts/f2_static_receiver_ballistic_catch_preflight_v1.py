#!/usr/bin/env python3
"""Run the single authorized F2 CPU/native input preflight.

The ``run-preflight`` command rechecks the root-review receipt, materializes
the literal Definition once with GenCase, decodes the resulting first native
frame, and writes a hard-input receipt.  It has no solver, CUDA, queue,
ledger, registry, or qualification-matrix entry point.  ``verify-preflight``
is read-only and never calls GenCase or the native decoder.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts.core_cfd import environment, native_frame  # noqa: E402
from scripts.f2_static_receiver_ballistic_catch_definition_writer_v1 import (  # noqa: E402
    BASE, CASE_ID, DEFAULT_CONTRACT, DEFAULT_DEFINITION, inspect_definition, sha256,
)
from scripts.f2_static_receiver_ballistic_catch_root_review_v1 import (  # noqa: E402
    ROOT_RECEIPT, verify_receipt,
)


PREFLIGHT_DIR = BASE / "preflight"
GENERATED_PREFIX = PREFLIGHT_DIR / "generated" / CASE_ID
PREFLIGHT_RECEIPT = PREFLIGHT_DIR / "preflight.json"
GENCASE_BINARY = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
NATIVE_DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
SCHEMA = "core.f2.static_receiver_ballistic_catch.cpu_native_preflight.v1"
ENDPOINT_TOLERANCE_M = 1.0e-8
RECEIVER_SURFACE_TOLERANCE_M = DP_M = 0.0075
SOURCE_DENSITY_KG_M3 = 1000.0
MASS_RELATIVE_ERROR_MAX = 0.025


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


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
    expected = np.concatenate([np.arange(begin, begin + count, dtype=np.uint32) for begin, count in spans])
    if len(expected) != total or not np.array_equal(expected, np.arange(total, dtype=np.uint32)):
        raise ValueError("generated XML IDs are not contiguous")
    if boundary != sum(count for _, count in spans[:2]):
        raise ValueError("generated XML boundary count mismatch")
    fluid_begin, fluid_count = spans[2]
    return {
        "total_particles": total, "boundary_particles": boundary,
        "fluid_particles": fluid_count, "fluid_begin": fluid_begin,
        "outer_boundary_particles": spans[0][1], "receiver_boundary_particles": spans[1][1],
        "xml_ids_contiguous": True,
    }


def _receiver_surface_overlap(positions: np.ndarray) -> int:
    """Count endpoints within one dp of the receiver's closed faces."""
    pos = np.asarray(positions, dtype=float)
    low = np.array([0.35, -0.18, 0.08])
    high = low + np.array([0.50, 0.36, 0.50])
    tol = RECEIVER_SURFACE_TOLERANCE_M
    inside_xy = (
        (pos[:, 0] >= low[0] - tol) & (pos[:, 0] <= high[0] + tol) &
        (pos[:, 1] >= low[1] - tol) & (pos[:, 1] <= high[1] + tol)
    )
    bottom = inside_xy & (np.abs(pos[:, 2] - low[2]) <= tol)
    side_z = (pos[:, 2] >= low[2] - tol) & (pos[:, 2] <= high[2] + tol)
    left = side_z & (np.abs(pos[:, 0] - low[0]) <= tol) & (pos[:, 1] >= low[1] - tol) & (pos[:, 1] <= high[1] + tol)
    right = side_z & (np.abs(pos[:, 0] - high[0]) <= tol) & (pos[:, 1] >= low[1] - tol) & (pos[:, 1] <= high[1] + tol)
    front = side_z & (np.abs(pos[:, 1] - low[1]) <= tol) & (pos[:, 0] >= low[0] - tol) & (pos[:, 0] <= high[0] + tol)
    back = side_z & (np.abs(pos[:, 1] - high[1]) <= tol) & (pos[:, 0] >= low[0] - tol) & (pos[:, 0] <= high[0] + tol)
    return int(np.count_nonzero(bottom | left | right | front | back))


def _audit_native(ids: np.ndarray, positions: np.ndarray, velocity: np.ndarray,
                  density: np.ndarray, metadata: dict[str, str], counts: dict[str, Any]) -> dict[str, Any]:
    total = counts["total_particles"]
    fluid_begin = counts["fluid_begin"]
    fluid_count = counts["fluid_particles"]
    expected = np.arange(total, dtype=np.uint32)
    ids_unique = len(np.unique(ids)) == len(ids)
    ids_match = len(ids) == total and np.array_equal(ids, expected)
    fluid_ids_match = ids_match and np.array_equal(ids[fluid_begin:fluid_begin + fluid_count],
                                                    np.arange(fluid_begin, fluid_begin + fluid_count, dtype=np.uint32))
    arrays_finite = bool(all(np.isfinite(array).all() for array in (positions, velocity, density)))
    fluid_pos = positions[fluid_begin:fluid_begin + fluid_count]
    outer = np.array([0.0, -0.45, 0.0])
    outer_high = outer + np.array([1.25, 0.90, 0.80])
    tol = ENDPOINT_TOLERANCE_M
    outer_outside = (
        (fluid_pos[:, 0] < outer[0] - tol) | (fluid_pos[:, 0] > outer_high[0] + tol) |
        (fluid_pos[:, 1] < outer[1] - tol) | (fluid_pos[:, 1] > outer_high[1] + tol) |
        (fluid_pos[:, 2] < outer[2] - tol)
    )
    outer_endpoint_count = int(np.count_nonzero(outer_outside))
    receiver_overlap_count = _receiver_surface_overlap(fluid_pos)
    mass_fluid = float(metadata.get("MassFluid", "nan"))
    discrete_mass = mass_fluid * fluid_count
    continuous_mass = 0.24 * 0.18 * 0.18 * SOURCE_DENSITY_KG_M3
    mass_error = discrete_mass / continuous_mass - 1.0 if np.isfinite(mass_fluid) else float("inf")
    mass_pass = bool(np.isfinite(mass_error) and abs(mass_error) <= MASS_RELATIVE_ERROR_MAX)
    hard = {
        "ids": {"unique": bool(ids_unique), "match_generated_xml": bool(ids_match),
                "fluid_span_match": bool(fluid_ids_match),
                "pass": bool(ids_unique and ids_match and fluid_ids_match)},
        "finite": {"positions": bool(np.isfinite(positions).all()),
                   "velocity": bool(np.isfinite(velocity).all()),
                   "density": bool(np.isfinite(density).all()), "pass": arrays_finite},
        "mass": {"continuous_source_mass_kg": continuous_mass,
                 "discrete_native_mass_kg": discrete_mass, "relative_error": mass_error,
                 "max_relative_error": MASS_RELATIVE_ERROR_MAX, "pass": mass_pass},
        "outer_wall_endpoints": {"count": outer_endpoint_count,
                                  "tolerance_m": ENDPOINT_TOLERANCE_M,
                                  "pass": outer_endpoint_count == 0},
        "receiver_surface_overlap": {"count": receiver_overlap_count,
                                      "tolerance_m": RECEIVER_SURFACE_TOLERANCE_M,
                                      "pass": receiver_overlap_count == 0},
    }
    return {
        "native_particle_count": int(len(ids)), "fluid_particle_count": int(fluid_count),
        "boundary_particle_count": int(counts["boundary_particles"]),
        "ids_unique": bool(ids_unique), "ids_match_generated_xml": bool(ids_match),
        "fluid_ids_match_generated_xml": bool(fluid_ids_match), "arrays_finite": arrays_finite,
        "outer_wall_endpoint_count": outer_endpoint_count,
        "receiver_surface_overlap_count": receiver_overlap_count,
        "hard_gates": hard, "all_hard_gates_pass": bool(all(item["pass"] for item in hard.values())),
        "mass_fluid_kg_per_particle": mass_fluid,
    }


def _fresh_guard() -> None:
    if PREFLIGHT_RECEIPT.exists() or PREFLIGHT_DIR.exists() and any(PREFLIGHT_DIR.iterdir()):
        raise FileExistsError("preflight namespace is not fresh; same-input retry is forbidden")
    if GENERATED_PREFIX.exists() or GENERATED_PREFIX.with_suffix(".xml").exists() or GENERATED_PREFIX.with_suffix(".bi4").exists():
        raise FileExistsError("generated prefix already exists")


def run_preflight() -> dict[str, Any]:
    root_review = verify_receipt(ROOT_RECEIPT)
    definition = DEFAULT_DEFINITION.resolve()
    contract_path = DEFAULT_CONTRACT.resolve()
    if not definition.is_file() or not contract_path.is_file():
        raise FileNotFoundError("fresh Definition and contract must be materialized before preflight")
    contract = _json(contract_path)
    definition_audit = inspect_definition(definition)
    if contract.get("definition_sha256") != definition_audit["sha256"]:
        raise ValueError("contract does not bind the exact fresh Definition")
    if contract.get("writer_sha256") != sha256(Path(__file__).with_name("f2_static_receiver_ballistic_catch_definition_writer_v1.py")):
        raise ValueError("contract writer hash mismatch")
    _fresh_guard()
    PREFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
    generated_dir = GENERATED_PREFIX.parent
    generated_dir.mkdir(parents=True, exist_ok=True)
    gencase_log = PREFLIGHT_DIR / "gencase.stdout.log"
    command = [str(GENCASE_BINARY), str(definition.with_suffix("")), str(GENERATED_PREFIX), "-save:all"]
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.run(command, cwd=PREFLIGHT_DIR, env=environment(LAB_ROOT),
                              stdout=gencase_log.open("w"), stderr=subprocess.STDOUT)
    controls = {"gencase_invoked": True, "native_decode_invoked": False,
                "solver_launch": False, "gpu_launch": False, "queue_mutation": 0,
                "ledger_mutation": 0, "registry_mutation": 0, "matrix_submission": 0}
    base = {
        "schema": SCHEMA, "created_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "cpu_native_preflight_failed_gencase", "qualified": False, "qualification_claim": "none",
        "matrix_credit": 0, "root_review": root_review, "root_review_path": str(ROOT_RECEIPT),
        "root_review_sha256": sha256(ROOT_RECEIPT), "definition": _ref(definition, "fresh literal Definition"),
        "contract": _ref(contract_path, "fresh Definition contract"), "gencase_command": command,
        "gencase_returncode": int(process.returncode), "execution_controls": controls,
        "denominator": {"parent_scope_rows": 15, "preflight_credit": 0, "same_input_retry": False},
    }
    if process.returncode != 0:
        base["gencase_log"] = _ref(gencase_log, "GenCase log")
        PREFLIGHT_RECEIPT.write_text(json.dumps(base, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        return base
    generated_xml = GENERATED_PREFIX.with_suffix(".xml")
    generated_bi4 = GENERATED_PREFIX.with_suffix(".bi4")
    counts = _generated_counts(generated_xml)
    controls["native_decode_invoked"] = True
    with tempfile.TemporaryDirectory(prefix="f2-static-receiver-native-") as folder:
        ids, pos, vel, rho, metadata, info, arrays = native_frame(generated_bi4, Path(folder) / "native", NATIVE_DECODER)
        audit = _audit_native(ids, pos, vel, rho, metadata, counts)
    base.update({
        "status": "cpu_native_preflight_pass" if audit["all_hard_gates_pass"] else "cpu_native_preflight_failed_hard_audit",
        "generated_xml": _ref(generated_xml, "GenCase generated XML"),
        "generated_bi4": _ref(generated_bi4, "GenCase initial native frame"),
        "gencase_log": _ref(gencase_log, "GenCase log"),
        "generated_counts": counts, "native_metadata": metadata,
        "native_audit": audit, "execution_controls": controls,
    })
    base["execution_controls"] = controls
    PREFLIGHT_RECEIPT.write_text(json.dumps(base, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return base


def verify_preflight(path: Path = PREFLIGHT_RECEIPT) -> dict[str, Any]:
    value = _json(path)
    if value.get("schema") != SCHEMA or value.get("qualification_claim") != "none" or value.get("matrix_credit") != 0:
        raise ValueError("preflight schema/credit mismatch")
    if value.get("denominator", {}).get("preflight_credit") != 0:
        raise ValueError("preflight credit opened")
    controls = value.get("execution_controls", {})
    for key in ("solver_launch", "gpu_launch"):
        if controls.get(key) is not False:
            raise ValueError(f"preflight opened {key}")
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "matrix_submission"):
        if controls.get(key) != 0:
            raise ValueError(f"preflight opened {key}")
    if value.get("status") == "cpu_native_preflight_pass" and not value.get("native_audit", {}).get("all_hard_gates_pass"):
        raise ValueError("preflight status claims pass without hard gates")
    for key in ("definition", "contract", "gencase_log"):
        item = value.get(key)
        if item and sha256(Path(item["path"])) != item.get("sha256"):
            raise ValueError(f"preflight binding changed: {key}")
    for key in ("generated_xml", "generated_bi4"):
        item = value.get(key)
        if item and sha256(Path(item["path"])) != item.get("sha256"):
            raise ValueError(f"preflight product binding changed: {key}")
    return {"status": "ok", "preflight_status": value.get("status"),
            "qualification_claim": value.get("qualification_claim"),
            "matrix_credit": value.get("matrix_credit"),
            "native_decode_invoked": value.get("execution_controls", {}).get("native_decode_invoked", False)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-preflight")
    p = sub.add_parser("verify-preflight"); p.add_argument("--receipt", type=Path, default=PREFLIGHT_RECEIPT)
    args = parser.parse_args()
    result = run_preflight() if args.command == "run-preflight" else verify_preflight(args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.command == "verify-preflight" or result.get("status") == "cpu_native_preflight_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
