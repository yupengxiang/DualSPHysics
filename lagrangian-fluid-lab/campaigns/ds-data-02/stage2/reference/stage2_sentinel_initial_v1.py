#!/usr/bin/env python3
"""Check the F2-S1 native and typed initial state at frame zero.

This narrow Stage2 audit binds one exact row from ``CURRENT336.json`` to the
producer's conversion report, decodes only ``Part_0000.bi4`` with the decoder
named by that report, and reads only HDF5 frame zero.  It does not scan the
raw tree, walk the trajectory, run PartVTK, or start a solver.  A typed
trajectory SHA is therefore recorded from the producer report and its file
stat, rather than recomputed here.

The result is an initial-state equivalence receipt.  It does not grant QI,
QN, QE, or a production claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any, Mapping

import h5py
import numpy as np


SCHEMA = "ds02.stage2.f2-s1.initial-frame-equivalence.v1"
CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
TOLERANCES = {
    "position": 1.0e-6,
    "velocity": 1.0e-6,
    "density": 1.0e-3,
    "mass": 1.0e-7,
    "pressure": 5.0e-2,
    "time": 5.0e-5,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def scalar(element: ET.Element) -> Any:
    value = element.get("v")
    if value is None:
        return None
    tag = element.tag.lower().split("}")[-1]
    if tag in {"bool", "boolean"}:
        return value.lower() in {"1", "true", "yes"}
    if tag in {"int", "uint", "int32", "uint32", "int64", "uint64", "long"}:
        try:
            return int(value)
        except ValueError:
            return value
    if tag in {"float", "double", "real"}:
        try:
            return float(value)
        except ValueError:
            return value
    return value


def named_values(node: ET.Element | None) -> dict[str, Any]:
    if node is None:
        return {}
    return {child.get("name"): scalar(child) for child in node if child.get("name")}


def read_current_row(current_path: Path) -> dict[str, Any]:
    current = load_json(current_path)
    matches = [row for row in current.get("cases", []) if row.get("physical_case_id") == CASE_ID]
    if len(matches) != 1:
        raise ValueError(f"CURRENT336 must contain exactly one {CASE_ID!r}; got {len(matches)}")
    row = matches[0]
    if row.get("family_id") != "F2":
        raise ValueError("F2-S1 row has an unexpected family")
    return row


def resolve_source(provenance: Mapping[str, Any], key: str) -> Path:
    value = provenance.get("sources", {}).get(key, {}).get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"small provenance lacks sources.{key}.path")
    return Path(value)


def verify_small_provenance(current_path: Path, provenance_path: Path, row: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    provenance = load_json(provenance_path)
    if provenance.get("schema") != "ds02.stage2.f2-s1.initial-frame-smallprovenance.v1":
        raise ValueError("unexpected small provenance schema")
    if provenance.get("physical_case_id") != CASE_ID:
        raise ValueError("small provenance physical case does not match F2-S1")
    current_expected = provenance.get("sources", {}).get("current336", {}).get("path")
    if Path(current_expected).resolve() != current_path.resolve():
        raise ValueError("small provenance CURRENT336 path does not match invocation")
    generated_xml = Path(row["source_bindings"]["generated_xml"]["path"])
    report_generated = Path(report["source_provenance"]["generated_xml"]["path"])
    if generated_xml.resolve() != report_generated.resolve():
        raise ValueError("CURRENT generated XML and conversion-report XML differ")
    report_hdf5 = Path(report["output_hdf5"])
    if report_hdf5.resolve() != resolve_source(provenance, "typed_hdf5").resolve():
        raise ValueError("small provenance typed HDF5 path does not match conversion report")
    raw_root = Path(row["raw_root"]["path"])
    report_raw = Path(report["source_provenance"]["data_root"])
    if raw_root.resolve() != report_raw.resolve():
        raise ValueError("CURRENT raw root and conversion-report raw root differ")
    paths = {
        "current336": current_path,
        "generated_xml": generated_xml,
        "conversion_report": resolve_source(provenance, "conversion_report"),
        "decoder": Path(report["source_provenance"]["decoder"]["path"]),
        "native_frame0": raw_root / "Part_0000.bi4",
        "typed_hdf5": report_hdf5,
    }
    checks: dict[str, Any] = {}
    for key, path in paths.items():
        declared = provenance.get("sources", {}).get(key, {})
        actual = {"path": str(path), "exists": path.is_file()}
        declared_path = declared.get("path")
        if declared_path and Path(declared_path).resolve() != path.resolve():
            actual["path_match"] = False
            actual["status"] = "FAIL"
            checks[key] = actual
            continue
        actual["path_match"] = True
        if not path.is_file():
            actual["status"] = "UNKNOWN"
            checks[key] = actual
            continue
        # The 1.2 GB trajectory is intentionally stat/provenance bound only.
        if key == "typed_hdf5":
            stat = path.stat()
            actual.update(
                bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                producer_declared_sha256=report.get("output_sha256"),
                declared_bytes=declared.get("bytes"),
            )
            actual["status"] = "PASS" if (
                report.get("output_sha256") == declared.get("producer_declared_sha256")
                and stat.st_size == declared.get("bytes")
            ) else "FAIL"
        else:
            actual_sha = sha256_file(path)
            actual.update(sha256=actual_sha, declared_sha256=declared.get("sha256"))
            actual["status"] = "PASS" if actual_sha == declared.get("sha256") else "FAIL"
        checks[key] = actual
    return {
        "status": "PASS" if all(item.get("status") == "PASS" for item in checks.values()) else "FAIL",
        "checks": checks,
        "hdf5_hash_policy": "producer_declared_sha256_plus_stat; full trajectory rehash intentionally omitted",
    }


def parse_particle_blocks(generated_xml: Path) -> list[dict[str, Any]]:
    root = ET.parse(generated_xml).getroot()
    particles = root.find(".//execution/particles") or root.find(".//particles")
    if particles is None:
        raise ValueError("generated XML lacks execution/particles")
    type_by_tag = {"fixed": 0, "moving": 1, "floating": 2, "fluid": 3}
    blocks = []
    for child in particles:
        if child.tag not in type_by_tag:
            continue
        blocks.append({
            "begin": int(child.attrib["begin"]),
            "count": int(child.attrib["count"]),
            "mk": int(child.attrib["mk"]),
            "type": type_by_tag[child.tag],
            "tag": child.tag,
        })
    if not blocks:
        raise ValueError("generated XML has no typed particle blocks")
    return sorted(blocks, key=lambda item: item["begin"])


def assign_types(ids: np.ndarray, blocks: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    types = np.full(ids.size, -1, dtype=np.int8)
    mks = np.full(ids.size, -1, dtype=np.int16)
    covered = np.zeros(ids.size, dtype=bool)
    for block in blocks:
        selected = (ids >= block["begin"]) & (ids < block["begin"] + block["count"])
        if np.any(covered[selected]):
            raise ValueError("overlapping typed ranges")
        types[selected] = block["type"]
        mks[selected] = block["mk"]
        covered[selected] = True
    if not np.all(covered):
        raise ValueError(f"typed blocks leave IDs unclassified: {ids[~covered][:5].tolist()}")
    return types, mks


def decode_frame_zero(native_frame: Path, decoder: Path, work_root: Path) -> dict[str, Any]:
    """Run the producer-named decoder once, on Part_0000 only."""
    prefix = work_root / "frame_0000"
    command = [str(decoder), str(native_frame), str(prefix)]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    xml_path = Path(str(prefix) + ".xml")
    if not xml_path.is_file():
        raise RuntimeError(f"decoder did not produce {xml_path}")
    root = ET.parse(xml_path).getroot()
    outer = root.find("item")
    particle = root.find(".//item/item")
    metadata = named_values(outer)
    info = named_values(particle)
    if particle is None or not particle.get("name"):
        raise RuntimeError("decoder XML lacks particle item")
    data_root = work_root / "frame_0000" / str(particle.get("name"))
    ids_path = data_root / "Idp.bin"
    pos_path = data_root / "Pos.bin"
    pos_dtype = np.float32
    if not pos_path.is_file():
        pos_path = data_root / "Posd.bin"
        pos_dtype = np.float64
    velocity_path = data_root / "Vel.bin"
    density_path = data_root / "Rhop.bin"
    if not all(path.is_file() for path in (ids_path, pos_path, velocity_path, density_path)):
        raise RuntimeError(f"decoder output is incomplete: {data_root}")
    ids_unsorted = np.fromfile(ids_path, dtype=np.uint32)
    order = np.argsort(ids_unsorted, kind="mergesort")
    if ids_unsorted.size == 0 or np.unique(ids_unsorted).size != ids_unsorted.size:
        raise RuntimeError("native frame has an empty or duplicate Idp axis")
    n = ids_unsorted.size
    position = np.fromfile(pos_path, dtype=pos_dtype).reshape(n, 3)[order].astype(np.float32, copy=False)
    velocity = np.fromfile(velocity_path, dtype=np.float32).reshape(n, 3)[order]
    density = np.fromfile(density_path, dtype=np.float32)[order]
    raw_time = info.get("TimeStep")
    if raw_time is None or not math.isfinite(float(raw_time)):
        raise RuntimeError("native frame has no finite TimeStep")
    return {
        "command": command,
        "decoder_stdout": completed.stdout[-2000:],
        "decoder_stderr": completed.stderr[-2000:],
        "metadata": metadata,
        "info": info,
        "ids": ids_unsorted[order],
        "position": position,
        "velocity": velocity,
        "density": density,
        "time": float(raw_time),
        "zone": int(metadata.get("Piece", 0)),
        "decoder_xml_sha256": sha256_file(xml_path),
    }


def compare_arrays(name: str, raw: np.ndarray, typed: np.ndarray, tolerance: float, *, exact: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "raw_shape": list(raw.shape),
        "typed_shape": list(typed.shape),
        "tolerance": tolerance,
        "exact_required": exact,
    }
    if raw.shape != typed.shape:
        result.update(status="FAIL", reason="shape_mismatch")
        return result
    raw_f = np.asarray(raw)
    typed_f = np.asarray(typed)
    finite = np.isfinite(raw_f).all() and np.isfinite(typed_f).all()
    result["finite"] = bool(finite)
    if not finite:
        result.update(status="FAIL", reason="non_finite_value")
        return result
    diff = np.abs(raw_f.astype(np.float64) - typed_f.astype(np.float64))
    result["max_abs_error"] = float(np.max(diff)) if diff.size else 0.0
    result["rmse"] = float(np.sqrt(np.mean(np.square(diff)))) if diff.size else 0.0
    result["exact"] = bool(np.array_equal(raw_f, typed_f))
    passed = result["exact"] if exact else result["max_abs_error"] <= tolerance
    result["status"] = "PASS" if passed else "FAIL"
    return result


def type_mass_summary(types: np.ndarray, mass: np.ndarray) -> dict[str, Any]:
    return {
        str(int(kind)): {
            "count": int(np.sum(types == kind)),
            "mass_kg": float(np.sum(mass[types == kind], dtype=np.float64)),
        }
        for kind in sorted(set(int(item) for item in types.tolist()))
    }


def run_check(current_path: Path, provenance_path: Path, output_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    row = read_current_row(current_path)
    report_path = Path(row["conversion_report"]["path"])
    report = load_json(report_path)
    source_check = verify_small_provenance(current_path, provenance_path, row, report)
    generated_xml = Path(row["source_bindings"]["generated_xml"]["path"])
    native_frame = Path(row["raw_root"]["path"]) / "Part_0000.bi4"
    typed_hdf5 = Path(report["output_hdf5"])
    decoder = Path(report["source_provenance"]["decoder"]["path"])
    blocks = parse_particle_blocks(generated_xml)
    with tempfile.TemporaryDirectory(prefix="ds02-f2s1-frame0-") as temporary:
        raw = decode_frame_zero(native_frame, decoder, Path(temporary))

    raw_types, raw_mks = assign_types(raw["ids"], blocks)
    mass_fluid = float(raw["metadata"]["MassFluid"])
    mass_bound = float(raw["metadata"]["MassBound"])
    raw_mass = np.where(raw_types == 3, mass_fluid, mass_bound).astype(np.float32)
    b_value = float(raw["metadata"]["B"])
    rhop0 = float(raw["metadata"]["Rhop0"])
    gamma = float(raw["metadata"]["Gamma"])
    raw_pressure = (b_value * ((raw["density"].astype(np.float64) / rhop0) ** gamma - 1.0)).astype(np.float32)

    with h5py.File(typed_hdf5, "r") as h5:
        typed = {
            "ids": np.asarray(h5["particle_id"][:]),
            "zone": np.asarray(h5["particle_zone"][:]),
            "position": np.asarray(h5["position"][0, :, :]),
            "velocity": np.asarray(h5["velocity"][0, :, :]),
            "density": np.asarray(h5["density"][0, :]),
            "mass": np.asarray(h5["mass"][0, :]),
            "pressure": np.asarray(h5["pressure"][0, :]),
            "type": np.asarray(h5["type"][0, :]),
            "mk": np.asarray(h5["mk"][0, :]),
            "valid": np.asarray(h5["valid"][0, :]),
            "initial_type": np.asarray(h5["initial_type"][:]),
            "initial_mk": np.asarray(h5["initial_mk"][:]),
            "initial_mass": np.asarray(h5["initial_mass"][:]),
            "time": float(h5["time"][0]),
            "schema": str(h5.attrs.get("schema", "UNKNOWN")),
        }

    n = int(raw["ids"].size)
    identity_raw_zone = np.full(n, raw["zone"], dtype=np.int16)
    fields = {
        "identity_idp": compare_arrays("identity_idp", raw["ids"], typed["ids"], 0.0, exact=True),
        "identity_zone": compare_arrays("identity_zone", identity_raw_zone, typed["zone"], 0.0, exact=True),
        "type": compare_arrays("type", raw_types, typed["type"], 0.0, exact=True),
        "mk": compare_arrays("mk", raw_mks, typed["mk"], 0.0, exact=True),
        "position": compare_arrays("position", raw["position"], typed["position"], TOLERANCES["position"]),
        "velocity": compare_arrays("velocity", raw["velocity"], typed["velocity"], TOLERANCES["velocity"]),
        "density": compare_arrays("density", raw["density"], typed["density"], TOLERANCES["density"]),
        "mass": compare_arrays("mass", raw_mass, typed["mass"], TOLERANCES["mass"]),
        "pressure_eos": compare_arrays("pressure_eos", raw_pressure, typed["pressure"], TOLERANCES["pressure"]),
        "initial_type": compare_arrays("initial_type", typed["type"], typed["initial_type"], 0.0, exact=True),
        "initial_mk": compare_arrays("initial_mk", typed["mk"], typed["initial_mk"], 0.0, exact=True),
        "initial_mass": compare_arrays("initial_mass", typed["mass"], typed["initial_mass"], TOLERANCES["mass"]),
    }
    fields["valid"] = {
        "status": "PASS" if bool(np.all(typed["valid"])) else "FAIL",
        "count": int(typed["valid"].size),
        "valid_count": int(np.sum(typed["valid"])),
    }
    time_error = abs(raw["time"] - typed["time"])
    fields["time"] = {
        "status": "PASS" if time_error <= TOLERANCES["time"] else "FAIL",
        "raw_s": raw["time"],
        "typed_s": typed["time"],
        "abs_error_s": time_error,
        "tolerance_s": TOLERANCES["time"],
    }
    fields_status = {name: value.get("status", "UNKNOWN") for name, value in fields.items()}
    overall = "PASS" if source_check["status"] == "PASS" and all(value == "PASS" for value in fields_status.values()) else "FAIL"
    partvtk_frames = report.get("partvtk_validation", {}).get("frames", [])
    partvtk_frame0 = next((frame for frame in partvtk_frames if frame.get("frame") == 0), None)
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": overall,
        "scientific_acceptance": {"QI": "NOT_ASSESSED", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
        "scope": {
            "physical_case_id": CASE_ID,
            "frame_index": 0,
            "raw_read": "Part_0000.bi4 only",
            "typed_read": "HDF5 datasets at index 0 only",
            "full_time_scan": False,
            "raw_tree_scan": False,
            "solver_started": False,
            "partvtk_started": False,
        },
        "inputs": {
            "current336": {"path": str(current_path), "sha256": sha256_file(current_path)},
            "small_provenance": {"path": str(provenance_path), "sha256": sha256_file(provenance_path)},
            "generated_xml": {"path": str(generated_xml), "sha256": sha256_file(generated_xml)},
            "conversion_report": {"path": str(report_path), "sha256": sha256_file(report_path)},
            "native_frame0": {"path": str(native_frame), "sha256": sha256_file(native_frame), "bytes": native_frame.stat().st_size},
            "decoder": {"path": str(decoder), "sha256": sha256_file(decoder)},
            "typed_hdf5": {
                "path": str(typed_hdf5),
                "producer_declared_sha256": report.get("output_sha256"),
                "bytes": typed_hdf5.stat().st_size,
                "mtime_ns": typed_hdf5.stat().st_mtime_ns,
                "full_rehash": "OMITTED_BY_SCOPE",
            },
        },
        "source_binding_check": source_check,
        "decoder": {
            "argv_shape": [str(decoder), str(native_frame), "<temporary-prefix>"],
            "reported_zone_piece": raw["zone"],
            "metadata_constants": {key: raw["metadata"].get(key) for key in ("Dp", "MassFluid", "MassBound", "Rhop0", "Gamma", "B")},
            "decoded_particles": n,
            "decoder_xml_sha256": raw["decoder_xml_sha256"],
        },
        "typed": {
            "hdf5_schema": typed["schema"],
            "particles": int(typed["ids"].size),
            "frames_declared": report.get("frames"),
            "initial_identity_key": report.get("typed_identity", {}).get("key", "UNKNOWN"),
            "blocks_from_generated_xml": blocks,
        },
        "field_checks": fields,
        "field_status": fields_status,
        "mass_summary_raw": type_mass_summary(raw_types, raw_mass),
        "mass_summary_typed": type_mass_summary(typed["type"], typed["mass"]),
        "partvtk_report_frame0_crosscheck": partvtk_frame0 if partvtk_frame0 is not None else "UNKNOWN",
        "resource": {
            "elapsed_wall_seconds": time.monotonic() - started,
            "self_user_seconds": usage_after.ru_utime - usage_before.ru_utime,
            "self_system_seconds": usage_after.ru_stime - usage_before.ru_stime,
            "max_rss_kib": usage_after.ru_maxrss,
        },
        "unknowns": [
            "typed HDF5 full-byte hash was not recomputed; producer hash and stat are bound",
            "this receipt says nothing about frames after frame zero",
            "this receipt says nothing about numerical convergence or QN/QE",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=json_default) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_check(args.current, args.provenance, args.output)
    except Exception as error:  # dispatch receipt captures the reproducible failure
        failure = {
            "schema": SCHEMA,
            "status": "FAILED",
            "scientific_acceptance": {"QI": "NOT_ASSESSED", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
            "error_type": type(error).__name__,
            "error": str(error),
            "scope": {"frame_index": 0, "full_time_scan": False, "solver_started": False},
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(failure, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False), flush=True)
        return 2
    print(json.dumps({"status": result["status"], "output": str(args.output), "field_status": result["field_status"]}, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
