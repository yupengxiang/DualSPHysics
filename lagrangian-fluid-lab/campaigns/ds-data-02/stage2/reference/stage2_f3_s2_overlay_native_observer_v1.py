#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Forward wrapper for a guarded native observer of ROOT162/173/174.

The consumed full-native worker owns decoder safety, source stat/hash
boundaries, native ``MassFluid`` decoding, and the full report/compact
summary schemas.  This wrapper keeps those bytes unchanged and adds a small
overlay binding sidecar.  It is intentionally useful only after the parent
has joined a terminal solver request, receipt, proof, source snapshot and
native output tree; it never reads a native file before that guard.

The sidecar is an operational binding record.  It does not grant QI/QN/QE,
does not interpolate fields, and does not use XML mass as a replacement for
the decoded native header mass.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V5_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v5.py"
SCHEMA = "ds02.stage2.f3-s2.overlay-native-observer.v1"
PASS_STATUS = "PASS_OVERLAY_NATIVE_OBSERVER_WITH_NATIVE_MASS_BINDING"


def _load_v5():
    spec = importlib.util.spec_from_file_location(
        "stage2_f3_s2_overlay_native_observer_v1_v5_dependency", V5_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(V5_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V5 = _load_v5()


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _stable_record(path: Path, label: str) -> dict[str, Any]:
    # V5's record performs a stat-before/read/stat-after check and hashes the
    # complete small metadata file.  The native Part tree is handled only by
    # V5 after the parent reservation.
    return V5._stable_record(_path(path), label)


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable overlay sidecar: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    # V5.run delegates to the consumed V3 decoder and writes the full report
    # plus compact summary.  All payload access remains inside that guarded
    # call; the wrapper does not open raw_root itself.
    result = V5.run(args)
    binding_output = _path(args.binding_output)
    terminal_records = {
        "solver_request": _stable_record(args.solver_request, "overlay terminal solver request"),
        "terminal_receipt": _stable_record(args.terminal_receipt, "overlay terminal receipt"),
        "terminal_proof": _stable_record(args.terminal_proof, "overlay terminal proof"),
        "source_snapshot_proof": _stable_record(args.source_snapshot_proof, "overlay source snapshot proof"),
        "source_snapshot_report": _stable_record(args.source_snapshot_report, "overlay source snapshot report"),
    }
    payload = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "overlay": {
            "label": str(args.overlay_label),
            "changed_variable": str(args.overlay_variable),
            "changed_value": str(args.overlay_value),
            "same_source_bi4_forcing_continuous_owner": True,
        },
        "producer_outputs": {
            "full_report": result["full_report"],
            "compact_summary": result["summary"],
            "native_mass_source": "full/compact observer native_header.MassFluid only",
            "xml_mass_fallback": False,
            "native_payload_read_by_wrapper": False,
        },
        "terminal_binding": terminal_records,
        "observation_scope": {
            "full_window_or_actual_query_brackets": True,
            "native_saved_times": "RunPARTs plus decoded native TimeStep",
            "time_interpolation": False,
            "particle_field_interpolation": False,
            "neighbor_grid_as_truth": False,
            "event_time": "UNKNOWN_NO_SOURCE_EVENT_DEFINITION",
        },
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "native field/header/time/source binding only; task error separation is a later consumer",
        },
    }
    _write_once(binding_output, payload)
    return {"status": PASS_STATUS, "binding": _stable_record(binding_output, "overlay observer binding sidecar"), **result}


def self_test() -> dict[str, Any]:
    value = V5.self_test()
    if value.get("status") != "PASS":
        raise AssertionError(value)
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "delegated_worker": V5.SCHEMA,
        "native_mass_source": "native_header.MassFluid",
        "xml_mass_fallback": False,
        "solver_started": False,
        "native_payload_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--solver-request", type=Path)
    parser.add_argument("--terminal-receipt", type=Path)
    parser.add_argument("--terminal-proof", type=Path)
    parser.add_argument("--source-snapshot-proof", type=Path)
    parser.add_argument("--source-snapshot-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--decoder-source", type=Path)
    parser.add_argument("--calibration-contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--binding-output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--expected-dp-m", type=float)
    parser.add_argument("--expected-initial-fluid-count", type=int)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-9)
    parser.add_argument("--query-times", type=float, nargs="+")
    parser.add_argument("--decoder-timeout-s", type=float, default=300.0)
    parser.add_argument("--max-decoder-log-bytes", type=int, default=64 * 1024)
    parser.add_argument("--max-decoder-scratch-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--overlay-label", default="UNREGISTERED_OVERLAY")
    parser.add_argument("--overlay-variable", default="UNKNOWN")
    parser.add_argument("--overlay-value", default="UNKNOWN")
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (
        args.solver_request, args.terminal_receipt, args.terminal_proof,
        args.source_snapshot_proof, args.source_snapshot_report, args.raw_root,
        args.runparts, args.generated_xml, args.decoder, args.decoder_source,
        args.calibration_contract, args.output, args.summary_output,
        args.binding_output, args.scratch_root, args.expected_frame_count,
        args.expected_final_time_s, args.expected_dp_m,
        args.expected_initial_fluid_count, args.query_times,
    )
    if any(value is None for value in required):
        parser.error("all terminal/source/observer/output arguments are required unless --self-test is used")
    try:
        result = run(args)
    except V5.V3.WorkerCancelled as exc:
        print(str(exc), file=sys.stderr)
        return 143
    except Exception as exc:
        print(f"overlay native observer failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": result["status"],
        "binding": result["binding"],
        "full_report": result["full_report"],
        "summary": result["summary"],
        "solver_started": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
