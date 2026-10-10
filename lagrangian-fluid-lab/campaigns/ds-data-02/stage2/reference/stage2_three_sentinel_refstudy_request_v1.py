#!/usr/bin/env python3
"""Prepare a source-only parent request for a three-sentinel refstudy.

The request is deliberately not executable until the parent has produced the
observer sidecars.  Those sidecars are deferred inputs: this builder records
their planned paths and does not open native files, VTK, HDF5, or solver
output.  A later parent rebinding must replace the deferred records with
actual post-reservation SHA/stat records before the worker can run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
WORKER = HERE / "stage2_three_sentinel_refstudy_worker_v1.py"
CONTRACT = HERE / "stage2_three_sentinel_refstudy_contract_v1.json"
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel.refstudy-manifest.v1"
TARGETS = {"F2-S2", "F3-S1", "F5-S1"}
DIMENSIONS = {"spatial", "integration", "output_sampling"}
JSON_CAP = 10 * 1024 * 1024
UNKNOWN_Q = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class BuildFailure(RuntimeError):
    pass


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"device": int(s.st_dev), "inode": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular(path: Path, label: str) -> Path:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _bounded_json(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during the bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object")
    return {"value": value, "record": {"path": str(path), "sha256": _sha(raw),
                                         "stat": after, "scope": "bounded_source_metadata",
                                         "payload_read_by_builder": True}}


def _static(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB static cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during the bounded read: {path}")
    return {"path": str(path), "sha256": _sha(raw), "stat": after,
            "hash_status": "BOUND_SMALL_SOURCE", "scope": "bounded_source_metadata",
            "payload_read_by_builder": True, "label": label}


def _runtime_records() -> dict[str, dict[str, Any]]:
    if not PYTHON.is_symlink() or not PYTHON.exists():
        raise BuildFailure(f"literal virtualenv interpreter is unavailable: {PYTHON}")
    target = PYTHON.resolve()
    if not target.is_file() or not PYVENV.is_file():
        raise BuildFailure("literal venv target or pyvenv.cfg is unavailable")
    return {str(target): _static(target, "resolved literal venv interpreter"),
            str(PYVENV): _static(PYVENV, "pyvenv.cfg")}


def _deferred(path: Path, label: str) -> dict[str, Any]:
    # Do not stat or open a deferred observer here.  In particular, a path
    # may not exist until the parent has reserved and materialized its source.
    return {"path": str(_abs(path)), "sha256": "PARENT_AFTER_RESERVATION_REQUIRED",
            "stat": None, "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
            "scope": "parent_observer_sidecar", "payload_read_by_builder": False,
            "label": label}


def build(*, sentinel_id: str, dimension: str, physical_case_id: str,
          source_paths: list[Path], observer_paths: list[Path],
          output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if sentinel_id not in TARGETS:
        raise BuildFailure(f"unsupported sentinel: {sentinel_id}")
    if dimension not in DIMENSIONS:
        raise BuildFailure(f"unsupported dimension: {dimension}")
    expected = 3 if dimension == "spatial" else 2
    if len(observer_paths) != expected:
        raise BuildFailure(f"{dimension} requires exactly {expected} observer paths")
    if not physical_case_id or not isinstance(physical_case_id, str):
        raise BuildFailure("physical_case_id is required")

    static: dict[str, dict[str, Any]] = {}
    for path, label in ((WORKER, "refstudy worker"), (CONTRACT, "refstudy contract")):
        rec = _static(path, label); static[rec["path"]] = rec
    for path, label in ((HERE / "stage2_three_sentinel_refstudy_request_v1.py", "request builder"),):
        rec = _static(path, label); static[rec["path"]] = rec
    for path, label in ((PYVENV, "pyvenv.cfg"), (PYTHON.resolve(), "resolved literal venv interpreter")):
        rec = _static(path, label); static[rec["path"]] = rec
    for index, path in enumerate(source_paths):
        rec = _static(path, f"source record {index}"); static[rec["path"]] = rec

    output_dir = _abs(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "refstudy-manifest-v1.json"
    request_path = output_dir / "refstudy-request-v1.json"
    if manifest_path.exists() or request_path.exists():
        raise BuildFailure(f"refusing to overwrite immutable request directory: {output_dir}")

    deferred = []
    for index, path in enumerate(observer_paths):
        deferred.append({"index": index, "role": "native_observer_sidecar",
                         **_deferred(path, f"observer sidecar {index}")})
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_REFSTUDY",
        "sentinel_id": sentinel_id,
        "dimension": dimension,
        "physical_case_id": physical_case_id,
        "observer_records": deferred,
        "source_records": list(static.values()),
        "recipe_contract": {
            "dimension": dimension,
            "allowed_variable": {"spatial": "definition_dp_m", "integration": "cfl_number",
                                 "output_sampling": "output_interval_s"}[dimension],
            "same_source_control_geometry": True,
            "same_physical_case_id": physical_case_id,
        },
        "scientific_scope": {
            "scientific_qualification": dict(UNKNOWN_Q),
            "interpolation": False,
            "neighbor_grid_truth": False,
            "xml_mass_is_not_native_mass": True,
            "event_time": "UNKNOWN",
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_record = _static(manifest_path, "refstudy manifest")
    static[manifest_record["path"]] = manifest_record
    request = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARDED_REFSTUDY",
        "request_variant": "three-sentinel-refstudy-v1-source-prepared",
        "sentinel_id": sentinel_id,
        "case_id": f"{sentinel_id.replace('-', '_')}_{dimension.upper()}_REFSTUDY_V1",
        "attempt_id": "PARENT_ASSIGNED_AFTER_RESERVATION",
        "request_id": f"{sentinel_id.replace('-', '_').lower()}-{dimension}-refstudy-v1-prepared-001",
        "kind": "cpu", "cpu_task_kind": "audit", "family_id": sentinel_id[:2],
        "command": [str(PYTHON), str(WORKER), "--run", "--manifest", str(manifest_path),
                    "--output", f"{{attempt_root}}/report/refstudy-{dimension}-v1.json"],
        "cwd": str(HERE.parents[4] / "lagrangian-fluid-lab"),
        "worktree_root": str(HERE.parents[4]),
        "max_wall_seconds": 1200, "cpu_threads": 1,
        "estimated_storage_bytes": 2 * 1024 * 1024 * 1024,
        "resource_scope": {"cpu_threads": 1, "memory_max_bytes": 4 * 1024**3,
                           "max_wall_seconds": 1200, "scratch_max_bytes": 2 * 1024**3, "gpu": "none"},
        "input_files": sorted(static),
        "input_sha256": {path: rec["sha256"] for path, rec in static.items()},
        "input_records": static,
        "manifest": manifest_record,
        "deferred_input_records": deferred,
        "execution_allowed": False, "launch_disabled": True, "source_only": True,
        "production_eligible": False, "gencase_launch": False, "solver_launch": False,
        "read_scope": {"builder_reads_only_bounded_source_metadata": True,
                       "worker_reads_observer_json_only_after_reservation": True,
                       "production_bi4": False, "production_vtk": False,
                       "production_hdf5": False, "interpolation": False,
                       "neighbor_grid_truth": False},
        "scientific_qualification": dict(UNKNOWN_Q),
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest, request


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="three-sentinel-refstudy-request-") as td:
        root = Path(td)
        source = root / "source.json"; source.write_text('{"source":"tiny"}\n', encoding="utf-8")
        manifest, request = build(sentinel_id="F3-S1", dimension="integration",
                                  physical_case_id="F3-S1-TINY", source_paths=[source],
                                  observer_paths=[root / "observer-a.json", root / "observer-b.json"],
                                  output_dir=root / "request")
        assert manifest["status"] == "READY_FOR_PARENT_GUARDED_REFSTUDY"
        assert len(request["deferred_input_records"]) == 2
        assert request["execution_allowed"] is False and request["solver_launch"] is False
        assert request["cpu_task_kind"] == "audit" and request["family_id"] == "F3"
        bad = json.loads((root / "request/refstudy-manifest-v1.json").read_text())
        bad["dimension"] = "bad"
        assert bad["dimension"] not in DIMENSIONS
    print("PASS_THREE_SENTINEL_REFSTUDY_REQUEST_V1_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--sentinel-id", choices=sorted(TARGETS))
    parser.add_argument("--dimension", choices=sorted(DIMENSIONS))
    parser.add_argument("--physical-case-id")
    parser.add_argument("--source-record", action="append", type=Path, default=[])
    parser.add_argument("--observer", action="append", type=Path, default=[])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test(); return 0
    if not all((args.sentinel_id, args.dimension, args.physical_case_id, args.output_dir)):
        parser.error("--sentinel-id, --dimension, --physical-case-id and --output-dir are required")
    try:
        manifest, request = build(sentinel_id=args.sentinel_id, dimension=args.dimension,
                                  physical_case_id=args.physical_case_id,
                                  source_paths=args.source_record, observer_paths=args.observer,
                                  output_dir=args.output_dir)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_THREE_SENTINEL_REFSTUDY_REQUEST_V1: {exc}")
        return 2
    print(json.dumps({"status": manifest["status"], "sentinel_id": manifest["sentinel_id"],
                      "dimension": manifest["dimension"], "output_dir": str(_abs(args.output_dir)),
                      "scientific_credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
