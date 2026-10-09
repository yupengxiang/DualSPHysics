#!/usr/bin/env python3
"""Stream the complete ROOT133 native window through bounded BI4 decoding.

This is a forward-only full-window worker.  It processes exactly the 836
``Part_*.bi4`` files named by the terminal RunPARTs axis, one file at a time.
Each source is hashed with a stat-before/stat-after check immediately after
parent reservation, decoded by the official ``bi4_dump`` binary in a fresh
bounded scratch directory, and hashed/stat-checked again before the next
frame.  No HDF5 or second native tree is read.

The worker reports finite native fields, XML-range particle identity, native
BI4 ``MassFluid`` weighted aggregate observables, and exact per-ID first/last
frame lifecycle records.  XML ranges are an identity label only; they do not
make a native MK/type claim.  A missing or changing native MassFluid is an
explicit UNKNOWN/failure and never falls back to the generated XML mass.
Continuum equivalence, pressure/EOS, rigid-body dynamics, and QI/QN/QE remain
UNKNOWN.
"""

from __future__ import annotations

import argparse
import bisect
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

import numpy as np

import stage2_f3_s2_native_header_observer_v1 as header_observer
import stage2_native_physical_observer_v2 as base


SCHEMA = "ds02.stage2.f3-s2.full-native-stream-observer.v2"
PASS_STATUS = "PASS_FULL_NATIVE_STREAM_V2"
UNKNOWN_STATUS = "UNKNOWN_UNSUPPORTED_NATIVE_ENCODING"
FRAME_RE = re.compile(r"^Part_(\d+)\.bi4$")
CHUNK = 1024 * 1024
DEFAULT_DECODER_TIMEOUT_S = 300.0
DEFAULT_MAX_LOG_BYTES = 64 * 1024
DEFAULT_MAX_SCRATCH_BYTES = 256 * 1024 * 1024
PR_SET_PDEATHSIG = 1


class WorkerCancelled(RuntimeError):
    """The parent asked this worker to stop; child decoder must be reaped."""


_ACTIVE_PROCESS: subprocess.Popen[bytes] | None = None
_ACTIVE_SCRATCH: Path | None = None



def stat_record(path: Path) -> dict[str, int]:
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


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def checked_hash(path: Path, phase: str) -> dict[str, Any]:
    before = stat_record(path)
    digest, size = sha256_file(path)
    after = stat_record(path)
    if before != after:
        raise base.UnsupportedSemantics(
            f"{phase}: source changed while hashing {path}: before={before} after={after}"
        )
    if size != before["bytes"]:
        raise base.UnsupportedSemantics(f"{phase}: source size changed while hashing {path}")
    return {
        "path": str(path.resolve()),
        "bytes": size,
        "sha256": digest,
        "stat_before": before,
        "stat_after": after,
        "stat_consistency": "PASS_HASH_BOUNDARY_STABLE",
    }


def compare_decode_boundaries(pre: dict[str, Any], post: dict[str, Any]) -> None:
    if pre["path"] != post["path"] or pre["bytes"] != post["bytes"] or pre["sha256"] != post["sha256"]:
        raise base.UnsupportedSemantics(f"source content changed across decode: {pre['path']}")
    if pre["stat_after"] != post["stat_before"]:
        raise base.UnsupportedSemantics(
            f"source stat changed at decoder handoff: {pre['path']} "
            f"pre_after={pre['stat_after']} post_before={post['stat_before']}"
        )
    if pre["stat_before"] != post["stat_after"]:
        raise base.UnsupportedSemantics(
            f"source stat changed across decoder: {pre['path']} "
            f"pre_before={pre['stat_before']} post_after={post['stat_after']}"
        )


