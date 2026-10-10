#!/usr/bin/env python3
"""Prepare a source-bound ROOT279 native producer→scalar parent request.

The request is execution-disabled until the parent normalizer binds a fresh
attempt root and reservation.  It joins the actual ROOT279 V5 source
manifest/request, ROOT310 ten-file snapshot proof, and the terminal ROOT277
same-CFL / ROOT278 half-CFL proof→request→receipt edges.  The deferred native
files are never read here.  The parent worker later runs the frozen ROOT279
guarded producer, the compact JSON adapter, the v2 scalar consumer, and the
independent metadata verifier in that order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV = PYTHON.parent.parent / "pyvenv.cfg"
GUARD = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
NATIVE_CHILD = HERE / "stage2_f1_native_selected_observer_v1.py"
GUARD_V4 = HERE / "stage2_f1_native_selected_observer_guarded_v4.py"
NATIVE_PHYSICAL = HERE / "stage2_native_physical_observer_v2.py"
COMPACT = HERE / "stage2_f1_s2_root279_native_compact_worker_v1.py"
SCALAR = HERE / "stage2_rotation_invariant_native_scalar_observer_v2.py"
SCALAR_REQUEST = HERE / "stage2_rotation_invariant_native_scalar_request_v2.py"
VERIFIER = HERE / "stage2_f1_s2_root279_native_scalar_verify_v1.py"
PARENT_WORKER = HERE / "stage2_f1_s2_root279_native_scalar_parent_worker_v1.py"
ROOT279_BRIDGE = HERE / "stage2_f1_s2_root279_root310_manifest_bridge_v1.py"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-parent-request.v1"
PARENT_MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-parent-manifest.v1"
ROOT279_MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v2"
ROOT279_ROOT310_MANIFEST_SCHEMA = "ds02.stage2.f1.native-selected-observer-manifest.v3-root310"
SNAPSHOT_SCHEMA = "ds02.stage2.native-source-snapshot.v2"
SNAPSHOT_STATUS = "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE"
MAX_SMALL_BYTES = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"
PLACEHOLDERS = {"PARENT_AFTER_RESERVATION_REQUIRED", "PARENT_AFTER_RESERVATION", "UNKNOWN"}


class BuildFailure(RuntimeError):
    pass


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", value))


def _record(path: Path, label: str, *, json_only: bool = False) -> dict[str, Any]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular source file: {path}")
    if json_only and path.suffix.lower() != ".json":
        raise BuildFailure(f"{label} is not JSON metadata: {path}")
    before = _stat(path)
    if before["bytes"] > MAX_SMALL_BYTES:
        raise BuildFailure(f"{label} exceeds the 10 MiB source cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while being read: {path}")
    return {"path": str(path), "label": label, "bytes": len(raw), "sha256": _sha(raw),
            "stat": after, "payload_read_by_builder": False, "scope": "bounded_source_metadata"}


def _literal_python() -> dict[str, Any]:
    path = _abs(PYTHON)
    if not path.is_symlink() or not path.exists() or not _abs(PYVENV).is_file():
        raise BuildFailure("literal project venv/pyvenv.cfg is unavailable")
    target = path.resolve(strict=True)
    if target.is_symlink() or not target.is_file():
        raise BuildFailure("literal venv target is not regular")
    link = path.lstat(); target_record = _record(target, "resolved venv interpreter")
    link_after = path.lstat()
    if (link.st_dev, link.st_ino, link.st_size, link.st_mtime_ns, link.st_ctime_ns) != (link_after.st_dev, link_after.st_ino, link_after.st_size, link_after.st_mtime_ns, link_after.st_ctime_ns):
        raise BuildFailure("literal venv symlink changed")
    return {"literal_argv0": str(path), "resolved_target": str(target),
            "resolved_target_sha256": target_record["sha256"],
            "resolved_target_record": target_record,
            "pyvenv_cfg": _record(_abs(PYVENV), "pyvenv.cfg")}


def _json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label, json_only=True)
    try:
        value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not an object")
    return value, record


def _edge(path: Path, label: str) -> dict[str, Any]:
    value, record = _json(path, label)
    record["status"] = value.get("status")
    record["schema"] = value.get("schema")
    return record


def _proof_edge(path: Path, label: str, expected_prefix: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    proof, proof_record = _json(path, label)
    if not str(proof.get("status", "")).startswith(expected_prefix):
        raise BuildFailure(f"{label} is not terminal verified: {proof.get('status')}")
    request_path = proof.get("request")
    receipt_path = proof.get("receipt")
    request_sha = proof.get("request_sha256")
    receipt_sha = proof.get("receipt_sha256")
    if not all(isinstance(item, str) for item in (request_path, receipt_path, request_sha, receipt_sha)):
        raise BuildFailure(f"{label} lacks exact request/receipt edges")
    request, request_record = _json(Path(request_path), f"{label} producer request")
    receipt, receipt_record = _json(Path(receipt_path), f"{label} execution receipt")
    if request_record["sha256"] != request_sha or receipt_record["sha256"] != receipt_sha:
        raise BuildFailure(f"{label} request/receipt SHA mismatch")
    nested = receipt.get("request")
    if not isinstance(nested, dict) or nested.get("path") != str(_abs(Path(request_path))) or nested.get("sha256") != request_sha:
        raise BuildFailure(f"{label} receipt/request identity mismatch")
    execution = receipt.get("execution")
    if not isinstance(execution, dict) or execution.get("returncode") != 0:
        raise BuildFailure(f"{label} does not explicitly report execution returncode 0")
    edges = [proof_record, request_record, receipt_record]
    return proof, proof_record, edges


def _root310_edge(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    proof, proof_record = _json(path, "ROOT310 source snapshot proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL_F1_S2_TEN_SELECTED_NATIVE_SOURCE_SINGLE_STREAM"):
        raise BuildFailure("ROOT310 proof schema/status is not the exact terminal snapshot proof")
    report_path, request_path = proof.get("report"), proof.get("request")
    if not all(isinstance(item, str) for item in (report_path, request_path)):
        raise BuildFailure("ROOT310 proof lacks report/request paths")
    report, report_record = _json(Path(report_path), "ROOT310 selected source snapshot report")
    request, request_record = _json(Path(request_path), "ROOT310 snapshot request")
    if report_record["sha256"] != proof.get("report_sha256") or request_record["sha256"] != proof.get("request_sha256"):
        raise BuildFailure("ROOT310 proof/report/request SHA mismatch")
    if report.get("schema") != SNAPSHOT_SCHEMA or report.get("status") != SNAPSHOT_STATUS:
        raise BuildFailure("ROOT310 snapshot report is not stable v2")
    files = []
    for entry in report.get("requests", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("selected_native_files"), list):
            raise BuildFailure("ROOT310 snapshot request entry lacks selected_native_files")
        files.extend(entry["selected_native_files"])
    if len(files) != 10 or len({item.get("path") for item in files}) != 10:
        raise BuildFailure("ROOT310 snapshot does not contain exactly ten selected native files")
    return proof, proof_record, [proof_record, report_record, request_record]


def _root279_source(manifest_path: Path, request_path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    manifest, manifest_record = _json(manifest_path, "ROOT279 source manifest")
    request, request_record = _json(request_path, "ROOT279 source request")
    schema = manifest.get("schema")
    if schema not in {ROOT279_MANIFEST_SCHEMA, ROOT279_ROOT310_MANIFEST_SCHEMA}:
        raise BuildFailure("ROOT279 source manifest schema mismatch")
    if schema == ROOT279_ROOT310_MANIFEST_SCHEMA:
        if manifest.get("status") != "PREPARED_ROOT279_ROOT310_SNAPSHOT_BOUND_WAITING_PARENT_NATIVE_DECODE":
            raise BuildFailure("ROOT310 source manifest status is not the exact parent-waiting status")
        cases = manifest.get("cases")
        if not isinstance(cases, list) or [item.get("label") for item in cases if isinstance(item, dict)] != ["same_cfl", "half_cfl"]:
            raise BuildFailure("ROOT310 source manifest case order is not same_cfl/half_cfl")
    deferred = manifest.get("native_deferred_records")
    if not isinstance(deferred, dict) or len(deferred) != 10:
        raise BuildFailure("ROOT279 source manifest lacks exactly ten deferred records")
    if request.get("schema") != REQUEST_SCHEMA:
        raise BuildFailure("ROOT279 source request schema mismatch")
    if request.get("native_payload_read") is True or request.get("execution_allowed") is True:
        raise BuildFailure("ROOT279 source request is not source-only")
    bound_manifest = request.get("manifest")
    if isinstance(bound_manifest, dict):
        if bound_manifest.get("path") != str(_abs(manifest_path)) or bound_manifest.get("sha256") != manifest_record["sha256"]:
            raise BuildFailure("ROOT279 source request does not exactly bind its manifest file")
    return manifest, request, [manifest_record, request_record]


def _code_records() -> list[dict[str, Any]]:
    paths = [GUARD, ROOT279_BRIDGE, NATIVE_CHILD, GUARD_V4, NATIVE_PHYSICAL, COMPACT, SCALAR,
             SCALAR_REQUEST, VERIFIER, PARENT_WORKER, Path(__file__)]
    return [_record(path, f"ROOT279 scalar chain source: {path.name}") for path in paths]


def _identity_digest(records: list[dict[str, Any]]) -> str:
    edges = [{"path": record["path"], "sha256": record["sha256"]} for record in sorted(records, key=lambda item: item["path"])]
    return hashlib.sha256(json.dumps(edges, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    root279_manifest, root279_request, root279_edges = _root279_source(args.root279_manifest, args.root279_request)
    same_proof, same_proof_record, same_edges = _proof_edge(args.same_proof, "ROOT277 same-CFL proof", "VERIFIED_ACTUAL_F1_S2_DP020_SAME_CFL")
    half_proof, half_proof_record, half_edges = _proof_edge(args.half_proof, "ROOT278 half-CFL proof", "VERIFIED_ACTUAL_F1_S2_DP020_HALF_CFL")
    root310_proof, root310_proof_record, root310_edges = _root310_edge(args.root310_proof)
    python = _literal_python()
    code_records = _code_records()
    all_edges = root279_edges + same_edges + half_edges + root310_edges + code_records + [python["pyvenv_cfg"], python["resolved_target_record"]]
    unique: dict[str, dict[str, Any]] = {record["path"]: record for record in all_edges}
    identity = _identity_digest(list(unique.values()))
    output_dir = _abs(args.output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise BuildFailure(f"refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "root279-native-scalar-parent-manifest.json"
    request_path = output_dir / "root279-native-scalar-parent-request.json"
    compact_template = {
        "schema": "ds02.stage2.f1-s2.root279-native-compact-manifest.v1",
        "status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT",
        "source_identity_digest": identity,
        "guard_result": {"path": "{attempt_root}/observer/root279-guard-result.json", "sha256": "PARENT_AFTER_RESERVATION_REQUIRED"},
        "child_report": {"path": "{attempt_root}/observer/.v1-result.json", "sha256": "PARENT_AFTER_RESERVATION_REQUIRED"},
        "outputs": {
            "same_cfl": {"path": "{attempt_root}/observer/compact/same_cfl.json"},
            "half_cfl": {"path": "{attempt_root}/observer/compact/half_cfl.json"},
        },
        "result_path": "{attempt_root}/observer/compact/root279-native-compact-result.json",
        "producer_lineage": {"root279_manifest": str(_abs(args.root279_manifest)),
                             "root279_request": str(_abs(args.root279_request)),
                             "root310_proof_sha256": root310_proof_record["sha256"],
                             "root277_proof_sha256": same_proof_record["sha256"],
                             "root278_proof_sha256": half_proof_record["sha256"]},
    }
    scalar_template = {
        "schema": "ds02.stage2.rotation-invariant-native-scalar-manifest.v2",
        "status": "READY_FOR_PARENT_ROTATION_INVARIANT_NATIVE_SCALAR",
        "source_identity": {"source_identity_digest": identity,
                            "physical_case_id": "F1_S2_DP020_ROOT279_SAME_HALF_CFL",
                            "component_basis": "PRODUCER_COMPONENT_XYZ", "world_orientation": UNKNOWN,
                            "world_directional_claims": False, "flux_claims": False, "owner_mass_claims": False},
        "attempts": [], "query_times_s": [0.0, 0.25, 0.5],
        "scientific_scope": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
    }
    parent_manifest = {
        "schema": PARENT_MANIFEST_SCHEMA,
        "status": "READY_FOR_PARENT_ROOT279_NATIVE_SCALAR",
        "source_identity_digest": identity,
        "root279": {"manifest": _record(args.root279_manifest, "ROOT279 source manifest"),
                    "request": _record(args.root279_request, "ROOT279 source request")},
        "terminal_edges": {"same_cfl": same_proof_record, "half_cfl": half_proof_record,
                            "root310": root310_proof_record},
        "compact_manifest": compact_template,
        "scalar_manifest": scalar_template,
        "runtime": {"literal_python": str(_abs(PYTHON)), "pyvenv_cfg": python["pyvenv_cfg"]["path"],
                    "guard_worker": str(_abs(GUARD)), "native_child_worker": str(_abs(NATIVE_CHILD)),
                    "root279_bridge": str(_abs(ROOT279_BRIDGE)),
                    "compact_worker": str(_abs(COMPACT)), "scalar_worker": str(_abs(SCALAR)),
                    "scalar_request_builder": str(_abs(SCALAR_REQUEST)), "verifier": str(_abs(VERIFIER)),
                    "parent_worker": str(_abs(PARENT_WORKER)), "root279_manifest": str(_abs(args.root279_manifest)),
                    "cwd": str(_abs(args.cwd)), "max_scratch_bytes": 256 * 1024 * 1024,
                    "max_log_bytes": 1024 * 1024, "guard_timeout_seconds": 1800,
                    "compact_timeout_seconds": 300, "scalar_timeout_seconds": 300,
                    "verify_timeout_seconds": 300},
        "source_closure": {"records": list(unique.values()), "complete": True,
                           "native_payload_files_in_static_closure": False,
                           "root279_deferred_native_count": 10},
        "native_mass_policy": "MassFluid/MassBound per-particle; typed role counts or per-ID native weights required for sample total",
        "world_axis_policy": "UNKNOWN; component-space scalar norms only",
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
        "execution_allowed": False,
        "native_payload_read": False,
        "solver_launch": False,
        "gencase_launch": False,
    }
    manifest_path.write_text(json.dumps(parent_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_record = _record(manifest_path, "ROOT279 parent manifest")
    static = dict(unique); static[manifest_record["path"]] = manifest_record
    request = {
        "schema": REQUEST_SCHEMA, "variant_schema": VARIANT_SCHEMA,
        "family_id": "F1", "sentinel_id": "F1-S2",
        "case_id": "F1_S2_DP020_ROOT279_NATIVE_SCALAR_CHAIN",
        "attempt_id": "ROOT_REBINDS_AFTER_RESERVATION",
        "cpu_task_kind": "audit", "cpu_threads": 1,
        "execution_allowed": False, "launch_disabled": True,
        "command": [str(_abs(PYTHON)), str(_abs(PARENT_WORKER)), "--run", "--manifest", str(manifest_path), "--attempt-root", "{attempt_root}"],
        "literal_python": python,
        "parent_manifest": manifest_record,
        "input_files": sorted(static), "input_records": static,
        "input_sha256": {path: value["sha256"] for path, value in static.items()},
        "deferred_input_records": list(root279_manifest["native_deferred_records"].values()),
        "estimated_resource_scope": {"cpu_seconds": 3600, "memory_bytes": 2 * 1024 * 1024 * 1024,
                                     "scratch_bytes": 256 * 1024 * 1024, "native_read_passes": 4,
                                     "compact_json_report_reads": 2, "scalar_json_report_reads": 2,
                                     "native_payload_read_by_builder": False},
        "status": "SOURCE_PREPARED_PARENT_AFTER_RESERVATION_REQUIRED",
        "source_only": True, "native_payload_read": False, "solver_launch": False,
        "gencase_launch": False, "ledger_mutation": False,
        "source_binding": {"root279_manifest_sha256": root279_edges[0]["sha256"],
                           "root279_request_sha256": root279_edges[1]["sha256"],
                           "root277_proof_sha256": same_proof_record["sha256"],
                           "root278_proof_sha256": half_proof_record["sha256"],
                           "root310_proof_sha256": root310_proof_record["sha256"],
                           "source_identity_digest": identity,
                           "query_times_s": [0.0, 0.25, 0.5], "interpolation": False,
                           "world_orientation": UNKNOWN},
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
    }
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    request_record = _record(request_path, "ROOT279 parent source request")
    package = {"schema": "ds02.stage2.f1-s2.root279-native-scalar-parent-package.v1",
               "status": "SOURCE_PREPARED_WAITING_PARENT_ROOT279_NATIVE_CHAIN",
               "manifest": manifest_record, "request": request_record,
               "source_identity_digest": identity, "selected_native_count": 10,
               "estimated_native_read_passes": 4, "estimated_native_read_bytes": "ROOT310 selected_native_total_bytes * 4; parent measures actual",
               "native_mass_policy": parent_manifest["native_mass_policy"],
               "world_axis": UNKNOWN, "scientific_qualification": request["scientific_qualification"],
               "production_payload_read_by_builder": False}
    package_path = output_dir / "source-package.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"manifest_path": str(manifest_path), "request_path": str(request_path), "package_path": str(package_path), "request": request, "manifest": parent_manifest}


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-parent-request-") as value:
        root = Path(value)
        # Only test the source identity and template boundary here; actual
        # terminal proofs are intentionally not fabricated in this source-only
        # builder self-test.
        code = root / "code.py"; code.write_text("print('fixture')\n")
        assert _record(code, "tiny source")["bytes"] > 0
        digest = _identity_digest([_record(code, "tiny source")])
        assert len(digest) == 64
        try:
            _valid_sha("not-a-sha")
            assert not _valid_sha("not-a-sha")
        except Exception:
            raise AssertionError("SHA validator failed")
    print("PASS_ROOT279_NATIVE_SCALAR_PARENT_REQUEST_SOURCE_BOUNDARY_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--root279-manifest", type=Path)
    parser.add_argument("--root279-request", type=Path)
    parser.add_argument("--same-proof", type=Path)
    parser.add_argument("--half-proof", type=Path)
    parser.add_argument("--root310-proof", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cwd", type=Path, default=HERE.parents[5])
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        required = (args.root279_manifest, args.root279_request, args.same_proof, args.half_proof, args.root310_proof, args.output_dir)
        if any(item is None for item in required):
            parser.error("--build requires ROOT279 manifest/request, ROOT277/278 proofs, ROOT310 proof and output directory")
        result = build(args)
        print(json.dumps({"status": "SOURCE_PREPARED_WAITING_PARENT_ROOT279_NATIVE_CHAIN", "manifest": result["manifest_path"], "request": result["request_path"], "package": result["package_path"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (BuildFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_SCALAR_PARENT_REQUEST: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
