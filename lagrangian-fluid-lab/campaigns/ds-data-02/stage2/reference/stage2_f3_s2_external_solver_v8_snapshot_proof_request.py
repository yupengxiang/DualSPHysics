#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Prepare the ROOT133 F3-S2 solver request with the ROOT132 proof bound.

This is a forward-only adapter around the existing v7 snapshot request
builder.  It consumes the small ROOT132 snapshot JSON and its independent
verification proof, but never opens the generated BI4 payload.  The snapshot
report supplies the one-stream BI4 SHA; the proof supplies the actual
producer/request/report joins and records that the parent did not decode the
payload.  The emitted request keeps the runner's required top-level
``READY_FOR_PARENT_GUARD`` status while preserving a separate variant status.

The request is source-bound development evidence.  It does not select a GPU,
reserve storage, copy forcing data, or launch a solver.  The existing v5
materializer performs the forcing CSV copy only after the parent reservation
and source pre-hash.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V7_PATH = HERE / "stage2_f3_s2_external_solver_v7_snapshot_request.py"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
PROOF_STATUS = "VERIFIED_ACTUAL_F3_GENERATED_BI4_GUARDED_SINGLE_FD_HASH_IDENTITY"
SNAPSHOT_SCHEMA = "ds02.stage2.f3-s2.generated-bi4-source-snapshot.v1"
SNAPSHOT_STATUS = "PASS_F3_GENERATED_BI4_HASHED_STABLE"
REQUEST_SCHEMA = "ds02.stage2.external-solver-request.v5"
VARIANT_SCHEMA = "ds02.stage2.f3.s2.external-solver-request.v7-bi4-snapshot-and-root-proof"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V7 = load_module("stage2_f3_external_solver_v7_for_snapshot_proof_v8", V7_PATH)


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def small_record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": sha256(path),
        "content_scope": "small_snapshot_and_verification_json_hashed_by_builder_and_parent",
        "content_read_by_builder": True,
    }


def validate_proof(
    proof_path: Path,
    snapshot_path: Path,
    gencase_request: Path,
    receipt: Path,
) -> dict[str, Any]:
    """Validate ROOT132's actual proof without touching the BI4 payload."""

    proof_path = regular(proof_path, "ROOT132 verification proof")
    snapshot_path = regular(snapshot_path, "ROOT132 snapshot report")
    q_path = regular(gencase_request, "ROOT120 GenCase request")
    receipt_path = regular(receipt, "ROOT120 GenCase receipt")
    proof = load_json(proof_path, "ROOT132 verification proof")
    snapshot = load_json(snapshot_path, "ROOT132 snapshot report")

    if proof.get("schema") != PROOF_SCHEMA or proof.get("status") != PROOF_STATUS:
        raise ValueError("ROOT132 proof schema/status is not the verified single-FD proof")
    if snapshot.get("schema") != SNAPSHOT_SCHEMA or snapshot.get("status") != SNAPSHOT_STATUS:
        raise ValueError("ROOT132 snapshot report is not the terminal stable snapshot")
    expected_identity = {
        "family_id": "F3",
        "sentinel_id": "F3-S2",
        "physical_case_id": "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT",
    }
    for key, expected in expected_identity.items():
        if proof.get(key) != expected or snapshot.get(key) != expected:
            raise ValueError(f"ROOT132 {key} identity mismatch")

    report_ref = proof.get("report")
    if report_ref != str(snapshot_path):
        raise ValueError("ROOT132 proof does not bind the supplied snapshot report path")
    report_sha = proof.get("report_sha256")
    actual_report_sha = sha256(snapshot_path)
    if report_sha != actual_report_sha:
        raise ValueError("ROOT132 proof report SHA does not match supplied snapshot report")

    # The verification proof itself was for the snapshot request, while the
    # current solver request is bound to the same ROOT120 producer through the
    # report's producer_join.  Check those exact producer paths and SHA values.
    producer = snapshot.get("producer_join")
    if not isinstance(producer, dict):
        raise ValueError("ROOT132 snapshot has no producer join")
    if producer.get("q_path") != str(q_path) or producer.get("q_sha256") != sha256(q_path):
        raise ValueError("ROOT132 proof/report producer request mismatch")
    if producer.get("receipt_path") != str(receipt_path):
        raise ValueError("ROOT132 proof/report producer receipt mismatch")
    if producer.get("receipt_request_exact_q") is not True or producer.get("receipt_request_sha256_exact_q") is not True:
        raise ValueError("ROOT132 producer receipt is not joined exactly to ROOT120 q")

    source = snapshot.get("source")
    worker_source = proof.get("worker_source_snapshot")
    if not isinstance(source, dict) or not isinstance(worker_source, dict):
        raise ValueError("ROOT132 source proof fields are missing")
    source_sha = source.get("content_sha256") or source.get("sha256")
    if not isinstance(source_sha, str) or HEX64.fullmatch(source_sha) is None:
        raise ValueError("ROOT132 snapshot has no full BI4 SHA")
    if worker_source.get("content_sha256") != source_sha or worker_source.get("sha256") != source_sha:
        raise ValueError("ROOT132 proof worker/source BI4 SHA mismatch")
    if proof.get("parent_bi4_payload_hash") is not False or proof.get("root_bi4_payload_read_or_hash") is not False:
        raise ValueError("ROOT132 proof no-payload-read scope is not explicit")
    if proof.get("native_particle_fields_decoded") is not False or proof.get("solver_started") is not False:
        raise ValueError("ROOT132 proof indicates native decode or solver launch")
    if proof.get("parent_actual_prepost_content_hashes_equal") is not True:
        raise ValueError("ROOT132 proof lacks parent source pre/post stability")
    worker_scope = snapshot.get("worker_scope")
    if not isinstance(worker_scope, dict) or worker_scope.get("full_payload_streamed") is not True:
        raise ValueError("ROOT132 snapshot does not prove one complete BI4 stream")
    return {
        "path": str(proof_path),
        "sha256": sha256(proof_path),
        "schema": proof.get("schema"),
        "status": proof.get("status"),
        "report_path": str(snapshot_path),
        "report_sha256": actual_report_sha,
        "source_path": source.get("path"),
        "source_sha256": source_sha,
        "source_bytes": source.get("bytes"),
        "parent_payload_read_or_hash": False,
        "native_fields_decoded": False,
        "solver_started": False,
        "producer_join": producer,
    }


