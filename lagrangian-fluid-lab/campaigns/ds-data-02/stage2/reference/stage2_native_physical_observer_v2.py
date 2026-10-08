#!/usr/bin/env python3
"""Decode bounded native frames with explicit relative/absolute MK semantics.

This worker is deliberately separate from any hash-only stream observer.  It
decodes only the frame numbers needed to bracket registered
physical query times, using the producer's official ``bi4_dump`` binary, and
then removes each temporary decoder tree before moving to the next frame.  It
does not read HDF5, infer a rigid-body mass from particle samples, interpolate
particle fields, or scan/hash the complete native tree.

The XML particle ranges are read from the exact solver XML supplied to the
worker.  Fluid ``mkfluid`` values remain relative fluid labels and XML ``mk``
values remain absolute MK labels; the two are never merged into one key.  The
worker decodes positions, velocities, density/Rhop and derived sample mass;
pressure/EOS pressure is explicitly reported as not decoded.  If a
decoder/source semantic is unsupported, the output is an explicit
``UNKNOWN`` sidecar.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Iterable

import numpy as np


SCHEMA = "ds02.stage2.native-physical-observer.v2"
CHUNK = 1024 * 1024
TIME_TOLERANCE_S = 1.0e-10


class UnsupportedSemantics(RuntimeError):
    """A real source/decoder condition that must remain UNKNOWN."""


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def file_record(path: Path, *, content_sha256: bool = True) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"required regular file is missing or symlinked: {path}")
    stat = path.stat()
    value: dict[str, Any] = {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if content_sha256:
        value["sha256"], _ = sha256_file(path)
    return value


def atomic_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def scalar_value(element: ET.Element) -> Any:
    raw = element.get("v")
    if raw is None:
        return None
    tag = element.tag.rsplit("}", 1)[-1].lower()
    if tag in {"bool", "boolean"}:
        return raw.lower() in {"1", "true", "yes"}
    if tag in {"int", "uint", "int32", "uint32", "int64", "uint64", "long"}:
        try:
            return int(raw)
        except ValueError:
            return raw
    if tag in {"float", "double", "real"}:
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def named_values(node: ET.Element | None) -> dict[str, Any]:
    if node is None:
        return {}
    return {
        child.get("name"): scalar_value(child)
        for child in node
        if child.get("name")
    }


def _first_float(root: ET.Element, paths: Iterable[str]) -> float | None:
    for path in paths:
        node = root.find(path)
        if node is None:
            continue
        raw = node.get("value")
        if raw is None:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        if math.isfinite(value):
            return value
    return None


def parse_source_xml(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particle_node = root.find(".//particles")
    if particle_node is None:
        raise UnsupportedSemantics("solver XML has no execution/particles node")
    blocks: list[dict[str, Any]] = []
    allowed = {"fixed", "moving", "floating", "fluid"}
    for node in particle_node:
        kind = node.tag.rsplit("}", 1)[-1].lower()
        if kind not in allowed or node.get("begin") is None or node.get("count") is None:
            continue
        try:
            begin = int(node.get("begin", ""))
            count = int(node.get("count", ""))
        except ValueError as exc:
            raise UnsupportedSemantics(f"non-numeric particle block: {ET.tostring(node, encoding='unicode')}") from exc
        if begin < 0 or count <= 0:
            raise UnsupportedSemantics(f"invalid particle block begin/count: {begin}/{count}")
        # DualSPHysics uses ``mkfluid`` as a fluid-relative label and ``mk``
        # as the absolute material label.  They can both be present on a
        # fluid block (often mkfluid=0, mk=1); retaining only one would make
        # relative 0 look like absolute 0 and mixes coordinate systems.
        mkfluid_raw = node.get("mkfluid")
        mk_raw = node.get("mk")
        mkfluid_relative: int | None
        mk_absolute: int | None
        try:
            mkfluid_relative = int(mkfluid_raw) if mkfluid_raw is not None else None
            mk_absolute = int(mk_raw) if mk_raw is not None else None
        except ValueError as exc:
            raise UnsupportedSemantics(
                f"non-numeric particle block mkfluid/mk: {mkfluid_raw}/{mk_raw}"
            ) from exc
        if kind == "fluid" and mkfluid_relative is None:
            raise UnsupportedSemantics("fluid particle block has no mkfluid relative label")
        if mk_absolute is None:
            raise UnsupportedSemantics("particle block has no absolute mk label")
        blocks.append({
            "kind": kind,
            "mkfluid_relative": mkfluid_relative,
            "mk_absolute": mk_absolute,
            "begin": begin,
            "count": count,
            "end_exclusive": begin + count,
            "refmotion": node.get("refmotion"),
        })
    if not blocks:
        raise UnsupportedSemantics("solver XML has no typed particle ranges")
    blocks.sort(key=lambda item: item["begin"])
    previous_end = -1
    for block in blocks:
        if block["begin"] < previous_end:
            raise UnsupportedSemantics("overlapping XML particle ranges")
        previous_end = block["end_exclusive"]

    massfluid = _first_float(root, (".//constants/massfluid", ".//massfluid"))
    massbound = _first_float(root, (".//constants/massbound", ".//massbound"))
    rhop0 = _first_float(root, (".//constants/rhop0", ".//rhop0", ".//constantsdef/rhop0"))
    parameters: dict[str, Any] = {}
    for node in root.findall(".//parameters/parameter"):
        key = node.get("key")
        value = node.get("value")
        if key and value is not None:
            try:
                parameters[key] = float(value)
            except ValueError:
                parameters[key] = value

    # Keep rigid-body declarations separate from particle sample mass.  The
    # parser must preserve a declaration if a source contains one.
    rigid_declarations: list[dict[str, Any]] = []
    for node in root.iter():
        attrs: dict[str, Any] = {}
        for key, value in node.attrib.items():
            key_lower = key.lower()
            if key_lower in {"massbody", "mass", "inertia", "center", "com", "comx", "comy", "comz"}:
                attrs[key] = value
        if attrs:
            rigid_declarations.append({
                "tag": node.tag.rsplit("}", 1)[-1],
                "attributes": attrs,
            })

    return {
        "path": str(path.resolve()),
        "blocks": blocks,
        "constants": {
            "massfluid_kg": massfluid,
            "massbound_kg": massbound,
            "rhop0_kg_m3": rhop0,
        },
        "parameters": parameters,
        "rigid_body_declarations": rigid_declarations,
        "rigid_body_mass_semantics": (
            "DECLARED_IN_XML_BUT_SEPARATE_FROM_PARTICLE_SAMPLE_MASS"
            if rigid_declarations else "UNKNOWN_NOT_DECLARED_IN_SOURCE_XML"
        ),
    }


def _clean_numeric(raw: str | None) -> str | None:
    if raw is None:
        return None
    match = re.match(r"^\s*([^#\s]+)", raw)
    return match.group(1) if match else None


def read_runparts(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        raise ValueError(f"RunPARTs is empty: {path}")
    reader = csv.DictReader(lines, delimiter=";")
    rows: list[dict[str, Any]] = []
    for row in reader:
        cleaned = {(key or "").strip(): (value or "").strip() for key, value in row.items()}
        part_raw = _clean_numeric(cleaned.get("Part"))
        time_raw = _clean_numeric(cleaned.get("TimeStep [s]"))
        if part_raw is None or time_raw is None or not re.match(r"^-?\d+$", part_raw):
            continue
        try:
            part = int(part_raw)
            time_s = float(time_raw)
        except ValueError:
            continue
        if not math.isfinite(time_s):
            raise ValueError(f"non-finite RunPARTs time at Part {part}")
        rows.append({"part": part, "time_s": time_s, "raw": cleaned})
    if not rows:
        raise ValueError(f"RunPARTs has no numeric rows: {path}")
    rows.sort(key=lambda item: item["part"])
    if [item["part"] for item in rows] != list(range(len(rows))):
        raise ValueError("RunPARTs parts are not contiguous from zero")
    times = [item["time_s"] for item in rows]
    if any(right <= left for left, right in zip(times, times[1:])):
        raise ValueError("RunPARTs saved times are not strictly increasing")
    return rows


def time_bracket(rows: list[dict[str, Any]], query: float) -> dict[str, Any]:
    if not math.isfinite(query):
        raise ValueError(f"non-finite physical query time: {query}")
    times = [row["time_s"] for row in rows]
    parts = [row["part"] for row in rows]
    if query < times[0] or query > times[-1]:
        return {
            "query_time_s": query,
            "status": "OUTSIDE_SAVED_WINDOW",
            "reason": "no extrapolation beyond actual saved native interval",
        }
    right = bisect.bisect_left(times, query)
    if right == 0:
        return {
            "query_time_s": query, "status": "EXACT_OR_LEFT",
            "lower_frame": parts[0], "upper_frame": parts[0],
            "lower_time_s": times[0], "upper_time_s": times[0],
        }
    if right == len(times):
        right -= 1
    if abs(times[right] - query) <= TIME_TOLERANCE_S:
        return {
            "query_time_s": query, "status": "EXACT",
            "lower_frame": parts[right], "upper_frame": parts[right],
            "lower_time_s": times[right], "upper_time_s": times[right],
        }
    left = right - 1
    fraction = (query - times[left]) / (times[right] - times[left])
    return {
        "query_time_s": query, "status": "BRACKETED",
        "lower_frame": parts[left], "upper_frame": parts[right],
        "lower_time_s": times[left], "upper_time_s": times[right],
        "interpolation_fraction": fraction,
    }


def _decoder_particle_paths(prefix: Path) -> tuple[dict[str, Any], Path]:
    xml_path = Path(str(prefix) + ".xml")
    if not xml_path.is_file():
        raise UnsupportedSemantics(f"bi4_dump did not produce XML: {xml_path}")
    root = ET.parse(xml_path).getroot()
    outer = root.find("item")
    particle = root.find(".//item/item")
    metadata = named_values(outer)
    info = named_values(particle)
    if particle is None or not particle.get("name"):
        raise UnsupportedSemantics("bi4_dump XML has no particle item")
    data_root = prefix / particle.get("name")
    return {"metadata": metadata, "info": info, "xml_path": xml_path}, data_root


def decode_frame(frame_path: Path, decoder: Path, scratch_root: Path, frame: int) -> dict[str, Any]:
    if not frame_path.is_file() or frame_path.is_symlink():
        raise ValueError(f"selected native frame is not a regular file: {frame_path}")
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"native-frame-{frame:04d}-", dir=scratch_root) as temporary:
        prefix = Path(temporary) / "decoded"
        try:
            completed = subprocess.run(
                [str(decoder), str(frame_path), str(prefix)],
                check=True, capture_output=True, text=True, timeout=300,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or ""
            raise UnsupportedSemantics(f"official BI4 decoder failed for frame {frame}: {detail[-1000:]}") from exc
        decoder_xml, data_root = _decoder_particle_paths(prefix)
        decoder_metadata = {**decoder_xml["metadata"], **decoder_xml["info"]}
        dynamic_semantics: dict[str, Any] = {}
        for key in ("Npiece", "Piece", "NpDynamic", "ReuseIds", "PeriMode"):
            value = decoder_metadata.get(key)
            dynamic_semantics[key] = value if value is not None else "UNKNOWN_NOT_EXPOSED_BY_DECODER"
        for key, expected in (("Npiece", 1), ("Piece", 0), ("NpDynamic", 0), ("ReuseIds", 0), ("PeriMode", 0)):
            value = decoder_metadata.get(key)
            if value is None:
                continue
            try:
                if int(value) != expected:
                    raise UnsupportedSemantics(f"unsupported multi-piece/dynamic decoder field {key}={value}")
            except (TypeError, ValueError) as exc:
                raise UnsupportedSemantics(f"non-numeric decoder semantic field {key}={value!r}") from exc
        ids_path = data_root / "Idp.bin"
        posd_path = data_root / "Posd.bin"
        pos_path = data_root / "Pos.bin"
        velocity_path = data_root / "Vel.bin"
        density_path = data_root / "Rhop.bin"
        if not ids_path.is_file() or not velocity_path.is_file() or not density_path.is_file():
            raise UnsupportedSemantics(f"official decoder lacks Idp/Vel/Rhop for frame {frame}")
        if posd_path.is_file():
            position_path = posd_path
            position_dtype = np.dtype("<f8")
        elif pos_path.is_file():
            position_path = pos_path
            position_dtype = np.dtype("<f4")
        else:
            raise UnsupportedSemantics(f"official decoder lacks Pos or Posd for frame {frame}")

        ids_unsorted = np.fromfile(ids_path, dtype=np.dtype("<u4"))
        if ids_unsorted.size == 0 or np.unique(ids_unsorted).size != ids_unsorted.size:
            raise UnsupportedSemantics(f"empty or duplicate Idp axis in frame {frame}")
        order = np.argsort(ids_unsorted, kind="mergesort")
        count = int(ids_unsorted.size)
        position = np.fromfile(position_path, dtype=position_dtype)
        velocity = np.fromfile(velocity_path, dtype=np.dtype("<f4"))
        density = np.fromfile(density_path, dtype=np.dtype("<f4"))
        try:
            position = position.reshape(count, 3)[order]
            velocity = velocity.reshape(count, 3)[order]
            density = density.reshape(count)[order]
        except ValueError as exc:
            raise UnsupportedSemantics(f"decoder array lengths do not match Idp for frame {frame}") from exc
        ids = ids_unsorted[order]
        if not (np.isfinite(position).all() and np.isfinite(velocity).all() and np.isfinite(density).all()):
            raise UnsupportedSemantics(f"non-finite native field in frame {frame}")

        raw_time = decoder_xml["info"].get("TimeStep")
        try:
            frame_time = float(raw_time)
        except (TypeError, ValueError) as exc:
            raise UnsupportedSemantics(f"decoder frame has no finite TimeStep: {frame}") from exc
        if not math.isfinite(frame_time):
            raise UnsupportedSemantics(f"decoder frame has non-finite TimeStep: {frame}")

        field_digest = hashlib.sha256()
        for name, array in (("Idp", ids), ("Pos", position), ("Vel", velocity), ("Rhop", density)):
            field_digest.update(name.encode("ascii"))
            field_digest.update(str(array.dtype).encode("ascii"))
            field_digest.update(json.dumps(list(array.shape)).encode("ascii"))
            field_digest.update(np.ascontiguousarray(array).tobytes())
        part_sha256, part_bytes = sha256_file(frame_path)
        return {
            "frame": frame,
            "saved_file": {
                "path": str(frame_path.resolve()),
                "bytes": part_bytes,
                "sha256": part_sha256,
            },
            "decoder_xml_sha256": sha256_file(decoder_xml["xml_path"])[0],
            "decoded_time_s": frame_time,
            "field_digest_sha256": field_digest.hexdigest(),
            "ids": ids,
            "position": position,
            "velocity": velocity,
            "density": density,
            "metadata": decoder_xml["metadata"],
            "info": decoder_xml["info"],
            "dynamic_semantics": dynamic_semantics,
            "position_dtype": str(position_dtype),
        }


def assign_particle_ranges(
    ids: np.ndarray, blocks: list[dict[str, Any]]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    kind = np.full(ids.size, "UNKNOWN", dtype=object)
    mkfluid_relative = np.full(ids.size, -1, dtype=np.int64)
    mk_absolute = np.full(ids.size, -1, dtype=np.int64)
    covered = np.zeros(ids.size, dtype=bool)
    for block in blocks:
        selected = (ids >= block["begin"]) & (ids < block["end_exclusive"])
        if np.any(covered[selected]):
            raise UnsupportedSemantics("XML particle ranges overlap on decoded Idp axis")
        kind[selected] = block["kind"]
        if block["mkfluid_relative"] is not None:
            mkfluid_relative[selected] = int(block["mkfluid_relative"])
        if block["mk_absolute"] is not None:
            mk_absolute[selected] = int(block["mk_absolute"])
        covered[selected] = True
    if not np.all(covered):
        missing = ids[~covered]
        raise UnsupportedSemantics(f"XML particle ranges do not cover decoded IDs; first missing IDs={missing[:5].tolist()}")
    return kind, mkfluid_relative, mk_absolute


def finite_stats(values: np.ndarray) -> dict[str, Any]:
    if values.size == 0:
        return {"status": "UNKNOWN_EMPTY", "count": 0}
    return {
        "status": "PASS_FINITE",
        "count": int(values.size),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values, dtype=np.float64)),
        "std": float(np.std(values, dtype=np.float64)),
    }


def decoder_source_contract(path: Path | None) -> dict[str, Any]:
    """Check the repository adapter's real two-argument output contract.

    The native adapter intentionally has no useful ``--help`` mode.  Its
    source is therefore the auditable contract: argc must be three, argv[1]
    is the BI4 input, and argv[2] is the output prefix.  A successful actual
    selected-frame decode below separately proves that this contract worked
    for the supplied F1/native interface.
    """
    if path is None:
        return {
            "status": "UNKNOWN_DECODER_SOURCE_NOT_BOUND",
            "argv_contract": ["decoder", "native_part.bi4", "scratch/decoded"],
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    checks = {
        "argc_exactly_three": "if(argc!=3)return 2" in text,
        "input_is_argv1": "LoadFile(argv[1]" in text,
        "output_xml_uses_argv2": 'SaveFileXml(std::string(argv[2])+".xml"' in text,
        "arrays_dump_uses_argv2": "dump(d,argv[2])" in text,
    }
    return {
        "status": "PASS_SOURCE_ARGC3_OUTPUT_PREFIX_CONTRACT" if all(checks.values()) else "UNKNOWN_DECODER_SOURCE_CONTRACT",
        "source": file_record(path),
        "checks": checks,
        "argv_contract": ["decoder", "native_part.bi4", "scratch/decoded"],
        "help_mode": "NOT_AVAILABLE_BY_ADAPTER; source contract used",
    }


def manufactured_semantic_selftests() -> dict[str, Any]:
    """Exercise boundary cases without reading a native payload."""
    cases: list[dict[str, Any]] = []

    blocks = [
        {"kind": "fixed", "mkfluid_relative": None, "mk_absolute": 10, "begin": 0, "count": 2, "end_exclusive": 2},
        {"kind": "fluid", "mkfluid_relative": 0, "mk_absolute": 1, "begin": 2, "count": 2, "end_exclusive": 4},
    ]
    kinds, relative, absolute = assign_particle_ranges(np.arange(4, dtype=np.uint32), blocks)
    ok = (
        kinds.tolist() == ["fixed", "fixed", "fluid", "fluid"]
        and relative.tolist() == [-1, -1, 0, 0]
        and absolute.tolist() == [10, 10, 1, 1]
        and relative[2] != absolute[2]
    )
    cases.append({
        "name": "relative_mkfluid_zero_is_not_absolute_mk_zero",
        "status": "PASS" if ok else "FAIL",
        "expected": {"fluid_mkfluid_relative": 0, "fluid_mk_absolute": 1},
        "actual": {"mkfluid_relative": relative.tolist(), "mk_absolute": absolute.tolist()},
    })

    frame = {
        "position": np.asarray([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]], dtype=np.float64),
        "velocity": np.asarray([[1.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32),
        "density": np.asarray([1000.0, 1000.0], dtype=np.float32),
    }
    mass_result = group_observable("fluid", 0, 1, np.asarray([True, True]), frame, {"massfluid_kg": 2.5, "massbound_kg": 1.0})
    mass_ok = abs(float(mass_result["sample_mass_kg"]) - 5.0) < 1.0e-12
    velocity_ok = mass_result["weighted_velocity_m_per_s"] == [2.0, 0.0, 0.0]
    cases.append({
        "name": "nonunit_particle_mass_and_velocity_are_not_unit_weighted",
        "status": "PASS" if mass_ok and velocity_ok else "FAIL",
        "expected": {"sample_mass_kg": 5.0, "weighted_velocity_m_per_s": [2.0, 0.0, 0.0]},
        "actual": {"sample_mass_kg": mass_result["sample_mass_kg"], "weighted_velocity_m_per_s": mass_result["weighted_velocity_m_per_s"]},
    })

    rows = [{"part": 0, "time_s": 0.0}, {"part": 1, "time_s": 0.5}, {"part": 2, "time_s": 1.0}]
    bracket_ok = (
        time_bracket(rows, 0.25)["status"] == "BRACKETED"
        and time_bracket(rows, 0.0)["status"] == "EXACT_OR_LEFT"
        and time_bracket(rows, 1.1)["status"] == "OUTSIDE_SAVED_WINDOW"
    )
    try:
        time_bracket(rows, float("nan"))
    except ValueError:
        nonfinite_ok = True
    else:
        nonfinite_ok = False
    cases.append({
        "name": "time_brackets_reject_outside_and_nonfinite_queries",
        "status": "PASS" if bracket_ok and nonfinite_ok else "FAIL",
        "expected": ["EXACT_OR_LEFT", "BRACKETED", "OUTSIDE_SAVED_WINDOW", "ValueError(nonfinite)"],
        "actual": [time_bracket(rows, 0.0)["status"], time_bracket(rows, 0.25)["status"], time_bracket(rows, 1.1)["status"], "ValueError" if nonfinite_ok else "NO_ERROR"],
    })
    return {"status": "PASS" if all(case["status"] == "PASS" for case in cases) else "FAIL", "cases": cases, "scope": "manufactured semantics only; no native field or scientific error qualification"}


def group_observable(
    kind: str,
    mkfluid_relative: int,
    mk_absolute: int,
    mask: np.ndarray,
    frame: dict[str, Any],
    constants: dict[str, Any],
) -> dict[str, Any]:
    position = frame["position"][mask]
    velocity = frame["velocity"][mask]
    density = frame["density"][mask]
    velocity_magnitude = np.linalg.norm(velocity, axis=1)
    mass_key = "massfluid_kg" if kind == "fluid" else "massbound_kg"
    mass_per_particle = constants.get(mass_key)
    result: dict[str, Any] = {
        "kind": kind,
        "mkfluid_relative": None if mkfluid_relative < 0 else mkfluid_relative,
        "mk_absolute": None if mk_absolute < 0 else mk_absolute,
        "count": int(np.sum(mask)),
        "position_finite": bool(np.isfinite(position).all()),
        "velocity_finite": bool(np.isfinite(velocity).all()),
        "density_finite": bool(np.isfinite(density).all()),
        "centroid_m": [float(x) for x in np.mean(position, axis=0)] if position.size else None,
        "mean_velocity_m_per_s": [float(x) for x in np.mean(velocity, axis=0)] if velocity.size else None,
        "density": finite_stats(density),
        "speed_m_per_s": finite_stats(velocity_magnitude),
        "mass_semantics": "native_particle_sample_mass_only",
        "pressure_status": "NOT_DECODED_BY_WORKER",
        "eos_pressure": "UNKNOWN_NOT_DECODED",
    }
    if mass_per_particle is None:
        result.update({
            "sample_mass_kg": "UNKNOWN_MISSING_XML_MASS_CONSTANT",
            "weighted_centroid_m": None,
            "weighted_velocity_m_per_s": None,
            "kinetic_energy_j": "UNKNOWN_MISSING_XML_MASS_CONSTANT",
        })
        return result
    mass = float(mass_per_particle)
    sample_mass = float(mask.sum() * mass)
    result.update({
        "particle_mass_kg": mass,
        "sample_mass_kg": sample_mass,
        "weighted_centroid_m": [float(x) for x in np.average(position, axis=0, weights=np.ones(position.shape[0]) * mass)] if position.size else None,
        "weighted_velocity_m_per_s": [float(x) for x in np.average(velocity, axis=0, weights=np.ones(velocity.shape[0]) * mass)] if velocity.size else None,
        "kinetic_energy_j": float(0.5 * mass * np.sum(np.square(velocity), dtype=np.float64)),
    })
    return result


def frame_observables(frame: dict[str, Any], source: dict[str, Any], expected_time_s: float) -> dict[str, Any]:
    ids = frame["ids"]
    kind, mkfluid_relative, mk_absolute = assign_particle_ranges(ids, source["blocks"])
    if abs(frame["decoded_time_s"] - expected_time_s) > TIME_TOLERANCE_S:
        time_status = "FAIL_DECODED_TIME_MISMATCH"
    else:
        time_status = "PASS_DECODED_TIME_MATCH"
    groups: dict[str, Any] = {}
    for group_kind in sorted(set(str(value) for value in kind.tolist())):
        group_mask = kind == group_kind
        groups[group_kind] = group_observable(
            group_kind, -1, -1, group_mask, frame, source["constants"]
        )
        relative_values = sorted(set(int(value) for value in mkfluid_relative[group_mask].tolist()))
        absolute_values = sorted(set(int(value) for value in mk_absolute[group_mask].tolist()))
        groups[group_kind]["by_mkfluid_relative"] = {
            str(relative): group_observable(
                group_kind,
                relative,
                -1,
                group_mask & (mkfluid_relative == relative),
                frame,
                source["constants"],
            )
            for relative in relative_values
            if relative >= 0
        }
        groups[group_kind]["by_mk_absolute"] = {
            str(absolute): group_observable(
                group_kind,
                -1,
                absolute,
                group_mask & (mk_absolute == absolute),
                frame,
                source["constants"],
            )
            for absolute in absolute_values
            if absolute >= 0
        }
    fluid_mask = kind == "fluid"
    all_position = frame["position"]
    all_velocity = frame["velocity"]
    all_density = frame["density"]
    return {
        "frame": frame["frame"],
        "time": {
            "runparts_s": expected_time_s,
            "decoded_s": frame["decoded_time_s"],
            "absolute_error_s": abs(frame["decoded_time_s"] - expected_time_s),
            "status": time_status,
        },
        "identity": {
            "particle_count": int(ids.size),
            "id_unique": bool(np.unique(ids).size == ids.size),
            "id_min": int(np.min(ids)),
            "id_max": int(np.max(ids)),
            "type_ranges": "PASS_XML_BEGIN_COUNT_ASSIGNMENT",
        },
        "finite_fields": {
            "position": bool(np.isfinite(all_position).all()),
            "velocity": bool(np.isfinite(all_velocity).all()),
            "density": bool(np.isfinite(all_density).all()),
        },
        "groups": groups,
        "fluid_observables": {
            "status": "PASS" if np.any(fluid_mask) else "UNKNOWN_NO_FLUID_RANGE",
            "sample_mass_semantics": "sum(native fluid particle mass) only; not continuum mass or rigid body mass",
            "sample_mass_kg": groups.get("fluid", {}).get("sample_mass_kg", "UNKNOWN"),
            "centroid_m": groups.get("fluid", {}).get("centroid_m"),
            "mean_velocity_m_per_s": groups.get("fluid", {}).get("mean_velocity_m_per_s"),
            "density": groups.get("fluid", {}).get("density", {"status": "UNKNOWN"}),
            "kinetic_energy_j": groups.get("fluid", {}).get("kinetic_energy_j", "UNKNOWN"),
            "pressure_status": "NOT_DECODED_BY_WORKER",
            "eos_pressure": "UNKNOWN_NOT_DECODED",
        },
        "raw_field_digest_sha256": frame["field_digest_sha256"],
        "decoder_xml_sha256": frame["decoder_xml_sha256"],
        "position_dtype": frame["position_dtype"],
        "physical_rigid_body_mass": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SUM",
        "pressure_status": "NOT_DECODED_BY_WORKER",
        "eos_pressure": "UNKNOWN_NOT_DECODED",
    }


def _unknown_sidecar(output: Path, reason: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": "UNKNOWN_UNSUPPORTED_SEMANTICS",
        "reason": reason,
        "field_observables": "UNKNOWN",
        "typed_conversion": "NOT_PERFORMED",
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source": source or {},
    }
    atomic_json(output, value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = args.raw_root.resolve()
    runparts = args.runparts.resolve()
    source_xml = args.generated_xml.resolve()
    decoder = args.decoder.resolve()
    decoder_source = args.decoder_source.resolve() if args.decoder_source is not None else None
    output = args.output.resolve()
    scratch_root = args.scratch_root.resolve()
    if not raw_root.is_dir():
        raise ValueError(f"native raw root is missing: {raw_root}")
    if not decoder.is_file() or not os.access(decoder, os.X_OK):
        raise ValueError(f"official decoder is not executable: {decoder}")
    decoder_contract = decoder_source_contract(decoder_source)
    if decoder_contract["status"] == "UNKNOWN_DECODER_SOURCE_CONTRACT":
        raise UnsupportedSemantics("decoder source does not prove the argc=3 input/output-prefix contract")
    semantic_tests = manufactured_semantic_selftests()
    if semantic_tests["status"] != "PASS":
        raise UnsupportedSemantics("manufactured observer semantic self-test failed")
    rows = read_runparts(runparts)
    if args.expected_frame_count is not None and len(rows) != args.expected_frame_count:
        raise ValueError(f"RunPARTs rows {len(rows)} != expected {args.expected_frame_count}")
    if abs(rows[-1]["time_s"] - args.expected_final_time_s) > args.final_time_tolerance_s:
        raise ValueError(f"RunPARTs final time {rows[-1]['time_s']} differs from expected {args.expected_final_time_s}")
    source = parse_source_xml(source_xml)
    queries = [float(value) for value in args.query_times]
    brackets = [time_bracket(rows, query) for query in queries]
    required_frames: set[int] = set()
    for item in brackets:
        if item["status"] in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
            required_frames.add(int(item["lower_frame"]))
            required_frames.add(int(item["upper_frame"]))
    selected_frames = sorted(set(int(value) for value in args.frames) | required_frames)
    if not selected_frames:
        raise ValueError("no selected or query-bracketing frames")
    if any(frame < 0 or frame >= len(rows) for frame in selected_frames):
        raise ValueError(f"selected frame outside RunPARTs: {selected_frames}")

    decoded: dict[int, dict[str, Any]] = {}
    for frame in selected_frames:
        path = raw_root / f"Part_{frame:04d}.bi4"
        decoded_frame = decode_frame(path, decoder, scratch_root, frame)
        decoded[frame] = frame_observables(decoded_frame, source, rows[frame]["time_s"])

    # Rewrite query anchors with explicit references to the decoded field
    # values.  A bracket remains a bracket; no particle interpolation is done.
    for item in brackets:
        if item["status"] not in {"EXACT", "EXACT_OR_LEFT", "BRACKETED"}:
            continue
        item["lower_observation"] = decoded[item["lower_frame"]]
        item["upper_observation"] = decoded[item["upper_frame"]]
        item["field_interpolation"] = "NOT_PERFORMED_BY_WORKER"

    payload = {
        "schema": SCHEMA,
        "status": "PASS_DECODED_SELECTED_NATIVE_FIELDS",
        "scope": {
            "selected_frames_only": True,
            "selected_frame_count": len(selected_frames),
            "runparts_frame_count": len(rows),
            "full_native_tree_scanned": False,
            "full_native_tree_sha256": "NOT_COMPUTED_BY_WORKER",
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "particle_field_interpolation": "NOT_PERFORMED",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "source": {
            "raw_root": str(raw_root),
            "runparts": file_record(runparts),
            "generated_xml": file_record(source_xml),
            "decoder": file_record(decoder),
            "decoder_interface": decoder_contract,
            "particle_range_semantics": source,
            "selected_frames": selected_frames,
            "selected_part_records": [
                file_record(raw_root / f"Part_{frame:04d}.bi4") for frame in selected_frames
            ],
        },
        "time_window": {
            "first_saved_time_s": rows[0]["time_s"],
            "last_saved_time_s": rows[-1]["time_s"],
            "queries": brackets,
            "out_of_window_policy": "UNKNOWN; no extrapolation",
        },
        "observations": [decoded[frame] for frame in selected_frames],
        "decoder_interface": {
            **decoder_contract,
            "actual_selected_frame_decode": "PASS_F1_NATIVE_INTERFACE" if decoded else "UNKNOWN_NO_DECODED_FRAME",
            "decoded_output_contract": "each selected frame produced XML plus Idp/Pos-or-Posd/Vel/Rhop arrays",
        },
        "manufactured_semantic_selftests": semantic_tests,
        "mass_semantics": {
            "fluid": "native per-particle mass summed within fluid ranges; this is a discrete sample observable",
            "continuum": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
            "rigid_body": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SUM",
            "xml_rigid_declarations": source["rigid_body_declarations"],
        },
        "source_deleted": False,
    }
    atomic_json(output, payload)
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
    except UnsupportedSemantics as exc:
        result = _unknown_sidecar(args.output.resolve(), str(exc))
    print(json.dumps({
        "status": result["status"],
        "output": str(args.output.resolve()),
        "selected_frames": result.get("scope", {}).get("selected_frame_count", 0),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
