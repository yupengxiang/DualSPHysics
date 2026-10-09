#!/usr/bin/env python3
"""Seal a V50 producer with an honest pre-run metadata record.

V47's consumed sealer requires a pre-run record that already claims
``parent_v3_full_static_content_pass=true``.  ROOT122 intentionally records
that content validation as a post-reservation parent operation instead.  This
additive sealer keeps the V47 product/contract checks, but accepts the V50
preflight schema and requires a separate, parent-produced static-content
receipt after reservation.  It never reads or hashes H5, BI4, raw, typed, or
result payloads.

The post-reservation receipt is a small JSON attestation.  Its content is
bound to the exact V50 executor/parent paths and physical hashes; the sealer
does not turn that attestation into an independent payload verification.
Scientific quality and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_v47_terminal_sealer_v1.py"
V50_PREFLIGHT_SCHEMA = "ds02.stage2.root.v50-metadata-preflight.v1"
V50_PREFLIGHT_STATUS = "ACTUAL_PARENT_V3_METADATA_VALIDATOR_PASS"
STATIC_RECEIPT_SCHEMA = "ds02.stage2.f2-v50-parent-static-content-verification.v1"
STATIC_RECEIPT_STATUS = "PASS_PARENT_STATIC_CONTENT_AFTER_RESERVATION"
STATIC_PHASE = "AFTER_ATOMIC_PARENT_RESERVATION"
SEAL_SCHEMA = "ds02.stage2.f2-v50-producer-terminal-seal.v2"
SEAL_STATUS = "READY_FOR_PARENT_V10_SEMANTIC_GUARD_V2"
BUILDER_SCHEMA = "ds02.stage2.f2-v50-terminal-sealer-v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 8 * 1024 * 1024


class SealerV50Error(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SealerV50Error(f"cannot load bound V47 sealer: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load(V1_SCRIPT, "ds02_bound_f2_v47_terminal_sealer_v1_for_v50")


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise SealerV50Error(f"{role} must be a lowercase SHA-256")
    return value


def _sha_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file(path: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).startswith("/"):
        raise SealerV50Error(f"{role} must be an absolute path")
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise SealerV50Error(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise SealerV50Error(f"{role} exceeds the metadata bound: {target}")
    return target


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SealerV50Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise SealerV50Error(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise SealerV50Error(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def _stat(path: Path) -> dict[str, int]:
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise SealerV50Error(f"metadata input is not a regular non-symlink file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _binding(path: Path, role: str) -> dict[str, Any]:
    return {"path": str(path), "role": role, "physical_sha256": _sha_file(path), **_stat(path)}


def _verify_v50_preflight(path: Path, executor_path: Path, parent_path: Path) -> dict[str, Any]:
    """Validate ROOT122's honest pre-run record and V50 graph."""
    _, value = _json(path, "V50 metadata preflight")
    if value.get("schema") != V50_PREFLIGHT_SCHEMA:
        raise SealerV50Error("V50 metadata preflight schema differs")
    if value.get("status") != V50_PREFLIGHT_STATUS:
        raise SealerV50Error("V50 metadata preflight status differs")
    if value.get("array_payload_read") is not False or value.get("qualification_credit") != "NONE":
        raise SealerV50Error("V50 preflight claims payload access or qualification credit")
    if value.get("content_hash_phase") != "AFTER_ATOMIC_PARENT_RESERVATION":
        raise SealerV50Error("V50 preflight content phase differs")
    if value.get("namespace_absent") is not True:
        raise SealerV50Error("V50 preflight namespace absence is not explicit")
    executor_value = _json(executor_path, "V50 executor request")[1]
    parent_value = _json(parent_path, "V50 parent request")[1]
    v47 = V1._module_v47()
    executor_summary = v47._verify_executor(executor_path, executor_value)
    parent_summary = v47._verify_parent(parent_path, parent_value, executor_path, executor_summary["binding"])
    expected_executor = str(executor_path)
    expected_parent = str(parent_path)
    if value.get("executor", {}).get("request") != expected_executor:
        raise SealerV50Error("V50 preflight executor path differs")
    if value.get("parent", {}).get("parent_request") != expected_parent:
        raise SealerV50Error("V50 preflight parent path differs")
    if value.get("parent", {}).get("executor_request") != expected_executor:
        raise SealerV50Error("V50 preflight parent executor path differs")
    if value.get("executor", {}).get("request_sha256") != executor_summary["binding"]["physical_sha256"]:
        raise SealerV50Error("V50 preflight executor SHA differs")
    if value.get("parent", {}).get("parent_physical_sha256") != parent_summary["binding"]["physical_sha256"]:
        raise SealerV50Error("V50 preflight parent SHA differs")
    if value.get("parent", {}).get("parent_canonical_sha256") != parent_summary["binding"]["canonical_sha256"]:
        raise SealerV50Error("V50 preflight parent canonical SHA differs")
    target = Path(executor_summary["fresh_roots"]["target_root"])
    output = Path(executor_summary["fresh_roots"]["output_root"])
    namespace = str(target.parent)
    if value.get("namespace") != namespace:
        raise SealerV50Error("V50 preflight namespace differs")
    verification_binding = _binding(path, "V50 metadata preflight")
    verification_binding.update({
        "canonical_sha256": parent_summary["binding"]["canonical_sha256"],
        "canonical_sha_scope": "v50_parent_request",
    })
    return {
        "executor": executor_summary,
        "parent": parent_summary,
        "verification": {"binding": verification_binding},
        "roots": {"target_root": target, "output_root": output},
        "preflight": value,
    }


