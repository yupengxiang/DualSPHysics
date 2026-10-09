#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Bounded selected-frame native observer for the ROOT162 F3 middle run.

The decoder and process-group safety come from the consumed F3 full-native
stream worker.  This wrapper adds the middle-run scope: it reads only frame 0,
the frames bracketing the registered 2/4/6/8 s queries, and the actual final
frame.  Every selected Part is hashed/stat-checked before and after decode;
the worker records native header MassFluid and decoder TimeStep values without
interpolating particle fields or using XML mass as a fallback.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import stage2_f3_s2_full_native_stream_observer_v2 as full
import stage2_f3_s2_native_header_observer_v1 as header_observer
import stage2_native_physical_observer_v2 as base


SCHEMA = "ds02.stage2.f3-s2.middle-selected-native-observer.v1"
PASS_STATUS = "PASS_MIDDLE_SELECTED_NATIVE_FIELDS"


def _unknown(output: Path, reason: str) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": "UNKNOWN_UNSUPPORTED_MIDDLE_NATIVE_OBSERVER",
        "reason": reason,
        "scope": {"selected_frames_only": True, "typed_conversion": "NOT_PERFORMED", "hdf5_read": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    base.atomic_json(output, value)
    return value


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise base.UnsupportedSemantics(f"{label} is not finite")
    return float(value)


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = args.raw_root.expanduser().resolve()
    runparts = args.runparts.expanduser().resolve()
    generated_xml = args.generated_xml.expanduser().resolve()
    decoder = args.decoder.expanduser().resolve()
    decoder_source = args.decoder_source.expanduser().resolve()
    calibration_path = args.calibration_contract.expanduser().resolve()
    output = args.output.expanduser().resolve()
    scratch_root = args.scratch_root.expanduser().resolve()
    if not raw_root.is_dir() or raw_root.is_symlink():
        raise base.UnsupportedSemantics(f"middle raw root is missing or symlinked: {raw_root}")
    rows = base.read_runparts(runparts)
    if len(rows) != args.expected_frame_count:
        raise base.UnsupportedSemantics(f"RunPARTs rows {len(rows)} != expected {args.expected_frame_count}")
    if abs(rows[-1]["time_s"] - args.expected_final_time_s) > args.final_time_tolerance_s:
        raise base.UnsupportedSemantics(
            f"RunPARTs final time {rows[-1]['time_s']} differs from expected {args.expected_final_time_s}"
        )
    calibration = full.load_calibration(calibration_path)
    source = base.parse_source_xml(generated_xml)
    decoder_contract = base.decoder_source_contract(decoder_source)
    if decoder_contract["status"] == "UNKNOWN_DECODER_SOURCE_CONTRACT":
        raise base.UnsupportedSemantics("decoder source does not prove the argc=3 input/output-prefix contract")
    queries = [float(value) for value in args.query_times]
    brackets = [base.time_bracket(rows, query) for query in queries]
    if any(item["status"] == "OUTSIDE_SAVED_WINDOW" for item in brackets):
        raise base.UnsupportedSemantics("registered middle query is outside the actual saved RunPARTs window")
    required_frames: set[int] = {0, args.expected_frame_count - 1}
    for item in brackets:
        if item["status"] not in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
            raise base.UnsupportedSemantics(f"unsupported query bracket status: {item['status']}")
        required_frames.add(int(item["lower_frame"]))
        required_frames.add(int(item["upper_frame"]))
    requested_frames = {int(value) for value in args.frames}
    selected_frames = sorted(requested_frames | required_frames)
    if any(frame < 0 or frame >= len(rows) for frame in selected_frames):
        raise base.UnsupportedSemantics(f"selected middle frame outside RunPARTs axis: {selected_frames}")

    previous_handlers = full._install_signal_cleanup()
    frame_records: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    mass_values: list[float] = []
    massbound_values: list[float] = []
    try:
        for frame in selected_frames:
            frame_path = raw_root / f"Part_{frame:04d}.bi4"
            pre = full.checked_hash(frame_path, f"middle_pre_decode_frame_{frame}")
            try:
                native = full.decode_frame_bounded(
                    frame_path,
                    decoder,
                    scratch_root,
                    frame,
                    timeout_s=args.decoder_timeout_s,
                    max_log_bytes=args.max_decoder_log_bytes,
                    max_scratch_bytes=args.max_decoder_scratch_bytes,
                )
                native_header = {
                    name: header_observer.native_scalar(
                        name,
                        native["metadata"],
                        native["info"],
                        required=name == "MassFluid",
                    )
                    for name in ("MassFluid", "MassBound", "Rhop0", "Dp", "H", "PeriMode")
                }
                mass = _finite(native_header["MassFluid"]["value"], f"MassFluid frame {frame}")
                mass_values.append(mass)
                bound = native_header["MassBound"]["value"]
                if isinstance(bound, (int, float)) and not isinstance(bound, bool):
                    massbound_values.append(float(bound))
                observation = header_observer._observable(native, source, native_header)
                observation["runparts_time_s"] = float(rows[frame]["time_s"])
                observation["decoder_time_delta_s"] = float(native["decoded_time_s"] - rows[frame]["time_s"])
                observation["decoder_process"] = {
                    "stdout_tail": native["decoder_stdout_tail"],
                    "stderr_tail": native["decoder_stderr_tail"],
                    "timeout_s": args.decoder_timeout_s,
                    "max_scratch_bytes": args.max_decoder_scratch_bytes,
                    "max_stdout_stderr_bytes": args.max_decoder_log_bytes,
                    "process_group_cancel_policy": "SIGTERM_then_SIGKILL_and_wait_on_timeout",
                    "parent_death_signal": "PR_SET_PDEATHSIG_SIGTERM_best_effort",
                }
                observation["source_file"] = native["saved_file"]
                observation["decoder_xml_sha256"] = native["decoder_xml_sha256"]
                observations.append(observation)
            finally:
                post = full.checked_hash(frame_path, f"middle_post_decode_frame_{frame}")
                full.compare_decode_boundaries(pre, post)
                frame_records.append({"frame": frame, "path": str(frame_path), "pre_decode": pre, "post_decode": post})
    finally:
        full._restore_signal_cleanup(previous_handlers)

    if not mass_values or len(set(mass_values)) != 1:
        raise base.UnsupportedSemantics("native MassFluid changed or was absent across selected middle frames")
    if massbound_values and len(set(massbound_values)) != 1:
        raise base.UnsupportedSemantics("native MassBound changed across selected middle frames")
    payload = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
        "scope": {
            "selected_frames_only": True,
            "selected_frame_count": len(selected_frames),
            "runparts_frame_count": len(rows),
            "selected_frame_ids": selected_frames,
            "registered_query_times_s": queries,
            "full_native_tree_scanned": False,
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "particle_field_interpolation": "NOT_PERFORMED",
            "time_interpolation": "NOT_PERFORMED",
            "native_payload_read_after_parent_reservation": True,
        },
        "source": {
            "raw_root": str(raw_root),
            "runparts": base.file_record(runparts),
            "generated_xml": base.file_record(generated_xml),
            "decoder": base.file_record(decoder),
            "decoder_source": base.file_record(decoder_source),
            "decoder_interface": decoder_contract,
            "particle_range_semantics": source,
            "selected_frame_records": frame_records,
        },
        "time_window": {
            "first_saved_time_s": rows[0]["time_s"],
            "last_saved_time_s": rows[-1]["time_s"],
            "queries": brackets,
            "saved_time_source": "actual RunPARTs.csv plus decoder TimeStep for selected frames",
            "no_extrapolation": True,
        },
        "calibration": {
            "contract": calibration,
            "field_comparisons": "NOT_PERFORMED",
            "time_output_error_separation": "NOT_PERFORMED",
            "neighbor_grid_truth": False,
        },
        "native_header_summary": {
            "selected_massfluid_kg": mass_values[0],
            "selected_massbound_kg": massbound_values[0] if massbound_values else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
            "massfluid_exact_across_selected_frames": True,
            "massbound_exact_across_selected_frames": True if massbound_values else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
            "sample_mass_role": "native BI4 header MassFluid times decoded XML-range fluid count; discrete diagnostic only",
            "continuum_owner_mass": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
            "rigid_body_mass_inertia": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SAMPLE",
        },
        "observations": observations,
        "decoder_resource_policy": {
            "per_frame_timeout_s": args.decoder_timeout_s,
            "process_group_cancel": "SIGTERM_then_SIGKILL_then_wait",
            "parent_death_signal": "PR_SET_PDEATHSIG_SIGTERM_best_effort",
            "max_decoder_log_bytes": args.max_decoder_log_bytes,
            "max_decoder_scratch_bytes": args.max_decoder_scratch_bytes,
            "scratch_retained_after_frame": False,
        },
        "scientific_qualification": {
            "QI": "PASS_LIMITED_SELECTED_NATIVE_FIELDS" if frame_records else "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "scope_note": "native header/finite/identity/time source checks only; no interpolation, dynamics, spatial truth, or event qualification",
        },
    }
    base.atomic_json(output, payload)
    return payload


