#!/usr/bin/env python3
"""Record the bounded external-authority gap for the F3 MLP seed43 path.

The current-manifest MLP launcher binds a local manifest, training receipt,
checkpoint, nonce, namespace, command and GPU index.  That local plan is
diagnostic-only, however: it is not a producer-issued scheduler admission and
does not carry a trusted Ed25519 authority, a one-shot consume witness, or a
scheduler-owned GPU UUID/PCI resource snapshot.

This artifact audits that boundary without adding an admission bypass.  It
reads only bounded repository source/test files and filesystem metadata for
the configured trust paths and existing report files.  It never opens the
manifest, training receipt, checkpoint, evaluation, trajectory or HDF5 data;
never verifies or fabricates an authority document; and never starts a
process, solver, worker, queue or GPU workload.  The result is a seed43-only
fail-closed gap report with zero Core credit.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 43
MODEL_KIND = "mlp"
HIDDEN = 16
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836

CURRENT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
LAUNCHER_SOURCE = LAB_ROOT / "scripts" / "f3_mlp_hidden16_current_manifest_rollout_launcher_v1.py"
TERMINAL_SOURCE = LAB_ROOT / "scripts" / "f3_mlp_hidden16_current_manifest_terminal_evidence_v1.py"
TRAINING_SOURCE = LAB_ROOT / "scripts" / "f3_mlp_hidden16_current_manifest_training_evidence_v1.py"
LAUNCHER_TEST = LAB_ROOT / "tests" / "test_f3_mlp_hidden16_current_manifest_rollout_launcher_v1.py"
CURRENT_TRAINING_REPORT = (
    LAB_ROOT / "reports" / "F3-MLP-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN1.json"
)
CURRENT_TERMINAL_REPORT = (
    LAB_ROOT / "reports" / "F3-MLP-HIDDEN16-CURRENT-MANIFEST-TERMINAL-EVIDENCE-2026-09-29-RERUN2.json"
)

# These are deployment-owned locations, not local claims.  Their metadata is
# observed only; the audit never creates them or treats their presence as
# proof of an authority signature.
TRUSTED_SCHEDULER_PUBLIC_KEY = Path("/etc/dual-sph/scheduler-ed25519-public.key")
EXTERNAL_SCHEDULER_ROOT = Path("/var/lib/dual-sph/f3-mlp-seed43-scheduler")

SCHEMA = "core.f3.mlp.hidden16.seed43.authority_projection_gap.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-mlp-hidden16-seed43-authority-projection-gap-v1"
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-MLP-HIDDEN16-SEED43-AUTHORITY-PROJECTION-GAP-2026-09-29.json"
)
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_SOURCE_BYTES = 256 * 1024
FORBIDDEN_IMPORT_ROOTS = {"subprocess", "multiprocessing", "queue"}
FORBIDDEN_CALL_NAMES = {
    "Popen",
    "run",
    "call",
    "check_call",
    "check_output",
    "system",
    "execve",
    "spawn",
}

SOURCE_PATHS = {
    "current_manifest_rollout_launcher": LAUNCHER_SOURCE,
    "current_manifest_terminal_evidence": TERMINAL_SOURCE,
    "current_manifest_training_evidence": TRAINING_SOURCE,
    "rollout_launcher_regression": LAUNCHER_TEST,
}

ZERO_CREDIT: dict[str, Any] = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "qualification_credit": 0,
    "credit": 0,
}

SIDE_EFFECTS: dict[str, Any] = {
    "source_files_read": len(SOURCE_PATHS),
    "current_manifest_bytes_opened": 0,
    "current_training_report_bytes_opened": 0,
    "current_terminal_report_bytes_opened": 0,
    "production_large_files_opened": 0,
    "gpu_probes": 0,
    "popen_attempts": 0,
    "solver_attempts": 0,
    "worker_attempts": 0,
    "queue_submissions": 0,
    "registry_writes": 0,
    "ledger_writes": 0,
    "denominator_writes": 0,
    "gate_writes": 0,
    "completion_writes": 0,
    "PLAN_writes": 0,
    "historical_receipt_writes": 0,
}


class AuditError(ValueError):
    """Malformed audit input or an unsafe audit target."""


def _fail(message: str) -> None:
    raise AuditError(f"fail-closed: {message}")


def _absolute(path: Path | str, name: str) -> Path:
    candidate = Path(os.fspath(path))
    if not candidate.is_absolute() or any(part in {".", ".."} for part in candidate.parts):
        _fail(f"{name} must be an absolute lexical path")
    if Path(os.path.normpath(str(candidate))) != candidate:
        _fail(f"{name} contains a lexical alias")
    return candidate


def _read_small(path: Path | str, *, max_bytes: int, name: str) -> bytes:
    """Read only a bounded regular repository source/test file."""

    candidate = _absolute(path, name)
    try:
        info = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot inspect {name}: {error}")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _fail(f"{name} must be a regular non-symlink file")
    if info.st_size > max_bytes:
        _fail(f"{name} exceeds the bounded audit read limit")
    try:
        with candidate.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    if len(raw) > max_bytes:
        _fail(f"{name} grew beyond the bounded audit read limit")
    return raw


def _metadata(path: Path | str, name: str) -> dict[str, Any]:
    """Collect filesystem metadata only; never opens the target."""

    candidate = _absolute(path, name)
    try:
        info = os.lstat(candidate)
    except FileNotFoundError:
        return {"path": str(candidate), "present": False}
    except OSError as error:
        return {
            "path": str(candidate),
            "present": False,
            "inspection_error": type(error).__name__,
        }
    return {
        "path": str(candidate),
        "present": True,
        "symlink": stat.S_ISLNK(info.st_mode),
        "regular_file": stat.S_ISREG(info.st_mode),
        "directory": stat.S_ISDIR(info.st_mode),
        "bytes": int(info.st_size),
        "mode": stat.S_IMODE(info.st_mode),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
    }


def _bounded_children(root: Path | str, suffix: str) -> list[dict[str, Any]]:
    """List scheduler-root child metadata without opening child contents."""

    candidate = _absolute(root, "external scheduler root")
    try:
        root_info = os.lstat(candidate)
    except (FileNotFoundError, OSError):
        return []
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        return []
    children: list[dict[str, Any]] = []
    try:
        with os.scandir(candidate) as entries:
            for entry in entries:
                if not entry.name.endswith(suffix):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                children.append(
                    {
                        "name": entry.name,
                        "path": str(candidate / entry.name),
                        "symlink": stat.S_ISLNK(info.st_mode),
                        "regular_file": stat.S_ISREG(info.st_mode),
                        "bytes": int(info.st_size),
                        "mode": stat.S_IMODE(info.st_mode),
                        "uid": int(info.st_uid),
                        "gid": int(info.st_gid),
                        "nlink": int(info.st_nlink),
                    }
                )
    except OSError:
        return []
    return sorted(children, key=lambda item: str(item["name"]))


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_observation(path: Path, *, name: str) -> tuple[str, ast.Module, dict[str, Any], str]:
    raw = _read_small(path, max_bytes=MAX_SOURCE_BYTES, name=name)
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=str(path))
    except (UnicodeDecodeError, SyntaxError) as error:
        _fail(f"{name} is not parseable UTF-8 Python: {error}")
    text = raw.decode("utf-8")
    digest = _sha(raw)
    return (
        digest,
        tree,
        {"path": str(path), "bytes": len(raw), "sha256": digest},
        text,
    )


def _function_names(tree: ast.AST) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _call_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def _marker(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def _gap(
    gap_id: str,
    title: str,
    condition: str,
    consequence: str,
    next_evidence: str,
) -> dict[str, str]:
    return {
        "id": gap_id,
        "title": title,
        "condition": condition,
        "consequence": consequence,
        "required_evidence": next_evidence,
    }


def audit(
    *,
    current_manifest: Path | str = CURRENT_MANIFEST,
    trusted_scheduler_public_key: Path | str = TRUSTED_SCHEDULER_PUBLIC_KEY,
    external_scheduler_root: Path | str = EXTERNAL_SCHEDULER_ROOT,
) -> dict[str, Any]:
    """Audit only the MLP seed43 authority/projection boundary."""

    manifest_path = _absolute(current_manifest, "current manifest")
    key_path = _absolute(trusted_scheduler_public_key, "trusted scheduler public key")
    scheduler_root = _absolute(external_scheduler_root, "external scheduler root")

    observations: dict[str, dict[str, Any]] = {}
    source_texts: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    source_digests: dict[str, str] = {}
    for key, path in SOURCE_PATHS.items():
        digest, tree, descriptor, text = _source_observation(path, name=key)
        source_digests[key] = digest
        trees[key] = tree
        observations[key] = descriptor
        source_texts[key] = text

    launcher_text = source_texts["current_manifest_rollout_launcher"]
    terminal_text = source_texts["current_manifest_terminal_evidence"]
    training_text = source_texts["current_manifest_training_evidence"]
    all_contract_text = "\n".join(source_texts.values())
    launcher_tree = trees["current_manifest_rollout_launcher"]
    imports = _import_roots(launcher_tree)
    calls = _call_names(launcher_tree)
    forbidden_imports = sorted(imports & FORBIDDEN_IMPORT_ROOTS)
    forbidden_calls = sorted(set(calls) & FORBIDDEN_CALL_NAMES)

    implementation_coverage = {
        "current_manifest_identity_binding": _marker(
            launcher_text, "manifest_sha256", "training_receipt", "checkpoint_path"
        ),
        "seed43_parameter_binding": _marker(
            launcher_text, "def build_plan", "seed: int", "run_id: str", "nonce: str"
        ),
        "local_nonce_binding": _marker(
            launcher_text, "def _validate_nonce", "namespace_nonce"
        ),
        "local_namespace_binding": _marker(
            launcher_text, "def _validate_output_namespace", "output_namespace"
        ),
        "local_source_digest_binding": _marker(
            launcher_text, "_canonical_manifest_sha", "_input_snapshot"
        ),
        "diagnostic_zero_credit_boundary": _marker(
            all_contract_text, '"diagnostic_only": True', '"credit": 0'
        ),
        "external_scheduler_authority_contract": _marker(
            all_contract_text, "external_authority", "EXTERNAL_SCHEDULER_ROOT"
        ),
        "ed25519_signature_verification": _marker(
            all_contract_text, "Ed25519PublicKey", "signature_algorithm"
        ),
        "scheduler_owned_gpu_uuid_pci_binding": _marker(
            all_contract_text, "gpu_uuid", "pci_bus_id", "scheduler_owned"
        ),
        "one_shot_external_consume_witness": _marker(
            all_contract_text, "consume_path", "one_shot", "external_claim"
        ),
        "authority_gate_before_execute": _marker(
            launcher_text, "external_authority", "--execute"
        ),
    }

    manifest_metadata = _metadata(manifest_path, "current manifest")
    key_metadata = _metadata(key_path, "trusted scheduler public key")
    scheduler_metadata = _metadata(scheduler_root, "external scheduler root")
    authority_documents = _bounded_children(scheduler_root, ".authority.json")
    claim_documents = _bounded_children(scheduler_root, ".claim.json")
    production_key_available = bool(
        key_metadata.get("present")
        and key_metadata.get("regular_file")
        and not key_metadata.get("symlink")
    )
    production_root_available = bool(
        scheduler_metadata.get("present")
        and scheduler_metadata.get("directory")
        and not scheduler_metadata.get("symlink")
    )
    authority_document_available = any(
        item.get("regular_file") and not item.get("symlink") for item in authority_documents
    )
    claim_available = any(
        item.get("regular_file") and not item.get("symlink") for item in claim_documents
    )

    gaps: list[dict[str, str]] = []
    if not production_key_available or not production_root_available:
        gaps.append(
            _gap(
                "F3-MLP43-AUTH-ROOT-001",
                "MLP seed43 scheduler trust root unavailable",
                "a deployment-owned Ed25519 public key and external scheduler root are not both present",
                "no caller-supplied authority can be authenticated as a real scheduler authority",
                "install the owner-controlled 32-byte Ed25519 public key and protected scheduler root, then provide metadata/permission evidence",
            )
        )
    if not authority_document_available:
        gaps.append(
            _gap(
                "F3-MLP43-AUTH-DOC-002",
                "signed external authority document unavailable",
                "no current-manifest MLP seed43 one-shot authority document is available under the configured root",
                "nonce, namespace inode, source/plan/resource and GPU identity bindings have no external scheduler witness",
                "obtain a scheduler-issued authority document and validate its Ed25519 signature against the deployment key",
            )
        )
    if not claim_available:
        gaps.append(
            _gap(
                "F3-MLP43-AUTH-CLAIM-003",
                "one-shot consume claim unavailable",
                "no durable scheduler consume-path claim is available",
                "the reservation cannot be shown to be unused by another consumer",
                "obtain an external claim bound to authority id, document digest, receipt identity, nonce and namespace descriptor",
            )
        )
    if not implementation_coverage["external_scheduler_authority_contract"]:
        gaps.append(
            _gap(
                "F3-MLP43-AUTH-IMPL-004",
                "current MLP launcher has no external-authority admission gate",
                "the current-manifest launcher accepts a local plan and exposes --execute without an external authority envelope",
                "a local nonce/namespace/GPU-index plan cannot authorize diagnostic execution or be promoted to Core evidence",
                "add a producer-issued, fail-closed seed43 admission boundary before any retry; do not widen the existing launcher locally",
            )
        )
    if not implementation_coverage["scheduler_owned_gpu_uuid_pci_binding"]:
        gaps.append(
            _gap(
                "F3-MLP43-AUTH-RESOURCE-005",
                "scheduler-owned GPU identity binding unavailable",
                "the MLP plan contains a local GPU index but no scheduler-owned UUID/PCI snapshot binding",
                "GPU index availability cannot prove that the reserved physical resource is the one used by the evaluator",
                "obtain a scheduler-owned resource snapshot bound by digest to the authority, nonce, namespace and command plan",
            )
        )
    gaps.append(
        _gap(
            "F3-MLP43-AUTH-VERIFY-006",
            "this gap audit does not verify production authority",
            "the audit reads only bounded source files and trust-path metadata; it does not consume or replay authority documents",
            "synthetic fixtures or present filenames cannot promote launch, terminal status or Core credit",
            "after all external evidence exists, a dedicated admission verifier must perform signature, nonce, namespace, source, resource and one-shot checks",
        )
    )

    status = "blocked_fail_closed"
    if production_key_available and production_root_available and authority_document_available and claim_available:
        status = "blocked_static_unverified"

    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": status,
        "audit_mode": "bounded_mlp_seed43_authority_projection_gap_only",
        "requested_agent_policy": {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "max",
            "parallel_scope": "f3_mlp_hidden16_seed43_authority_projection_gap_v1",
        },
        "scope": {
            "family": "F3",
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "seed": SEED,
            "case_id": CASE_ID,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "current_manifest": str(manifest_path),
            "shared_files_modified": False,
            "historical_receipts_modified": False,
        },
        "contract_sources": observations,
        "contract_source_sha256": source_digests,
        "implementation_coverage": implementation_coverage,
        "implementation_evidence": {
            "launcher_imports": sorted(imports),
            "forbidden_imports": forbidden_imports,
            "forbidden_call_names": forbidden_calls,
            "launcher_execute_surface_present": _marker(launcher_text, "--execute", "execute_plan("),
            "launcher_default_is_dry_run": _marker(launcher_text, 'mode": "dry_run"', "if args.execute"),
            "terminal_contract_zero_credit": _marker(terminal_text, '"credit"', "diagnostic"),
            "training_contract_zero_credit": _marker(training_text, '"credit"', "diagnostic"),
        },
        "production_observation": {
            "current_manifest_metadata_only": manifest_metadata,
            "current_training_report_metadata_only": {
                **_metadata(CURRENT_TRAINING_REPORT, "current MLP training report"),
                "content_opened": False,
            },
            "current_terminal_report_metadata_only": {
                **_metadata(CURRENT_TERMINAL_REPORT, "current MLP terminal report"),
                "content_opened": False,
            },
            "trusted_scheduler_public_key_metadata_only": key_metadata,
            "external_scheduler_root_metadata_only": scheduler_metadata,
            "authority_documents_metadata_only": authority_documents,
            "claim_documents_metadata_only": claim_documents,
            "production_key_available": production_key_available,
            "production_scheduler_root_available": production_root_available,
            "authority_document_available": authority_document_available,
            "one_shot_claim_available": claim_available,
            "production_authority_verified": False,
        },
        "required_external_contract": {
            "external_scheduler_authority": True,
            "signature_algorithm": "ed25519",
            "nonce_binding": True,
            "namespace_inode_binding": True,
            "source_digest_binding": True,
            "plan_digest_binding": True,
            "resource_snapshot_binding": True,
            "scheduler_owned_gpu_uuid_pci_binding": True,
            "one_shot_consume_witness": True,
            "caller_claim_can_substitute": False,
        },
        "external_authority": {
            "path_supplied": False,
            "verified": False,
            "real_external_document_required": True,
            "signature_algorithm": "ed25519",
            "caller_claim_can_substitute": False,
            "trusted_key": key_metadata,
            "scheduler_root": scheduler_metadata,
            "authority_documents": authority_documents,
            "claim_documents": claim_documents,
        },
        "resource_binding": {
            "local_gpu_index_present_in_plan": True,
            "scheduler_owned_gpu_uuid_pci_required": True,
            "verified": False,
            "implicit_probe_allowed": False,
            "caller_snapshot_accepted": False,
        },
        "projection_contract": {
            "safe_local_projection_implemented": False,
            "safe_local_repair": False,
            "non_authorizing_projection_only": True,
            "producer_reissue_required": True,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "historical_receipt_rewritten": False,
            "authority_gate_before_execute": False,
            "popen_allowed": False,
            "formal_promotion_allowed": False,
        },
        "exact_gaps": gaps,
        "readiness": {
            "diagnostic_only": True,
            "authority_verified": False,
            "launch_allowed": False,
            "popen_attempted": False,
            "solver_started": False,
            "worker_started": False,
            "queue_submitted": False,
            "gpu_execution_observed": False,
            "formal": False,
            "credit": 0,
        },
        "side_effects": dict(SIDE_EFFECTS),
        "write_set": [
            str(DEFAULT_REPORT.relative_to(LAB_ROOT)),
            str(DEFAULT_MARKDOWN.relative_to(LAB_ROOT)),
        ],
        **ZERO_CREDIT,
    }


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    observed = value[key]
    if type(expected) is bool and type(observed) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(observed) is not int:
        _fail(f"{name}.{key} must be integer")
    if observed != expected:
        _fail(f"{name}.{key} must be {expected!r}")


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        if report.get("status") not in {"blocked_fail_closed", "blocked_static_unverified"}:
            _fail("report.status is not a blocked status")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        scope = _mapping(report.get("scope"), "report.scope")
        for key, expected in {
            "family": "F3",
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "seed": SEED,
            "case_id": CASE_ID,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "shared_files_modified": False,
            "historical_receipts_modified": False,
        }.items():
            _exact(scope, key, expected, "report.scope")
        coverage = _mapping(report.get("implementation_coverage"), "report.implementation_coverage")
        for key in (
            "external_scheduler_authority_contract",
            "ed25519_signature_verification",
            "scheduler_owned_gpu_uuid_pci_binding",
            "one_shot_external_consume_witness",
            "authority_gate_before_execute",
        ):
            _exact(coverage, key, False, "report.implementation_coverage")
        external = _mapping(report.get("external_authority"), "report.external_authority")
        _exact(external, "verified", False, "report.external_authority")
        _exact(external, "real_external_document_required", True, "report.external_authority")
        _exact(external, "caller_claim_can_substitute", False, "report.external_authority")
        resource = _mapping(report.get("resource_binding"), "report.resource_binding")
        _exact(resource, "verified", False, "report.resource_binding")
        _exact(resource, "implicit_probe_allowed", False, "report.resource_binding")
        projection = _mapping(report.get("projection_contract"), "report.projection_contract")
        for key, expected in {
            "safe_local_projection_implemented": False,
            "safe_local_repair": False,
            "non_authorizing_projection_only": True,
            "producer_reissue_required": True,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "historical_receipt_rewritten": False,
            "authority_gate_before_execute": False,
            "popen_allowed": False,
            "formal_promotion_allowed": False,
        }.items():
            _exact(projection, key, expected, "report.projection_contract")
        readiness = _mapping(report.get("readiness"), "report.readiness")
        for key, expected in {
            "diagnostic_only": True,
            "authority_verified": False,
            "launch_allowed": False,
            "popen_attempted": False,
            "solver_started": False,
            "worker_started": False,
            "queue_submitted": False,
            "gpu_execution_observed": False,
            "formal": False,
            "credit": 0,
        }.items():
            _exact(readiness, key, expected, "report.readiness")
        exact_gaps = report.get("exact_gaps")
        if not isinstance(exact_gaps, list) or not exact_gaps:
            _fail("report.exact_gaps must be a non-empty list")
        for index, gap in enumerate(exact_gaps):
            item = _mapping(gap, f"report.exact_gaps[{index}]")
            for key in ("id", "title", "condition", "consequence", "required_evidence"):
                if not isinstance(item.get(key), str) or not item[key]:
                    _fail(f"report.exact_gaps[{index}].{key} must be a non-empty string")
        effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key, expected in SIDE_EFFECTS.items():
            _exact(effects, key, expected, "report.side_effects")
        sources = _mapping(report.get("contract_sources"), "report.contract_sources")
        if set(sources) != set(SOURCE_PATHS):
            _fail("report.contract_sources must contain only the MLP seed43 contract sources")
    except (AuditError, TypeError, ValueError, KeyError) as error:
        errors.append(str(error))
    return errors


def _json_text(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _markdown(report: Mapping[str, Any]) -> str:
    coverage = report["implementation_coverage"]
    observation = report["production_observation"]
    gaps = report["exact_gaps"]
    lines = [
        "# F3 MLP hidden16 seed43 authority projection gap",
        "",
        f"状态：`{report['status']}`；这是 bounded gap artifact，不是 scheduler authority receipt。",
        "",
        "范围：MLP / hidden16 / seed43 / current-manifest / test / 500 updates / 835 transitions / 836 frames。",
        "",
        "现有本地契约观察：",
        "",
    ]
    lines.extend(f"- `{key}`：`{value}`" for key, value in sorted(coverage.items()))
    lines.extend(
        [
            "",
            "外部 authority 观察（仅 metadata，未打开 manifest/training/checkpoint/trajectory/HDF5）：",
            "",
            f"- trusted Ed25519 key available：`{observation['production_key_available']}`",
            f"- scheduler root available：`{observation['production_scheduler_root_available']}`",
            f"- signed authority document available：`{observation['authority_document_available']}`",
            f"- one-shot consume claim available：`{observation['one_shot_claim_available']}`",
            "- production authority verified：`False`",
            "",
            "精确缺口：",
            "",
        ]
    )
    for gap in gaps:
        lines.extend(
            [
                f"- `{gap['id']}` **{gap['title']}**：{gap['condition']}；后果：{gap['consequence']}。",
                f"  - 下一证据：{gap['required_evidence']}。",
            ]
        )
    lines.extend(
        [
            "",
            "安全边界：未调用 Popen/solver/worker/GPU/queue，未打开生产大文件，未写 registry、ledger、denominator、gate、completion 或 PLAN；`launch_allowed=false`、`formal=false`、`credit=0`。",
            "",
            "现有 current-manifest terminal/training reports 即使存在，也不能替代外部 scheduler authority 或产生 Core credit。",
            "",
        ]
    )
    return "\n".join(lines)


def _output_path(value: Path | str, expected_suffix: str, name: str) -> Path:
    path = _absolute(value, name)
    if path.suffix != expected_suffix or "SEED43" not in path.name.upper():
        _fail(f"{name} must be a seed43 report path with suffix {expected_suffix}")
    if not path.parent.exists() or not path.parent.is_dir():
        _fail(f"{name} parent must already exist")
    return path


def write_reports(
    report: Mapping[str, Any],
    *,
    report_path: Path | str = DEFAULT_REPORT,
    markdown_path: Path | str = DEFAULT_MARKDOWN,
) -> tuple[Path, Path]:
    if validate_report(report):
        _fail("cannot write an invalid gap report")
    json_path = _output_path(report_path, ".json", "JSON report")
    md_path = _output_path(markdown_path, ".md", "Markdown report")
    json_path.write_text(_json_text(report), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--verify-report", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.verify_report is not None:
            raw = _read_small(args.verify_report, max_bytes=2 * 1024 * 1024, name="gap report")
            report = json.loads(raw.decode("utf-8"))
            errors = validate_report(_mapping(report, "gap report"))
            if errors:
                for error in errors:
                    print(error)
                return 2
            return 0
        report = audit()
        write_reports(report, report_path=args.report_output, markdown_path=args.markdown_output)
    except (AuditError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"blocked_fail_closed: {error}")
        return 2
    print(json.dumps({"status": report["status"], "credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
