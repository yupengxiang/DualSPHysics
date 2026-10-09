#!/usr/bin/env python3
"""Forward F5 Y-zero geometry/support worker built on the consumed V8 reader.

V8's payload reader and first-hash/pre-post machinery are reused by module
loading; its consumed files are not changed.  The only adapter is the source
identity contract: V8 accepted the historical Y-half rung, while this worker
accepts the new dp=.005 Y-zero rung and rejects Y-half.  Before V8 reads any
dynamic XML/VTK payload, this wrapper checks the static Def phase relationship
and records that ``pointref`` is global to fluid, boundary, and shape/forcing
representations.  QI/QN/QE remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V8_PATH = HERE / "stage2_f5_s1_clipplane_geometry_diagnostic_v8.py"
CONTRACT_PATH = HERE / "stage2_f5_s1_clipplane_yzero_contract_v1.py"
SCHEMA = "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v9"
REQUEST_SCHEMA = "ds02.request.v1"
SUPPORT_CONTRACT_SCHEMA = "ds02.stage2.f5-s1.clipplane-geometry-diagnostic-contract.v8"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V8 = load_module("stage2_f5_yzero_v8_adapter", V8_PATH)
CONTRACT = load_module("stage2_f5_yzero_contract_v1", CONTRACT_PATH)

# V8.build_report calls V8.V7.validate_gencase_request before reading any
# dynamic payload.  Replace only this identity function in the in-memory
# module; the consumed V8 source and V8 payload reader remain byte-untouched.
V8.V7.validate_gencase_request = CONTRACT.validate_gencase_request


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    q = json.loads(args.gencase_request.expanduser().resolve().read_text(encoding="utf-8"))
    receipt = json.loads(args.receipt.expanduser().resolve().read_text(encoding="utf-8"))
    identity = CONTRACT.validate_gencase_request(q, receipt)
    phase = CONTRACT.validate_def_phase(args.candidate_def, args.source_def, expected_pointref=tuple(identity["expected_pointref_m"]))
    report = V8.build_report(args)
    report["schema"] = SCHEMA
    report["status"] = "COMPLETED_F5_YZERO_GEOMETRY_IDP_OVERLAP_DIAGNOSTIC_V9"
    report["source_binding"] = {
        "global_lattice_phase_change": True,
        "phase_change_relative_to_q107": "pointref.y 0.0025 -> 0.0000 only",
        "pointref_scope": "global GenCase lattice origin",
        "all_shapes_scope": ["fluid", "boundary", "forcing", "shape_operations"],
        "fluid_selector_unchanged": True,
        "boundary_selector_unchanged": True,
        "forcing_motion_content_unchanged": True,
        "static_def_phase_audit": phase,
    }
    report["candidate_contract"].update({
        "grid": identity["grid"],
        "expected_pointref_m": identity["expected_pointref_m"],
        "global_lattice_phase_change": True,
        "all_shapes_require_comparison": True,
        "fluid_boundary_forcing_not_assumed_equal": True,
        "continuous_owner_mass_kg": CONTRACT.CONTINUOUS_MASS_KG,
        "mass_rescale": False,
    })
    report["qualification"] = {
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        "reason": "Y-zero global phase geometry/support diagnostic only; terminal XML/Fluid/Bound evidence does not grant continuous mass, contact, flux, or solver qualification",
    }
    report["source_closure"]["worker_contract_adapter"] = "Y-zero static identity adapter; consumed V8 payload reader reused"
    return report


def self_test() -> dict[str, Any]:
    helper = CONTRACT.self_test()
    worker = V8.self_test()
    if helper.get("status") != "PASS" or worker.get("status") != "PASS":
        raise AssertionError({"contract": helper, "v8": worker})
    return {"status": "PASS", "schema": SCHEMA, "request_schema": REQUEST_SCHEMA, "reused_v8_payload_reader": True, "yhalf_rejected": True, "global_shape_scope": ["fluid", "boundary", "forcing", "shape_operations"], "solver_started": False, "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "support-contract", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "generated-xml", "receipt", "support-contract"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = [args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.clip_evidence, args.gencase_request, args.support_contract, args.output]
    if any(value is None for value in required):
        parser.error("all terminal/static paths, --support-contract and --output are required")
    report = build_report(args)
    V8.write_new(args.output, report)
    print(json.dumps({"status": report["status"], "schema": report["schema"], "output": str(args.output.resolve()), "global_shape_scope": report["source_binding"]["all_shapes_scope"], "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
