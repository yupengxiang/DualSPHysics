#!/usr/bin/env python3
"""Bounded, read-only authority-projection gap audit for F3 MLP seed29.

The current-manifest MLP launcher binds a manifest, training receipt,
checkpoint metadata, run id, nonce, output namespace, and a GPU index.  Those
caller-supplied values are useful diagnostic plan metadata, but they are not a
producer-issued external scheduler authority.  In particular, this checkout
does not provide an Ed25519 trust anchor, a scheduler-owned GPU UUID/PCI
snapshot, or a namespace-inode-bound authority document for seed29.

This adapter records that bounded gap without projecting authority locally.
It reads only small JSON/source metadata, never opens checkpoints,
evaluation/trajectory/HDF5 data, or production manifests, and never starts a
process.  It does not rewrite the existing plan or any historical receipt and
cannot grant formal, T1/T2, qualification, or credit state.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
MODEL = "mlp"
HIDDEN = 16
SEED = 29
UPDATES = 500
CASE_ID = "F3_DEV_00_a0p903125"
SPLIT = "test"
TRANSITIONS = 835
FRAMES = 836

SCHEMA = "core.f3.mlp.hidden16.seed29.authority_projection_gap.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-mlp-hidden16-seed29-authority-projection-gap-v1"
AUTHORITY_SCHEMA = "core.f3.mlp.hidden16.seed29.external_scheduler_authority.v1"
ROLLOUT_PLAN_SCHEMA = "core.f3.mlp.hidden16.current_manifest_rollout_launcher_plan.v1"

DEFAULT_OBSERVED_PLAN = (
    LAB_ROOT
    / "reports"
    / "F3-MLP-HIDDEN16-CURRENT-MANIFEST-SEED29-ROLLOUT-PLAN-V1.json"
)
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-MLP-HIDDEN16-SEED29-AUTHORITY-PROJECTION-GAP-2026-09-29.json"
)
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

TRUSTED_SCHEDULER_PUBLIC_KEY_PATH = Path(
    "/etc/dual-sph/scheduler-ed25519-public.key"
)
EXTERNAL_SCHEDULER_ROOT = Path("/var/lib/dual-sph/f3-mlp-seed29-scheduler")

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024

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

# These are shared current-manifest contracts only.  The audit is scoped to
# seed29 and deliberately does not inventory another model or seed's adapter.
CONTRACT_SOURCE_PATHS = {
    "rollout_launcher": LAB_ROOT / "scripts" / "f3_mlp_hidden16_current_manifest_rollout_launcher_v1.py",
    "training_evidence": LAB_ROOT / "scripts" / "f3_mlp_hidden16_current_manifest_training_evidence_v1.py",
    "case_matrix": LAB_ROOT / "scripts" / "f3_mlp_hidden16_current_manifest_case_matrix_v1.py",
    "terminal_evidence": LAB_ROOT / "scripts" / "f3_mlp_hidden16_current_manifest_terminal_evidence_v1.py",
}


class GapAuditError(ValueError):
    """Malformed bounded input or invalid gap report."""


def _fail(message: str) -> None:
    raise GapAuditError(f"fail-closed: {message}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


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


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_uid),
        int(info.st_gid),
    )


def _regular_single_link(path: Path, name: str, *, max_bytes: int) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as error:
        _fail(f"cannot stat {name}: {error}")
    if stat.S_ISLNK(info.st_mode):
        _fail(f"{name} must not be a symlink")
    if not stat.S_ISREG(info.st_mode):
        _fail(f"{name} must be a regular file")
    if info.st_nlink != 1:
        _fail(f"{name} must have exactly one hard link")
    if info.st_size < 0 or info.st_size > max_bytes:
        _fail(f"{name} exceeds bounded size {max_bytes}")
    return info


def _read_bounded_bytes(path: Path | str, name: str, *, max_bytes: int) -> tuple[bytes, dict[str, Any]]:
    candidate = Path(path)
    info = _regular_single_link(candidate, name, max_bytes=max_bytes)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        _fail(f"cannot open {name}: {error}")
    chunks: list[bytes] = []
    try:
        opened = os.fstat(fd)
        if _file_identity(opened) != _file_identity(info):
            _fail(f"{name} changed before bounded read")
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        if total > max_bytes:
            _fail(f"{name} exceeds bounded size {max_bytes}")
        closed = os.fstat(fd)
        if _file_identity(closed) != _file_identity(info):
            _fail(f"{name} changed during bounded read")
    except OSError as error:
        _fail(f"cannot read {name}: {error}")
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        _fail(f"cannot re-stat {name}: {error}")
    if _file_identity(after) != _file_identity(info) or after.st_size != len(b"".join(chunks)):
        _fail(f"{name} changed after bounded read")
    raw = b"".join(chunks)
    return raw, {
        "path": str(candidate),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
    }


def _read_bounded_json(path: Path | str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = Path(path)
    try:
        raw, descriptor = _read_bounded_bytes(candidate, name, max_bytes=MAX_JSON_BYTES)
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, GapAuditError) as error:
        if isinstance(error, GapAuditError):
            raise
        _fail(f"invalid bounded {name}: {error}")
    return dict(_mapping(payload, name)), descriptor


def _path_state(path: Path, name: str) -> dict[str, Any]:
    """Inspect filesystem metadata only; do not open the target."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {"path": str(path), "present": False, "kind": "absent"}
    except OSError as error:
        return {
            "path": str(path),
            "present": False,
            "kind": "uninspectable",
            "error": str(error),
        }
    if stat.S_ISLNK(info.st_mode):
        kind = "symlink"
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
    elif stat.S_ISREG(info.st_mode):
        kind = "regular_file"
    else:
        kind = "other"
    return {
        "path": str(path),
        "present": True,
        "kind": kind,
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
    }


