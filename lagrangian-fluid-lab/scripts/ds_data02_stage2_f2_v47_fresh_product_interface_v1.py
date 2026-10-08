#!/usr/bin/env python3
"""Prepare the post-V47 fresh-proof/evaluator interface.

This module is deliberately a *metadata-only* hand-off.  It consumes the
small V47 executor request, its parent request, and the root metadata
verification record.  It does not open a H5/BI4/raw file or a producer/result
JSON.  Its output is therefore a closed, source-bound staging contract whose
product hashes are explicitly ``null`` until the V47 producer has completed.

The staging contract is useful before a cold run: it fixes the new output
namespace and the artifact names which a later producer/sealer must bind.  It
cannot be passed to the V8/V10 semantic consumer and it cannot be used as an
evaluator proof.  A later, producer-side sealer must replace every deferred
artifact binding with an observed path, stat, and SHA after the same-parent
guard has completed.  Historical ROOT060 products/proofs are never accepted
as substitutes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
EXECUTOR_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
PARENT_SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
VERIFICATION_SCHEMA = "ds02.stage2.root-v47-metadata-verification.v1"
PROOF_STAGING_SCHEMA = "ds02.stage2.f2-v47-fresh-proof-staging-request.v1"
EVALUATOR_STAGING_SCHEMA = "ds02.stage2.f2-v47-fresh-evaluator-staging-request.v1"
BUILDER_SCHEMA = "ds02.stage2.f2-v47-fresh-product-interface-builder.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 4 * 1024 * 1024
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
RAW_TREE_SHA = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
RAW_TREE_FILES = 405
RAW_TREE_FRAMES = 401


class V47FreshInterfaceError(RuntimeError):
    """Raised when a V47 metadata contract cannot be source-bound."""


def canonical_sha(value: Any) -> str:
    """Return the repository's canonical JSON SHA (excluding top-level SHA)."""
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    """Hash only a file explicitly supplied as bounded metadata input/output."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in HEX64 for char in value)):
        raise V47FreshInterfaceError(f"{role} must be a lowercase SHA-256")
    return value


def _absolute_file(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise V47FreshInterfaceError(f"{role} path is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise V47FreshInterfaceError(f"{role} path must be absolute: {value!r}")
    if path.is_symlink() or not path.is_file():
        raise V47FreshInterfaceError(f"{role} is not a regular non-symlink file: {path}")
    return path


def _metadata_json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _absolute_file(str(path), role)
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise V47FreshInterfaceError(f"{role} exceeds the metadata-only bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V47FreshInterfaceError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V47FreshInterfaceError(f"{role} must contain a JSON object")
    return target, value


def _stat(path: Path) -> dict[str, int]:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise V47FreshInterfaceError(f"metadata source is not a regular file: {path}")
    return {
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "mode_bits": int(stat.S_IMODE(info.st_mode)),
    }


def _unknown(value: Any, role: str) -> None:
    if value != UNKNOWN:
        raise V47FreshInterfaceError(f"{role} must remain QI/QN/QE UNKNOWN")


def _new_json(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise V47FreshInterfaceError(f"refusing to overwrite existing output: {target}")
    if target.is_symlink():
        raise V47FreshInterfaceError(f"refusing symlink output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False)
        stream.write("\n")
    return target


def _file_binding(path: Path, role: str, *, content_read: bool = True) -> dict[str, Any]:
    """Bind a small JSON input; never use this for a payload artifact."""
    info = _stat(path)
    return {
        "path": str(path),
        "role": role,
        "sha256": sha256_file(path),
        **info,
        "content_read_during_build": bool(content_read),
    }


def _canonical_file_binding(path: Path, value: Mapping[str, Any], role: str) -> dict[str, Any]:
    physical = sha256_file(path)
    canonical = _sha(value.get("sha256"), f"{role}.canonical_sha256")
    if canonical != canonical_sha(value):
        raise V47FreshInterfaceError(f"{role} canonical SHA differs")
    return {
        "path": str(path),
        "role": role,
        "physical_sha256": physical,
        "canonical_sha256": canonical,
        **_stat(path),
    }


def _verification_file_binding(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the root verification record without mislabeling its parent SHA.

    ``root-metadata-verification.json`` intentionally has no self ``sha256``
    field.  Its ``canonical_sha256`` field is the canonical SHA of the V47
    parent request.  Preserve that declaration with an explicit scope rather
    than pretending it is the verification record's own canonical digest.
    """
    declared_parent = _sha(value.get("canonical_sha256"),
                           "V47 root verification parent canonical SHA")
    return {
        "path": str(path),
        "role": "V47 root metadata verification",
        "physical_sha256": sha256_file(path),
        "canonical_sha256": declared_parent,
        "canonical_sha_scope": "v47_parent_request",
        **_stat(path),
    }


