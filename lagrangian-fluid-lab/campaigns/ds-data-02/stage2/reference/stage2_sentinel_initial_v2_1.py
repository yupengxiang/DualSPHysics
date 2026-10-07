#!/usr/bin/env python3
"""Audit frame zero for the fourteen Stage2 sentinels.

This module is deliberately a new entry point.  It binds one exact CURRENT336
row, its direct-conversion report, the generated XML and the native Part_0000
file before reading one frame from the typed trajectory.  The producer SHA and
file stat for the HDF5 are used as provenance; the large HDF5 is never
rehashed and no later frame is read.

The decoder metadata and the generated particle ranges are treated as data,
not as F2-specific assumptions.  Multiple pieces, dynamic/reused IDs,
periodic pieces, missing constants, unsupported block kinds, Posd positions,
and an unknown typed schema are reported explicitly.  An unsupported input is
``UNKNOWN`` rather than being silently interpreted with the F2 contract.

This is an input/equivalence audit only.  It does not start a solver or
PartVTK and it does not assign QI, QN, or QE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds02.stage2.sentinel.initial-frame-equivalence.v2.1"
PROVENANCE_SCHEMA = "ds02.stage2.sentinel.initial-provenance.v2.1"
REQUEST_SCHEMA = "ds02.request.v1"
EXPECTED_H5_SCHEMA = "ds-data-02.hdf5-schema.v1"
TOLERANCES = {
    "position": 1.0e-6,
    "velocity": 1.0e-6,
    "density": 1.0e-3,
    "mass": 1.0e-7,
    "pressure": 5.0e-2,
    "time": 5.0e-5,
}
TYPE_NAMES = {0: "fixed", 1: "moving", 2: "floating", 3: "fluid"}
REQUIRED_NATIVE_CONTRACT = ("Npiece", "Piece", "NpDynamic", "ReuseIds", "PeriMode")
DEFAULT_REVIEW = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/"
    "STAGE2_SENTINEL_INPUTS/sentinel-inputs-001/sentinel-input-review.json"
)
DEFAULT_CURRENT = Path(__file__).resolve().parents[1] / "CURRENT336.json"
FULLSCAN_RECEIPTS = {
    "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090": Path(
        "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
        "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/"
        "root-stage1-f2-rx056-rot090-actual1077-full401-116-023-nvme-hard2gib-root1097/"
        "execution-receipt.json"
    )
}
LEGACY_F2_SMALL_PROVENANCE = Path(__file__).with_name("f2-s1-initial-frame-smallprovenance.json")


class SourceBindingError(RuntimeError):
    """The exact source tuple cannot be trusted."""


class UnsupportedSemantics(RuntimeError):
    """A source is readable but its native semantics are not supported."""


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def atomic_write_once(path: Path, value: Any) -> None:
    """Create a JSON file once and never replace an existing artifact."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, ensure_ascii=False, default=json_default) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def scalar(element: ET.Element) -> Any:
    value = element.get("v")
    if value is None:
        return None
    tag = element.tag.lower().split("}")[-1]
    if tag in {"bool", "boolean"}:
        return value.lower() in {"1", "true", "yes"}
    if tag in {"int", "uint", "int32", "uint32", "int64", "uint64", "long", "ullong", "llong"}:
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