def _source_descriptor(path: Path) -> dict[str, Any]:
    try:
        raw, descriptor = _read_bounded_bytes(path, "MLP contract source", max_bytes=MAX_SOURCE_BYTES)
        text = raw.decode("utf-8")
    except (UnicodeError, GapAuditError) as error:
        return {"path": str(path), "present": False, "error": str(error)}
    return {
        **descriptor,
        "present": True,
        "markers": {
            "external_authority_schema": "EXTERNAL_AUTHORITY_SCHEMA" in text,
            "ed25519_verifier": "Ed25519PublicKey" in text,
            "scheduler_authority_validation": "external scheduler authority" in text,
            "namespace_descriptor": "namespace_descriptor" in text,
            "resource_snapshot": "resource_snapshot" in text,
            "popen_path": "Popen" in text,
        },
    }


def _observed_plan(path: Path | str | None) -> dict[str, Any]:
    if path is None:
        return {
            "supplied": False,
            "present": False,
            "path": None,
            "status": "not_supplied",
            "authority_field_present": False,
            "resource_snapshot_present": False,
            "namespace_inode_binding_present": False,
            "source_descriptor_binding_present": False,
            "terminal_receipt_present": False,
        }
    candidate = Path(path)
    try:
        payload, descriptor = _read_bounded_json(candidate, "seed29 rollout plan")
    except GapAuditError as error:
        return {
            "supplied": True,
            "present": False,
            "path": str(candidate),
            "status": "unreadable_or_absent",
            "error": str(error),
            "authority_field_present": False,
            "resource_snapshot_present": False,
            "namespace_inode_binding_present": False,
            "source_descriptor_binding_present": False,
            "terminal_receipt_present": False,
        }

    authority_present = "authority" in payload or "external_authority" in payload
    resource = payload.get("resource_snapshot")
    resource_present = isinstance(resource, Mapping) and any(
        key in resource for key in ("gpu_uuid", "gpu_pci", "gpu_uuid_pci")
    )
    source_present = any(
        key in payload for key in ("source_descriptors", "source_sha256", "source_identity")
    )
    return {
        "supplied": True,
        "present": True,
        "path": str(candidate),
        "file": descriptor,
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "seed": payload.get("seed"),
        "model": payload.get("model"),
        "hidden": payload.get("hidden"),
        "updates": payload.get("updates"),
        "run_id": payload.get("run_id"),
        "launched": payload.get("launched"),
        "mode": payload.get("mode"),
        "gpu_index": payload.get("gpu_index"),
        "namespace_nonce_present": isinstance(payload.get("namespace_nonce"), str),
        "output_namespace_present": isinstance(payload.get("output_namespace"), str),
        "authority_field_present": authority_present,
        "resource_snapshot_present": resource_present,
        "namespace_inode_binding_present": "namespace_descriptor" in payload,
        "source_descriptor_binding_present": source_present,
        "terminal_receipt_present": isinstance(payload.get("terminal_receipt"), Mapping),
    }