def _fresh_root(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value:
        raise V47FreshInterfaceError(f"{role} is missing")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise V47FreshInterfaceError(f"{role} must be absolute")
    return path


def _runtime_role_names(value: Mapping[str, Any]) -> list[str]:
    rows = value.get("runtime_sources")
    if not isinstance(rows, list) or not rows:
        raise V47FreshInterfaceError("V47 executor runtime_sources are missing")
    roles: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not isinstance(row.get("role"), str):
            raise V47FreshInterfaceError(f"runtime_sources[{index}] is malformed")
        _sha(row.get("sha256"), f"runtime_sources[{index}].sha256")
        relative = row.get("target_relative_path")
        if (not isinstance(relative, str) or not relative or relative.startswith("/")
                or ".." in Path(relative).parts):
            raise V47FreshInterfaceError(f"runtime_sources[{index}] has unsafe target path")
        roles.append(str(row["role"]))
    required = {"executor_v34", "python_executable", "raw_worker_v2"}
    missing = sorted(required.difference(roles))
    if missing:
        raise V47FreshInterfaceError(f"V47 runtime closure misses required roles: {missing}")
    return sorted(set(roles))


def _source_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    rows = value.get("source_entries")
    if not isinstance(rows, list) or not rows:
        raise V47FreshInterfaceError("V47 executor source_entries are missing")
    current = [row for row in rows
               if isinstance(row, Mapping)
               and row.get("role") in {"v2:current_catalog", "current_catalog"}]
    if len(current) != 1:
        raise V47FreshInterfaceError("V47 executor must have one current-catalog source row")
    current_row = current[0]
    current_sha = _sha(current_row.get("sha256"), "V47 current catalog SHA")
    if current_sha != ACTUAL_CURRENT_SHA:
        raise V47FreshInterfaceError(
            "V47 current catalog is not the exact CURRENT336 source identity")
    roles: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not isinstance(row.get("role"), str):
            raise V47FreshInterfaceError(f"source_entries[{index}] is malformed")
        _sha(row.get("sha256"), f"source_entries[{index}].sha256")
        relative = row.get("target_relative_path")
        if (not isinstance(relative, str) or not relative or relative.startswith("/")
                or ".." in Path(relative).parts):
            raise V47FreshInterfaceError(f"source_entries[{index}] has unsafe target path")
        roles.append(str(row["role"]))
    return {
        "count": len(rows),
        "roles": sorted(set(roles)),
        "current_catalog_sha256": current_sha,
    }


def _verify_executor(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema") != EXECUTOR_SCHEMA:
        raise V47FreshInterfaceError("V47 executor schema differs")
    if value.get("sha256") != canonical_sha(value):
        raise V47FreshInterfaceError("V47 executor canonical SHA differs")
    if value.get("status") != "READY_FOR_PARENT_STAGE2_GUARD":
        raise V47FreshInterfaceError("V47 executor is not ready for its parent guard")
    if value.get("role") != "DEVELOPMENT":
        raise V47FreshInterfaceError("V47 executor role is not DEVELOPMENT")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise V47FreshInterfaceError("V47 executor model/CFD boundary is not closed")
    if value.get("raw_opened") is not False or value.get("hdf5_opened") is not False:
        raise V47FreshInterfaceError("V47 metadata builder cannot accept a payload-read request")
    _unknown(value.get("qualification"), "V47 executor qualification")
    if value.get("fresh_result_required") is not True:
        raise V47FreshInterfaceError("V47 executor does not require a fresh result")

    roots = value.get("fresh_roots")
    if not isinstance(roots, Mapping):
        raise V47FreshInterfaceError("V47 fresh_roots are missing")
    target_root = _fresh_root(roots.get("target_root"), "fresh target_root")
    output_root = _fresh_root(roots.get("output_root"), "fresh output_root")
    if target_root == output_root:
        raise V47FreshInterfaceError("fresh target_root and output_root must differ")

    policy = value.get("evaluator_policy")
    if not isinstance(policy, Mapping):
        raise V47FreshInterfaceError("V47 evaluator policy is missing")
    if policy.get("independent_proof_required") is not True:
        raise V47FreshInterfaceError("V47 does not require an independent proof")
    if policy.get("old_v16_result_substitution") != "FORBIDDEN":
        raise V47FreshInterfaceError("V47 permits old V16 substitution")
    if policy.get("pending_status_without_fresh_proof") != "PENDING_FRESH_INDEPENDENT_PROOF":
        raise V47FreshInterfaceError("V47 pending proof policy differs")

    execution = value.get("execution")
    if not isinstance(execution, Mapping):
        raise V47FreshInterfaceError("V47 execution contract is missing")
    if execution.get("original_path_fallback") != "FORBIDDEN":
        raise V47FreshInterfaceError("V47 permits original path fallback")
    if execution.get("parent_owns_ledger") is not True:
        raise V47FreshInterfaceError("V47 does not bind the parent ledger owner")
    if execution.get("source_content_hash_phase") != "PARENT_AFTER_RESERVATION":
        raise V47FreshInterfaceError("V47 source hash phase is not parent-after-reservation")
    if execution.get("old_proof_input") is not None or execution.get("old_evaluator_output_reuse") != "FORBIDDEN":
        raise V47FreshInterfaceError("V47 old proof/evaluator input is not closed")
    if execution.get("evaluator_proof_input") is not None:
        raise V47FreshInterfaceError("V47 evaluator proof input must be empty before production")
    raw_tree = execution.get("raw_tree_binding")
    if not isinstance(raw_tree, Mapping):
        raise V47FreshInterfaceError("V47 raw tree binding is missing")
    if (raw_tree.get("file_count") != RAW_TREE_FILES
            or raw_tree.get("frame_count") != RAW_TREE_FRAMES
            or raw_tree.get("tree_sha256") != RAW_TREE_SHA):
        raise V47FreshInterfaceError("V47 frozen raw tree binding differs")
    forward = value.get("forward_v41")
    if not isinstance(forward, Mapping):
        raise V47FreshInterfaceError("V47 V41 forward metadata is missing")
    if forward.get("old_f208_sha_reuse") != "FORBIDDEN":
        raise V47FreshInterfaceError("V47 permits historical V16 reuse")
    if forward.get("actual_typed_h5_sha") != "MUST_BE_COMPUTED_BY_THIS_ATTEMPT":
        raise V47FreshInterfaceError("V47 typed H5 is already claimed by an old result")
    if forward.get("actual_converted_metadata_sha") != "MUST_BE_COMPUTED_BY_THIS_ATTEMPT":
        raise V47FreshInterfaceError("V47 converter metadata is already claimed by an old result")

    source = _source_summary(value)
    runtime_roles = _runtime_role_names(value)
    return {
        "binding": _canonical_file_binding(path, value, "V47 executor request"),
        "request_id": value.get("request_id"),
        "family_id": value.get("family_id"),
        "case_id_scope": "V47 executor request only; historical case names are not product identity",
        "fresh_roots": {"target_root": str(target_root), "output_root": str(output_root)},
        "source_entries": source,
        "runtime_sources": {"count": len(value["runtime_sources"]), "roles": runtime_roles},
        "raw_tree": {"file_count": RAW_TREE_FILES, "frame_count": RAW_TREE_FRAMES,
                      "tree_sha256": RAW_TREE_SHA},
    }


def _verify_parent(path: Path, value: Mapping[str, Any], executor_path: Path,
                   executor_binding: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema") != PARENT_SCHEMA:
        raise V47FreshInterfaceError("V47 parent schema differs")
    if value.get("sha256") != canonical_sha(value):
        raise V47FreshInterfaceError("V47 parent canonical SHA differs")
    if value.get("status") != "READY_FOR_PARENT_GUARD":
        raise V47FreshInterfaceError("V47 parent is not ready for its guard")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise V47FreshInterfaceError("V47 parent model/CFD boundary is not closed")
    if value.get("raw_opened") is not False or value.get("hdf5_opened") is not False:
        raise V47FreshInterfaceError("V47 parent claims payload access before its guard")
    _unknown(value.get("qualification"), "V47 parent qualification")
    executor = value.get("executor_request")
    if not isinstance(executor, Mapping):
        raise V47FreshInterfaceError("V47 parent executor binding is missing")
    if executor.get("path") != str(executor_path):
        raise V47FreshInterfaceError("V47 parent does not bind the supplied executor request")
    if executor.get("sha256") != executor_binding["physical_sha256"]:
        raise V47FreshInterfaceError("V47 parent executor physical SHA differs")
    resource = value.get("parent_resource_binding")
    if not isinstance(resource, Mapping) or resource.get("same_parent_ledger") is not True:
        raise V47FreshInterfaceError("V47 parent ledger binding is missing")
    if resource.get("allow_missing_parent") is not True or resource.get("ledger_reset") is not False:
        raise V47FreshInterfaceError("V47 parent fallback/reset policy differs")
    execution = value.get("execution")
    if not isinstance(execution, Mapping) or execution.get("reservation_order") != "same-parent ledger reservation before source content SHA":
        raise V47FreshInterfaceError("V47 parent reservation order differs")
    rows = value.get("static_bindings")
    if not isinstance(rows, list) or len(rows) < 17:
        raise V47FreshInterfaceError("V47 parent static closure is incomplete")
    roles = {row.get("role") for row in rows if isinstance(row, Mapping)}
    required = {"parent_executor_v3", "shared_v21_accounting", "shared_runtime_v6"}
    if not required.issubset(roles):
        raise V47FreshInterfaceError("V47 parent static closure misses required parent roles")
    return {
        "binding": _canonical_file_binding(path, value, "V47 parent request"),
        "attempt_id": value.get("parent_resource_binding", {}).get("attempt_id"),
        "charge_id": value.get("parent_resource_binding", {}).get("charge_id"),
        "ledger_path": value.get("parent_resource_binding", {}).get("ledger_path"),
        "static_binding_count": len(rows),
        "static_binding_roles": sorted(str(role) for role in roles if role),
        "same_parent_ledger": True,
        "allow_missing_parent": True,
    }


def _verify_root_metadata(path: Path, value: Mapping[str, Any], *, executor_path: Path,
                          parent_path: Path, executor_binding: Mapping[str, Any],
                          parent_binding: Mapping[str, Any], roots: Mapping[str, str]) -> dict[str, Any]:
    if value.get("schema") != VERIFICATION_SCHEMA:
        raise V47FreshInterfaceError("V47 root metadata verification schema differs")
    if value.get("status") != "REAL_V34_V41_PARENT_V3_METADATA_READY_NO_PAYLOAD_READ":
        raise V47FreshInterfaceError("V47 root metadata is not the no-payload verification")
    if value.get("request") != str(parent_path):
        raise V47FreshInterfaceError("V47 root verification parent path differs")
    if value.get("request_file_sha256") != parent_binding["binding"]["physical_sha256"]:
        raise V47FreshInterfaceError("V47 root verification parent SHA differs")
    if value.get("canonical_sha256") != parent_binding["binding"]["canonical_sha256"]:
        raise V47FreshInterfaceError("V47 root verification parent canonical SHA differs")
    if value.get("executor") != str(executor_path):
        raise V47FreshInterfaceError("V47 root verification executor path differs")
    if value.get("executor_file_sha256") != executor_binding["binding"]["physical_sha256"]:
        raise V47FreshInterfaceError("V47 root verification executor SHA differs")
    if value.get("v34_load_pass") is not True or value.get("v41_validate_pass") is not True:
        raise V47FreshInterfaceError("V47 root did not pass V34/V41 metadata validation")
    if value.get("parent_v3_full_static_content_pass") is not True:
        raise V47FreshInterfaceError("V47 root did not pass parent V3 static validation")
    if value.get("payload_read_or_hash_by_root") is not False:
        raise V47FreshInterfaceError("V47 root metadata verification claims payload access")
    if value.get("execution") != "NOT_YET_RUN":
        raise V47FreshInterfaceError("V47 root metadata record is no longer a pre-run record")
    if value.get("fresh_namespace") != str(Path(roots["target_root"]).parent):
        raise V47FreshInterfaceError("V47 fresh namespace differs from executor roots")
    if value.get("new_fresh_proof_and_evaluator") != "REQUIRED; OLD_ROOT060_NOT_ALLOWED":
        raise V47FreshInterfaceError("V47 fresh proof/evaluator requirement differs")
    _unknown(value.get("qualification"), "V47 root verification qualification")
    return {"binding": _verification_file_binding(path, value),
            "status": value["status"], "payload_read": False}


def _deferred_artifact(output_root: Path, relative: str, role: str,
                       phase: str) -> dict[str, Any]:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise V47FreshInterfaceError(f"unsafe expected artifact path for {role}")
    return {
        "role": role,
        "path": str(output_root / relative_path),
        "relative_path": relative,
        "sha256": None,
        "bytes": None,
        "stat": None,
        "content_sha256_deferred": True,
        "verification_phase": phase,
        "required": True,
    }


def _artifact_contract(output_root: Path) -> dict[str, Any]:
    phase = "AFTER_V47_PARENT_RESERVATION_AND_PRODUCER_TERMINAL"
    return {
        "sealed_overlay": _deferred_artifact(output_root, "sealed-overlay-v34.json", "sealed_overlay", phase),
        "private_runtime_audit": _deferred_artifact(output_root, "private-runtime-audit-v34.json", "private_runtime_audit", phase),
        "raw_converter_report": _deferred_artifact(output_root, "native-raw-to-label-v34/raw-converter-report-v2.json", "raw_converter_report", phase),
        "worker_report": _deferred_artifact(output_root, "native-raw-to-label-v34/raw-to-typed-to-label-report-v2.json", "worker_report", phase),
        "typed_hdf5": _deferred_artifact(output_root, "native-raw-to-label-v34/typed-reconstructed-v2.h5", "typed_hdf5", phase),
        "v15_label_result": _deferred_artifact(output_root, "native-raw-to-label-v34/v15-reconstructed-label-result-v2.json", "v15_label_result", phase),
        "v16_label_result": _deferred_artifact(output_root, "native-raw-to-label-v34/v16-reconstructed-label-result-v2.json", "v16_label_result", phase),
        "v40_current_view": _deferred_artifact(output_root, "v40-relocated-runtime/CURRENT336-case78-v40-runtime-view.json", "v40_current_view", phase),
        "v40_relocated_v15": _deferred_artifact(output_root, "v40-relocated-runtime/f2-s1-replay-request-v15-v40-relocated.json", "v40_relocated_v15", phase),
        "v40_source_contract": _deferred_artifact(output_root, "v40-relocated-runtime/f2-s1-fresh-v16-source-contract-v40-runtime.json", "v40_source_contract", phase),
        "v40_engine_report": _deferred_artifact(output_root, "v40-engine-integration-report.json", "v40_engine_report", phase),
        "fresh_semantic_proof": _deferred_artifact(output_root, "fresh-v16-semantic-proof-v8.json", "fresh_semantic_proof", "AFTER_FRESH_V16_RESULT_AND_V10_SEMANTIC_VALIDATION"),
        "evaluator_request": _deferred_artifact(output_root, "evaluator-v4-v40-relocated-request.json", "evaluator_request", "AFTER_FRESH_SEMANTIC_PROOF"),
        "evaluator_report": _deferred_artifact(output_root, "no-model-evaluator-v40.json", "evaluator_report", "AFTER_FRESH_SEMANTIC_PROOF_AND_PARENT_GUARD"),
    }


def _input_ref(binding: Mapping[str, Any], role: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": binding["path"],
        "physical_sha256": binding["physical_sha256"],
        "canonical_sha256": binding["canonical_sha256"],
        "bytes": binding["bytes"],
        "mtime_ns": binding["mtime_ns"],
        "mode_bits": binding["mode_bits"],
        "content_read_during_build": True,
    }


def build_pending_interfaces(*, v47_executor_request: Path | str,
                             v47_parent_request: Path | str,
                             metadata_verification: Path | str,
                             proof_staging_output: Path | str,
                             evaluator_staging_output: Path | str) -> dict[str, Any]:
    """Create immutable pending proof/evaluator descriptors from V47 metadata."""
    executor_path, executor = _metadata_json(v47_executor_request, "V47 executor request")
    parent_path, parent = _metadata_json(v47_parent_request, "V47 parent request")
    verification_path, verification = _metadata_json(metadata_verification, "V47 root metadata verification")
    proof_output = Path(proof_staging_output).expanduser()
    evaluator_output = Path(evaluator_staging_output).expanduser()
    if proof_output == evaluator_output:
        raise V47FreshInterfaceError("proof and evaluator staging outputs must differ")
    if proof_output.exists() or evaluator_output.exists():
        raise V47FreshInterfaceError("refusing existing proof/evaluator staging output")

    executor_summary = _verify_executor(executor_path, executor)
    parent_summary = _verify_parent(parent_path, parent, executor_path,
                                    executor_summary["binding"])
    roots = executor_summary["fresh_roots"]
    verification_summary = _verify_root_metadata(
        verification_path, verification, executor_path=executor_path,
        parent_path=parent_path, executor_binding=executor_summary,
        parent_binding=parent_summary, roots=roots)
    output_root = Path(roots["output_root"])
    artifacts = _artifact_contract(output_root)
    proof_product = artifacts["fresh_semantic_proof"]
    result_product = artifacts["v16_label_result"]

    source_identity = {
        "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
        "current_identity_scope": "exact CURRENT336 source identity; no qualification credit",
        "relocated_runtime_view_sha256": None,
        "relocated_runtime_view_sha_phase": "MUST_BE_COMPUTED_BY_THIS_V47_ATTEMPT",
        "historical_overlay_as_runtime_input": "FORBIDDEN",
        "raw_tree": dict(executor_summary["raw_tree"]),
    }
    input_refs = {
        "executor_request": _input_ref(executor_summary["binding"], "v47_executor_request"),
        "parent_request": _input_ref(parent_summary["binding"], "v47_parent_request"),
        "root_metadata_verification": _input_ref(verification_summary["binding"], "v47_root_metadata_verification"),
    }
    common = {
        "role": "DEVELOPMENT",
        "producer_attempt": {
            "request_id": executor_summary["request_id"],
            "parent_attempt_id": parent_summary["attempt_id"],
            "fresh_roots": dict(roots),
            "same_parent_ledger": True,
            "new_ledger_owner": False,
        },
        "input_bindings": input_refs,
        "source_identity": source_identity,
        "expected_products": artifacts,
        "product_sha_policy": {
            "all_product_sha256_must_start_null": True,
            "deferred_marker": "content_sha256_deferred=true",
            "producer_must_compute_after_reservation": True,
            "producer_must_reject_stale_existing_artifacts": True,
            "old_root060_result_or_proof_reuse": "FORBIDDEN",
            "historical_provenance_is_not_a_product_binding": True,
        },
        "execution_boundary": {
            "metadata_builder_payload_read": False,
            "hdf5_bi4_raw_read": False,
            "model_invoked": False,
            "cfd_invoked": False,
            "original_path_fallback": "FORBIDDEN",
            "parent_guard_required_before_product_sha": True,
        },
        "qualification": dict(UNKNOWN),
    }
    proof_request = {
        "schema": PROOF_STAGING_SCHEMA,
        "builder": {"schema": BUILDER_SCHEMA, "path": str(SCRIPT), "sha256": sha256_file(SCRIPT)},
        "status": "PENDING_V47_PRODUCER_RESULT",
        **common,
        "fresh_proof_contract": {
            "required_proof_schema": "ds02.stage2.f2-fresh-v16-proof.v8",
            "required_proof_status": "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN",
            "required_result": dict(result_product),
            "required_source_contract": dict(artifacts["v40_source_contract"]),
            "required_relocated_current_view_sha256": None,
            "required_exact_current_identity_sha256": ACTUAL_CURRENT_SHA,
            "proof_must_bind_new_v16_sha": True,
            "header_only_proof_is_insufficient": True,
            "old_proof_input": None,
            "old_result_input": None,
            "qualification": dict(UNKNOWN),
        },
        "evaluator_stage": {
            "status": "DISABLED_UNTIL_NEW_V16_RESULT_AND_NEW_SEMANTIC_PROOF",
            "run_allowed": False,
            "independent_proof_required": True,
        },
    }
    proof_request["sha256"] = canonical_sha(proof_request)
    _new_json(proof_output, proof_request)

    evaluator_request = {
        "schema": EVALUATOR_STAGING_SCHEMA,
        "builder": {"schema": BUILDER_SCHEMA, "path": str(SCRIPT), "sha256": sha256_file(SCRIPT)},
        "status": "BLOCKED_PENDING_FRESH_SEMANTIC_PROOF",
        **common,
        "proof_staging_interface": {
            "path": str(proof_output),
            "physical_sha256": sha256_file(proof_output),
            "canonical_sha256": proof_request["sha256"],
            "interface_only": True,
            "must_not_be_used_as_semantic_proof": True,
        },
        "fresh_result": dict(result_product),
        "fresh_semantic_proof": dict(proof_product),
        "evaluator_contract": {
            "required_result_sha_matches_proof": True,
            "required_result_source_current_sha256": ACTUAL_CURRENT_SHA,
            "required_relocated_view_sha256": None,
            "source_catalog_must_be_rechecked_after_parent_reservation": True,
            "old_root060_result_or_proof_reuse": "FORBIDDEN",
            "model_invoked": False,
            "cfd_invoked": False,
            "evaluator_run_allowed": False,
            "pending_until": ["V47 producer terminal", "fresh V16 result SHA", "V10 semantic proof SHA"],
        },
        "qualification": dict(UNKNOWN),
    }
    evaluator_request["sha256"] = canonical_sha(evaluator_request)
    _new_json(evaluator_output, evaluator_request)
    return {
        "schema": BUILDER_SCHEMA,
        "status": "PENDING_V47_PRODUCER_RESULT",
        "proof_staging_request": str(proof_output),
        "proof_staging_physical_sha256": sha256_file(proof_output),
        "evaluator_staging_request": str(evaluator_output),
        "evaluator_staging_physical_sha256": sha256_file(evaluator_output),
        "fresh_output_root": roots["output_root"],
        "all_product_sha256_deferred": True,
        "producer_payload_read_by_builder": False,
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prepare", nargs="?")
    parser.add_argument("--v47-executor-request", type=Path, required=True)
    parser.add_argument("--v47-parent-request", type=Path, required=True)
    parser.add_argument("--metadata-verification", type=Path, required=True)
    parser.add_argument("--proof-staging-output", type=Path, required=True)
    parser.add_argument("--evaluator-staging-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_pending_interfaces(
            v47_executor_request=args.v47_executor_request,
            v47_parent_request=args.v47_parent_request,
            metadata_verification=args.metadata_verification,
            proof_staging_output=args.proof_staging_output,
            evaluator_staging_output=args.evaluator_staging_output,
        )
    except (V47FreshInterfaceError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V47 fresh product interface: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
