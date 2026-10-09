#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""V2 overlay observer wrapper for terminal V8 solver requests.

ROOT173/174 V8 requests predate the full-native observer schema: their BI4
snapshot is recorded in ``source_provenance.root161_snapshot_proof`` and the
BI4 record remains in ``source_provenance.generated_bi4``.  The consumed V3
observer requires a top-level ``bi4_snapshot_binding``.  This additive wrapper
adapts that metadata in memory for the delegated observer; it never rewrites
the terminal request and never reads the BI4 or native Part payload before the
parent guard.

The delegated V5/V3 worker still owns all native decoding, stat/hash
boundaries, cancellation, and report writing.  The adapter only supplies the
missing source binding and writes a small overlay sidecar after the delegated
observer returns.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V5_PATH = HERE / "stage2_f3_s2_full_native_stream_observer_v5.py"
SCHEMA = "ds02.stage2.f3-s2.overlay-native-observer.v2"
PASS_STATUS = "PASS_OVERLAY_NATIVE_OBSERVER_V2_WITH_NATIVE_MASS_BINDING"


def _load_v5():
    spec = importlib.util.spec_from_file_location(
        "stage2_f3_s2_overlay_native_observer_v2_v5_dependency", V5_PATH
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


def _request_snapshot_binding(request: dict[str, Any]) -> dict[str, Any]:
    """Derive the V3 binding shape from the actual V8 request metadata.

    This only reads the already supplied JSON object.  The returned metadata
    contains the expected BI4 SHA and size; it does not open the BI4.
    """
    source = request.get("source_provenance")
    if not isinstance(source, dict):
        raise ValueError("terminal V8 request lacks source_provenance")
    proof = source.get("root161_snapshot_proof")
    generated_bi4 = source.get("generated_bi4")
    input_sha = request.get("input_sha256")
    if not isinstance(proof, dict) or not isinstance(generated_bi4, dict) or not isinstance(input_sha, dict):
        raise ValueError("terminal V8 request lacks ROOT161 snapshot metadata")
    proof_path = proof.get("path")
    proof_sha = proof.get("sha256")
    bi4_path = generated_bi4.get("path")
    bi4_bytes = generated_bi4.get("bytes")
    bi4_sha = input_sha.get(str(bi4_path))
    if not isinstance(proof_path, str) or not isinstance(proof_sha, str) or len(proof_sha) != 64:
        raise ValueError("ROOT161 snapshot proof metadata is incomplete")
    if not isinstance(bi4_path, str) or not isinstance(bi4_sha, str) or len(bi4_sha) != 64:
        raise ValueError("V8 request BI4 path/SHA binding is incomplete")
    if not isinstance(bi4_bytes, int) or bi4_bytes <= 0:
        raise ValueError("V8 request BI4 byte binding is incomplete")
    return {
        "proof": proof_path,
        "proof_sha256": proof_sha,
        "bi4": {
            "path": bi4_path,
            "content_sha256": bi4_sha,
            "expected_bytes": bi4_bytes,
        },
        "adapter_source": "V8 source_provenance.root161_snapshot_proof + generated_bi4 + input_sha256",
        "payload_read_by_adapter": False,
    }


def _load_json_with_v8_adapter(original, request_path: Path):
    """Return a loader that enriches only the in-memory terminal request."""
    def load(path: Path, label: str):
        value = original(path, label)
        if _path(path) != request_path or "bi4_snapshot_binding" in value:
            return value
        enriched = dict(value)
        enriched["bi4_snapshot_binding"] = _request_snapshot_binding(value)
        return enriched

    return load


def run(args: argparse.Namespace) -> dict[str, Any]:
    # V5.run delegates to V3.  V3 loads the terminal request through its own
    # module helper, so install a narrowly scoped in-memory adapter for that
    # one request path and restore it even on cancellation/failure.
    request_path = _path(args.solver_request)
    v3 = V5.V3
    original_loader = v3._load_json
    v3._load_json = _load_json_with_v8_adapter(original_loader, request_path)
    try:
        result = V5.run(args)
    finally:
        v3._load_json = original_loader

    terminal_records = {
        "solver_request": _stable_record(args.solver_request, "overlay V8 terminal solver request"),
        "terminal_receipt": _stable_record(args.terminal_receipt, "overlay V8 terminal receipt"),
        "terminal_proof": _stable_record(args.terminal_proof, "overlay V8 terminal proof"),
        "source_snapshot_proof": _stable_record(args.source_snapshot_proof, "overlay source snapshot proof"),
        "source_snapshot_report": _stable_record(args.source_snapshot_report, "overlay source snapshot report"),
    }
    payload = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "adapter": {
            "terminal_request_schema": "ds02.stage2.external-solver-request.v5",
            "snapshot_binding_source": "source_provenance.root161_snapshot_proof + generated_bi4 + input_sha256",
            "request_rewritten_on_disk": False,
            "native_payload_read_by_adapter": False,
        },
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
    _write_once(_path(args.binding_output), payload)
    return {"status": PASS_STATUS, "binding": _stable_record(args.binding_output, "overlay V2 observer binding sidecar"), **result}


def self_test() -> dict[str, Any]:
    value = V5.self_test()
    if value.get("status") != "PASS":
        raise AssertionError(value)
    fixture = {
        "source_provenance": {
            "root161_snapshot_proof": {"path": "/tmp/root161-proof.json", "sha256": "a" * 64},
            "generated_bi4": {"path": "/tmp/middle.bi4", "bytes": 9227118},
        },
        "input_sha256": {"/tmp/middle.bi4": "b" * 64},
    }
    binding = _request_snapshot_binding(fixture)
    if binding["bi4"]["content_sha256"] != "b" * 64 or binding["bi4"]["expected_bytes"] != 9227118:
        raise AssertionError("V8 snapshot binding adapter self-test failed")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "delegated_worker": V5.SCHEMA,
        "snapshot_binding_adapter": "PASS_MANUFACTURED_V8_SOURCE_PROVENANCE",
        "request_rewritten_on_disk": False,
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
        print(f"overlay native observer V2 failed: {exc}", file=sys.stderr)
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
