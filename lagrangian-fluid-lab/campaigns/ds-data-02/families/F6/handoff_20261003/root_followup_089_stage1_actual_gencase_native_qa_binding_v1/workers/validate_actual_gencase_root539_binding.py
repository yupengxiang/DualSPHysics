#!/usr/bin/env python3
"""Metadata-only validator for the Root539 -> fresh089 QA handoff.

This validator reads JSON/XML and source files only.  It never opens, hashes,
or decodes BI4/H5/CSV/DAT/IBI4/trajectory/particle-array payloads.  A BI4
digest is accepted only when it is a 64-hex producer attestation copied from
Root539's prepared-input-report.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping


SCIENCE_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".ibi4", ".vtu", ".vtk"}
COUNTS = {"fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}


class ValidationError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValidationError(f"expected JSON object: {path}")
    return value


def require(path: Path, label: str) -> Path:
    if not path.is_file():
        raise ValidationError(f"{label} is missing: {path}")
    return path


def finite_vector(node: ET.Element | None, label: str) -> list[float]:
    if node is None:
        raise ValidationError(f"missing XML node: {label}")
    values = []
    for axis in "xyz":
        raw = node.get(axis)
        if raw is None:
            raise ValidationError(f"missing XML {label}.{axis}")
        value = float(raw)
        if not math.isfinite(value):
            raise ValidationError(f"non-finite XML {label}.{axis}")
        values.append(value)
    return values


def same(left: list[float], right: list[float], tolerance: float = 1.0e-12) -> bool:
    return len(left) == len(right) and all(abs(a - b) <= tolerance for a, b in zip(left, right))


def validate_xml(source_path: Path, generated_path: Path, endpoint: Mapping[str, Any]) -> dict[str, Any]:
    source = ET.parse(require(source_path, "source definition")).getroot()
    generated = ET.parse(require(generated_path, "generated XML")).getroot()
    source_float = source.find(".//casedef/floatings/floating")
    generated_float = generated.find(".//casedef/floatings/floating")
    particles = generated.find(".//execution/particles")
    if particles is None:
        particles = generated.find(".//particles")
    if source_float is None or generated_float is None or particles is None:
        raise ValidationError(f"incomplete generated/source XML: {generated_path}")
    expected_omega = [float(value) for value in endpoint["omega_rad_s"]]
    checks = {
        "source_omega_matches_owner": same(finite_vector(source_float.find("angularvelini"), "source omega"), expected_omega),
        "generated_omega_matches_owner": same(finite_vector(generated_float.find("angularvelini"), "generated omega"), expected_omega),
        "generated_center_is_declared": same(finite_vector(generated_float.find("center"), "generated center"), [2.4, 1.2, 1.08]),
        "generated_massbody_is_128kg": abs(float(generated_float.find("massbody").get("value", "nan")) - 128.0) <= 1.0e-12 if generated_float.find("massbody") is not None else False,
        "generated_true_3d": (generated.find(".//constants/data2d") is not None and generated.find(".//constants/data2d").get("value", "").lower() == "false"),
        "generated_np_matches_receipt": int(particles.get("np", "-1")) == COUNTS["total"],
        "generated_floating_count_matches": int(particles.find("floating").get("count", "-1")) == COUNTS["floating"] if particles.find("floating") is not None else False,
        "generated_fixed_count_matches": int(particles.find("fixed").get("count", "-1")) == COUNTS["fixed"] if particles.find("fixed") is not None else False,
        "generated_fluid_count_matches": int(particles.find("fluid").get("count", "-1")) == COUNTS["fluid"] if particles.find("fluid") is not None else False,
    }
    pose = endpoint.get("initial_orientation_axis_angle")
    rotate = generated.find(".//initials/rotateaxis")
    if not isinstance(pose, Mapping) or rotate is None:
        checks["generated_rotateaxis_matches_owner"] = False
    else:
        axis1 = rotate.find("axisp1")
        axis2 = rotate.find("axisp2")
        checks["generated_rotateaxis_matches_owner"] = (abs(float(rotate.get("angle", "nan")) - float(pose["angle_deg"])) <= 1.0e-12 and rotate.get("anglesunits") == "degrees" and axis1 is not None and axis2 is not None and [float(axis1.get(a, "nan")) for a in "xyz"] == [2.4, 1.2, 1.08] and [float(axis2.get(a, "nan")) for a in "xyz"] == [2.4, 1.2, 2.08])
    return checks


def validate_request(path: Path, binding_path: Path, worker_path: Path) -> dict[str, Any]:
    request = load(path)
    if request.get("disabled") is not True or request.get("launch") is not False or request.get("launch_allowed") is not False or request.get("execution_allowed") is not False:
        raise ValidationError(f"QA request is not disabled: {path}")
    if request.get("binding") != str(binding_path):
        raise ValidationError("QA request binding path is not fresh089")
    if request.get("worker") != str(worker_path):
        raise ValidationError("QA request worker path is not fresh089")
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    if not isinstance(files, list) or not isinstance(hashes, dict) or set(files) != set(hashes):
        raise ValidationError("QA request input/hash closure mismatch")
    checked = 0
    skipped_bi4 = 0
    for raw in files:
        path_value = Path(str(raw))
        if path_value.suffix.lower() == ".bi4":
            if not re.fullmatch(r"[0-9a-f]{64}", str(hashes[str(raw)])):
                raise ValidationError(f"BI4 input does not carry a producer 64-hex digest: {raw}")
            skipped_bi4 += 1
            continue
        require(path_value, "QA input")
        if sha256(path_value) != str(hashes[str(raw)]):
            raise ValidationError(f"QA input hash mismatch: {raw}")
        checked += 1
    return {"path": str(path), "input_files": len(files), "metadata_files_hashed": checked, "bi4_producer_attestations_skipped": skipped_bi4}


def validate(binding_path: Path, request_path: Path | None, output_path: Path) -> dict[str, Any]:
    binding = load(binding_path)
    if binding.get("schema") != "ds02.f6.stage1-mechanical-pose-omega-initial-native-qa-binding.v3" or binding.get("status") != "source_only_disabled":
        raise ValidationError("fresh089 QA binding schema/status mismatch")
    if binding.get("launch_allowed") is not False or binding.get("execution_allowed") is not False:
        raise ValidationError("fresh089 QA binding is launchable")
    actual_binding_path = Path(str(binding["actual_gencase_binding"]))
    actual_binding = load(actual_binding_path)
    if actual_binding.get("actual_completed0_all24") is not True or int(actual_binding.get("case_count", -1)) != 24:
        raise ValidationError("Root539 actual binding is not complete 24-case metadata")
    if sha256(actual_binding_path) != binding.get("actual_gencase_binding_sha256"):
        raise ValidationError("Root539 binding hash mismatch")
    endpoints = binding.get("endpoints")
    if not isinstance(endpoints, list) or len(endpoints) != 24:
        raise ValidationError("fresh089 must contain exactly 24 endpoints")
    rows = []
    for endpoint in endpoints:
        cid = str(endpoint["endpoint_id"])
        source = Path(str(endpoint["source_definition"]))
        owner = Path(str(endpoint["canonical_owner"]))
        generated = Path(str(endpoint["generated_xml"]))
        receipt_path = Path(str(endpoint["execution_receipt"]))
        report_path = Path(str(endpoint["prepared_input_report"]))
        if sha256(source) != endpoint["source_definition_sha256"] or sha256(owner) != endpoint["canonical_owner_sha256"]:
            raise ValidationError(f"source/owner hash mismatch: {cid}")
        if sha256(generated) != endpoint["generated_xml_sha256"]:
            raise ValidationError(f"generated XML hash mismatch: {cid}")
        if sha256(receipt_path) != endpoint["execution_receipt_sha256"] or sha256(report_path) != endpoint["prepared_input_report_sha256"]:
            raise ValidationError(f"Root539 metadata hash mismatch: {cid}")
        receipt = load(receipt_path)
        report = load(report_path)
        if receipt.get("status") != "completed" or receipt.get("returncode") != 0 or receipt.get("total_particles") != COUNTS["total"] or receipt.get("fluid_particles") != COUNTS["fluid"] or receipt.get("solver_dimension_from_gencase") != 3:
            raise ValidationError(f"Root539 receipt mismatch: {cid}")
        if report.get("xml_sha256") != endpoint["generated_xml_sha256"] or report.get("bi4_sha256") != endpoint["generated_bi4_sha256"]:
            raise ValidationError(f"Root539 producer digest mismatch: {cid}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(report.get("bi4_sha256", ""))) or Path(str(endpoint["generated_bi4"])).suffix.lower() != ".bi4":
            raise ValidationError(f"BI4 producer attestation malformed: {cid}")
        checks = validate_xml(source, generated, endpoint)
        if not all(checks.values()):
            raise ValidationError(f"generated XML checks failed for {cid}: {checks}")
        rows.append({"case_id": cid, "receipt": "completed/0", "counts": COUNTS, "xml_checks": checks, "bi4_payload_opened": False})
    request_result = validate_request(request_path, binding_path, Path(str(binding["worker"]))) if request_path else None
    result = {
        "schema": "ds02.f6.fresh089.actual-gencase-native-qa-source-validation.v1",
        "fresh_id": "fresh089", "case_count": len(rows), "pass": True, "rows": rows,
        "root539_completed0_all24": True, "producer_bi4_attestation_only": True, "bi4_payloads_opened": False,
        "science_payloads_opened_or_hashed": False, "request_validation": request_result,
        "native_initial_qa_status": "disabled_pending_root_strict_cpu_partvtk", "floatinginfo_state0_status": "future_required",
        "claim_boundary": "metadata-only Root539 binding; no native QA/solver/state0/visual/Q-N/precision/production claim",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.binding, args.request, args.output)
    except Exception as exc:
        print(json.dumps({"schema": "ds02.f6.fresh089.actual-gencase-native-qa-source-validation.v1", "pass": False, "error": repr(exc)}, sort_keys=True))
        return 1
    print(json.dumps({"schema": result["schema"], "pass": True, "case_count": result["case_count"], "bi4_payloads_opened": False, "science_payloads_opened_or_hashed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
