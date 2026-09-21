#!/usr/bin/env python3
"""Finalize the bounded F6 native-decode amendment without another binary call.

The v2 amendment already invoked ``bi4_dump`` and wrote decoded arrays, but
its JSON serializer failed on a NumPy scalar.  This script only reads those
decoded files and writes the immutable final receipt; it never calls GenCase
or the native decoder.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f6_physical_anchor_root_review as physical
from scripts.f6_physical_anchor_cpu_native_decode_amendment_v1 import groups, ref, select


LAB = Path(__file__).resolve().parents[1]
ORIGINAL_DIR = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-preflight-v1-20260921"
AMENDMENT_V1 = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-decode-amendment-v1-20260921/amendment.json"
AMENDMENT_V2_DIR = LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-decode-amendment-v2-20260921"
GENERATED_XML = ORIGINAL_DIR / "generated/F6_physical_anchor_cpu_native_preflight_20260921.xml"
GENERATED_BI4 = ORIGINAL_DIR / "generated/F6_physical_anchor_cpu_native_preflight_20260921.bi4"
DECODED_XML = AMENDMENT_V2_DIR / "decoded/native.xml"
DECODED_PART = AMENDMENT_V2_DIR / "decoded/native/PART_0000"
OUTPUT = AMENDMENT_V2_DIR / "amendment-final.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def load_native() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, str], dict[str, str]]:
    root = ET.parse(DECODED_XML).getroot()
    parent = root.find("item")
    if parent is None:
        raise ValueError("decoded XML has no root data item")
    metadata = {node.get("name"): node.get("v") for node in parent if node.tag != "item"}
    item = parent.find("item")
    if item is None:
        raise ValueError("decoded XML has no frame item")
    info = {node.get("name"): node.get("v") for node in item if node.tag != "item"}
    ids = np.fromfile(DECODED_PART / "Idp.bin", np.uint32)
    positions = np.fromfile(DECODED_PART / "Posd.bin", np.float64).reshape(-1, 3)
    velocities = np.fromfile(DECODED_PART / "Vel.bin", np.float32).reshape(-1, 3)
    density = np.fromfile(DECODED_PART / "Rhop.bin", np.float32)
    order = np.argsort(ids)
    return ids[order], positions[order], velocities[order], density[order], metadata, info


def main() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"final receipt already exists: {OUTPUT}")
    for path in (AMENDMENT_V1, GENERATED_XML, GENERATED_BI4, DECODED_XML, DECODED_PART / "Idp.bin", DECODED_PART / "Posd.bin", DECODED_PART / "Vel.bin", DECODED_PART / "Rhop.bin"):
        if not path.is_file():
            raise FileNotFoundError(path)
    definition_contract = json.loads((LAB / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-root-review-v1-20260921/definition-contract.json").read_text(encoding="utf-8"))
    fixed, fluids = groups(GENERATED_XML)
    floating = [item for item in fixed if int(item.get("mkbound", -1)) == physical.MKBOUND]
    fluid = [item for item in fluids if int(item.get("mkfluid", -1)) == 0]
    ids, positions, velocities, density, metadata, info = load_native()
    body_mask = np.zeros(len(ids), dtype=bool)
    fluid_mask = np.zeros(len(ids), dtype=bool)
    for item in floating:
        body_mask |= select(ids, item)
    for item in fluid:
        fluid_mask |= select(ids, item)
    body = definition_contract["body"]
    expected_mass = float(body["mass_kg"])
    generated_mass = float(floating[0].get("massbody_kg", float("nan"))) if floating else float("nan")
    mass_error = generated_mass / expected_mass - 1.0 if expected_mass else float("inf")
    generated_center = floating[0].get("center_m", []) if floating else []
    center_error = max((abs(a - b) for a, b in zip(generated_center, body["com_m"])), default=float("inf"))
    expected_inertia = np.asarray(body["inertia_about_com_kg_m2"], dtype=float)
    generated_inertia = np.asarray(floating[0].get("inertia_matrix_kg_m2", [[float("nan")]*3]*3), dtype=float) if floating else np.full((3, 3), float("nan"))
    inertia_error = float(np.max(np.abs(generated_inertia - expected_inertia) / np.maximum(np.abs(expected_inertia), 1.0e-12)))
    checks = {
        "one_floating_body_group": bool(len(floating) == 1),
        "one_fluid_group": bool(len(fluid) == 1),
        "native_ids_unique": bool(len(np.unique(ids)) == len(ids)),
        "native_arrays_finite": bool(np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all()),
        "body_particles_present": bool(body_mask.any()),
        "fluid_particles_present": bool(fluid_mask.any()),
        "generated_body_mass_matches_contract": bool(math.isfinite(mass_error) and abs(mass_error) <= 0.01),
        "generated_body_center_matches_contract": bool(math.isfinite(center_error) and center_error <= 0.5 * physical.DP_M),
        "generated_body_inertia_matches_contract": bool(math.isfinite(inertia_error) and inertia_error <= 0.01),
    }
    receipt = {
        "schema": "core.f6.physical_anchor.cpu_native_decode_amendment.v1",
        "receipt_id": "F6_physical_anchor_cpu_native_decode_amendment_final_receipt_20260921",
        "created_at_utc": stamp(),
        "status": "cpu_native_decode_completed_hard_failure",
        "reason": "bounded_infrastructure_repair_finalization",
        "original_receipt": ref(ORIGINAL_DIR / "preflight.json", "immutable GenCase one-shot receipt"),
        "first_amendment_failure": ref(AMENDMENT_V1, "native decode attempt failed before output-parent creation"),
        "second_amendment_failure": {"status": "receipt_serialization_failed_after_native_decode", "output_dir": str(AMENDMENT_V2_DIR.relative_to(LAB)), "detail": "NumPy scalar was not converted before JSON serialization; decoded files are retained and finalized here without another decoder call."},
        "generated_xml": ref(GENERATED_XML, "already generated GenCase XML; never regenerated"),
        "generated_bi4": ref(GENERATED_BI4, "already generated GenCase BI4; never regenerated"),
        "decoded_xml": ref(DECODED_XML, "decoded XML from exactly one repaired native invocation"),
        "native_decode_binary": ref(LAB / "campaigns/l1-resume/artifacts/bi4_dump", "pinned native decoder"),
        "native_decode_invocation_count": 2,
        "native_decode_retry_policy": "one bounded infrastructure retry after first decoder output-parent failure",
        "gencase_invocation_count": 1,
        "same_input_gencase_retry": False,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_submission": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "generated_groups": {"fixed": fixed, "fluid": fluids},
        "generated_body": {"massbody_kg": generated_mass, "massbody_relative_error": mass_error, "center_m": generated_center, "center_max_abs_error_m": center_error, "inertia_matrix_kg_m2": generated_inertia.tolist(), "inertia_max_relative_error": inertia_error},
        "native": {"total_particles": int(len(ids)), "body_particles": int(body_mask.sum()), "fluid_particles": int(fluid_mask.sum()), "metadata": {str(k): str(v) for k, v in metadata.items()}, "info": {str(k): str(v) for k, v in info.items()}},
        "checks": checks,
        "preflight_pass": bool(all(checks.values())),
        "failure": "Generated floating metadata disagrees with the declared continuous body mass/COM/inertia contract; no solver canary is admissible.",
        "execution_controls": {"gencase_invoked": True, "native_decode_invoked": True, "solver_invoked": False, "gpu_invoked": False, "job_created": False, "queue_mutation": 0, "registry_mutation": 0, "ledger_mutation": 0, "matrix_submission": False, "qualification_credit": 0},
        "finished_at_utc": stamp(),
    }
    write_json(OUTPUT, receipt)
    print(json.dumps({"status": receipt["status"], "preflight_pass": receipt["preflight_pass"], "output": str(OUTPUT)}, ensure_ascii=False))
    return 0 if receipt["preflight_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
