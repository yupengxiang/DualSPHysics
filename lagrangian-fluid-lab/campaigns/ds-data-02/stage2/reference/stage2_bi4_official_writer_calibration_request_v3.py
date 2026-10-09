#!/usr/bin/env python3
"""Build a fresh, CPU-only request for the version-3 manufactured official BI4 test.

The builder hashes only repository source/configuration files and creates a
new source manifest.  It never opens, hashes, or stats a production BI4,
H5/VTK, solver output, or GPU input.  The compiled writer, ``bi4_dump``, and
the tiny fixture are all created below the parent attempt root by the worker
after the parent guard has reserved that root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
# ``HERE`` is the .../stage2/reference directory; its fourth parent is the
# worktree's DualSPHysics root (the file path itself would use parents[5]).
ROOT = HERE.parents[4]
SOURCE_ROOT = ROOT / "src/source"
REQUEST_ROOT = ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"
WORKER = HERE / "stage2_bi4_official_writer_calibration_worker_v3.py"
BUILDER = HERE / "stage2_bi4_official_writer_calibration_request_v3.py"
FIXTURE_CPP = HERE / "stage2_bi4_official_fixture_writer_v2.cpp"
DUMP_CPP = ROOT / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"
CONTRACT = HERE / "stage2_bi4_official_writer_calibration_contract_v2.json"
AUTHORITY = HERE / "stage2_bi4_official_writer_source_authority_v1.json"
OBSERVER = HERE / "stage2_f1_native_selected_observer_v1.py"
OBSERVER_BASE = HERE / "stage2_native_physical_observer_v2.py"
# The shared literal venv is outside the git worktrees.  Keeping this path
# literal is intentional: the parent runner must not resolve argv[0] to a
# system interpreter that lacks the observer's numpy dependency.
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
FORBIDDEN_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
MAX_SOURCE_BYTES = 16 * 1024 * 1024
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1.bi4-official-writer-calibration-request.v3"
MANIFEST_SCHEMA = "ds02.stage2.f1.bi4-official-writer-calibration-manifest.v3"

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


class BuildFailure(RuntimeError):
    pass


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().absolute()


def _record(path: Path, label: str) -> dict[str, Any]:
    path = _path(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise BuildFailure(f"{label} is a production payload: {path}")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SOURCE_BYTES:
        raise BuildFailure(f"{label} is unsafe or exceeds source metadata limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise BuildFailure(f"{label} changed while being read: {path}")
    return {
        "path": str(path),
        "label": label,
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


def _write_once(path: Path, value: Any) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _source_paths() -> list[tuple[Path, str]]:
    rows: list[tuple[Path, str]] = []
    rows.extend((path, "official DualSPHysics C++ source") for path in CORE_CPP)
    rows.extend((path, "official DualSPHysics C++ header") for path in CORE_HEADERS)
    rows.extend(
        [
            (FIXTURE_CPP, "manufactured official JPartDataBi4 fixture source"),
            (DUMP_CPP, "repository bi4_dump source"),
            (WORKER, "guarded calibration worker"),
            (BUILDER, "this request builder"),
            (CONTRACT, "manufactured calibration contract"),
            (AUTHORITY, "official writer storage source authority"),
            (OBSERVER, "existing F1 native observer implementation"),
            (OBSERVER_BASE, "existing native physical observer implementation"),
            (PYVENV, "literal venv configuration"),
        ]
    )
    unique: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for path, label in rows:
        path = _path(path)
        if str(path) in seen:
            continue
        seen.add(str(path))
        unique.append((path, label))
    return unique


def build(*, output_request: Path, output_manifest: Path, case_id: str, attempt_id: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    total = 0
    for path, label in _source_paths():
        row = _record(path, label)
        records.append(row)
        total += row["bytes"]
    if total > MAX_SOURCE_BYTES:
        raise BuildFailure(f"source closure exceeds metadata read limit: {total}")
    source_manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_CPU_GUARDED_MANUFACTURED_CALIBRATION_V3",
        "source_files": records,
        "contract_path": str(CONTRACT),
        "authority_path": str(AUTHORITY),
        "fixture_source": str(FIXTURE_CPP),
        "decoder_source": str(DUMP_CPP),
        "existing_observer_source": str(OBSERVER),
        "compiler": "g++",
        "compiler_resolution": shutil.which("g++") or "UNKNOWN_UNAVAILABLE_AT_PREPARATION",
        "source_only_preparation": {
            "production_native_payload_read": False,
            "production_h5_vtk_read": False,
            "solver_started": False,
            "gpu": False,
            "ledger_mutation": False,
            "qualification_credit": 0,
        },
    }
    output_manifest = _path(output_manifest)
    _write_once(output_manifest, source_manifest)
    manifest_record = _record(output_manifest, "calibration source manifest")
    input_records = {row["path"]: row for row in records}
    input_records[manifest_record["path"]] = manifest_record
    input_files = sorted(input_records)
    python_literal = _path(PYTHON)
    if not python_literal.is_file():
        raise BuildFailure(f"literal venv Python is missing: {python_literal}")
    output_request = _path(output_request)
    command = [
        str(python_literal),
        str(WORKER),
        "--run",
        "--source-manifest",
        str(output_manifest),
        "--attempt-root",
        "{attempt_root}",
        "--output",
        "{attempt_root}/observer/official-writer-calibration-v3.json",
        "--compile-timeout-seconds",
        "600",
        "--run-timeout-seconds",
        "120",
        "--max-scratch-bytes",
        str(256 * 1024 * 1024),
    ]
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "calibration_version": 3,
        "status": "READY_FOR_PARENT_GUARDED_CPU_MANUFACTURED_BI4_CALIBRATION_V3",
        "kind": "audit",
        "cpu_task_kind": "audit",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "cwd": str(ROOT),
        "worktree_root": str(ROOT),
        "command": command,
        "input_files": input_files,
        "input_sha256": {path: input_records[path]["sha256"] for path in input_files},
        "input_records": input_records,
        "source_manifest": manifest_record,
        "compiler": {
            "command": "g++",
            "resolution_at_prepare": source_manifest["compiler_resolution"],
            "compile_scope": "six official/common C++ translation units plus asymmetric fixture or bi4_dump; recursive quoted-header closure includes RunExceptionDef.h; no full solver build",
        },
        "resource_scope": {
            "cpu_threads": 1,
            "gpu": False,
            "memory_max_bytes": 2 * 1024 * 1024 * 1024,
            "external_storage_max_bytes": 512 * 1024 * 1024,
            "home_storage_max_bytes": 64 * 1024 * 1024,
            "wall_timeout_seconds": 900,
            "compile_timeout_seconds": 600,
            "run_timeout_seconds": 120,
            "scratch_cap_bytes": 256 * 1024 * 1024,
            "log_cap_bytes": 1024 * 1024,
            "parent_guard_required": True,
        },
        "storage_scope": {
            "output_root": "{attempt_root}",
            "all_generated_binaries_fixture_decode_and_report_inside_attempt_root": True,
            "production_payloads_allowed": False,
        },
        "source_binding": {
            "official_writer_class": "JPartDataBi4",
            "official_decoder_source": str(DUMP_CPP),
            "storage_source_authority": str(AUTHORITY),
            "existing_observer": str(OBSERVER),
            "source_manifest_path": str(output_manifest),
            "source_files_hashed_by_builder": len(input_files),
            "worker_rechecks_source_pre_and_post": True,
            "axis_storage_order_only": True,
            "producer_world_axis_authority": "UNKNOWN_UNTIL_REAL_CASE_SOURCE_AUTHORITY",
        },
        "calibration_scope": {
            "manufactured_particles": 6,
            "roles": {"fixed": 2, "moving": 1, "fluid": 3},
            "native_arrays": ["Idp", "Posd", "Vel", "Rhop"],
            "native_header": ["CaseNp", "CaseNfixed", "CaseNmoving", "CaseNfloat", "CaseNfluid", "Dp", "MassFluid", "MassBound", "PeriMode"],
            "negative_fixtures": ["duplicate_id", "wrong_units", "swapped_axes", "fixed_fluid_contamination", "nonfinite", "wrong_massfluid"],
            "per_particle_golden_validation": True,
            "negative_mutations_executed_by_actual_validator": True,
            "pre_registered_tolerance_contract": str(CONTRACT),
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "gpu_invoked": False,
        "ledger_mutation": False,
        "qualification_credit": 0,
        "builder_source": str(BUILDER),
        "builder_source_sha256": input_records[str(BUILDER)]["sha256"],
    }
    _write_once(output_request, request)
    return request


def _self_test() -> dict[str, Any]:
    # Only tiny temporary files are used.  No repository source or production
    # native path is opened in this mode.
    with tempfile.TemporaryDirectory(prefix="bi4-calibration-builder-") as tmp:
        root = Path(tmp)
        tiny = root / "tiny.cpp"
        tiny.write_text("int main(){return 0;}\n", encoding="utf-8")
        record = _record(tiny, "tiny fixture")
        assert record["bytes"] > 0 and len(record["sha256"]) == 64
        assert tiny.suffix.lower() not in FORBIDDEN_SUFFIXES
    return {
        "schema": VARIANT_SCHEMA,
        "status": "PASS",
        "source_only": True,
        "production_payload_read": False,
        "solver_started": False,
        "gpu": False,
        "qualification_credit": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--case-id", default="F1_BI4_OFFICIAL_WRITER_CALIBRATION")
    parser.add_argument("--attempt-id", default="f1-bi4-official-writer-calibration-root214-001")
    args = parser.parse_args(argv)
    if args.self_test:
        result = _self_test()
        print(json.dumps(result, sort_keys=True))
        return 0
    output_request = args.output_request or (REQUEST_ROOT / "stage2-f1-bi4-official-writer-calibration-root214-001.json")
    output_manifest = args.output_manifest or (output_request.parent / "stage2-f1-bi4-official-writer-calibration-root214-001-manifest.json")
    try:
        result = build(output_request=output_request, output_manifest=output_manifest, case_id=args.case_id, attempt_id=args.attempt_id)
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, sort_keys=True), file=os.sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "request": str(_path(output_request)), "manifest": str(_path(output_manifest)), "input_file_count": len(result["input_files"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
