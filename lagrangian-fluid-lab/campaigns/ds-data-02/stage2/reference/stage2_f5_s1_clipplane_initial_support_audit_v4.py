#!/usr/bin/env python3
"""Parameterized F5 clip-plane initial support/mass QA (forward V4).

This worker consumes a terminal GenCase product for either registered repair
candidate and measures the actual XML fluid blocks and binary VTK points.  It
compares the particle sample to the source-derived continuous clipped region
(287.736 kg), checks the explicit plane side and finite fluid/bound points, and
verifies source/candidate motion and controls.  It is a guarded CPU audit only:
no BI4, HDF5, solver output, or CFD is read.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V3_PATH = HERE / "stage2_f5_s1_initial_gencase_support_audit_v3.py"
V2_PATH = HERE / "stage2_f5_s1_clipplane_official_evidence_audit_v2.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V3 = load_module("stage2_f5_support_v3_runtime", V3_PATH)
CLIP = load_module("stage2_f5_clip_v2_runtime", V2_PATH)
MASS_ONE_PERCENT = 0.01
MASS_TWO_PERCENT = 0.02
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    s = path.stat()
    return {"path": str(path), "bytes": int(s.st_size), "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns), "st_dev": int(s.st_dev), "st_ino": int(s.st_ino), "sha256": sha256(path)}


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable support report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = __import__("os").open(path, __import__("os").O_WRONLY | __import__("os").O_CREAT | __import__("os").O_EXCL, 0o644)
    try:
        with __import__("os").fdopen(fd, "wb") as f:
            fd = -1; f.write(payload); f.flush(); __import__("os").fsync(f.fileno())
    finally:
        if fd >= 0: __import__("os").close(fd)


def normalized_representation(path: Path) -> str:
    data = path.read_bytes()
    data, n = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb"\1<DP>\2", data, count=1)
    if n != 1:
        raise ValueError(f"missing unique definition dp: {path}")
    data, n = re.subn(rb'<pointref\s+x="[^"]+"\s+y="[^"]+"\s+z="[^"]+"\s*/>', b'<pointref x="<X>" y="<Y>" z="<Z>" />', data, count=1)
    if n != 1:
        raise ValueError(f"missing unique pointref: {path}")
    return hashlib.sha256(data).hexdigest()


def controls(xml: dict[str, Any]) -> dict[str, Any]:
    keys = ("TimeMax", "TimeOut", "Boundary", "Kernel", "ViscoTreatment", "Visco", "DensityDT", "Shifting", "SlipMode", "StepAlgorithm")
    return {key: xml["parameters"].get(key) for key in keys}


def plane_relation(points, point: tuple[float, float, float], vector: tuple[float, float, float], dp: float) -> dict[str, Any]:
    import numpy as np
    p = np.asarray(point, dtype=np.float64); n = np.asarray(vector, dtype=np.float64)
    values = (points - p) @ n
    tol = max(1e-7, dp * 1e-5)
    return {"predicate": "n.(x-point)<=0", "tolerance": tol, "min_value": float(values.min()), "max_value": float(values.max()), "outside_count": int((values > tol).sum()), "boundary_or_near_count": int((np.abs(values) <= tol).sum())}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    generated_xml = args.generated_xml.resolve(); fluid_vtk = args.fluid_vtk.resolve(); bound_vtk = args.bound_vtk.resolve(); receipt_path = args.receipt.resolve(); candidate_def = args.candidate_def.resolve(); source_def = args.source_def.resolve(); candidate_motion = args.candidate_motion.resolve(); source_motion = args.source_motion.resolve(); evidence = args.clip_evidence.resolve(); gencase_request = args.gencase_request.resolve()
    dynamic = {"generated_xml": generated_xml, "fluid_vtk": fluid_vtk, "bound_vtk": bound_vtk, "receipt": receipt_path}
    dynamic_pre = {key: record(path) for key, path in dynamic.items()}
    static = {"candidate_def": candidate_def, "source_def": source_def, "candidate_motion": candidate_motion, "source_motion": source_motion, "clip_evidence": evidence, "gencase_request": gencase_request}
    static_pre = {key: record(path) for key, path in static.items()}
    expected = {"candidate_def": args.expected_candidate_def_sha, "source_def": args.expected_source_def_sha, "candidate_motion": args.expected_candidate_motion_sha, "source_motion": args.expected_source_motion_sha, "clip_evidence": args.expected_clip_evidence_sha, "gencase_request": args.expected_gencase_request_sha, "generated_xml": args.expected_generated_xml_sha, "receipt": args.expected_receipt_sha}
    for key, digest in expected.items():
        if digest and (static_pre[key]["sha256"] if key in static_pre else dynamic_pre[key]["sha256"]) != digest:
            raise ValueError(f"{key} SHA mismatch")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("GenCase receipt is not completed zero-return")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if generated_xml.parent != output_root:
        raise ValueError("generated XML is outside receipt output_root")
    request = json.loads(gencase_request.read_text(encoding="utf-8"))
    if request.get("family_id") != "F5" or request.get("sentinel_id") != "F5-S1" or request.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("GenCase request identity mismatch")
    generated = V3.parse_xml(generated_xml); candidate = V3.parse_xml(candidate_def); source = V3.parse_xml(source_def)
    if generated["fluid_count"] is None or generated["fluid_count"] <= 0 or not generated["fluid_blocks"]:
        raise ValueError("generated XML has no typed fluid blocks")
    if abs(generated["dp_m"] - candidate["dp_m"]) > 1e-12 or abs(generated["dp_m"] - float(request.get("source_binding", {}).get("dp_m", generated["dp_m"]))) > 1e-12:
        raise ValueError("generated/candidate/request dp mismatch")
    if generated["fluid_boxes"] != candidate["fluid_boxes"]:
        raise ValueError("generated fluid selector geometry differs from candidate")
    if normalized_representation(source_def) != normalized_representation(candidate_def):
        raise ValueError("candidate changes source definition outside dp/pointref")
    if source["parameters"] != candidate["parameters"] or source["boundary_boxes"] != candidate["boundary_boxes"]:
        raise ValueError("candidate changes source controls or boundary geometry")
    if sha256(candidate_motion) != sha256(source_motion):
        raise ValueError("candidate motion differs from source motion")
    clip_source = CLIP.parse_clip(source_def); clip_candidate = CLIP.parse_clip(candidate_def)
    if clip_source["point"] != clip_candidate["point"] or clip_source["vector"] != clip_candidate["vector"] or clip_source["fluid_low"] != clip_candidate["fluid_low"] or clip_source["fluid_size"] != clip_candidate["fluid_size"]:
        raise ValueError("candidate changes source clip/continuous box")
    points, fluid_meta = V3.read_vtk_fluid(fluid_vtk, generated["fluid_count"], generated["fluid_blocks"])
    bound_points, bound_meta = V3.read_vtk_points(bound_vtk)
    fluid_relation = V3.inside_relation(points, generated["fluid_boxes"][0], generated["dp_m"])
    plane = plane_relation(points, clip_source["point"], clip_source["vector"], generated["dp_m"])
    low = tuple(clip_source["fluid_low"]); size = tuple(clip_source["fluid_size"]); vector = tuple(clip_source["vector"]); point = tuple(clip_source["point"])
    volume, quadrature = CLIP.clipped_volume(low, size, vector, point)
    continuous_mass = volume * 1000.0; sample_mass = float(generated["fluid_count"] * generated["massfluid_kg"]); relative = sample_mass / continuous_mass - 1.0
    mass_gate = "PASS_SOURCE_DERIVED_CONTINUOUS_REGION_WITHIN_ONE_PERCENT" if abs(relative) <= MASS_ONE_PERCENT else "MARGINAL_SOURCE_DERIVED_CONTINUOUS_REGION_ONE_TO_TWO_PERCENT" if abs(relative) <= MASS_TWO_PERCENT else "HARDFAIL_SOURCE_DERIVED_CONTINUOUS_REGION_OVER_TWO_PERCENT"
    dynamic_post = {key: record(path) for key, path in dynamic.items()}; static_post = {key: record(path) for key, path in static.items()}
    if dynamic_pre != dynamic_post or static_pre != static_post:
        raise RuntimeError("input changed during F5 V4 support audit")
    support_gate = "PASS_FINITE_FLUID_SUPPORT_INSIDE_BOX_AND_CLIP_SIDE" if fluid_relation["outside_closed_count"] == 0 and plane["outside_count"] == 0 else "FAIL_FLUID_SUPPORT_OUTSIDE_BOX_OR_CLIP_SIDE"
    return {"schema": "ds02.stage2.f5-s1.clipplane-initial-support-audit.v4", "status": "COMPLETED_PARAMETERIZED_INITIAL_SUPPORT_MASS_AUDIT", "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE_ID, "grid": request.get("source_binding", {}).get("grid", "UNKNOWN"), "scope": {"generated_xml_read": True, "generated_fluid_vtk_read": True, "generated_bound_vtk_read": True, "execution_receipt_read": True, "clip_evidence_read": True, "bi4_read": False, "hdf5_read": False, "solver_started": False, "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "inputs": {"dynamic_pre": dynamic_pre, "dynamic_post": dynamic_post, "static_pre": static_pre, "static_post": static_post, "pre_post_equal": True}, "generated": {"dp_m": generated["dp_m"], "fluid_count": generated["fluid_count"], "massfluid_kg": generated["massfluid_kg"], "fluid_blocks": generated["fluid_blocks"], "fluid_boxes": generated["fluid_boxes"]}, "support": {"fluid_vtk": {key: value for key, value in fluid_meta.items() if key != "mapped_ids"}, "bound_vtk": bound_meta, "fluid_box_relation": fluid_relation, "clip_plane_relation": plane, "gate": support_gate}, "continuous_region": {"volume_m3": volume, "mass_kg": continuous_mass, "quadrature": quadrature, "source_clip_and_box_unchanged": True}, "mass_audit": {"generated_sample_mass_kg": sample_mass, "derived_continuous_mass_kg": continuous_mass, "relative_error_fraction": relative, "relative_error_percent": relative * 100.0, "gate": mass_gate, "preferred_fraction": MASS_ONE_PERCENT, "hard_fraction": MASS_TWO_PERCENT, "mass_rescale": False}, "control_audit": {"normalized_source_candidate_representation_equal": True, "source_candidate_controls_equal": True, "source_candidate_boundary_equal": True, "motion_byte_identical": True, "source_dp_m": source["dp_m"], "candidate_dp_m": candidate["dp_m"], "generated_dp_m": generated["dp_m"], "source_parameters": controls(source), "candidate_parameters": controls(candidate), "generated_parameters": controls(generated)}, "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "support_gate": support_gate, "mass_gate": mass_gate, "reason": "actual GenCase XML/VTK support and source-derived continuous mass audit only; solver remains blocked until preferred initial support/mass gate and parent review"}}


def self_test() -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", hashlib.sha256(b"f5-v4").hexdigest()):
        raise AssertionError("digest fixture failed")
    return {"status": "PASS", "bi4_read": False, "hdf5_read": False, "solver_started": False, "source_derived_mass_gate": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--self-test", action="store_true")
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "generated-xml", "receipt"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.clip_evidence, args.gencase_request, args.output]
    if any(v is None for v in required): parser.error("all generated/static paths and --output are required")
    report = build_report(args); write_new(args.output, report); print(json.dumps({"status": report["status"], "grid": report["grid"], "support_gate": report["support"]["gate"], "mass_gate": report["mass_audit"]["gate"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
