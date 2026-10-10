#!/usr/bin/env python3
"""Prepare the runnable, source-bound three-sentinel calibration audits.

This builder consumes the existing nine-row owner-grid *source manifest* and
creates one bounded initial-support request for each of F2-S2, F3-S1, and
F5-S1.  It only reads small source metadata.  Generated XML, Fluid/Bound
VTK, BI4, and native-header products are copied into ``deferred_input_records``
with their declared stat/SHA and are established by the parent after
reservation.  The command is a legal shared-runtime ``cpu/audit`` request;
the source artifact itself remains launch-disabled.

The self-test goes through the actual shared runtime-v2 ``run_request`` entry
using a temporary ledger and the frozen tiny product generator.  It is a
manufactured ABI test, not a production run or scientific qualification.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
LAB_ROOT = REPO_ROOT / "lagrangian-fluid-lab"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
WORKER = HERE / "stage2_three_sentinel_calibration_worker_v1.py"
FROZEN_WORKER = HERE / "stage2_three_sentinel_owner_grid_initial_support_audit_v1.py"
VERIFIER = HERE / "stage2_three_sentinel_calibration_verify_v1.py"
SCALE_REGISTRY = HERE / "stage2_three_sentinel_calibration_scales_v2.json"
CONTRACT = HERE / "stage2_three_sentinel_calibration_worker_contract_v1.json"
RUNTIME_V2 = LAB_ROOT / "scripts" / "ds_data02_runtime_v2.py"

SOURCE_MANIFEST_SCHEMAS = {
    "ds02.stage2.three-sentinel-owner-grid-initial-support-manifest.v1",
    "ds02.stage2.three-sentinel-calibration-manifest.v1",
}
REQUEST_SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.three-sentinel-calibration-manifest.v1"
TARGETS = ("F2-S2", "F3-S1", "F5-S1")
GRIDS = ("original", "coarse", "fine")
PAYLOAD_SUFFIXES = {".bi4", ".vtk", ".vtu", ".h5", ".hdf5", ".part", ".hdf"}
JSON_CAP = 10 * 1024 * 1024
QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}


class BuildFailure(RuntimeError):
    pass


def _abs(path: Path) -> Path:
    return path.expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
    }


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular(path: Path, label: str) -> Path:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    return path


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
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
        raise BuildFailure(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} must be a JSON object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after,
                   "payload_read_by_builder": True, "scope": "bounded_source_metadata"}


def _static_record(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise BuildFailure(f"{label} exceeds the 10 MiB static source cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise BuildFailure(f"{label} changed during the bounded source read: {path}")
    return {"path": str(path), "sha256": _sha(raw), "stat": after,
            "hash_status": "BOUND_SMALL_SOURCE", "payload_read_by_builder": True,
            "scope": "bounded_source_metadata", "label": label}


def _deferred_record(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise BuildFailure(f"{label} lacks an explicit path")
    path = _abs(Path(value["path"]))
    declared = value.get("sha256") if isinstance(value.get("sha256"), str) else None
    stat = value.get("stat") or value.get("stat_after") or value.get("stat_before") or {}
    if not isinstance(stat, dict):
        stat = {}
    return {
        "path": str(path), "sha256": declared, "stat": stat,
        "hash_status": "PARENT_AFTER_RESERVATION_REQUIRED",
        "payload_read_by_builder": False, "scope": "deferred_parent_product",
        "label": label,
    }


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BuildFailure(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _literal_runtime() -> dict[str, Any]:
    if not PYTHON.is_symlink() or not PYTHON.exists():
        raise BuildFailure(f"literal virtualenv interpreter is unavailable: {PYTHON}")
    target = PYTHON.resolve()
    if not target.is_file() or not PYVENV.is_file():
        raise BuildFailure("literal virtualenv target or pyvenv.cfg is unavailable")
    target_record = _static_record(target, "resolved virtualenv interpreter")
    return {
        "literal_argv0": str(PYTHON),
        "resolved_target": str(target),
        "resolved_target_record": target_record,
        "pyvenv_record": _static_record(PYVENV, "pyvenv.cfg"),
    }


def _source_cases(source: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if source.get("schema") not in SOURCE_MANIFEST_SCHEMAS:
        raise BuildFailure(f"unsupported source manifest schema: {source.get('schema')!r}")
    rows = source.get("cases")
    if not isinstance(rows, list):
        raise BuildFailure("source manifest has no cases list")
    by_sid: dict[str, list[dict[str, Any]]] = {sid: [] for sid in TARGETS}
    for row in rows:
        if not isinstance(row, dict) or row.get("sentinel_id") not in by_sid:
            continue
        if row.get("grid_label") not in GRIDS:
            raise BuildFailure("source manifest contains an invalid grid label")
        by_sid[str(row["sentinel_id"])].append(copy.deepcopy(row))
    for sid, values in by_sid.items():
        if {str(item.get("grid_label")) for item in values} != set(GRIDS):
            raise BuildFailure(f"source manifest does not contain exactly three grids for {sid}")
    return by_sid


def _add_static(static: dict[str, dict[str, Any]], path: Path, label: str) -> None:
    path = _abs(path)
    if str(path) in static:
        return
    static[str(path)] = _static_record(path, label)


def _add_case_sources(static: dict[str, dict[str, Any]], deferred: list[dict[str, Any]],
                      row: dict[str, Any], row_key: str) -> None:
    # These are source/control records needed to interpret the report.  The
    # generated products themselves are always deferred, even if a fixture is
    # tiny, so this policy cannot accidentally turn a production array into a
    # builder-time read.
    for name in ("source_xml", "source_def", "candidate_def"):
        value = row.get(name)
        if not isinstance(value, dict) or not isinstance(value.get("path"), str):
            raise BuildFailure(f"{row_key} lacks source record {name}")
        _add_static(static, Path(value["path"]), f"{row_key} {name}")
    auxiliary = row.get("motion_or_forcing")
    if isinstance(auxiliary, dict) and isinstance(auxiliary.get("path"), str):
        path = _abs(Path(auxiliary["path"]))
        size = (path.stat().st_size if path.is_file() and not path.is_symlink() else int((auxiliary.get("stat") or {}).get("bytes", 0)))
        if path.suffix.lower() in PAYLOAD_SUFFIXES or size > JSON_CAP:
            deferred.append({"row_key": row_key, "role": "motion_or_forcing", **_deferred_record(auxiliary, f"{row_key} motion/forcing")})
        else:
            _add_static(static, path, f"{row_key} motion/forcing")
    for name in ("gencase_receipt", "generated_xml", "fluid_vtk", "bound_vtk", "native_bi4", "native_header_probe"):
        value = row.get(name)
        if isinstance(value, dict) and isinstance(value.get("path"), str):
            deferred.append({"row_key": row_key, "role": name, **_deferred_record(value, f"{row_key} {name}")})
        elif name != "native_header_probe":
            raise BuildFailure(f"{row_key} lacks deferred product {name}")


def build(source_manifest_path: Path, output_dir: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    source, source_record = _json(source_manifest_path, "owner-grid source manifest")
    by_sid = _source_cases(source)
    scale, scale_record = _json(SCALE_REGISTRY, "calibration scale registry")
    if scale.get("schema") != "ds02.stage2.three-sentinel-calibration-scales.v2" or scale.get("scientific_credit") != 0:
        raise BuildFailure("calibration scale registry is not the frozen no-credit v2 registry")
    runtime = _literal_runtime()
    output_dir = _abs(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for sid in TARGETS:
        sid_dir = output_dir / sid.replace("-", "_")
        sid_dir.mkdir(parents=True, exist_ok=True)
        static: dict[str, dict[str, Any]] = {source_record["path"]: source_record,
                                             scale_record["path"]: scale_record}
        for path, label in ((WORKER, "calibration worker"), (FROZEN_WORKER, "frozen initial-support worker"),
                            (VERIFIER, "independent calibration verifier"), (RUNTIME_V2, "shared runtime v2"),
                            (CONTRACT, "calibration worker contract")):
            _add_static(static, path, label)
        static[runtime["pyvenv_record"]["path"]] = runtime["pyvenv_record"]
        static[runtime["resolved_target_record"]["path"]] = runtime["resolved_target_record"]
        rows = by_sid[sid]
        deferred: list[dict[str, Any]] = []
        for row in rows:
            _add_case_sources(static, deferred, row, f"{sid}:{row['grid_label']}")
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "status": "READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION",
            "sentinel_id": sid,
            "source_manifest": source_record,
            "calibration_scales": scale_record,
            "worker_contract": static[str(CONTRACT)],
            "cases": rows,
            "deferred_input_records": deferred,
            "scientific_scope": {
                "neighbor_grid_truth": False,
                "interpolation": False,
                "xml_mass_is_not_native_mass": True,
                "mass_rescale": False,
                "scientific_credit": 0,
            },
        }
        manifest_path = sid_dir / f"{sid.replace('-', '_')}-calibration-manifest-v1.json"
        request_path = sid_dir / f"{sid.replace('-', '_')}-calibration-request-v1.json"
        if manifest_path.exists() or request_path.exists():
            raise BuildFailure(f"refusing to overwrite immutable output for {sid}")
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
        manifest_path.write_bytes(manifest_bytes)
        manifest_record = _static_record(manifest_path, f"{sid} calibration manifest")
        static[manifest_record["path"]] = manifest_record
        input_files = sorted(static)
        input_sha256 = {path: static[path]["sha256"] for path in input_files}
        request = {
            "schema": REQUEST_SCHEMA,
            "status": "READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION",
            "request_variant": "three-sentinel-calibration-v1",
            "family_id": sid[:2],
            "sentinel_id": sid,
            "case_id": f"{sid.replace('-', '_')}_INITIAL_SUPPORT_CALIBRATION_V1",
            "attempt_id": "PARENT_ASSIGNED_AFTER_RESERVATION",
            "request_id": f"{sid.replace('-', '_').lower()}-initial-support-calibration-v1-prepared-001",
            "kind": "cpu",
            "cpu_task_kind": "audit",
            "command": [runtime["literal_argv0"], str(WORKER), "--run", "--manifest", str(manifest_path),
                        "--attempt-root", "{attempt_root}", "--output",
                        f"{{attempt_root}}/report/{sid.replace('-', '_')}-calibration-v1.json"],
            "cwd": str(LAB_ROOT),
            "worktree_root": str(REPO_ROOT),
            "max_wall_seconds": 900,
            "cpu_threads": 1,
            "estimated_storage_bytes": 1024 ** 3,
            "resource_scope": {"cpu_threads": 1, "memory_max_bytes": 4 * 1024 ** 3,
                               "max_wall_seconds": 900, "scratch_max_bytes": 1024 ** 3, "gpu": "none"},
            "input_files": input_files,
            "input_sha256": input_sha256,
            "input_records": static,
            "manifest": manifest_record,
            "calibration_scales": scale_record,
            "deferred_input_records": deferred,
            "execution_allowed": False,
            "launch_disabled": True,
            "source_only": True,
            "production_eligible": False,
            "gencase_launch": False,
            "solver_launch": False,
            "parent_v8_deferred_fields_not_credit": True,
            "read_scope": {"builder_reads_only_bounded_source_metadata": True,
                           "worker_reads_products_after_parent_reservation": True,
                           "native_header_is_optional_and_never_xml_fallback": True,
                           "no_hdf5": True, "no_solver": True, "no_gencase": True,
                           "neighbor_grid_truth": False, "interpolation": False},
            "scientific_qualification": copy.deepcopy(QUALIFICATION),
            "calibration_contract": {
                "scale_registry_status": "BOUND_BEFORE_RESULTS",
                "integration": "NOT_IN_THIS_PARENT",
                "output_sampling": "NOT_IN_THIS_PARENT",
                "spatial": "SUPPORT_ONLY_NO_CROSS_GRID_TRUTH",
                "native_header": "NATIVE_FIELDS_ONLY_NO_XML_MASS_FALLBACK",
            },
        }
        request_path.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        results.append((manifest, request))
    return results


def _init_ledger(data_root: Path) -> None:
    from datetime import datetime, timedelta, timezone
    (data_root / "runtime").mkdir(parents=True, exist_ok=True)
    ledger = {
        "schema": "ds02.runtime.resource-ledger.v1",
        "campaign_id": "three-sentinel-calibration-request-real-runtime-v2-fixture",
        "deadline_utc": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "limits": {"gpu_seconds": 0.0, "cpu_core_seconds": 3600.0,
                    "new_storage_bytes": 128 * 1024 * 1024,
                    "qualification_attempts": 0, "production_attempts": 0,
                    "storage_policy": "external", "home_min_free_bytes": 0},
        "charges": [], "reservations": [], "attempts": [],
    }
    (data_root / "runtime/resource-ledger.json").write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_actual_runtime(request_path: Path, data_root: Path) -> dict[str, Any]:
    """Invoke the actual runtime-v2 Python API through the literal venv.

    Runtime-v2 has no data-root CLI flag, so the tiny fixture imports its
    public ``run_request`` entry from a temporary launcher.  The launcher is
    not a production input and is intentionally outside the request's static
    closure; the request itself is still validated and receipt-bound by v2.
    """
    launcher = data_root / "run-runtime-v2-fixture.py"
    launcher.write_text(
        "import importlib.util, json, sys\n"
        "from pathlib import Path\n"
        "spec=importlib.util.spec_from_file_location('runtime_v2_fixture', sys.argv[3])\n"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "r=m.run_request(Path(sys.argv[1]), data_root=Path(sys.argv[2]))\n"
        "print(json.dumps({'status':r.get('status'),'output_root':r.get('output_root')}, sort_keys=True))\n"
        "raise SystemExit(0 if r.get('status') == 'completed' else 2)\n",
        encoding="utf-8",
    )
    completed = subprocess.run([str(PYTHON), str(launcher), str(request_path), str(data_root), str(RUNTIME_V2)],
                               cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        raise BuildFailure(f"real runtime-v2 fixture failed: {completed.stdout} {completed.stderr}")
    output_root = json.loads(completed.stdout.strip())["output_root"]
    receipt_path = Path(output_root) / "execution-receipt.json"
    if not receipt_path.is_file():
        raise BuildFailure("real runtime-v2 fixture did not write an execution receipt")
    return json.loads(receipt_path.read_text(encoding="utf-8"))


def self_test() -> None:
    verifier = _load_module(VERIFIER, "three_sentinel_calibration_verifier_for_builder")
    frozen = _load_module(FROZEN_WORKER, "three_sentinel_calibration_frozen_fixture")
    with tempfile.TemporaryDirectory(prefix="three-sentinel-calibration-request-") as directory:
        root = Path(directory)
        source_manifest = frozen._fixture_manifest(root / "source")
        results = build(source_manifest, root / "prepared")
        assert len(results) == 3
        data_root = root / "runtime-data"
        _init_ledger(data_root)
        for index, (manifest, request) in enumerate(results):
            request_path = root / f"runtime-request-{index}.json"
            actual = copy.deepcopy(request)
            actual.update({
                "status": "READY_FOR_PARENT_GUARD",
                "execution_allowed": True,
                "launch_disabled": False,
                "source_only": False,
                "case_id": f"{request['case_id']}_FIXTURE_{index}",
                "attempt_id": f"three-sentinel-calibration-fixture-{index:03d}",
                "request_id": f"three-sentinel-calibration-fixture-request-{index:03d}",
                "estimated_storage_bytes": 8 * 1024 * 1024,
            })
            request_path.write_text(json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            receipt = _run_actual_runtime(request_path, data_root)
            output_root = Path(receipt["output_root"])
            report_path = output_root / "report" / f"{actual['sentinel_id'].replace('-', '_')}-calibration-v1.json"
            assert report_path.is_file(), report_path
            verification = verifier.verify(manifest_path=Path(actual["manifest"]["path"]), request_path=request_path,
                                           receipt_path=output_root / "execution-receipt.json", report_path=report_path)
            assert verification["status"] == "VERIFIED_CALIBRATION_DIAGNOSTIC_NO_Q"
            if index == 0:
                # The negative cases use the actual runtime receipt/report,
                # then mutate only the metadata join.  They prove that a
                # copied receipt or a promoted integration dimension cannot
                # pass the independent verifier.
                bad_request_path = root / "bad-request.json"
                bad_request = copy.deepcopy(actual)
                bad_request["request_id"] = "tampered-request-id"
                bad_request_path.write_text(json.dumps(bad_request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                try:
                    verifier.verify(manifest_path=Path(actual["manifest"]["path"]), request_path=bad_request_path,
                                    receipt_path=output_root / "execution-receipt.json", report_path=report_path)
                except verifier.VerifyFailure:
                    pass
                else:
                    raise AssertionError("tampered request unexpectedly verified")
                bad_report_path = root / "bad-report.json"
                bad_report = json.loads(report_path.read_text(encoding="utf-8"))
                bad_report["dimension_status"]["integration"]["status"] = "PASS"
                bad_report_path.write_text(json.dumps(bad_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                try:
                    verifier.verify(manifest_path=Path(actual["manifest"]["path"]), request_path=request_path,
                                    receipt_path=output_root / "execution-receipt.json", report_path=bad_report_path)
                except verifier.VerifyFailure:
                    pass
                else:
                    raise AssertionError("promoted integration dimension unexpectedly verified")
        # The request was run by the real runtime, not a hand-written receipt.
        assert len(list((data_root / "families").rglob("execution-receipt.json"))) == 3
    print("PASS_THREE_SENTINEL_CALIBRATION_REQUEST_REAL_RUNTIME_V2_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        if args.source_manifest is None or args.output_dir is None:
            parser.error("--build requires --source-manifest and --output-dir")
        results = build(args.source_manifest, args.output_dir)
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError, AssertionError) as exc:
        print(f"FAILED_THREE_SENTINEL_CALIBRATION_REQUEST_V1: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "READY_FOR_PARENT_GUARDED_THREE_SENTINEL_CALIBRATION",
                      "requests": len(results), "scientific_credit": 0,
                      "output_dir": str(_abs(args.output_dir))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
