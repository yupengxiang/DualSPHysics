#!/usr/bin/env python3
"""Build a launch-disabled F1-S2 compact-observer comparison request.

The builder hashes only the small source XML/code/contract files.  The three
observer reports and the ROOT207 proof are deferred compact JSON inputs: their
SHA values are supplied by the parent after the actual producer paths are
known, and the worker performs a stable post-reservation read.  No BI4/H5/VTK
path is opened or hashed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[4]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1")
CONTRACT = HERE / "stage2_f1_s2_component_space_compare_contract_v1.json"
WORKER = HERE / "stage2_f1_s2_component_space_compare_v1.py"
BUILDER = HERE / "stage2_f1_s2_component_space_compare_request_v1.py"
AUTHORITY = HERE / "stage2_f1_world_axis_units_roles_authority_contract_v3.json"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.component-space-compare-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.component-space-compare-manifest.v1"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
FORBIDDEN = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu"}
ROOT207_PROOF_SHA = "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab"

XMLS = {
    "coarse": DATA / "F1_S2_SPATIAL_COARSE_DP0p022500/f1-s2-spatial-coarse-dp0p022500-v5-primary-001/generated.xml",
    "medium": DATA / "F1_STAGE1_DUAL_H340_DP020/root-stage1-dual-h340-actual-gencase-027/prepared/F1_STAGE1_DUAL_H340_DP020.xml",
    "fine": DATA / "F1_S2_SPATIAL_INTERVAL_DP0p017000/f1-s2-spatial-interval-dp0p017000-v2-primary-001/generated.xml",
}


class BuildFailure(RuntimeError):
    pass


def _abs(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _record(path: Path, label: str) -> dict[str, Any]:
    path = _abs(path)
    if path.suffix.lower() in FORBIDDEN:
        raise BuildFailure(f"{label} is a forbidden production payload: {path}")
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SOURCE_BYTES:
        raise BuildFailure(f"{label} is missing, unsafe, or too large: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise BuildFailure(f"{label} changed while being read: {path}")
    return {"path": str(path), "label": label, "bytes": int(after.st_size), "sha256": digest, "device": int(after.st_dev), "inode": int(after.st_ino), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns), "link_count": int(after.st_nlink)}


def _record_literal_venv_python(path: Path) -> dict[str, Any]:
    """Record the literal venv argv0 without replacing it with its target.

    The runner must execute the venv path literally because the venv carries
    the required Python environment.  That path is normally a symlink to the
    system interpreter, so the ordinary regular-file source rule cannot be
    applied to the argv0 itself.  We bind both the symlink metadata and the
    resolved interpreter bytes; the command still contains ``path``.
    """
    path = _abs(path)
    if not path.is_symlink():
        raise BuildFailure(f"literal venv Python must be a symlink: {path}")
    target = path.resolve(strict=True)
    if target == path or target.suffix.lower() in FORBIDDEN or not target.is_file() or target.is_symlink():
        raise BuildFailure(f"literal venv Python target is unsafe: {path} -> {target}")
    before_link = path.lstat()
    before_target = target.stat()
    if not stat.S_ISREG(before_target.st_mode) or before_target.st_size > MAX_SOURCE_BYTES:
        raise BuildFailure(f"literal venv Python target is missing, unsafe, or too large: {target}")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    after_target = target.stat()
    after_link = path.lstat()
    if (before_link.st_dev, before_link.st_ino, before_link.st_size, before_link.st_mtime_ns, before_link.st_ctime_ns) != (after_link.st_dev, after_link.st_ino, after_link.st_size, after_link.st_mtime_ns, after_link.st_ctime_ns):
        raise BuildFailure(f"literal venv Python symlink changed while being read: {path}")
    if (before_target.st_dev, before_target.st_ino, before_target.st_size, before_target.st_mtime_ns, before_target.st_ctime_ns) != (after_target.st_dev, after_target.st_ino, after_target.st_size, after_target.st_mtime_ns, after_target.st_ctime_ns):
        raise BuildFailure(f"literal venv Python target changed while being read: {target}")
    return {
        "path": str(path),
        "label": "literal venv Python argv0",
        "bytes": int(after_target.st_size),
        "sha256": digest,
        "device": int(after_target.st_dev),
        "inode": int(after_target.st_ino),
        "mtime_ns": int(after_target.st_mtime_ns),
        "ctime_ns": int(after_target.st_ctime_ns),
        "link_count": int(after_target.st_nlink),
        "literal_argv0": True,
        "symlink_target": str(target),
        "symlink_device": int(after_link.st_dev),
        "symlink_inode": int(after_link.st_ino),
        "symlink_mtime_ns": int(after_link.st_mtime_ns),
        "symlink_ctime_ns": int(after_link.st_ctime_ns),
    }


def _write_once(path: Path, value: Any) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing to overwrite output: {path}")
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


def _sha_argument(value: str, label: str) -> str:
    value = str(value)
    if value in {"PARENT_AFTER_RESERVATION", "UNKNOWN"}:
        return value
    if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise BuildFailure(f"{label} must be a SHA256 hex string or PARENT_AFTER_RESERVATION")
    return value.lower()


def build(*, output_request: Path, output_manifest: Path, coarse_report: Path, medium_report: Path, fine_report: Path, proof_path: Path, coarse_sha: str, medium_sha: str, fine_sha: str, proof_sha: str = ROOT207_PROOF_SHA) -> dict[str, Any]:
    if not str(proof_path).startswith("/"):
        raise BuildFailure("producer proof path must be absolute")
    static_paths = [WORKER, BUILDER, CONTRACT, AUTHORITY, PYTHON, *XMLS.values()]
    static_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in static_paths:
        record = _record_literal_venv_python(path) if _abs(path) == _abs(PYTHON) else _record(path, "static comparison source")
        if record["path"] not in seen:
            static_records.append(record)
            seen.add(record["path"])
    try:
        contract_data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"cannot read comparison contract metadata: {exc}") from exc
    reader_calibration = contract_data.get("reader_calibration_prerequisite")
    if not isinstance(reader_calibration, dict) or not isinstance(reader_calibration.get("proof_sha256"), str):
        raise BuildFailure("comparison contract lacks the official writer calibration prerequisite")
    report_bindings = {
        "coarse": {"label": "coarse", "report_path": str(_abs(coarse_report)), "report_sha256": _sha_argument(coarse_sha, "coarse report")},
        "medium": {"label": "medium", "report_path": str(_abs(medium_report)), "report_sha256": _sha_argument(medium_sha, "medium report")},
        "fine": {"label": "fine", "report_path": str(_abs(fine_report)), "report_sha256": _sha_argument(fine_sha, "fine report")},
    }
    grid_bindings = []
    for label, xml_path in XMLS.items():
        xml_record = next(record for record in static_records if record["path"] == str(_abs(xml_path)))
        grid_bindings.append({**report_bindings[label], "xml_path": str(_abs(xml_path)), "xml_sha256": xml_record["sha256"], "aliases": [label, {"coarse": "dp0p0225", "medium": "dp0p020", "fine": "dp0p017"}[label]]})
    proof_binding = {"path": str(_abs(proof_path)), "sha256": _sha_argument(proof_sha, "ROOT207 proof")}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_COMPACT_JSON_GUARDED_COMPONENT_COMPARE",
        "contract_path": str(_abs(CONTRACT)),
        "contract_sha256": next(record["sha256"] for record in static_records if record["path"] == str(_abs(CONTRACT))),
        "source_files": static_records,
        "producer_proof": proof_binding,
        "grids": grid_bindings,
        "query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0],
        "source_only_preparation": {"production_native_payload_read": False, "production_h5_vtk_read": False, "solver_started": False, "ledger_mutation": False, "qualification_credit": 0},
        "deferred_input_policy": {"reports_are_compact_json_only": True, "worker_hashes_reports_after_reservation": True, "parent_must_join_actual_proof_receipt": True, "full_native_tree_scan": False},
        "reader_calibration_prerequisite": reader_calibration,
    }
    manifest_record_path = _abs(output_manifest)
    _write_once(manifest_record_path, manifest)
    manifest_record = _record(manifest_record_path, "comparison manifest")
    input_files = sorted(record["path"] for record in static_records + [manifest_record])
    input_sha256 = {record["path"]: record["sha256"] for record in static_records}
    input_sha256[manifest_record["path"]] = manifest_record["sha256"]
    report_paths = [binding["report_path"] for binding in grid_bindings]
    deferred_paths = [*report_paths, proof_binding["path"]]
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "PREPARED_LAUNCH_DISABLED",
        "kind": "audit",
        "cpu_task_kind": "audit",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_COMPONENT_SPACE_COMPARE_ROOT202",
        "attempt_id": "f1-s2-component-space-compare-root202-001",
        "cwd": str(PROJECT),
        "worktree_root": str(PROJECT),
        "command": [str(_abs(PYTHON)), str(_abs(WORKER)), "--run", "--manifest", "{attempt_root}/inputs/f1_s2_component_space_compare_manifest_v1.json", "--output", "{attempt_root}/observer/f1_s2_component_space_compare_v1.json"],
        "input_files": input_files,
        "input_sha256": input_sha256,
        "deferred_input_files": deferred_paths,
        "deferred_input_records": [{"path": path, "sha256": (proof_binding["sha256"] if path == proof_binding["path"] else next(binding["report_sha256"] for binding in grid_bindings if binding["report_path"] == path)), "worker_owned_after_reservation": True, "compact_json_only": True} for path in deferred_paths],
        "resource_scope": {"cpu_threads": 1, "omp_threads": 1, "memory_max_bytes": 1024 * 1024 * 1024, "external_storage_max_bytes": 64 * 1024 * 1024, "home_storage_max_bytes": 16 * 1024 * 1024, "wall_timeout_seconds": 300, "log_cap_bytes": 256 * 1024, "parent_guard_required": True, "gpu": False},
        "storage_scope": {"output_root": "{attempt_root}", "compact_report_only": True, "native_payloads_allowed": False, "h5_vtk_allowed": False},
        "source_binding": {"schema": VARIANT_SCHEMA, "contract": str(_abs(CONTRACT)), "worker": str(_abs(WORKER)), "producer_proof": proof_binding, "reader_calibration_prerequisite": reader_calibration, "grid_xml_control_join": True, "component_space_only": True, "world_orientation": "UNKNOWN_NOT_REQUIRED_FOR_THIS_SUBDOMAIN"},
        "comparison_scope": {"query_times_s": [0.0, 1.0, 2.0, 3.0, 4.0], "exact_time_tolerance_s": 1.0e-12, "interpolation": "FORBIDDEN", "neighbor_grid_truth": False, "continuum_owner_mass": "UNKNOWN", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "ledger_mutation": False,
        "qualification_credit": 0,
        "builder_source": str(_abs(BUILDER)),
        "builder_source_sha256": next(record["sha256"] for record in static_records if record["path"] == str(_abs(BUILDER))),
    }
    _write_once(_abs(output_request), request)
    return request


def _self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="f1-s2-compare-builder-") as temp:
        path = Path(temp) / "small.json"
        path.write_text("{}", encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert _sha_argument(digest, "fixture") == digest
        assert _sha_argument("PARENT_AFTER_RESERVATION", "fixture") == "PARENT_AFTER_RESERVATION"
    return {"schema": VARIANT_SCHEMA, "status": "PASS", "production_payload_read": False, "solver_started": False, "qualification_credit": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--coarse-report", type=Path)
    parser.add_argument("--medium-report", type=Path)
    parser.add_argument("--fine-report", type=Path)
    parser.add_argument("--producer-proof", type=Path)
    parser.add_argument("--coarse-sha256", default="PARENT_AFTER_RESERVATION")
    parser.add_argument("--medium-sha256", default="PARENT_AFTER_RESERVATION")
    parser.add_argument("--fine-sha256", default="PARENT_AFTER_RESERVATION")
    parser.add_argument("--producer-proof-sha256", default=ROOT207_PROOF_SHA)
    args = parser.parse_args(argv)
    if args.self_test:
        print(json.dumps(_self_test(), sort_keys=True))
        return 0
    required = [args.output_request, args.output_manifest, args.coarse_report, args.medium_report, args.fine_report, args.producer_proof]
    if any(item is None for item in required):
        parser.error("--output-request, --output-manifest, --coarse-report, --medium-report, --fine-report, and --producer-proof are required with --build")
    try:
        request = build(output_request=args.output_request, output_manifest=args.output_manifest, coarse_report=args.coarse_report, medium_report=args.medium_report, fine_report=args.fine_report, proof_path=args.producer_proof, coarse_sha=args.coarse_sha256, medium_sha=args.medium_sha256, fine_sha=args.fine_sha256, proof_sha=args.producer_proof_sha256)
    except Exception as exc:
        print(json.dumps({"schema": VARIANT_SCHEMA, "status": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"schema": VARIANT_SCHEMA, "status": request["status"], "request": str(_abs(args.output_request)), "manifest": str(_abs(args.output_manifest))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
