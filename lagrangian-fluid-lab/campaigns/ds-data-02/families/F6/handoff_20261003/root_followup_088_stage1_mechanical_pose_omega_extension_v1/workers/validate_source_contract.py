#!/usr/bin/env python3
"""Fail-closed metadata/XML validator for F6 fresh088.

This validator reads only JSON, XML, and source files in the source package. It
never opens a BI4, H5, CSV, DAT, IBI4, trajectory, or particle array. Future
paths and hashes are checked as declarations and remain null until Root binds
actual producer evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any


EXPECTED_COUNTS = {"fixed": 73441, "moving": 0, "floating": 16384, "fluid": 327680, "total": 417505}
EXPECTED_TYPES_MK = {
    "fixed": {"type": 0, "mk": 30},
    "moving": {"type": 1, "mk": None},
    "floating": {"type": 2, "mk": 60},
    "fluid": {"type": 3, "mk": 1},
}
CENTER = [2.4, 1.2, 1.08]
BASE = [0.08, 0.12, 0.06]
ANGLES = {-18.0, -12.0, -6.0, 6.0, 12.0, 18.0}
SCALES = {0.375, 0.625, 0.875, 1.125, 1.375, 1.625}
PATTERNS = {
    "DXYZ": [0.08, 0.12, 0.06],
    "DYXZ": [0.12, 0.08, 0.06],
    "DZXY": [0.06, 0.08, 0.12],
    "DYZX": [0.12, 0.06, 0.08],
}
SCIENCE_SUFFIXES = {".bi4", ".h5", ".csv", ".dat", ".ibi4", ".vtu", ".vtk"}


def canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def finite_vector(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(math.isfinite(float(x)) for x in value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    pkg = args.package.resolve()
    errors: list[str] = []

    def ok(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    plan = load(pkg / "metadata/mechanical-pose-plan.json")
    rows = plan.get("endpoints")
    ok(isinstance(rows, list) and len(rows) == 24, "plan must contain exactly 24 endpoints")
    rows = rows if isinstance(rows, list) else []
    ids = [str(row.get("endpoint_id", "")) for row in rows if isinstance(row, dict)]
    ok(len(ids) == len(set(ids)) == 24, "endpoint IDs must be unique")
    new_condition_hashes: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            errors.append("plan row is not an object")
            continue
        cid = str(row.get("endpoint_id", ""))
        scale = float(row.get("omega_scale", float("nan")))
        pattern = str(row.get("angular_component_pattern", ""))
        omega = row.get("initial_angular_velocity_rad_s")
        pose = row.get("initial_orientation_axis_angle", {})
        angle = float(pose.get("angle_deg", float("nan"))) if isinstance(pose, dict) else float("nan")
        ok(pattern in PATTERNS, f"{cid}: unknown angular component pattern")
        ok(scale in SCALES, f"{cid}: scale outside declared sparse extension")
        ok(angle in ANGLES, f"{cid}: orientation angle outside reviewed pose envelope")
        expected = [round(x * scale, 12) for x in PATTERNS.get(pattern, BASE)]
        ok(finite_vector(omega) and [round(float(x), 12) for x in omega] == expected, f"{cid}: omega does not match pattern*scale")
        ok(pose.get("axis") == [0.0, 0.0, 1.0], f"{cid}: orientation axis drift")
        ok(row.get("initial_center_m") == CENTER, f"{cid}: center drift")
        physical_tuple = {
            "family_id": "F6",
            "mechanism_id": "F6_FREE6DOF_RIGID_ANGULAR_RELEASE_V1",
            "dp_m": 0.025,
            "initial_angular_velocity_rad_s": omega,
            "initial_center_m": CENTER,
            "initial_orientation_axis_angle": pose,
            "body_mass_kg": 128.0,
            "full_event_window_s": [0.0, 12.0],
            "time_out_s": 0.05,
        }
        # The source plan hash is deliberately independent of the canonical
        # physical binding hash. The exact plan payload is recorded in the row.
        ok(row.get("source_plan_condition_sha256") == digest(row.get("source_plan_condition")), f"{cid}: source-plan hash drift")
        owner_path = Path(str(row.get("canonical_owner", "")))
        source_path = Path(str(row.get("source_definition", "")))
        ok(owner_path.is_file(), f"{cid}: owner missing")
        ok(source_path.is_file(), f"{cid}: source XML missing")
        if owner_path.is_file():
            owner = load(owner_path)
            ok(owner.get("physical_case_id") == cid, f"{cid}: owner case mismatch")
            ok(owner.get("source_definition") == str(source_path), f"{cid}: owner source path mismatch")
            ok(owner.get("source_definition_sha256") == sha(source_path), f"{cid}: owner source hash drift")
            ok(owner.get("source_plan_condition_sha256") == row.get("source_plan_condition_sha256"), f"{cid}: owner plan hash drift")
            pb = owner.get("physical_binding")
            ok(isinstance(pb, dict), f"{cid}: owner physical binding missing")
            if isinstance(pb, dict):
                ok(owner.get("physical_condition_sha256") == digest(pb), f"{cid}: canonical physical hash drift")
                new_condition_hashes.add(str(owner.get("physical_condition_sha256")))
                parameters = pb.get("parameters", {})
                ok(parameters.get("initial_angular_velocity_rad_s") == omega, f"{cid}: owner omega drift")
                ok(parameters.get("body_center_m") == CENTER, f"{cid}: owner center drift")
                ok(parameters.get("initial_orientation_axis_angle") == pose, f"{cid}: owner orientation drift")
                ok(float(parameters.get("body_mass_kg", float("nan"))) == 128.0, f"{cid}: owner physical mass drift")
            ok(row.get("canonical_owner_sha256") == sha(owner_path), f"{cid}: owner file hash drift")
            expected_native = owner.get("expected_native", {})
            ok(expected_native.get("dimension") == 3 and expected_native.get("true_3d") is True, f"{cid}: 3D source contract drift")
            for name in ("fixed", "moving", "floating", "fluid", "total"):
                ok(expected_native.get(name) == EXPECTED_COUNTS[name], f"{cid}: expected count contract drift {name}")
            ok(expected_native.get("floating_type") == 2 and expected_native.get("floating_mk") == 60, f"{cid}: floating type/Mk drift")
            ok(expected_native.get("fluid_type") == 3 and expected_native.get("fluid_mk") == 1, f"{cid}: fluid type/Mk drift")
        if source_path.is_file():
            try:
                root = ET.parse(source_path).getroot()
                angular = root.find(".//casedef/floatings/floating/angularvelini")
                center = root.find(".//casedef/floatings/floating/center")
                mass = root.find(".//casedef/floatings/floating/massbody")
                tm = root.find('.//execution/parameters/parameter[@key="TimeMax"]')
                tout = root.find('.//execution/parameters/parameter[@key="TimeOut"]')
                move = root.find('.//initials/move[@mkbound="50"]')
                rotate = root.find('.//initials/rotateaxis[@mkbound="50"]')
                ok(angular is not None and [round(float(angular.get(axis)), 12) for axis in "xyz"] == [round(float(x), 12) for x in omega], f"{cid}: XML angular declaration drift")
                ok(center is not None and [float(center.get(axis)) for axis in "xyz"] == CENTER, f"{cid}: XML center drift")
                ok(mass is not None and float(mass.get("value")) == 128.0, f"{cid}: XML physical mass drift")
                ok(tm is not None and tm.get("value") == "12" and tout is not None and tout.get("value") == "0.05", f"{cid}: XML time recipe drift")
                ok(move is not None and [float(move.get(axis)) for axis in "xyz"] == [0.0125, 0.0125, -0.0075], f"{cid}: XML lattice move drift")
                ok(rotate is not None and float(rotate.get("angle")) == angle and rotate.get("anglesunits") == "degrees", f"{cid}: XML orientation drift")
                if rotate is not None:
                    a1 = rotate.find("axisp1")
                    a2 = rotate.find("axisp2")
                    ok(a1 is not None and a2 is not None, f"{cid}: XML rotation axis incomplete")
                    if a1 is not None and a2 is not None:
                        ok([float(a1.get(axis)) for axis in "xyz"] == CENTER, f"{cid}: XML rotation axis start drift")
                        ok([float(a2.get(axis)) for axis in "xyz"] == [2.4, 1.2, 2.08], f"{cid}: XML rotation axis end drift")
            except Exception as exc:
                errors.append(f"{cid}: XML parse {exc}")
        ok(str(row.get("physical_condition_sha256")) in new_condition_hashes, f"{cid}: physical hash not bound")

    dedup = load(pkg / "metadata/dedup-registry.json")
    known = set(str(x) for x in dedup.get("existing_accepted_physical_condition_sha256", []))
    ok(not (new_condition_hashes & known), "new canonical physical hashes collide with accepted F6 evidence")
    ok(len(new_condition_hashes) == 24, "new canonical physical hashes must be unique")

    # Every request is a disabled declaration. Current source inputs must not
    # name scientific payload; those are future Root bindings only.
    request_paths = sorted(pkg.glob("gencase/requests/*.json")) + sorted(pkg.glob("qualification/requests/*.json")) + [pkg / "qa/requests/mechanical-pose-initial-native-qa-request.json", pkg / "floatinginfo/state0-request.json"]
    for path in request_paths:
        if not path.is_file():
            errors.append(f"request missing: {path}")
            continue
        request = load(path)
        ok(request.get("disabled") is True and request.get("launch") is False and request.get("launch_allowed") is False and request.get("execution_allowed") is False, f"{path.name}: request is not disabled")
        current = [str(x) for x in request.get("input_files", [])]
        ok(not any(Path(x).suffix.lower() in SCIENCE_SUFFIXES for x in current), f"{path.name}: source request names science payload")
        future_hashes = request.get("future_input_sha256", {})
        ok(isinstance(future_hashes, dict) and all(value is None for value in future_hashes.values()), f"{path.name}: future input hash not null")
        future_outputs = request.get("future_outputs", {})
        def check_null(value: Any) -> None:
            if isinstance(value, dict):
                if "sha256" in value:
                    ok(value.get("sha256") is None, f"{path.name}: future output hash fabricated")
                for child in value.values():
                    check_null(child)
            elif isinstance(value, list):
                for child in value:
                    check_null(child)
        check_null(future_outputs)
        input_sha = request.get("input_sha256", {})
        ok(set(current) == set(input_sha), f"{path.name}: current input/hash closure mismatch")

    qa_binding = load(pkg / "qa/initial-native-qa-binding.json")
    ok(qa_binding.get("launch_allowed") is False and qa_binding.get("status") == "source_only_disabled", "initial QA binding enabled")
    ok(isinstance(qa_binding.get("historical_evidence"), list) and len(qa_binding["historical_evidence"]) == 2, "historical QA/semantic evidence must remain exactly two records")
    ok(len(qa_binding.get("endpoints", [])) == 24, "initial QA binding must list all 24 cases")
    state_binding = load(pkg / "floatinginfo/state0-binding.json")
    ok(state_binding.get("launch_allowed") is False and state_binding.get("execution_allowed") is False, "FloatingInfo binding enabled")
    ok(len(state_binding.get("cases", [])) == 24, "FloatingInfo binding must list all 24 cases")

    report = {
        "schema": "ds02.f6.fresh088.source-validation.v1",
        "fresh_id": "fresh088",
        "package": str(pkg),
        "pass": not errors,
        "errors": errors,
        "new_case_count": 24,
        "dedup_basis": "checkpoint082 F6 accepted physical hashes plus source package 082; exact tuple includes angular vector, amplitude, center, and yaw pose",
        "recipe": {"dimension": 3, "dp_m": 0.025, "time_max_s": 12.0, "time_out_s": 0.05, "frames": 241},
        "native_identity_contract": EXPECTED_TYPES_MK,
        "mass_policy": {"physical_mass_kg": 128.0, "native_support_mass_kg": 256.0, "masspart_kg": 0.015625, "normalization": "none"},
        "read_policy": "JSON/XML/source only; no BI4/H5/CSV/DAT/IBI4/trajectory/particle arrays opened or hashed",
        "claim_boundary": "Source contract only; no GenCase/native initial QA/FloatingInfo state0/typed/XMF/render/visual/Q-N/precision/production result",
    }
    out = pkg / "metadata/source-validation-report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