def _tail(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def _set_parent_death_signal() -> None:
    """Ask Linux to terminate the decoder if this worker parent disappears."""

    try:
        libc = ctypes.CDLL(None)
        result = libc.prctl(PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0)
        if result != 0:
            raise OSError(result, "prctl(PR_SET_PDEATHSIG) failed")
    except Exception:
        # The worker still has a process-group cleanup path on non-Linux hosts.
        return


def _kill_and_reap(process: subprocess.Popen[bytes], *, grace_s: float = 5.0) -> None:
    """Kill a decoder process group and wait until its process is reaped."""

    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    else:
        process.wait()


def _scratch_bytes(root: Path, limit: int) -> int:
    total = 0
    if not root.exists():
        return 0
    for current, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            path = Path(current) / name
            if path.is_symlink():
                raise base.UnsupportedSemantics(f"decoder scratch contains symlink: {path}")
        for name in files:
            path = Path(current) / name
            if path.is_symlink():
                raise base.UnsupportedSemantics(f"decoder scratch contains symlink: {path}")
            total += int(path.stat().st_size)
            if total > limit:
                return total
    return total


def _install_signal_cleanup() -> dict[int, Any]:
    previous: dict[int, Any] = {}

    def handle(signum: int, _frame: Any) -> None:
        process = _ACTIVE_PROCESS
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        raise WorkerCancelled(f"worker received signal {signum}; decoder group terminated")

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, handle)
    return previous


def _restore_signal_cleanup(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _run_decoder_process(
    command: list[str],
    temporary: Path,
    *,
    timeout_s: float,
    max_log_bytes: int,
    max_scratch_bytes: int,
) -> tuple[str, str, int]:
    """Run one decoder with bounded pipes, scratch, timeout, and reaping."""

    global _ACTIVE_PROCESS, _ACTIVE_SCRATCH
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        start_new_session=True,
        preexec_fn=_set_parent_death_signal,
    )
    _ACTIVE_PROCESS = process
    _ACTIVE_SCRATCH = temporary
    selector = selectors.DefaultSelector()
    stdout_tail = bytearray()
    stderr_tail = bytearray()
    output_bytes = {"stdout": 0, "stderr": 0}
    streams: dict[int, tuple[str, Any]] = {}
    assert process.stdout is not None and process.stderr is not None
    for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, label)
        streams[stream.fileno()] = (label, stream)
    started = time.monotonic()
    termination_reason: str | None = None

    def append_tail(target: bytearray, data: bytes) -> None:
        target.extend(data)
        if len(target) > max_log_bytes:
            del target[:-max_log_bytes]

    result: tuple[str, str, int] | None = None
    try:
        while streams or process.poll() is None:
            if termination_reason is None and time.monotonic() - started > timeout_s:
                termination_reason = f"decoder timeout after {timeout_s}s"
                _kill_and_reap(process)
            if termination_reason is None and _scratch_bytes(temporary, max_scratch_bytes) > max_scratch_bytes:
                termination_reason = f"decoder scratch exceeded {max_scratch_bytes} bytes"
                _kill_and_reap(process)
            for key, _mask in selector.select(timeout=0.10):
                stream = key.fileobj
                label = key.data
                try:
                    data = os.read(stream.fileno(), 65536)
                except BlockingIOError:
                    continue
                if not data:
                    selector.unregister(stream)
                    streams.pop(stream.fileno(), None)
                    stream.close()
                    continue
                output_bytes[label] += len(data)
                if termination_reason is None and output_bytes[label] > max_log_bytes:
                    termination_reason = f"decoder {label} exceeded {max_log_bytes} bytes"
                    _kill_and_reap(process)
                append_tail(stdout_tail if label == "stdout" else stderr_tail, data)
            if termination_reason is not None and process.poll() is not None and not streams:
                break
        if process.poll() is None:
            process.wait()
        result = (stdout_tail.decode("utf-8", errors="replace"), stderr_tail.decode("utf-8", errors="replace"), int(process.returncode or 0))
    except BaseException:
        _kill_and_reap(process)
        raise
    finally:
        for key in list(selector.get_map().values()):
            try:
                selector.unregister(key.fileobj)
            except Exception:
                pass
            try:
                key.fileobj.close()
            except Exception:
                pass
        selector.close()
        _ACTIVE_PROCESS = None
        _ACTIVE_SCRATCH = None
    if termination_reason is not None:
        raise base.UnsupportedSemantics(termination_reason + f"; stderr={stderr_tail.decode('utf-8', errors='replace')!r}")
    assert result is not None
    return result


