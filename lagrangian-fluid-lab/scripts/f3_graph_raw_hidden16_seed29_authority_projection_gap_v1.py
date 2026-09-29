#!/usr/bin/env python3
"""Bounded, read-only authority-projection gap inventory for F3 seed29.

The seed29 admission and runner already contain the security boundary needed
for a real diagnostic admission.  What is absent in this checkout is the
producer-issued external scheduler authority, its trusted Ed25519 key, and a
current receipt carrying the resulting bindings.  This module records that
gap without attempting to repair it locally.

This is deliberately seed29-only.  It does not import or edit seed17 files,
does not edit the shared runner, and never mints an authority document,
consumes a receipt, starts Popen/solver/worker/GPU/queue work, or writes any
formal/registry/ledger/denominator/gate/completion state.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from datetime import datetime, timezone
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.dont_write_bytecode = True

from scripts import f3_graph_raw_hidden16_seed29_diagnostic_admission_v1 as admission
from scripts import f3_graph_raw_hidden16_seed29_diagnostic_runner_v2 as runner


LAB_ROOT = Path(__file__).resolve().parents[1]
SEED = 29
MODEL_KIND = "graph_raw"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
SPLIT = "test"

SCHEMA = "core.f3.graph_raw.hidden16.seed29.authority_projection_gap.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-graph-raw-hidden16-seed29-authority-projection-gap-v1"
DEFAULT_OBSERVED_ADMISSION_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RAW-HIDDEN16-SEED29-DIAGNOSTIC-ADMISSION-2026-09-29.json"
)
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RAW-HIDDEN16-SEED29-AUTHORITY-PROJECTION-GAP-RERUN1-2026-09-29.json"
)
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024

ZERO_CREDIT: dict[str, Any] = dict(admission.ZERO_CREDIT)

REQUIRED_RECEIPT_FIELDS = (
    "schema",
    "status",
    "receipt_version",
    "report_id",
    "identity",
    "identity_sha256",
    "namespace_marker",
    "receipt_path",
    "consumption",
    "diagnostic_execute_only",
    "authority",
    "receipt_sha256",
)
REQUIRED_IDENTITY_FIELDS = (
    "model_kind",
    "hidden",
    "updates",
    "seed",
    "case_id",
    "split",
    "transitions",
    "frames",
    "run_id",
    "root",
    "manifest",
    "training_receipt",
    "checkpoint",
    "source_sha256",
    "resource_snapshot",
    "gpu",
    "gpu_identity_sha256",
    "command",
    "environment",
    "executable",
    "owner",
    "namespace_descriptor",
    "namespace",
    "nonce",
    "plan_sha256",
    "rollout_snapshot",
    "rollout_snapshot_sha256",
    "external_authority",
)
REQUIRED_CONSUMPTION_FIELDS = (
    "one_shot",
    "state",
    "consumed",
    "state_file",
    "lock_path",
    "consumed_marker",
    "external_claim_path",
)

CONTRACT_SOURCE_PATHS = {
    "seed29_admission": LAB_ROOT / "scripts" / "f3_graph_raw_hidden16_seed29_diagnostic_admission_v1.py",
    "seed29_runner": LAB_ROOT / "scripts" / "f3_graph_raw_hidden16_seed29_diagnostic_runner_v2.py",
    "seed29_admission_tests": LAB_ROOT / "tests" / "test_f3_graph_raw_hidden16_seed29_diagnostic_admission_v1.py",
    "seed29_runner_tests": LAB_ROOT / "tests" / "test_f3_graph_raw_hidden16_seed29_diagnostic_runner_v2.py",
}


class GapInventoryError(ValueError):
    """Malformed bounded input or an invalid gap report."""


def _fail(message: str) -> None:
    raise GapInventoryError(f"fail-closed: {message}")


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


def _read_bounded_json(path: Path | str, name: str, *, max_bytes: int) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        raw, descriptor, payload = admission._read_file(
            candidate,
            name,
            max_bytes=max_bytes,
            parse_json=True,
        )
    except (admission.AdmissionError, OSError, TypeError, ValueError) as error:
        _fail(str(error))
    if payload is None:
        _fail(f"{name} is not a JSON object")
    return dict(_mapping(payload, name)), {
        "path": str(candidate),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mode": int(descriptor["mode"]),
        "uid": int(descriptor["uid"]),
        "gid": int(descriptor["gid"]),
        "nlink": int(descriptor["nlink"]),
    }


def _path_state(path: Path | str, name: str) -> dict[str, Any]:
    """Inspect only filesystem metadata; never opens the target."""

    candidate = Path(path)
    try:
        info = os.lstat(candidate)
    except FileNotFoundError:
        return {"path": str(candidate), "present": False, "kind": "absent"}
    except OSError as error:
        return {"path": str(candidate), "present": False, "kind": "uninspectable", "error": str(error)}
    if stat.S_ISLNK(info.st_mode):
        kind = "symlink"
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
    elif stat.S_ISREG(info.st_mode):
        kind = "regular_file"
    else:
        kind = "other"
    return {
        "path": str(candidate),
        "present": True,
        "kind": kind,
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
    }


def _source_descriptor(path: Path) -> dict[str, Any]:
    """Hash only the small, seed29 contract sources in the repository."""

    try:
        info = os.lstat(path)
    except OSError as error:
        return {"path": str(path), "present": False, "error": str(error)}
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        return {
            "path": str(path),
            "present": False,
            "error": "contract source must be a regular single-link file",
        }
    if info.st_size < 1 or info.st_size > MAX_SOURCE_BYTES:
        return {
            "path": str(path),
            "present": False,
            "error": "contract source exceeds bounded size",
        }
    raw = path.read_bytes()
    return {
        "path": str(path),
        "present": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
    }


def _receipt_gap(path: Path | str | None) -> dict[str, Any]:
    if path is None:
        return {
            "supplied": False,
            "present": False,
            "path": None,
            "missing_fields": [],
            "status": "not_supplied",
        }
    candidate = Path(path)
    try:
        receipt, descriptor = _read_bounded_json(candidate, "seed29 source receipt", max_bytes=MAX_JSON_BYTES)
    except GapInventoryError as error:
        return {
            "supplied": True,
            "present": False,
            "path": str(candidate),
            "status": "unreadable_or_absent",
            "error": str(error),
            "missing_fields": ["current_authority_bound_receipt"],
        }
    missing: list[str] = [key for key in REQUIRED_RECEIPT_FIELDS if key not in receipt]
    identity = receipt.get("identity")
    if not isinstance(identity, Mapping):
        missing.append("identity")
    else:
        missing.extend(
            f"identity.{key}" for key in REQUIRED_IDENTITY_FIELDS if key not in identity
        )
    consumption = receipt.get("consumption")
    if not isinstance(consumption, Mapping):
        missing.append("consumption")
    else:
        missing.extend(
            f"consumption.{key}"
            for key in REQUIRED_CONSUMPTION_FIELDS
            if key not in consumption
        )
    return {
        "supplied": True,
        "present": True,
        "path": str(candidate),
        "file": descriptor,
        "schema": receipt.get("schema"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "status": "current_shape_complete" if not missing else "missing_current_fields",
        "missing_fields": sorted(set(missing)),
        "authority_present": "authority" in receipt,
        "external_authority_present": isinstance(identity, Mapping) and "external_authority" in identity,
    }


def _observed_admission_report(path: Path) -> dict[str, Any]:
    try:
        payload, descriptor = _read_bounded_json(
            path,
            "seed29 observed admission report",
            max_bytes=MAX_REPORT_BYTES,
        )
    except GapInventoryError as error:
        return {
            "path": str(path),
            "present": False,
            "error": str(error),
        }
    return {
        "path": str(path),
        "present": True,
        "file": descriptor,
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "source_bound": payload.get("source_bound"),
        "admission_granted": payload.get("admission_granted"),
        "blocked_reasons": list(payload.get("blocked_reasons", []))
        if isinstance(payload.get("blocked_reasons"), list)
        else [],
    }


def _runner_boundary() -> dict[str, Any]:
    """Use the explicit no-receipt dry-run path; it cannot call Popen."""

    report = runner.build_report(None, execute_requested=False)
    return {
        "script": str(LAB_ROOT / "scripts" / "f3_graph_raw_hidden16_seed29_diagnostic_runner_v2.py"),
        "schema": report.get("schema"),
        "status": report.get("status"),
        "requires_explicit_admission_receipt": "--admission-receipt is required"
        in " ".join(str(item) for item in report.get("blocked_reasons", [])),
        "popen_attempted": report.get("popen_attempted"),
        "wait_attempted": report.get("wait_attempted"),
        "real_workload_started": report.get("real_workload_started"),
        "terminal_receipt_present": report.get("terminal_receipt") is not None,
        "launch_allowed": report.get("launch_allowed"),
        "credit": report.get("credit"),
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
    observed_admission_report: Path | str = DEFAULT_OBSERVED_ADMISSION_REPORT,
    source_receipt: Path | str | None = None,
) -> dict[str, Any]:
    """Build a fail-closed inventory without minting or projecting authority."""

    observed = _observed_admission_report(Path(observed_admission_report))
    receipt_gap = _receipt_gap(source_receipt)
    runner_boundary = _runner_boundary()
    trust_key = _path_state(admission.TRUSTED_SCHEDULER_PUBLIC_KEY_PATH, "trusted scheduler key")
    scheduler_root = _path_state(admission.EXTERNAL_SCHEDULER_ROOT, "external scheduler root")
    authority_document = {
        "path_supplied": False,
        "verified": False,
        "real_external_document_required": True,
        "signature_algorithm": "ed25519",
        "trust_key": trust_key,
        "scheduler_root": scheduler_root,
        "caller_claim_can_substitute": False,
    }
    resource_binding = {
        "supplied": False,
        "verified": False,
        "scheduler_owned_gpu_uuid_pci_required": True,
        "implicit_probe_allowed": False,
    }

    missing: list[str] = []
    if not observed.get("source_bound"):
        missing.append("scheduler_owned_resource_snapshot.gpu_uuid_pci")
    if not trust_key.get("present") or trust_key.get("kind") != "regular_file":
        missing.append("trusted_scheduler_ed25519_public_key")
    if not scheduler_root.get("present") or scheduler_root.get("kind") != "directory":
        missing.append("external_scheduler_root")
    missing.append("external_scheduler_authority_document")
    if not receipt_gap.get("present"):
        missing.append("current_authority_bound_receipt")
    missing.extend(
        [
            "receipt.identity.nonce",
            "receipt.identity.namespace_descriptor",
            "receipt.identity.plan_sha256",
            "receipt.identity.source_sha256",
            "receipt.identity.resource_snapshot",
            "receipt.identity.external_authority",
        ]
        if not receipt_gap.get("present")
        else []
    )
    if not runner_boundary.get("terminal_receipt_present"):
        missing.append("independently_bound_terminal_receipt")

    blockers = [
        "no producer-issued external scheduler authority document was supplied or verified",
        "authority verification requires a deployment-trusted Ed25519 public key and scheduler root",
        "nonce, namespace inode, plan, source descriptors, resource snapshot, and GPU identity cannot be reconstructed locally",
        "seed29 admission report is not source-bound because the scheduler-owned GPU UUID/PCI snapshot is absent",
        "seed29 runner requires an explicit authority-bound admission receipt and has no independent terminal receipt",
        "producer-issued current-schema receipt/reissue is required before any runner retry",
    ]
    if observed.get("blocked_reasons"):
        blockers.extend(
            f"observed admission report: {reason}"
            for reason in observed["blocked_reasons"]
        )
    if receipt_gap.get("status") == "missing_current_fields":
        blockers.append("the supplied source receipt is missing current-schema fields; local repair is prohibited")

    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "blocked_projection_gap",
        "scope": {
            "family": "F3",
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "seed": SEED,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "mode": "diagnostic_only",
        },
        "contract_sources": {
            key: _source_descriptor(path) for key, path in CONTRACT_SOURCE_PATHS.items()
        },
        "admission_contract": {
            "module": str(CONTRACT_SOURCE_PATHS["seed29_admission"]),
            "schema": admission.SCHEMA,
            "authority_schema": admission.EXTERNAL_AUTHORITY_SCHEMA,
            "external_authority_required": True,
            "signature_algorithm": "ed25519",
            "required_bindings": [
                "signed_external_authority",
                "nonce",
                "namespace_inode",
                "plan_sha256",
                "source_descriptors",
                "resource_snapshot",
                "gpu_identity",
                "independent_consume_path",
            ],
            "caller_claim_can_substitute": False,
            "implicit_resource_probe_allowed": False,
            "durable_local_projection_allowed": False,
        },
        "runner_boundary": runner_boundary,
        "observed_admission_report": observed,
        "source_receipt": receipt_gap,
        "external_authority": authority_document,
        "resource_binding": resource_binding,
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
        "missing_requirements": sorted(set(missing)),
        "blockers": list(dict.fromkeys(blockers)),
        "side_effects": _side_effects(),
        "diagnostic_only": True,
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
            "model_kind": MODEL_KIND,
            "hidden": HIDDEN,
            "seed": SEED,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "mode": "diagnostic_only",
        }.items():
            _exact(scope, key, expected, "report.scope")
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
        external = _mapping(report.get("external_authority"), "report.external_authority")
        _exact(external, "verified", False, "report.external_authority")
        _exact(external, "real_external_document_required", True, "report.external_authority")
        resource = _mapping(report.get("resource_binding"), "report.resource_binding")
        _exact(resource, "verified", False, "report.resource_binding")
        _exact(resource, "implicit_probe_allowed", False, "report.resource_binding")
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
        expected_sources = set(CONTRACT_SOURCE_PATHS)
        if set(sources) != expected_sources:
            _fail("report.contract_sources must contain only seed29 contract sources")
        runner_info = _mapping(report.get("runner_boundary"), "report.runner_boundary")
        _exact(runner_info, "popen_attempted", False, "report.runner_boundary")
        _exact(runner_info, "wait_attempted", False, "report.runner_boundary")
        _exact(runner_info, "real_workload_started", 0, "report.runner_boundary")
        _exact(runner_info, "terminal_receipt_present", False, "report.runner_boundary")
        _exact(runner_info, "launch_allowed", False, "report.runner_boundary")
        _exact(runner_info, "credit", 0, "report.runner_boundary")
    except (GapInventoryError, TypeError, ValueError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# F3 graph_raw hidden16 seed29 authority projection gap",
        "",
        f"- status: `{report.get('status')}`",
        "- scope: `graph_raw / hidden16 / seed29 / test / 500 updates / 835 transitions / 836 frames`",
        f"- current admission source-bound: `{report.get('observed_admission_report', {}).get('source_bound')}`",
        f"- external authority verified: `{report.get('external_authority', {}).get('verified')}`",
        f"- resource binding verified: `{report.get('resource_binding', {}).get('verified')}`",
        f"- terminal receipt present: `{report.get('runner_boundary', {}).get('terminal_receipt_present')}`",
        f"- safe local projection: `{report.get('projection_contract', {}).get('safe_local_projection_implemented')}`",
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
            "This seed29-only inventory does not mint or project authority. A future producer-issued "
            "receipt must carry a real external scheduler signature and exact nonce, namespace, "
            "source, plan, resource, and GPU bindings before the runner can be reconsidered.",
            "",
            "No Popen/solver/worker/GPU/queue execution occurred; no PLAN, registry, ledger, "
            "denominator, gate, completion, or historical receipt was modified.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed-admission-report", type=Path, default=DEFAULT_OBSERVED_ADMISSION_REPORT)
    parser.add_argument("--source-receipt", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verify_report is not None:
        try:
            report, _descriptor = _read_bounded_json(
                args.verify_report,
                "gap report",
                max_bytes=MAX_REPORT_BYTES,
            )
        except GapInventoryError as error:
            print(str(error), file=sys.stderr)
            return 2
        errors = validate_report(report)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
        return 0

    report = build_report(
        observed_admission_report=args.observed_admission_report,
        source_receipt=args.source_receipt,
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
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
