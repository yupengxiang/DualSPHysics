#!/usr/bin/env python3
"""Decode only the 24 missing native rows for one F4-S1 run.

This is a forward-only companion to the consumed F4 nine-row observers.  The
builder records source ``stat`` metadata without opening native payloads.  A
parent guard must reserve the bounded CPU task before this worker hashes or
decodes any selected ``Part_*.bi4`` file.  The actual decode reuses the
forward v2 bounded decoder, including process-group cancellation, parent-death
handling, log and scratch caps, and source pre/post SHA/stat checks.

The output contains only the newly decoded rows.  It does not rewrite or
re-decode the historical nine-row observer and it never interpolates particle
fields.  XML ranges label relative/absolute MK coordinates; native rigid-body
mass, continuum mass, pressure/EOS, and QN/QE remain unknown.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np

import stage2_f3_s2_full_native_stream_observer_v2 as bounded
import stage2_f3_s2_native_header_observer_v1 as header_observer
import stage2_native_physical_observer_v2 as base


SCHEMA = "ds02.stage2.f4-s1.missing-native-observer.v1"
PASS_STATUS = "PASS_MISSING_SELECTED_NATIVE_FIELDS"
UNKNOWN_STATUS = "UNKNOWN_UNSUPPORTED_NATIVE_ENCODING"
TIME_TOLERANCE_S = 1.0e-10


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _record_small(path: Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Hash only small control/metadata files, never a native Part here."""

    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular file is missing or symlinked: {path}")
    record = base.file_record(path)
    if expected is not None:
        if record.get("sha256") != expected.get("sha256") or record.get("bytes") != expected.get("bytes"):
            raise base.UnsupportedSemantics(f"small source changed: {path}")
    return record


def _planned_stat(path: Path) -> dict[str, int]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise base.UnsupportedSemantics(f"native source is missing or symlinked: {path}")
    stat = path.stat()
    return {
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
    }


def _stat_matches_planned(path: Path, planned: dict[str, Any]) -> dict[str, int]:
    actual = _planned_stat(path)
    expected = {key: int(planned[key]) for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}
    if actual != expected:
        raise base.UnsupportedSemantics(
            f"source stat changed after preparation for {path}: expected={expected} actual={actual}"
        )
    return actual