def _decoder_particle_paths(prefix: Path) -> tuple[dict[str, Any], Path]:
    xml_path = Path(str(prefix) + ".xml")
    if not xml_path.is_file():
        raise base.UnsupportedSemantics(f"bi4_dump did not produce XML: {xml_path}")
    root = base.ET.parse(xml_path).getroot()
    outer = root.find("item")
    particle = root.find(".//item/item")
    metadata = base.named_values(outer)
    info = base.named_values(particle)
    if particle is None or not particle.get("name"):
        raise base.UnsupportedSemantics("bi4_dump XML has no particle item")
    data_root = prefix / particle.get("name")
    return {"metadata": metadata, "info": info, "xml_path": xml_path}, data_root


def decode_frame_bounded(
    frame_path: Path,
    decoder: Path,
    scratch_root: Path,
    frame: int,
    *,
    timeout_s: float,
    max_log_bytes: int,
    max_scratch_bytes: int,
) -> dict[str, Any]:
    """Decode one BI4 with a process-group timeout and no retained scratch."""

    frame_path = frame_path.expanduser().resolve()
    decoder = decoder.expanduser().resolve()
    scratch_root = scratch_root.expanduser().resolve()
    if frame_path.is_symlink() or not frame_path.is_file():
        raise base.UnsupportedSemantics(f"selected native frame is not a regular file: {frame_path}")
    if decoder.is_symlink() or not decoder.is_file():
        raise base.UnsupportedSemantics(f"official decoder is not a regular file: {decoder}")
    scratch_root.mkdir(parents=True, exist_ok=True)
    scratch_stat = scratch_root.stat()
    if not scratch_root.is_dir() or scratch_root.is_symlink():
        raise base.UnsupportedSemantics(f"decoder scratch root is not a directory: {scratch_root}")
    with tempfile.TemporaryDirectory(prefix=f"full-native-frame-{frame:04d}-", dir=scratch_root) as temporary:
        prefix = Path(temporary) / "decoded"
        stdout, stderr, returncode = _run_decoder_process(
            [str(decoder), str(frame_path), str(prefix)],
            Path(temporary),
            timeout_s=timeout_s,
            max_log_bytes=max_log_bytes,
            max_scratch_bytes=max_scratch_bytes,
        )
        if returncode != 0:
            raise base.UnsupportedSemantics(
                f"official decoder failed for frame {frame} returncode={returncode}; "
                f"stderr={_tail(stderr, max_log_bytes)!r}"
            )
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
                    raise base.UnsupportedSemantics(
                        f"unsupported multi-piece/dynamic decoder field {key}={value}"
                    )
            except (TypeError, ValueError) as exc:
                raise base.UnsupportedSemantics(
                    f"non-numeric decoder semantic field {key}={value!r}"
                ) from exc
        ids_path = data_root / "Idp.bin"
        posd_path = data_root / "Posd.bin"
        pos_path = data_root / "Pos.bin"
        velocity_path = data_root / "Vel.bin"
        density_path = data_root / "Rhop.bin"
        if not ids_path.is_file() or not velocity_path.is_file() or not density_path.is_file():
            raise base.UnsupportedSemantics(f"official decoder lacks Idp/Vel/Rhop for frame {frame}")
        if posd_path.is_file():
            position_path = posd_path
            position_dtype = np.dtype("<f8")
        elif pos_path.is_file():
            position_path = pos_path
            position_dtype = np.dtype("<f4")
        else:
            raise base.UnsupportedSemantics(f"official decoder lacks Pos or Posd for frame {frame}")
        ids_unsorted = np.fromfile(ids_path, dtype=np.dtype("<u4"))
        if ids_unsorted.size == 0 or np.unique(ids_unsorted).size != ids_unsorted.size:
            raise base.UnsupportedSemantics(f"empty or duplicate Idp axis in frame {frame}")
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
            raise base.UnsupportedSemantics(
                f"decoder array lengths do not match Idp for frame {frame}"
            ) from exc
        ids = ids_unsorted[order]
        if not (np.isfinite(position).all() and np.isfinite(velocity).all() and np.isfinite(density).all()):
            raise base.UnsupportedSemantics(f"non-finite native field in frame {frame}")
        raw_time = decoder_xml["info"].get("TimeStep")
        try:
            frame_time = float(raw_time)
        except (TypeError, ValueError) as exc:
            raise base.UnsupportedSemantics(f"decoder frame has no finite TimeStep: {frame}") from exc
        if not math.isfinite(frame_time):
            raise base.UnsupportedSemantics(f"decoder frame has non-finite TimeStep: {frame}")
        digest = hashlib.sha256()
        for name, array in (("Idp", ids), ("Pos", position), ("Vel", velocity), ("Rhop", density)):
            digest.update(name.encode("ascii"))
            digest.update(str(array.dtype).encode("ascii"))
            digest.update(json.dumps(list(array.shape)).encode("ascii"))
            digest.update(np.ascontiguousarray(array).tobytes())
        part_sha256, part_bytes = sha256_file(frame_path)
        return {
            "frame": frame,
            "saved_file": {"path": str(frame_path), "bytes": part_bytes, "sha256": part_sha256},
            "decoder_xml_sha256": base.sha256_file(decoder_xml["xml_path"])[0],
            "decoded_time_s": frame_time,
            "field_digest_sha256": digest.hexdigest(),
            "ids": ids,
            "position": position,
            "velocity": velocity,
            "density": density,
            "metadata": decoder_xml["metadata"],
            "info": decoder_xml["info"],
            "dynamic_semantics": dynamic_semantics,
            "position_dtype": str(position_dtype),
            "decoder_stdout_tail": _tail(stdout, max_log_bytes),
            "decoder_stderr_tail": _tail(stderr, max_log_bytes),
            "scratch_root_device": int(scratch_stat.st_dev),
        }