def self_test() -> dict[str, Any]:
    if SCHEMA != "ds02.stage2.f3-s2.middle-selected-native-observer.v1":
        raise AssertionError("middle observer schema changed")
    queries = [0.0, 2.0, 4.0, 6.0, 8.0, 8.350016881886734]
    if queries != sorted(queries) or queries[0] != 0.0 or queries[-1] <= 8.0:
        raise AssertionError("registered query times changed")
    return {"status": "PASS", "schema": SCHEMA, "selected_query_times_s": queries, "interpolation": False, "solver_started": False}


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
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.raw_root, args.runparts, args.generated_xml, args.decoder, args.decoder_source, args.calibration_contract, args.output, args.scratch_root, args.expected_frame_count, args.expected_final_time_s, args.frames, args.query_times)
    if any(value is None for value in required):
        parser.error("all middle selected observer arguments are required unless --self-test is used")
    try:
        result = run(args)
    except full.WorkerCancelled as exc:
        print(str(exc), file=sys.stderr); return 143
    except base.UnsupportedSemantics as exc:
        try:
            result = _unknown(args.output.expanduser().resolve(), str(exc))
        except FileExistsError:
            print(str(exc), file=sys.stderr); return 2
        print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve())}, ensure_ascii=False)); return 2
    except Exception as exc:
        print(f"middle selected observer failed: {exc}", file=sys.stderr); return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.expanduser().resolve()), "selected_frames": len(result["observations"])}, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