def _field_digest(frame: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for name, array in (
        ("Idp", frame["ids"]),
        ("Pos", frame["position"]),
        ("Vel", frame["velocity"]),
        ("Rhop", frame["density"]),
    ):
        digest.update(name.encode("ascii"))
        digest.update(str(array.dtype).encode("ascii"))
        digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("ascii"))
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _native_groups(native: dict[str, Any], source: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    """Compute weighted groups using the decoded native MassFluid field."""

    ids = native["ids"]
    kind, mkfluid_relative, mk_absolute = base.assign_particle_ranges(ids, source["blocks"])
    massfluid = header["MassFluid"]["value"]
    massbound_value = header["MassBound"]["value"]
    massbound = massbound_value if isinstance(massbound_value, (int, float)) and not isinstance(massbound_value, bool) else None
    constants = {"massfluid_kg": float(massfluid), "massbound_kg": massbound}
    groups: dict[str, Any] = {}
    for index in range(ids.size):
        key = f"{kind[index]}:mkfluid_relative={int(mkfluid_relative[index])}:mk_absolute={int(mk_absolute[index])}"
        if key in groups:
            continue
        mask = (kind == kind[index]) & (mkfluid_relative == mkfluid_relative[index]) & (mk_absolute == mk_absolute[index])
        groups[key] = base.group_observable(
            str(kind[index]), int(mkfluid_relative[index]), int(mk_absolute[index]), mask, native, constants
        )
    return groups


def _observable(native: dict[str, Any], source: dict[str, Any], header: dict[str, Any], runparts_time_s: float) -> dict[str, Any]:
    ids = native["ids"]
    position = native["position"]
    velocity = native["velocity"]
    density = native["density"]
    if not (np.isfinite(ids).all() and np.isfinite(position).all() and np.isfinite(velocity).all() and np.isfinite(density).all()):
        raise base.UnsupportedSemantics(f"non-finite decoded field at frame {native['frame']}")
    if np.unique(ids).size != ids.size:
        raise base.UnsupportedSemantics(f"duplicate Idp at frame {native['frame']}")
    decoded_time = float(native["decoded_time_s"])
    if not math.isfinite(decoded_time) or abs(decoded_time - runparts_time_s) > TIME_TOLERANCE_S:
        raise base.UnsupportedSemantics(
            f"decoder/RunPARTs time mismatch at frame {native['frame']}: {decoded_time} vs {runparts_time_s}"
        )
    kind, mkfluid_relative, mk_absolute = base.assign_particle_ranges(ids, source["blocks"])
    fluid_mask = kind == "fluid"
    mass = float(header["MassFluid"]["value"])
    fluid_count = int(np.sum(fluid_mask))
    if fluid_count:
        fluid_position = position[fluid_mask]
        fluid_velocity = velocity[fluid_mask]
        weights = np.full(fluid_count, mass, dtype=np.float64)
        centroid = np.average(fluid_position, axis=0, weights=weights)
        mean_velocity = np.average(fluid_velocity, axis=0, weights=weights)
        kinetic_energy = float(0.5 * mass * np.sum(np.square(fluid_velocity), dtype=np.float64))
        sample_mass = float(fluid_count * mass)
    else:
        centroid = mean_velocity = None
        kinetic_energy = None
        sample_mass = 0.0
    return {
        "frame": int(native["frame"]),
        "time": {
            "runparts_s": float(runparts_time_s),
            "decoded_s": decoded_time,
            "absolute_error_s": abs(decoded_time - runparts_time_s),
            "status": "PASS_DECODED_TIME_MATCH",
        },
        "identity": {
            "status": "PASS_XML_TYPED_RANGE_COVERAGE",
            "particle_count": int(ids.size),
            "id_unique": True,
            "id_min": int(ids.min()),
            "id_max": int(ids.max()),
            "mkfluid_relative_values": sorted(set(int(value) for value in mkfluid_relative[fluid_mask].tolist())),
            "mk_absolute_values": sorted(set(int(value) for value in mk_absolute[fluid_mask].tolist())),
            "semantics": "XML ranges label relative/absolute MK only; no native Type/MK claim",
        },
        "finite_fields": {
            "Idp": True,
            "Pos_or_Posd": True,
            "Vel": True,
            "Rhop": True,
            "status": "PASS_FINITE",
        },
        "native_header": header,
        "groups": _native_groups(native, source, header),
        "fluid_observables": {
            "fluid_count": fluid_count,
            "sample_mass_kg": sample_mass,
            "weighted_centroid_m": None if centroid is None else [float(value) for value in centroid],
            "weighted_velocity_m_per_s": None if mean_velocity is None else [float(value) for value in mean_velocity],
            "kinetic_energy_j": kinetic_energy,
            "mass_semantics": "native_BI4_header_MassFluid_times_XML_range_fluid_count; discrete diagnostic only",
        },
        "field_digest_sha256": _field_digest(native),
        "position_dtype": native["position_dtype"],
        "decoder_process": {
            "stdout_tail": native.get("decoder_stdout_tail", ""),
            "stderr_tail": native.get("decoder_stderr_tail", ""),
        },
    }


def _atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _unknown(output: Path, reason: str, failed_frame: int | None = None) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": UNKNOWN_STATUS,
        "reason": reason,
        "failed_frame": failed_frame,
        "scope": {"selected_missing_frames_only": True, "hdf5_read": False, "solver_launch": False},
        "scientific_qualification": {
            "QI": "UNKNOWN_SELECTED_NATIVE_FIELDS",
            "QN": "UNKNOWN_TIME_OUTPUT_AND_SPATIAL_REFERENCE",
            "QE": "UNKNOWN_NO_REGISTERED_EVENT_TIME",
        },
    }
    _atomic_json(output, value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().resolve()
    spec_path = args.spec.expanduser().resolve()
    spec = _read_json(spec_path)
    if spec.get("schema") != "ds02.stage2.f4-s1.missing-native-observer-spec.v1":
        raise ValueError(f"unexpected spec schema: {spec_path}")
    raw_root = Path(spec["raw_root"]).expanduser().resolve()
    runparts = Path(spec["runparts"]["path"]).expanduser().resolve()
    generated_xml = Path(spec["generated_xml"]["path"]).expanduser().resolve()
    decoder = Path(spec["decoder"]["path"]).expanduser().resolve()
    decoder_source = Path(spec["decoder_source"]["path"]).expanduser().resolve()
    rows = base.read_runparts(runparts)
    if len(rows) != int(spec["expected_frame_count"]):
        raise ValueError(f"RunPARTs row count changed: {len(rows)}")
    if abs(rows[-1]["time_s"] - float(spec["expected_final_time_s"])) > float(spec["final_time_tolerance_s"]):
        raise ValueError("RunPARTs final time changed from the source binding")
    source = base.parse_source_xml(generated_xml)
    decoder_contract = base.decoder_source_contract(decoder_source)
    if decoder_contract["status"] != "PASS_SOURCE_ARGC3_OUTPUT_PREFIX_CONTRACT":
        raise base.UnsupportedSemantics("official decoder source contract is not proven")
    small_records = {
        "runparts": _record_small(runparts, spec["runparts"]),
        "generated_xml": _record_small(generated_xml, spec["generated_xml"]),
        "decoder": _record_small(decoder),
        "decoder_source": _record_small(decoder_source, spec["decoder_source"]),
        "existing_observer": _record_small(Path(spec["existing_observer"]["path"]), spec["existing_observer"]),
    }
    selected = spec.get("selected_frames")
    planned_records = spec.get("selected_native_frame_records")
    if not isinstance(selected, list) or not isinstance(planned_records, list) or len(selected) != len(planned_records):
        raise ValueError("spec selected frame records are malformed")
    if [int(item["frame"]) for item in planned_records] != [int(value) for value in selected]:
        raise ValueError("spec selected frame order mismatch")
    queries = [float(value) for value in spec["query_times_s"]]
    query_windows = []
    for query in queries:
        bracket = base.time_bracket(rows, query)
        window = next((item for item in spec["query_windows"] if float(item["query_time_s"]) == query), None)
        if window is None:
            raise ValueError(f"missing source query window: {query}")
        query_windows.append({"source": window, "actual_runparts_bracket": bracket, "field_interpolation": "NOT_PERFORMED"})
    previous_handlers = bounded._install_signal_cleanup()
    observations: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    mass_values: list[float] = []
    try:
        for item in planned_records:
            frame = int(item["frame"])
            path = Path(item["path"]).expanduser().resolve()
            if int(frame) != int(path.stem.split("_")[-1]):
                raise base.UnsupportedSemantics(f"frame/path mismatch: {frame} {path}")
            _stat_matches_planned(path, item["planned_stat"])
            pre = bounded.checked_hash(path, f"pre_decode_frame_{frame}")
            try:
                native = bounded.decode_frame_bounded(
                    path,
                    decoder,
                    args.scratch_root.expanduser().resolve(),
                    frame,
                    timeout_s=float(args.decoder_timeout_s),
                    max_log_bytes=int(args.max_decoder_log_bytes),
                    max_scratch_bytes=int(args.max_decoder_scratch_bytes),
                )
                header = {
                    name: header_observer.native_scalar(
                        name,
                        native["metadata"],
                        native["info"],
                        required=name == "MassFluid",
                    )
                    for name in ("MassFluid", "MassBound", "Rhop0", "Dp", "H", "PeriMode")
                }
                mass_values.append(float(header["MassFluid"]["value"]))
                obs = _observable(native, source, header, float(rows[frame]["time_s"]))
                obs["source_file"] = {"path": str(path), "bytes": pre["bytes"], "sha256": pre["sha256"]}
                observations.append(obs)
            finally:
                post = bounded.checked_hash(path, f"post_decode_frame_{frame}")
                bounded.compare_decode_boundaries(pre, post)
                records.append({"frame": frame, "path": str(path), "pre_decode": pre, "post_decode": post})
    finally:
        bounded._restore_signal_cleanup(previous_handlers)
    if not mass_values or len(set(mass_values)) != 1:
        raise base.UnsupportedSemantics("native MassFluid changed or was not exposed across missing frames")
    output_value = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "family_id": "F4",
        "sentinel_id": "F4-S1",
        "run_label": spec["run_label"],
        "physical_case_id": spec["physical_case_id"],
        "scope": {
            "selected_missing_frames_only": True,
            "selected_frame_count": len(selected),
            "existing_observer_frames_not_redecoded": spec["existing_frame_ids"],
            "full_runparts_frame_count": len(rows),
            "full_native_tree_scanned": False,
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "particle_field_interpolation": "NOT_PERFORMED",
            "native_payload_read_after_parent_reservation": True,
        },
        "source": {
            "raw_root": str(raw_root),
            "runparts": small_records["runparts"],
            "generated_xml": small_records["generated_xml"],
            "decoder": small_records["decoder"],
            "decoder_source": small_records["decoder_source"],
            "decoder_interface": decoder_contract,
            "existing_observer": small_records["existing_observer"],
            "selected_frames": selected,
            "selected_part_records": records,
            "planned_stat_source": "builder stat only; parent/worker pre-hash is authoritative",
        },
        "native_header_summary": {
            "massfluid_kg": mass_values[0],
            "massfluid_exact_across_selected_frames": True,
            "mass_source": "official BI4 decoder metadata, never XML fallback",
            "mass_semantics": "native header MassFluid times XML typed fluid count; discrete sample diagnostic only",
            "continuum_owner_mass": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
            "rigid_body_mass_inertia": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SUM",
        },
        "units_contract": {
            "time": "seconds from RunPARTs and decoder TimeStep",
            "position": "metres as decoded Pos/Posd",
            "velocity": "metres_per_second as decoded Vel",
            "density": "kg_per_m3 as decoded Rhop",
            "mass": "kg from official native MassFluid header",
            "pressure_eos": "UNKNOWN_NOT_DECODED",
        },
        "time_window": {
            "first_saved_time_s": rows[0]["time_s"],
            "last_saved_time_s": rows[-1]["time_s"],
            "query_windows": query_windows,
            "no_extrapolation": True,
            "saved_time_source": "actual RunPARTs.csv plus decoder TimeStep per selected missing frame",
        },
        "observations": observations,
        "decoder_resource_policy": {
            "per_frame_timeout_s": float(args.decoder_timeout_s),
            "process_group_cancel": "SIGTERM_then_SIGKILL_then_wait",
            "parent_death_signal": "PR_SET_PDEATHSIG_SIGTERM_best_effort",
            "max_decoder_log_bytes": int(args.max_decoder_log_bytes),
            "max_decoder_scratch_bytes": int(args.max_decoder_scratch_bytes),
            "scratch_retained_after_frame": False,
        },
        "scientific_qualification": {
            "QI": "PASS_LIMITED_SELECTED_NATIVE_FIELDS",
            "QN": "UNKNOWN_TIME_OUTPUT_AND_SPATIAL_REFERENCE",
            "QE": "UNKNOWN_NO_REGISTERED_CHARACTERISTIC_EVENT_TIME",
            "scope_note": "QI covers source stability, decoder fields, finite values, IDs, native mass consistency, and RunPART time correspondence only.",
        },
    }
    _atomic_json(output, output_value)
    return output_value


def self_test() -> dict[str, Any]:
    cases = base.manufactured_semantic_selftests()
    assert cases["status"] == "PASS"
    assert bounded.DEFAULT_MAX_LOG_BYTES == 64 * 1024
    assert bounded.DEFAULT_MAX_SCRATCH_BYTES == 256 * 1024 * 1024
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "decoder_launch": False,
        "native_payload_read": False,
        "reuses_bounded_v2": True,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--decoder-timeout-s", type=float, default=bounded.DEFAULT_DECODER_TIMEOUT_S)
    parser.add_argument("--max-decoder-log-bytes", type=int, default=bounded.DEFAULT_MAX_LOG_BYTES)
    parser.add_argument("--max-decoder-scratch-bytes", type=int, default=bounded.DEFAULT_MAX_SCRATCH_BYTES)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (args.spec, args.output, args.scratch_root)
    if any(value is None for value in required):
        parser.error("--spec, --output, and --scratch-root are required unless --self-test is used")
    try:
        result = run(args)
    except base.UnsupportedSemantics as exc:
        try:
            result = _unknown(args.output.resolve(), str(exc))
        except FileExistsError:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(f"missing native observer failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "selected_frames": len(result["observations"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