def load_calibration(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"calibration contract is missing or symlinked: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("calibration contract is not an object")
    if value.get("schema") != "ds02.stage2.f3-s2.observer-calibration-contract.v1":
        raise ValueError("unexpected F3 calibration contract schema")
    return value


def read_expected_frames(raw_root: Path, frame_count: int) -> list[Path]:
    raw_root = raw_root.expanduser().resolve()
    if raw_root.is_symlink() or not raw_root.is_dir():
        raise base.UnsupportedSemantics(f"native raw root is missing or symlinked: {raw_root}")
    numeric_parts: list[int] = []
    for path in raw_root.iterdir():
        match = FRAME_RE.fullmatch(path.name)
        if match is not None:
            try:
                numeric_parts.append(int(match.group(1)))
            except ValueError as exc:
                raise base.UnsupportedSemantics(f"invalid native frame name: {path.name}") from exc
    expected = list(range(frame_count))
    if sorted(numeric_parts) != expected:
        raise base.UnsupportedSemantics(
            f"native Part axis is not exactly 0..{frame_count - 1}: "
            f"count={len(numeric_parts)} first_extra={sorted(set(numeric_parts) - set(expected))[:5]} "
            f"missing={sorted(set(expected) - set(numeric_parts))[:5]}"
        )
    return [raw_root / f"Part_{frame:04d}.bi4" for frame in expected]


def lifecycle_update(
    lifecycle: dict[str, dict[str, Any]],
    previous: set[int] | None,
    ids: np.ndarray,
    frame: int,
    source: dict[str, Any],
) -> tuple[set[int], dict[str, Any]]:
    current = {int(value) for value in ids.tolist()}
    if len(current) != int(ids.size):
        raise base.UnsupportedSemantics(f"duplicate Idp values in lifecycle frame {frame}")
    kind, mkfluid, mk_absolute = base.assign_particle_ranges(ids, source["blocks"])
    for index, particle_id in enumerate(ids.tolist()):
        key = str(int(particle_id))
        classification = {
            "xml_kind": str(kind[index]),
            "xml_mkfluid_relative": int(mkfluid[index]),
            "xml_mk_absolute": int(mk_absolute[index]),
            "semantics": "XML_particle_range_label_only; not_native_MK_or_type",
        }
        record = lifecycle.get(key)
        if record is None:
            record = {
                "idp": int(particle_id),
                "first_frame": frame,
                "last_frame": frame,
                "observed_frame_count": 0,
                "classification": classification,
            }
            lifecycle[key] = record
        elif record["classification"] != classification:
            raise base.UnsupportedSemantics(f"XML identity classification changed for Idp {particle_id}")
        record["last_frame"] = frame
        record["observed_frame_count"] += 1
    appeared = sorted(current if previous is None else current - previous)
    disappeared = [] if previous is None else sorted(previous - current)
    for particle_id in disappeared:
        lifecycle[str(particle_id)]["first_missing_frame"] = frame
    return current, {
        "appeared_idp": appeared,
        "disappeared_idp": disappeared,
        "particle_count": len(current),
        "id_min": min(current),
        "id_max": max(current),
        "id_unique": True,
        "identity_semantics": "XML ranges only; no native Type/MK claim",
    }


def atomic_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def unknown_artifact(output: Path, reason: str, *, frame: int | None = None) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "status": UNKNOWN_STATUS,
        "reason": reason,
        "failed_frame": frame,
        "source_scope": "ROOT133 native full 836-frame window; no scientific qualification",
        "native_mass": "UNKNOWN",
        "continuum_owner_mass": "UNKNOWN",
        "typed_conversion": "NOT_PERFORMED",
        "hdf5_read": False,
        "solver_launch": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, value)
    return value


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output.expanduser().resolve()
    raw_root = args.raw_root.expanduser().resolve()
    runparts = args.runparts.expanduser().resolve()
    generated_xml = args.generated_xml.expanduser().resolve()
    decoder = args.decoder.expanduser().resolve()
    decoder_source = args.decoder_source.expanduser().resolve()
    scratch_root = args.scratch_root.expanduser().resolve()
    calibration = load_calibration(args.calibration_contract)
    rows = base.read_runparts(runparts)
    if len(rows) != args.expected_frame_count:
        raise ValueError(f"RunPARTs rows {len(rows)} != expected {args.expected_frame_count}")
    if abs(rows[-1]["time_s"] - args.expected_final_time_s) > args.final_time_tolerance_s:
        raise ValueError(
            f"RunPARTs final time {rows[-1]['time_s']} differs from expected {args.expected_final_time_s}"
        )
    frames = read_expected_frames(raw_root, args.expected_frame_count)
    source = base.parse_source_xml(generated_xml)
    brackets = [base.time_bracket(rows, float(query)) for query in args.query_times]
    if any(item["status"] == "OUTSIDE_SAVED_WINDOW" for item in brackets):
        raise ValueError("registered query is outside the actual saved RunPARTs window")
    decoder_contract = base.decoder_source_contract(decoder_source)
    if decoder_contract["status"] == "UNKNOWN_DECODER_SOURCE_CONTRACT":
        raise base.UnsupportedSemantics("decoder source does not prove argc=3 input/output-prefix contract")
    lifecycle: dict[str, dict[str, Any]] = {}
    previous_ids: set[int] | None = None
    frame_records: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    mass_values: list[float] = []
    massbound_values: list[float] = []
    encoding_fields: dict[str, dict[str, Any]] | None = None
    first_native_sha: dict[str, Any] | None = None
    for frame, frame_path, row in zip(range(args.expected_frame_count), frames, rows):
        pre = checked_hash(frame_path, f"pre_decode_frame_{frame}")
        if first_native_sha is None:
            first_native_sha = pre
        try:
            native = decode_frame_bounded(
                frame_path,
                decoder,
                scratch_root,
                frame,
                timeout_s=args.decoder_timeout_s,
                max_log_bytes=args.max_decoder_log_bytes,
                max_scratch_bytes=args.max_decoder_scratch_bytes,
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
            mass = float(header["MassFluid"]["value"])
            mass_values.append(mass)
            if isinstance(header["MassBound"]["value"], (int, float)) and not isinstance(header["MassBound"]["value"], bool):
                massbound_values.append(float(header["MassBound"]["value"]))
            if encoding_fields is None:
                encoding_fields = header
            elif header["MassFluid"]["value_binary64_little_endian_hex"] != encoding_fields["MassFluid"]["value_binary64_little_endian_hex"]:
                raise base.UnsupportedSemantics(f"native MassFluid encoding changed at frame {frame}")
            observation = header_observer._observable(native, source, header)
            previous_ids, identity = lifecycle_update(lifecycle, previous_ids, native["ids"], frame, source)
            observation["identity_lifecycle"] = identity
            observation["runparts_time_s"] = float(row["time_s"])
            observation["decoder_time_delta_s"] = float(native["decoded_time_s"] - row["time_s"])
            observation["decoder_process"] = {
                "stdout_tail": native["decoder_stdout_tail"],
                "stderr_tail": native["decoder_stderr_tail"],
                "timeout_s": args.decoder_timeout_s,
                "max_scratch_bytes": args.max_decoder_scratch_bytes,
                "max_stdout_stderr_bytes": args.max_decoder_log_bytes,
                "process_group_cancel_policy": "SIGTERM_then_SIGKILL_and_wait_on_timeout",
                "parent_death_signal": "PR_SET_PDEATHSIG_SIGTERM_best_effort",
            }
            observations.append(observation)
        finally:
            post = checked_hash(frame_path, f"post_decode_frame_{frame}")
            compare_decode_boundaries(pre, post)
            frame_records.append({"frame": frame, "path": str(frame_path), "pre_decode": pre, "post_decode": post})
    if len(set(mass_values)) != 1:
        raise base.UnsupportedSemantics("native MassFluid changed across the full saved window")
    if massbound_values and len(massbound_values) != args.expected_frame_count:
        raise base.UnsupportedSemantics("MassBound is inconsistently exposed across the full saved window")
    if massbound_values and len(set(massbound_values)) != 1:
        raise base.UnsupportedSemantics("native MassBound changed across the full saved window")
    xml_mass = source["constants"].get("massfluid_kg")
    native_mass = mass_values[0]
    xml_relative = None if not isinstance(xml_mass, (int, float)) or xml_mass == 0 else (native_mass - float(xml_mass)) / float(xml_mass)
    payload = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "scope": {
            "full_native_window": True,
            "frame_count": args.expected_frame_count,
            "frames": [0, args.expected_frame_count - 1],
            "full_raw_tree_scan": False,
            "hdf5_read": False,
            "typed_conversion": "NOT_PERFORMED",
            "particle_field_interpolation": "NOT_PERFORMED",
            "source_payload_read_after_parent_reservation": True,
        },
        "source": {
            "raw_root": str(raw_root),
            "runparts": base.file_record(runparts),
            "generated_xml": base.file_record(generated_xml),
            "decoder": base.file_record(decoder),
            "decoder_source": base.file_record(decoder_source),
            "decoder_interface": decoder_contract,
            "particle_range_semantics": source,
            "first_native_sha_after_reservation": first_native_sha,
            "full_window_frame_records": frame_records,
        },
        "encoding_contract": {
            "status": "PASS_ACTUAL_NATIVE_HEADER_ENCODING" if encoding_fields else "UNKNOWN",
            "native_header_fields_from_official_decoder": encoding_fields,
            "massfluid_binary64_hex_consistent": True,
            "xml_mass_used_as_fallback": False,
            "xml_mass_comparison": {
                "xml_massfluid_kg": xml_mass,
                "native_massfluid_kg": native_mass,
                "relative_difference_diagnostic_only": xml_relative,
            },
            "field_files": ["Idp.bin", "Pos.bin_or_Posd.bin", "Vel.bin", "Rhop.bin"],
            "type_and_mk_semantics": "XML particle ranges only; no native Type/MK claim",
        },
        "time_window": {
            "first_saved_time_s": rows[0]["time_s"],
            "last_saved_time_s": rows[-1]["time_s"],
            "query_brackets": brackets,
            "no_extrapolation": True,
            "saved_time_source": "actual RunPARTs.csv plus decoder TimeStep per frame",
        },
        "observations": observations,
        "id_lifecycle": {
            "particle_id_count": len(lifecycle),
            "records": [lifecycle[key] for key in sorted(lifecycle, key=lambda value: int(value))],
            "semantics": "first/last observed native Idp; XML kind/MK labels only",
        },
        "native_header_summary": {
            "massfluid_kg": native_mass,
            "massbound_kg": massbound_values[0] if massbound_values else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
            "massfluid_exact_across_all_frames": True,
            "massbound_exact_across_all_frames": True if massbound_values else "UNKNOWN_NOT_EXPOSED_BY_DECODER",
            "sample_mass_role": "native BI4 MassFluid times decoded XML-range fluid count; discrete diagnostic only",
            "continuum_owner_mass": "UNKNOWN_NOT_DERIVED_FROM_PARTICLE_SUM",
            "rigid_body_mass_inertia": "UNKNOWN_NOT_INFERRED_FROM_PARTICLE_SAMPLE",
        },
        "calibration": {
            "contract": calibration,
            "field_comparisons": "NOT_PERFORMED",
            "neighbor_grid_truth": False,
            "time_output_error_separation": "NOT_PERFORMED",
        },
        "decoder_resource_policy": {
            "per_frame_timeout_s": args.decoder_timeout_s,
            "process_group_cancel": "SIGTERM_then_SIGKILL_then_wait",
            "scratch_root": str(scratch_root),
            "scratch_retained_after_frame": False,
            "max_decoder_log_bytes": args.max_decoder_log_bytes,
            "max_decoder_scratch_bytes": args.max_decoder_scratch_bytes,
            "process_group_signal_cleanup": True,
            "parent_death_signal": "PR_SET_PDEATHSIG_SIGTERM_best_effort",
        },
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(output, payload)
    return payload


def _signal_cleanup_child(marker: Path, scratch: Path) -> int:
    """Run a fake sleeping decoder for the parent SIGTERM self-test."""

    marker = marker.expanduser().resolve()
    scratch = scratch.expanduser().resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    previous = _install_signal_cleanup()
    try:
        with tempfile.TemporaryDirectory(prefix="full-native-signal-child-", dir=scratch) as temporary:
            payload = Path(temporary) / "payload.bin"
            fake = [
                sys.executable,
                "-c",
                (
                    "import os,pathlib,sys,time; "
                    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='ascii'); "
                    "pathlib.Path(sys.argv[2]).write_bytes(b'fake'); "
                    "time.sleep(10)"
                ),
                str(marker),
                str(payload),
            ]
            _run_decoder_process(
                fake,
                Path(temporary),
                timeout_s=120.0,
                max_log_bytes=4096,
                max_scratch_bytes=1024 * 1024,
            )
    except WorkerCancelled:
        marker.with_name(marker.name + ".worker_cancelled").write_text("1\n", encoding="ascii")
        return 143
    finally:
        _restore_signal_cleanup(previous)
    return 0


