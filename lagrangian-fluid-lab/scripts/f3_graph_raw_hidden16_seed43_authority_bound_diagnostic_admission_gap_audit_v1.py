#!/usr/bin/env python3
"""Bounded gap audit for the existing seed43 authority-bound admission.

The seed43 admission implementation already contains the requested contract:
current-manifest binding, an externally supplied Ed25519 authority, nonce and
namespace inode binding, source/resource/plan digests, and zero-credit
diagnostic-only output.  This audit deliberately does not duplicate that
implementation.  It inspects only small source/test files and filesystem
metadata for the deployment trust paths, then emits the exact remaining gap.

It never opens the current manifest, training receipt, checkpoint, trajectory,
or any other production artifact.  It never probes a GPU, starts a process, or
writes scheduler/Core state.  The report is therefore an admission-gap
artifact, not an authority receipt and not a launch authorization.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable, Mapping
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
ADMISSION_SOURCE = (
    LAB_ROOT / "scripts" / "f3_graph_raw_hidden16_seed43_diagnostic_admission_v1.py"
)
ADMISSION_TEST = (
    LAB_ROOT / "tests" / "test_f3_graph_raw_hidden16_seed43_diagnostic_admission_v1.py"
)
CURRENT_MANIFEST = LAB_ROOT / "campaigns" / "core-v1" / "f3-dataset-v2.json"
TRUSTED_SCHEDULER_PUBLIC_KEY = Path("/etc/dual-sph/scheduler-ed25519-public.key")
EXTERNAL_SCHEDULER_ROOT = Path("/var/lib/dual-sph/f3-seed43-scheduler")

SCHEMA = "core.f3.graph_raw.hidden16.seed43.authority_bound_diagnostic_admission_gap.v1"
REPORT_SCHEMA = f"{SCHEMA}.report"
REPORT_ID = "f3-graph-raw-hidden16-seed43-authority-bound-diagnostic-admission-gap-2026-09-29"
DEFAULT_REPORT = (
    LAB_ROOT
    / "reports"
    / "F3-GRAPH-RAW-HIDDEN16-SEED43-AUTHORITY-BOUND-DIAGNOSTIC-ADMISSION-GAP-AUDIT-2026-09-29.json"
)
DEFAULT_MARKDOWN = DEFAULT_REPORT.with_suffix(".zh-CN.md")

MAX_SOURCE_BYTES = 256 * 1024
MAX_TEST_BYTES = 256 * 1024

REQUIRED_FUNCTIONS = {
    "mint_admission",
    "_validate_external_authority",
    "_read_trusted_scheduler_key",
    "_authority_signing_message",
    "_validate_external_claim",
    "consume_receipt",
    "_source_descriptor",
    "_validate_resource",
}

REQUIRED_MARKERS = {
    "current_manifest": "f3-dataset-v2.json",
    "seed_binding": "SEED = 43",
    "ed25519_verifier": "Ed25519PublicKey",
    "ed25519_signature": '"ed25519"',
    "external_authority_schema": "EXTERNAL_AUTHORITY_SCHEMA",
    "nonce_binding": "nonce",
    "namespace_binding": "namespace_descriptor",
    "source_binding": '"source_sha256"',
    "resource_binding": '"resource_snapshot_sha256"',
    "plan_binding": '"plan_sha256"',
    "self_claim_rejection": "local receipt fields are not authority",
    "external_authority_required": "external scheduler authority is required",
    "zero_credit": '"qualification_credit": 0',
    "popen_false": '"receipt_authorizes_popen": False',
}

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


class AuditError(ValueError):
    """Malformed audit input or an unsafe audit target."""


def _absolute(path: Path | str, name: str) -> Path:
    candidate = Path(os.fspath(path))
    if not candidate.is_absolute() or any(part in {".", ".."} for part in candidate.parts):
        raise AuditError(f"{name} must be an absolute lexical path")
    if Path(os.path.normpath(str(candidate))) != candidate:
        raise AuditError(f"{name} contains a lexical alias")
    return candidate


def _read_small(path: Path | str, *, max_bytes: int, name: str) -> bytes:
    candidate = _absolute(path, name)
    try:
        info = os.lstat(candidate)
    except OSError as error:
        raise AuditError(f"cannot inspect {name}: {error}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AuditError(f"{name} must be a regular non-symlink file")
    if info.st_size > max_bytes:
        raise AuditError(f"{name} exceeds the bounded audit read limit")
    try:
        with candidate.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as error:
        raise AuditError(f"cannot read {name}: {error}") from error
    if len(raw) > max_bytes:
        raise AuditError(f"{name} grew beyond the bounded audit read limit")
    return raw


def _metadata(path: Path | str, name: str) -> dict[str, Any]:
    """Collect metadata only; never opens the target."""

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
    }


def _bounded_children(root: Path | str, suffix: str) -> list[dict[str, Any]]:
    """List matching names and lstat metadata without opening any child."""

    candidate = _absolute(root, "external scheduler root")
    try:
        root_info = os.lstat(candidate)
    except (FileNotFoundError, OSError):
        return []
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
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
                    }
                )
    except OSError:
        return []
    return sorted(children, key=lambda item: str(item["name"]))


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
        function = node.func
        if isinstance(function, ast.Name):
            names.append(function.id)
        elif isinstance(function, ast.Attribute):
            names.append(function.attr)
    return names


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _source_observation(path: Path, *, max_bytes: int, name: str) -> tuple[str, ast.Module, dict[str, Any]]:
    raw = _read_small(path, max_bytes=max_bytes, name=name)
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=str(path))
    except (UnicodeDecodeError, SyntaxError) as error:
        raise AuditError(f"{name} is not parseable UTF-8 Python: {error}") from error
    return (
        _hash(raw),
        tree,
        {"path": str(path), "bytes": len(raw), "sha256": _hash(raw)},
    )


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
    admission_source: Path | str = ADMISSION_SOURCE,
    admission_test: Path | str = ADMISSION_TEST,
    current_manifest: Path | str = CURRENT_MANIFEST,
    trusted_scheduler_public_key: Path | str = TRUSTED_SCHEDULER_PUBLIC_KEY,
    external_scheduler_root: Path | str = EXTERNAL_SCHEDULER_ROOT,
) -> dict[str, Any]:
    admission_path = _absolute(admission_source, "seed43 admission source")
    test_path = _absolute(admission_test, "seed43 admission test")
    manifest_path = _absolute(current_manifest, "current manifest")
    key_path = _absolute(trusted_scheduler_public_key, "trusted scheduler public key")
    scheduler_root = _absolute(external_scheduler_root, "external scheduler root")

    admission_hash, tree, admission_file = _source_observation(
        admission_path,
        max_bytes=MAX_SOURCE_BYTES,
        name="seed43 admission source",
    )
    test_hash, _test_tree, test_file = _source_observation(
        test_path,
        max_bytes=MAX_TEST_BYTES,
        name="seed43 admission test",
    )
    source_text = _read_small(
        admission_path,
        max_bytes=MAX_SOURCE_BYTES,
        name="seed43 admission source",
    ).decode("utf-8")
    test_text = _read_small(
        test_path,
        max_bytes=MAX_TEST_BYTES,
        name="seed43 admission test",
    ).decode("utf-8")
    functions = _function_names(tree)
    imports = _import_roots(tree)
    calls = _call_names(tree)
    forbidden_imports = sorted(imports & FORBIDDEN_IMPORT_ROOTS)
    forbidden_calls = sorted(set(calls) & FORBIDDEN_CALL_NAMES)

    marker_results = {
        key: marker in source_text for key, marker in REQUIRED_MARKERS.items()
    }
    coverage = {
        "current_manifest_binding": marker_results["current_manifest"],
        "graph_raw_hidden16_seed43_identity": marker_results["seed_binding"]
        and "graph_raw" in source_text
        and "HIDDEN" in source_text,
        "external_scheduler_authority_input": "external_authority" in source_text
        and "EXTERNAL_SCHEDULER_ROOT" in source_text,
        "ed25519_signature_verification": marker_results["ed25519_verifier"]
        and marker_results["ed25519_signature"]
        and "verify(" in source_text,
        "nonce_binding": marker_results["nonce_binding"],
        "namespace_inode_binding": marker_results["namespace_binding"]
        and "dev" in source_text
        and "ino" in source_text,
        "source_digest_binding": marker_results["source_binding"],
        "resource_digest_binding": marker_results["resource_binding"],
        "plan_digest_binding": marker_results["plan_binding"],
        "caller_self_claim_rejected": marker_results["self_claim_rejection"]
        and marker_results["external_authority_required"],
        "one_shot_claim_validation": "_validate_external_claim" in functions
        and "consume_receipt" in functions
        and "EXTERNAL_CLAIM_SCHEMA" in source_text,
        "zero_credit_diagnostic_boundary": marker_results["zero_credit"]
        and marker_results["popen_false"]
        and '"launch_allowed": False' in source_text,
        "admission_module_has_no_process_launch_surface": not forbidden_imports
        and not forbidden_calls,
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
                "F3-S43-AUTH-ROOT-001",
                "生产 scheduler trust root 不可用",
                "trusted Ed25519 public key 或 external scheduler root 未同时提供",
                "无法把任何 caller-supplied authority document 认证为真实 external scheduler authority",
                "由部署外部安装 owner-only 32-byte Ed25519 public key 与受保护 scheduler root，并提供其 inode/权限证明",
            )
        )
    if not authority_document_available:
        gaps.append(
            _gap(
                "F3-S43-AUTH-DOC-002",
                "真实 signed authority document 未提供",
                "没有可验证的 seed43 issued one-shot authority document",
                "nonce、namespace inode、plan/source/resource/GPU binding 尚未获得真实 scheduler 签名见证",
                "由 external scheduler 签发当前 manifest seed43 authority，并由 admission 以 Ed25519 验签后留存不可变 digest",
            )
        )
    if not claim_available:
        gaps.append(
            _gap(
                "F3-S43-AUTH-CLAIM-003",
                "独立 one-shot consume claim 未提供",
                "scheduler consume_path 下没有 durable consumed claim witness",
                "不能证明 authority reservation 未被其他 consumer 使用，也不能完成一次性消费闭环",
                "提供与 authority_id、document digest、receipt/identity digest、nonce、namespace descriptor 交叉绑定的外部 claim",
            )
        )
    gaps.append(
        _gap(
            "F3-S43-AUTH-VERIFY-004",
            "本次 gap audit 不执行生产 authority 验签",
            "本审计只读小型 source/test 与 trust-path metadata，不接收或重放生产 authority",
            "synthetic pytest fixture 不能升级为生产 authority；launch 和 credit 必须继续关闭",
            "在真实 scheduler authority、key、namespace、resource snapshot 同时存在后，由受控 admission 重新完成签名/文件/消费验证并生成 terminal evidence",
        )
    )

    status = "blocked_fail_closed"
    if production_key_available and production_root_available and authority_document_available and claim_available:
        status = "blocked_static_unverified"

    return {
        "schema": REPORT_SCHEMA,
        "report_id": REPORT_ID,
        "contract_date": "2026-09-29",
        "status": status,
        "audit_mode": "bounded_seed43_authority_gap_only",
        "requested_agent_policy": {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "max",
            "actual_subagent_invoked": False,
            "reason": "the current tool surface exposed no callable spawn_agent interface",
        },
        "scope": {
            "family": "F3",
            "model_kind": "graph_raw",
            "hidden": 16,
            "seed": 43,
            "current_manifest": str(manifest_path),
            "existing_admission": str(admission_path),
            "existing_regression": str(test_path),
            "shared_files_modified": False,
            "historical_receipts_modified": False,
        },
        "implementation_coverage": coverage,
        "implementation_evidence": {
            "admission_source": admission_file,
            "admission_source_sha256": admission_hash,
            "admission_test": test_file,
            "admission_test_sha256": test_hash,
            "required_functions_present": sorted(REQUIRED_FUNCTIONS - functions) == [],
            "missing_functions": sorted(REQUIRED_FUNCTIONS - functions),
            "required_markers": marker_results,
            "forbidden_imports": forbidden_imports,
            "forbidden_call_names": forbidden_calls,
            "synthetic_scheduler_fixture_is_not_production": "synthetic" in test_text,
        },
        "production_observation": {
            "current_manifest_metadata_only": manifest_metadata,
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
        "exact_gaps": gaps,
        "readiness": {
            "diagnostic_only": True,
            "launch_allowed": False,
            "popen_attempted": False,
            "solver_started": False,
            "worker_started": False,
            "queue_submitted": False,
            "gpu_execution_observed": False,
            "formal": False,
            "credit": 0,
        },
        "side_effects": {
            "source_files_read": 2,
            "current_manifest_bytes_opened": 0,
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
        },
        "write_set": [
            str(DEFAULT_REPORT.relative_to(LAB_ROOT)),
            str(DEFAULT_MARKDOWN.relative_to(LAB_ROOT)),
        ],
    }


def _json_text(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _markdown(report: Mapping[str, Any]) -> str:
    coverage = report["implementation_coverage"]
    gaps = report["exact_gaps"]
    observation = report["production_observation"]
    lines = [
        "# F3 graph_raw hidden16 seed43 authority-bound diagnostic admission gap audit",
        "",
        f"状态：`{report['status']}`。这是 gap artifact，不是 scheduler receipt。",
        "",
        "现有 seed43 admission 已覆盖的契约：",
        "",
    ]
    lines.extend(
        f"- `{key}`：`{'covered' if value else 'missing'}`"
        for key, value in sorted(coverage.items())
    )
    lines.extend(
        [
            "",
            "生产 authority 观察（只读 metadata，未打开 manifest/training/checkpoint/trajectory）：",
            "",
            f"- trusted key available：`{observation['production_key_available']}`",
            f"- scheduler root available：`{observation['production_scheduler_root_available']}`",
            f"- signed authority document available：`{observation['authority_document_available']}`",
            f"- independent one-shot claim available：`{observation['one_shot_claim_available']}`",
            "- production authority verified：`False`",
            "",
            "精确剩余缺口：",
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
            "安全边界：未调用 Popen/solver/worker/GPU/queue，未读取生产大文件，未写 registry、ledger、denominator、gate、completion 或 PLAN；`launch_allowed=false`、`formal=false`、`credit=0`。",
            "",
            "pytest synthetic authority fixture 仅证明 fail-closed contract，不构成生产 scheduler authority。",
        ]
    )
    return "\n".join(lines) + "\n"


def _output_path(value: Path | str, expected_suffix: str, name: str) -> Path:
    path = _absolute(value, name)
    if path.suffix != expected_suffix or "SEED43" not in path.name.upper():
        raise AuditError(f"{name} must be a seed43 report path with suffix {expected_suffix}")
    if not path.parent.exists() or not path.parent.is_dir():
        raise AuditError(f"{name} parent must already exist")
    return path


def write_reports(
    report: Mapping[str, Any],
    *,
    report_path: Path | str = DEFAULT_REPORT,
    markdown_path: Path | str = DEFAULT_MARKDOWN,
) -> tuple[Path, Path]:
    json_path = _output_path(report_path, ".json", "JSON report")
    md_path = _output_path(markdown_path, ".md", "Markdown report")
    json_path.write_text(_json_text(report), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, md_path


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        report = audit()
        write_reports(
            report,
            report_path=args.report_output,
            markdown_path=args.markdown_output,
        )
    except AuditError as error:
        print(f"blocked_fail_closed: {error}")
        return 2
    print(json.dumps({"status": report["status"], "credit": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
