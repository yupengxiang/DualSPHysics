#!/usr/bin/env python3
"""Bind a completed external-v5 ROOT170 receipt for the F3 native audit.

This forward-only adapter exists because the external-v5 runner writes a
nested receipt with status ``COMPLETED_DEVELOPMENT_UNKNOWN``, returncode under
``execution``, request path/SHA under ``request``, and output root under
``filesystem``.  The V1 audit worker intentionally does not guess that shape.

``bind`` consumes only terminal receipt/proof/request metadata and small source
files.  It records stat metadata for the future ``PartOut_000.obi4`` but does
not hash or open that native payload.  It also writes a derived receipt
adapter: V1 can consume its ordinary ``completed``/top-level ``returncode``
shape, while the exact external-v5 receipt and proof remain separately bound
and immutable.  The resulting final manifest marks its raw SHA as
``PARENT_GUARD_COMPUTED``; the V2 audit entrypoint delegates to the V1 decoder
after the shared parent guard, where the actual pre/post content SHA is
obtained around official PartVTKOut.  V1 and its pending manifests remain
immutable.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


V1_PATH = Path(__file__).with_name("ds_data02_stage2_f3_s2_fine_native_motive_audit_v1.py")
_spec = importlib.util.spec_from_file_location("f3_s2_fine_native_motive_audit_v1", V1_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot import V1 worker: {V1_PATH}")
_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v1)

SCHEMA = "ds02.stage2.f3.s2.fine-native-motive-binder.v2"
REQUEST_SCHEMA = "ds02.stage2.f3.s2.fine-native-motive-binder-request.v2"
RECEIPT_ADAPTER_SCHEMA = "ds02.stage2.external-solver-receipt-adapter.v1"
PARENT_GUARD_COMPUTED = "PARENT_GUARD_COMPUTED"


class FineMotiveBinderError(ValueError):
    """Raised for a terminal receipt/proof identity mismatch."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_json(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FineMotiveBinderError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FineMotiveBinderError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FineMotiveBinderError(f"{label} is not a JSON object")
    return value


def small_ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FineMotiveBinderError(f"{role} is missing: {path}")
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": sha256_file(path),
        "source_scope": "SMALL_METADATA_OR_SOURCE",
    }