def signal_cleanup_self_test() -> dict[str, Any]:
    """Prove SIGTERM kills/reaps a fake decoder and cleans its scratch tree."""

    with tempfile.TemporaryDirectory(prefix="ds02-f3-full-native-signal-test-") as root_text:
        root = Path(root_text)
        marker = root / "decoder.pid"
        scratch = root / "scratch"
        scratch.mkdir()
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--self-test-signal-child", str(marker), "--self-test-signal-scratch", str(scratch)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        deadline = time.monotonic() + 3.0
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not marker.exists():
            _kill_and_reap(child)
            raise AssertionError("fake decoder did not start")
        os.kill(child.pid, signal.SIGTERM)
        returncode = child.wait(timeout=5.0)
        fake_pid = int(marker.read_text(encoding="ascii"))
        try:
            os.kill(fake_pid, 0)
        except ProcessLookupError:
            fake_alive = False
        else:
            fake_alive = True
        scratch_entries = list(scratch.iterdir())
        if returncode == 0 or fake_alive or scratch_entries:
            raise AssertionError(
                f"signal cleanup failed: worker_rc={returncode} fake_alive={fake_alive} scratch={scratch_entries}"
            )
        return {
            "status": "PASS",
            "worker_returncode": returncode,
            "fake_decoder_reaped": not fake_alive,
            "scratch_empty": not scratch_entries,
            "pdeathsig_configured": True,
        }


