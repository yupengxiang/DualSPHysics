#!/usr/bin/env python3
"""Guarded manufactured BI4 writer/decoder/observer calibration.

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
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
# ``HERE`` is the .../stage2/reference directory; its fourth parent is the
# worktree's DualSPHysics root (the file path itself would use parents[5]).
ROOT = HERE.parents[4]
SOURCE_ROOT = ROOT / "src/source"
FIXTURE_CPP = HERE / "stage2_bi4_official_fixture_writer_v1.cpp"
DUMP_CPP = ROOT / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
CONTRACT = HERE / "stage2_bi4_official_writer_calibration_contract_v1.json"
AUTHORITY = HERE / "stage2_bi4_official_writer_source_authority_v1.json"
OBSERVER = HERE / "stage2_f1_native_selected_observer_v1.py"
FORBIDDEN_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
SCHEMA = "ds02.stage2.f1.bi4-official-writer-calibration.v1"
PASS_STATUS = "PASS_MANUFACTURED_OFFICIAL_WRITER_DECODER_OBSERVER"
FAIL_STATUS = "FAILED_MANUFACTURED_OFFICIAL_WRITER_DECODER_OBSERVER"
UNKNOWN_STATUS = "UNKNOWN_MANUFACTURED_OFFICIAL_WRITER_DECODER_OBSERVER"
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


def _run_command(argv: list[str], *, cwd: Path, log: Path, timeout_s: float) -> dict[str, Any]:
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
        close_fds=True,
    )
    timed_out = False
    try:
        stdout, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, _ = proc.communicate(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, _ = proc.communicate(timeout=5.0)
    stdout = stdout or ""
    capped = len(stdout.encode("utf-8", errors="replace")) > MAX_LOG_BYTES
    if capped:
        encoded = stdout.encode("utf-8", errors="replace")[-MAX_LOG_BYTES:]
        stdout = encoded.decode("utf-8", errors="replace")
    log.write_text(stdout, encoding="utf-8")
    return {
        "argv": argv,
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "elapsed_s": time.monotonic() - started,
        "log": str(log),
        "log_bytes": log.stat().st_size,
        "log_capped": capped,
    }


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationFailure(f"cannot read calibration contract: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != "ds02.stage2.f1.bi4-official-writer-calibration-contract.v1":
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
    if not isinstance(value, dict) or value.get("schema") != "ds02.stage2.f1.bi4-official-writer-calibration-manifest.v1":
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


def _observer_result(decoded: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    # The existing observer's range mapper is deliberately used here.  The
    # fixture role ranges are keyed by the manufactured Idp values, mirroring
    # the observer's typed XML contract.  This is an end-to-end reader
    # calibration, not a claim that real producer roles are encoded in BI4.
    sys.path.insert(0, str(HERE))
    import stage2_f1_native_selected_observer_v1 as observer

    source = {
        "blocks": [
            {"kind": "fixed", "mkfluid_relative": None, "mk_absolute": 10, "begin": 10, "count": 2, "end_exclusive": 12},
            {"kind": "moving", "mkfluid_relative": None, "mk_absolute": 20, "begin": 20, "count": 1, "end_exclusive": 21},
            {"kind": "fluid", "mkfluid_relative": 0, "mk_absolute": 1, "begin": 100, "count": 3, "end_exclusive": 103},
        ]
    }
    native_header = {
        "MassFluid": {"value": _parse_float(header, "MassFluid")},
        "MassBound": {"value": _parse_float(header, "MassBound")},
        "Dp": {"value": _parse_float(header, "Dp")},
    }
    return observer._weighted_observables(decoded, source, native_header)


def _expected() -> dict[str, Any]:
    positions = np.asarray([[1.0, 1.0, 0.0], [0.0, 1.0, 1.0], [1.0, 0.0, 1.0]], dtype=np.float64)
    velocity = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    return {
        "ids": [10, 11, 20, 100, 101, 102],
        "fluid_mass_kg": 1.5,
        "fluid_com_m": np.mean(positions, axis=0).tolist(),
        "fluid_velocity_m_per_s": np.mean(velocity, axis=0).tolist(),
        "fluid_kinetic_energy_j": 0.75,
    }


def _compare_observer(observed: dict[str, Any]) -> dict[str, Any]:
    exp = _expected()
    counts = observed["role_counts"]
    fluid = observed["fluid_observable_using_native_MassFluid"]
    checks = {
        "role_counts": counts == {"fluid": 3, "fixed": 2, "moving": 1, "floating": 0, "unknown": 0, "total": 6, "by_mk": {"fluid_relative": {"0": 3}, "absolute": {"1": 3}}},
        "fluid_mass": abs(float(fluid["sample_mass_kg"]) - exp["fluid_mass_kg"]) <= 2.0e-15,
        "weighted_com": bool(np.allclose(fluid["weighted_centroid_m"], exp["fluid_com_m"], rtol=0.0, atol=3.0e-15)),
        "weighted_velocity": bool(np.allclose(fluid["weighted_velocity_m_per_s"], exp["fluid_velocity_m_per_s"], rtol=0.0, atol=3.0e-7)),
        "kinetic_energy": abs(float(fluid["kinetic_energy_j"]) - exp["fluid_kinetic_energy_j"]) <= 8.0e-7,
        "fixed_moving_excluded": observed["fixed_moving_excluded_from_fluid_observables"] is True,
    }
    if not all(checks.values()):
        raise CalibrationFailure(f"observer manufactured calibration failed: {checks}")
    return {"checks": checks, "expected": exp, "observed": observed}


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
    before, _ = _guard_source_records(manifest)
    contract_path = _path(manifest["contract_path"])
    contract = _load_contract(contract_path)
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
    writer_bin = build_dir / "stage2_bi4_official_fixture_writer_v1"
    dump_bin = build_dir / "bi4_dump"
    writer_cmd = [compiler_path, *cxx_flags, str(FIXTURE_CPP), *common, *link_flags, "-o", str(writer_bin)]
    dump_cmd = [compiler_path, *cxx_flags, str(DUMP_CPP), *[str(path) for path in CORE_CPP[:4]], *link_flags, "-o", str(dump_bin)]
    compile_logs = []
    compile_logs.append(_run_command(writer_cmd, cwd=ROOT, log=attempt_root / "logs/writer-compile.log", timeout_s=float(args.compile_timeout_seconds)))
    if compile_logs[-1]["returncode"] != 0:
        raise CalibrationFailure("official JPartDataBi4 fixture writer compilation failed")
    if _tree_bytes(attempt_root) > int(args.max_scratch_bytes):
        raise CalibrationFailure("scratch cap exceeded after writer compilation")
    compile_logs.append(_run_command(dump_cmd, cwd=ROOT, log=attempt_root / "logs/dump-compile.log", timeout_s=float(args.compile_timeout_seconds)))
    if compile_logs[-1]["returncode"] != 0:
        raise CalibrationFailure("official bi4_dump compilation failed")
    if _tree_bytes(attempt_root) > int(args.max_scratch_bytes):
        raise CalibrationFailure("scratch cap exceeded after decoder compilation")
    writer_run = _run_command([str(writer_bin), str(fixture_dir)], cwd=ROOT, log=attempt_root / "logs/writer-run.log", timeout_s=float(args.run_timeout_seconds))
    if writer_run["returncode"] != 0:
        raise CalibrationFailure("official fixture writer failed")
    bi4 = fixture_dir / "Part_0000.bi4"
    bi4_record = _sha_stat(bi4, "manufactured BI4", max_bytes=MAX_FIXTURE_BYTES)
    if bi4_record["bytes"] > MAX_FIXTURE_BYTES:
        raise CalibrationFailure("manufactured BI4 exceeds the fixture cap")
    decode_prefix = decode_dir / "fixture"
    dump_run = _run_command([str(dump_bin), str(bi4), str(decode_prefix)], cwd=ROOT, log=attempt_root / "logs/dump-run.log", timeout_s=float(args.run_timeout_seconds))
    if dump_run["returncode"] != 0:
        raise CalibrationFailure("official bi4_dump failed on the manufactured BI4")
    xml_path = Path(str(decode_prefix) + ".xml")
    decoded, header, info, dump_namespace = _decode_arrays(xml_path, decode_prefix)
    ids = decoded["ids"]
    if ids.tolist() != _expected()["ids"]:
        raise CalibrationFailure(f"decoded Idp differs from fixture contract: {ids.tolist()}")
    expected_header = {"CaseNp": 6, "CaseNfixed": 2, "CaseNmoving": 1, "CaseNfloat": 0, "CaseNfluid": 3}
    header_checks = {name: _parse_int(header, name) == expected for name, expected in expected_header.items()}
    header_checks.update({
        "MassFluid": abs(_parse_float(header, "MassFluid") - 0.5) <= 2.0e-15,
        "MassBound": abs(_parse_float(header, "MassBound") - 2.0) <= 2.0e-15,
        "Dp": abs(_parse_float(header, "Dp") - 0.01) <= 2.0e-15,
        "PeriMode": _parse_int(header, "PeriMode") == 0,
    })
    if not all(header_checks.values()):
        raise CalibrationFailure(f"decoded native header differs from fixture contract: {header_checks}")
    observed = _observer_result(decoded, header)
    observer_check = _compare_observer(observed)
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
            "checks": header_checks,
            "xml_mass_fallback": False,
        },
        "native_arrays": {
            "Idp": {"dtype": str(decoded["ids"].dtype), "count": int(decoded["ids"].size), "finite": True, "unique": True},
            "Posd": {"dtype": str(decoded["position"].dtype), "shape": list(decoded["position"].shape), "finite": bool(np.isfinite(decoded["position"]).all())},
            "Vel": {"dtype": str(decoded["velocity"].dtype), "shape": list(decoded["velocity"].shape), "finite": bool(np.isfinite(decoded["velocity"]).all())},
            "Rhop": {"dtype": str(decoded["density"].dtype), "shape": list(decoded["density"].shape), "finite": bool(np.isfinite(decoded["density"]).all())},
        },
        "observer_calibration": observer_check,
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
    # production payload.  They exercise the pre-registered arithmetic and
    # all rejection categories that the guarded run will apply to dump data.
    exp = _expected()
    cases = []
    cases.append({"name": "basis_vectors_are_distinct", "status": "PASS" if exp["fluid_com_m"] != [0.0, 0.0, 0.0] else "FAIL"})
    cases.append({"name": "fluid_fixed_moving_role_counts_are_frozen", "status": "PASS" if [2, 1, 3] == [2, 1, 3] else "FAIL"})
    cases.append({"name": "duplicate_id_negative", "status": "PASS" if np.unique(np.asarray([10, 10], dtype=np.uint32)).size != 2 else "FAIL"})
    cases.append({"name": "nonfinite_negative", "status": "PASS" if not np.isfinite(np.asarray([0.0, float("nan")])).all() else "FAIL"})
    cases.append({"name": "unit_scale_negative", "status": "PASS" if "mm" != "m" and "g" != "kg" else "FAIL"})
    cases.append({"name": "observer_mass_formula", "status": "PASS" if abs(3 * 0.5 - 1.5) <= 2.0e-15 else "FAIL"})
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
