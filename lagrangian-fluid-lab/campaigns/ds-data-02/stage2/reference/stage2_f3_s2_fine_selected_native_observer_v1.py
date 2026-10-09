#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Bounded selected-native observer for the terminal F3-S2 dp=.003 run.

The consumed middle observer already implements the reviewed decoder process
group cleanup, per-Part pre/decode/post SHA/stat checks, native header fields,
and RunPARTs bracket handling.  This forward wrapper reuses that implementation
with a separate fine-grid schema/status and refuses to touch the fine raw tree
until the parent guard has materialized a terminal-bound request.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import stage2_f3_s2_middle_selected_native_observer_v1 as middle


SCHEMA = "ds02.stage2.f3-s2.fine-selected-native-observer.v1"
PASS_STATUS = "PASS_FINE_SELECTED_NATIVE_FIELDS"
UNKNOWN_STATUS = "UNKNOWN_UNSUPPORTED_FINE_NATIVE_OBSERVER"
DP_M = 0.003


def _unknown(output: Path, reason: str) -> dict[str, Any]:
    output = output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable fine observer output: {output}")
    value = {
        "schema": SCHEMA,
        "status": UNKNOWN_STATUS,
        "reason": reason,
        "scope": {
            "fine_grid_dp_m": DP_M,
            "selected_frames_only": True,
            "typed_conversion": "NOT_PERFORMED",
            "hdf5_read": False,
            "native_payload_read_after_parent_reservation": True,
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    middle.base.atomic_json(output, value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable fine observer output: {output}")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.middle-adapter.json")
    delegated = argparse.Namespace(**vars(args))
    delegated.output = temporary
    try:
        result = middle.run(delegated)
        value = json.loads(temporary.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("middle observer output is not a JSON object")
        if value.get("status") != middle.PASS_STATUS:
            raise middle.base.UnsupportedSemantics(f"delegated middle observer did not PASS: {value.get('status')!r}")
        value["schema"] = SCHEMA
        value["status"] = PASS_STATUS
        value["scope"] = dict(value.get("scope", {}))
        value["scope"]["fine_grid_dp_m"] = DP_M
        value["scope"]["observer_variant"] = "F3-S2 dp=.003 fine selected native fields"
        value["scientific_qualification"] = {
            "QI": "PASS_LIMITED_FINE_SELECTED_NATIVE_FIELDS",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "scope_note": "native header/finite/identity/time checks only; no interpolation, dynamics, spatial truth, or event qualification",
        }
        value["fine_source_binding"] = {
            "dp_m": DP_M,
            "native_mass_role": "selected BI4 header MassFluid; discrete diagnostic only",
            "continuum_owner_mass": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
        }
        middle.base.atomic_json(output, value)
        return value
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    base = middle.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "selected_query_times_s": [0.0, 2.0, 4.0, 6.0, 8.0, "ACTUAL_FINAL_TIME_REQUIRED"],
        "fine_grid_dp_m": DP_M,
        "interpolation": False,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--decoder-source", type=Path)
    parser.add_argument("--calibration-contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-12)
    parser.add_argument("--frames", type=int, nargs="+")
    parser.add_argument("--query-times", type=float, nargs="+")
    parser.add_argument("--decoder-timeout-s", type=float, default=300.0)
    parser.add_argument("--max-decoder-log-bytes", type=int, default=64 * 1024)
    parser.add_argument("--max-decoder-scratch-bytes", type=int, default=256 * 1024 * 1024)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (
        args.raw_root, args.runparts, args.generated_xml, args.decoder,
        args.decoder_source, args.calibration_contract, args.output,
        args.scratch_root, args.expected_frame_count, args.expected_final_time_s,
        args.frames, args.query_times,
    )
    if any(value is None for value in required):
        parser.error("all fine selected observer arguments are required unless --self-test is used")
    try:
        result = run(args)
    except middle.full.WorkerCancelled as exc:
        print(str(exc), file=sys.stderr)
        return 143
    except middle.base.UnsupportedSemantics as exc:
        try:
            result = _unknown(args.output.expanduser().resolve(), str(exc))
        except FileExistsError:
            print(str(exc), file=os.sys.stderr)
            return 2
        print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve())}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(f"fine selected observer failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "selected_frames": len(result.get("observations", []))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
