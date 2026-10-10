#!/usr/bin/env python3
"""Build the additive V2 source-bound V10 CPU request for the F1-S2 JSON diagnostic.

The builder binds ROOT362 and the ROOT277/278 terminal proof edges, the two
compact reports, and the frozen calibration contract.  It reads only bounded
JSON metadata and emits an ordinary ``ds02.request.v1`` request.  The request
is intentionally launch-disabled: the parent normalizer owns the attempt root
and admission, while the worker itself has no solver, native, VTK, or HDF5
read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PRIMARY_REFERENCE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference")
PRIMARY_LAB = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
WORKER = HERE / "stage2_f1_s2_integral_output_separation_v1.py"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.integral-output-separation-request.v2"
# The consumed worker V1 accepts this manifest schema/status.  V2 changes the
# request binding/path semantics, not the worker's data contract.
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.integral-output-separation-manifest.v1"
MANIFEST_STATUS = "PREPARED_ROOT371_F1_S2_INTEGRAL_OUTPUT_DIAGNOSTIC"
MAX_SMALL_BYTES = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"


class BuildFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, label: str) -> tuple[Any, dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not JSON metadata: {exc}") from exc
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after, "bytes": len(raw), "scope": "bounded_json_metadata", "payload_read_by_builder": True}


def _source_record(path: Path, label: str, *, runtime_path: Path | None = None) -> dict[str, Any]:
    value, record = _read_json(path, label)
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not an object")
    if runtime_path is not None:
        record["source_preparation_path"] = record["path"]
        record["path"] = str(runtime_path.expanduser().absolute())
        record["primary_path_after_cherry_pick"] = record["path"]
    return record


def _code_record(path: Path, label: str, relative_name: str) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular source file: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds the source cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed during bounded source read")
    runtime_path = PRIMARY_REFERENCE / relative_name
    return {"path": str(runtime_path), "source_preparation_path": str(path), "sha256": _sha(raw), "stat": after, "bytes": len(raw), "scope": "bounded_worker_source", "payload_read_by_builder": False}


def _runtime_record(path: Path, label: str, relative_name: str | None = None) -> dict[str, Any]:
    if relative_name is None:
        return _source_record(path, label)
    source_record = _code_record(path, label, relative_name)
    runtime_path = Path(source_record["path"])
    if runtime_path.is_file() and not runtime_path.is_symlink():
        _, runtime_record = _read_json(runtime_path, f"{label} primary path")
        if runtime_record["sha256"] != source_record["sha256"]:
            raise BuildFailure(f"{label} primary path content differs from the prepared source")
        runtime_record["source_preparation_path"] = source_record["source_preparation_path"]
        runtime_record["primary_path_after_cherry_pick"] = str(runtime_path)
        runtime_record["scope"] = source_record["scope"]
        runtime_record["payload_read_by_builder"] = False
        return runtime_record
    return source_record


def _proof_status(proof: dict[str, Any], label: str, prefix: str) -> None:
    if not str(proof.get("status", "")).startswith(prefix):
        raise BuildFailure(f"{label} is not the expected completed proof: {proof.get('status')}")
    q = proof.get("scientific_qualification")
    if isinstance(q, dict) and any(q.get(key) not in (None, UNKNOWN) for key in ("QI", "QN", "QE")):
        raise BuildFailure(f"{label} contains unauthorized scientific qualification")


def _receipt_edge(proof: dict[str, Any], proof_record: dict[str, Any], label: str, prefix: str) -> list[dict[str, Any]]:
    _proof_status(proof, label, prefix)
    request_path = proof.get("request")
    receipt_path = proof.get("receipt")
    if not all(isinstance(value, str) for value in (request_path, receipt_path)):
        raise BuildFailure(f"{label} lacks request/receipt paths")
    request, request_record = _read_json(Path(request_path), f"{label} request")
    receipt, receipt_record = _read_json(Path(receipt_path), f"{label} receipt")
    if not isinstance(request, dict) or not isinstance(receipt, dict):
        raise BuildFailure(f"{label} request/receipt are not objects")
    if proof.get("request_sha256") != request_record["sha256"] or proof.get("receipt_sha256") != receipt_record["sha256"]:
        raise BuildFailure(f"{label} proof does not bind request/receipt bytes")
    nested = receipt.get("request")
    if not isinstance(nested, dict) or nested.get("sha256") != request_record["sha256"]:
        raise BuildFailure(f"{label} receipt does not bind the producer request")
    execution = receipt.get("execution")
    if not isinstance(execution, dict) or execution.get("returncode") != 0:
        raise BuildFailure(f"{label} receipt does not explicitly report returncode 0")
    return [proof_record, request_record, receipt_record]


def _literal_python() -> dict[str, Any]:
    path = PYTHON.expanduser().absolute()
    cfg = PYVENV.expanduser().absolute()
    if not path.is_symlink() or not path.exists() or not cfg.is_file():
        raise BuildFailure("literal project venv or pyvenv.cfg is unavailable")
    target = path.resolve(strict=True)
    if target.is_symlink() or not target.is_file():
        raise BuildFailure("resolved venv target is not a regular file")
    raw = target.read_bytes(); target_stat = _stat(target)
    cfg_raw = cfg.read_bytes(); cfg_stat = _stat(cfg)
    return {"literal_argv0": str(path), "resolved_target": str(target), "resolved_target_sha256": _sha(raw), "resolved_target_stat": target_stat, "pyvenv_cfg": {"path": str(cfg), "sha256": _sha(cfg_raw), "stat": cfg_stat, "bytes": len(cfg_raw), "scope": "runtime_provenance"}}


def _generated_manifest_record(path: Path, label: str) -> dict[str, Any]:
    """Bind the freshly generated manifest at its actual static path.

    The V1 helper remapped any basename to PRIMARY_REFERENCE and therefore
    rejected a newly generated manifest whose bytes differ from an older
    prepared file.  V2 treats this manifest as a new source input and keeps
    the exact output path used by the parent command.
    """
    value, record = _read_json(path, label)
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not an object")
    record["scope"] = "fresh_generated_manifest_static_input"
    record["payload_read_by_builder"] = False
    return record


def build(*, root362_proof_path: Path, calibration_path: Path, output_dir: Path) -> dict[str, Any]:
    proof, proof_record = _read_json(root362_proof_path, "ROOT362 proof")
    if not isinstance(proof, dict):
        raise BuildFailure("ROOT362 proof is not an object")
    _proof_status(proof, "ROOT362 proof", "VERIFIED_ACTUAL_ROOT279_METADATA_RECOVERY_COMPACT_SCALAR_CHAIN_NO_NATIVE_REREAD_NO_Q")
    if proof.get("actual_native_selected_read_after_reservation") is not False or proof.get("native_payload_reopened_by_recovery") is not False or proof.get("scientific_Q_credit") != 0 or proof.get("world_orientation") != UNKNOWN:
        raise BuildFailure("ROOT362 proof has an unauthorized read/orientation/credit claim")
    recovery_path = Path(str(proof.get("report", "")))
    recovery, recovery_record = _read_json(recovery_path, "ROOT362 recovery report")
    if proof.get("report_sha256") != recovery_record["sha256"]:
        raise BuildFailure("ROOT362 proof/report SHA mismatch")
    if recovery.get("schema") != "ds02.stage2.f1-s2.root279-native-scalar-recovery-worker.v1" or recovery.get("status") != "COMPLETE_ROOT279_METADATA_RECOVERY_COMPACT_V3_SCALAR_V2_VERIFIER_NO_NATIVE_REREAD":
        raise BuildFailure("ROOT362 recovery report schema/status mismatch")
    scalar_path = Path(str(recovery.get("scalar_result", {}).get("path", "")))
    scalar, scalar_record = _read_json(scalar_path, "ROOT362 scalar result")
    if recovery.get("scalar_result", {}).get("sha256") != scalar_record["sha256"]:
        raise BuildFailure("ROOT362 recovery/scalar SHA mismatch")
    if scalar.get("schema") != "ds02.stage2.rotation-invariant-native-scalar-observer.v2" or scalar.get("status") != "COMPLETE_ROTATION_INVARIANT_NATIVE_SCALAR_DIAGNOSTIC":
        raise BuildFailure("ROOT362 scalar result schema/status mismatch")
    q = scalar.get("scientific_qualification")
    if not isinstance(q, dict) or q.get("scientific_credit") != 0 or any(q.get(key) != UNKNOWN for key in ("QI", "QN", "QE")):
        raise BuildFailure("ROOT362 scalar result contains unauthorized Q")
    calibration, calibration_source_record = _read_json(calibration_path, "F1-S2 calibration contract")
    calibration_q = calibration.get("scientific_qualification") or calibration.get("interpretation", {}).get("scientific_qualification", {})
    if calibration.get("schema") != "ds02.stage2.f1-s2.common-endpoint-calibration.v1" or calibration_q.get("QN") != UNKNOWN:
        raise BuildFailure("calibration contract schema/qualification mismatch")
    controls = calibration.get("actual_pair_controls")
    if not isinstance(controls, dict) or controls.get("same_cfl", {}).get("effective_cfl") != 0.2 or controls.get("half_cfl", {}).get("effective_cfl") != 0.1 or controls.get("common_output_contract", {}).get("output_interval_s") != 0.005:
        raise BuildFailure("calibration contract lacks the frozen .2/.1 CFL and .005 output contract")
    calibration_record = _runtime_record(Path(calibration_path), "F1-S2 frozen calibration contract", Path(calibration_path).name)
    compact_refs: dict[str, dict[str, Any]] = {}
    for attempt in scalar.get("attempts", []):
        label = str(attempt.get("label", "")).replace("-", "_")
        if label not in {"same_cfl", "half_cfl"}:
            raise BuildFailure(f"unexpected ROOT362 scalar attempt: {label}")
        ref = attempt.get("report")
        report, report_record = _read_json(Path(str(ref.get("path", ""))), f"ROOT362 {label} compact report")
        if ref.get("sha256") != report_record["sha256"] or report.get("schema") != "ds02.stage2.f1-s2.root279-native-compact-report.v1" or report.get("status") != "COMPLETE_ROOT279_NATIVE_COMPACT_REPORT":
            raise BuildFailure(f"ROOT362 {label} compact report binding/status mismatch")
        compact_refs[label] = report_record
    if set(compact_refs) != {"same_cfl", "half_cfl"}:
        raise BuildFailure("ROOT362 scalar result does not bind both compact reports")
    edge_records: list[dict[str, Any]] = []
    source_edges = calibration.get("source_edges", {})
    for label, prefix in (("same_cfl", "VERIFIED_ACTUAL_F1_S2_DP020_SAME_CFL"), ("half_cfl", "VERIFIED_ACTUAL_F1_S2_DP020_HALF_CFL")):
        proof_ref = source_edges.get(label, {}).get("proof", {})
        if not isinstance(proof_ref, dict) or not isinstance(proof_ref.get("path"), str):
            raise BuildFailure(f"calibration contract lacks {label} terminal proof")
        edge_proof, edge_record = _read_json(Path(proof_ref["path"]), f"{label} terminal proof")
        if edge_record["sha256"] != proof_ref.get("sha256"):
            raise BuildFailure(f"{label} terminal proof SHA differs from calibration contract")
        edge_records.extend(_receipt_edge(edge_proof, edge_record, f"{label} terminal proof", prefix))
    python = _literal_python()
    source_records = [
        _code_record(WORKER, "F1-S2 integral/output worker", WORKER.name),
        _code_record(Path(__file__), "F1-S2 integral/output request builder", Path(__file__).name),
        calibration_record,
    ]
    source_records.extend([proof_record, recovery_record, scalar_record, calibration_record, *compact_refs.values(), *edge_records])
    unique = {record["path"]: record for record in source_records}
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "stage2_f1_s2_integral_output_separation_manifest_v1.json"
    request_path = output_dir / "stage2_f1_s2_integral_output_separation_request_v1.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": MANIFEST_STATUS,
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "registered_query_times_s": [0.0, 0.25, 0.5],
        "root362_proof": proof_record,
        "recovery_report": recovery_record,
        "scalar_result": scalar_record,
        "calibration_contract": calibration_record,
        "producers": [{"label": label, "report": compact_refs[label], "effective_cfl": controls[label]["effective_cfl"], "output_interval_s": controls["common_output_contract"]["output_interval_s"]} for label in ("same_cfl", "half_cfl")],
        "scope": {"integration": "trapezoid over actual saved-time rows", "output_sampling": "saved-time gaps and no-interpolation brackets", "world_orientation": UNKNOWN, "native_payload_reopened": False, "interpolation": False, "neighbor_grid_truth": False, "scientific_credit": 0},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_record = _generated_manifest_record(manifest_path, "generated F1-S2 diagnostic manifest V2")
    # The attempt manifest is materialized by the parent after reservation;
    # keep it as a bound template, rather than pretending the source-prepared
    # copy is a runtime input file with a reusable inode/stat record.
    input_records = {record["path"]: record for record in unique.values()}
    worker_runtime = str(PRIMARY_REFERENCE / WORKER.name)
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "READY_FOR_PARENT_V10_F1_S2_INTEGRAL_OUTPUT_DIAGNOSTIC_V2",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-integral-output-separation-v2-root371",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_ROOT371_INTEGRAL_OUTPUT_SEPARATION",
        "attempt_id": "PARENT_ASSIGNED_AFTER_RESERVATION",
        "cwd": str(PRIMARY_LAB),
        "worktree_root": str(PRIMARY_LAB.parent),
        "command": [str(PYTHON), worker_runtime, "--run", "--manifest", str(manifest_path), "--output", "{attempt_root}/report/f1_s2_integral_output_separation_v2.json"],
        "literal_python": python,
        "input_files": sorted(input_records),
        "input_records": input_records,
        "input_sha256": {path: record["sha256"] for path, record in input_records.items()},
        "deferred_input_files": [],
        "deferred_input_records": [],
        "manifest_template": manifest_record,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_peak_memory_bytes": 256 * 1024 * 1024,
        "estimated_input_read_bytes": sum(int(record["bytes"]) for record in input_records.values()),
        "estimated_output_bytes": 2 * 1024 * 1024,
        "estimated_storage_bytes": 8 * 1024 * 1024,
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": False,
        "launch_disabled": True,
        "solver_started": False,
        "solver_launch": False,
        "gencase_launch": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "vtk_read": False,
        "runparts_read": False,
        "ledger_mutation": False,
        "parent_admission_required": True,
        "parent_runtime_contract": "ds02_runtime_v10_after_reservation_parent_binding",
        "output_root": "{attempt_root}",
        "output": {"path": "{attempt_root}/report/f1_s2_integral_output_separation_v2.json", "atomic": True, "refuse_overwrite": True},
        "source_binding": {"root362_proof": proof_record, "same_half_compact_reports": compact_refs, "terminal_pair_proofs": {label: source_edges[label]["proof"] for label in ("same_cfl", "half_cfl")}, "world_orientation": UNKNOWN, "native_payload_reopened": False, "no_xml_mass_fallback": True, "interpolation": False, "neighbor_grid_truth": False, "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "credit": 0}},
        "resource_guard": {"runner": "parent-v10", "native_payload": "forbidden", "large_report": "forbidden", "solver_launch": "forbidden", "cancel_and_cleanup": True},
    }
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"manifest": str(manifest_path), "request": str(request_path), "manifest_value": manifest, "request_value": request}


def _self_test() -> None:
    # This validates the actual builder's request shape without fabricating a
    # production proof; production inputs are supplied only in --build mode.
    with __import__("tempfile").TemporaryDirectory(prefix="f1-s2-request-builder-") as temporary:
        root = Path(temporary)
        calibration = root / "calibration.json"
        calibration.write_text(json.dumps({"schema": "ds02.stage2.f1-s2.common-endpoint-calibration.v1", "scientific_qualification": {"QN": UNKNOWN}, "actual_pair_controls": {"same_cfl": {"effective_cfl": 0.2}, "half_cfl": {"effective_cfl": 0.1}, "common_output_contract": {"output_interval_s": 0.005}}, "source_edges": {"same_cfl": {"proof": {"path": "missing", "sha256": "0" * 64}}, "half_cfl": {"proof": {"path": "missing", "sha256": "0" * 64}}}}) + "\n")
        try:
            build(root362_proof_path=root / "missing-proof.json", calibration_path=calibration, output_dir=root / "out")
        except (BuildFailure, OSError):
            pass
        else:
            raise AssertionError("missing ROOT362 proof was accepted")
    assert REQUEST_SCHEMA == "ds02.request.v1"
    assert MANIFEST_SCHEMA.endswith("manifest.v1")
    print("PASS_F1_S2_INTEGRAL_OUTPUT_REQUEST_V10_SOURCE_GATE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--root362-proof", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if any(value is None for value in (args.root362_proof, args.calibration, args.output_dir)):
            parser.error("--build requires --root362-proof, --calibration and --output-dir")
        result = build(root362_proof_path=args.root362_proof, calibration_path=args.calibration, output_dir=args.output_dir)
        print(json.dumps({"status": "SOURCE_PREPARED_WAITING_PARENT_V10_F1_S2_INTEGRAL_OUTPUT_DIAGNOSTIC", "manifest": result["manifest"], "request": result["request"], "execution_allowed": False, "scientific_credit": 0}, sort_keys=True))
        return 0
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_F1_S2_INTEGRAL_OUTPUT_REQUEST_BUILD: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
