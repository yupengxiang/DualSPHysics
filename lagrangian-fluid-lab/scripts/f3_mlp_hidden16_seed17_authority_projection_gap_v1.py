#!/usr/bin/env python3
"""Bounded, read-only authority gap inventory for F3 MLP hidden16 seed17.

The current-manifest MLP artifacts contain useful producer/local projections:
training, manifest, rollout-plan, and terminal metadata.  They do not contain
a deployment-owned scheduler authority.  This module records that exact
boundary without treating a local GPU index, nonce, namespace, or copied JSON
field as authority.

The inventory is deliberately seed17-only.  It reads only bounded JSON
metadata and bounded source-code descriptors.  It never opens checkpoints,
trajectories/HDF5, evaluation payloads, or a scheduler database; it never
imports or calls a runner; and it never starts Popen, solver, worker, GPU, or
queue work.  A future external authority must be a real Ed25519-signed
scheduler document binding nonce, namespace inode, plan, source descriptors,
resource snapshot, GPU identity, and an independent consume-once path.
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
SEED = 17
MODEL = "mlp"
HIDDEN = 16
UPDATES = 500
TRANSITIONS = 835
FRAMES = 836
SPLIT = "test"

SCHEMA = "core.f3.mlp.hidden16.seed17.authority_projection_gap.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-mlp-hidden16-seed17-authority-projection-gap-v1"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024

DEFAULT_INPUTS: dict[str, Path] = {
    "manifest_identity": LAB_ROOT / "reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-IDENTITY-2026-09-29.json",
    "training_evidence": LAB_ROOT / "reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN1.json",
    "terminal_evidence": LAB_ROOT / "reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-TERMINAL-EVIDENCE-2026-09-29-RERUN2.json",
    "rollout_plan": LAB_ROOT / "reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-SEED17-ROLLOUT-PLAN-V1.json",
}
DEFAULT_REPORT = LAB_ROOT / "reports/F3-MLP-HIDDEN16-SEED17-AUTHORITY-PROJECTION-GAP-2026-09-29.json"
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

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

# These are the small, model-family contract files inspected by this
# inventory.  They are not an admission authority and are not edited here.
CONTRACT_SOURCE_PATHS: dict[str, Path] = {
    "training_intake": LAB_ROOT / "scripts/f3_mlp_hidden16_current_manifest_training_evidence_v1.py",
    "rollout_launcher": LAB_ROOT / "scripts/f3_mlp_hidden16_current_manifest_rollout_launcher_v1.py",
    "terminal_evidence": LAB_ROOT / "scripts/f3_mlp_hidden16_current_manifest_terminal_evidence_v1.py",
    "terminal_verifier": LAB_ROOT / "scripts/f3_mlp_hidden16_terminal_runtime_verifier_v1.py",
    "training_intake_tests": LAB_ROOT / "tests/test_f3_mlp_hidden16_current_manifest_training_evidence_v1.py",
    "rollout_launcher_tests": LAB_ROOT / "tests/test_f3_mlp_hidden16_current_manifest_rollout_launcher_v1.py",
    "terminal_evidence_tests": LAB_ROOT / "tests/test_f3_mlp_hidden16_current_manifest_terminal_evidence_v1.py",
}


class GapInventoryError(ValueError):
    """Malformed bounded input or an invalid fail-closed report."""


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


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _absolute(path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return Path(os.path.abspath(candidate))


def _read_bounded_json(path: Path | str, name: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Read only a small regular JSON file with no symlink following."""

    candidate = _absolute(path)
    descriptor: dict[str, Any] = {
        "path": str(candidate),
        "present": False,
        "opened": False,
        "bytes": None,
        "sha256": None,
        "schema": None,
    }
    try:
        before = os.lstat(candidate)
    except FileNotFoundError:
        return None, descriptor
    except OSError as error:
        descriptor["error"] = str(error)
        return None, descriptor
    descriptor["present"] = True
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        descriptor["error"] = "input must be a regular single-link file"
        return None, descriptor
    if before.st_size > MAX_JSON_BYTES:
        descriptor["error"] = f"input exceeds {MAX_JSON_BYTES} bytes"
        return None, descriptor
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as error:
        descriptor["error"] = str(error)
        return None, descriptor
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_nlink, opened.st_size) != (
            before.st_dev,
            before.st_ino,
            before.st_nlink,
            before.st_size,
        ):
            descriptor["error"] = "input changed during open"
            return None, descriptor
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_JSON_BYTES:
            chunk = os.read(fd, min(64 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_JSON_BYTES:
            descriptor["error"] = f"input exceeds {MAX_JSON_BYTES} bytes while reading"
            return None, descriptor
    except OSError as error:
        descriptor["error"] = str(error)
        return None, descriptor
    finally:
        os.close(fd)
    try:
        after = os.lstat(candidate)
    except OSError as error:
        descriptor["error"] = f"input disappeared after read: {error}"
        return None, descriptor
    if (after.st_dev, after.st_ino, after.st_nlink, after.st_size) != (
        before.st_dev,
        before.st_ino,
        before.st_nlink,
        before.st_size,
    ):
        descriptor["error"] = "input changed after read"
        return None, descriptor
    descriptor.update({"opened": True, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
        payload = dict(_mapping(payload, name))
    except (UnicodeError, json.JSONDecodeError, GapInventoryError) as error:
        descriptor["error"] = f"invalid JSON: {error}"
        return None, descriptor
    descriptor["schema"] = payload.get("schema")
    return payload, descriptor


def _source_descriptor(path: Path) -> dict[str, Any]:
    """Hash only bounded repository contract sources; do not execute them."""

    descriptor: dict[str, Any] = {"path": str(path), "present": False}
    try:
        info = os.lstat(path)
    except OSError as error:
        descriptor["error"] = str(error)
        return descriptor
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        descriptor["error"] = "contract source must be a regular single-link file"
        return descriptor
    if info.st_size < 1 or info.st_size > MAX_SOURCE_BYTES:
        descriptor["error"] = f"contract source exceeds {MAX_SOURCE_BYTES} bytes"
        return descriptor
    try:
        raw = path.read_bytes()
    except OSError as error:
        descriptor["error"] = str(error)
        return descriptor
    descriptor.update(
        {
            "present": True,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "mode": int(stat.S_IMODE(info.st_mode)),
            "uid": int(info.st_uid),
            "gid": int(info.st_gid),
            "nlink": int(info.st_nlink),
        }
    )
    return descriptor


def _input_summary(payload: Mapping[str, Any] | None, descriptor: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Keep only bounded, non-authorizing projections from an input report."""

    result: dict[str, Any] = {
        "source": dict(descriptor),
        "observed": payload is not None,
    }
    if payload is None:
        return result
    result.update(
        {
            "schema": payload.get("schema"),
            "status": payload.get("status"),
            "source_bound": payload.get("source_bound"),
            "diagnostic_only": payload.get("diagnostic_only"),
            "formal": payload.get("formal"),
            "credit": payload.get("credit"),
        }
    )
    if name == "manifest_identity":
        manifest = payload.get("manifest")
        if isinstance(manifest, Mapping):
            result["manifest"] = {
                "raw": dict(manifest.get("raw", {})) if isinstance(manifest.get("raw"), Mapping) else None,
                "canonical": dict(manifest.get("canonical", {}))
                if isinstance(manifest.get("canonical"), Mapping)
                else None,
            }
    elif name == "training_evidence":
        runs = payload.get("runs")
        if isinstance(runs, list):
            rows: list[dict[str, Any]] = []
            for row in runs:
                if not isinstance(row, Mapping) or row.get("seed") != SEED:
                    continue
                evidence = row.get("evidence")
                source = row.get("source")
                rows.append(
                    {
                        "seed": row.get("seed"),
                        "status": row.get("status"),
                        "run_id": evidence.get("run_id") if isinstance(evidence, Mapping) else None,
                        "model": evidence.get("model") if isinstance(evidence, Mapping) else None,
                        "hidden": evidence.get("hidden") if isinstance(evidence, Mapping) else None,
                        "updates": evidence.get("updates") if isinstance(evidence, Mapping) else None,
                        "training_receipt": dict(source) if isinstance(source, Mapping) else None,
                        "checkpoint": dict(evidence.get("checkpoint_identity", {}))
                        if isinstance(evidence, Mapping) and isinstance(evidence.get("checkpoint_identity"), Mapping)
                        else None,
                    }
                )
            result["seed17_rows"] = rows
    elif name == "terminal_evidence":
        rows = payload.get("seed_matrix")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, Mapping) and row.get("seed") == SEED:
                    result["seed17"] = {
                        "status": row.get("status"),
                        "blocked_reasons": list(row.get("blocked_reasons", []))
                        if isinstance(row.get("blocked_reasons"), list)
                        else [],
                        "evidence_present": isinstance(row.get("evidence"), Mapping),
                        "source_names": sorted(row.get("sources", {}).keys())
                        if isinstance(row.get("sources"), Mapping)
                        else [],
                    }
                    break
    elif name == "rollout_plan":
        result["seed17_projection"] = {
            key: payload.get(key)
            for key in (
                "seed",
                "run_id",
                "model",
                "hidden",
                "updates",
                "case_id",
                "split",
                "transitions",
                "frames",
                "mode",
                "launched",
                "gpu_index",
                "manifest_sha256",
                "manifest_file_sha256",
                "training_receipt_sha256",
                "output_namespace",
                "namespace_nonce",
                "command_sha256",
                "diagnostic_only",
                "formal",
                "formal_eligible",
                "credit",
            )
        }
    return result


def _zero_side_effects() -> dict[str, Any]:
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


def _binding_status(inputs: Mapping[str, Any]) -> dict[str, Any]:
    plan = inputs.get("rollout_plan", {}).get("seed17_projection", {})
    training_rows = inputs.get("training_evidence", {}).get("seed17_rows", [])
    training = training_rows[0] if training_rows else {}
    return {
        "nonce_declared": isinstance(plan.get("namespace_nonce"), str) and bool(plan.get("namespace_nonce")),
        "namespace_declared": isinstance(plan.get("output_namespace"), str) and bool(plan.get("output_namespace")),
        "plan_sha256_declared": False,
        "source_descriptor_declared": bool(training.get("training_receipt")) and bool(training.get("checkpoint")),
        "resource_snapshot_scheduler_owned": False,
        "gpu_identity_scheduler_attested": False,
        "external_signature_verified": False,
        "independent_consume_path_verified": False,
    }


def build_report(
    *,
    inputs: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed inventory without projecting or minting authority."""

    paths = dict(DEFAULT_INPUTS)
    if inputs is not None:
        paths.update({key: Path(value) for key, value in inputs.items()})
    input_summaries: dict[str, Any] = {}
    for name, path in paths.items():
        payload, descriptor = _read_bounded_json(path, f"{name} projection")
        input_summaries[name] = _input_summary(payload, descriptor, name)

    missing_inputs = [name for name, summary in input_summaries.items() if not summary.get("observed")]
    bindings = _binding_status(input_summaries)
    missing_requirements = [
        "external_scheduler_authority_document",
        "trusted_scheduler_ed25519_public_key",
        "scheduler_owned_resource_snapshot.gpu_uuid_pci_vram",
        "authority_bound_plan_sha256",
        "authority_bound_source_descriptors",
        "authority_bound_resource_snapshot",
        "authority_bound_gpu_identity",
        "authority_bound_consume_once_path",
        "current_mlp_seed17_authority_bound_admission_receipt",
        "independent_terminal_receipt_with_authority_binding",
    ]
    if missing_inputs:
        missing_requirements.extend(f"observed_projection:{name}" for name in missing_inputs)

    blockers = [
        "no real external scheduler authority document was supplied or verified",
        "no deployment-trusted Ed25519 public key or configured scheduler root is available for this MLP seed17 boundary",
        "the current nonce and namespace are producer/local declarations; they are not scheduler authority or namespace-inode attestation",
        "the rollout plan GPU index and local artifact hashes are not a scheduler-owned resource snapshot or GPU identity proof",
        "local JSON fields cannot reconstruct the missing plan/source/resource/consume-once bindings",
        "producer-issued current-schema authority-bound admission receipt and independently bound terminal receipt are required before any runner retry",
    ]
    if missing_inputs:
        blockers.append("one or more bounded current-manifest projections are unavailable; this inventory does not synthesize them")

    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "blocked_projection_gap",
        "scope": {
            "family": "F3",
            "model": MODEL,
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "seed": SEED,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "mode": "diagnostic_only",
        },
        "contract_sources": {key: _source_descriptor(path) for key, path in CONTRACT_SOURCE_PATHS.items()},
        "observed_inputs": input_summaries,
        "binding_status": bindings,
        "admission_contract": {
            "current_mlp_admission_module": None,
            "external_scheduler_authority_required": True,
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
            "local_projection_allowed": False,
            "durable_receipt_write_allowed": False,
        },
        "external_authority": {
            "path_supplied": False,
            "verified": False,
            "real_external_document_required": True,
            "signature_algorithm": "ed25519",
            "configured_scheduler_root": None,
            "configured_trusted_public_key": None,
            "caller_claim_can_substitute": False,
        },
        "resource_binding": {
            "supplied": False,
            "verified": False,
            "scheduler_owned_gpu_uuid_pci_required": True,
            "scheduler_owned_vram_snapshot_required": True,
            "implicit_probe_allowed": False,
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
        "missing_requirements": sorted(set(missing_requirements)),
        "blockers": list(dict.fromkeys(blockers)),
        "input_boundary": {
            "bounded_json_only": True,
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "trajectory_hdf5_opened": False,
            "scheduler_database_opened": False,
            "runtime_started": False,
            "queue_submissions": 0,
        },
        "side_effects": _zero_side_effects(),
        **ZERO_CREDIT,
    }


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        _exact(report, "schema", REPORT_SCHEMA, "report")
        _exact(report, "report_id", REPORT_ID, "report")
        _exact(report, "status", "blocked_projection_gap", "report")
        for key, expected in ZERO_CREDIT.items():
            _exact(report, key, expected, "report")
        scope = _mapping(report.get("scope"), "report.scope")
        for key, expected in {
            "family": "F3",
            "model": MODEL,
            "model_kind": MODEL,
            "hidden": HIDDEN,
            "seed": SEED,
            "split": SPLIT,
            "updates": UPDATES,
            "transitions": TRANSITIONS,
            "frames": FRAMES,
            "mode": "diagnostic_only",
        }.items():
            _exact(scope, key, expected, "report.scope")
        admission = _mapping(report.get("admission_contract"), "report.admission_contract")
        for key, expected in {
            "current_mlp_admission_module": None,
            "external_scheduler_authority_required": True,
            "signature_algorithm": "ed25519",
            "caller_claim_can_substitute": False,
            "implicit_resource_probe_allowed": False,
            "local_projection_allowed": False,
            "durable_receipt_write_allowed": False,
        }.items():
            _exact(admission, key, expected, "report.admission_contract")
        external = _mapping(report.get("external_authority"), "report.external_authority")
        for key, expected in {
            "path_supplied": False,
            "verified": False,
            "real_external_document_required": True,
            "signature_algorithm": "ed25519",
            "configured_scheduler_root": None,
            "configured_trusted_public_key": None,
            "caller_claim_can_substitute": False,
        }.items():
            _exact(external, key, expected, "report.external_authority")
        resource = _mapping(report.get("resource_binding"), "report.resource_binding")
        for key, expected in {
            "supplied": False,
            "verified": False,
            "scheduler_owned_gpu_uuid_pci_required": True,
            "scheduler_owned_vram_snapshot_required": True,
            "implicit_probe_allowed": False,
        }.items():
            _exact(resource, key, expected, "report.resource_binding")
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
        missing = report.get("missing_requirements")
        if not isinstance(missing, list) or not missing or any(not isinstance(item, str) for item in missing):
            _fail("report.missing_requirements must be a non-empty string list")
        blockers = report.get("blockers")
        if not isinstance(blockers, list) or not blockers or any(not isinstance(item, str) for item in blockers):
            _fail("report.blockers must be a non-empty string list")
        effects = _mapping(report.get("side_effects"), "report.side_effects")
        for key, expected in _zero_side_effects().items():
            _exact(effects, key, expected, "report.side_effects")
        boundary = _mapping(report.get("input_boundary"), "report.input_boundary")
        for key, expected in {
            "bounded_json_only": True,
            "checkpoint_content_opened": False,
            "evaluation_content_opened": False,
            "trajectory_hdf5_opened": False,
            "scheduler_database_opened": False,
            "runtime_started": False,
            "queue_submissions": 0,
        }.items():
            _exact(boundary, key, expected, "report.input_boundary")
        sources = _mapping(report.get("contract_sources"), "report.contract_sources")
        if set(sources) != set(CONTRACT_SOURCE_PATHS):
            _fail("report.contract_sources must contain only the MLP hidden16 contract sources")
        for key, item in sources.items():
            source = _mapping(item, f"report.contract_sources.{key}")
            path = source.get("path")
            if not isinstance(path, str) or "f3_mlp_hidden16" not in path and "f3_mlp_hidden16" not in Path(path).name:
                _fail(f"report.contract_sources.{key} is outside the MLP hidden16 scope")
            if "graph_raw" in path or "graph_residual" in path:
                _fail(f"report.contract_sources.{key} crosses another model scope")
    except (GapInventoryError, TypeError, ValueError, KeyError) as error:
        errors.append(str(error))
    return errors


def render_markdown(report: Mapping[str, Any]) -> str:
    scope = report.get("scope", {})
    bindings = report.get("binding_status", {})
    external = report.get("external_authority", {})
    projection = report.get("projection_contract", {})
    lines = [
        "# F3 MLP hidden16 seed17 authority projection gap",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 范围：`{scope.get('model')}/hidden{scope.get('hidden')}/seed{scope.get('seed')}/{scope.get('split')}/{scope.get('updates')} updates/{scope.get('transitions')} transitions/{scope.get('frames')} frames`",
        f"- 外部 scheduler authority：`verified={external.get('verified')}`；签名算法要求 `Ed25519`",
        f"- scheduler-owned resource/GPU binding：`{bindings.get('resource_snapshot_scheduler_owned')}/{bindings.get('gpu_identity_scheduler_attested')}`",
        f"- producer/local nonce：`{bindings.get('nonce_declared')}`；namespace：`{bindings.get('namespace_declared')}`（二者不等于 authority）",
        f"- safe local projection：`{projection.get('safe_local_projection_implemented')}`；producer reissue required：`{projection.get('producer_reissue_required')}`",
        f"- credit：`{report.get('credit')}`",
        "",
        "## 缺失准入条件",
        "",
    ]
    lines.extend(f"- `{item}`" for item in report.get("missing_requirements", []))
    lines.extend(["", "## 阻塞原因", ""])
    lines.extend(f"- {item}" for item in report.get("blockers", []))
    lines.extend(
        [
            "",
            "本报告只记录 MLP seed17 的 bounded projection gap；不把本地 GPU index、nonce、namespace、artifact hash 或历史 JSON 字段升级为 scheduler authority。",
            "",
            "本轮未启动 Popen/solver/worker/GPU/queue，未读取 checkpoint、evaluation、trajectory/HDF5 内容，未写入 registry、ledger、denominator、gate、completion 或历史 receipt。",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-identity", type=Path, default=DEFAULT_INPUTS["manifest_identity"])
    parser.add_argument("--training-evidence", type=Path, default=DEFAULT_INPUTS["training_evidence"])
    parser.add_argument("--terminal-evidence", type=Path, default=DEFAULT_INPUTS["terminal_evidence"])
    parser.add_argument("--rollout-plan", type=Path, default=DEFAULT_INPUTS["rollout_plan"])
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--verify-report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verify_report is not None:
        report, _descriptor = _read_bounded_json(args.verify_report, "gap report")
        if report is None:
            print("fail-closed: gap report is unavailable", file=sys.stderr)
            return 2
        errors = validate_report(report)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
        return 0

    report = build_report(
        inputs={
            "manifest_identity": args.manifest_identity,
            "training_evidence": args.training_evidence,
            "terminal_evidence": args.terminal_evidence,
            "rollout_plan": args.rollout_plan,
        }
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
    # A blocked gap is a valid diagnostic result but is intentionally a
    # non-zero CLI status so callers cannot mistake it for an admission.
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