def canonical_sha(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    proof_binding = validate_proof(args.snapshot_proof, args.bi4_snapshot, args.gencase_request, args.receipt)
    adapted = argparse.Namespace(**vars(args))
    # v7 requires the snapshot JSON and delegates all existing runner/input
    # checks to V6/V5.  It still never opens the BI4 payload.
    staged = args.output.with_name(f".{args.output.name}.{os.getpid()}.v8-staging.json")
    adapted.output = staged
    request = V7.build(adapted)
    if staged.exists():
        staged.unlink()
    if request.get("schema") != REQUEST_SCHEMA:
        raise ValueError("delegated v7 request schema changed")

    proof_record = small_record(args.snapshot_proof, "ROOT132 actual verification proof")
    request["request_variant_schema"] = VARIANT_SCHEMA
    request["request_variant_status"] = request.get("status")
    # The shared external-v5 validator consumes this status.  Keep the v7
    # semantic status in a separate field rather than making a non-runnable
    # top-level status.
    request["status"] = "READY_FOR_PARENT_GUARD"
    request["input_files"] = sorted(set(list(request.get("input_files", [])) + [proof_record["path"]]))
    request["input_sha256"] = dict(request.get("input_sha256", {}))
    request["input_sha256"][proof_record["path"]] = proof_record["sha256"]
    request["input_content_scope"] = dict(request.get("input_content_scope", {}))
    request["input_content_scope"][proof_record["path"]] = proof_record["content_scope"]
    request["source_provenance"] = dict(request.get("source_provenance", {}))
    request["source_provenance"]["generated_bi4_snapshot_proof"] = proof_binding
    request["bi4_snapshot_binding"] = dict(request.get("bi4_snapshot_binding", {}))
    request["bi4_snapshot_binding"]["actual_verification_proof"] = proof_record
    request["bi4_snapshot_binding"]["proof_scope"] = {
        "report_sha256_joined": True,
        "producer_q_receipt_joined": True,
        "parent_payload_read_or_hash": False,
        "native_fields_decoded": False,
        "solver_started": False,
    }
    request["forcing_materialization_contract"] = {
        "copy_after_parent_reservation": True,
        "source_pre_hash_before_copy": True,
        "source_post_hash_after_copy": True,
        "builder_read_forcing_payload": False,
        "materializer": "stage2_f3_s2_external_solver_v5_materialize.py",
        "copy_is_attempt_contained": True,
    }
    request["qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    request["physical_qualification"] = {
        "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        "reason": "ROOT132 single-stream BI4 source proof and ROOT128 support are bound; solver, dt, output and observer qualification remain pending parent GPU guard",
    }
    request["sha256"] = canonical_sha(request)
    return request


def write_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    result = V7.self_test()
    if result.get("status") != "PASS":
        raise AssertionError(result)
    return {
        "status": "PASS",
        "schema": REQUEST_SCHEMA,
        "request_variant_schema": VARIANT_SCHEMA,
        "top_level_status": "READY_FOR_PARENT_GUARD",
        "proof_required": True,
        "bi4_payload_read_by_builder": False,
        "solver_started": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "generated-bi4", "support-report", "source-xml", "source-control", "output", "bi4-snapshot", "snapshot-proof"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--generated-bi4-sha256")
    parser.add_argument("--cost-basis-receipt", type=Path)
    parser.add_argument("--launch-commit")
    parser.add_argument("--case-id", default="F3_S2_OWNER_CENTERED_DP015_FULL_CFD_CANARY_ROOT133")
    parser.add_argument("--attempt-id", default="f3-s2-owner-centered-dp015-full-cfd-canary-v7-root133-001")
    parser.add_argument("--external-filesystem", default="/var/tmp/ds02-stage2")
    parser.add_argument("--external-reserve-bytes", type=int, default=8 * 1024**3)
    parser.add_argument("--home-receipt-reserve-bytes", type=int, default=16 * 1024**2)
    parser.add_argument("--max-wall-seconds", type=float, default=7200.0)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.generated_bi4, args.support_report, args.output, args.launch_commit, args.bi4_snapshot, args.snapshot_proof]
    if any(value is None for value in required):
        parser.error("--build-request requires ROOT120 q/receipt/XML/BI4, ROOT128 support, ROOT132 snapshot+proof, output and launch commit")
    request = build(args)
    write_new(args.output, request)
    print(json.dumps({"status": request["status"], "schema": REQUEST_SCHEMA, "request_variant_schema": VARIANT_SCHEMA, "output": str(args.output.resolve()), "solver_started": False, "bi4_read": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