def decoder_caps_self_test() -> dict[str, Any]:
    """Prove output and scratch caps terminate a fake decoder during execution."""

    with tempfile.TemporaryDirectory(prefix="ds02-f3-full-native-cap-test-") as root_text:
        root = Path(root_text)
        output_scratch = root / "output-scratch"
        output_scratch.mkdir()
        output_code = (
            "import sys,time; "
            "sys.stdout.buffer.write(b'x' * (2 * 1024 * 1024)); "
            "sys.stdout.flush(); time.sleep(5)"
        )
        try:
            _run_decoder_process(
                [sys.executable, "-c", output_code],
                output_scratch,
                timeout_s=10.0,
                max_log_bytes=1024,
                max_scratch_bytes=1024 * 1024,
            )
        except base.UnsupportedSemantics as exc:
            output_reason = str(exc)
        else:
            raise AssertionError("decoder stdout cap did not terminate the fake decoder")
        if "stdout exceeded 1024 bytes" not in output_reason:
            raise AssertionError(f"unexpected stdout cap reason: {output_reason}")

        scratch_scratch = root / "scratch-cap"
        scratch_scratch.mkdir()
        scratch_code = (
            "import pathlib,sys,time; "
            "pathlib.Path(sys.argv[1]).write_bytes(b'x' * (16 * 1024)); "
            "time.sleep(5)"
        )
        scratch_file = scratch_scratch / "decoder-output.bin"
        try:
            _run_decoder_process(
                [sys.executable, "-c", scratch_code, str(scratch_file)],
                scratch_scratch,
                timeout_s=10.0,
                max_log_bytes=1024,
                max_scratch_bytes=4096,
            )
        except base.UnsupportedSemantics as exc:
            scratch_reason = str(exc)
        else:
            raise AssertionError("decoder scratch cap did not terminate the fake decoder")
        if "decoder scratch exceeded 4096 bytes" not in scratch_reason:
            raise AssertionError(f"unexpected scratch cap reason: {scratch_reason}")
    return {
        "status": "PASS",
        "stdout_cap_bytes": 1024,
        "scratch_cap_bytes": 4096,
        "decoder_launch": "manufactured_sleep_only",
    }


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ds02-f3-full-native-selftest-") as root_text:
        root = Path(root_text)
        path = root / "Part_0000.bi4"
        path.write_bytes(b"native")
        pre = checked_hash(path, "self_test_pre")
        post = checked_hash(path, "self_test_post")
        compare_decode_boundaries(pre, post)
        life: dict[str, dict[str, Any]] = {}
        source = {"blocks": [{"kind": "fluid", "mkfluid_relative": 0, "mk_absolute": 1, "begin": 0, "count": 2, "end_exclusive": 2}]}
        current, row = lifecycle_update(life, None, np.array([0, 1], dtype=np.uint32), 0, source)
        assert row["appeared_idp"] == [0, 1] and not row["disappeared_idp"]
        _current, row2 = lifecycle_update(life, current, np.array([0], dtype=np.uint32), 1, source)
        assert row2["disappeared_idp"] == [1]
    signal_result = signal_cleanup_self_test()
    cap_result = decoder_caps_self_test()
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "hash_stat_cross_decode": True,
        "lifecycle_events": True,
        "decoder_process_cleanup": signal_result,
        "decoder_runtime_caps": cap_result,
        "decoder_launch": "manufactured_sleep_only",
        "payload_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


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
    parser.add_argument("--query-times", type=float, nargs="+")
    parser.add_argument("--decoder-timeout-s", type=float, default=DEFAULT_DECODER_TIMEOUT_S)
    parser.add_argument("--max-decoder-log-bytes", type=int, default=DEFAULT_MAX_LOG_BYTES)
    parser.add_argument("--max-decoder-scratch-bytes", type=int, default=DEFAULT_MAX_SCRATCH_BYTES)
    parser.add_argument("--self-test-signal-child", type=Path)
    parser.add_argument("--self-test-signal-scratch", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.self_test_signal_child is not None:
        if args.self_test_signal_scratch is None:
            parser.error("--self-test-signal-child requires --self-test-signal-scratch")
        return _signal_cleanup_child(args.self_test_signal_child, args.self_test_signal_scratch)
    required = (
        args.raw_root, args.runparts, args.generated_xml, args.decoder, args.decoder_source,
        args.calibration_contract, args.output, args.scratch_root, args.expected_frame_count,
        args.expected_final_time_s, args.query_times,
    )
    if any(value is None for value in required):
        parser.error("all full-native stream arguments are required unless --self-test is used")
    previous_handlers = _install_signal_cleanup()
    try:
        result = run(args)
    except WorkerCancelled as exc:
        print(str(exc), file=sys.stderr)
        return 143
    except base.UnsupportedSemantics as exc:
        try:
            result = unknown_artifact(args.output.resolve(), str(exc))
        except FileExistsError:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps({"status": result["status"], "output": str(args.output.resolve())}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(f"full native stream failed: {exc}", file=sys.stderr)
        return 2
    finally:
        _restore_signal_cleanup(previous_handlers)
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "frame_count": result["scope"]["frame_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
