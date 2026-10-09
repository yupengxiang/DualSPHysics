#!/usr/bin/env python3
"""Audit the portable dependency boundary for the consumed F2 typed product.

This is a metadata-only manifest builder for the ROOT179C -> ROOT200 ->
ROOT191 V4 development product.  It binds the actual producer/evidence
requests, proof, receipts, report and frozen V15 source, then records the
runtime import closure with logical target-relative names.  Large deferred
result/HDF5/native files are stat'ed and bound to already-attested SHA values;
their content is never opened by this tool.

The manifest keeps original absolute paths as provenance.  An actionable
consumer must use the target-relative path map and must fail if an original
path remains in an executable field.  The project venv is an explicit shared
environment exception: this manifest does not claim a standalone Python
environment.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence


MAIN_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SCRIPT_ROOT = MAIN_ROOT / "lagrangian-fluid-lab/scripts"
STAGE2 = MAIN_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
MAX_METADATA_BYTES = 32 * 1024 * 1024
MANIFEST_SCHEMA = "ds02.stage2.f2-typed-only-portable-dependency-manifest.v1"
FULL_STAT_FIELDS = ("bytes", "mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino")

ROOT179C_REQUEST = STAGE2 / "requests/f2-s1-root145-v66-root179c-primary-prepared-003.json"
ROOT179C_DIR = DATA_ROOT / "families/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/f2-s1-v66-root179c-003"
ROOT179C_PARENT_REPORT = ROOT179C_DIR / "actual-returned-parent-report.json"
ROOT179C_RECEIPT = ROOT179C_DIR / "execution-receipt.json"
ROOT179C_PROOF = STAGE2 / "checkpoints/F2_ROOT179C_V66_ACTUAL_CONVERSION_LABEL_INTERFACE_ROOT_VERIFICATION.json"

ROOT200_INNER = STAGE2 / (
    "requests/f2-root200-profile-output-fresh-proof-root-prepared-200-001/"
    "root200-profile-proof-request.json"
)
ROOT200_OUTER = STAGE2 / "requests/f2-root200-profile-output-fresh-proof-root-forward-200-001.json"
ROOT200_DIR = DATA_ROOT / "families/F2/STAGE2_F2_ROOT200_V14_PROFILE_OUTPUT_ROOT_20261009/f2-s1-root200-v14-profile-output-001-root-forward-030-001"
ROOT200_RECEIPT = ROOT200_DIR / "execution-receipt.json"
ROOT200_PROOF = ROOT200_DIR / "fresh-v16-proof-v12.json"
ROOT200_CHECKPOINT = STAGE2 / "checkpoints/F2_FRESH_V16_PROFILE_OUTPUT_ROOT_PROOF_V12_ACTUAL_ROOT_VERIFICATION_200.json"

ROOT191_INNER = STAGE2 / "requests/f2-root191-v4-root-prepared-191-002/root191-v3-v4-inner-stat-bound-request.json"
ROOT191_OUTER = STAGE2 / "requests/f2-typed-only-no-model-evaluator-v4-root-forward-191-001.json"
ROOT191_DIR = DATA_ROOT / "families/F2/STAGE2_F2_ROOT191_V3_V4_TYPED_ONLY_20261009/f2-s1-root191-v3-v4-typed-only-root200-001-root-forward-030-001"
ROOT191_RECEIPT = ROOT191_DIR / "execution-receipt.json"
ROOT191_REPORT = ROOT191_DIR / "typed-only-no-model-evaluator-v4.json"
ROOT191_CHECKPOINT = STAGE2 / "checkpoints/F2_TYPED_ONLY_NO_MODEL_EVALUATOR_V4_ACTUAL_ROOT_VERIFICATION_191.json"

FROZEN_V15 = STAGE2 / "replay/v15/f2-s1-replay-request-v15-001.json"
CURRENT336 = STAGE2 / "CURRENT336.json"
CURRENT336_PROVENANCE = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"

RESULT_PATH = Path("/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/products/v16-reconstructed-label-result-v2.json")
RESULT_SHA = "69d2ea956b86013135c2418a8b3bc9fc2983b8395cb5a62a243d997bb3d914a5"
RESULT_BYTES = 62365973
TYPED_H5_PATH = Path("/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT145_V66_RECOVERY_ROOT_179C_20261009/products/typed-reconstructed-v2.h5")
TYPED_H5_SHA = "2a2ef5cf5c0e1f164018466fa4815a4465ab72dbf1071bf60e76c33657288664"
TYPED_H5_BYTES = 1191110528
TRAJECTORY_H5_PATH = DATA_ROOT / "families/F2/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010/root-stage1-f2-f2_stage1_first48_expansion_rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual812-full401-typed157-home4gib-source140-root1013/trajectory.h5"
TRAJECTORY_H5_SHA = "f882a38dca872cbe81523b0691ea10ff6cc122037917b5d0a3004337eb6a8e9d"

LITERAL_VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PYVENV_CFG = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/pyvenv.cfg")

CODE_ROLES = (
    ("root191_v4_entrypoint", "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v4.py", "executed"),
    ("root191_v3_entrypoint", "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v3.py", "imported"),
    ("root191_v2_binding", "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v2.py", "imported"),
    ("root191_v1_binding", "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v1.py", "imported"),
    ("fresh_v16_proof_consumer_v8", "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py", "imported"),
    ("fresh_v16_proof_consumer_v12", "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py", "imported"),
    ("fresh_v16_proof_request_v66_contract", "ds_data02_stage2_f2_fresh_v16_proof_request_v66.py", "source_contract"),
    ("typed_only_evaluator_v1", "ds_data02_stage2_f2_typed_only_evaluator_v1.py", "imported"),
    ("no_model_evaluator_v3", "ds_data02_stage2_f2_no_model_evaluator_v3.py", "transitive_import"),
    ("no_model_evaluator_v2", "ds_data02_stage2_f2_no_model_evaluator_v2.py", "transitive_import"),
    ("v16_operator_source_contract", "ds_data02_stage2_f2_flux_v16.py", "source_contract"),
    ("raw_converter_source_contract", "ds_data02_f5_bi4.py", "source_contract"),
    ("raw_reconstruction_worker_source_contract", "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py", "source_contract"),
    ("replay_v14_source_contract", "ds_data02_stage2_f2_replay_v14.py", "transitive_import"),
    ("replay_v15_source_contract", "ds_data02_stage2_f2_replay_v15.py", "transitive_import"),
    ("root191_primary_builder", "ds_data02_stage2_f2_root191_v3_primary_builder.py", "build_only"),
    ("shared_runtime_v8_parent_guard", "ds_data02_runtime_v8.py", "parent_guard_dependency"),
)

SMALL_EVIDENCE = (
    ("root179c_request", ROOT179C_REQUEST, "evidence/root179c/f2-s1-root145-v66-root179c-primary-prepared-003.json"),
    ("root179c_parent_report", ROOT179C_PARENT_REPORT, "evidence/root179c/actual-returned-parent-report.json"),
    ("root179c_receipt", ROOT179C_RECEIPT, "evidence/root179c/execution-receipt.json"),
    ("root179c_root_proof", ROOT179C_PROOF, "evidence/root179c/root-proof.json"),
    ("root200_inner_request", ROOT200_INNER, "evidence/root200/root200-inner-request.json"),
    ("root200_outer_request", ROOT200_OUTER, "evidence/root200/root200-outer-request.json"),
    ("root200_receipt", ROOT200_RECEIPT, "evidence/root200/execution-receipt.json"),
    ("root200_fresh_v12_proof", ROOT200_PROOF, "evidence/root200/fresh-v16-proof-v12.json"),
    ("root200_checkpoint", ROOT200_CHECKPOINT, "evidence/root200/root-verification-checkpoint.json"),
    ("root191_inner_request", ROOT191_INNER, "evidence/root191/root191-v4-inner-request.json"),
    ("root191_outer_request", ROOT191_OUTER, "evidence/root191/root191-v4-outer-request.json"),
    ("root191_receipt", ROOT191_RECEIPT, "evidence/root191/execution-receipt.json"),
    ("root191_operator_report", ROOT191_REPORT, "evidence/root191/typed-only-no-model-evaluator-v4.json"),
    ("root191_checkpoint", ROOT191_CHECKPOINT, "evidence/root191/root-verification-checkpoint.json"),
    ("frozen_v15_request", FROZEN_V15, "evidence/frozen-v15/f2-s1-replay-request-v15-001.json"),
    ("current336_actionable_metadata", CURRENT336, "evidence/current/CURRENT336.json"),
    ("current336_provenance_alias", CURRENT336_PROVENANCE, "provenance/current/CURRENT336-catalog-003.json"),
)


class ManifestError(RuntimeError):
    """A missing or unsafe portable dependency binding."""


def _stat(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        raise ManifestError(f"expected regular non-symlink file: {path}")
    info = path.stat()
    return {"bytes": int(info.st_size), "mode_bits": int(info.st_mode & 0o7777),
            "mtime_ns": int(info.st_mtime_ns), "ctime_ns": int(info.st_ctime_ns),
            "st_dev": int(info.st_dev), "st_ino": int(info.st_ino)}


def _sha(path: Path, *, limit: int = MAX_METADATA_BYTES) -> str:
    if path.stat().st_size > limit:
        raise ManifestError(f"content hash exceeds metadata limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, role: str) -> dict[str, Any]:
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise ManifestError(f"{role} exceeds bounded metadata size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ManifestError(f"{role} must be a JSON object")
    return value


def _record(path: Path, role: str, target: str, *, kind: str, actionable: bool,
            known_sha: str | None = None, known_bytes: int | None = None,
            content_read: bool | None = None) -> dict[str, Any]:
    stat = _stat(path)
    if known_bytes is not None and stat["bytes"] != int(known_bytes):
        raise ManifestError(f"{role} size differs from bound metadata")
    if content_read is None:
        content_read = known_sha is None and stat["bytes"] <= MAX_METADATA_BYTES
    if content_read:
        digest = _sha(path)
        if known_sha is not None and digest != known_sha:
            raise ManifestError(f"{role} content SHA differs")
        sha_source = "manifest_read_bounded"
    else:
        if known_sha is None:
            raise ManifestError(f"{role} needs an attested SHA when content is deferred")
        digest = known_sha
        sha_source = "producer_attested_known_sha"
    if target.startswith("/") or ".." in Path(target).parts:
        raise ManifestError(f"{role} target path is not a safe relative path")
    return {
        "logical_role": role,
        "source_path_provenance": str(path),
        "source_sha256": digest,
        "source_sha256_basis": sha_source,
        "source_stat_provenance": stat,
        "source_stat_is_target_claim": False,
        "target_relative_path": target,
        "actionable": actionable,
        "source_kind": kind,
        "content_read_by_manifest": bool(content_read),
    }


def _imports(path: Path) -> dict[str, Any]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise ManifestError(f"cannot inspect source imports: {path}: {error}") from error
    imported: set[str] = set()
    sibling_literals: set[str] = set()
    absolute_literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if value.endswith(".py"):
                sibling_literals.add(value)
            if value.startswith(("/home/", "/var/", "/tmp/")):
                absolute_literals.add(value)
    roots = sorted({name.lstrip(".").split(".", 1)[0] for name in imported if name and not name.startswith(".")})
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__", "xml"}
    external = sorted(root for root in roots if root not in stdlib and not root.startswith("ds_data02"))
    return {"imports": sorted(imported), "import_roots": roots, "external_import_roots": external,
            "sibling_python_literals": sorted(sibling_literals),
            "absolute_path_literals": sorted(absolute_literals),
            "canonical_sibling_directory_required": True}


def _code_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    records: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    external: set[str] = set()
    for role, filename, phase in CODE_ROLES:
        path = SCRIPT_ROOT / filename
        item = _record(path, role, f"runtime/{filename}", kind="runtime_source", actionable=True,
                       content_read=True)
        item["execution_phase"] = phase
        audit = _imports(path)
        item["static_import_audit"] = audit
        external.update(audit["external_import_roots"])
        audits.append({"logical_role": role, "path": str(path), **audit})
        records.append(item)
    return records, audits, external


def _canonical_sha(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _join_evidence() -> dict[str, Any]:
    inner = _json(ROOT200_INNER, "ROOT200 inner request")
    proof = _json(ROOT200_PROOF, "ROOT200 fresh proof")
    checkpoint = _json(ROOT191_CHECKPOINT, "ROOT191 verification checkpoint")
    report = _json(ROOT191_REPORT, "ROOT191 operator report")
    result = inner.get("result")
    source_result = proof.get("source_result")
    if not isinstance(result, Mapping) or not isinstance(source_result, Mapping):
        raise ManifestError("ROOT200 result/source-result binding is missing")
    for field in ("path", "sha256", "bytes"):
        if result.get(field) != source_result.get(field):
            raise ManifestError(f"ROOT200 proof differs for result {field}")
    if result.get("sha256") != RESULT_SHA or int(result.get("bytes")) != RESULT_BYTES:
        raise ManifestError("ROOT200 result is not the known ROOT179C typed product")
    if checkpoint.get("report") != str(ROOT191_REPORT):
        raise ManifestError("ROOT191 checkpoint report path differs")
    if checkpoint.get("report_sha256") != _sha(ROOT191_REPORT):
        raise ManifestError("ROOT191 report SHA differs from checkpoint")
    summary = checkpoint.get("validated_result_summary")
    if not isinstance(summary, Mapping) or summary.get("result_sha256") != RESULT_SHA:
        raise ManifestError("ROOT191 validated result summary differs")
    source_binding = summary.get("source_binding")
    if not isinstance(source_binding, Mapping) or source_binding.get("current_catalog_sha256") != "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b":
        raise ManifestError("ROOT191 CURRENT source identity is not df7e")
    if report.get("source_result", report.get("result_source", {})).get("sha256") not in (None, RESULT_SHA):
        raise ManifestError("ROOT191 report result SHA differs")
    return {
        "root200_result": {"path": result["path"], "sha256": result["sha256"], "bytes": result["bytes"],
                           "proof_source_stat": source_result.get("stat")},
        "root191_report": {"path": str(ROOT191_REPORT), "sha256": _sha(ROOT191_REPORT),
                            "result_sha256": RESULT_SHA, "current_catalog_sha256": source_binding["current_catalog_sha256"]},
        "root191_status": checkpoint.get("status"),
        "root191_quality": checkpoint.get("quality", checkpoint.get("qualification", {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})),
        "cold_or_qualification_credit": "NOT_CLAIMED",
    }


def build_manifest(*, output: Path) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise ManifestError(f"refusing to overwrite manifest: {output}")
    join = _join_evidence()
    artifacts: list[dict[str, Any]] = []
    for role, path, target in SMALL_EVIDENCE:
        artifacts.append(_record(path, role, target, kind="bounded_evidence", actionable=True))
    artifacts.append(_record(RESULT_PATH, "root179c_typed_result_deferred", "products/v16-reconstructed-label-result-v2.json",
                             kind="deferred_result_json", actionable=True, known_sha=RESULT_SHA,
                             known_bytes=RESULT_BYTES, content_read=False))
    artifacts.append(_record(TYPED_H5_PATH, "root179c_typed_h5_deferred", "products/typed-reconstructed-v2.h5",
                             kind="deferred_typed_h5", actionable=True, known_sha=TYPED_H5_SHA,
                             known_bytes=TYPED_H5_BYTES, content_read=False))
    artifacts.append(_record(TRAJECTORY_H5_PATH, "current_trajectory_h5_provenance", "provenance/source/trajectory.h5",
                             kind="source_provenance_deferred_h5", actionable=False, known_sha=TRAJECTORY_H5_SHA,
                             content_read=False))
    code, code_audit, external = _code_records()
    artifacts.extend(code)
    venv_target = Path(__import__("os").path.realpath(LITERAL_VENV))
    artifacts.append(_record(PYVENV_CFG, "pinned_project_pyvenv_cfg", "environment/pyvenv.cfg",
                             kind="external_environment", actionable=False, content_read=True))
    artifacts.append({
        "logical_role": "literal_project_venv_python",
        "source_path_provenance": str(LITERAL_VENV),
        "source_sha256": _sha(venv_target),
        "source_sha256_basis": "pinned_resolved_binary_provenance",
        "source_stat_provenance": _stat(venv_target),
        "source_stat_is_target_claim": False,
        "target_relative_path": "environment/.venv/bin/python",
        "actionable": False,
        "source_kind": "external_environment_exception",
        "content_read_by_manifest": True,
        "invocation_path_is_literal": True,
        "resolved_path_provenance": str(venv_target),
        "standalone_environment_claim": False,
    })
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "status": "PORTABLE_TYPED_ONLY_DEPENDENCY_AUDIT_METADATA_COMPLETE",
        "product_scope": {
            "family": "F2", "case": "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_SPATIAL_REFERENCE_SAVE010",
            "mode": "development_typed_only_no_model_operator_product",
            "raw_to_typed_credit": "NOT_CLAIMED", "cold_replay_credit": "NOT_CLAIMED",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "evidence_join": join,
        "artifacts": artifacts,
        "runtime_import_closure": {
            "runtime_target_root": "runtime",
            "canonical_sibling_basename_required": True,
            "code_audit": code_audit,
            "external_import_roots": sorted(external),
            "abi_scope": "literal shared project venv plus pyvenv.cfg; not a standalone relocatable Python environment",
            "original_worktree_fallback": "FORBIDDEN",
            "bootstrap_requirement": "run literal environment interpreter with explicit copied runtime sibling directory; never resolve argv0 to system Python and never use original PYTHONPATH",
        },
        "portable_loading_entry": {
            "schema": "ds02.stage2.f2-typed-only-portable-loading-entry.v1",
            "entrypoint_logical_role": "root191_v4_entrypoint",
            "entrypoint_target_relative_path": "runtime/ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v4.py",
            "request_target_relative_path": "evidence/root191/root191-v4-inner-request.json",
            "frozen_v15_target_relative_path": "evidence/frozen-v15/f2-s1-replay-request-v15-001.json",
            "current_target_relative_path": "evidence/current/CURRENT336.json",
            "result_target_relative_path": "products/v16-reconstructed-label-result-v2.json",
            "typed_h5_target_relative_path": "products/typed-reconstructed-v2.h5",
            "fresh_proof_target_relative_path": "evidence/root200/fresh-v16-proof-v12.json",
            "operator_report_target_relative_path": "evidence/root191/typed-only-no-model-evaluator-v4.json",
            "runtime_sibling_directory": "runtime",
            "argv0_policy": "literal_shared_venv_only",
            "argv0_provenance": str(LITERAL_VENV),
            "argv0_resolved_provenance": str(venv_target),
            "standalone_python_claim": False,
            "source_fallback": "REJECT",
            "old_absolute_paths": "provenance_only",
            "payload_read_phase": "parent_after_reservation_pre_post_stat_and_SHA_gate",
            "no_model": True,
            "model_invoked": False,
            "cold_or_qualification_credit": "NOT_CLAIMED",
        },
        "path_policy": {
            "provenance_paths_are_not_actionable": True,
            "actionable_inputs_must_use_target_relative_path": True,
            "original_absolute_path_fallback": "REJECT",
            "source_stat_and_inode": "provenance_only; no copied target inode/mtime equivalence is claimed",
            "deferred_payloads": ["root179c_typed_result_deferred", "root179c_typed_h5_deferred", "current_trajectory_h5_provenance"],
        },
        "identified_portability_gaps": [
            {"id": "G1_RESULT_REBIND", "severity": "required", "description": "ROOT191/V4 request points at the original deferred V16 result path; a relocated consumer must rebind products/v16-reconstructed-label-result-v2.json while preserving original path as provenance."},
            {"id": "G2_V15_REBIND", "severity": "required", "description": "The V4 scorer loads frozen V15 through an absolute source path; copy it under evidence/frozen-v15 and rewrite only the actionable request path."},
            {"id": "G3_CANONICAL_SIBLING_NAMES", "severity": "required", "description": "V1/V2/V3/V4, V8/V12 and no-model/replay imports use sibling basenames; renaming copied modules or flattening directories breaks the dynamic import closure."},
            {"id": "G4_EXTERNAL_ABI", "severity": "bounded", "description": "numpy/h5py are imported by the transitive replay modules; the manifest binds the literal shared venv and pyvenv.cfg but does not claim a standalone environment. An isolated ABI smoke is required after parent reservation."},
            {"id": "G5_CURRENT_ALIAS", "severity": "required", "description": "CURRENT df7e is source identity while the original catalog path is provenance; relocated requests must bind a copied CURRENT target and preserve the df7e SHA without copying source inode/mtime claims."},
            {"id": "G6_DEFERRED_CONTENT", "severity": "required", "description": "Result/H5/native contents were not read by this audit; parent-after-reservation pre/post SHA/stat validation remains a separate gate."},
        ],
        "offline_fixture_contract": {
            "schema": "ds02.stage2.f2-typed-only-portable-offline-fixture.v1",
            "manufactured_inputs": "small JSON/code files only",
            "must_pass": ["target-relative runtime imports", "literal venv exception", "provenance path retained separately"],
            "must_fail": ["actionable original absolute path", "renamed sibling module", "source inode/mtime treated as copied target identity"],
            "payload_read": False,
        },
        "content_read_by_manifest": False,
        "large_payload_content_read": False,
    }
    manifest["sha256"] = _canonical_sha(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")
    return manifest


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_manifest(path: Path, *, relocated_root: Path | None = None) -> dict[str, Any]:
    manifest = _json(path, "portable dependency manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ManifestError("manifest schema differs")
    if manifest.get("sha256") != _canonical_sha(manifest):
        raise ManifestError("manifest canonical SHA differs")
    missing_targets: list[str] = []
    checked = 0
    for item in manifest.get("artifacts", []):
        if not isinstance(item, Mapping):
            raise ManifestError("malformed artifact entry")
        source = Path(str(item.get("source_path_provenance"))).expanduser()
        environment_exception = item.get("source_kind") == "external_environment_exception"
        if environment_exception:
            if not source.is_file():
                raise ManifestError(f"pinned environment source disappeared: {source}")
            stat_source = Path(os.path.realpath(source))
        else:
            if not source.is_file() or source.is_symlink():
                raise ManifestError(f"source provenance disappeared: {source}")
            stat_source = source
        expected_stat = item.get("source_stat_provenance")
        if expected_stat != _stat(stat_source):
            raise ManifestError(f"source provenance stat changed: {source}")
        if item.get("content_read_by_manifest"):
            if _sha(stat_source) != item.get("source_sha256"):
                raise ManifestError(f"small source SHA changed: {source}")
        elif item.get("source_sha256") is None:
            raise ManifestError(f"deferred source has no attested SHA: {source}")
        target_rel = Path(str(item.get("target_relative_path")))
        if target_rel.is_absolute() or ".." in target_rel.parts:
            raise ManifestError(f"unsafe target-relative path: {target_rel}")
        if relocated_root is not None and item.get("actionable"):
            target = relocated_root / target_rel
            if target.exists():
                if not _inside(target, relocated_root):
                    raise ManifestError(f"target escapes relocated root: {target}")
            else:
                missing_targets.append(str(target))
        checked += 1
    return {"schema": MANIFEST_SCHEMA, "status": "PORTABLE_DEPENDENCY_MANIFEST_VALIDATED",
            "manifest": str(path), "sha256": manifest["sha256"], "artifact_count": checked, "missing_relocated_targets": missing_targets,
            "payload_read": False, "large_payload_content_read": False}


def validate_actionable_mapping(mapping: Mapping[str, Any], *, original_roots: Iterable[str]) -> None:
    """Reject original absolute paths in actionable fields for small fixtures.

    ``provenance`` subtrees are intentionally ignored.  This helper is used
    only for the metadata fixture and is not a scientific result validator.
    """
    roots = tuple(str(root) for root in original_roots)

    def walk(value: Any, field_path: str, provenance: bool = False) -> None:
        if isinstance(value, Mapping):
            next_provenance = provenance or field_path.split(".")[-1] in {"provenance", "source_path_provenance"}
            for key, child in value.items():
                walk(child, f"{field_path}.{key}" if field_path else str(key), next_provenance)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, f"{field_path}[{i}]", provenance)
        elif isinstance(value, str) and value.startswith("/") and not provenance:
            if any(value == root or value.startswith(root.rstrip("/") + "/") for root in roots):
                raise ManifestError(f"actionable original absolute path: {field_path}={value}")

    walk(mapping, "")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--relocated-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_manifest(output=args.output) if args.command == "build" else validate_manifest(
            args.manifest, relocated_root=args.relocated_root)
    except (ManifestError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"typed-only portable dependency manifest: {error}", file=sys.stderr)
        return 2
    summary = {"schema": result.get("schema"), "status": result.get("status"),
               "manifest": result.get("manifest", str(args.output) if args.command == "build" else None),
               "sha256": result.get("sha256"),
               "artifact_count": result.get("artifact_count"),
               "missing_relocated_targets": result.get("missing_relocated_targets"),
               "payload_read": result.get("payload_read")}
    if args.command == "build":
        summary["artifact_count"] = len(result.get("artifacts", []))
        summary["payload_read"] = False
    print(json.dumps(summary, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
