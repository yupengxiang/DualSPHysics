#!/usr/bin/env python3
"""Complete the unused native-decode leg of the F6 one-shot preflight.

The original one-shot GenCase receipt stopped before decoding because its
verifier recognised ``fixed/moving/fluid`` but omitted the valid GenCase
``floating`` particle group.  This amendment keeps that receipt immutable,
does not invoke GenCase again, and performs exactly one native BI4 decode of
the already generated artifact.  It is an infrastructure repair diagnostic,
not a solver canary or a qualification run.
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

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import core_cfd  # noqa: E402
from scripts import f6_physical_anchor_root_review as physical  # noqa: E402


SCHEMA = "core.f6.physical_anchor.cpu_native_decode_amendment.v1"
SOURCE_DIR = LAB_ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-root-review-v1-20260921"
ORIGINAL_DIR = LAB_ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-preflight-v1-20260921"
OUTPUT_DIR = LAB_ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-decode-amendment-v1-20260921"
ORIGINAL_RECEIPT = ORIGINAL_DIR / "preflight.json"
GENERATED_XML = ORIGINAL_DIR / "generated/F6_physical_anchor_cpu_native_preflight_20260921.xml"
GENERATED_BI4 = ORIGINAL_DIR / "generated/F6_physical_anchor_cpu_native_preflight_20260921.bi4"
DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
MASS_TOLERANCE_RELATIVE = 0.01
CENTER_TOLERANCE_M = 0.5 * physical.DP_M
INERTIA_TOLERANCE_RELATIVE = 0.01


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    partial.replace(path)


def ref(path: Path, role: str) -> dict[str, Any]:
    path = path.resolve()
    return {"path": str(path.relative_to(LAB_ROOT)).replace("\\", "/"), "sha256": sha256(path), "bytes": path.stat().st_size, "role": role}


def _number(raw: str | None) -> float:
    if raw is None:
        raise ValueError("missing numeric attribute")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("non-finite numeric attribute")
    return value


def _group(node: ET.Element) -> dict[str, Any]:
    value: dict[str, Any] = {"kind": node.tag}
    for key, raw in node.attrib.items():
        try:
            value[key] = int(raw) if key in {"begin", "count", "mk", "mkbound", "mkfluid"} else raw
        except (TypeError, ValueError):
            value[key] = raw
    for child in node:
        if child.tag == "massbody":
            value["massbody_kg"] = _number(child.get("value"))
        elif child.tag == "masspart":
            value["masspart_kg"] = _number(child.get("value"))
        elif child.tag == "center":
            value["center_m"] = [_number(child.get(axis)) for axis in "xyz"]
        elif child.tag == "inertia":
            if all(child.get(axis) is not None for axis in "xyz"):
                value["inertia_diag_kg_m2"] = [_number(child.get(axis)) for axis in "xyz"]
            else:
                rows = child.findall("values")
                value["inertia_matrix_kg_m2"] = [[_number(row.get(f"v{i}{j}")) for j in (1, 2, 3)] for i, row in enumerate(rows, 1)]
    return value


def groups(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = ET.parse(path).getroot()
    fixed: list[dict[str, Any]] = []
    fluids: list[dict[str, Any]] = []
    for node in root.findall(".//particles/*"):
        if node.tag not in {"fixed", "moving", "floating", "fluid"}:
            continue
        item = _group(node)
        (fluids if node.tag == "fluid" else fixed).append(item)
    return fixed, fluids


def select(ids: np.ndarray, item: dict[str, Any]) -> np.ndarray:
    begin = int(item["begin"])
    count = int(item["count"])
    return (ids >= begin) & (ids < begin + count)


def compare_relative(actual: float, expected: float) -> tuple[bool, float]:
    error = actual / expected - 1.0 if expected else float("inf")
    return math.isfinite(error) and abs(error) <= MASS_TOLERANCE_RELATIVE, error


def run(output: Path = OUTPUT_DIR) -> dict[str, Any]:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"amendment output is not fresh: {output}")
    original = json.loads(ORIGINAL_RECEIPT.read_text(encoding="utf-8"))
    if original.get("status") != "cpu_native_preflight_failed_hard":
        raise ValueError("original one-shot receipt is not the retained hard-failure receipt")
    # The original verifier set its bookkeeping flag before entering the
    # decoder helper.  Its receipt has no decoded XML and the helper returned
    # at the generated-group gate, so the native binary was not actually
    # called.  Treat that flag as a recorded *attempt*, not a consumed decode.
    decoded_xml = original.get("decoded_xml")
    if decoded_xml is not None or original.get("native", {}).get("native_decoder_invoked") is True:
        raise ValueError("the original receipt already contains a completed native decode")
    if original.get("execution_controls", {}).get("solver_invoked") is not False:
        raise ValueError("original receipt has solver execution")
    for path in (GENERATED_XML, GENERATED_BI4, DECODER, SOURCE_DIR / "definition-contract.json"):
        if not path.is_file():
            raise FileNotFoundError(path)

    output.mkdir(parents=True, exist_ok=True)
    decoded_root = output / "decoded" / "native"
    # bi4_dump writes ``native.xml`` beside the temporary directory.  Keep the
    # parent explicit; the first amendment attempt is retained as an
    # infrastructure-failure receipt when this directory is absent.
    decoded_root.parent.mkdir(parents=True, exist_ok=True)
    fixed, fluids = groups(GENERATED_XML)
    floating = [item for item in fixed if int(item.get("mkbound", -1)) == physical.MKBOUND]
    fluid = [item for item in fluids if int(item.get("mkfluid", -1)) == 0]
    definition_contract = json.loads((SOURCE_DIR / "definition-contract.json").read_text(encoding="utf-8"))
    body = definition_contract["body"]
    native: dict[str, Any]
    try:
        ids, positions, velocities, density, metadata, info, arrays = core_cfd.native_frame(GENERATED_BI4, decoded_root, DECODER)
        ids, positions, velocities, density = map(np.asarray, (ids, positions, velocities, density))
        body_mask = np.zeros(len(ids), dtype=bool)
        fluid_mask = np.zeros(len(ids), dtype=bool)
        for item in floating:
            body_mask |= select(ids, item)
        for item in fluid:
            fluid_mask |= select(ids, item)
        body_position = positions[body_mask]
        body_velocity = velocities[body_mask]
        fluid_velocity = velocities[fluid_mask]
        expected_mass = float(body["mass_kg"])
        generated_mass = float(floating[0].get("massbody_kg", float("nan"))) if floating else float("nan")
        mass_pass, mass_error = compare_relative(generated_mass, expected_mass)
        generated_center = floating[0].get("center_m", []) if floating else []
        center_error = max((abs(a - b) for a, b in zip(generated_center, body["com_m"])), default=float("inf"))
        inertia_expected = np.asarray(body["inertia_about_com_kg_m2"], dtype=float)
        if floating and "inertia_matrix_kg_m2" in floating[0]:
            generated_inertia = np.asarray(floating[0]["inertia_matrix_kg_m2"], dtype=float)
        elif floating and "inertia_diag_kg_m2" in floating[0]:
            generated_inertia = np.diag(np.asarray(floating[0]["inertia_diag_kg_m2"], dtype=float))
        else:
            generated_inertia = np.full((3, 3), float("nan"))
        inertia_rel = np.max(np.abs(generated_inertia - inertia_expected) / np.maximum(np.abs(inertia_expected), 1.0e-12))
        native = {
            "native_decode_invoked": True,
            "native": {
                "total_particles": int(len(ids)),
                "fluid_particles": int(fluid_mask.sum()),
                "body_particles": int(body_mask.sum()),
                "metadata": {str(k): str(v) for k, v in metadata.items()},
                "info": {str(k): str(v) for k, v in info.items()},
                "max_body_initial_speed_m_s": float(np.max(np.linalg.norm(body_velocity, axis=1))) if len(body_velocity) else None,
                "max_fluid_initial_speed_m_s": float(np.max(np.linalg.norm(fluid_velocity, axis=1))) if len(fluid_velocity) else None,
            },
            "checks": {
                "one_floating_body_group": len(floating) == 1,
                "one_fluid_group": len(fluid) == 1,
                "native_ids_unique": len(np.unique(ids)) == len(ids),
                "native_arrays_finite": bool(np.isfinite(positions).all() and np.isfinite(velocities).all() and np.isfinite(density).all()),
                "generated_body_mass_matches_contract": mass_pass,
                "generated_body_center_matches_contract": math.isfinite(center_error) and center_error <= CENTER_TOLERANCE_M,
                "generated_body_inertia_matches_contract": math.isfinite(float(inertia_rel)) and inertia_rel <= INERTIA_TOLERANCE_RELATIVE,
                "body_particles_present": bool(body_mask.any()),
                "fluid_particles_present": bool(fluid_mask.any()),
            },
            "generated_groups": {"fixed": fixed, "fluid": fluids},
            "generated_body": {
                "massbody_kg": generated_mass,
                "massbody_relative_error": mass_error,
                "center_m": generated_center,
                "center_max_abs_error_m": center_error,
                "inertia_matrix_kg_m2": generated_inertia.tolist(),
                "inertia_max_relative_error": float(inertia_rel),
            },
            "decoded_xml": ref(Path(str(decoded_root) + ".xml"), "native decoder XML"),
        }
    except Exception as error:
        native = {"native_decode_invoked": True, "checks": {}, "failure": repr(error)}

    checks = native.get("checks", {})
    preflight_pass = bool(checks) and all(checks.values())
    receipt = {
        "schema": SCHEMA,
        "receipt_id": "F6_physical_anchor_cpu_native_decode_amendment_receipt_20260921",
        "created_at_utc": stamp(),
        "status": "cpu_native_decode_amendment_hard_failure" if not preflight_pass else "cpu_native_decode_amendment_pass",
        "reason": "verifier_repair_of_original_receipt_only",
        "original_receipt": ref(ORIGINAL_RECEIPT, "immutable original one-shot receipt"),
        "generated_xml": ref(GENERATED_XML, "already generated GenCase XML; not regenerated"),
        "generated_bi4": ref(GENERATED_BI4, "already generated GenCase BI4; not regenerated"),
        "native_decoder": ref(DECODER, "single native decoder invocation"),
        "same_input_gencase_retry": False,
        "gencase_invoked_in_amendment": False,
        "native_decode_invoked_in_amendment": True,
        "solver_invoked": False,
        "gpu_invoked": False,
        "queue_mutation": 0,
        "registry_mutation": 0,
        "ledger_mutation": 0,
        "matrix_submission": False,
        "qualification_claim": "none",
        "qualification_credit": 0,
        "T1": False,
        "preflight_pass": preflight_pass,
        "gencase_logical_observation": "GenCase code=0 produced a floating group; original verifier omitted the floating tag and stopped before native decode",
        "failure_policy": "retain original receipt and this amendment; no same-input GenCase retry or solver canary is authorized",
        **native,
        "finished_at_utc": stamp(),
    }
    write_json(output / "amendment.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    receipt = run(args.output)
    print(json.dumps({"status": receipt["status"], "preflight_pass": receipt["preflight_pass"], "output": str(Path(args.output).resolve() / "amendment.json")}, ensure_ascii=False))
    return 0 if receipt["preflight_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