def read_current_rows(current_path: Path) -> dict[str, dict[str, Any]]:
    current = load_json(current_path)
    rows = current.get("cases")
    if not isinstance(rows, list):
        raise ValueError("CURRENT336 has no cases list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("physical_case_id"), str):
            result[row["physical_case_id"]] = row
    return result


def review_rows(review_path: Path) -> list[dict[str, Any]]:
    review = load_json(review_path)
    rows = review.get("sentinels")
    if not isinstance(rows, list) or len(rows) != 14:
        raise ValueError(f"expected exactly 14 sentinel review rows, got {len(rows) if isinstance(rows, list) else 'UNKNOWN'}")
    result = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("sentinel review row is not an object")
        sid = row.get("sentinel_id")
        physical = row.get("physical_case_id")
        if not isinstance(sid, str) or not isinstance(physical, str) or sid in seen:
            raise ValueError("sentinel review has an invalid or duplicate identity")
        seen.add(sid)
        result.append(row)
    return result


def file_record(path: Path, *, digest: bool = True) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    result: dict[str, Any] = {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if digest:
        result["sha256"] = sha256_file(path)
    return result


def _same_path(left: Any, right: Any) -> bool:
    try:
        return Path(str(left)).resolve() == Path(str(right)).resolve()
    except (TypeError, ValueError):
        return False


def _declared_hash(path: Path, value: Any, label: str) -> None:
    if not isinstance(value, str) or value != sha256_file(path):
        raise SourceBindingError(f"{label} SHA differs from its declared producer/source SHA: {path}")


def fullscan_credit(physical_case_id: str, expected_h5_sha: str) -> dict[str, Any]:
    receipt_path = FULLSCAN_RECEIPTS.get(physical_case_id)
    if receipt_path is None:
        return {"status": "UNKNOWN", "reason": "no linked full-time receipt in this narrow scope"}
    if not receipt_path.is_file():
        return {"status": "UNKNOWN", "reason": "linked full-time receipt is unavailable", "path": str(receipt_path)}
    receipt = load_json(receipt_path)
    request = receipt.get("request", {})
    producer = request.get("source_h5_producer_sha256")
    checks = {
        "status_completed": receipt.get("status") == "completed",
        "returncode_zero": receipt.get("returncode") == 0,
        "source_h5_producer_sha_match": producer == expected_h5_sha,
        "full_time_and_native_identity_required": request.get("full_time_and_native_identity_required") is True,
        "full401_authorized": request.get("full401_authorized") is True,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "source_h5_producer_sha256": producer,
        "checks": checks,
        "full_hdf5_rehash": "OMITTED_BY_SCOPE",
    }


def _legacy_small_provenance(physical_case_id: str, current_path: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    if physical_case_id != "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090":
        return {"status": "UNKNOWN", "reason": "no legacy v1 small-provenance artifact for this sentinel"}
    if not LEGACY_F2_SMALL_PROVENANCE.is_file():
        return {"status": "UNKNOWN", "reason": "legacy v1 small-provenance artifact unavailable"}
    legacy = load_json(LEGACY_F2_SMALL_PROVENANCE)
    sources = legacy.get("sources", {})
    typed = sources.get("typed_hdf5", {})
    checks = {
        "schema": legacy.get("schema") == "ds02.stage2.f2-s1.initial-frame-smallprovenance.v1",
        "physical_case_id": legacy.get("physical_case_id") == physical_case_id,
        "current_path": _same_path(sources.get("current336", {}).get("path"), current_path),
        "typed_path": _same_path(typed.get("path"), entry["typed_hdf5"]["path"]),
        "typed_producer_sha": typed.get("producer_declared_sha256") == entry["typed_hdf5"]["producer_declared_sha256"],
        "typed_bytes": typed.get("bytes") == entry["typed_hdf5"]["bytes"],
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "path": str(LEGACY_F2_SMALL_PROVENANCE),
        "sha256": sha256_file(LEGACY_F2_SMALL_PROVENANCE),
        "checks": checks,
        "scope": legacy.get("scope", {}),
    }


def _report_paths(row: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Path]:
    try:
        raw_root = Path(row["raw_root"]["path"])
        generated_xml = Path(row["source_bindings"]["generated_xml"]["path"])
        report_path = Path(row["conversion_report"]["path"])
        report_xml = Path(report["source_provenance"]["generated_xml"]["path"])
        report_raw = Path(report["source_provenance"]["data_root"])
        report_h5 = Path(report["output_hdf5"])
        row_h5 = Path(row["trajectory"]["path"])
        decoder = Path(report["source_provenance"]["decoder"]["path"])
    except (KeyError, TypeError) as error:
        raise SourceBindingError(f"incomplete CURRENT/report source binding: {error}") from error
    if not _same_path(generated_xml, report_xml):
        raise SourceBindingError("CURRENT generated XML and conversion report generated XML differ")
    if not _same_path(raw_root, report_raw):
        raise SourceBindingError("CURRENT raw root and conversion report data root differ")
    if not _same_path(row_h5, report_h5):
        raise SourceBindingError("CURRENT trajectory path and conversion report output HDF5 differ")
    native_frame = raw_root / "Part_0000.bi4"
    return {
        "report": report_path,
        "generated_xml": generated_xml,
        "raw_root": raw_root,
        "native_frame0": native_frame,
        "typed_hdf5": report_h5,
        "decoder": decoder,
    }


def emit_provenance(current_path: Path, review_path: Path, output_path: Path) -> dict[str, Any]:
    current_rows = read_current_rows(current_path)
    reviews = review_rows(review_path)
    current_record = file_record(current_path)
    review_record = file_record(review_path)
    entries = []
    for review in reviews:
        physical = review["physical_case_id"]
        if physical not in current_rows:
            raise SourceBindingError(f"CURRENT336 has no reviewed physical case: {physical}")
        row = current_rows[physical]
        if row.get("family_id") != review.get("family_id"):
            raise SourceBindingError(f"family mismatch for {physical}")
        report_path = Path(row["conversion_report"]["path"])
        report = load_json(report_path)
        paths = _report_paths(row, report)
        for label, path in paths.items():
            if label == "raw_root":
                if not path.is_dir():
                    raise SourceBindingError(f"missing bound source directory {label}: {path}")
            elif not path.is_file():
                raise SourceBindingError(f"missing bound source {label}: {path}")
        trajectory = row.get("trajectory", {})
        report_sha = report.get("output_sha256")
        producer_sha = trajectory.get("producer_declared_sha256")
        if producer_sha != report_sha:
            raise SourceBindingError(f"CURRENT trajectory producer SHA and report SHA differ: {physical}")
        current_h5 = {
            "path": str(Path(trajectory["path"])),
            "producer_declared_sha256": producer_sha,
            "bytes": trajectory.get("bytes"),
            "mtime_ns": trajectory.get("mtime_ns"),
        }
        observed_h5 = paths["typed_hdf5"].stat()
        if current_h5["bytes"] != observed_h5.st_size or current_h5["mtime_ns"] != observed_h5.st_mtime_ns:
            raise SourceBindingError(f"CURRENT HDF5 stat is stale: {physical}")
        if not isinstance(current_h5["bytes"], int) or not isinstance(current_h5["mtime_ns"], int):
            raise SourceBindingError(f"CURRENT HDF5 stat is incomplete: {physical}")
        xml_record = file_record(paths["generated_xml"])
        report_xml_declared = report.get("source_provenance", {}).get("generated_xml", {})
        if xml_record["sha256"] != row["source_bindings"]["generated_xml"].get("sha256"):
            raise SourceBindingError(f"CURRENT generated XML SHA changed: {physical}")
        if xml_record["sha256"] != report_xml_declared.get("sha256"):
            raise SourceBindingError(f"conversion report generated XML SHA differs: {physical}")
        decoder_record = file_record(paths["decoder"])
        decoder_declared = report.get("source_provenance", {}).get("decoder", {})
        if decoder_record["sha256"] != decoder_declared.get("sha256"):
            raise SourceBindingError(f"decoder SHA differs from conversion report: {physical}")
        native_record = file_record(paths["native_frame0"])
        report_raw = report.get("source_provenance", {}).get("data_root")
        if not _same_path(report_raw, paths["raw_root"]):
            raise SourceBindingError(f"raw root changed in report: {physical}")
        report_record = file_record(paths["report"])
        entry: dict[str, Any] = {
            "sentinel_id": review["sentinel_id"],
            "family_id": review["family_id"],
            "physical_case_id": physical,
            "runtime_case_alias": row.get("runtime_case_alias"),
            "current336_row": {
                "trajectory": dict(current_h5),
                "frames": row.get("frames"),
                "particles": row.get("particles"),
            },
            "report_output": {
                "path": str(paths["typed_hdf5"]),
                "producer_declared_sha256": report_sha,
                "frames": report.get("frames"),
                "particles": report.get("particles"),
            },
            "small_provenance": {
                "trajectory": dict(current_h5),
                "hdf5_hash_policy": "producer_declared_sha256_plus_stat; full trajectory rehash intentionally omitted",
            },
            "source_files": {
                "current336": current_record,
                "sentinel_review": review_record,
                "generated_xml": xml_record,
                "conversion_report": report_record,
                "native_frame0": native_record,
                "decoder": decoder_record,
            },
            "typed_hdf5": {
                **current_h5,
                "observed_bytes": observed_h5.st_size,
                "observed_mtime_ns": observed_h5.st_mtime_ns,
                "full_rehash": "OMITTED_BY_SCOPE",
            },
            "source_bindings": {
                "generated_xml": str(paths["generated_xml"]),
                "raw_root": str(paths["raw_root"]),
                "native_frame0": str(paths["native_frame0"]),
                "decoder": str(paths["decoder"]),
                "conversion_report": str(paths["report"]),
            },
            "review": {
                "status": review.get("status"),
                "mismatches": review.get("mismatches", []),
                "coordinate_frame": review.get("coordinate_frame"),
                "units": review.get("units"),
            },
            "fullscan_hash_credit": fullscan_credit(physical, producer_sha),
        }
        entry["legacy_v1_small_provenance"] = _legacy_small_provenance(physical, current_path, entry)
        entries.append(entry)
    result = {
        "schema": PROVENANCE_SCHEMA,
        "scope": {
            "sentinel_count": len(entries),
            "raw_read": "not read while emitting provenance; runtime reads Part_0000.bi4 only",
            "typed_read": "not read while emitting provenance; runtime reads HDF5 datasets at index 0 only",
            "full_time_scan": False,
            "full_hdf5_rehash": False,
            "solver_started": False,
            "partvtk_started": False,
        },
        "sources": {"current336": current_record, "sentinel_review": review_record},
        "cases": entries,
    }
    atomic_write_once(output_path, result)
    return result


def _entry_for(entries: Sequence[Mapping[str, Any]], sentinel_id: str) -> Mapping[str, Any]:
    matches = [entry for entry in entries if entry.get("sentinel_id") == sentinel_id]
    if len(matches) != 1:
        raise ValueError(f"provenance index must contain one {sentinel_id!r}; got {len(matches)}")
    return matches[0]


def load_provenance_entry(index_path: Path, sentinel_id: str) -> dict[str, Any]:
    index = load_json(index_path)
    if index.get("schema") != PROVENANCE_SCHEMA:
        raise SourceBindingError("unexpected v2 provenance index schema")
    entries = index.get("cases")
    if not isinstance(entries, list):
        raise SourceBindingError("v2 provenance index has no cases")
    return dict(_entry_for(entries, sentinel_id))


def verify_provenance_entry(
    current_path: Path,
    review_path: Path,
    entry: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    physical = entry.get("physical_case_id")
    rows = read_current_rows(current_path)
    row = rows.get(physical)
    if row is None:
        raise SourceBindingError(f"CURRENT336 row is missing: {physical}")
    paths = _report_paths(row, report)
    expected = entry.get("typed_hdf5", {})
    current_trajectory = row.get("trajectory", {})
    report_output = entry.get("report_output", {})
    small = entry.get("small_provenance", {}).get("trajectory", {})
    checks: dict[str, Any] = {}
    checks["current_path"] = _same_path(current_trajectory.get("path"), expected.get("path"))
    checks["report_path"] = _same_path(report.get("output_hdf5"), expected.get("path"))
    checks["current_producer_sha"] = current_trajectory.get("producer_declared_sha256") == expected.get("producer_declared_sha256")
    checks["report_producer_sha"] = report.get("output_sha256") == expected.get("producer_declared_sha256")
    checks["report_entry_path"] = _same_path(report_output.get("path"), expected.get("path"))
    checks["report_entry_sha"] = report_output.get("producer_declared_sha256") == expected.get("producer_declared_sha256")
    checks["small_provenance_path"] = _same_path(small.get("path"), expected.get("path"))
    checks["small_provenance_sha"] = small.get("producer_declared_sha256") == expected.get("producer_declared_sha256")
    checks["small_provenance_bytes"] = small.get("bytes") == expected.get("bytes")
    checks["small_provenance_mtime_ns"] = small.get("mtime_ns") == expected.get("mtime_ns")
    checks["current_bytes"] = current_trajectory.get("bytes") == expected.get("bytes")
    checks["current_mtime_ns"] = current_trajectory.get("mtime_ns") == expected.get("mtime_ns")
    checks["report_frames"] = report.get("frames") == report_output.get("frames")
    checks["report_particles"] = report.get("particles") == report_output.get("particles")
    h5 = paths["typed_hdf5"]
    if not h5.is_file():
        checks["hdf5_live_stat"] = False
        live_stat = {"exists": False}
    else:
        stat = h5.stat()
        live_stat = {"exists": True, "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        checks["hdf5_live_stat"] = stat.st_size == expected.get("bytes") and stat.st_mtime_ns == expected.get("mtime_ns")
    checks["report_file_binding"] = _same_path(entry.get("source_files", {}).get("conversion_report", {}).get("path"), paths["report"])
    checks["xml_path_binding"] = _same_path(entry.get("source_files", {}).get("generated_xml", {}).get("path"), paths["generated_xml"])
    checks["raw_path_binding"] = _same_path(entry.get("source_files", {}).get("native_frame0", {}).get("path"), paths["native_frame0"])
    checks["decoder_path_binding"] = _same_path(entry.get("source_files", {}).get("decoder", {}).get("path"), paths["decoder"])
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise SourceBindingError(f"three-way provenance mismatch for {physical}: {', '.join(failed)}")
    credit = entry.get("fullscan_hash_credit", {})
    credit_check = "UNKNOWN"
    if credit.get("status") == "PASS":
        credit_path = Path(credit["path"])
        if credit_path.is_file():
            receipt = load_json(credit_path)
            request = receipt.get("request", {})
            credit_checks = (
                receipt.get("status") == "completed"
                and receipt.get("returncode") == 0
                and request.get("source_h5_producer_sha256") == expected.get("producer_declared_sha256")
            )
            credit_check = "PASS" if credit_checks and sha256_file(credit_path) == credit.get("receipt_sha256") else "FAIL"
        else:
            credit_check = "FAIL"
    return {
        "status": "PASS",
        "checks": checks,
        "live_hdf5_stat": live_stat,
        "producer_sha256": expected.get("producer_declared_sha256"),
        "fullscan_hash_credit": credit_check,
        "full_hdf5_rehash": "OMITTED_BY_SCOPE",
    }


def parse_particle_blocks(generated_xml: Path) -> list[dict[str, Any]]:
    root = ET.parse(generated_xml).getroot()
    particles = root.find(".//execution/particles")
    if particles is None:
        particles = root.find(".//particles")
    if particles is None:
        raise UnsupportedSemantics("generated XML lacks execution/particles")
    type_by_tag = {"fixed": 0, "moving": 1, "floating": 2, "fluid": 3}
    blocks: list[dict[str, Any]] = []
    unsupported_tags = []
    for child in particles:
        tag = child.tag.split("}")[-1]
        if tag == "_summary":
            continue
        if tag not in type_by_tag:
            unsupported_tags.append(tag)
            continue
        try:
            blocks.append({
                "begin": int(child.attrib["begin"]),
                "count": int(child.attrib["count"]),
                "mk": int(child.attrib["mk"]),
                "type": type_by_tag[tag],
                "tag": tag,
            })
        except (KeyError, TypeError, ValueError) as error:
            raise UnsupportedSemantics(f"typed XML block is incomplete: {tag}") from error
    if unsupported_tags:
        raise UnsupportedSemantics("unsupported typed XML blocks: " + ", ".join(unsupported_tags))
    if not blocks:
        raise UnsupportedSemantics("generated XML has no typed particle blocks")
    return sorted(blocks, key=lambda item: item["begin"])


def assign_types(ids: np.ndarray, blocks: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    types = np.full(ids.size, -1, dtype=np.int8)
    mks = np.full(ids.size, -1, dtype=np.int16)
    covered = np.zeros(ids.size, dtype=bool)
    for block in blocks:
        selected = (ids >= int(block["begin"])) & (ids < int(block["begin"]) + int(block["count"]))
        if np.any(covered[selected]):
            raise UnsupportedSemantics("typed XML ranges overlap")
        types[selected] = int(block["type"])
        mks[selected] = int(block["mk"])
        covered[selected] = True
    if not np.all(covered):
        raise UnsupportedSemantics("typed XML ranges leave native IDs unclassified")
    return types, mks


def native_semantics(metadata: Mapping[str, Any]) -> dict[str, Any]:
    missing = [name for name in REQUIRED_NATIVE_CONTRACT if name not in metadata]
    if missing:
        return {"status": "UNKNOWN", "reason": "missing decoder contract fields", "missing": missing}
    expected = {"Npiece": 1, "Piece": 0, "NpDynamic": False, "ReuseIds": False, "PeriMode": 0}
    mismatches = {}
    for name, wanted in expected.items():
        value = metadata.get(name)
        if value != wanted:
            mismatches[name] = {"observed": value, "required": wanted}
    if mismatches:
        return {"status": "UNKNOWN", "reason": "native multi-piece/dynamic/periodic contract is unsupported", "mismatches": mismatches}
    return {"status": "PASS", "contract": {name: metadata[name] for name in REQUIRED_NATIVE_CONTRACT}}


def decode_frame_zero(native_frame: Path, decoder: Path, work_root: Path) -> dict[str, Any]:
    """Run exactly the report-named decoder on the one native frame."""
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
    position_encoding = "Pos"
    pos_dtype = np.float32
    if not pos_path.is_file():
        pos_path = data_root / "Posd.bin"
        position_encoding = "Posd"
        pos_dtype = np.float64
    velocity_path = data_root / "Vel.bin"
    density_path = data_root / "Rhop.bin"
    if not all(path.is_file() for path in (ids_path, pos_path, velocity_path, density_path)):
        raise RuntimeError(f"decoder output is incomplete: {data_root}")
    ids_unsorted = np.fromfile(ids_path, dtype=np.uint32)
    if ids_unsorted.size == 0 or np.unique(ids_unsorted).size != ids_unsorted.size:
        raise RuntimeError("native frame has an empty or duplicate Idp axis")
    order = np.argsort(ids_unsorted, kind="mergesort")
    n = ids_unsorted.size
    position = np.fromfile(pos_path, dtype=pos_dtype).reshape(n, 3)[order]
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
        "position_encoding": position_encoding,
        "position_dtype": np.dtype(pos_dtype).name,
        "velocity": velocity,
        "density": density,
        "time": float(raw_time),
        "zone": int(metadata.get("Piece", 0)) if isinstance(metadata.get("Piece", 0), (int, float)) else None,
        "decoder_xml_sha256": sha256_file(xml_path),
    }


def compare_arrays(raw: np.ndarray, typed: np.ndarray, tolerance: float, *, exact: bool = False) -> dict[str, Any]:
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
    result["status"] = "PASS" if (result["exact"] if exact else result["max_abs_error"] <= tolerance) else "FAIL"
    return result


def unknown_field(reason: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "reason": reason}


def type_mass_summary(types: np.ndarray, mass: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in sorted(set(int(item) for item in types.tolist())):
        selected = types == kind
        result[str(kind)] = {
            "type_name": TYPE_NAMES.get(kind, "UNKNOWN"),
            "count": int(np.sum(selected)),
            "mass_kg": float(np.sum(mass[selected], dtype=np.float64)),
        }
    return result


def read_typed_frame_zero(typed_hdf5: Path) -> dict[str, Any]:
    with h5py.File(typed_hdf5, "r") as h5:
        schema = h5.attrs.get("schema", "UNKNOWN")
        schema = schema.decode() if isinstance(schema, bytes) else str(schema)
        result: dict[str, Any] = {"schema": schema, "missing": []}

        def read_frame(name: str) -> np.ndarray | None:
            if name not in h5:
                result["missing"].append(name)
                return None
            dataset = h5[name]
            if dataset.ndim < 2 or dataset.shape[0] < 1:
                result["missing"].append(name)
                return None
            return np.asarray(dataset[0])

        def read_initial(name: str) -> np.ndarray | None:
            if name not in h5:
                result["missing"].append(name)
                return None
            return np.asarray(h5[name][:])

        def read_scalar(name: str) -> float | None:
            if name not in h5 or h5[name].ndim < 1 or h5[name].shape[0] < 1:
                result["missing"].append(name)
                return None
            return float(h5[name][0])

        result.update({
            "ids": read_initial("particle_id"),
            "zone": read_initial("particle_zone"),
            "position": read_frame("position"),
            "velocity": read_frame("velocity"),
            "density": read_frame("density"),
            "mass": read_frame("mass"),
            "pressure": read_frame("pressure"),
            "type": read_frame("type"),
            "mk": read_frame("mk"),
            "valid": read_frame("valid"),
            "initial_type": read_initial("initial_type"),
            "initial_mk": read_initial("initial_mk"),
            "initial_mass": read_initial("initial_mass"),
            "time": read_scalar("time"),
        })
        return result


def verify_and_read_source(current_path: Path, review_path: Path, index_path: Path, sentinel_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Path]]:
    entry = load_provenance_entry(index_path, sentinel_id)
    review = next(row for row in review_rows(review_path) if row["sentinel_id"] == sentinel_id)
    physical = entry.get("physical_case_id")
    rows = read_current_rows(current_path)
    row = rows.get(physical)
    if row is None:
        raise SourceBindingError(f"no CURRENT row for {physical}")
    report_path = Path(row["conversion_report"]["path"])
    report = load_json(report_path)
    paths = _report_paths(row, report)
    provenance = verify_provenance_entry(current_path, review_path, entry, report)
    return entry, review, provenance, paths


def _raw_unknown_fields(reason: str) -> dict[str, dict[str, Any]]:
    return {name: unknown_field(reason) for name in (
        "identity_idp", "identity_zone", "type", "mk", "position", "velocity", "density",
        "mass", "pressure_eos", "initial_type", "initial_mk", "initial_mass", "valid", "time"
    )}


def run_check(current_path: Path, review_path: Path, index_path: Path, sentinel_id: str, output_path: Path) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"refuse to overwrite existing output: {output_path}")
    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    entry, review, source_check, paths = verify_and_read_source(current_path, review_path, index_path, sentinel_id)
    with tempfile.TemporaryDirectory(prefix=f"ds02-{sentinel_id.lower()}-frame0-") as temporary:
        raw = decode_frame_zero(paths["native_frame0"], paths["decoder"], Path(temporary))
    semantics = native_semantics(raw["metadata"])
    typed = read_typed_frame_zero(paths["typed_hdf5"])
    blocks: list[dict[str, Any]] | None = None
    raw_types: np.ndarray | None = None
    raw_mks: np.ndarray | None = None
    semantics_reason = None
    try:
        blocks = parse_particle_blocks(paths["generated_xml"])
        raw_types, raw_mks = assign_types(raw["ids"], blocks)
    except UnsupportedSemantics as error:
        semantics = {"status": "UNKNOWN", "reason": str(error), **semantics}
        semantics_reason = str(error)
    if semantics.get("status") != "PASS":
        reason = semantics_reason or semantics.get("reason", "native contract is unsupported")
        fields = _raw_unknown_fields(reason)
        unknown_reason = reason
    elif typed.get("schema") != EXPECTED_H5_SCHEMA:
        fields = _raw_unknown_fields(f"typed HDF5 schema is unsupported: {typed.get('schema')}")
        unknown_reason = f"typed HDF5 schema is unsupported: {typed.get('schema')}"
    else:
        unknown_reason = None
        fields = {}
        def required(name: str) -> np.ndarray | None:
            value = typed.get(name)
            if value is None:
                fields[name] = unknown_field(f"typed dataset is missing: {name}")
            return value
        typed_ids = required("ids")
        typed_zone = required("zone")
        typed_position = required("position")
        typed_velocity = required("velocity")
        typed_density = required("density")
        typed_mass = required("mass")
        typed_pressure = required("pressure")
        typed_type = required("type")
        typed_mk = required("mk")
        typed_valid = required("valid")
        typed_initial_type = required("initial_type")
        typed_initial_mk = required("initial_mk")
        typed_initial_mass = required("initial_mass")
        if raw_types is None or raw_mks is None:
            fields.update(_raw_unknown_fields("typed particle range semantics are unsupported"))
        else:
            if typed_ids is not None:
                fields["identity_idp"] = compare_arrays(raw["ids"], typed_ids, 0.0, exact=True)
            if typed_zone is not None:
                fields["identity_zone"] = compare_arrays(
                    np.full(raw["ids"].size, raw["zone"], dtype=np.int16), typed_zone, 0.0, exact=True
                )
            if typed_type is not None:
                fields["type"] = compare_arrays(raw_types, typed_type, 0.0, exact=True)
            if typed_mk is not None:
                fields["mk"] = compare_arrays(raw_mks, typed_mk, 0.0, exact=True)
            if typed_position is not None:
                fields["position"] = compare_arrays(raw["position"], typed_position, TOLERANCES["position"])
            if typed_velocity is not None:
                fields["velocity"] = compare_arrays(raw["velocity"], typed_velocity, TOLERANCES["velocity"])
            if typed_density is not None:
                fields["density"] = compare_arrays(raw["density"], typed_density, TOLERANCES["density"])
            mass_fluid = raw["metadata"].get("MassFluid")
            mass_bound = raw["metadata"].get("MassBound")
            if mass_fluid is None or mass_bound is None:
                fields["mass"] = unknown_field("native MassFluid/MassBound constants are unavailable")
            elif typed_mass is not None:
                raw_mass = np.where(raw_types == 3, float(mass_fluid), float(mass_bound)).astype(np.float32)
                fields["mass"] = compare_arrays(raw_mass, typed_mass, TOLERANCES["mass"])
            b_value = raw["metadata"].get("B")
            rhop0 = raw["metadata"].get("Rhop0")
            gamma = raw["metadata"].get("Gamma")
            if None in (b_value, rhop0, gamma) or typed_pressure is None:
                fields["pressure_eos"] = unknown_field("native EOS constants or typed pressure are unavailable")
            else:
                raw_pressure = (float(b_value) * ((raw["density"].astype(np.float64) / float(rhop0)) ** float(gamma) - 1.0)).astype(np.float32)
                fields["pressure_eos"] = compare_arrays(raw_pressure, typed_pressure, TOLERANCES["pressure"])
            if typed_initial_type is not None and typed_type is not None:
                fields["initial_type"] = compare_arrays(typed_type, typed_initial_type, 0.0, exact=True)
            if typed_initial_mk is not None and typed_mk is not None:
                fields["initial_mk"] = compare_arrays(typed_mk, typed_initial_mk, 0.0, exact=True)
            if typed_initial_mass is not None and typed_mass is not None:
                fields["initial_mass"] = compare_arrays(typed_mass, typed_initial_mass, TOLERANCES["mass"])
            if typed_valid is not None:
                fields["valid"] = {
                    "status": "PASS" if bool(np.all(typed_valid)) else "FAIL",
                    "count": int(typed_valid.size),
                    "valid_count": int(np.sum(typed_valid)),
                }
            if typed.get("time") is None:
                fields["time"] = unknown_field("typed time dataset is unavailable")
            else:
                time_error = abs(raw["time"] - float(typed["time"]))
                fields["time"] = {
                    "status": "PASS" if time_error <= TOLERANCES["time"] else "FAIL",
                    "raw_s": raw["time"],
                    "typed_s": float(typed["time"]),
                    "abs_error_s": time_error,
                    "tolerance_s": TOLERANCES["time"],
                }
    expected_names = (
        "identity_idp", "identity_zone", "type", "mk", "position", "velocity", "density", "mass",
        "pressure_eos", "initial_type", "initial_mk", "initial_mass", "valid", "time"
    )
    for name in expected_names:
        fields.setdefault(name, unknown_field("comparison could not be established"))
    statuses = {name: value.get("status", "UNKNOWN") for name, value in fields.items()}
    if source_check.get("status") != "PASS":
        overall = "FAILED"
    elif any(value == "FAIL" for value in statuses.values()):
        overall = "FAIL"
    elif any(value == "UNKNOWN" for value in statuses.values()) or unknown_reason:
        overall = "UNKNOWN"
    else:
        overall = "PASS"
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "status": overall,
        "scientific_acceptance": {"QI": "NOT_ASSESSED", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
        "scope": {
            "sentinel_id": sentinel_id,
            "physical_case_id": entry.get("physical_case_id"),
            "frame_index": 0,
            "raw_read": "Part_0000.bi4 only",
            "typed_read": "HDF5 datasets at index 0 only",
            "full_time_scan": False,
            "raw_tree_scan": False,
            "full_hdf5_rehash": False,
            "solver_started": False,
            "partvtk_started": False,
        },
        "inputs": {
            "current336": file_record(current_path),
            "sentinel_review": file_record(review_path),
            "provenance_index": file_record(index_path),
            "generated_xml": file_record(paths["generated_xml"]),
            "conversion_report": file_record(paths["report"]),
            "native_frame0": file_record(paths["native_frame0"]),
            "decoder": file_record(paths["decoder"]),
            "typed_hdf5": {
                "path": str(paths["typed_hdf5"]),
                "producer_declared_sha256": entry["typed_hdf5"].get("producer_declared_sha256"),
                "bytes": entry["typed_hdf5"].get("bytes"),
                "mtime_ns": entry["typed_hdf5"].get("mtime_ns"),
                "full_rehash": "OMITTED_BY_SCOPE",
            },
        },
        "source_binding_check": source_check,
        "native_semantics": semantics,
        "decoder": {
            "argv_shape": [str(paths["decoder"]), str(paths["native_frame0"]), "<temporary-prefix>"],
            "reported_zone_piece": raw["zone"],
            "position_encoding": raw["position_encoding"],
            "position_dtype": raw["position_dtype"],
            "metadata_constants": {key: raw["metadata"].get(key) for key in ("Dp", "MassFluid", "MassBound", "Rhop0", "Gamma", "B")},
            "decoded_particles": int(raw["ids"].size),
            "decoder_xml_sha256": raw["decoder_xml_sha256"],
        },
        "typed": {
            "hdf5_schema": typed.get("schema"),
            "particles": int(typed["ids"].size) if isinstance(typed.get("ids"), np.ndarray) else "UNKNOWN",
            "frames_declared": entry.get("report_output", {}).get("frames"),
            "initial_identity_key": "(Zone,Idp)",
            "missing_datasets": typed.get("missing", []),
            "blocks_from_generated_xml": blocks if blocks is not None else "UNKNOWN",
        },
        "field_checks": fields,
        "field_status": statuses,
        "mass_semantics": {
            "type_names": TYPE_NAMES,
            "source_by_type": {"0": "native_header_MassBound", "1": "native_header_MassBound", "2": "native_header_MassBound", "3": "native_header_MassFluid"},
            "unknown_if_header_missing": True,
        },
        "fullscan_hash_credit": entry.get("fullscan_hash_credit", {"status": "UNKNOWN"}),
        "review": {"sentinel_status": review.get("status"), "mismatches": review.get("mismatches", [])},
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
        ] + ([unknown_reason] if unknown_reason else []),
    }
    atomic_write_once(output_path, result)
    return result


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("cannot locate git repository root")


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=_repo_root(), check=True, capture_output=True, text=True).stdout.strip()


def request_input_files(entry: Mapping[str, Any], current_path: Path, review_path: Path, index_path: Path) -> list[Path]:
    source_files = entry["source_files"]
    result = [
        Path(__file__).resolve().parents[4] / "scripts/ds_data02_stage2_dispatch.py",
        Path(__file__).resolve().parents[4] / "scripts/ds_data02_strict_dispatch_v1.py",
        Path(__file__).resolve().parents[4] / "scripts/ds_data02_runtime_v2.py",
        Path(__file__).resolve(),
        current_path,
        review_path,
        index_path,
        Path(source_files["generated_xml"]["path"]),
        Path(source_files["conversion_report"]["path"]),
        Path(source_files["native_frame0"]["path"]),
        Path(source_files["decoder"]["path"]),
    ]
    legacy = entry.get("legacy_v1_small_provenance", {})
    if legacy.get("status") == "PASS":
        result.append(Path(legacy["path"]))
    credit = entry.get("fullscan_hash_credit", {})
    if credit.get("status") == "PASS":
        result.append(Path(credit["path"]))
    seen: set[str] = set()
    unique = []
    for path in result:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(Path(resolved))
    return unique


def emit_requests(current_path: Path, review_path: Path, index_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    index = load_json(index_path)
    if index.get("schema") != PROVENANCE_SCHEMA or not isinstance(index.get("cases"), list) or len(index["cases"]) != 14:
        raise ValueError("v2 provenance index must contain exactly 14 cases")
    python = "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
    repo = _repo_root()
    requests = []
    for entry in index["cases"]:
        sentinel_id = entry["sentinel_id"]
        safe_sid = sentinel_id.replace("-", "_")
        family = str(entry["family_id"])
        case_id = f"{safe_sid}_INITIAL_FRAME_EQUIV_V2"
        attempt_id = "initial-frame-equivalence-v2-001"
        input_paths = request_input_files(entry, current_path, review_path, index_path)
        input_files = [str(path) for path in input_paths]
        input_hashes = {str(path): sha256_file(path) for path in input_paths}
        script = str(Path(__file__).resolve())
        command = [
            python,
            script,
            "--run",
            "--current", str(current_path.resolve()),
            "--review", str(review_path.resolve()),
            "--provenance-index", str(index_path.resolve()),
            "--sentinel-id", sentinel_id,
            "--output", "{attempt_root}/initial-frame-check.json",
        ]
        request = {
            "schema": REQUEST_SCHEMA,
            "family_id": family,
            "case_id": case_id,
            "attempt_id": attempt_id,
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "cpu_threads": 2,
            "max_wall_seconds": 300,
            "estimated_storage_bytes": 67108864,
            "worktree_root": str(repo),
            "cwd": str(repo),
            "command": command,
            "input_files": input_files,
            "input_hashes": input_hashes,
            "resource_guard": {
                "owner": "stage2-reference-preparation",
                "runner": "ds_data02_stage2_dispatch.py",
                "strict_guard": "ds_data02_strict_dispatch_v1.py",
                "runtime": "ds_data02_runtime_v2.py",
                "launch_commit": git_commit(),
                "cpu_parent_binding": "required",
                "gpu": "none",
                "estimated_cpu_core_hours": 2 * 300 / 3600,
                "estimated_new_storage_bytes": 67108864,
                "full_hdf5_hash": "forbidden_by_scope",
            },
            "scope": {
                "sentinel_id": sentinel_id,
                "physical_case_id": entry["physical_case_id"],
                "frame_index": 0,
                "full_time_scan": False,
                "solver_started": False,
                "partvtk_started": False,
            },
        }
        path = output_dir / f"{safe_sid.lower()}-initial-frame-v2-001.json"
        atomic_write_once(path, request)
        requests.append(request)
    return requests


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-v2-selftest-") as temporary:
        root = Path(temporary)
        output = root / "output.json"
        atomic_write_once(output, {"status": "PASS"})
        original = output.read_bytes()
        try:
            atomic_write_once(output, {"status": "MUTATED"})
        except FileExistsError:
            pass
        else:
            raise AssertionError("output overwrite guard did not reject existing artifact")
        if output.read_bytes() != original:
            raise AssertionError("output overwrite guard changed an existing artifact")
        semantics = native_semantics({"Npiece": 2, "Piece": 0, "NpDynamic": False, "ReuseIds": False, "PeriMode": 0})
        if semantics.get("status") != "UNKNOWN":
            raise AssertionError("multi-piece manufactured counterexample was not UNKNOWN")
        if native_semantics({"Npiece": 1, "Piece": 0, "NpDynamic": False, "ReuseIds": False, "PeriMode": 0}).get("status") != "PASS":
            raise AssertionError("supported native contract was not PASS")
        if not all(name in TYPE_NAMES for name in (0, 1, 2, 3)):
            raise AssertionError("type semantics table is incomplete")
        payload = root / "payload.bin"
        payload.write_bytes(b"source")
        record = file_record(payload)
        if record["sha256"] != hashlib.sha256(b"source").hexdigest():
            raise AssertionError("manufactured source digest mismatch")
        return {"status": "PASS", "checks": ["output_exists_refused", "unsupported_piece_unknown", "type_semantics", "small_digest"]}


def failure_result(error: Exception, sentinel_id: str | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "FAILED",
        "scientific_acceptance": {"QI": "NOT_ASSESSED", "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED"},
        "error_type": type(error).__name__,
        "error": str(error),
        "scope": {"sentinel_id": sentinel_id or "UNKNOWN", "frame_index": 0, "full_time_scan": False, "solver_started": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--emit-provenance", type=Path)
    parser.add_argument("--emit-requests-dir", type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--provenance-index", type=Path)
    parser.add_argument("--sentinel-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.self_test:
            result = self_test()
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return 0
        if args.emit_provenance is not None:
            result = emit_provenance(args.current, args.review, args.emit_provenance)
            print(json.dumps({"status": "PASS", "cases": len(result["cases"]), "output": str(args.emit_provenance)}, ensure_ascii=False), flush=True)
            return 0
        if args.emit_requests_dir is not None:
            if args.provenance_index is None:
                raise ValueError("--emit-requests-dir requires --provenance-index")
            requests = emit_requests(args.current, args.review, args.provenance_index, args.emit_requests_dir)
            print(json.dumps({"status": "PASS", "requests": len(requests), "output_dir": str(args.emit_requests_dir)}, ensure_ascii=False), flush=True)
            return 0
        if not args.run:
            raise ValueError("choose --self-test, --emit-provenance, --emit-requests-dir, or --run")
        if args.provenance_index is None or args.sentinel_id is None or args.output is None:
            raise ValueError("--run requires --provenance-index, --sentinel-id, and --output")
        result = run_check(args.current, args.review, args.provenance_index, args.sentinel_id, args.output)
        print(json.dumps({"status": result["status"], "sentinel_id": args.sentinel_id, "output": str(args.output), "field_status": result["field_status"]}, ensure_ascii=False), flush=True)
        return 0 if result["status"] == "PASS" else 2
    except Exception as error:
        sentinel_id = args.sentinel_id
        failure = failure_result(error, sentinel_id)
        if args.output is None:
            print(json.dumps(failure, ensure_ascii=False), flush=True)
            return 2
        if args.output.exists():
            print(json.dumps({"status": "FAILED", "error_type": "OutputExists", "output_untouched": str(args.output)}, ensure_ascii=False), flush=True)
            return 2
        try:
            atomic_write_once(args.output, failure)
        except FileExistsError:
            print(json.dumps({"status": "FAILED", "error_type": "OutputExists", "output_untouched": str(args.output)}, ensure_ascii=False), flush=True)
            return 2
        print(json.dumps(failure, ensure_ascii=False), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