def payload_stat_ref(path: Path, role: str) -> dict[str, Any]:
    """Record native payload stat without opening or hashing its contents."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FineMotiveBinderError(f"{role} is missing: {path}")
    if path.name != "PartOut_000.obi4":
        raise FineMotiveBinderError(f"{role} is not PartOut_000.obi4: {path}")
    stat = path.stat()
    return {
        "role": role,
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": PARENT_GUARD_COMPUTED,
        "content_sha256_status": "DEFERRED_TO_GUARDED_DECODER_PRE_POST",
        "content_opened_by_binder": False,
        "source_scope": "PARENT_GUARDED_NATIVE_PAYLOAD_STAT_ONLY",
    }


def normalized_receipt_adapter(
    *,
    external_receipt: dict[str, Any],
    external_receipt_ref: dict[str, Any],
    external_proof_ref: dict[str, Any],
    request_ref: dict[str, Any],
    output_root: str,
    attempt_id: str,
) -> dict[str, Any]:
    """Normalize an external-v5 receipt for the immutable V1 audit contract.

    The adapter is a derived metadata file.  It does not replace or mutate the
    producer receipt: the original receipt and proof stay separately bound in
    ``terminal_binding.refs`` and in the request input list.  V1 only needs the
    normalized top-level status/returncode/request/output-root fields; every
    such field is copied from the already validated external-v5 chain.
    """
    return {
        "schema": RECEIPT_ADAPTER_SCHEMA,
        "status": "completed",
        "returncode": 0,
        "attempt_id": attempt_id,
        "output_root": output_root,
        "request": {
            "path": request_ref["path"],
            "sha256": request_ref["sha256"],
            "attempt_id": attempt_id,
        },
        "normalized_from": {
            "schema": external_receipt.get("schema"),
            "status": external_receipt.get("status"),
            "execution_returncode": (external_receipt.get("execution") or {}).get("returncode"),
            "source_verified_after_reservation": (external_receipt.get("execution") or {}).get("source_verified_after_reservation"),
            "receipt": external_receipt_ref,
            "proof": external_proof_ref,
        },
        "source_scope": "DERIVED_METADATA_ADAPTER_EXTERNAL_V5_TO_V1_AUDIT",
        "native_content_opened_by_adapter": False,
    }


def _resolve(path: str, label: str) -> str:
    if not isinstance(path, str):
        raise FineMotiveBinderError(f"{label} is not a path")
    return str(Path(path).expanduser().resolve())


def validate_external_v5_receipt(
    receipt_path: Path,
    *,
    expected_request_path: Path,
    expected_request_sha256: str,
    expected_case_id: str,
    expected_attempt_id: str,
    expected_family_id: str,
    expected_physical_case_id: str,
    expected_output_root: Path,
    proof_path: Path | None = None,
) -> dict[str, Any]:
    """Validate one exact external-v5 terminal chain using metadata only."""
    receipt_path = Path(receipt_path).expanduser().resolve()
    receipt = require_json(receipt_path, "external-v5 receipt")
    if receipt.get("schema") != "ds02.stage2.external-solver-report.v5":
        raise FineMotiveBinderError("receipt schema is not external-solver-report.v5")
    if receipt.get("status") != "COMPLETED_DEVELOPMENT_UNKNOWN":
        raise FineMotiveBinderError(f"receipt status is not COMPLETED_DEVELOPMENT_UNKNOWN: {receipt.get('status')!r}")
    execution = receipt.get("execution")
    if not isinstance(execution, dict) or execution.get("returncode") != 0:
        raise FineMotiveBinderError("receipt execution.returncode is not zero")
    if execution.get("source_verified_after_reservation") is not True:
        raise FineMotiveBinderError("receipt lacks after-reservation source verification")
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise FineMotiveBinderError("receipt request object is missing")
    request_path = _resolve(request.get("path"), "receipt request.path")
    expected_request_path = str(Path(expected_request_path).expanduser().resolve())
    if request_path != expected_request_path:
        raise FineMotiveBinderError("receipt request path differs from expected ROOT170 request")
    if request.get("sha256") != expected_request_sha256:
        raise FineMotiveBinderError("receipt request SHA differs from expected ROOT170 request")
    request_data = require_json(Path(request_path), "embedded external-v5 request")
    actual_request_sha = sha256_file(Path(request_path))
    if actual_request_sha != expected_request_sha256:
        raise FineMotiveBinderError("embedded request content SHA differs")
    if request_data.get("schema") != _v1.ROOT170_REQUEST_SCHEMA:
        raise FineMotiveBinderError("embedded request schema differs")
    expected_request_fields = {
        "case_id": expected_case_id,
        "attempt_id": expected_attempt_id,
        "family_id": expected_family_id,
        "physical_case_id": expected_physical_case_id,
    }
    for field, expected in expected_request_fields.items():
        if request_data.get(field) != expected:
            raise FineMotiveBinderError(f"embedded request {field} differs")
    expected_receipt_attempt = f"{expected_family_id}/{expected_case_id}/{expected_attempt_id}"
    if receipt.get("attempt_id") != expected_receipt_attempt:
        raise FineMotiveBinderError("receipt attempt_id differs from exact request chain")
    filesystem = receipt.get("filesystem")
    if not isinstance(filesystem, dict):
        raise FineMotiveBinderError("external-v5 receipt filesystem object is missing")
    output_root = _resolve(filesystem.get("output_root"), "receipt filesystem.output_root")
    expected_output_root = str(Path(expected_output_root).expanduser().resolve())
    if output_root != expected_output_root:
        raise FineMotiveBinderError("receipt output root differs from expected ROOT170 output root")
    proof_ref = None
    proof = None
    if proof_path is not None:
        proof_path = Path(proof_path).expanduser().resolve()
        proof = require_json(proof_path, "external-v5 verification proof")
        proof_request = _resolve(proof.get("request"), "proof request")
        if proof_request != expected_request_path or proof.get("request_sha256") != expected_request_sha256:
            raise FineMotiveBinderError("proof request path/SHA does not match receipt chain")
        proof_receipt = _resolve(proof.get("receipt"), "proof receipt")
        if proof_receipt != str(receipt_path) or proof.get("receipt_sha256") != sha256_file(receipt_path):
            raise FineMotiveBinderError("proof receipt path/SHA does not match receipt")
        proof_ref = small_ref(proof_path, "terminal_proof")
        if proof.get("BI4_H5_VTK_or_native_content_read_by_root") is True:
            raise FineMotiveBinderError("proof claims root read native content before guarded decoder")
    return {
        "receipt": small_ref(receipt_path, "terminal_receipt"),
        "receipt_status": receipt["status"],
        "execution_returncode": execution["returncode"],
        "request": small_ref(Path(request_path), "root170_request"),
        "request_chain": {**expected_request_fields, "receipt_attempt_id": receipt["attempt_id"]},
        "filesystem_output_root": output_root,
        "source_verified_after_reservation": execution["source_verified_after_reservation"],
        "proof": proof_ref,
        "proof_status": proof.get("status") if isinstance(proof, dict) else None,
    }


def _load_pending(path: Path) -> dict[str, Any]:
    manifest = require_json(Path(path), "pending ROOT182 manifest")
    if manifest.get("schema") != _v1.MANIFEST_SCHEMA:
        raise FineMotiveBinderError("pending manifest schema differs")
    if manifest.get("status") != "WAITING_FOR_ROOT170_TERMINAL_BINDING":
        raise FineMotiveBinderError("pending manifest is not the immutable ROOT182 waiting manifest")
    case = manifest.get("case")
    if not isinstance(case, dict) or case.get("case_id") != _v1.ROOT170_CASE_ID:
        raise FineMotiveBinderError("pending manifest case differs")
    return manifest


def bind_terminal(
    *,
    pending_manifest: Path,
    terminal_receipt: Path,
    terminal_proof: Path,
    output_manifest: Path,
    output_request: Path,
    output_receipt_adapter: Path,
    raw_partout: Path | None = None,
    runparts: Path | None = None,
    run_out: Path | None = None,
    generated_xml: Path | None = None,
) -> dict[str, Any]:
    """Build an additive ready manifest/request without reading raw PartOut."""
    pending = _load_pending(pending_manifest)
    root170 = pending["root170_binding"]
    root170_request_ref = root170["request"]
    root170_request = Path(root170_request_ref["path"]).expanduser().resolve()
    root170_data = require_json(root170_request, "ROOT170 request")
    output_root = Path(root170["output_root"]).expanduser().resolve()
    terminal = validate_external_v5_receipt(
        terminal_receipt,
        expected_request_path=root170_request,
        expected_request_sha256=root170_request_ref["sha256"],
        expected_case_id=_v1.ROOT170_CASE_ID,
        expected_attempt_id=_v1.ROOT170_ATTEMPT_ID,
        expected_family_id="F3",
        expected_physical_case_id=_v1.PHYSICAL_CASE_ID,
        expected_output_root=output_root,
        proof_path=terminal_proof,
    )
    # Defaults are derived from the exact receipt output root, never discovered
    # with a glob.  Callers can pass explicit paths when the materializer uses a
    # documented layout alias; the resolved paths remain exact in the manifest.
    solver_output_root = output_root / "solver_output"
    raw_partout = Path(raw_partout or solver_output_root / "data" / "PartOut_000.obi4").expanduser().resolve()
    runparts = Path(runparts or solver_output_root / "RunPARTs.csv").expanduser().resolve()
    run_out = Path(run_out or solver_output_root / "Run.out").expanduser().resolve()
    generated_xml_default = root170_data.get("source_provenance", {}).get("generated_xml", {}).get("path")
    if generated_xml is None:
        if not isinstance(generated_xml_default, str):
            raise FineMotiveBinderError("ROOT170 request has no generated XML path")
        generated_xml = Path(generated_xml_default)
    generated_xml = Path(generated_xml).expanduser().resolve()
    # All small terminal files are hashed now.  The PartOut record is stat-only;
    # the parent guard/decoder owns its first content SHA and post-read SHA.
    original_receipt_ref = terminal["receipt"]
    original_proof_ref = terminal["proof"]
    if original_proof_ref is None:
        raise FineMotiveBinderError("terminal proof binding is required")
    request_ref = terminal["request"]
    adapter_value = normalized_receipt_adapter(
        external_receipt=require_json(Path(original_receipt_ref["path"]), "external-v5 receipt"),
        external_receipt_ref=original_receipt_ref,
        external_proof_ref=original_proof_ref,
        request_ref=request_ref,
        output_root=terminal["filesystem_output_root"],
        attempt_id=terminal["request_chain"]["attempt_id"],
    )
    output_receipt_adapter = Path(output_receipt_adapter).expanduser().resolve()
    atomic_json(output_receipt_adapter, adapter_value)
    adapter_ref = small_ref(output_receipt_adapter, "terminal_receipt_adapter")
    terminal_refs = {
        # V1 receives this normalized derived receipt.  The producer's exact
        # external-v5 receipt remains separately bound below and is never
        # replaced or edited.
        "terminal_receipt": adapter_ref,
        "external_v5_receipt": original_receipt_ref,
        "terminal_proof": original_proof_ref,
        "raw_partout": payload_stat_ref(raw_partout, "raw_partout"),
        "runparts": small_ref(runparts, "runparts"),
        "run_out": small_ref(run_out, "run_out"),
        "generated_xml": small_ref(generated_xml, "generated_xml"),
    }
    final = json.loads(json.dumps(pending))
    final["status"] = "READY_FOR_GUARDED_AUDIT"
    final["binder"] = {
        "schema": SCHEMA,
        "status": "COMPLETED_METADATA_ONLY_TERMINAL_BIND",
        "pending_manifest": small_ref(Path(pending_manifest), "pending_manifest"),
        "terminal_validation": terminal,
        "raw_content_sha_policy": "PARENT_GUARD_COMPUTED_BY_V1_DECODER_PRE_POST",
        "receipt_adapter": adapter_ref,
    }
    final["terminal_binding"] = {
        "status": "READY_FOR_GUARDED_AUDIT",
        "solver_output_root": str(solver_output_root),
        "receipt_output_root": terminal["filesystem_output_root"],
        "refs": terminal_refs,
        "external_v5_terminal_chain": {
            "receipt": original_receipt_ref,
            "proof": original_proof_ref,
            "normalized_receipt_adapter": adapter_ref,
            "status": terminal["receipt_status"],
            "execution_returncode": terminal["execution_returncode"],
        },
        "raw_partout_sha256_policy": PARENT_GUARD_COMPUTED,
        "raw_partout_content_opened_by_binder": False,
        "required_decoder": "V1 audit obtains raw PartOut pre/post full content SHA only after parent guard",
    }
    final["read_policy"] = {
        **(final.get("read_policy") or {}),
        "binder_terminal_receipt_opened": True,
        "binder_terminal_proof_opened": True,
        "binder_raw_partout_stat_only": True,
        "binder_raw_partout_content_opened": False,
        "binder_runparts_content_opened": False,
        "binder_run_out_content_opened": False,
        "decoder_raw_content_deferred": True,
        "terminal_receipt_adapter_written": True,
        "external_v5_receipt_preserved": True,
    }
    output_manifest = Path(output_manifest).expanduser().resolve()
    atomic_json(output_manifest, final)
    # This is a new guarded audit request, not permission to run the binder or
    # solver.  It names the V1 decoder and keeps raw payload SHA deferred.
    worker_v2 = Path(__file__).resolve()
    worker_v1 = V1_PATH.resolve()
    input_paths = [str(output_manifest), str(worker_v1), str(worker_v2), str(pending_manifest.resolve())]
    for role in ("terminal_receipt", "external_v5_receipt", "terminal_proof", "runparts", "run_out", "generated_xml"):
        input_paths.append(terminal_refs[role]["path"])
    input_paths.append(terminal_refs["raw_partout"]["path"])
    # Deduplicate while preserving role order.
    input_paths = list(dict.fromkeys(input_paths))
    input_hashes = {}
    for path in input_paths:
        if path == terminal_refs["raw_partout"]["path"]:
            input_hashes[path] = PARENT_GUARD_COMPUTED
        else:
            input_hashes[path] = sha256_file(Path(path))
    request = {
        "schema": "ds02.runner-request.v1",
        "request_schema": REQUEST_SCHEMA,
        "attempt_id": "f3-s2-fine-native-motive-audit-v2-root-forward-terminal-001",
        "case_id": "f3-s2-fine-native-motive-audit-v2-root-forward-terminal-001",
        "family_id": "infra",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "max_memory_bytes": 1073741824,
        "estimated_storage_bytes": 134217728,
        "estimated_native_read_bytes": "UNKNOWN_UNTIL_GUARDED_PARTOUT",
        "estimated_hdf5_read_bytes": 0,
        "estimated_part_frame_read_bytes": 0,
        "launch_allowed": True,
        "status": "prepared_guard_pending_native_decoder",
        "primary_launch_owner": "root",
        "command": [
            "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
            str(worker_v2), "audit", "--manifest", str(output_manifest),
            "--output", "{attempt_root}/f3-s2-fine-native-motive-audit-v2.json",
        ],
        "input_files": input_paths,
        "input_sha256": input_hashes,
        "manifest_contract": {
            "manifest": str(output_manifest),
            "manifest_sha256": sha256_file(output_manifest),
            "raw_partout_sha256": PARENT_GUARD_COMPUTED,
            "raw_partout_pre_post_sha_required": True,
            "h5_opened": False,
            "part_frames_opened": False,
            "solver_started": False,
            "forbid_threads_flag": True,
        },
        "source_cost": {
            "metadata_bytes_read_by_binder": sum(Path(path).stat().st_size for path in input_paths if path != terminal_refs["raw_partout"]["path"]),
            "raw_partout_bytes_read": "UNKNOWN_UNTIL_GUARDED_DECODER",
            "raw_partout_content_hash_owner": "V1 decoder after parent guard",
            "trajectory_h5_bytes_read": 0,
            "part_frame_bytes_read": 0,
            "solver_started": False,
        },
        "claim_boundary": (pending.get("semantic_contract") or {}),
        "root170_terminal_validation": terminal,
    }
    atomic_json(Path(output_request), request)
    return {"manifest": final, "request": request, "terminal_validation": terminal}


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise FineMotiveBinderError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(fd)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def audit(manifest: Path, output: Path) -> dict[str, Any]:
    """Run the immutable V1 native audit against a V2-adapted manifest.

    The V2 manifest points V1's required ``terminal_receipt`` role at the
    normalized adapter while retaining the exact external-v5 receipt and
    proof as separate refs.  V1 therefore performs its usual source/path,
    PartOut pre/post, and official decoder checks without being taught a new
    receipt schema or accepting an unbound terminal.
    """
    return _v1.audit(Path(manifest), Path(output))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bind = sub.add_parser("bind")
    bind.add_argument("--pending-manifest", required=True, type=Path)
    bind.add_argument("--terminal-receipt", required=True, type=Path)
    bind.add_argument("--terminal-proof", required=True, type=Path)
    bind.add_argument("--output-manifest", required=True, type=Path)
    bind.add_argument("--output-request", required=True, type=Path)
    bind.add_argument("--output-receipt-adapter", required=True, type=Path)
    bind.add_argument("--raw-partout", type=Path)
    bind.add_argument("--runparts", type=Path)
    bind.add_argument("--run-out", type=Path)
    bind.add_argument("--generated-xml", type=Path)
    aud = sub.add_parser("audit")
    aud.add_argument("--manifest", required=True, type=Path)
    aud.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "bind":
            result = bind_terminal(
                pending_manifest=args.pending_manifest,
                terminal_receipt=args.terminal_receipt,
                terminal_proof=args.terminal_proof,
                output_manifest=args.output_manifest,
                output_request=args.output_request,
                output_receipt_adapter=args.output_receipt_adapter,
                raw_partout=args.raw_partout,
                runparts=args.runparts,
                run_out=args.run_out,
                generated_xml=args.generated_xml,
            )
            print(json.dumps({"schema": SCHEMA, "status": result["manifest"]["status"], "launch_allowed": result["request"]["launch_allowed"]}, sort_keys=True))
        else:
            result = audit(args.manifest, args.output)
            print(json.dumps({"schema": result["schema"], "status": result["status"], "rows": result["native_identity"]["row_count"]}, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"F3-S2 fine native motive terminal binder failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
