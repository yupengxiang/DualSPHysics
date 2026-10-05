#!/usr/bin/env python3
"""Pure metadata preflight for the actual converter legacy scope.

The direct converter is loaded under a private sys.modules name and only
_physical_condition_scope(owner) and canonical_hash are called. No BI4, H5,
CSV, VTK, decoder, output tree, or scientific array is opened. Fresh100 owners
intentionally omit physical_binding, so the result is prospective
legacy-owner-scope.v0 and never a canonical approval.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

SCIENCE_SUFFIXES = {".bi4", ".h5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return value


def import_converter(path: Path) -> Any:
    name = "ds02_f2_fresh100_direct_converter_scope_preflight"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def motion_contract(definition: Path, motion: Path) -> dict[str, Any]:
    root = ET.parse(definition).getroot()
    node = root.find(".//casedef/motion/objreal/mvrotfile/file")
    errors: list[str] = []
    if node is None or node.get("name") != motion.name:
        errors.append("XML mvrotfile name does not match source asset basename")
    times: list[float] = []
    angles: list[float] = []
    for raw in motion.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            time_s, angle_s = raw.split(";", 1)
            times.append(float(time_s))
            angles.append(float(angle_s))
        except ValueError:
            errors.append("motion row is not #Time;Degrees")
    if not times or times[0] != 0.0 or abs(times[-1] - 4.0) > 1e-12:
        errors.append("motion does not span 0..4 seconds")
    if any(not (a < b) for a, b in zip(times, times[1:])):
        errors.append("motion times are not strictly increasing")
    if any(not (value == value and abs(value) < float("inf")) for value in times + angles):
        errors.append("motion has a nonfinite value")
    if angles and abs(angles[-1] + 105.0) > 1e-12:
        errors.append("motion final angle is not -105 degrees")
    return {"status": "pass" if not errors else "fail", "errors": errors,
            "definition": str(definition), "definition_sha256": sha256(definition),
            "motion": {"path": str(motion), "sha256": sha256(motion), "rows": len(times),
                       "time_start_s": times[0] if times else None,
                       "time_end_s": times[-1] if times else None,
                       "final_angle_deg": angles[-1] if angles else None}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--converter", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = load(Path(args.manifest).resolve())
    converter_path = Path(args.converter).resolve()
    converter = import_converter(converter_path)
    rows = []
    errors: list[str] = []
    for case in manifest.get("cases", []):
        cid = str(case["case_id"])
        definition = Path(case["definition"]["path"]).resolve()
        motion = Path(case["motion"]["path"]).resolve()
        metadata = Path(case["metadata"]["path"]).resolve()
        binding = load(Path(case["binding"]["path"]).resolve())
        owner = load(Path(case["owner"]["path"]).resolve())
        meta = load(metadata)
        case_errors: list[str] = []
        if Path(binding["definition"]).resolve() != definition:
            case_errors.append("binding definition path mismatch")
        if binding.get("definition_sha256") != sha256(definition):
            case_errors.append("binding definition digest mismatch")
        if binding.get("canonical_physical_binding_sha256") is not None:
            case_errors.append("binding canonical scope was prefilled")
        if owner.get("canonical_physical_binding_sha256") is not None:
            case_errors.append("owner canonical scope was prefilled")
        if owner.get("source_plan_physical_condition_sha256") != meta.get("source_plan_physical_condition_sha256"):
            case_errors.append("source plan hash mismatch")
        if owner.get("actual_converter_physical_condition_sha256") is not None:
            case_errors.append("actual converter scope was prefilled")
        if "physical_binding" in owner:
            case_errors.append("owner physical_binding is premature")
        for raw in (owner.get("source", {}).get("definition", {}).get("path", ""),
                    owner.get("source", {}).get("motion", {}).get("path", ""),
                    owner.get("source", {}).get("metadata", {}).get("path", "")):
            if Path(str(raw)).suffix.lower() in SCIENCE_SUFFIXES:
                case_errors.append("owner points at a scientific artifact")
        scope = converter._physical_condition_scope(owner)
        scope_hash = converter.canonical_hash(scope)
        if scope.get("schema") != "legacy-owner-scope.v0":
            case_errors.append("converter scope is not legacy-owner-scope.v0")
        if scope.get("semantic_binding_status") != "legacy_incomplete; no cross-resolution physical claim":
            case_errors.append("converter legacy status changed")
        motion_result = motion_contract(definition, motion)
        if motion_result["status"] != "pass":
            case_errors.extend(motion_result["errors"])
        rows.append({
            "case_id": cid,
            "status": "pass" if not case_errors else "fail",
            "source_motion_contract": motion_result,
            "converter_module": str(converter_path),
            "converter_scope_callable": "ds_data02_direct_convert._physical_condition_scope(owner)",
            "producer_scope_schema": scope.get("schema"),
            "semantic_binding_status": scope.get("semantic_binding_status"),
            "prospective_legacy_scope_sha256": scope_hash,
            "actual_converter_physical_condition_sha256": None,
            "source_plan_physical_condition_sha256": owner.get("source_plan_physical_condition_sha256"),
            "canonical_physical_binding_sha256": None,
            "canonical_grant": False,
            "scientific_inputs_opened": [],
            "errors": case_errors,
        })
        errors.extend(f"{cid}: {error}" for error in case_errors)
    result = {
        "schema": "ds02.f2.stage1.fresh100.metadata-only-preflight.v1",
        "status": "pass" if len(rows) == 16 and not errors else "fail",
        "source_only": True, "converter_import_mode": "safe private sys.modules import",
        "scientific_inputs_opened": [], "actual_conversion_executed": False,
        "source_plan_scope_is_separate_from_converter_scope": True,
        "canonical_scope_granted": False, "cases": rows, "errors": errors,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
