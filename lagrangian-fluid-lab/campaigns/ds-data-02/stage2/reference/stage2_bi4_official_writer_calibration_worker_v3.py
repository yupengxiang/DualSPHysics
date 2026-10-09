#!/usr/bin/env python3
"""Guarded manufactured BI4 writer/decoder/observer calibration, version 3.

The parent runner is expected to reserve a fresh CPU attempt before invoking
this worker.  The worker then hashes only the small, declared source files,
compiles the official ``JPartDataBi4`` writer and the repository's
``bi4_dump`` adapter into the attempt directory, creates one six-particle
fixture, decodes it, and feeds the decoded arrays through the existing F1
native observer's weighted-observable implementation.

No production BI4, H5, VTK, solver, or GPU path is accepted by this worker.
The fixture is a storage/reader calibration and grants no QI/QN/QE credit.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import selectors
import stat
import subprocess
import sys
import tempfile
import time
import re
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
# ``HERE`` is the .../stage2/reference directory; its fourth parent is the
# worktree's DualSPHysics root (the file path itself would use parents[5]).
ROOT = HERE.parents[4]
SOURCE_ROOT = ROOT / "src/source"
FIXTURE_CPP = HERE / "stage2_bi4_official_fixture_writer_v2.cpp"
DUMP_CPP = ROOT / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
CONTRACT = HERE / "stage2_bi4_official_writer_calibration_contract_v2.json"
AUTHORITY = HERE / "stage2_bi4_official_writer_source_authority_v1.json"
OBSERVER = HERE / "stage2_f1_native_selected_observer_v1.py"
# These are explicit manifest identities.  V2 accidentally referenced both
# names only inside run(), so the real --run path failed before preflight.
WORKER = HERE / "stage2_bi4_official_writer_calibration_worker_v3.py"
OBSERVER_BASE = HERE / "stage2_native_physical_observer_v2.py"
FORBIDDEN_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
SCHEMA = "ds02.stage2.f1.bi4-official-writer-calibration.v3"
PASS_STATUS = "PASS_MANUFACTURED_OFFICIAL_WRITER_DECODER_OBSERVER_V3"
FAIL_STATUS = "FAILED_MANUFACTURED_OFFICIAL_WRITER_DECODER_OBSERVER_V3"
UNKNOWN_STATUS = "UNKNOWN_MANUFACTURED_OFFICIAL_WRITER_DECODER_OBSERVER_V3"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_FIXTURE_BYTES = 1 * 1024 * 1024
MAX_SCRATCH_BYTES = 256 * 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024

# This is the exact source closure used by both tiny binaries.  The linker
# drops unused JPartDataBi4 methods, but JPartDataHead is included so the
# closure remains valid if a compiler does not discard those sections.
CORE_CPP = [
    SOURCE_ROOT / "Functions.cpp",
    SOURCE_ROOT / "JObject.cpp",
    SOURCE_ROOT / "JException.cpp",
    SOURCE_ROOT / "JBinaryData.cpp",
    SOURCE_ROOT / "JPartDataHead.cpp",
    SOURCE_ROOT / "JPartDataBi4.cpp",
]
CORE_HEADERS = [
    SOURCE_ROOT / name
    for name in (
        "Functions.h",
        "JObject.h",
        "RunExceptionDef.h",
        "JException.h",
        "JBinaryData.h",
        "JPartDataHead.h",
        "JPartDataBi4.h",
        "TypesDef.h",
        "JPeriodicDef.h",
        "JParticlesDef.h",
        "JViscosityDef.h",
    )
]


class CalibrationFailure(RuntimeError):
    pass


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().absolute()


def _regular(path: Path, label: str) -> os.stat_result:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise CalibrationFailure(f"{label} is not a regular non-symlink file: {path}")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise CalibrationFailure(f"{label} has unsafe file identity: {path}")
    return st


def _sha_stat(path: Path, label: str, *, max_bytes: int = MAX_SOURCE_BYTES) -> dict[str, Any]:
    path = _path(path)
    before = _regular(path, label)
    if before.st_size > max_bytes:
        raise CalibrationFailure(f"{label} exceeds the bounded read size: {path}")
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
        ):
            raise CalibrationFailure(f"{label} changed before hashing: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
        opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns
    ):
        raise CalibrationFailure(f"{label} changed during hashing: {path}")
    return {
        "path": str(path),
        "bytes": int(after.st_size),
        "sha256": digest.hexdigest(),
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "mtime_ns": int(after.st_mtime_ns),
        "ctime_ns": int(after.st_ctime_ns),
        "regular_file": True,
        "symlink": False,
        "link_count": int(after.st_nlink),
    }


def _atomic_json(path: Path, value: Any) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise CalibrationFailure(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _tree_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


_CANCEL_REQUESTED = False


def _handle_cancel(signum: int, frame: Any) -> None:
    del signum, frame
    global _CANCEL_REQUESTED
    _CANCEL_REQUESTED = True


def _set_parent_death_signal() -> None:
    """Make a compiler/decoder child terminate if this worker disappears."""
    if os.name != "posix":
        return
    try:
        parent_pid = os.getppid()
        libc = ctypes.CDLL(None)
        # Linux PR_SET_PDEATHSIG = 1.  The second check closes the fork/exec
        # race where the parent dies before prctl() is called.
        if libc.prctl(1, int(signal.SIGTERM), 0, 0, 0) != 0:
            return
        if os.getppid() != parent_pid:
            os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        # The parent guard still owns the process group; this field is
        # reported as best-effort metadata and never used as a Q claim.
        return


def _kill_process_group(proc: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


def _run_command(
    argv: list[str],
    *,
    cwd: Path,
    log: Path,
    timeout_s: float,
    scratch_root: Path,
    scratch_cap: int,
) -> dict[str, Any]:
    """Run with bounded streaming output, cancellation and scratch polling."""
    global _CANCEL_REQUESTED
    _CANCEL_REQUESTED = False
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        start_new_session=True,
        close_fds=True,
        preexec_fn=_set_parent_death_signal if os.name == "posix" else None,
    )
    timed_out = False
    cancelled = False
    scratch_exceeded = False
    termination_started: float | None = None
    total_log_bytes = 0
    tail = bytearray()
    selector = selectors.DefaultSelector()
    if proc.stdout is None:
        raise CalibrationFailure("bounded child has no stdout pipe")
    selector.register(proc.stdout, selectors.EVENT_READ)
    previous_handlers = (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT))
    signal.signal(signal.SIGTERM, _handle_cancel)
    signal.signal(signal.SIGINT, _handle_cancel)

    def drain_once() -> bool:
        nonlocal total_log_bytes
        events = selector.select(timeout=0.0)
        got_eof = False
        for key, _ in events:
            try:
                chunk = os.read(key.fileobj.fileno(), 65536)
            except OSError:
                chunk = b""
            if not chunk:
                try:
                    selector.unregister(key.fileobj)
                except Exception:
                    pass
                got_eof = True
                continue
            total_log_bytes += len(chunk)
            tail.extend(chunk)
            if len(tail) > MAX_LOG_BYTES:
                del tail[:-MAX_LOG_BYTES]
        return got_eof

    try:
        while True:
            elapsed = time.monotonic() - started
            if _CANCEL_REQUESTED:
                cancelled = True
                if termination_started is None:
                    termination_started = time.monotonic()
                    _kill_process_group(proc, signal.SIGTERM)
            elif elapsed > timeout_s:
                timed_out = True
                if termination_started is None:
                    termination_started = time.monotonic()
                    _kill_process_group(proc, signal.SIGTERM)
            elif _tree_bytes(scratch_root) > scratch_cap:
                scratch_exceeded = True
                if termination_started is None:
                    termination_started = time.monotonic()
                    _kill_process_group(proc, signal.SIGTERM)
            if termination_started is not None and time.monotonic() - termination_started > 5.0:
                _kill_process_group(proc, signal.SIGKILL)

            events = selector.select(timeout=0.05)
            for key, _ in events:
                try:
                    chunk = os.read(key.fileobj.fileno(), 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    try:
                        selector.unregister(key.fileobj)
                    except Exception:
                        pass
                else:
                    total_log_bytes += len(chunk)
                    tail.extend(chunk)
                    if len(tail) > MAX_LOG_BYTES:
                        del tail[:-MAX_LOG_BYTES]
            if proc.poll() is not None:
                drain_once()
                if not selector.get_map():
                    break
            if (timed_out or cancelled or scratch_exceeded) and proc.poll() is not None:
                drain_once()
                if not selector.get_map():
                    break
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc, signal.SIGKILL)
            proc.wait(timeout=5.0)
    finally:
        try:
            selector.close()
        finally:
            signal.signal(signal.SIGTERM, previous_handlers[0])
            signal.signal(signal.SIGINT, previous_handlers[1])
    log.write_bytes(bytes(tail))
    return {
        "argv": argv,
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "cancelled": cancelled,
        "scratch_exceeded": scratch_exceeded,
        "elapsed_s": time.monotonic() - started,
        "log": str(log),
        "log_bytes": log.stat().st_size,
        "log_capped": total_log_bytes > MAX_LOG_BYTES,
        "log_total_bytes_seen": total_log_bytes,
        "streaming_log_drain": True,
        "log_memory_cap_bytes": MAX_LOG_BYTES + 65536,
        "parent_death_signal_requested": os.name == "posix",
        "scratch_bytes_after": _tree_bytes(scratch_root),
    }


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationFailure(f"cannot read calibration contract: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != "ds02.stage2.f1.bi4-official-writer-calibration-contract.v2":
        raise CalibrationFailure("unexpected calibration contract schema")
    return value


def _load_authority(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationFailure(f"cannot read writer source authority: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != "ds02.stage2.f1.bi4-official-writer-source-authority.v1":
        raise CalibrationFailure("unexpected writer source authority schema")
    return value


def _load_manifest(path: Path) -> dict[str, Any]:
    path = _path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise CalibrationFailure(f"source manifest is missing, unsafe, or too large: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationFailure(f"cannot read source manifest: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != "ds02.stage2.f1.bi4-official-writer-calibration-manifest.v3":
        raise CalibrationFailure("unexpected source manifest schema")
    records = value.get("source_files")
    if not isinstance(records, list) or not records:
        raise CalibrationFailure("source manifest has no source records")
    return value


def _guard_source_records(manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = manifest["source_files"]
    total = 0
    before: list[dict[str, Any]] = []
    for index, declared in enumerate(records):
        if not isinstance(declared, dict) or not isinstance(declared.get("path"), str):
            raise CalibrationFailure(f"source record {index} is malformed")
        path = _path(declared["path"])
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise CalibrationFailure(f"production payload leaked into source closure: {path}")
        record = _sha_stat(path, f"source record {index}")
        total += record["bytes"]
        if total > MAX_SOURCE_BYTES:
            raise CalibrationFailure("source closure exceeds bounded metadata read limit")
        for key in ("bytes", "sha256"):
            if declared.get(key) != record[key]:
                raise CalibrationFailure(f"source record {index} {key} differs from parent binding")
        before.append(record)
    return before, records


def _assert_quoted_include_closure(records: list[dict[str, Any]]) -> None:
    """Reject a manifest that omits any local quoted C/C++ include."""
    declared = {str(_path(record["path"])) for record in records}
    include_pattern = re.compile(r'^\s*#\s*include\s*"([^"]+)"\s*$')
    for record in records:
        path = _path(record["path"])
        if path.suffix.lower() not in {".cpp", ".h"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise CalibrationFailure(f"cannot inspect quoted include closure for {path}: {exc}") from exc
        for line_no, line in enumerate(lines, 1):
            match = include_pattern.match(line)
            if not match:
                continue
            include = match.group(1)
            candidate = (path.parent / include).absolute()
            if candidate.is_file() and str(candidate) not in declared:
                raise CalibrationFailure(f"source manifest omits quoted include {include} from {path}:{line_no}")


def _assert_source_unchanged(before: list[dict[str, Any]]) -> list[dict[str, Any]]:
    after: list[dict[str, Any]] = []
    for index, old in enumerate(before):
        record = _sha_stat(Path(old["path"]), f"source record {index} post-run")
        for key in ("bytes", "sha256", "device", "inode", "mtime_ns", "ctime_ns"):
            if record[key] != old[key]:
                raise CalibrationFailure(f"source record {index} changed during calibration: {key}")
        after.append(record)
    return after


def _value_map(item: ET.Element) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for child in item:
        name = child.get("name")
        if name is not None and not child.tag.endswith("item"):
            result[name] = dict(child.attrib)
    return result


def _find_item(item: ET.Element, name: str) -> ET.Element | None:
    for child in item.iter():
        if child.tag.endswith("item") and child.get("name") == name:
            return child
    return None


def _parse_float(values: dict[str, dict[str, str]], name: str) -> float:
    raw = values.get(name, {}).get("v")
    if raw is None:
        raise CalibrationFailure(f"decoded BI4 XML is missing scalar {name}")
    try:
        value = float(raw)
    except ValueError as exc:
        raise CalibrationFailure(f"decoded scalar {name} is not numeric") from exc
    if not math.isfinite(value):
        raise CalibrationFailure(f"decoded scalar {name} is non-finite")
    return value


def _parse_int(values: dict[str, dict[str, str]], name: str) -> int:
    raw = values.get(name, {}).get("v")
    if raw is None:
        raise CalibrationFailure(f"decoded BI4 XML is missing integer {name}")
    try:
        return int(float(raw))
    except ValueError as exc:
        raise CalibrationFailure(f"decoded integer {name} is invalid") from exc


def _decode_arrays(xml_path: Path, decode_prefix: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]], dict[str, dict[str, str]], dict[str, Any]]:
    try:
        xml_root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise CalibrationFailure(f"cannot parse official bi4_dump XML: {exc}") from exc
    root_item = xml_root.find("./item")
    if root_item is None:
        raise CalibrationFailure("official bi4_dump XML has no root item")
    header = _value_map(root_item)
    part_container = next((child for child in root_item if child.tag.endswith("item") and child.get("name") == "Part"), None)
    if part_container is None:
        raise CalibrationFailure("official BI4 XML has no Part item")
    part_item = next((child for child in part_container if child.tag.endswith("item") and child.get("name") == "PART_0000"), None)
    if part_item is None:
        raise CalibrationFailure("official BI4 XML has no PART_0000 item")
    info = _value_map(part_item)
    arrays: dict[str, dict[str, str]] = {}
    array_tags: dict[str, str] = {}
    for child in part_item:
        if child.tag.startswith("array_") and child.get("name"):
            name = child.get("name", "")
            arrays[name] = dict(child.attrib)
            array_tags[name] = child.tag.removeprefix("array_")
    array_root = decode_prefix / "Part" / "PART_0000"
    expected_types = {"Idp": "uint", "Posd": "double3", "Vel": "float3", "Rhop": "float"}
    for name, expected_type in expected_types.items():
        if name not in arrays or not arrays[name].get("count"):
            raise CalibrationFailure(f"official dump did not declare {name}")
        # The type is encoded in the tag (array_uint, array_double3, ...),
        # not in a portable XML attribute.
        tag_type = array_tags.get(name, "")
        if tag_type != expected_type:
            raise CalibrationFailure(f"decoded {name} type is {tag_type!r}, expected {expected_type!r}")
    def read(name: str, dtype: str, shape: tuple[int, ...]) -> np.ndarray:
        path = array_root / f"{name}.bin"
        if path.is_symlink() or not path.is_file():
            raise CalibrationFailure(f"official dump did not create {name}.bin")
        expected = int(np.prod(shape)) * np.dtype(dtype).itemsize
        if path.stat().st_size != expected:
            raise CalibrationFailure(f"{name}.bin has {path.stat().st_size} bytes, expected {expected}")
        values = np.fromfile(path, dtype=dtype)
        if values.size != int(np.prod(shape)):
            raise CalibrationFailure(f"{name}.bin count differs from XML")
        return values.reshape(shape)
    decoded = {
        "ids": read("Idp", "<u4", (6,)),
        "position": read("Posd", "<f8", (6, 3)),
        "velocity": read("Vel", "<f4", (6, 3)),
        "density": read("Rhop", "<f4", (6,)),
    }
    return decoded, header, info, {"arrays": arrays, "array_root": str(array_root), "xml": str(xml_path)}


def _observer_result(
    decoded: dict[str, Any],
    header: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # The existing observer's range mapper is deliberately used here.  The
    # fixture role ranges are keyed by the manufactured Idp values, mirroring
    # the observer's typed XML contract.  This is an end-to-end reader
    # calibration, not a claim that real producer roles are encoded in BI4.
    sys.path.insert(0, str(HERE))
    import stage2_f1_native_selected_observer_v1 as observer

    if source is None:
        source = _role_source()
    native_header = {
        "MassFluid": {"value": _parse_float(header, "MassFluid")},
        "MassBound": {"value": _parse_float(header, "MassBound")},
        "Dp": {"value": _parse_float(header, "Dp")},
    }
    return observer._weighted_observables(decoded, source, native_header)


def _expected_arrays() -> dict[str, np.ndarray]:
    """Asymmetric per-Id golden values for the official writer fixture."""
    return {
        "ids": np.asarray([10, 11, 20, 100, 101, 102], dtype=np.uint32),
        "position": np.asarray([
            [-3.125, 4.5, 0.25],
            [2.75, -1.5, 3.125],
            [-0.875, 2.25, -4.75],
            [1.25, 2.5, 3.75],
            [-0.5, 4.25, 1.75],
            [2.75, -1.25, 5.5],
        ], dtype=np.float64),
        "velocity": np.asarray([
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [-0.25, 0.5, 0.75],
            [0.75, -1.25, 2.5],
            [-2.0, 3.5, 0.125],
            [1.25, 0.5, -3.0],
        ], dtype=np.float32),
        "density": np.asarray([997.25, 1001.5, 1004.75, 998.125, 999.875, 1002.625], dtype=np.float32),
    }


def _expected() -> dict[str, Any]:
    arrays = _expected_arrays()
    fluid_pos = arrays["position"][3:]
    fluid_vel = arrays["velocity"][3:].astype(np.float64)
    return {
        "ids": arrays["ids"].tolist(),
        "positions_m": arrays["position"].tolist(),
        "velocities_m_per_s": arrays["velocity"].tolist(),
        "density_kg_per_m3": arrays["density"].tolist(),
        "fluid_mass_kg": 1.5,
        "fluid_com_m": np.mean(fluid_pos, axis=0).tolist(),
        "fluid_velocity_m_per_s": np.mean(fluid_vel, axis=0).tolist(),
        "fluid_kinetic_energy_j": float(0.5 * 0.5 * np.sum(np.square(fluid_vel), dtype=np.float64)),
    }


def _role_source() -> dict[str, Any]:
    return {
        "blocks": [
            {"kind": "fixed", "mkfluid_relative": None, "mk_absolute": 10, "begin": 10, "count": 2, "end_exclusive": 12},
            {"kind": "moving", "mkfluid_relative": None, "mk_absolute": 20, "begin": 20, "count": 1, "end_exclusive": 21},
            {"kind": "fluid", "mkfluid_relative": 0, "mk_absolute": 1, "begin": 100, "count": 3, "end_exclusive": 103},
        ]
    }


def _contract_golden_check(contract: dict[str, Any]) -> None:
    expected = _expected()
    particles = contract.get("manufactured_particles")
    if not isinstance(particles, dict):
        raise CalibrationFailure("v2 contract has no manufactured_particles object")
    checks = {
        "ids": particles.get("ids") == expected["ids"],
        "positions": particles.get("positions_m") == expected["positions_m"],
        "velocities": particles.get("velocities_m_per_s") == expected["velocities_m_per_s"],
        "density": particles.get("density_kg_per_m3") == expected["density_kg_per_m3"],
    }
    obs = particles.get("expected_fluid_observables", {})
    checks.update({
        "fluid_mass": obs.get("mass_kg") == expected["fluid_mass_kg"],
        "fluid_com": np.allclose(obs.get("weighted_com_m"), expected["fluid_com_m"], rtol=0.0, atol=1.0e-15),
        "fluid_velocity": np.allclose(obs.get("weighted_velocity_m_per_s"), expected["fluid_velocity_m_per_s"], rtol=0.0, atol=1.0e-15),
        "fluid_ke": obs.get("kinetic_energy_j") == expected["fluid_kinetic_energy_j"],
    })
    if not all(bool(value) for value in checks.values()):
        raise CalibrationFailure(f"v2 contract golden values differ from worker golden values: {checks}")


def _header_checks(header: dict[str, dict[str, str]]) -> dict[str, bool]:
    expected_header = {"CaseNp": 6, "CaseNfixed": 2, "CaseNmoving": 1, "CaseNfloat": 0, "CaseNfluid": 3}
    checks = {name: _parse_int(header, name) == expected for name, expected in expected_header.items()}
    checks.update({
        "MassFluid": abs(_parse_float(header, "MassFluid") - 0.5) <= 2.0e-15,
        "MassBound": abs(_parse_float(header, "MassBound") - 2.0) <= 2.0e-15,
        "Dp": abs(_parse_float(header, "Dp") - 0.01) <= 2.0e-15,
        "PeriMode": _parse_int(header, "PeriMode") == 0,
    })
    return checks


def _particle_golden(decoded: dict[str, Any]) -> dict[str, Any]:
    expected = _expected_arrays()
    observed_ids = decoded["ids"]
    if observed_ids.dtype != expected["ids"].dtype or observed_ids.shape != expected["ids"].shape:
        raise CalibrationFailure("decoded Idp dtype/shape differs from v2 golden")
    if not np.array_equal(observed_ids, expected["ids"]):
        raise CalibrationFailure(f"decoded Idp differs from v2 golden: {observed_ids.tolist()}")
    for name in ("position", "velocity", "density"):
        if decoded[name].dtype != expected[name].dtype:
            raise CalibrationFailure(f"decoded {name} dtype {decoded[name].dtype} differs from v2 golden {expected[name].dtype}")
    checks: list[dict[str, Any]] = []
    tolerances = {"position": 2.0e-15, "velocity": 2.0e-7, "density": 2.0e-4}
    for index, particle_id in enumerate(expected["ids"].tolist()):
        row = {"id": int(particle_id), "position": {}, "velocity": {}, "density": {}}
        for name in ("position", "velocity", "density"):
            actual = np.asarray(decoded[name][index])
            target = np.asarray(expected[name][index])
            if not np.isfinite(actual).all():
                raise CalibrationFailure(f"decoded {name} for Idp {particle_id} is non-finite")
            delta = np.abs(actual.astype(np.float64) - target.astype(np.float64))
            max_error = float(np.max(delta)) if delta.size else 0.0
            row[name] = {"max_abs_error": max_error, "tolerance": tolerances[name], "pass": max_error <= tolerances[name]}
            if max_error > tolerances[name]:
                raise CalibrationFailure(f"decoded {name} for Idp {particle_id} exceeds v2 tolerance")
        checks.append(row)
    return {
        "ids_exact": True,
        "row_count": len(checks),
        "rows": checks,
        "all_rows_pass": True,
        "storage_component_order_checked": True,
    }


def _validate_decoded(decoded: dict[str, Any], header: dict[str, dict[str, str]], source: dict[str, Any]) -> dict[str, Any]:
    for name in ("ids", "position", "velocity", "density"):
        if name not in decoded or not np.isfinite(decoded[name]).all():
            raise CalibrationFailure(f"decoded {name} is missing or non-finite")
    if decoded["position"].shape != (6, 3) or decoded["velocity"].shape != (6, 3) or decoded["density"].shape != (6,):
        raise CalibrationFailure("decoded array shape differs from v2 fixture")
    header_checks = _header_checks(header)
    if not all(header_checks.values()):
        raise CalibrationFailure(f"decoded native header differs from v2 contract: {header_checks}")
    particle_golden = _particle_golden(decoded)
    observed = _observer_result(decoded, header, source) if source is not None else None
    if observed is None:
        raise CalibrationFailure("role source is required for v2 observer validation")
    counts = observed["role_counts"]
    expected_counts = {
        "fluid": 3, "fixed": 2, "moving": 1, "floating": 0, "unknown": 0, "total": 6,
        "by_mk": {"fluid_relative": {"0": 3}, "absolute": {"1": 3, "10": 2, "20": 1}},
    }
    if counts != expected_counts:
        raise CalibrationFailure(f"role counts differ from v2 contract: {counts}")
    expected = _expected()
    fluid = observed["fluid_observable_using_native_MassFluid"]
    aggregate_checks = {
        "fluid_mass": abs(float(fluid["sample_mass_kg"]) - expected["fluid_mass_kg"]) <= 2.0e-15,
        "weighted_com": bool(np.allclose(fluid["weighted_centroid_m"], expected["fluid_com_m"], rtol=0.0, atol=3.0e-15)),
        "weighted_velocity": bool(np.allclose(fluid["weighted_velocity_m_per_s"], expected["fluid_velocity_m_per_s"], rtol=0.0, atol=3.0e-7)),
        "kinetic_energy": abs(float(fluid["kinetic_energy_j"]) - expected["fluid_kinetic_energy_j"]) <= 8.0e-7,
        "fixed_moving_excluded": observed["fixed_moving_excluded_from_fluid_observables"] is True,
    }
    if not all(aggregate_checks.values()):
        raise CalibrationFailure(f"observer aggregate differs from v2 contract: {aggregate_checks}")
    return {"header_checks": header_checks, "particle_golden": particle_golden, "role_counts": counts, "aggregate_checks": aggregate_checks, "observed": observed}


def _negative_cases(decoded: dict[str, Any], header: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    names = ["duplicate_id", "wrong_units_mm_or_g", "swapped_x_y_components", "fixed_particle_in_fluid_slice", "nonfinite_position_or_velocity", "wrong_mass_fluid"]
    results: list[dict[str, Any]] = []
    for name in names:
        mutated = {key: np.array(value, copy=True) for key, value in decoded.items()}
        mutated_header = copy.deepcopy(header)
        source = _role_source()
        if name == "duplicate_id":
            mutated["ids"][1] = mutated["ids"][0]
        elif name == "wrong_units_mm_or_g":
            mutated["position"][3] *= 1000.0
            mutated["density"][3] *= 0.001
        elif name == "swapped_x_y_components":
            mutated["position"][:, [0, 1]] = mutated["position"][:, [1, 0]]
            mutated["velocity"][:, [0, 1]] = mutated["velocity"][:, [1, 0]]
        elif name == "fixed_particle_in_fluid_slice":
            source["blocks"][0].update({"kind": "fluid", "mkfluid_relative": 0, "mk_absolute": 1})
        elif name == "nonfinite_position_or_velocity":
            mutated["position"][4, 2] = np.nan
        elif name == "wrong_mass_fluid":
            mutated_header["MassFluid"]["v"] = "0.25"
        try:
            _validate_decoded(mutated, mutated_header, source)
        except Exception as exc:
            results.append({"name": name, "status": "REJECTED_BY_ACTUAL_VALIDATOR", "reason": str(exc)})
        else:
            raise CalibrationFailure(f"negative fixture unexpectedly accepted: {name}")
    return results


def _require_command_ok(result: dict[str, Any], label: str) -> None:
    if result.get("timed_out") or result.get("cancelled") or result.get("scratch_exceeded"):
        raise CalibrationFailure(f"{label} stopped by bounded worker guard: {result}")
    if result.get("returncode") != 0:
        raise CalibrationFailure(f"{label} returned {result.get('returncode')}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    if sys.byteorder != "little":
        raise CalibrationFailure("official BI4 fixture contract requires a little-endian host")
    attempt_root = _path(args.attempt_root)
    attempt_root.mkdir(parents=True, exist_ok=True)
    output = _path(args.output)
    manifest = _load_manifest(_path(args.source_manifest))
    declared_source_paths = {
        str(_path(record["path"]))
        for record in manifest["source_files"]
        if isinstance(record, dict) and isinstance(record.get("path"), str)
    }
    required_closure = [FIXTURE_CPP, DUMP_CPP, WORKER, CONTRACT, AUTHORITY, OBSERVER, OBSERVER_BASE]
    missing_closure = [str(path) for path in required_closure if str(_path(path)) not in declared_source_paths]
    if missing_closure:
        raise CalibrationFailure(f"source manifest omits required calibration closure: {missing_closure}")
    before, manifest_records = _guard_source_records(manifest)
    _assert_quoted_include_closure(manifest_records)
    contract_path = _path(manifest["contract_path"])
    contract = _load_contract(contract_path)
    _contract_golden_check(contract)
    authority_path = _path(manifest["authority_path"])
    authority = _load_authority(authority_path)
    build_dir = attempt_root / "build"
    fixture_dir = attempt_root / "fixture"
    decode_dir = attempt_root / "decoded"
    for directory in (build_dir, fixture_dir, decode_dir):
        if directory.exists() or directory.is_symlink():
            raise CalibrationFailure(f"fresh calibration directory already exists: {directory}")
        directory.mkdir(parents=True, exist_ok=False)
    if _tree_bytes(attempt_root) > MAX_SCRATCH_BYTES:
        raise CalibrationFailure("attempt scratch already exceeds cap")
    compiler = str(manifest.get("compiler", "g++"))
    compiler_path = shutil.which(compiler) if os.path.sep not in compiler else compiler
    if not compiler_path:
        raise CalibrationFailure(f"compiler is unavailable: {compiler}")
    compiler_path = str(_path(compiler_path))
    common = [str(path) for path in CORE_CPP]
    cxx_flags = [
        "-std=c++0x", "-O0", "-g0", "-fno-fast-math", "-ffunction-sections",
        "-fdata-sections", f"-I{SOURCE_ROOT}", "-Wno-unused-parameter",
        "-Wno-unused-variable", "-Wno-sign-compare",
    ]
    link_flags = ["-Wl,--gc-sections", "-pthread"]
    writer_bin = build_dir / "stage2_bi4_official_fixture_writer_v2"
    dump_bin = build_dir / "bi4_dump"
    writer_cmd = [compiler_path, *cxx_flags, str(FIXTURE_CPP), *common, *link_flags, "-o", str(writer_bin)]
    dump_cmd = [compiler_path, *cxx_flags, str(DUMP_CPP), *[str(path) for path in CORE_CPP[:4]], *link_flags, "-o", str(dump_bin)]
    compile_logs = []
    run_kwargs = {"scratch_root": attempt_root, "scratch_cap": int(args.max_scratch_bytes)}
    compile_logs.append(_run_command(writer_cmd, cwd=ROOT, log=attempt_root / "logs/writer-compile.log", timeout_s=float(args.compile_timeout_seconds), **run_kwargs))
    _require_command_ok(compile_logs[-1], "official JPartDataBi4 fixture writer compilation")
    if _tree_bytes(attempt_root) > int(args.max_scratch_bytes):
        raise CalibrationFailure("scratch cap exceeded after writer compilation")
    compile_logs.append(_run_command(dump_cmd, cwd=ROOT, log=attempt_root / "logs/dump-compile.log", timeout_s=float(args.compile_timeout_seconds), **run_kwargs))
    _require_command_ok(compile_logs[-1], "official bi4_dump compilation")
    if _tree_bytes(attempt_root) > int(args.max_scratch_bytes):
        raise CalibrationFailure("scratch cap exceeded after decoder compilation")
    writer_run = _run_command([str(writer_bin), str(fixture_dir)], cwd=ROOT, log=attempt_root / "logs/writer-run.log", timeout_s=float(args.run_timeout_seconds), **run_kwargs)
    _require_command_ok(writer_run, "official fixture writer")
    bi4 = fixture_dir / "Part_0000.bi4"
    bi4_record = _sha_stat(bi4, "manufactured BI4", max_bytes=MAX_FIXTURE_BYTES)
    if bi4_record["bytes"] > MAX_FIXTURE_BYTES:
        raise CalibrationFailure("manufactured BI4 exceeds the fixture cap")
    decode_prefix = decode_dir / "fixture"
    dump_run = _run_command([str(dump_bin), str(bi4), str(decode_prefix)], cwd=ROOT, log=attempt_root / "logs/dump-run.log", timeout_s=float(args.run_timeout_seconds), **run_kwargs)
    _require_command_ok(dump_run, "official bi4_dump")
    xml_path = Path(str(decode_prefix) + ".xml")
    decoded, header, info, dump_namespace = _decode_arrays(xml_path, decode_prefix)
    observer_check = _validate_decoded(decoded, header, _role_source())
    negative_results = _negative_cases(decoded, header)
    post = _assert_source_unchanged(before)
    report = {
        "schema": SCHEMA,
        "status": PASS_STATUS,
        "scope": {
            "manufactured_fixture_only": True,
            "production_native_payload_read": False,
            "hdf5_read": False,
            "vtk_read": False,
            "solver_started": False,
            "gpu": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "official_writer": {
            "source": str(FIXTURE_CPP),
            "class": "JPartDataBi4",
            "output": bi4_record,
            "writer_run": writer_run,
        },
        "official_decoder": {
            "source": str(DUMP_CPP),
            "binary": str(dump_bin),
            "compile": compile_logs[1],
            "run": dump_run,
            "xml": str(xml_path),
            "namespace": dump_namespace,
        },
        "native_header": {
            "values": {name: header[name] for name in ("CaseNp", "CaseNfixed", "CaseNmoving", "CaseNfloat", "CaseNfluid", "Dp", "MassFluid", "MassBound", "PeriMode")},
            "checks": observer_check["header_checks"],
            "xml_mass_fallback": False,
        },
        "native_arrays": {
            "Idp": {"dtype": str(decoded["ids"].dtype), "count": int(decoded["ids"].size), "finite": True, "unique": True},
            "Posd": {"dtype": str(decoded["position"].dtype), "shape": list(decoded["position"].shape), "finite": bool(np.isfinite(decoded["position"]).all())},
            "Vel": {"dtype": str(decoded["velocity"].dtype), "shape": list(decoded["velocity"].shape), "finite": bool(np.isfinite(decoded["velocity"]).all())},
            "Rhop": {"dtype": str(decoded["density"].dtype), "shape": list(decoded["density"].shape), "finite": bool(np.isfinite(decoded["density"]).all())},
        },
        "observer_calibration": observer_check,
        "negative_fixture_execution": {
            "all_rejected": len(negative_results) == 6,
            "results": negative_results,
            "validator": "same native header/array/role/aggregate validator used for the real decoded fixture",
        },
        "coordinate_authority": {
            "source_audit": authority,
            "storage_component_order": "PASS_tdouble3_x_y_z_and_tfloat3_x_y_z",
            "fixture_units": {"position": "m", "velocity": "m/s", "mass": "kg", "density": "kg/m^3", "time": "s"},
            "producer_world_axis": "UNKNOWN_NOT_ENCODED_BY_JPARTDATABI4",
            "physical_axis_calibration_credit": "NONE",
        },
        "source_guard": {"pre": before, "post": post, "stable": True, "bytes_read": sum(item["bytes"] for item in before) * 2},
        "negative_fixture_contract": contract["negative_fixtures"],
        "qualification_limits": [
            "manufactured writer/reader/observer storage calibration only",
            "role ranges are explicitly supplied by the fixture contract; BI4 does not carry a per-particle role tag",
            "producer world-axis orientation, physical units of a real case, continuum mass, and solver error remain UNKNOWN",
        ],
    }
    _atomic_json(output, report)
    return report


def _self_test() -> dict[str, Any]:
    # These tests never compile or execute a binary and never touch a
    # production payload.  They do exercise the same validator called after
    # the real official decoder, including every mutation in the contract.
    expected = _expected()
    arrays = _expected_arrays()
    header = {
        "CaseNp": {"v": "6"}, "CaseNfixed": {"v": "2"}, "CaseNmoving": {"v": "1"},
        "CaseNfloat": {"v": "0"}, "CaseNfluid": {"v": "3"}, "Dp": {"v": "0.01"},
        "MassFluid": {"v": "0.5"}, "MassBound": {"v": "2.0"}, "PeriMode": {"v": "0"},
    }
    _contract_golden_check({"manufactured_particles": {
        "ids": expected["ids"], "positions_m": expected["positions_m"],
        "velocities_m_per_s": expected["velocities_m_per_s"], "density_kg_per_m3": expected["density_kg_per_m3"],
        "expected_fluid_observables": {
            "mass_kg": expected["fluid_mass_kg"], "weighted_com_m": expected["fluid_com_m"],
            "weighted_velocity_m_per_s": expected["fluid_velocity_m_per_s"], "kinetic_energy_j": expected["fluid_kinetic_energy_j"],
        },
    }})
    valid = _validate_decoded(arrays, header, _role_source())
    negative_results = _negative_cases(arrays, header)
    cases = [
        {"name": "real_validator_accepts_asymmetric_golden", "status": "PASS", "detail": valid["particle_golden"]},
        {"name": "full_role_counts_and_mk_mapping", "status": "PASS" if valid["role_counts"]["by_mk"]["absolute"] == {"1": 3, "10": 2, "20": 1} else "FAIL"},
        {"name": "all_contract_negative_mutations_rejected", "status": "PASS" if len(negative_results) == 6 else "FAIL", "detail": negative_results},
    ]
    return {
        "schema": SCHEMA,
        "status": "PASS" if all(case["status"] == "PASS" for case in cases) else "FAIL",
        "cases": cases,
        "compiled_writer_invoked": False,
        "bi4_dump_invoked": False,
        "production_payload_read": False,
        "qualification_credit": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compile-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--run-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--max-scratch-bytes", type=int, default=MAX_SCRATCH_BYTES)
    args = parser.parse_args(argv)
    if args.self_test:
        result = _self_test()
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 2
    if args.source_manifest is None or args.attempt_root is None or args.output is None:
        parser.error("--source-manifest, --attempt-root, and --output are required with --run")
    try:
        result = run(args)
    except Exception as exc:
        failure = {
            "schema": SCHEMA,
            "status": FAIL_STATUS,
            "reason": str(exc),
            "scope": {"production_native_payload_read": False, "solver_started": False, "gpu": False},
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }
        try:
            _atomic_json(_path(args.output), failure)
        except Exception:
            pass
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "output": str(_path(args.output))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
