#!/usr/bin/env python3
"""Scan every native BI4 frame for identity carry and finite-field closure.

This is a bounded audit over an already completed solver run.  It reuses the
existing ``ds_data02_f5_bi4.decode_frame`` adapter and its checked-in
``bi4_dump`` decoder, opens one raw ``Part_####.bi4`` at a time, and deletes
that frame's decoder scratch before advancing.  Raw frames are never copied
or renamed, no HDF5 file is opened or written, and no solver is started.

The native numerical axis is allowed to shrink: a frame's ``Idp`` set must be
a unique subset of frame zero and its count must agree with the producer's
``RunPARTs NpSave/NpSim`` count.  An absent ID is recorded as numerical-node
censoring only; this worker does not infer physical outflow, material fate, or
boundary meaning.  Reappearance, unknown IDs, duplicate IDs, non-finite
fields, count disagreement, and time disagreement are retained as bounded
findings and make the scan fail closed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
from typing import Any, Mapping

import numpy as np

# The shared adapter lives at the laboratory root.  Runner ``cwd`` is the
# worktree root, while Python's script directory is this nested campaign path;
# make the checked-in package import explicit for both launch modes.
_LAB_ROOT = Path(__file__).resolve().parents[5]
if str(_LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(_LAB_ROOT))
from scripts import ds_data02_f5_bi4 as direct_bi4


MANIFEST_SCHEMA = "ds-data-02.upstream-first.native-frame-scan-manifest.v1"
OUTPUT_SCHEMA = "ds-data-02.upstream-first.native-frame-identity-scan.v1"
NATIVE_INTEGRITY_SCHEMA = "ds-data-02.upstream-first.f1-native-integrity.v1"
FRAME_RE = re.compile(r"^Part_(\d{4,})\.bi4$", re.ASCII)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
CHUNK_BYTES = 8 * 1024 * 1024
TIME_TOLERANCE_S = 1.0e-6
MAX_ANOMALY_SAMPLES = 32
MAX_MILESTONES = 64


class FrameScanError(ValueError):
    """Raised when a native frame scan cannot close its source contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_fd(fd: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        block = os.pread(fd, min(CHUNK_BYTES, size - offset), offset)
        if not block:
            raise FrameScanError("raw frame truncated while hashing")
        digest.update(block)
        offset += len(block)
    if os.pread(fd, 1, size):
        raise FrameScanError("raw frame grew while hashing")
    return digest.hexdigest()


def _regular(path_value: str | Path, label: str, *, allow_symlink: bool = False) -> Path:
    path = Path(path_value).expanduser()
    if path.is_symlink() and not allow_symlink:
        raise FrameScanError(f"{label} is a symbolic link: {path}")
    if not path.is_file():
        raise FrameScanError(f"{label} is not a regular file: {path}")
    if not stat.S_ISREG(path.stat().st_mode):
        raise FrameScanError(f"{label} is not a regular file: {path}")
    return path


def _binding(value: Any, label: str) -> Path:
    if not isinstance(value, Mapping):
        raise FrameScanError(f"{label} binding is not an object")
    path = _regular(value.get("path", ""), label)
    expected_bytes = value.get("bytes")
    expected_hash = value.get("sha256")
    if not isinstance(expected_bytes, int) or expected_bytes < 0:
        raise FrameScanError(f"{label} byte binding is invalid")
    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        raise FrameScanError(f"{label} SHA-256 binding is invalid")
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes or _sha256(path) != expected_hash:
        raise FrameScanError(f"{label} hash/size differs from its manifest")
    return path


def _load_manifest(path: Path) -> dict[str, Any]:
    path = _regular(path, "frame scan manifest")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrameScanError("frame scan manifest is not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema") != MANIFEST_SCHEMA:
        raise FrameScanError(f"frame scan manifest schema must be {MANIFEST_SCHEMA!r}")
    for key in ("family_id", "case_id", "solver_root", "data_root", "decoder", "sources", "expected"):
        if key not in payload:
            raise FrameScanError(f"frame scan manifest lacks {key}")
    expected = payload["expected"]
    if not isinstance(expected, Mapping):
        raise FrameScanError("frame scan manifest expected section is not an object")
    for key in ("frame_count", "initial_particles", "minimum_time_end_s"):
        if key not in expected:
            raise FrameScanError(f"frame scan expected section lacks {key}")
    if not isinstance(expected["frame_count"], int) or expected["frame_count"] < 2:
        raise FrameScanError("frame count is outside the bounded scan contract")
    if not isinstance(expected["initial_particles"], int) or expected["initial_particles"] <= 0:
        raise FrameScanError("initial particle count is invalid")
    if (
        not isinstance(expected.get("excluded_particles"), int)
        or expected["excluded_particles"] < 0
        or expected["excluded_particles"] > expected["initial_particles"]
    ):
        raise FrameScanError("expected native exclusion count is invalid")
    if not isinstance(expected["minimum_time_end_s"], (int, float)) or expected["minimum_time_end_s"] < 0:
        raise FrameScanError("minimum time end is invalid")
    decoder = _binding(payload["decoder"], "BI4 decoder")
    payload["_decoder_path"] = str(decoder)
    source_bindings = payload["sources"]
    if not isinstance(source_bindings, Mapping):
        raise FrameScanError("frame scan sources section is not an object")
    resolved_sources: dict[str, str] = {}
    for key, value in source_bindings.items():
        resolved_sources[str(key)] = str(_binding(value, f"source {key}"))
    payload["_resolved_sources"] = resolved_sources
    integrity_path = resolved_sources.get("native_integrity")
    if integrity_path is None:
        raise FrameScanError("frame scan manifest lacks native_integrity source")
    try:
        integrity = json.loads(Path(integrity_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrameScanError("native integrity evidence is not valid JSON") from exc
    if (
        integrity.get("schema") != NATIVE_INTEGRITY_SCHEMA
        or integrity.get("status") != "verified"
        or integrity.get("case_id") != payload["case_id"]
    ):
        raise FrameScanError("native integrity evidence is not verified and case-bound")
    if Path(str(integrity.get("solver_root", ""))).expanduser().resolve() != Path(payload["solver_root"]).expanduser().resolve():
        raise FrameScanError("native integrity solver_root differs from frame scan manifest")
    integrity_hashes = integrity.get("source_hashes")
    if not isinstance(integrity_hashes, Mapping):
        raise FrameScanError("native integrity evidence lacks source_hashes")
    for key, value in source_bindings.items():
        if key == "native_integrity":
            continue
        if not isinstance(value, Mapping):
            raise FrameScanError(f"source {key} binding is not an object")
        expected_hash = integrity_hashes.get(f"{key}_sha256")
        if expected_hash != value.get("sha256"):
            raise FrameScanError(f"native integrity source hash does not match manifest source {key}")
    payload["_native_integrity"] = integrity
    return payload


def _number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FrameScanError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise FrameScanError(f"{label} is not finite: {value!r}")
    return number


def _integer(value: Any, label: str) -> int:
    try:
        number = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise FrameScanError(f"{label} is not an integer: {value!r}") from exc
    if number < 0:
        raise FrameScanError(f"{label} is negative: {value!r}")
    return number


def _runparts(path: Path, expected_count: int) -> list[dict[str, Any]]:
    lines = [
        line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    reader = csv.DictReader(lines, delimiter=";")
    required = {"Part", "TimeStep [s]", "NpSave", "NpSim"}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise FrameScanError("RunPARTs lacks Part/time/NpSave/NpSim fields")
    rows: list[dict[str, Any]] = []
    for ordinal, raw in enumerate(reader):
        part = _integer(raw.get("Part"), f"RunPARTs row {ordinal}.Part")
        if part != ordinal:
            raise FrameScanError("RunPARTs Part sequence is not contiguous from zero")
        rows.append(
            {
                "part": part,
                "time_s": _number(raw.get("TimeStep [s]"), f"RunPARTs row {ordinal}.time"),
                "np_save": _integer(raw.get("NpSave"), f"RunPARTs row {ordinal}.NpSave"),
                "np_sim": _integer(raw.get("NpSim"), f"RunPARTs row {ordinal}.NpSim"),
            }
        )
    if len(rows) != expected_count:
        raise FrameScanError(
            f"RunPARTs row count {len(rows)} differs from expected frame count {expected_count}"
        )
    if rows[0]["time_s"] > TIME_TOLERANCE_S:
        raise FrameScanError("RunPARTs does not begin at time zero")
    if any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise FrameScanError("RunPARTs times are not strictly increasing")
    if any(row["time_s"] < -TIME_TOLERANCE_S for row in rows):
        raise FrameScanError("RunPARTs contains a negative saved time")
    return rows


def _frame_paths(data_root: Path, expected_count: int) -> list[Path]:
    root = Path(data_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise FrameScanError(f"native data root is not a regular directory: {root}")
    indexed: list[tuple[int, Path]] = []
    for path in root.glob("Part_*.bi4"):
        if path.is_symlink() or not path.is_file():
            raise FrameScanError(f"native frame is not a regular file: {path}")
        match = FRAME_RE.fullmatch(path.name)
        if match is None:
            raise FrameScanError(f"native frame name is outside the bounded contract: {path.name}")
        indexed.append((int(match.group(1)), path))
    indexed.sort()
    if len(indexed) != expected_count or [index for index, _ in indexed] != list(range(expected_count)):
        raise FrameScanError(
            f"native frame sequence is not exactly Part_0000..Part_{expected_count - 1:04d}"
        )
    return [path for _, path in indexed]


def _runout_summary(path: Path, expected_initial: int) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    initial = re.search(r"Particles of simulation \(initial\):\s*([0-9,]+)", text)
    excluded = re.search(r"Excluded particles\.*:\s*([0-9,]+)", text)
    events = list(
        re.finditer(
            r"Particles out:\s*([0-9,]+)\s*\(total out:\s*([0-9,]+)\)\s*-\s*Current np:\s*([0-9,]+)",
            text,
            flags=re.IGNORECASE,
        )
    )
    if initial is None or excluded is None or not events:
        raise FrameScanError("Run.out lacks the native initial/exclusion/event ledger")
    initial_count = _integer(initial.group(1), "Run.out initial particles")
    excluded_count = _integer(excluded.group(1), "Run.out excluded particles")
    terminal = events[-1]
    terminal_total = _integer(terminal.group(2), "Run.out terminal total out")
    terminal_current = _integer(terminal.group(3), "Run.out terminal current particles")
    if initial_count != expected_initial:
        raise FrameScanError("Run.out initial particle count differs from manifest")
    if terminal_total != excluded_count or terminal_current != initial_count - excluded_count:
        raise FrameScanError("Run.out terminal event does not close its native count ledger")
    return {
        "initial_particles": initial_count,
        "excluded_particles": excluded_count,
        "event_count": len(events),
        "terminal_total_out": terminal_total,
        "terminal_current_particles": terminal_current,
    }


def _native_exclusion_summary(integrity: Mapping[str, Any], expected_initial: int) -> dict[str, Any]:
    """Validate the already decoded native exclusion records without copying them."""
    rows = integrity.get("native_rows")
    if not isinstance(rows, list):
        raise FrameScanError("native integrity evidence lacks retained native_rows")
    record = integrity.get("excluded_particle_records")
    if not isinstance(record, Mapping) or record.get("present") is not True:
        raise FrameScanError("native integrity evidence lacks its excluded-record binding")
    record_count = record.get("record_count")
    if not isinstance(record_count, int) or record_count != len(rows):
        raise FrameScanError("native excluded-record count does not match retained rows")
    ids: list[int] = []
    motives: Counter[str] = Counter()
    for ordinal, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise FrameScanError(f"native exclusion row {ordinal} is not an object")
        idp = row.get("idp")
        if isinstance(idp, bool) or not isinstance(idp, int) or not 0 <= idp < expected_initial:
            raise FrameScanError(f"native exclusion row {ordinal} has an invalid Idp")
        motive = row.get("motive")
        if not isinstance(motive, str) or not motive:
            raise FrameScanError(f"native exclusion row {ordinal} lacks its native motive")
        ids.append(idp)
        motives[motive] += 1
    sorted_ids = np.asarray(sorted(ids), dtype=np.uint32)
    if sorted_ids.size != np.unique(sorted_ids).size:
        raise FrameScanError("native exclusion records contain duplicate Idp values")
    if record_count != len(ids):
        raise FrameScanError("native exclusion record count is inconsistent")
    if record.get("raw_native_fields_retained") is not True:
        raise FrameScanError("native exclusion evidence does not retain raw native fields")
    records_path = _binding(record, "native excluded-record CSV")
    digest = hashlib.sha256(np.ascontiguousarray(sorted_ids).tobytes()).hexdigest()
    return {
        "record_count": record_count,
        "ids_sorted": sorted_ids,
        "id_set_sha256": digest,
        "motive_counts": dict(sorted(motives.items())),
        "records_source": str(records_path),
        "records_source_bytes": records_path.stat().st_size,
        "records_source_sha256": record.get("sha256"),
        "raw_native_fields_retained": True,
    }


def _typed_cohort(generated_xml: Path, expected_initial: int) -> dict[str, Any]:
    """Read the generated XML's explicit numerical ranges via the existing adapter."""
    try:
        parsed = direct_bi4.parse_particle_blocks(generated_xml)
    except (OSError, ValueError, direct_bi4.DirectConversionError) as exc:
        raise FrameScanError(f"generated XML typed cohort cannot be parsed: {exc}") from exc
    if parsed["np"] != expected_initial:
        raise FrameScanError(
            f"generated XML cohort size {parsed['np']} differs from expected initial {expected_initial}"
        )
    blocks = parsed["blocks"]
    fixed = [block for block in blocks if block["tag"] == "fixed"]
    if not fixed:
        raise FrameScanError("generated XML does not explicitly define fixed particle ranges")
    return {
        "np": parsed["np"],
        "blocks": blocks,
        "fixed_ranges": [(int(block["begin"]), int(block["begin"] + block["count"])) for block in fixed],
        "fixed_count": sum(int(block["count"]) for block in fixed),
        "xml_sha256": parsed["xml_sha256"],
    }


def _finite_counts(frame: direct_bi4.DecodedFrame) -> dict[str, int]:
    arrays = {
        "position": np.asarray(frame.position),
        "velocity": np.asarray(frame.velocity),
        "density": np.asarray(frame.density),
    }
    counts: dict[str, int] = {}
    for name, array in arrays.items():
        if name in {"position", "velocity"}:
            if array.ndim != 2 or array.shape[1] != 3:
                raise FrameScanError(f"decoded {name} shape is not (N,3)")
            counts[name] = int(array.shape[0] - np.isfinite(array).all(axis=1).sum())
        else:
            if array.ndim != 1:
                raise FrameScanError(f"decoded {name} shape is not (N,)")
            counts[name] = int(array.shape[0] - np.isfinite(array).sum())
    return counts


def _digest_row(digest: hashlib._Hash, row: Mapping[str, Any]) -> None:
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    digest.update(encoded)
    digest.update(b"\n")


def _sample(mapping: dict[str, list[int]], key: str, values: np.ndarray) -> None:
    if len(mapping[key]) >= MAX_ANOMALY_SAMPLES:
        return
    remaining = MAX_ANOMALY_SAMPLES - len(mapping[key])
    mapping[key].extend(int(value) for value in np.asarray(values).reshape(-1)[:remaining])


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FrameScanError(f"refusing to overwrite scan report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".partial-{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def scan(manifest_path: Path, output: Path, *, max_wall_seconds: float) -> dict[str, Any]:
    if max_wall_seconds <= 0:
        raise FrameScanError("max-wall-seconds must be positive")
    deadline = time.monotonic() + max_wall_seconds
    manifest = _load_manifest(manifest_path)
    expected = manifest["expected"]
    expected_count = int(expected["frame_count"])
    expected_initial = int(expected["initial_particles"])
    solver_root = Path(manifest["solver_root"]).expanduser().resolve()
    data_root = Path(manifest["data_root"]).expanduser().resolve()
    if not data_root.is_relative_to(solver_root):
        raise FrameScanError("native data root escapes solver root")
    runparts_path = Path(manifest["_resolved_sources"]["runparts"])
    runout_path = Path(manifest["_resolved_sources"]["run_out"])
    runparts = _runparts(runparts_path, expected_count)
    runout = _runout_summary(runout_path, expected_initial)
    native_exclusions = _native_exclusion_summary(manifest["_native_integrity"], expected_initial)
    if runout["excluded_particles"] != expected["excluded_particles"]:
        raise FrameScanError("Run.out native exclusion count differs from manifest expected count")
    if native_exclusions["record_count"] != expected["excluded_particles"]:
        raise FrameScanError("retained native exclusion records differ from manifest expected count")
    cohort = _typed_cohort(Path(manifest["_resolved_sources"]["generated_xml"]), expected_initial)
    paths = _frame_paths(data_root, expected_count)
    decoder = Path(manifest["_decoder_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = output.parent / f".native-frame-scan-scratch-{os.getpid()}"
    if scratch.exists() or scratch.is_symlink():
        raise FrameScanError(f"stale decoder scratch exists: {scratch}")
    scratch.mkdir(parents=True)

    hash_digest = hashlib.sha256()
    observation_digest = hashlib.sha256()
    initial_ids: np.ndarray | None = None
    previously_missing: np.ndarray | None = None
    active_histogram: Counter[str] = Counter()
    missing_histogram: Counter[str] = Counter()
    first_missing_histogram: Counter[str] = Counter()
    milestones: list[dict[str, Any]] = []
    anomaly_samples: dict[str, list[int]] = {
        "unknown_ids": [],
        "reappeared_ids": [],
        "nonfinite_position_ids": [],
        "nonfinite_velocity_ids": [],
        "nonfinite_density_ids": [],
    }
    totals = {
        "unknown_id_records": 0,
        "duplicate_id_records": 0,
        "reappeared_id_records": 0,
        "nonfinite_position_records": 0,
        "nonfinite_velocity_records": 0,
        "nonfinite_density_records": 0,
        "time_mismatch_frames": 0,
        "negative_time_frames": 0,
        "count_mismatch_frames": 0,
        "fixed_boundary_missing_records": 0,
        "fixed_boundary_missing_frames": 0,
    }
    fatal_findings: list[str] = []
    frame_count_changes = 0
    prior_active: int | None = None
    initial_time: float | None = None
    final_time: float | None = None
    dynamic_contract: dict[str, Any] | None = None
    source_frame_bytes = 0
    finite_frames_checked = 0
    fixed_boundary_missing_sample: list[int] = []
    try:
        for index, path in enumerate(paths):
            if time.monotonic() > deadline:
                raise FrameScanError("native frame scan wall limit exceeded")
            stat_before = path.stat()
            if stat_before.st_nlink != 1:
                raise FrameScanError(f"native frame has unexpected hard-link count: {path}")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
            try:
                held_before = os.fstat(fd)
                expected_hash = _sha256_fd(fd, held_before.st_size)
                frame = direct_bi4.decode_frame(path, decoder, scratch, index)
                held_after = os.fstat(fd)
                actual_after = _sha256_fd(fd, held_after.st_size)
            finally:
                os.close(fd)
            if held_before.st_size != held_after.st_size or expected_hash != actual_after:
                raise FrameScanError(f"native frame changed while decoding: {path}")
            source_frame_bytes += held_before.st_size
            hash_digest.update(path.name.encode("ascii"))
            hash_digest.update(b"\0")
            hash_digest.update(str(held_before.st_size).encode("ascii"))
            hash_digest.update(b"\0")
            hash_digest.update(expected_hash.encode("ascii"))
            hash_digest.update(b"\n")

            ids = np.asarray(frame.ids)
            if ids.ndim != 1 or ids.dtype != np.dtype("<u4") or ids.size == 0:
                raise FrameScanError(f"decoded Idp axis is not a nonempty uint32 vector: {path}")
            finite_counts = _finite_counts(frame)
            finite_frames_checked += 1
            try:
                frame_dynamic = direct_bi4._reject_dynamic_contract(
                    Path(manifest["_resolved_sources"]["generated_xml"]), frame.metadata
                )
            except (OSError, ValueError, direct_bi4.DirectConversionError) as exc:
                raise FrameScanError(f"frame {index} fails the single-piece Zone0 contract: {exc}") from exc
            if dynamic_contract is None:
                dynamic_contract = frame_dynamic
            elif frame_dynamic != dynamic_contract:
                raise FrameScanError(f"frame {index} changes its single-piece metadata contract")
            for key, value in finite_counts.items():
                totals[f"nonfinite_{key}_records"] += value
            if initial_ids is None:
                initial_ids = ids.copy()
                if ids.size != expected_initial:
                    raise FrameScanError(
                        f"frame zero active count {ids.size} differs from expected initial {expected_initial}"
                    )
                if not np.array_equal(initial_ids, np.arange(expected_initial, dtype=np.uint32)):
                    raise FrameScanError("frame zero Idp axis differs from the generated XML numerical cohort")
                previously_missing = np.zeros(ids.size, dtype=bool)
                initial_time = float(frame.time)
            assert initial_ids is not None and previously_missing is not None
            if ids.size != runparts[index]["np_save"] or ids.size != runparts[index]["np_sim"]:
                totals["count_mismatch_frames"] += 1
            sorted_ids = ids  # decode_frame returns stable Idp order
            duplicate_mask = np.zeros(sorted_ids.size, dtype=bool)
            if sorted_ids.size > 1:
                duplicate_mask[1:] = sorted_ids[1:] == sorted_ids[:-1]
            duplicate_count = int(duplicate_mask.sum())
            totals["duplicate_id_records"] += duplicate_count

            positions = np.searchsorted(initial_ids, sorted_ids)
            in_range = positions < initial_ids.size
            safe_positions = np.minimum(positions, initial_ids.size - 1)
            known = in_range & (initial_ids[safe_positions] == sorted_ids)
            unknown_ids = sorted_ids[~known]
            totals["unknown_id_records"] += int(unknown_ids.size)
            _sample(anomaly_samples, "unknown_ids", unknown_ids)
            present = np.zeros(initial_ids.size, dtype=bool)
            present[positions[known]] = True
            missing = ~present
            fixed_missing = 0
            for begin, end in cohort["fixed_ranges"]:
                left = int(np.searchsorted(sorted_ids, begin, side="left"))
                right = int(np.searchsorted(sorted_ids, end, side="left"))
                fixed_missing += (end - begin) - (right - left)
            if fixed_missing:
                totals["fixed_boundary_missing_records"] += fixed_missing
                totals["fixed_boundary_missing_frames"] += 1
                if len(fixed_boundary_missing_sample) < MAX_ANOMALY_SAMPLES:
                    for begin, end in cohort["fixed_ranges"]:
                        left = int(np.searchsorted(sorted_ids, begin, side="left"))
                        right = int(np.searchsorted(sorted_ids, end, side="left"))
                        expected_ids = np.arange(begin, end, dtype=np.uint32)
                        present_ids = sorted_ids[left:right]
                        missing_fixed = expected_ids[~np.isin(expected_ids, present_ids)]
                        fixed_boundary_missing_sample.extend(
                            int(value) for value in missing_fixed[: MAX_ANOMALY_SAMPLES - len(fixed_boundary_missing_sample)]
                        )
            new_missing = missing & ~previously_missing
            reappeared = previously_missing & present
            reappeared_ids = initial_ids[reappeared]
            totals["reappeared_id_records"] += int(reappeared_ids.size)
            _sample(anomaly_samples, "reappeared_ids", reappeared_ids)
            previously_missing |= missing

            finite_id_indices = np.arange(ids.size, dtype=np.int64)
            for field, sample_key in (
                ("position", "nonfinite_position_ids"),
                ("velocity", "nonfinite_velocity_ids"),
                ("density", "nonfinite_density_ids"),
            ):
                array = np.asarray(getattr(frame, field))
                valid_rows = np.isfinite(array).all(axis=1) if array.ndim == 2 else np.isfinite(array)
                _sample(anomaly_samples, sample_key, ids[~valid_rows])

            time_s = float(frame.time)
            if not math.isfinite(time_s) or abs(time_s - runparts[index]["time_s"]) > TIME_TOLERANCE_S:
                totals["time_mismatch_frames"] += 1
            if time_s < -TIME_TOLERANCE_S:
                totals["negative_time_frames"] = totals.get("negative_time_frames", 0) + 1
            if prior_active is not None and ids.size != prior_active:
                frame_count_changes += 1
            prior_active = int(ids.size)
            final_time = time_s
            active_histogram[str(ids.size)] += 1
            missing_histogram[str(int(missing.sum()))] += 1
            first_missing_histogram[str(index)] += int(new_missing.sum())
            row = {
                "frame": index,
                "name": path.name,
                "bytes": held_before.st_size,
                "sha256": expected_hash,
                "time_s": time_s,
                "expected_time_s": runparts[index]["time_s"],
                "active_count": int(ids.size),
                "expected_active_count": runparts[index]["np_save"],
                "missing_count": int(missing.sum()),
                "fixed_boundary_missing_count": int(fixed_missing),
                "unknown_count": int(unknown_ids.size),
                "reappeared_count": int(reappeared_ids.size),
                "nonfinite": finite_counts,
            }
            _digest_row(observation_digest, row)
            if (
                index == 0
                or index == expected_count - 1
                or len(milestones) < MAX_MILESTONES
                and (index % max(1, expected_count // MAX_MILESTONES) == 0)
            ):
                if len(milestones) < MAX_MILESTONES:
                    milestones.append(row)
            frame_scratch = scratch / f"frame_{index:04d}"
            frame_xml = scratch / f"frame_{index:04d}.xml"
            if frame_scratch.exists():
                shutil.rmtree(frame_scratch)
            if frame_xml.exists() or frame_xml.is_symlink():
                frame_xml.unlink()
            del frame
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)

    if initial_ids is None or previously_missing is None:
        raise FrameScanError("no native frames were decoded")
    if initial_time is None or final_time is None:
        raise FrameScanError("native frame time axis was not decoded")
    missing_ids = initial_ids[previously_missing]
    if final_time < float(expected["minimum_time_end_s"]) - TIME_TOLERANCE_S:
        totals["time_mismatch_frames"] += 1
    final_missing_matches_native = np.array_equal(missing_ids, native_exclusions["ids_sorted"])
    if not final_missing_matches_native:
        fatal_findings.append(
            "final missing Idp set does not equal the retained native exclusion Idp set"
        )
    if native_exclusions["record_count"] != runout["excluded_particles"]:
        fatal_findings.append("retained native exclusion count differs from the Run.out terminal count")
    for key, value in (
        ("unknown IDs", totals["unknown_id_records"]),
        ("duplicate IDs", totals["duplicate_id_records"]),
        ("non-finite values", sum(totals[key] for key in ("nonfinite_position_records", "nonfinite_velocity_records", "nonfinite_density_records"))),
        ("time mismatches", totals["time_mismatch_frames"]),
        ("count mismatches", totals["count_mismatch_frames"]),
        ("fixed-boundary carry gaps", totals["fixed_boundary_missing_records"]),
        ("reappeared IDs", totals["reappeared_id_records"]),
        ("negative times", totals.get("negative_time_frames", 0)),
    ):
        if value:
            fatal_findings.append(f"{key}: {value}")
    report = {
        "schema": OUTPUT_SCHEMA,
        "status": "verified" if not fatal_findings else "failed",
        "family_id": manifest["family_id"],
        "case_id": manifest["case_id"],
        "reference_role": manifest.get("reference_role"),
        "solver_root": str(solver_root),
        "native_data_root": str(data_root),
        "decoder": {
            "path": str(decoder),
            "sha256": _sha256(decoder),
            "existing_adapter": "scripts.ds_data02_f5_bi4.decode_frame",
            "native_binary_invoked": True,
        },
        "dynamic_contract": dynamic_contract,
        "coverage": {
            "frame_count": expected_count,
            "first_frame": paths[0].name,
            "last_frame": paths[-1].name,
            "frame_bytes_total": source_frame_bytes,
            "frame_hash_sequence_sha256": hash_digest.hexdigest(),
            "observation_sequence_sha256": observation_digest.hexdigest(),
            "raw_frames_opened_one_at_a_time": True,
            "raw_frames_staged_or_copied": False,
            "hdf5_opened": False,
            "solver_started": False,
        },
        "source_bindings": {
            key: {"path": path, "bytes": Path(path).stat().st_size, "sha256": _sha256(Path(path))}
            for key, path in manifest["_resolved_sources"].items()
        },
        "time_axis": {
            "first_s": initial_time,
            "last_s": final_time,
            "minimum_required_end_s": expected["minimum_time_end_s"],
            "runparts_tolerance_s": TIME_TOLERANCE_S,
            "strictly_increasing_runparts": True,
        },
        "identity_axis": {
            "key": "native Idp",
            "initial_count": int(initial_ids.size),
            "initial_ids_sha256": hashlib.sha256(np.ascontiguousarray(initial_ids).tobytes()).hexdigest(),
            "final_missing_count": int(missing_ids.size),
            "final_missing_ids_sha256": hashlib.sha256(np.ascontiguousarray(missing_ids).tobytes()).hexdigest(),
            "unknown_id_records": totals["unknown_id_records"],
            "duplicate_id_records": totals["duplicate_id_records"],
            "reappeared_id_records": totals["reappeared_id_records"],
            "generated_cohort": cohort["blocks"],
            "all_ids_unique_and_in_generated_cohort": not totals["unknown_id_records"] and not totals["duplicate_id_records"],
            "missing_ids_are_numerical_censoring": True,
            "physical_fate_inferred": False,
            "boundary_or_fluid_material_semantics_inferred": False,
            "carry_contract": "each frame carries a unique subset of the frame-zero native numerical IDs; absent IDs remain censored unless reappearance is observed",
        },
        "count_semantics": {
            "active_count_source": "decoded Idp array length",
            "producer_count_source": "RunPARTs NpSave and NpSim",
            "active_count_histogram": dict(sorted(active_histogram.items(), key=lambda item: int(item[0]))),
            "missing_count_histogram": dict(sorted(missing_histogram.items(), key=lambda item: int(item[0]))),
            "first_missing_frame_histogram": dict(sorted(first_missing_histogram.items(), key=lambda item: int(item[0]))),
            "frame_count_change_events": frame_count_changes,
            "boundary_carry_policy": "boundary nodes are carried by their native Idp exactly like all other numerical nodes; this scan does not classify type or material fate",
            "fixed_boundary_carry": {
                "status": "verified",
                "source": "generated XML fixed particle ranges",
                "expected_fixed_count": cohort["fixed_count"],
                "missing_records": totals["fixed_boundary_missing_records"],
                "missing_frames": totals["fixed_boundary_missing_frames"],
                "missing_id_sample": fixed_boundary_missing_sample,
                "classification_scope": "fixed numerical boundary ranges explicitly declared by generated XML; no physical material-fate inference",
            },
        },
        "finite_field_audit": {
            "frames_checked": finite_frames_checked,
            "all_frames_checked": finite_frames_checked == expected_count,
            "nonfinite_position_records": totals["nonfinite_position_records"],
            "nonfinite_velocity_records": totals["nonfinite_velocity_records"],
            "nonfinite_density_records": totals["nonfinite_density_records"],
            "fields_checked": ["position", "velocity", "density"],
        },
        "runout_ledger": runout,
        "native_exclusions": {
            "record_count": native_exclusions["record_count"],
            "excluded_particles_runout": runout["excluded_particles"],
            "final_missing_count": int(missing_ids.size),
            "final_missing_matches_native_ids": final_missing_matches_native,
            "id_set_sha256": native_exclusions["id_set_sha256"],
            "motive_counts": native_exclusions["motive_counts"],
            "records_source": native_exclusions["records_source"],
            "records_source_bytes": native_exclusions["records_source_bytes"],
            "records_source_sha256": native_exclusions["records_source_sha256"],
            "raw_native_fields_retained": native_exclusions["raw_native_fields_retained"],
            "native_cause_semantics": "PartOut Motive is retained as the native numerical exclusion cause; physical fate remains unknown",
        },
        "milestones": milestones,
        "anomaly_samples": anomaly_samples,
        "fatal_findings": fatal_findings,
    }
    _write_report(output, report)
    if fatal_findings:
        raise FrameScanError("native frame scan failed: " + "; ".join(fatal_findings[:8]))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-wall-seconds", type=float, default=3600.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = scan(args.manifest, args.output, max_wall_seconds=args.max_wall_seconds)
    except (OSError, FrameScanError, RuntimeError, ValueError) as exc:
        print(f"native frame identity scan failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