def _verify_static_receipt(path: Path, *, executor_path: Path, parent_path: Path,
                           parent_summary: Mapping[str, Any]) -> dict[str, Any]:
    """Require the parent's real after-reservation static-content attestation."""
    _, value = _json(path, "V50 parent static-content verification")
    if value.get("schema") != STATIC_RECEIPT_SCHEMA or value.get("status") != STATIC_RECEIPT_STATUS:
        raise SealerV50Error("parent static-content receipt schema/status differs")
    if value.get("phase") != STATIC_PHASE or value.get("static_content_verified") is not True:
        raise SealerV50Error("parent static-content receipt is not after-reservation PASS")
    if value.get("request") != str(parent_path) or value.get("executor") != str(executor_path):
        raise SealerV50Error("parent static-content receipt request binding differs")
    if value.get("request_file_sha256") != parent_summary["binding"]["physical_sha256"]:
        raise SealerV50Error("parent static-content receipt parent SHA differs")
    if value.get("executor_file_sha256") != _sha_file(executor_path):
        raise SealerV50Error("parent static-content receipt executor SHA differs")
    resource = parent_summary
    parent_attempt = value.get("parent_attempt_id")
    if parent_attempt is not None and parent_attempt != resource.get("attempt_id"):
        raise SealerV50Error("parent static-content attempt differs")
    charge_id = value.get("charge_id")
    if charge_id is not None and charge_id != resource.get("charge_id"):
        raise SealerV50Error("parent static-content charge differs")
    if value.get("same_parent_ledger") is not True:
        raise SealerV50Error("parent static-content receipt is not same-ledger")
    hashes = value.get("verified_source_hashes")
    if not isinstance(hashes, Mapping) or not hashes:
        raise SealerV50Error("parent static-content source hash map is missing")
    return {"path": str(path), "physical_sha256": _sha_file(path),
            "stat": _stat(path), "value": value}


