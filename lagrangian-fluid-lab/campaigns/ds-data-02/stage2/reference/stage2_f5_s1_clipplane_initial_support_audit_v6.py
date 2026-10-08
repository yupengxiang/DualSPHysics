#!/usr/bin/env python3
"""Forward F5 Y-half initial support/mass/control audit (V6).

V5 GenCase requests 106/107 preserve the F5 source box, official clip plane,
bed, boundary and motion while changing the lattice phase.  This worker is a
small forward wrapper around the consumed V4 binary-VTK audit.  It adds the
candidate-rung contract and the parent-v8 source-closure checks without
changing V4 bytes or reading any payload before the parent guard reserves the
job.

The worker reads generated XML, Fluid VTK and Bound VTK only after the parent
reservation.  It records full pre/immediate/post hashes and stats for those
worker-owned VTK files through V4.  The builder never hashes VTK.  The old
254.4779834119572 kg producer sample remains diagnostic; the source-derived
official clip region is 287.736 kg at rho0=1000 kg/m^3.  No mass rescaling,
solver launch, BI4 read or HDF5 read is allowed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V4_PATH = HERE / "stage2_f5_s1_clipplane_initial_support_audit_v4.py"
SCHEMA = "ds02.stage2.f5-s1.clipplane-initial-support-audit.v6"
REQUEST_SCHEMA = "ds02.request.v1"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_DISCRETE_SAMPLE_MASS_KG = 254.4779834119572
EXPECTED = {
    "dp010": {"dp_m": 0.010, "pointref_m": (0.015, 0.005, 0.015)},
    "dp005": {"dp_m": 0.005, "pointref_m": (0.0125, 0.0025, 0.0125)},
}


def load_v4():
    spec = importlib.util.spec_from_file_location("stage2_f5_clipplane_support_v4_for_v6", V4_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V4_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V4 = load_v4()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def validate_request_contract(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("GenCase/support request schema mismatch")
    if request.get("family_id") != "F5" or request.get("sentinel_id") != "F5-S1":
        raise ValueError("F5-S1 request identity mismatch")
    if request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("F5 physical case identity mismatch")
    binding = request.get("source_binding")
    if not isinstance(binding, dict):
        raise ValueError("missing source_binding")
    grid = binding.get("grid")
    if grid not in EXPECTED:
        raise ValueError(f"unsupported F5 Y-half grid: {grid!r}")
    expected = EXPECTED[grid]
    if abs(float(binding.get("dp_m", -1.0)) - expected["dp_m"]) > 1e-12:
        raise ValueError("request dp does not match the registered Y-half rung")
    pointref = tuple(float(value) for value in binding.get("pointref_m", ()))
    if pointref != expected["pointref_m"]:
        raise ValueError("request pointref does not match the registered Y-half rung")
    if abs(float(binding.get("continuous_region_mass_kg", -1.0)) - CONTINUOUS_MASS_KG) > 1e-9:
        raise ValueError("request continuous owner mass is not the frozen source-derived 287.736 kg")
    if float(binding.get("old_sample_mass_kg", OLD_DISCRETE_SAMPLE_MASS_KG)) != OLD_DISCRETE_SAMPLE_MASS_KG:
        raise ValueError("request changed the diagnostic old discrete sample mass")
    if binding.get("continuous_box_and_clip_unchanged") is not True:
        raise ValueError("request does not preserve the continuous box and official clip")
    if binding.get("controls_and_motion_unchanged") is not True:
        raise ValueError("request does not preserve source controls and motion")
    if binding.get("mass_rescale") is not False:
        raise ValueError("mass rescaling is forbidden")
    closure = request.get("parent_v8_input_closure")
    if not isinstance(closure, dict):
        raise ValueError("missing parent_v8_input_closure")
    if closure.get("deferred_input_files_used") is not False:
        raise ValueError("deferred input files cannot stand in for parent input closure")
    if closure.get("vtk_sha_authority") != "V4 worker pre/post full SHA after parent reservation":
        raise ValueError("worker-owned VTK SHA authority is not explicit")
    if request.get("worker_owned_input_hashes", {}).get("hash_status") != "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES":
        raise ValueError("builder must leave worker-owned VTK hashes for the reserved worker")
    return {"grid": grid, "expected_dp_m": expected["dp_m"], "expected_pointref_m": list(expected["pointref_m"]), "continuous_region_mass_kg": CONTINUOUS_MASS_KG}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    request = load_json(args.gencase_request, "F5 GenCase request")
    contract = validate_request_contract(request)
    report = V4.build_report(args)
    # V4 has already performed source/candidate/clip/control comparisons and
    # full worker-owned VTK pre/post checks.  V6 adds explicit terminal
    # candidate identity and keeps the qualification state conservative.
    generated_parameters = report.get("control_audit", {}).get("generated_parameters")
    candidate_parameters = report.get("control_audit", {}).get("candidate_parameters")
    if generated_parameters != candidate_parameters:
        raise ValueError("generated XML controls differ from the candidate Def controls")
    generated_dp = float(report.get("generated", {}).get("dp_m", -1.0))
    if abs(generated_dp - contract["expected_dp_m"]) > 1e-12:
        raise ValueError("terminal generated XML dp differs from the Y-half request")
    report["schema"] = SCHEMA
    report["status"] = "COMPLETED_F5_YHALF_INITIAL_SUPPORT_MASS_CONTROL_AUDIT"
    report["candidate_contract"] = {
        "grid": contract["grid"],
        "expected_dp_m": contract["expected_dp_m"],
        "expected_pointref_m": contract["expected_pointref_m"],
        "continuous_owner_mass_kg": CONTINUOUS_MASS_KG,
        "old_discrete_sample_mass_kg": OLD_DISCRETE_SAMPLE_MASS_KG,
        "old_discrete_sample_is_diagnostic_only": True,
        "official_clip_and_box_unchanged": True,
        "controls_and_motion_unchanged": True,
        "mass_rescale": False,
    }
    report["source_closure"] = {
        "parent_v8_deferred_input_files_used": False,
        "small_inputs_parent_sha_stat_checked": True,
        "worker_owned_vtk_full_sha_stat_pre_immediate_post": True,
        "worker_owned_vtk_hash_scope": "after parent reservation; no builder/local payload hash",
        "source_generated_xml_and_receipt_scope": "small inputs checked by parent and worker",
    }
    report["support_scope"] = {
        "fluid_vtk": "finite points, XML Idp mapping, closed fluid envelope and official clip half-space",
        "bound_vtk": "finite point payload/count only; no no-penetration or contact-free claim",
        "continuous_owner": "source-derived official clipped region mass 287.736 kg; no old-sample normalization",
    }
    report["qualification"] = {
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        "reason": "actual Y-half GenCase XML/Fluid/Bound VTK support and mass/control audit only; solver and scientific qualification remain pending",
    }
    return report


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable V6 report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{__import__('os').getpid()}.tmp")
    try:
        fd = __import__('os').open(temporary, __import__('os').O_CREAT | __import__('os').O_EXCL | __import__('os').O_WRONLY, 0o644)
        try:
            with __import__('os').fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                __import__('os').fsync(handle.fileno())
        finally:
            if fd >= 0:
                __import__('os').close(fd)
        __import__('os').replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    good = {
        "schema": REQUEST_SCHEMA,
        "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "source_binding": {
            "grid": "dp010", "dp_m": 0.01, "pointref_m": [0.015, 0.005, 0.015],
            "continuous_region_mass_kg": CONTINUOUS_MASS_KG,
            "old_sample_mass_kg": OLD_DISCRETE_SAMPLE_MASS_KG,
            "continuous_box_and_clip_unchanged": True, "controls_and_motion_unchanged": True, "mass_rescale": False,
        },
        "parent_v8_input_closure": {"deferred_input_files_used": False, "vtk_sha_authority": "V4 worker pre/post full SHA after parent reservation"},
        "worker_owned_input_hashes": {"hash_status": "NOT_COMPUTED_BY_BUILDER_OR_PARENT_INPUT_FILES"},
    }
    assert validate_request_contract(good)["grid"] == "dp010"
    bad = json.loads(json.dumps(good))
    bad["parent_v8_input_closure"]["deferred_input_files_used"] = True
    try:
        validate_request_contract(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("deferred VTK input closure was accepted")
    bad = json.loads(json.dumps(good))
    bad["source_binding"]["old_sample_mass_kg"] = 287.736
    try:
        validate_request_contract(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("old discrete sample mass was silently replaced")
    return {"status": "PASS", "schema": SCHEMA, "grids": sorted(EXPECTED), "vtk_payload_read": False, "solver_started": False, "deferred_input_rejected": True, "old_sample_rescale_rejected": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "generated-xml", "receipt"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.clip_evidence, args.gencase_request, args.output]
    if any(value is None for value in required):
        parser.error("all terminal/static paths and --output are required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "grid": report["candidate_contract"]["grid"], "support_gate": report["support"]["gate"], "mass_gate": report["mass_audit"]["gate"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
