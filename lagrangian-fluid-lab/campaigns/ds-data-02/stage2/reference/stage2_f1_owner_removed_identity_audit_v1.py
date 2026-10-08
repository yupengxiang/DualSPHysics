#!/usr/bin/env python3
"""Identify a bounded F1 native particle removal.

The terminal F1 dp=.0025 half-CFL receipt reports one native particle fewer
than the source run.  This audit decodes only the first and last saved BI4
frames and reads only their official decoder ``Idp.bin`` arrays.  It compares
the ID sets, classifies any difference against the exact solver XML ranges,
and records raw-frame/source stat and SHA evidence.  It does not read
positions, velocities, density, HDF5, or any other frame.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


SCHEMA = "ds02.stage2.f1.owner-removed-identity-audit.v1"
PART_RE = re.compile(r"^Part_(\d+)\.bi4$")


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def file_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular file is missing or symlinked: {path}")
    stat = path.stat()
    digest, size = sha256_file(path)
    return {
        "path": str(path), "bytes": int(size), "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns), "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino), "sha256": digest,
    }


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_runparts(path: Path) -> list[dict[str, Any]]:
    lines = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(lines, delimiter=";"):
        part_raw = (row.get("Part") or "").strip().split()[0]
        time_raw = (row.get("TimeStep [s]") or "").strip().split()[0]
        if not part_raw.isdigit():
            continue
        time_s = float(time_raw)
        if not math.isfinite(time_s):
            raise ValueError(f"non-finite RunPARTs time: {path}")
        rows.append({"part": int(part_raw), "time_s": time_s})
    if not rows or [row["part"] for row in rows] != list(range(len(rows))):
        raise ValueError(f"RunPARTs is not contiguous from zero: {path}")
    if any(next_row["time_s"] <= row["time_s"] for row, next_row in zip(rows, rows[1:])):
        raise ValueError(f"RunPARTs times are not strictly increasing: {path}")
    return rows


def parse_particle_ranges(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    particles_nodes = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "particles"]
    if len(particles_nodes) != 1:
        raise ValueError(f"expected one XML particles node, found {len(particles_nodes)}")
    particles = particles_nodes[0]
    ranges: list[dict[str, Any]] = []
    for node in list(particles):
        kind = node.tag.rsplit("}", 1)[-1].lower()
        if kind not in {"fixed", "moving", "floating", "fluid"}:
            continue
        if not all(key in node.attrib for key in ("begin", "count", "mk")):
            continue  # summary row, not a typed range
        begin = int(node.attrib["begin"])
        count = int(node.attrib["count"])
        if begin < 0 or count <= 0:
            raise ValueError(f"invalid particle range {begin}/{count}")
        mkfluid = node.attrib.get("mkfluid")
        ranges.append({
            "kind": kind, "begin": begin, "count": count,
            "end_exclusive": begin + count, "mk_absolute": int(node.attrib["mk"]),
            "mkfluid_relative": int(mkfluid) if mkfluid is not None else None,
            "refmotion": node.attrib.get("refmotion"),
        })
    ranges.sort(key=lambda item: item["begin"])
    if not ranges:
        raise ValueError("XML particles node contains no typed ranges")
    for previous, current in zip(ranges, ranges[1:]):
        if current["begin"] < previous["end_exclusive"]:
            raise ValueError("XML particle ranges overlap")
    return {
        "particles_summary": dict(particles.attrib),
        "ranges": ranges,
        "massfluid_kg": next((float(node.attrib["value"]) for node in particles if node.tag.rsplit("}", 1)[-1] == "massfluid"), None),
    }


def classify_id(identifier: int, ranges: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [item for item in ranges if item["begin"] <= identifier < item["end_exclusive"]]
    if len(matches) != 1:
        return {"id": int(identifier), "status": "UNKNOWN_ID_RANGE", "matching_range_count": len(matches)}
    item = matches[0]
    return {
        "id": int(identifier), "status": "PASS_XML_RANGE_CLASSIFIED",
        "kind": item["kind"], "mk_absolute": item["mk_absolute"],
        "mkfluid_relative": item["mkfluid_relative"], "refmotion": item["refmotion"],
        "range_begin": item["begin"], "range_end_exclusive": item["end_exclusive"],
        "offset_in_range": int(identifier - item["begin"]),
    }


def decoder_particle_paths(prefix: Path) -> tuple[dict[str, Any], Path]:
    xml_path = Path(str(prefix) + ".xml")
    if not xml_path.is_file():
        raise RuntimeError(f"decoder did not produce XML: {xml_path}")
    root = ET.parse(xml_path).getroot()
    outer = root.find("item")
    particle = root.find(".//item/item")
    if particle is None or not particle.get("name"):
        raise RuntimeError("decoder XML has no particle item")
    def named(node: ET.Element | None) -> dict[str, Any]:
        if node is None:
            return {}
        return {child.get("name"): child.get("v") for child in node if child.get("name")}
    return {"xml_path": xml_path, "metadata": named(outer), "info": named(particle)}, Path(temporary_path(prefix, particle.get("name")))


def temporary_path(prefix: Path, name: str) -> str:
    return str(prefix / name)


def decode_ids(frame_path: Path, decoder: Path, scratch_root: Path, frame: int) -> dict[str, Any]:
    frame_path = frame_path.expanduser().resolve()
    if frame_path.is_symlink() or not frame_path.is_file():
        raise ValueError(f"selected frame is not a regular file: {frame_path}")
    before = file_record(frame_path)
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"removed-id-{frame:04d}-", dir=scratch_root) as temporary:
        prefix = Path(temporary) / "decoded"
        completed = subprocess.run([str(decoder), str(frame_path), str(prefix)], check=True, capture_output=True, text=True, timeout=600)
        decoder_xml, data_root = decoder_particle_paths(prefix)
        ids_path = data_root / "Idp.bin"
        if not ids_path.is_file():
            raise RuntimeError(f"decoder output lacks Idp.bin for frame {frame}")
        ids = np.fromfile(ids_path, dtype=np.dtype("<u4"))
        if ids.size == 0 or np.unique(ids).size != ids.size:
            raise RuntimeError(f"frame {frame} Idp is empty or duplicated")
        ids.sort()
        metadata = {**decoder_xml["metadata"], **decoder_xml["info"]}
        after = file_record(frame_path)
        if before != after:
            raise RuntimeError(f"native frame mutated while decoding: frame {frame}")
        return {
            "frame": frame, "saved_file": before, "id_count": int(ids.size),
            "id_min": int(ids[0]), "id_max": int(ids[-1]),
            "id_sha256": hashlib.sha256(np.ascontiguousarray(ids).tobytes()).hexdigest(),
            "ids": ids, "decoder_xml_sha256": file_record(decoder_xml["xml_path"])["sha256"],
            "decoder_semantics": {key: metadata.get(key, "UNKNOWN_NOT_EXPOSED_BY_DECODER") for key in ("Npiece", "Piece", "NpDynamic", "ReuseIds", "PeriMode")},
            "decoder_stdout": completed.stdout[-500:], "decoder_stderr": completed.stderr[-500:],
        }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = args.raw_root.expanduser().resolve()
    runparts = args.runparts.expanduser().resolve()
    xml_path = args.generated_xml.expanduser().resolve()
    receipt_path = args.receipt.expanduser().resolve()
    decoder = args.decoder.expanduser().resolve()
    output = args.output.expanduser().resolve()
    rows = read_runparts(runparts)
    if args.expected_frame_count is not None and len(rows) != args.expected_frame_count:
        raise ValueError(f"RunPARTs rows {len(rows)} != expected {args.expected_frame_count}")
    if abs(rows[-1]["time_s"] - args.expected_final_time_s) > args.final_time_tolerance_s:
        raise ValueError("RunPARTs final time differs from bound receipt")
    source = parse_particle_ranges(xml_path)
    pre = {"runparts": file_record(runparts), "generated_xml": file_record(xml_path), "receipt": file_record(receipt_path)}
    initial = decode_ids(raw_root / f"Part_{rows[0]['part']:04d}.bi4", decoder, args.scratch_root.expanduser().resolve(), rows[0]["part"])
    terminal = decode_ids(raw_root / f"Part_{rows[-1]['part']:04d}.bi4", decoder, args.scratch_root.expanduser().resolve(), rows[-1]["part"])
    initial_ids = initial.pop("ids")
    terminal_ids = terminal.pop("ids")
    removed = np.setdiff1d(initial_ids, terminal_ids, assume_unique=True)
    added = np.setdiff1d(terminal_ids, initial_ids, assume_unique=True)
    post = {"runparts": file_record(runparts), "generated_xml": file_record(xml_path), "receipt": file_record(receipt_path)}
    if pre != post:
        raise RuntimeError("audit input changed during two-frame identity decode")
    removed_classification = [classify_id(int(value), source["ranges"]) for value in removed]
    added_classification = [classify_id(int(value), source["ranges"]) for value in added]
    if removed.size == 1 and added.size == 0:
        identity_status = "PASS_EXPECTED_ONE_REMOVED"
    else:
        identity_status = "UNKNOWN_UNEXPECTED_ID_SET"
    return {
        "schema": SCHEMA, "status": "COMPLETED_F1_REMOVED_IDENTITY_AUDIT",
        "scope": {"first_and_last_frames_only": True, "decoded_fields": ["Idp"], "positions_read": False, "velocities_read": False, "density_read": False, "hdf5_read": False, "full_native_tree_scanned": False, "solver_started": False},
        "inputs": {"pre": pre, "post": post, "pre_post_complete_stat_and_sha_equal": True},
        "source": {"runparts": str(runparts), "generated_xml": str(xml_path), "raw_root": str(raw_root), "particle_ranges": source, "first_frame": initial, "terminal_frame": terminal},
        "identity_delta": {"initial_count": int(initial["id_count"]), "terminal_count": int(terminal["id_count"]), "removed_count": int(removed.size), "added_count": int(added.size), "removed": removed_classification, "added": added_classification, "status": identity_status},
        "time_window": {"first_saved_time_s": rows[0]["time_s"], "terminal_saved_time_s": rows[-1]["time_s"], "terminal_frame": rows[-1]["part"]},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "identity diagnostic only; no field accuracy or scientific qualification"},
    }


def self_test() -> dict[str, Any]:
    ranges = [{"kind": "fluid", "begin": 10, "count": 3, "end_exclusive": 13, "mk_absolute": 1, "mkfluid_relative": 0, "refmotion": None}]
    assert classify_id(11, ranges)["status"] == "PASS_XML_RANGE_CLASSIFIED"
    assert classify_id(99, ranges)["status"] == "UNKNOWN_ID_RANGE"
    return {"status": "PASS", "native_decode": False, "positions_read": False, "identity_classification": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--runparts", type=Path)
    parser.add_argument("--generated-xml", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--decoder", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--expected-frame-count", type=int)
    parser.add_argument("--expected-final-time-s", type=float)
    parser.add_argument("--final-time-tolerance-s", type=float, default=1e-12)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    required = (args.raw_root, args.runparts, args.generated_xml, args.receipt, args.decoder, args.scratch_root, args.expected_frame_count, args.expected_final_time_s, args.output)
    if any(value is None for value in required):
        parser.error("all audit input, bound frame/time, scratch, and output arguments are required")
    result = audit(args)
    atomic_json(args.output, result)
    print(json.dumps({"status": result["status"], "identity": result["identity_delta"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