def seal_terminal(*, v50_executor_request: Path | str, v50_parent_request: Path | str,
                  v50_metadata_preflight: Path | str, parent_static_verification: Path | str,
                  terminal_manifest: Path | str, source_contract: Path | str,
                  adapter_output: Path | str, v10_request_output: Path | str,
                  seal_output: Path | str, max_wall_seconds: float = 900.0,
                  max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    executor_path = _file(v50_executor_request, "V50 executor request")
    parent_path = _file(v50_parent_request, "V50 parent request")
    preflight_path = _file(v50_metadata_preflight, "V50 metadata preflight")
    v47 = _verify_v50_preflight(preflight_path, executor_path, parent_path)
    static_receipt_path = _file(parent_static_verification, "parent static-content verification")
    static_receipt = _verify_static_receipt(
        static_receipt_path, executor_path=executor_path, parent_path=parent_path,
        parent_summary=v47["parent"])
    manifest_path, manifest_value = V1._json(terminal_manifest, "V50 terminal producer manifest")
    manifest_static = manifest_value.get("parent_static_content_verification")
    if not isinstance(manifest_static, Mapping) or manifest_static.get("path") != str(static_receipt_path):
        raise SealerV50Error("terminal manifest does not bind the parent static-content receipt")
    if manifest_static.get("physical_sha256") != static_receipt["physical_sha256"]:
        raise SealerV50Error("terminal manifest static-content receipt SHA differs")
    manifest = V1._validate_manifest(
        manifest_path, manifest_value, executor_path=executor_path, parent_path=parent_path,
        verification_path=preflight_path, v47=v47)
    contract_path, contract_value = V1._json(source_contract, "fresh source contract")
    contract = V1._validate_source_contract(
        contract_path, contract_value,
        relocated_sha=manifest["source_identity"]["relocated_runtime_view_sha256"],
        manifest=manifest_value)
    adapter_path, adapter = V1._make_adapter(
        manifest=manifest, contract=contract, contract_path=contract_path,
        v47=v47, output=Path(adapter_output).expanduser())
    request_path, request = V1._make_v10_request(
        adapter_path=adapter_path, adapter=adapter, contract_path=contract_path,
        contract=contract, v47=v47, manifest=manifest,
        output=Path(v10_request_output).expanduser(),
        max_wall_seconds=max_wall_seconds, max_result_bytes=max_result_bytes)
    seal = {
        "schema": SEAL_SCHEMA, "status": SEAL_STATUS,
        "builder": {"schema": BUILDER_SCHEMA, "path": str(SCRIPT), "sha256": _sha_file(SCRIPT)},
        "v50_metadata_preflight": v47["verification"]["binding"],
        "parent_static_content_verification": {
            "path": str(static_receipt_path), "sha256": static_receipt["physical_sha256"],
            "phase": STATIC_PHASE, "status": STATIC_RECEIPT_STATUS,
        },
        "terminal_manifest": {"path": str(manifest_path), "sha256": manifest["sha256"]},
        "source_contract": {"path": str(contract_path), "sha256": contract["sha256"],
                            "actual_current_catalog_sha256": V1.ACTUAL_CURRENT_SHA,
                            "relocated_runtime_view_sha256": manifest["source_identity"]["relocated_runtime_view_sha256"]},
        "producer_adapter": {"path": str(adapter_path), "sha256": _sha_file(adapter_path),
                              "schema": V1.PRODUCER_SCHEMA},
        "v10_request": {"path": str(request_path), "sha256": request["sha256"],
                        "schema": V1.V10_REQUEST_SCHEMA},
        "source_identity": dict(manifest["source_identity"]),
        "execution_boundary": {
            "payload_read_by_sealer": False, "typed_hdf5_read_by_sealer": False,
            "v16_result_read_by_sealer": False, "model_invoked": False, "cfd_invoked": False,
            "v10_content_read_deferred_until_parent_guard": True,
        },
        "fresh_v10_semantic_proof": {"status": "REQUIRED_AFTER_V10_RUN",
                                      "schema": V1.V10_PROOF_SCHEMA, "path": None, "sha256": None,
                                      "old_root060_reuse": "FORBIDDEN"},
        "qualification": dict(UNKNOWN),
        "limitations": [
            "V50 preflight is metadata-validator evidence only; parent static content evidence is a separate after-reservation receipt.",
            "No payload artifact was read or hashed by this sealer.",
            "Fresh V10 proof and evaluator-v4 adapter remain required; ROOT060/aabfb reuse is forbidden.",
        ],
    }
    seal["sha256"] = V1.canonical_sha(seal)
    seal_path = V1._write_new(seal_output, seal)
    return {"schema": SEAL_SCHEMA, "status": SEAL_STATUS, "seal": str(seal_path),
            "seal_sha256": seal["sha256"], "producer_adapter": str(adapter_path),
            "v10_request": str(request_path), "fresh_semantic_proof": "PENDING_V10_PARENT_GUARD",
            "payload_read_by_builder": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v50-executor-request", type=Path, required=True)
    parser.add_argument("--v50-parent-request", type=Path, required=True)
    parser.add_argument("--v50-metadata-preflight", type=Path, required=True)
    parser.add_argument("--parent-static-verification", type=Path, required=True)
    parser.add_argument("--terminal-manifest", type=Path, required=True)
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--adapter-output", type=Path, required=True)
    parser.add_argument("--v10-request-output", type=Path, required=True)
    parser.add_argument("--seal-output", type=Path, required=True)
    parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    parser.add_argument("--max-result-bytes", type=int, default=100_000_000)
    args = parser.parse_args(argv)
    try:
        result = seal_terminal(
            v50_executor_request=args.v50_executor_request,
            v50_parent_request=args.v50_parent_request,
            v50_metadata_preflight=args.v50_metadata_preflight,
            parent_static_verification=args.parent_static_verification,
            terminal_manifest=args.terminal_manifest, source_contract=args.source_contract,
            adapter_output=args.adapter_output, v10_request_output=args.v10_request_output,
            seal_output=args.seal_output, max_wall_seconds=args.max_wall_seconds,
            max_result_bytes=args.max_result_bytes)
    except (SealerV50Error, V1.SealerError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 V50 terminal sealer: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
