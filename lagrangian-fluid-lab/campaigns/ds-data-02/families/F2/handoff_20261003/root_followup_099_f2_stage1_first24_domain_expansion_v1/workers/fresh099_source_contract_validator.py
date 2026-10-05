#!/usr/bin/env python3
"""Validate fresh099 source/request closure without opening science data.

This validator reads only XML, JSON, motion text and request metadata. It
refuses any future science artifact as an input and never invokes a worker,
decoder, GenCase, PartVTK, solver or converter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
MANIFEST_DEFAULT = HERE / "F2_STAGE1_FIRST24_DOMAIN_EXPANSION_MANIFEST.json"
EXPECTED_X = {0.46, 0.48, 0.52, 0.54, 0.57, 0.59, 0.62, 0.64}
FIRST8_X = {0.45, 0.47, 0.50, 0.55, 0.60, 0.63, 0.65}
EXPECTED_DURATIONS = {0.65, 1.2}
SCIENCE_SUFFIXES = {".bi4", ".h5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
FORBIDDEN_OPTIONS = ("mdbc", "noslip", "-mdbc", "-noslip")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_hash_closure(request: dict, errors: list[str], path: Path) -> None:
    inputs = request.get("input_files")
    hashes = request.get("input_sha256")
    if not isinstance(inputs, list) or not isinstance(hashes, dict):
        fail(errors, f"{path.name}: input digest closure missing")
        return
    for value in inputs:
        p = Path(value)
        if p.suffix.lower() in SCIENCE_SUFFIXES:
            fail(errors, f"{path.name}: science artifact in source input_files: {p}")
        if not p.is_file():
            fail(errors, f"{path.name}: missing input file: {p}")
            continue
        key = str(p.resolve())
        if hashes.get(key) != sha(p):
            fail(errors, f"{path.name}: input hash mismatch: {p}")


def validate_request(path: Path, case: dict, errors: list[str]) -> None:
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(errors, f"{path.name}: invalid JSON: {exc}")
        return
    if request.get("case_id") != case["case_id"] or request.get("physical_case_id") != case["physical_case_id"]:
        fail(errors, f"{path.name}: identity mismatch")
    for key in ("disabled", "source_only", "execution_allowed", "launch_allowed", "launch"):
        expected = True if key in {"disabled", "source_only"} else False
        if request.get(key) is not expected:
            fail(errors, f"{path.name}: {key} must be {expected}")
    if request.get("launch_owner") != "root":
        fail(errors, f"{path.name}: launch_owner is not root")
    if request.get("production_claim") != "none" or request.get("qualification_claim") != "none":
        fail(errors, f"{path.name}: approval claim was prefilled")
    if request.get("physical_condition_sha256") != case["physical_condition_sha256"]:
        fail(errors, f"{path.name}: source condition hash mismatch")
    if request.get("canonical_physical_binding_sha256") is not None:
        fail(errors, f"{path.name}: canonical actual scope was fabricated")
    if any(option in " ".join(map(str, request.get("command", []))).lower() for option in FORBIDDEN_OPTIONS):
        fail(errors, f"{path.name}: unsupported solver option appears")
    for value in request.get("future_input_sha256", {}).values():
        if value is not None:
            fail(errors, f"{path.name}: future input hash was prefilled")
    for key, value in request.get("future_outputs", {}).items():
        if key.endswith("sha256") and value is not None:
            fail(errors, f"{path.name}: future output hash was prefilled")
    validate_hash_closure(request, errors, path)
    command = request.get("command", [])
    kind = path.name.rsplit("-", 1)[-1].replace(".json", "")
    if kind == "native" and request.get("kind") != "qualification":
        fail(errors, f"{path.name}: native request kind is not qualification")
    if kind in {"gencase", "initial-qa", "typed"} and request.get("kind") != "cpu":
        fail(errors, f"{path.name}: CPU request kind mismatch")
    if kind == "native":
        if request.get("expected_output", {}).get("frame_count") != 401:
            fail(errors, f"{path.name}: native frame contract is not 401")
        if request.get("expected_output", {}).get("solver_dimension") != 3:
            fail(errors, f"{path.name}: native dimension is not 3")
        if request.get("gencase_receipt_sha256") is not None or request.get("initial_qa_report_sha256") is not None:
            fail(errors, f"{path.name}: native upstream hashes were prefilled")
        if command[-2:] != ["-tmax:4.0", "-tout:0.01"]:
            fail(errors, f"{path.name}: native recipe drift")
    if kind == "typed":
        if request.get("expected_native_frames") != 401 or request.get("expected_dimension") != 3:
            fail(errors, f"{path.name}: typed native contract drift")
        if request.get("expected_particles") is not None:
            fail(errors, f"{path.name}: typed expected particle count was fabricated")
        if request.get("native_receipt_sha256") is not None or request.get("gencase_receipt_sha256") is not None or request.get("initial_qa_report_sha256") is not None:
            fail(errors, f"{path.name}: typed upstream hash was prefilled")
        if request.get("decoder_sha256") != "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e":
            fail(errors, f"{path.name}: approved decoder digest drift")
    if not command:
        fail(errors, f"{path.name}: empty command")


def validate_case(case: dict) -> dict:
    errors: list[str] = []
    cid = case.get("case_id", "")
    definition = Path(case["definition"]["path"])
    motion = Path(case["motion"]["path"])
    metadata = Path(case["metadata"]["path"])
    if not all(p.is_file() for p in (definition, motion, metadata)):
        return {"case_id": cid, "status": "fail", "errors": ["source file missing"], "arrays_opened": False}
    try:
        root = ET.parse(definition).getroot()
        meta = json.loads(metadata.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"case_id": cid, "status": "fail", "errors": [f"source parse: {exc}"], "arrays_opened": False}
    geometry = root.find(".//geometry/definition")
    if geometry is None or geometry.attrib.get("dp") != "0.01":
        fail(errors, "dp is not .01")
    params = {node.attrib.get("key"): node.attrib.get("value") for node in root.findall(".//execution/parameters/parameter")}
    if params.get("TimeMax") != "4" or params.get("TimeOut") != "0.01":
        fail(errors, f"time recipe drift: {params.get('TimeMax')}/{params.get('TimeOut')}")
    if root.find(".//execution/parameters/simulationdomain") is None:
        fail(errors, "simulation domain missing")
    receiver = [node for node in root.findall(".//geometry/commands/mainlist/drawbox/point") if node.attrib.get("y") == "-0.16" and node.attrib.get("z") == "0"]
    if len(receiver) != 1:
        fail(errors, "receiver point is not unique")
    x = round(float(case["receiver_x_m"]), 2)
    if x not in EXPECTED_X or x in FIRST8_X or round(float(receiver[0].attrib.get("x", "nan")), 2) != x:
        fail(errors, f"receiver x is outside fresh099 set: {x}")
    duration = float(case["rotation_duration_s"])
    if duration not in EXPECTED_DURATIONS:
        fail(errors, f"unsupported rotation duration: {duration}")
    if meta.get("actual_counts") is not None or meta.get("actual_mass_kg") is not None:
        fail(errors, "actual count/mass prefilled")
    if any(value is not None for value in meta.get("future_receipt_hashes", {}).values()):
        fail(errors, "future receipt hash prefilled")
    if meta.get("geometry", {}).get("dimension") != 3 or meta.get("geometry", {}).get("data2d") is not False:
        fail(errors, "source is not explicit 3-D")
    if meta.get("geometry", {}).get("dp_m") != 0.01 or meta.get("parameter_values", {}).get("fill_ratio") != 0.8:
        fail(errors, "source geometry recipe drift")
    if meta.get("parameter_values", {}).get("mouth_geometry") != "open_rim" or meta.get("parameter_values", {}).get("receiver_y_m") != 0.14:
        fail(errors, "reviewed open-rim offset controls drift")
    if meta.get("physical_condition_sha256") != case.get("physical_condition_sha256"):
        fail(errors, "metadata condition hash mismatch")
    if case.get("definition", {}).get("sha256") != sha(definition) or case.get("motion", {}).get("sha256") != sha(motion) or case.get("metadata", {}).get("sha256") != sha(metadata):
        fail(errors, "manifest source digest mismatch")
    motion_rows = {}
    for line in motion.read_text(encoding="utf-8").splitlines()[1:]:
        if line.strip():
            time_s, angle_s = line.split(";", 1)
            motion_rows[float(time_s)] = float(angle_s)
    stop = 0.5 + duration
    if motion_rows.get(0.0) != 0.0 or motion_rows.get(stop) != -105.0 or motion_rows.get(4.0) != -105.0:
        fail(errors, "motion does not match declared hold/ramp/stop contract")
    for request_path in case.get("requests", {}).values():
        validate_request(Path(request_path), case, errors)
    return {"case_id": cid, "status": "pass" if not errors else "fail", "errors": errors,
            "definition_sha256": sha(definition), "motion_sha256": sha(motion), "metadata_sha256": sha(metadata), "arrays_opened": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(MANIFEST_DEFAULT))
    parser.add_argument("--output")
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    cases = manifest.get("cases", [])
    reports = [validate_case(case) for case in cases]
    errors: list[str] = []
    if len(cases) != 16:
        errors.append(f"manifest has {len(cases)} cases, expected 16")
    identities = {(round(float(c.get("receiver_x_m", 0)), 2), float(c.get("rotation_duration_s", -1))) for c in cases}
    if len(identities) != 16:
        errors.append("physical tuple identities are not unique")
    if set(round(float(c.get("receiver_x_m", 0)), 2) for c in cases) != EXPECTED_X:
        errors.append("receiver x set drift")
    if any(report["status"] != "pass" for report in reports):
        errors.append("one or more case contracts failed")
    report = {"schema": "ds02.f2.stage1.first24.source-contract-audit.v1", "status": "pass" if not errors else "fail",
              "source_only": True, "arrays_opened": False, "errors": errors, "cases": reports,
              "case_count": len(cases), "future_hashes_null": True}
    output = Path(args.output) if args.output else None
    if output:
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