def _side_effects() -> dict[str, Any]:
    return {
        "popen_attempted": False,
        "wait_attempted": False,
        "processes_started": 0,
        "processes_stopped": 0,
        "processes_restarted": 0,
        "solver_started": False,
        "worker_started": False,
        "queue_submissions": 0,
        "gpu_execution_started": False,
        "registry_writes": 0,
        "ledger_writes": 0,
        "denominator_writes": 0,
        "gate_writes": 0,
        "completion_writes": 0,
        "plan_writes": 0,
        "historical_receipt_writes": 0,
    }


def build_report(
    *,
    observed_plan: Path | str | None = DEFAULT_OBSERVED_PLAN,
    authority_document: Path | str | None = None,
) -> dict[str, Any]:
    """Build a non-authorizing seed29 gap report without launching anything."""

    plan = _observed_plan(observed_plan)
    sources = {key: _source_descriptor(path) for key, path in CONTRACT_SOURCE_PATHS.items()}
    trust_key = _path_state(TRUSTED_SCHEDULER_PUBLIC_KEY_PATH, "trusted scheduler key")
    scheduler_root = _path_state(EXTERNAL_SCHEDULER_ROOT, "external scheduler root")
    supplied_authority = None if authority_document is None else _path_state(Path(authority_document), "authority document")

    launcher_markers = sources["rollout_launcher"].get("markers", {})
    authority_boundary_present = bool(
        launcher_markers.get("external_authority_schema")
        and launcher_markers.get("ed25519_verifier")
        and launcher_markers.get("scheduler_authority_validation")
    )
    missing = [
        "external_scheduler_authority_document",
        "trusted_scheduler_ed25519_public_key",
        "external_scheduler_root",
        "authority_ed25519_signature_verification",
        "authority_nonce_binding",
        "authority_namespace_inode_binding",
        "authority_plan_sha256_binding",
        "authority_source_descriptor_binding",
        "authority_resource_snapshot_binding",
        "authority_gpu_uuid_pci_binding",
        "seed29_current_authority_bound_admission",
        "independently_bound_terminal_receipt",
    ]
    blockers = [
        "the current MLP launcher has no external scheduler authority boundary; its nonce, output namespace, and gpu_index are caller-supplied plan fields",
        "no producer-issued external scheduler authority document was supplied or verified",
        "authority verification requires a deployment-trusted Ed25519 public key and scheduler root",
        "a gpu_index is not a scheduler-owned GPU UUID/PCI resource snapshot and cannot satisfy resource binding",
        "namespace_nonce and output_namespace do not provide a namespace inode descriptor or an independent consume path",
        "manifest/training/checkpoint hashes in the local plan cannot substitute for signed source descriptors and plan binding",
        "the seed29 plan is dry-run metadata with no independently bound terminal receipt; local projection cannot make it runner-consumable",
        "producer-side authority-bound reissue is required before any diagnostic rollout retry",
    ]
    if not plan.get("present"):
        blockers.append("the observed seed29 rollout plan is unavailable or unreadable")
    elif plan.get("status") != "dry_run_ready" or plan.get("launched") is not False:
        blockers.append("the observed seed29 plan is not the expected non-launched dry-run shape")
    if plan.get("authority_field_present"):
        blockers.append("caller-supplied authority-shaped fields are untrusted and cannot mint scheduler authority")
    if authority_document is not None:
        blockers.append("a supplied authority path is metadata-only here; no local document is verified or promoted")
    if trust_key.get("present") and trust_key.get("kind") == "regular_file":
        missing.remove("trusted_scheduler_ed25519_public_key")
    if scheduler_root.get("present") and scheduler_root.get("kind") == "directory":
        missing.remove("external_scheduler_root")

    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "blocked_projection_gap",
        "scope": {
            "family": "F3",
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "seed": SEED,
            "case_id": CASE_ID,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "mode": "diagnostic_only",
        },
        "contract_sources": sources,
        "current_contract": {
            "rollout_plan_schema": ROLLOUT_PLAN_SCHEMA,
            "launcher": str(CONTRACT_SOURCE_PATHS["rollout_launcher"]),
            "external_authority_boundary_present": authority_boundary_present,
            "caller_supplied_nonce_present": True,
            "caller_supplied_output_namespace_present": True,
            "caller_supplied_gpu_index_present": True,
            "explicit_execute_path_present": bool(launcher_markers.get("popen_path")),
            "safe_local_projection_implemented": False,
        },
        "admission_contract": {
            "authority_schema": AUTHORITY_SCHEMA,
            "external_authority_required": True,
            "signature_algorithm": "ed25519",
            "required_bindings": [
                "signed_external_authority",
                "nonce",
                "namespace_inode",
                "plan_sha256",
                "source_descriptors",
                "resource_snapshot",
                "gpu_uuid_pci",
                "independent_consume_path",
            ],
            "caller_claim_can_substitute": False,
            "implicit_resource_probe_allowed": False,
            "durable_local_projection_allowed": False,
        },
        "observed_plan": plan,
        "external_authority": {
            "path_supplied": authority_document is not None,
            "path": None if authority_document is None else str(authority_document),
            "verified": False,
            "real_external_document_required": True,
            "signature_algorithm": "ed25519",
            "trust_key": trust_key,
            "scheduler_root": scheduler_root,
            "supplied_path_state": supplied_authority,
            "caller_claim_can_substitute": False,
        },
        "resource_binding": {
            "supplied": False,
            "verified": False,
            "scheduler_owned_gpu_uuid_pci_required": True,
            "implicit_probe_allowed": False,
            "local_gpu_index_is_not_identity": True,
        },
        "projection_contract": {
            "safe_local_projection_implemented": False,
            "safe_local_repair": False,
            "non_authorizing_projection_only": True,
            "producer_reissue_required": True,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "historical_receipt_rewritten": False,
            "popen_allowed": False,
        },
        "launch_boundary": {
            "popen_attempted": False,
            "wait_attempted": False,
            "launch_allowed": False,
            "terminal_receipt_present": False,
            "independent_terminal_receipt_required": True,
            "credit": 0,
        },
        "missing_requirements": sorted(set(missing)),
        "blockers": list(dict.fromkeys(blockers)),
        "side_effects": _side_effects(),
        **ZERO_CREDIT,
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_projection_gap", "report")
        _exact(report, "diagnostic_only", True, "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")

        scope = _mapping(report.get("scope"), "report.scope")
        for key, expected in {
            "family": "F3",
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "seed": SEED,
            "case_id": CASE_ID,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "mode": "diagnostic_only",
        }.items():
            _exact(scope, key, expected, "report.scope")

        contract = _mapping(report.get("current_contract"), "report.current_contract")
        _exact(contract, "external_authority_boundary_present", False, "report.current_contract")
        _exact(contract, "safe_local_projection_implemented", False, "report.current_contract")
        _exact(contract, "caller_supplied_nonce_present", True, "report.current_contract")
        _exact(contract, "caller_supplied_output_namespace_present", True, "report.current_contract")
        _exact(contract, "caller_supplied_gpu_index_present", True, "report.current_contract")

        admission = _mapping(report.get("admission_contract"), "report.admission_contract")
        _exact(admission, "external_authority_required", True, "report.admission_contract")
        _exact(admission, "signature_algorithm", "ed25519", "report.admission_contract")
        _exact(admission, "caller_claim_can_substitute", False, "report.admission_contract")
        _exact(admission, "implicit_resource_probe_allowed", False, "report.admission_contract")
        bindings = admission.get("required_bindings")
        if not isinstance(bindings, list) or "nonce" not in bindings or "resource_snapshot" not in bindings:
            _fail("report.admission_contract.required_bindings must include nonce/resource_snapshot")

        authority = _mapping(report.get("external_authority"), "report.external_authority")
        _exact(authority, "verified", False, "report.external_authority")
        _exact(authority, "real_external_document_required", True, "report.external_authority")
        _exact(authority, "signature_algorithm", "ed25519", "report.external_authority")

        resource = _mapping(report.get("resource_binding"), "report.resource_binding")
        _exact(resource, "verified", False, "report.resource_binding")
        _exact(resource, "implicit_probe_allowed", False, "report.resource_binding")
        _exact(resource, "local_gpu_index_is_not_identity", True, "report.resource_binding")

        projection = _mapping(report.get("projection_contract"), "report.projection_contract")
        for key, expected in {
            "safe_local_projection_implemented": False,
            "safe_local_repair": False,
            "non_authorizing_projection_only": True,
            "producer_reissue_required": True,
            "durable_receipt_written": False,
            "runner_consumable": False,
            "historical_receipt_rewritten": False,
            "popen_allowed": False,
        }.items():
            _exact(projection, key, expected, "report.projection_contract")

        boundary = _mapping(report.get("launch_boundary"), "report.launch_boundary")
        for key, expected in {
            "popen_attempted": False,
            "wait_attempted": False,
            "launch_allowed": False,
            "terminal_receipt_present": False,
            "independent_terminal_receipt_required": True,
            "credit": 0,
        }.items():
            _exact(boundary, key, expected, "report.launch_boundary")

        missing = report.get("missing_requirements")
        if not isinstance(missing, list) or not missing or any(not isinstance(item, str) for item in missing):
            _fail("report.missing_requirements must be a non-empty string list")
        blockers = report.get("blockers")
        if not isinstance(blockers, list) or not blockers or any(not isinstance(item, str) for item in blockers):
            _fail("report.blockers must be a non-empty string list")

        effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key, expected in _side_effects().items():
            _exact(effects, key, expected, "report.side_effects")

        sources = _mapping(report.get("contract_sources"), "report.contract_sources")
        if set(sources) != set(CONTRACT_SOURCE_PATHS):
            _fail("report.contract_sources must contain only current-manifest MLP sources")
        for key, item in sources.items():
            descriptor = _mapping(item, f"report.contract_sources.{key}")
            path = descriptor.get("path")
            if not isinstance(path, str) or "f3_mlp_hidden16_current_manifest_" not in path:
                _fail(f"report.contract_sources.{key} is outside the shared MLP current-manifest scope")
            if "seed17" in path or "seed43" in path:
                _fail(f"report.contract_sources.{key} crosses another seed scope")

        observed = _mapping(report.get("observed_plan"), "report.observed_plan")
        if observed.get("present"):
            _exact(observed, "seed", SEED, "report.observed_plan")
            _exact(observed, "model", MODEL, "report.observed_plan")
            _exact(observed, "hidden", HIDDEN, "report.observed_plan")
            _exact(observed, "updates", UPDATES, "report.observed_plan")
            _exact(observed, "authority_field_present", False, "report.observed_plan")
            _exact(observed, "resource_snapshot_present", False, "report.observed_plan")
            _exact(observed, "namespace_inode_binding_present", False, "report.observed_plan")
            _exact(observed, "source_descriptor_binding_present", False, "report.observed_plan")
            _exact(observed, "terminal_receipt_present", False, "report.observed_plan")
        if observed.get("authority_field_present"):
            _fail("caller-supplied authority-shaped plan fields cannot be accepted")
    except (GapAuditError, TypeError, ValueError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    scope = report.get("scope", {})
    authority = report.get("external_authority", {})
    resource = report.get("resource_binding", {})
    plan = report.get("observed_plan", {})
    lines = [
        "# F3 MLP hidden16 seed29 authority projection gap",
        "",
        f"- status: `{report.get('status')}`",
        f"- scope: `{scope.get('model_kind')} / hidden{scope.get('hidden')} / seed{scope.get('seed')} / {scope.get('split')} / {scope.get('updates')} updates / {scope.get('transitions')} transitions`",
        f"- observed plan: `{plan.get('status')}`; launched=`{plan.get('launched')}`",
        f"- external authority verified: `{authority.get('verified')}`",
        f"- resource binding verified: `{resource.get('verified')}`",
        f"- launch allowed: `{report.get('launch_boundary', {}).get('launch_allowed')}`",
        f"- credit: `{report.get('credit')}`",
        "",
        "## Exact missing requirements",
        "",
    ]
    lines.extend(f"- `{item}`" for item in report.get("missing_requirements", []))
    lines.extend(["", "## Blockers", ""])
    lines.extend(f"- {item}" for item in report.get("blockers", []))
    lines.extend(
        [
            "",
            "The local nonce, output namespace, gpu_index, manifest digest, and training/checkpoint metadata are not scheduler authority. A future producer-issued document must be verified with the deployment Ed25519 key and bind nonce, namespace inode, plan, source descriptors, resource snapshot, and GPU UUID/PCI identity before a seed29 rollout can be reconsidered.",
            "",
            "No Popen/solver/worker/GPU/queue execution occurred; no registry, ledger, denominator, gate, completion, PLAN, or historical receipt was modified.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed-plan", type=Path, default=DEFAULT_OBSERVED_PLAN)
    parser.add_argument("--authority-document", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verify_report is not None:
        try:
            report, _descriptor = _read_bounded_json(args.verify_report, "gap report")
        except GapAuditError as error:
            print(str(error), file=sys.stderr)
            return 2
        errors = validate_report(report)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
        return 0

    report = build_report(
        observed_plan=args.observed_plan,
        authority_document=args.authority_document,
    )
    errors = validate_report(report)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(report) + "\n", encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(report), encoding="utf-8")
    # A gap audit is intentionally non-authorizing; return 2 so callers cannot
    # mistake a valid blocked report for a launch/admission success.
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
