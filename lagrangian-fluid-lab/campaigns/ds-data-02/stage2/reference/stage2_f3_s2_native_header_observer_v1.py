#!/usr/bin/env python3
"""Decode selected F3 frames and audit the native BI4 MassFluid header.

``stage2_native_physical_observer_v2.py`` uses the generated XML mass
constant when it forms weighted observables.  That is useful for geometry
classification, but it does not prove that the value encoded in each native
BI4 header agrees with the XML.  This adapter is a forward-only child for
the ROOT139 source-manifest/enforcer chain: it reuses the official
``bi4_dump`` decoder, reads only the selected frames, and requires the
decoder-produced outer metadata to expose ``MassFluid``.  ``MassBound`` is
reported when exposed, but its absence remains explicit UNKNOWN and never
causes an XML fallback.

The result reports the native header values and their binary64 representation
as supplied by the decoder's XML scalar.  It never substitutes an XML value
when a native header field is absent.  Continuum mass, rigid-body mass,
pressure/EOS, and QI/QN/QE remain UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Any

import numpy as np

import stage2_native_physical_observer_v2 as base


SCHEMA = "ds02.stage2.f3-s2.native-header-observer.v1"
PASS_STATUS = "PASS_DECODED_SELECTED_NATIVE_FIELDS"


def _value(values: dict[str, Any], name: str) -> tuple[Any, str | None]:
    for key, value in values.items():
        if str(key).lower() == name.lower():
            return value, str(key)
    return None, None


def native_scalar(name: str, metadata: dict[str, Any], info: dict[str, Any], *, required: bool = True) -> dict[str, Any]:
    """Require a native decoder scalar and preserve its numeric bit view."""

    value, key = _value(metadata, name)
    section = "metadata"
    if key is None:
        value, key = _value(info, name)
        section = "particle_info"
    if key is None and not required:
        return {
            "field": name,
            "decoder_key": None,
            "decoder_section": None,
            "value": "UNKNOWN_NOT_EXPOSED_BY_DECODER",
            "semantics": "native_bi4_header_scalar_not_exposed",
        }
    if key is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise base.UnsupportedSemantics(f"native BI4 decoder did not expose numeric {name}")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise base.UnsupportedSemantics(f"native BI4 decoder exposed non-finite {name}={value!r}")
    return {
        "field": name,
        "decoder_key": key,
        "decoder_section": section,
        "value": numeric,
        "value_float_hex": numeric.hex(),
        "value_binary64_little_endian_hex": struct.pack("<d", numeric).hex(),
        "semantics": "native_bi4_header_scalar_from_official_decoder_xml",
    }


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
        digest.update(json.dumps(list(array.shape)).encode("ascii"))
        digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _observable(decoded: dict[str, Any], source: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    ids = decoded["ids"]
    kind, mkfluid, mk_absolute = base.assign_particle_ranges(ids, source["blocks"])
    if not (np.isfinite(decoded["position"]).all() and np.isfinite(decoded["velocity"]).all() and np.isfinite(decoded["density"]).all()):
        raise base.UnsupportedSemantics("selected native fields contain NaN/Inf")
    fluid = kind == "fluid"
    fluid_count = int(fluid.sum())
    mass = float(header["MassFluid"]["value"])
    position = decoded["position"][fluid]
    velocity = decoded["velocity"][fluid]
    if fluid_count:
        weights = np.full(fluid_count, mass, dtype=np.float64)
        weighted_centroid = np.average(position, axis=0, weights=weights)
        weighted_velocity = np.average(velocity, axis=0, weights=weights)
        kinetic_energy = float(0.5 * mass * np.sum(np.square(velocity), dtype=np.float64))
    else:
        weighted_centroid = weighted_velocity = None
        kinetic_energy = None
    return {
        "frame": int(decoded["frame"]),
        "decoded_time_s": float(decoded["decoded_time_s"]),
        "field_digest_sha256": _field_digest(decoded),
        "position_dtype": decoded["position_dtype"],
        "finite_fields": {
            "Idp": bool(np.isfinite(ids).all()),
            "Pos_or_Posd": bool(np.isfinite(decoded["position"]).all()),
            "Vel": bool(np.isfinite(decoded["velocity"]).all()),
            "Rhop": bool(np.isfinite(decoded["density"]).all()),
            "status": "PASS_FINITE",
        },
        "identity": {
            "status": "PASS_XML_TYPED_RANGE_COVERAGE",
            "particle_count": int(ids.size),
            "id_min": int(ids.min()),
            "id_max": int(ids.max()),
            "id_unique": bool(np.unique(ids).size == ids.size),
            "mkfluid_relative_values": sorted(set(int(value) for value in mkfluid[kind == "fluid"].tolist())),
            "mk_absolute_values": sorted(set(int(value) for value in mk_absolute[kind == "fluid"].tolist())),
        },
        "native_header": header,
        "fluid_observable_using_native_header_mass": {
            "fluid_count": fluid_count,
            "sample_mass_kg": float(fluid_count * mass),
            "weighted_centroid_m": None if weighted_centroid is None else [float(value) for value in weighted_centroid],
            "weighted_velocity_m_per_s": None if weighted_velocity is None else [float(value) for value in weighted_velocity],
            "kinetic_energy_j": kinetic_energy,
            "mass_semantics": "native_bi4_header_MassFluid_times_decoded_fluid_count",
        },
        "xml_mass_constant_not_used_for_sample_mass": True,
    }


def _unknown_sidecar(output: Path, reason: str) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": "UNKNOWN_UNSUPPORTED_SEMANTICS",
        "reason": reason,
        "field_observables": "UNKNOWN",
        "native_header_mass": "UNKNOWN",
        "typed_conversion": "NOT_PERFORMED",
        "hdf5_read": False,
        "solver_launch": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    base.atomic_json(output, value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = args.raw_root.resolve()
    runparts = args.runparts.resolve()
    source_xml = args.generated_xml.resolve()
    decoder = args.decoder.resolve()
    decoder_source = args.decoder_source.resolve()
    output = args.output.resolve()
    if not raw_root.is_dir():
        raise ValueError(f"native raw root is missing: {raw_root}")
    if not decoder.is_file() or not decoder.exists():
        raise ValueError(f"official decoder is missing: {decoder}")
    decoder_contract = base.decoder_source_contract(decoder_source)
    if decoder_contract["status"] == "UNKNOWN_DECODER_SOURCE_CONTRACT":
        raise base.UnsupportedSemantics("decoder source does not prove the argc=3 input/output-prefix contract")
    rows = base.read_runparts(runparts)
    if len(rows) != args.expected_frame_count:
        raise ValueError(f"RunPARTs rows {len(rows)} != expected {args.expected_frame_count}")
    if abs(rows[-1]["time_s"] - args.expected_final_time_s) > args.final_time_tolerance_s:
        raise ValueError(f"RunPARTs final time {rows[-1]['time_s']} differs from expected {args.expected_final_time_s}")
    source = base.parse_source_xml(source_xml)
    brackets = [base.time_bracket(rows, float(query)) for query in args.query_times]
    required: set[int] = set()
    for bracket in brackets:
        if bracket["status"] in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
            required.add(int(bracket["lower_frame"]))
            required.add(int(bracket["upper_frame"]))
    selected = sorted(set(int(frame) for frame in args.frames))
    if not selected or not required.issubset(set(selected)):
        raise ValueError(f"selected frames do not cover registered query brackets: selected={selected} required={sorted(required)}")
    if any(frame < 0 or frame >= len(rows) for frame in selected):
        raise ValueError(f"selected frame outside RunPARTs: {selected}")

    decoded: list[dict[str, Any]] = []
    for frame in selected:
        native = base.decode_frame(raw_root / f"Part_{frame:04d}.bi4", decoder, args.scratch_root.resolve(), frame)
        header = {
            name: native_scalar(name, native["metadata"], native["info"], required=name == "MassFluid")
            for name in ("MassFluid", "MassBound", "Rhop0", "Dp", "H", "PeriMode")
        }
        decoded.append({
            "saved_file": native["saved_file"],
            "observation": _observable(native, source, header),
            "dynamic_semantics": native["dynamic_semantics"],
            "decoder_xml_sha256": native["decoder_xml_sha256"],
        })

    mass_values = [item["observation"]["native_header"]["MassFluid"]["value"] for item in decoded]
    bound_values = [item["observation"]["native_header"]["MassBound"]["value"] for item in decoded]
    if len(set(mass_values)) != 1:
        raise base.UnsupportedSemantics("native MassFluid changed across selected frames")
    numeric_bound_values = [value for value in bound_values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if numeric_bound_values and len(numeric_bound_values) != len(bound_values):
        raise base.UnsupportedSemantics("native MassBound is exposed inconsistently across selected frames")
    if numeric_bound_values and len(set(numeric_bound_values)) != 1:
        raise base.UnsupportedSemantics("native MassBound changed across selected frames")
    massbound_exact: bool | str = True if numeric_bound_values else "UNKNOWN_NOT_EXPOSED_BY_DECODER"
    payload = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "scope": {
            "selected_frames_only": True,
            "selected_frame_count": len(selected),
            "runparts_frame_count": len(rows),
            "full_native_tree_scanned": False,
            "full_native_tree_sha256": "NOT_COMPUTED_BY_WORKER",
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "particle_field_interpolation": "NOT_PERFORMED",
            "native_header_mass_audited": True,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source": {
            "raw_root": str(raw_root),
            "runparts": base.file_record(runparts),
            "generated_xml": base.file_record(source_xml),
            "decoder": base.file_record(decoder),
            "decoder_interface": decoder_contract,
            "particle_range_semantics": source,
            "selected_frames": selected,
            "selected_part_records": [item["saved_file"] for item in decoded],
        },
        "time_window": {
            "first_saved_time_s": rows[0]["time_s"],
            "last_saved_time_s": rows[-1]["time_s"],
            "queries": brackets,
            "out_of_window_policy": "UNKNOWN; no extrapolation",
        },
        "native_header_contract": {
            "massfluid": "required native BI4 outer-header scalar; XML source constant is not substituted",
            "massbound": "optional native BI4 outer-header scalar; absent is explicit UNKNOWN",
            "rhop0_dp_h_perimode": "reported from decoder metadata when exposed; missing field is UNKNOWN/failure",
            "source_basis": "JPartDataBi4 MassFluid/MassBound metadata, read through official bi4_dump output",
        },
        "observations": [item["observation"] | {"dynamic_semantics": item["dynamic_semantics"], "decoder_xml_sha256": item["decoder_xml_sha256"]} for item in decoded],
        "native_header_summary": {
            "selected_massfluid_kg": mass_values[0],
            "selected_massbound_kg": bound_values[0] if numeric_bound_values else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
            "massfluid_exact_across_selected_frames": True,
            "massbound_exact_across_selected_frames": massbound_exact,
            "sample_mass_role": "native_header_mass_times_decoded_fluid_count; discrete diagnostic only",
            "continuum_owner_mass": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
            "rigid_body_mass_inertia": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SAMPLE",
        },
        "manufactured_semantic_selftests": "NOT_REPEATED; official base decoder contract bound",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    base.atomic_json(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--runparts", type=Path, required=True)
    parser.add_argument("--generated-xml", type=Path, required=True)
    parser.add_argument("--decoder", type=Path, required=True)
    parser.add_argument("--decoder-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--expected-frame-count", type=int, required=True)
    parser.add_argument("--expected-final-time-s", type=float, required=True)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1.0e-12)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument("--query-times", type=float, nargs="+", required=True)
    args = parser.parse_args()
    try:
        result = run(args)
    except base.UnsupportedSemantics as exc:
        result = _unknown_sidecar(args.output.resolve(), str(exc))
    except Exception as exc:
        print(f"native header audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "selected_frames": result.get("scope", {}).get("selected_frame_count", 0)}, ensure_ascii=False))
    return 0 if result.get("status") == PASS_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
