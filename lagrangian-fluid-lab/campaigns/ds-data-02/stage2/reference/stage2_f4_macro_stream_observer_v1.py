#!/usr/bin/env python3
"""Decode a complete native F4 window once and stream macro observables.

The worker keeps the immutable native Part tree as the scientific source and
writes one compact JSON object per saved frame.  It does not create HDF5,
interpolate query times, pair IDs across grids, or infer rigid-body mass.  A
temporary official-decoder directory is removed after each frame.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage2_f4_physical_observer_v1 import (  # noqa: E402
    UnsupportedSemantics,
    atomic_json,
    decode_frame,
    file_record,
    frame_observables,
    parse_source_xml,
    read_runparts,
    sha256_file,
    time_bracket,
)


SCHEMA = "ds02.stage2.f4-macro-stream-observer.v1"


def compact_group(group: dict[str, Any]) -> dict[str, Any]:
    density = group.get("density", {})
    return {
        "kind": group.get("kind"),
        "mk": group.get("mk"),
        "count": group.get("count"),
        "sample_mass_kg": group.get("sample_mass_kg"),
        "centroid_m": group.get("centroid_m"),
        "mean_velocity_m_per_s": group.get("mean_velocity_m_per_s"),
        "kinetic_energy_j": group.get("kinetic_energy_j"),
        "density_mean": density.get("mean") if isinstance(density, dict) else None,
        "density_status": density.get("status") if isinstance(density, dict) else "UNKNOWN",
    }


def compact_observables(observation: dict[str, Any], raw_file: dict[str, Any]) -> dict[str, Any]:
    groups = observation.get("groups", {})
    fluid = groups.get("fluid", {}) if isinstance(groups, dict) else {}
    by_mk = fluid.get("by_mk", {}) if isinstance(fluid, dict) else {}
    region = {str(mk): compact_group(value) for mk, value in by_mk.items() if isinstance(value, dict)}
    return {
        "frame": observation.get("frame"),
        "time": observation.get("time"),
        "identity": observation.get("identity"),
        "fluid": {
            "sample_mass_kg": observation.get("fluid_observables", {}).get("sample_mass_kg"),
            "centroid_m": observation.get("fluid_observables", {}).get("centroid_m"),
            "mean_velocity_m_per_s": observation.get("fluid_observables", {}).get("mean_velocity_m_per_s"),
            "kinetic_energy_j": observation.get("fluid_observables", {}).get("kinetic_energy_j"),
            "density_mean": (observation.get("fluid_observables", {}).get("density") or {}).get("mean"),
            "status": observation.get("fluid_observables", {}).get("status"),
        },
        "regions_by_mk": region,
        "native_part": raw_file,
        "field_digest_sha256": observation.get("raw_field_digest_sha256"),
        "position_dtype": observation.get("position_dtype"),
    }


def write_line(handle: Any, value: dict[str, Any]) -> None:
    handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = args.raw_root.resolve()
    runparts = args.runparts.resolve()
    generated_xml = args.generated_xml.resolve()
    decoder = args.decoder.resolve()
    output = args.output.resolve()
    scratch_root = args.scratch_root.resolve()
    if output.exists():
        raise FileExistsError(f"refuse to overwrite {output}")
    if not raw_root.is_dir() or decoder.is_symlink() or not decoder.is_file() or not os.access(decoder, os.X_OK):
        raise ValueError("raw root or official decoder is unavailable/unsafe")
    rows = read_runparts(runparts)
    if len(rows) != args.expected_frame_count:
        raise ValueError(f"RunPARTs rows {len(rows)} != expected {args.expected_frame_count}")
    if abs(rows[-1]["time_s"] - args.expected_final_time_s) > args.final_time_tolerance_s:
        raise ValueError(f"actual final time {rows[-1]['time_s']} differs from expected {args.expected_final_time_s}")
    parts = [int(row["part"]) for row in rows]
    if parts != list(range(len(rows))):
        raise ValueError("RunPARTs parts are not contiguous from zero")
    source = parse_source_xml(generated_xml)
    queries = [float(x) for x in args.query_times]
    brackets = [time_bracket(rows, query) for query in queries]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".{os.getpid()}.tmp")
    combined = __import__("hashlib").sha256()
    frame_count = 0
    raw_bytes = 0
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            write_line(handle, {
                "record_type": "manifest",
                "schema": SCHEMA,
                "status": "STREAMING",
                "source": {"raw_root": str(raw_root), "runparts": file_record(runparts), "generated_xml": file_record(generated_xml), "decoder": file_record(decoder)},
                "expected_frame_count": len(rows),
                "expected_raw_part_bytes": args.expected_raw_bytes,
                "expected_final_time_s": args.expected_final_time_s,
                "actual_saved_window_s": [rows[0]["time_s"], rows[-1]["time_s"]],
                "query_brackets": brackets,
                "sampling_policy": "saved-frame macro observables; no interpolation/extrapolation",
                "mass_semantics": "native particle sample mass only; not continuum or rigid body mass",
                "particle_id_pairing": "not performed",
                "hdf5_read": False,
            })
            for frame, row in enumerate(rows):
                path = raw_root / f"Part_{frame:04d}.bi4"
                decoded = decode_frame(path, decoder, scratch_root, frame)
                observation = frame_observables(decoded, source, row["time_s"])
                raw_file = decoded["saved_file"]
                raw_bytes += int(raw_file["bytes"])
                combined.update(path.name.encode("ascii"))
                combined.update(int(raw_file["bytes"]).to_bytes(8, "big"))
                combined.update(bytes.fromhex(str(raw_file["sha256"])))
                write_line(handle, {"record_type": "frame", "observable": compact_observables(observation, raw_file)})
                frame_count += 1
                del decoded, observation
            write_line(handle, {
                "record_type": "summary",
                "status": "PASS_FULL_NATIVE_MACRO_STREAM",
                "frame_count": frame_count,
                "raw_part_bytes": raw_bytes,
                "combined_ordered_part_digest": combined.hexdigest(),
                "query_policy": "brackets retained; query-time fields UNKNOWN until consumer interpolation policy",
                "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
                "typed_conversion": "NOT_PERFORMED",
                "hdf5_read": False,
                "source_deleted": False,
            })
            handle.flush()
            os.fsync(handle.fileno())
        if raw_bytes != args.expected_raw_bytes:
            output.unlink(missing_ok=True)
            raise ValueError(f"native Part bytes {raw_bytes} != expected {args.expected_raw_bytes}")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"status": "PASS_FULL_NATIVE_MACRO_STREAM", "frames": frame_count, "raw_part_bytes": raw_bytes, "output": str(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--expected-frame-count", type=int, required=True)
    parser.add_argument("--expected-raw-bytes", type=int, required=True)
    parser.add_argument("--expected-final-time-s", type=float, required=True)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-12)
    parser.add_argument("--query-times", type=float, nargs="+", required=True)
    args = parser.parse_args()
    try:
        result = run(args)
    except UnsupportedSemantics as exc:
        raise SystemExit(f"UNKNOWN_UNSUPPORTED_SEMANTICS: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
